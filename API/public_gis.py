"""Parcel-aware public environmental screening and MassGIS lidar sampling."""

import json
import math
import re
from urllib.parse import urlencode

from ._http import get_json

LIDAR = "https://arcgisserver.digital.mass.gov/arcgisserver/rest/services/LiDAR/DEM_lidar_2013to2021_32bitFloat/ImageServer"
LAYERS = {
    "wetlands": "https://services1.arcgis.com/hGdibHYSPO59RG1h/ArcGIS/rest/services/DEP_Wetlands/FeatureServer/1",
    "environmental": "https://arcgisserver.digital.mass.gov/arcgisserver/rest/services/AGOL/C21e/FeatureServer/0",
    "activity_use_limits": "https://arcgisserver.digital.mass.gov/arcgisserver/rest/services/AGOL/AUL_Sites/FeatureServer/0",
    "protected_habitat": "https://arcgisserver.digital.mass.gov/arcgisserver/rest/services/AGOL/NHESP_Priority_Habitats/FeatureServer/0",
}


def parcel_extent(context, latitude, longitude):
    records = context.get("parcels", {}).get("records", [])
    points = [
        p
        for r in records
        for ring in r.get("geometry", {}).get("rings", [])
        for p in ring
    ]
    if points:
        return [
            min(p[0] for p in points),
            min(p[1] for p in points),
            max(p[0] for p in points),
            max(p[1] for p in points),
        ]
    # A small, explicitly labeled search envelope when no parcel was returned.
    return [
        longitude - 0.0005,
        latitude - 0.0005,
        longitude + 0.0005,
        latitude + 0.0005,
    ]


def screen(session, source, latitude, longitude, context):
    parcels = context.get("parcels", {}).get("records", [])
    geometry = parcels[0].get("geometry") if len(parcels) == 1 else None
    geometry = geometry or {
        "x": longitude,
        "y": latitude,
        "spatialReference": {"wkid": 4326},
    }
    polygon = "rings" in geometry
    params = {
        "f": "json",
        "where": "1=1",
        "outFields": "*",
        "geometry": json.dumps(geometry),
        "geometryType": "esriGeometryPolygon" if polygon else "esriGeometryPoint",
        "inSR": 4326,
        "outSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "returnGeometry": "true",
        "resultRecordCount": 100,
    }
    if source in ("environmental", "activity_use_limits"):
        params.update(distance=250, units="esriSRUnit_Meter")
    payload = get_json(session, LAYERS[source] + "/query", params, method="POST")
    records = [
        {
            **f["attributes"],
            "geometry": f.get("geometry", {}),
            "screening_scope": "parcel plus 250m"
            if source in ("environmental", "activity_use_limits") and polygon
            else "parcel intersection"
            if polygon
            else "point screening",
            "match_method": "parcel_buffer_candidate"
            if source in ("environmental", "activity_use_limits") and polygon
            else "parcel_intersection"
            if polygon
            else "point_intersection",
        }
        for f in payload.get("features", [])
    ]
    return {
        "records": records,
        "query": params,
        "query_method": "POST",
        "query_url": LAYERS[source] + "?f=pjson",
        "truncated": bool(payload.get("exceededTransferLimit")),
        "screening_extent": parcel_extent(context, latitude, longitude),
        "limitations": "An empty result does not establish absence of wetlands, contamination or regulatory constraints. Environmental layers are published subsets.",
    }


def lidar(session, latitude, longitude, context):
    extent = parcel_extent(context, latitude, longitude)
    points = [
        (longitude, latitude),
        *[
            (x, y)
            for x in (extent[0], (extent[0] + extent[2]) / 2, extent[2])
            for y in (extent[1], (extent[1] + extent[3]) / 2, extent[3])
        ],
    ]
    params = {
        "f": "json",
        "geometry": json.dumps({"points": points, "spatialReference": {"wkid": 4326}}),
        "geometryType": "esriGeometryMultipoint",
        "returnFirstValueOnly": "true",
        "outFields": "*",
    }
    payload = get_json(session, LIDAR + "/getSamples", params)
    records = []
    for sample in payload.get("samples", []):
        raw = sample.get("value", "")
        try:
            value = float(re.split(r"[,\s]+", str(raw).strip())[0])
        except ValueError:
            continue
        if not math.isfinite(value):
            continue
        location = sample.get("location", {})
        if location.get("spatialReference", {}).get("wkid") in (3857, 102100):
            x = location["x"] / 20037508.342789244 * 180
            y = math.degrees(
                2 * math.atan(math.exp(location["y"] / 6378137)) - math.pi / 2
            )
        else:
            x, y = location.get("x"), location.get("y")
        records.append(
            {
                "elevation_m": value,
                "vertical_datum": "NAVD88",
                "latitude": y,
                "longitude": x,
                "source_date": "2013–2021",
                "source_date_basis": "MassGIS mosaic acquisition range; individual flight date not established",
                "match_method": "lidar_sample",
                "sample_scope": "requested point and parcel bounding-envelope grid; not a foundation survey",
            }
        )
    bounds = ",".join(map(str, extent))
    raster = {
        "url": LIDAR
        + "/exportImage?"
        + urlencode(
            {
                "f": "image",
                "bbox": bounds,
                "bboxSR": 4326,
                "imageSR": 4326,
                "size": "512,512",
                "format": "tiff",
                "pixelType": "F32",
                "noDataInterpretation": "esriNoDataMatchAny",
            }
        ),
        "title": "MassGIS lidar DEM — parcel envelope raster",
        "kind": "lidar_raster",
    }
    return {
        "records": records,
        "query": params,
        "query_url": LIDAR + "/getSamples?" + urlencode(params),
        "truncated": False,
        "documents": [raster],
        "extent_wgs84": extent,
        "summary": {
            "min_sample_elevation_m": min(
                (r["elevation_m"] for r in records), default=None
            ),
            "max_sample_elevation_m": max(
                (r["elevation_m"] for r in records), default=None
            ),
        },
        "limitations": "Grid samples are not whole-parcel extrema; acquisition dates vary across the statewide mosaic.",
    }


def imagery_tiles(context, latitude, longitude, *, max_tiles=9):
    """Cover the full parcel envelope by reducing zoom instead of truncating tiles."""
    bbox = parcel_extent(context, latitude, longitude)

    def tile(x, y, z):
        return int((x + 180) / 360 * 2**z), int(
            (1 - math.asinh(math.tan(math.radians(y))) / math.pi) / 2 * 2**z
        )

    zoom = 19
    while True:
        x1, y1 = tile(bbox[0], bbox[3], zoom)
        x2, y2 = tile(bbox[2], bbox[1], zoom)
        if (x2 - x1 + 1) * (y2 - y1 + 1) <= max_tiles or zoom == 0:
            break
        zoom -= 1
    return zoom, [(x, y) for x in range(x1, x2 + 1) for y in range(y1, y2 + 1)], bbox
