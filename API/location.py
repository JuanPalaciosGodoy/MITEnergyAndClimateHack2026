"""Locations describe source records separately from the searched coordinate."""

import math

LOCATION_COLUMNS = ["searched_latitude", "searched_longitude", "source_latitude", "source_longitude",
                    "source_distance_m", "source_location_basis", "match_method"]


def location_metadata(latitude, longitude, source_latitude=None, source_longitude=None, *, basis="Source location not supplied", match_method="unknown"):
    """Keep unknown locations null; distance is to the representative source point."""
    distance = None
    if source_latitude is None or source_longitude is None:
        source_latitude = source_longitude = None
    if source_latitude is not None and source_longitude is not None:
        try:
            source_latitude, source_longitude = float(source_latitude), float(source_longitude)
        except (ValueError, TypeError):
            source_latitude = source_longitude = float("nan")
        if not (math.isfinite(source_latitude) and math.isfinite(source_longitude)
                and -90 <= source_latitude <= 90 and -180 <= source_longitude <= 180):
            source_latitude = source_longitude = None
            basis = "Source coordinates invalid or outside WGS84 bounds"
        else:
            lat1, lat2 = math.radians(latitude), math.radians(source_latitude)
            dlat, dlon = lat2 - lat1, math.radians(source_longitude - longitude)
            h = math.sin(dlat / 2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2)**2
            distance = round(6371008.8 * 2 * math.asin(math.sqrt(min(1, h))), 2)
    return {"searched_latitude": latitude, "searched_longitude": longitude,
            "source_latitude": source_latitude, "source_longitude": source_longitude,
            "source_distance_m": distance, "source_location_basis": basis, "match_method": match_method}


def record_location(source, record, latitude, longitude, match_method):
    """Prefer reported points, then provider centroids. Never geocode a guess."""
    y, x = record.get("latitude", record.get("Latitude")), record.get("longitude", record.get("Longitude"))
    basis = "Provider-reported record coordinates (WGS84)"
    geometry = record.get("geometry") or {}
    if y is None or x is None:
        coordinates = record.get("coordinates") or {}
        if coordinates.get("type") == "Point":
            x, y = coordinates["coordinates"][:2]
        elif "x" in geometry and "y" in geometry:
            x, y = geometry["x"], geometry["y"]
            basis = "Provider feature point returned in WGS84"
        elif record.get("centroid"):
            x, y = record["centroid"]["x"], record["centroid"]["y"]
            basis = "Provider polygon centroid in WGS84; not a meter or neighboring-site match"
        elif geometry.get("rings"):
            points = [point for ring in geometry["rings"] for point in ring]
            x = (min(p[0] for p in points) + max(p[0] for p in points)) / 2
            y = (min(p[1] for p in points) + max(p[1] for p in points)) / 2
            basis = "Derived polygon bounding-box center; not a surveyed site point"
        elif source in ("request", "elevation"):
            y, x = latitude, longitude
            basis = "Caller-provided coordinate" if source == "request" else "Requested model sampling point; native cell center not supplied"
        else:
            y = x = None
            basis = "Municipality-wide record; no site coordinate supplied" if source == "utilities" else "Source location not supplied"
    return location_metadata(latitude, longitude, y, x, basis=basis, match_method=match_method)
