"""Small coordinate queries against public Massachusetts data services.

Provider attributes are kept intact. Spatial matches identify published
features, not a customer's meter or an engineer-approved installation.
"""

import json
from functools import lru_cache
from pathlib import Path

import fastexcel
import polars as pl
import requests

from ._http import get_json
from .site_sources import KBTU_PER_KWH, MA_LAYERS, SiteDataClient, _download

SOURCES = {
    "utilities": {
        "url": "https://arcgisserver.digital.mass.gov/arcgisserver/rest/services/AGOL/ElectricityProviders/MapServer/0",
        "description": "Municipality and its published electric providers. Confirm the actual provider on a bill.",
        "data_kind": "published_utility_territory", "match_method": "municipality_containing_point",
        "fields": "TOWN,TOWN_ID,ELEC", "geometry": False,
    },
    "parcels": {
        "url": "https://services1.arcgis.com/hGdibHYSPO59RG1h/arcgis/rest/services/Massachusetts_Property_Tax_Parcels/FeatureServer/0",
        "description": "Containing assessor parcels, owner, address, use, area, zoning and recorded deed references.",
        "data_kind": "reported_assessor", "match_method": "point_intersection", "geometry": True,
    },
    "buildings": {
        "url": "https://services1.arcgis.com/hGdibHYSPO59RG1h/ArcGIS/rest/services/Building_Structures/FeatureServer/0",
        "description": "Mapped roof/building outline intersecting the point. Area is not gross floor area or usable battery space.",
        "data_kind": "published_geometry", "match_method": "point_intersection", "geometry": True,
    },
    "lber": {
        "url": MA_LAYERS[2025],
        "description": "Up to five 2025 annual disclosures within 250 m. Candidates require a building/reporting-boundary match.",
        "data_kind": "reported", "match_method": "within_250m_candidate", "radius_m": 250,
        "geometry": True,
    },
    "flood": {
        "url": "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28",
        "description": "FEMA flood-zone polygons at the point. No returned feature does not establish absence of flood risk.",
        "data_kind": "published_hazard", "match_method": "point_intersection",
        "fields": "FLD_ZONE,ZONE_SUBTY,SFHA_TF,DFIRM_ID", "geometry": False,
    },
    "tariffs": {
        "url": "https://api.openei.org/utility_rates",
        "description": "Commercial tariff candidates near the coordinates. Review utility, eligibility and effective dates.",
        "data_kind": "published_tariff", "match_method": "provider_location_candidates",
    },
    "solar": {
        "url": "https://www.masscec.com/sites/default/files/documents/Solar-PV-Systems-in-MA-as-of-Jan-2025.xlsx",
        "description": "January 2025 PTS municipal solar context. This public workbook has no site addresses or coordinates.",
        "data_kind": "reported_municipal_context", "match_method": "municipality_only",
    },
    "elevation": {
        "url": "https://api.open-meteo.com/v1/elevation",
        "description": "Terrain elevation in meters. It does not establish finished floor, pad elevation or ground conditions.",
        "data_kind": "modeled_terrain", "match_method": "coordinate_sample",
    },
}

# These sources need a human/site-specific document selection, not another
# point query. They are returned separately with honest access statuses.
REFERENCES = {
    "land_records": {
        "status": "manual_lookup", "url": "https://www.masslandrecords.com/",
        "description": "Search the appropriate registry using the parcel's recorded book/page and owner. No deed or survey is downloaded automatically.",
    },
    "permits": {
        "status": "manual_lookup", "url": None,
        "description": "Municipal portals vary. Search the returned address/parcel for plans and later alterations. No blueprints have been retrieved or interpreted.",
    },
    "tariff_documents": {
        "status": "reference_only", "url": "https://www.mass.gov/info-details/massachusetts-electric-rates-and-tariffs",
        "description": "Official tariff directory. Match the customer's bill to the applicable utility schedule and dates.",
    },
    "requirements": {
        "status": "reference_only", "url": "https://www.mass.gov/regulations/780-CMR-tenth-edition-table-of-contents",
        "description": "Identify current building, fire, electrical and municipal submission requirements. This API performs no code-compliance review.",
        "additional_urls": ["https://www.mass.gov/info-details/massachusetts-fire-code", "https://www.mass.gov/info-details/massachusetts-electrical-code"],
    },
    "bills": {
        "status": "authorization_required", "url": "https://www.eqore.com/guides/interval-data",
        "description": "Obtain twelve bills for each relevant account from the customer. Private bills cannot be retrieved from coordinates.",
    },
    "interval_data": {
        "status": "authorization_required", "url": "https://www.eqore.com/guides/interval-data",
        "description": "Obtain customer-authorized meter exports. Existing Green Button parsing is available through SiteDataClient.green_button(path).",
    },
    "comstock": {
        "status": "selection_required", "url": "https://natlabrockies.github.io/ComStock.github.io/docs/data.html",
        "description": "Select an appropriate modeled archetype explicitly. A ComStock ID cannot be assigned to a real facility from coordinates alone.",
    },
}

MUNICIPAL_PORTALS = {
    "HOLLISTON": "https://www.townofholliston.us/187/Building",
    "NEWTON": "https://www.newtonma.gov/government/inspectional-services",
    "NORTHAMPTON": "https://www.northamptonma.gov/266/Laserfiche-Program",
    "CAMBRIDGE": "https://www.cambridgema.gov/en/iwantto/applyforabuildingpermit",
    "BOSTON": "https://www.boston.gov/departments/inspectional-services",
}


def query_point(session, source, latitude, longitude):
    """Bounded ArcGIS point queries, with all geometries returned in WGS84.

    A short list of candidates is intentional. truncated is exposed rather
    than silently claiming the complete set was retrieved.
    """
    config = SOURCES[source]
    params = {
        "f": "json", "where": "1=1", "outFields": config.get("fields", "*"),
        "geometry": json.dumps({"x": longitude, "y": latitude, "spatialReference": {"wkid": 4326}}),
        "geometryType": "esriGeometryPoint", "inSR": 4326, "outSR": 4326,
        "spatialRel": "esriSpatialRelIntersects", "resultRecordCount": 5,
        "returnGeometry": str(config["geometry"]).lower(),
    }
    if config.get("radius_m"):
        params.update(distance=config["radius_m"], units="esriSRUnit_Meter")
    payload = get_json(session, config["url"] + "/query", params)
    return {
        "records": [{**feature["attributes"], **({"geometry": feature["geometry"]} if feature.get("geometry") else {})}
                    for feature in payload["features"]],
        "truncated": bool(payload.get("exceededTransferLimit")),
        "query": params,
    }


@lru_cache(maxsize=2)
def _solar_table(path, modified_time):
    """Parse this 13 MB public workbook once per downloaded version."""
    return fastexcel.read_excel(path).load_sheet(0, header_row=10, schema_sample_rows=None).to_polars()


def fetch_source(source, latitude, longitude, *, municipality=None, cache_dir="data/raw", refresh=False):
    """One provider per call, using its own session so calls can run concurrently."""
    with requests.Session() as session:
        if source not in ("tariffs", "solar", "elevation"):
            result = query_point(session, source, latitude, longitude)
            if source == "lber" and result["records"]:
                frame = pl.from_dicts(result["records"], infer_schema_length=None).with_columns(
                    building_id=pl.col("UBID"), address=pl.col("Street_Address"), city=pl.col("City"),
                    floor_area_sqft=pl.col("Gross_Floor_Area").cast(pl.Float64, strict=False),
                    annual_electricity_kwh=pl.col("Total_Electricity_Use_Purchased_From_Grid_kBtu").cast(pl.Float64, strict=False) / KBTU_PER_KWH,
                    data_year=pl.lit(2025),
                )
                result["records"] = json.loads(frame.write_json())
            return result
        if source == "tariffs":
            frame = SiteDataClient(session=session).tariffs(latitude, longitude, limit=2)
            records = json.loads(frame.write_json())
            for record in records:
                record["rate"] = json.loads(record.pop("rate_json"))
            return {"records": records, "truncated": len(records) >= 2,
                    "query": {"latitude": latitude, "longitude": longitude, "limit": 2}}
        if source == "elevation":
            payload = get_json(session, SOURCES[source]["url"], {"latitude": latitude, "longitude": longitude})
            return {"records": [{"elevation_m": payload["elevation"][0]}], "truncated": False,
                    "query": {"latitude": latitude, "longitude": longitude}}
        if not municipality:
            return {"status": "blocked", "records": [], "detail": "Municipality could not be resolved.", "truncated": False}
        path = _download(session, SOURCES[source]["url"], Path(cache_dir), refresh=refresh)
        table = _solar_table(str(path), path.stat().st_mtime)
        local = table.filter(pl.col("City").str.to_uppercase() == municipality.upper())
        return {
            "records": json.loads(local.head(5).write_json()), "total_municipal_records": local.height,
            "truncated": local.height > 5, "data_as_of": "2025-01-14",
            "downloaded_at_epoch": path.stat().st_mtime,
            "query": {"municipality": municipality, "limit": 5},
        }
