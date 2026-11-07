"""Coordinates to a public-data checklist, without a database or task queue."""

import logging
import math
import requests
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from time import perf_counter

from .ma_sources import (
    DEFAULT_SOURCES,
    DEPENDENT_SOURCES,
    MUNICIPAL_PORTALS,
    REFERENCES,
    SOURCES,
    fetch_source,
)
from .provenance import source_date
from .evidence import save_evidence
from .location import record_location
from .checklist_table import checklist_table
from pathlib import Path
import json
from urllib.parse import urlencode

logger = logging.getLogger(__name__)
SCHEMA_VERSION = "1.3"

# Category ID, label, expected fields, related sources and the next human input.
# All sites use these same categories. Missing private/engineering inputs stay
# missing. Candidate data does not fill a confirmed site-specific field.
CATEGORIES = [
    (
        "identity",
        "Site identity and assessor records",
        [
            "address",
            "municipality",
            "state",
            "latitude",
            "longitude",
            "parcel_id",
            "building_use",
            "assessor_building_area_sqft",
            "parcel_attributes",
            "assessor_records",
        ],
        ["parcels", "assessor_records"],
        "Review published parcel and municipal property boundaries and dates.",
    ),
    (
        "ownership",
        "Reported ownership and recorded documents",
        ["recorded_owner", "land_records"],
        ["parcels", "land_records"],
        "Inspect retrieved registry references and public recorded documents; blocked access remains explicit.",
    ),
    (
        "operations",
        "Published project narratives",
        ["municipal_archives"],
        ["municipal_archives", "permits"],
        "Review public permit scopes and later alterations without inferring actual operating schedules.",
    ),
    (
        "meters",
        "Published service and building relationships",
        ["utility_candidates", "public_service_relationships"],
        ["utilities", "electrical_permits", "assessor_records"],
        "Parcel/address links are candidates; public meter counts are not private account identifiers.",
    ),
    (
        "billing",
        "Public utility schedules",
        ["tariff_candidates"],
        ["tariffs"],
        "Published schedules are candidates; eligibility is not established from coordinates.",
    ),
    (
        "load",
        "Annual public building energy disclosures",
        ["annual_energy_candidates"],
        ["lber"],
        "Review reporting boundaries, years and fuels before assigning disclosure data to a building.",
    ),
    (
        "electrical",
        "Published electrical evidence",
        [
            "service_voltage_v",
            "service_phases",
            "service_amperage_a",
            "transformer_rating_kva",
            "single_line_diagram",
            "point_of_interconnection",
            "electrical_permit_candidates",
            "document_findings",
        ],
        ["electrical_permits", "municipal_archives"],
        "Quoted ratings identify historical/public evidence, not verified current installations.",
    ),
    (
        "existing_systems",
        "Public energy-system records",
        [
            "existing_site_solar",
            "existing_generators",
            "existing_batteries",
            "transfer_switches",
            "interconnection_agreement",
            "solar_permit_candidates",
            "masscec_context",
        ],
        ["solar_permits", "masscec"],
        "Unidentified municipal PTS systems are context, not facility matches.",
    ),
    (
        "placement",
        "Published site geometry and imagery",
        ["mapped_building_id", "roofprint_area_sqft", "public_site_plans"],
        ["buildings", "assessor_records"],
        "Imagery covers the parcel envelope; no clearance or placement suitability is inferred.",
    ),
    (
        "construction",
        "Public environmental and terrain screening",
        [
            "flood_zone",
            "ground_elevation_m",
            "lidar_samples",
            "wetland_candidates",
            "environmental_candidates",
            "activity_use_candidates",
            "habitat_candidates",
        ],
        [
            "flood",
            "lidar",
            "wetlands",
            "environmental",
            "activity_use_limits",
            "protected_habitat",
        ],
        "Published screening layers and lidar samples do not establish absence of constraints.",
    ),
    (
        "approvals",
        "Public authorities and submission references",
        [
            "zoning",
            "building_ahj",
            "fire_ahj",
            "permit_history",
            "applicable_requirements",
            "submission_excerpts",
        ],
        ["public_resources", "municipal_archives"],
        "Contacts and quoted rules require jurisdiction/applicability review; no binding BESS design requirement is inferred.",
    ),
    (
        "system",
        "Public equipment and document references",
        ["equipment_document_references"],
        ["municipal_archives", "assessor_records"],
        "Retain published document dates, page references and proposed/approved/as-built mentions separately.",
    ),
]


def _run_source(
    name,
    latitude,
    longitude,
    municipality,
    context=None,
    cache_dir="data/public_cache",
    refresh=False,
):
    """Keep independent provider failures visible while the others complete."""
    started = perf_counter()
    info = SOURCES[name]
    result = {
        "source_title": info["title"],
        "source_url": info["url"],
        "description": info["description"],
        "data_kind": info["data_kind"],
        "match_method": info["match_method"],
    }
    try:
        result.update(
            fetch_source(
                name,
                latitude,
                longitude,
                municipality=municipality,
                context=context,
                cache_dir=cache_dir,
                refresh=refresh,
            )
        )
        result.setdefault(
            "status",
            "partial"
            if result.get("document_errors") or result.get("resource_errors")
            else "ok"
            if result["records"]
            else "no_data",
        )
    except Exception as error:
        logger.warning("Source %s failed (%s)", name, type(error).__name__)
        result.update(
            status="blocked"
            if isinstance(error, requests.HTTPError)
            and error.response is not None
            and error.response.status_code in (401, 403, 429)
            else "error",
            records=[],
            error=f"{type(error).__name__}: {error}",
        )
    result["attempted_at_utc"] = datetime.now(timezone.utc).isoformat()
    if result["status"] in ("error", "blocked", "unsupported"):
        result["retrieved_at_utc"] = None
    else:
        result.setdefault("retrieved_at_utc", result["attempted_at_utc"])
    if (
        result.get("query")
        and not result.get("query_url")
        and name not in DEPENDENT_SOURCES
    ):
        endpoint = (
            info["url"] + "/query"
            if name
            not in ("permits", "electrical_permits", "solar_permits", "elevation")
            else info["url"]
        )
        result["query_url"] = endpoint + "?" + urlencode(result["query"])
    if name in DEPENDENT_SOURCES and not result.get("query_url"):
        public_query = result.get("query") or {}
        public_url = (
            result.get("search_url")
            or public_query.get("public_search_url")
            or public_query.get("url")
        )
        if public_url:
            result["query_url"] = public_url
    for record in result["records"]:
        record["_location"] = record_location(
            name,
            record,
            latitude,
            longitude,
            record.get("match_method", info["match_method"]),
        )
    result["record_dates"] = [
        {
            "source_date": source_date(name, record)[0],
            "source_date_basis": source_date(name, record)[1],
        }
        for record in result["records"]
    ]
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
        status = (
            "unreviewed"
            if len(records) == 1 and not result.get("truncated")
            else "ambiguous"
        )
    record = values[0] if status == "unreviewed" else {}
    return {
        "value": record.get(column),
        "unit": unit,
        "status": status,
        "source_id": source,
        "source_url": result.get("source_url"),
        "source_field": column,
        "source_record_id": next(
            (
                record[k]
                for k in ("OBJECTID", "FID", "UBID", "STRUCT_ID")
                if k in record
            ),
            None,
        ),
        "retrieved_at_utc": result.get("retrieved_at_utc"),
        "data_kind": result.get("data_kind"),
        "source_title": result.get("source_title"),
        **record.get("_location", {}),
        "source_date": source_date(source, record, column)[0] if record else None,
        "source_date_basis": source_date(source, record, column)[1]
        if record
        else "No single dated source record selected",
        "candidates": [
            {
                "value": r[column],
                "record_id": next(
                    (r[k] for k in ("OBJECTID", "FID", "UBID", "STRUCT_ID") if k in r),
                    None,
                ),
            }
            for r in values
        ]
        if status == "ambiguous"
        else [],
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
    evidence = {
        field: _published_field(results, source, column, unit=unit)
        for field, (source, column, unit) in published.items()
    }
    for field, value in (("latitude", latitude), ("longitude", longitude)):
        evidence[field] = {
            "value": value,
            "unit": "degrees",
            "status": "provided",
            "source_id": "request",
        }
    if municipality:
        utility = results["utilities"]
        for field, value in (("municipality", municipality), ("state", "MA")):
            evidence[field] = {
                "value": value,
                "status": "unreviewed",
                "source_id": "utilities",
                "source_url": utility["source_url"],
                "retrieved_at_utc": utility["retrieved_at_utc"],
            }
    for field, source in (
        ("utility_candidates", "utilities"),
        ("annual_energy_candidates", "lber"),
        ("permit_history", "permits"),
        ("electrical_permit_candidates", "electrical_permits"),
        ("solar_permit_candidates", "solar_permits"),
    ):
        result = results.get(source, {})
        records = result.get("records", [])
        evidence[field] = {
            "value": {
                "record_count": len(records),
                "records_path": f"sources.{source}.records",
            }
            if records
            else None,
            "status": "candidate"
            if records
            else (
                "unavailable"
                if result.get("status") in ("error", "blocked")
                else "missing"
                if source in results
                else "not_requested"
            ),
            "source_id": source,
            "source_url": result.get("source_url"),
            "retrieved_at_utc": result.get("retrieved_at_utc"),
            "data_kind": result.get("data_kind"),
        }
    for field, source in {
        "parcel_attributes": "parcels",
        "assessor_records": "assessor_records",
        "land_records": "land_records",
        "municipal_archives": "municipal_archives",
        "tariff_candidates": "tariffs",
        "masscec_context": "masscec",
        "lidar_samples": "lidar",
        "wetland_candidates": "wetlands",
        "environmental_candidates": "environmental",
        "activity_use_candidates": "activity_use_limits",
        "habitat_candidates": "protected_habitat",
    }.items():
        r = results.get(source, {})
        evidence[field] = {
            "value": {
                "records_path": f"sources.{source}.records",
                "record_count": len(r.get("records", [])),
            }
            if r.get("records")
            else None,
            "source_id": source,
            "status": "candidate"
            if r.get("records")
            else "unavailable"
            if r.get("status") in ("error", "blocked")
            else "not_requested"
            if not r
            else "missing",
        }
    relationships = []
    parcels = results.get("parcels", {}).get("records", [])
    parcel_ids = {str(p.get("MAP_PAR_ID", "")).upper() for p in parcels}
    for r in results.get("electrical_permits", {}).get("records", []):
        relationships.append(
            {
                "permit_id": r.get("id"),
                "address": r.get("full_address"),
                "parcel_id": r.get("mbl"),
                "parcel_relation": "matching published parcel ID"
                if str(r.get("mbl", "")).upper() in parcel_ids
                else "nearby/unmatched parcel",
                "existing_meter_count": r.get("count_of_meters_existing"),
                "new_meter_count": r.get("count_of_meters_new_service"),
                "overhead_existing": r.get("overhead_existing"),
                "underground_existing": r.get("underground_existing"),
                "relation_status": "public permit relationship; active service-to-building assignment unverified",
                "_location": r.get("_location"),
                "_source_url": (r.get("specific_url") or {}).get("url"),
            }
        )
    evidence["public_service_relationships"] = {
        "value": relationships or None,
        "source_id": "electrical_permits",
        "status": "candidate",
    }
    resources = results.get("public_resources", {})
    if resources.get("requirements"):
        evidence["submission_excerpts"] = {
            "value": {
                "record_count": len(resources["requirements"]),
                "records_path": "sources.public_resources.requirements",
            },
            "source_id": "public_resources",
            "status": "candidate",
        }
    for field in ("building_ahj", "fire_ahj", "applicable_requirements"):
        indices = [
            index
            for index, record in enumerate(resources.get("records", []))
            if record["field"] == field
        ]
        if indices:
            matches = [resources["records"][index] for index in indices]
            evidence[field] = {
                "value": matches[0]["title"]
                if len(matches) == 1
                else [{"title": r["title"], "url": r["url"]} for r in matches],
                "status": "reference_only",
                "source_id": "public_resources",
                "source_record_indices": indices,
                "source_url": matches[0]["url"],
                "retrieved_at_utc": resources["retrieved_at_utc"],
            }
    return [
        {
            "id": category,
            "title": title,
            "fields": [
                {
                    "name": field,
                    **evidence.get(field, {"value": None, "status": "missing"}),
                }
                for field in fields
            ],
            "source_ids": source_ids,
            "next_action": action,
        }
        for category, title, fields, source_ids, action in CATEGORIES
    ]


def lookup_site(
    latitude,
    longitude,
    *,
    sources=None,
    refresh=False,
    download_evidence=True,
    evidence_dir="data/evidence",
    documents=None,
):
    """Fetch public evidence for a Massachusetts point. Only two arguments needed.

    utilities is always queried to determine Massachusetts coverage and the
    municipality. Other independent providers run in a bounded thread pool.
    Public source success never marks the site engineering-ready.
    """
    if not (
        math.isfinite(latitude)
        and math.isfinite(longitude)
        and -90 <= latitude <= 90
        and -180 <= longitude <= 180
    ):
        raise ValueError(
            "Provide finite latitude in [-90, 90] and longitude in [-180, 180]."
        )
    selected = list(dict.fromkeys(DEFAULT_SOURCES if sources is None else sources))
    unknown = set(selected) - SOURCES.keys()
    if unknown:
        raise ValueError(
            f"Unknown sources: {', '.join(sorted(unknown))}. See /sources."
        )
    parcel_dependencies = DEPENDENT_SOURCES - {"masscec", "tariffs"}
    if set(selected) & parcel_dependencies and "parcels" not in selected:
        selected.insert(0, "parcels")
    results = {"utilities": _run_source("utilities", latitude, longitude, None)}
    if results["utilities"]["status"] == "no_data":
        raise ValueError(
            "No Massachusetts municipality contains this point. Choose a point on the facility in Massachusetts."
        )
    towns = {r["TOWN"] for r in results["utilities"]["records"] if r.get("TOWN")}
    municipality = next(iter(towns)) if len(towns) == 1 else None
    cache_dir = str(Path(evidence_dir) / f"{latitude:.6f}_{longitude:.6f}" / "files")
    names = [
        name
        for name in selected
        if name != "utilities" and name not in DEPENDENT_SOURCES
    ]
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {
            name: pool.submit(
                _run_source,
                name,
                latitude,
                longitude,
                municipality,
                None,
                cache_dir,
                refresh,
            )
            for name in names
        }
        results.update({name: future.result() for name, future in futures.items()})
    # Dependency stage receives a stable snapshot of parcel/utility results.
    context = dict(results)
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {
            name: pool.submit(
                _run_source,
                name,
                latitude,
                longitude,
                municipality,
                context,
                cache_dir,
                refresh,
            )
            for name in selected
            if name in DEPENDENT_SOURCES
        }
        results.update({name: future.result() for name, future in futures.items()})
    references = {name: dict(info) for name, info in REFERENCES.items()}
    references["permits"].update(
        url=MUNICIPAL_PORTALS.get(municipality),
        search_address=None,
        search_municipality=municipality,
    )
    checklist = build_checklist(results, latitude, longitude, municipality)
    address = checklist[0]["fields"][0]["value"]
    references["permits"]["search_address"] = address
    problems = [
        name
        for name, result in results.items()
        if result["status"] in ("error", "blocked", "unsupported", "partial")
        or result.get("resource_errors")
        or result.get("document_errors")
    ]
    site = {
        "schema_version": SCHEMA_VERSION,
        "status": "partial" if problems else "ok",
        "location": {
            "latitude": latitude,
            "longitude": longitude,
            "municipality": municipality,
            "state": "MA" if municipality else None,
            "address": address,
        },
        "requested_at_utc": datetime.now(timezone.utc).isoformat(),
        "sources": results,
        "references": references,
        "checklist": checklist,
        "source_errors": problems,
        "missing_fields": [
            {
                "category": category["id"],
                "field": field["name"],
                "next_action": category["next_action"],
            }
            for category in checklist
            for field in category["fields"]
            if field["value"] is None
        ],
        "public_only": True,
        "notes": [
            "Source status ok means records were retrieved, not verified against the facility or meter.",
            "Nearby LBER and permit records are candidates. Their coordinates and distance do not establish a site match.",
            "Assessor area, mapped roof area and usable battery space are distinct quantities.",
            "Permit matches and downloaded plans require confirmation of building, dates, revisions and as-built status.",
            "Blank source dates mean the provider did not supply a record date; fetch time is never substituted.",
        ],
    }

    site["public_coverage"] = [
        {
            "source": name,
            "status": r["status"],
            "records": len(r["records"]),
            "truncated": r.get("truncated", False),
            "document_access": r.get("document_access"),
            "document_errors": r.get("document_errors", []),
            "detail": r.get("detail") or r.get("limitations") or r.get("error"),
        }
        for name, r in results.items()
    ]
    site["evidence"] = (
        save_evidence(site, evidence_dir, refresh=refresh, documents=documents)
        if download_evidence
        else None
    )
    if site["evidence"]:
        files = site["evidence"]["files"]
        summaries = {
            "document_findings": site.get("document_findings", []),
            "submission_excerpts": results.get("public_resources", {}).get(
                "requirements", []
            ),
            "public_site_plans": [
                {
                    "title": f["source_title"],
                    "file_url": f.get("file_url"),
                    "kind": f["kind"],
                }
                for f in files
                if f["status"] == "ok"
                and f["kind"] in ("document", "assessor_image")
                and f.get("source_id") in ("municipal_archives", "assessor_records")
                and any(
                    w in f["source_title"].lower()
                    for w in ("plan", "sketch", "blueprint", "drawing")
                )
            ],
            "equipment_document_references": site.get("document_findings", []),
        }
        site["public_site_plans"] = summaries["public_site_plans"]
        for category in checklist:
            for field in category["fields"]:
                if field["name"] in summaries and summaries[field["name"]]:
                    field.update(
                        value={
                            "record_count": len(summaries[field["name"]]),
                            "evidence_path": {
                                "submission_excerpts": "sources.public_resources.requirements",
                                "equipment_document_references": "document_findings",
                            }.get(field["name"], field["name"]),
                        },
                        status="candidate",
                    )
        site["missing_fields"] = [
            {"category": c["id"], "field": f["name"], "next_action": c["next_action"]}
            for c in checklist
            for f in c["fields"]
            if f["value"] is None
        ]
        if site["evidence"]["errors"]:
            site["status"] = "partial"
        exports = site["evidence"]["exports"]
        table = checklist_table(site)
        table.write_csv(exports["checklist_csv"]["local_file"])
        table.write_parquet(exports["checklist_parquet"]["local_file"])
        Path(exports["site_json"]["local_file"]).write_text(
            json.dumps(site, indent=2, ensure_ascii=False)
        )
    return site
