"""Coordinates to a public-data checklist, without a database or task queue."""

import logging
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from time import perf_counter

from .ma_sources import MUNICIPAL_PORTALS, REFERENCES, SOURCES, fetch_source

logger = logging.getLogger(__name__)

# Category ID, label, expected fields, related sources and the next human input.
# All sites use these same categories. Missing private/engineering inputs stay
# missing. Candidate data does not fill a confirmed site-specific field.
CATEGORIES = [
    ("identity", "Site identity and boundaries",
     ["address", "municipality", "state", "latitude", "longitude", "parcel_id", "building_use", "assessor_building_area_sqft"],
     ["parcels", "buildings"], "Confirm the parcel, buildings and electrical service belong to this project."),
    ("authority", "Contacts and authority",
     ["recorded_owner", "facility_contact", "owner_consent", "utility_data_authorization"],
     ["parcels", "land_records"], "Identify the decision-maker and obtain owner consent and utility-data authorization."),
    ("operations", "Objectives and operations",
     ["primary_objective", "operating_schedule", "planned_load_changes"],
     ["permits"], "Ask about savings/backup objectives, shifts, seasonal changes and planned equipment."),
    ("meters", "Utility accounts and meters",
     ["utility_candidates", "utility_account_ids", "meter_ids", "service_building_mapping"],
     ["utilities", "bills"], "Use current bills and meter photos to map each account and service to its buildings."),
    ("billing", "Bills and applicable tariff",
     ["tariff_candidates", "actual_tariff_code", "monthly_bills"],
     ["tariffs", "tariff_documents", "bills"], "Collect twelve bills per relevant account and confirm applicable rate codes and dates."),
    ("load", "Interval consumption",
     ["annual_energy_candidates", "interval_data"],
     ["lber", "interval_data", "comstock"], "Obtain 12-24 months of customer-authorized meter exports and review time conventions, gaps and units."),
    ("electrical", "Existing electrical infrastructure",
     ["service_voltage_v", "service_phases", "service_amperage_a", "transformer_rating_kva", "single_line_diagram", "point_of_interconnection"],
     ["permits"], "Find current electrical drawings and readable equipment nameplates. Have an engineer confirm the connection point."),
    ("existing_systems", "Existing energy systems",
     ["municipal_solar_context", "existing_site_solar", "existing_generators", "existing_batteries", "transfer_switches", "interconnection_agreement"],
     ["solar", "permits"], "Confirm actual on-site equipment and controls using current drawings, specifications and agreements."),
    ("placement", "Candidate battery location",
     ["mapped_building_id", "roofprint_area_sqft", "proposed_bess_location", "measured_clearances_ft", "site_photos"],
     ["buildings", "parcels", "permits"], "Provide a marked site plan, dated photographs and measured clearances for engineering review."),
    ("construction", "Construction and site constraints",
     ["flood_zone", "ground_elevation_m", "cable_route", "foundation_assessment", "underground_services", "shutdown_window"],
     ["flood", "elevation", "permits"], "Check current site conditions, routing, foundations, underground services, communications and shutdown windows."),
    ("approvals", "Authorities and approvals",
     ["zoning", "building_ahj", "fire_ahj", "permit_history", "applicable_requirements"],
     ["parcels", "permits", "requirements"], "Identify the building/fire authorities and review current utility and municipal submission requirements."),
    ("system", "Proposed battery system",
     ["bess_power_kw", "bess_energy_kwh", "battery_model", "operating_mode"],
     ["requirements"], "Have EQORE select the system and operating mode from actual load, tariff and engineering evidence."),
]


def _run_source(name, latitude, longitude, municipality, cache_dir, refresh):
    """Keep independent provider failures visible while the others complete."""
    started = perf_counter()
    info = SOURCES[name]
    result = {"source_url": info["url"], "description": info["description"],
              "data_kind": info["data_kind"], "match_method": info["match_method"]}
    try:
        result.update(fetch_source(name, latitude, longitude, municipality=municipality,
                                   cache_dir=cache_dir, refresh=refresh))
        result.setdefault("status", "ok" if result["records"] else "no_data")
    except Exception as error:
        logger.warning("Source %s failed (%s)", name, type(error).__name__)
        result.update(status="error", records=[], error=f"{type(error).__name__}: {error}")
    retrieved = result.pop("downloaded_at_epoch", None)
    result["attempted_at_utc"] = datetime.now(timezone.utc).isoformat()
    result["retrieved_at_utc"] = None if result["status"] in ("error", "blocked") else (
        datetime.fromtimestamp(retrieved, timezone.utc).isoformat() if retrieved is not None else result["attempted_at_utc"]
    )
    result["elapsed_seconds"] = round(perf_counter() - started, 3)
    return result


def _published_field(results, source, column, *, unit=None):
    """Expose ambiguous intersections rather than choosing the first record."""
    result = results.get(source, {})
    records = result.get("records", [])
    values = [r for r in records if r.get(column) is not None and r.get(column) != ""]
    status = "missing"
    if source not in results:
        status = "not_requested"
    elif result["status"] in ("error", "blocked"):
        status = "unavailable"
    elif values:
        status = "unreviewed" if len(records) == 1 and not result.get("truncated") else "ambiguous"
    record = values[0] if status == "unreviewed" else {}
    return {
        "value": record.get(column), "unit": unit, "status": status,
        "source_id": source, "source_url": result.get("source_url"), "source_field": column,
        "source_record_id": next((record[k] for k in ("OBJECTID", "FID", "UBID", "STRUCT_ID") if k in record), None),
        "retrieved_at_utc": result.get("retrieved_at_utc"), "data_kind": result.get("data_kind"),
        "candidates": [{"value": r[column], "record_id": next((r[k] for k in ("OBJECTID", "FID", "UBID", "STRUCT_ID") if k in r), None)}
                       for r in values] if status == "ambiguous" else [],
    }


def build_checklist(results, latitude, longitude, municipality):
    """The same field contract for every site, including unresolved inputs."""
    published = {
        "address": ("parcels", "SITE_ADDR", None),
        "parcel_id": ("parcels", "LOC_ID", None),
        "recorded_owner": ("parcels", "OWNER1", None),
        "building_use": ("parcels", "USE_DESC", None),
        "assessor_building_area_sqft": ("parcels", "BLD_AREA", "ft2"),
        "zoning": ("parcels", "ZONING", None),
        "mapped_building_id": ("buildings", "STRUCT_ID", None),
        "roofprint_area_sqft": ("buildings", "AREA_SQ_FT", "ft2"),
        "flood_zone": ("flood", "FLD_ZONE", None),
        "ground_elevation_m": ("elevation", "elevation_m", "m"),
    }
    evidence = {field: _published_field(results, source, column, unit=unit)
                for field, (source, column, unit) in published.items()}
    for field, value in (("latitude", latitude), ("longitude", longitude)):
        evidence[field] = {"value": value, "unit": "degrees", "status": "provided", "source_id": "request"}
    if municipality:
        utility = results["utilities"]
        for field, value in (("municipality", municipality), ("state", "MA")):
            evidence[field] = {"value": value, "status": "unreviewed", "source_id": "utilities",
                               "source_url": utility["source_url"], "retrieved_at_utc": utility["retrieved_at_utc"]}
    for field, source in (("utility_candidates", "utilities"), ("tariff_candidates", "tariffs"),
                          ("annual_energy_candidates", "lber"), ("municipal_solar_context", "solar")):
        result = results.get(source, {})
        records = result.get("records", [])
        evidence[field] = {
            "value": {"record_count": len(records), "records_path": f"sources.{source}.records"} if records else None,
            "status": "candidate" if records else ("unavailable" if result.get("status") in ("error", "blocked")
                                                     else "missing" if source in results else "not_requested"),
            "source_id": source, "source_url": result.get("source_url"),
            "retrieved_at_utc": result.get("retrieved_at_utc"), "data_kind": result.get("data_kind"),
        }
    return [{
        "id": category, "title": title,
        "fields": [{"name": field, **evidence.get(field, {"value": None, "status": "missing"})} for field in fields],
        "source_ids": source_ids, "next_action": action,
    } for category, title, fields, source_ids, action in CATEGORIES]


def lookup_site(latitude, longitude, *, sources=None, cache_dir="data/raw", refresh=False):
    """Fetch public evidence for a Massachusetts point. Only two arguments needed.

    utilities is always queried to determine Massachusetts coverage and the
    municipality. Other independent providers run in a bounded thread pool.
    Public source success never marks the site engineering-ready.
    """
    if not (math.isfinite(latitude) and math.isfinite(longitude) and -90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError("Provide finite latitude in [-90, 90] and longitude in [-180, 180].")
    selected = list(dict.fromkeys(SOURCES if sources is None else sources))
    unknown = set(selected) - SOURCES.keys()
    if unknown:
        raise ValueError(f"Unknown sources: {', '.join(sorted(unknown))}. See /sources.")
    results = {"utilities": _run_source("utilities", latitude, longitude, None, cache_dir, refresh)}
    if results["utilities"]["status"] == "no_data":
        raise ValueError("No Massachusetts municipality contains this point. Choose a point on the facility in Massachusetts.")
    towns = {r["TOWN"] for r in results["utilities"]["records"] if r.get("TOWN")}
    municipality = next(iter(towns)) if len(towns) == 1 else None
    names = [name for name in selected if name != "utilities"]
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {name: pool.submit(_run_source, name, latitude, longitude, municipality, cache_dir, refresh) for name in names}
        results.update({name: future.result() for name, future in futures.items()})
    references = {name: dict(info) for name, info in REFERENCES.items()}
    references["permits"].update(url=MUNICIPAL_PORTALS.get(municipality),
                                 search_address=None, search_municipality=municipality)
    checklist = build_checklist(results, latitude, longitude, municipality)
    address = checklist[0]["fields"][0]["value"]
    references["permits"]["search_address"] = address
    problems = [name for name, result in results.items() if result["status"] in ("error", "blocked")]
    return {
        "schema_version": "1.0", "status": "partial" if problems else "ok",
        "location": {"latitude": latitude, "longitude": longitude, "municipality": municipality,
                     "state": "MA" if municipality else None, "address": address},
        "requested_at_utc": datetime.now(timezone.utc).isoformat(),
        "sources": results, "references": references, "checklist": checklist,
        "source_errors": problems,
        "missing_fields": [{"category": category["id"], "field": field["name"], "next_action": category["next_action"]}
                           for category in checklist for field in category["fields"] if field["value"] is None],
        "notes": [
            "Source status ok means records were retrieved, not verified against the customer's site or meter.",
            "Nearby LBER and tariff records are candidates. Municipal solar context does not identify on-site solar.",
            "Assessor area, mapped roof area and usable battery space are distinct quantities.",
            "Private documents and archived plans require the actions in references and missing_fields.",
        ],
    }
