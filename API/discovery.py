"""Resolve published datasets on every lookup; never fall back to a pinned edition."""

import re
from datetime import datetime, timezone

from ._http import get_json

LBER_CATALOG = "https://services1.arcgis.com/7iJyYTjCtKsZS1LR/arcgis/rest/services"
IMAGERY_CATALOG = "https://tiles.arcgis.com/tiles/hGdibHYSPO59RG1h/arcgis/rest/services"


def lber_datasets(session):
    catalog = get_json(session, LBER_CATALOG, {"f": "json"})
    services = [
        s
        for s in catalog.get("services", [])
        if s["type"] == "FeatureServer"
        and re.search(
            r"(?:LBER.*Annual_Report_Data|Annual_Report_Data)$", s["name"], re.I
        )
    ]
    if not services:
        raise ValueError(
            "No LBER annual datasets discovered in the live DOER catalog; no historical fallback used."
        )
    datasets = []
    for service in services:
        url = LBER_CATALOG + "/" + service["name"] + "/FeatureServer"
        metadata = get_json(session, url, {"f": "json"})
        layers = metadata.get("layers", [])
        layer = next((x for x in layers if x["name"].lower() == "properties"), None)
        if layer is None:
            raise ValueError(f"No Properties layer exposed by {url}")
        datasets.append(
            {
                "name": service["name"],
                "url": url + "/" + str(layer["id"]),
                "item_id": metadata.get("serviceItemId"),
            }
        )
    return datasets


def latest_raster(session, kind):
    if kind != "imagery":
        raise ValueError(
            "Only site imagery is in Option 1; lidar/environmental screening is excluded."
        )
    catalog_url = IMAGERY_CATALOG
    catalog = get_json(session, catalog_url, {"f": "json"})
    candidates = []
    for service in catalog.get("services", []):
        name = service["name"]
        match = re.fullmatch(
            r"(?:Massachusetts_Aerial_Imagery_|orthos)(20\d{2})", name, re.I
        )
        if not match or service["type"] != "MapServer":
            continue
        year = match[1]
        candidates.append(
            {
                "url": catalog_url + "/" + name + "/MapServer",
                "name": name,
                "years": [year],
                "source_date": year,
                "discovery_url": catalog_url,
            }
        )
    if not candidates:
        raise ValueError(
            f"No {kind} dataset discovered in the live catalog; no fixed-year fallback used."
        )
    selected = max(candidates, key=lambda c: max(map(int, c["years"])))
    selected["checked_at_utc"] = datetime.now(timezone.utc).isoformat()
    return selected
