"""Readable site-intake tables, dates and local evidence references."""

import json

import polars as pl

from .provenance import source_date
from .location import LOCATION_COLUMNS, record_location

TABLE_COLUMNS = [
    "checklist item",
    "subcategory_name",
    "subcategory_value",
    "data_source",
    "source_title",
    "fetched_at_utc",
    "source_date",
    "source_date_basis",
    "local_file",
    "file_url",
    *LOCATION_COLUMNS,
]
TABLE_SCHEMA = {
    column: (pl.Float64 if column in LOCATION_COLUMNS[:5] else pl.String)
    for column in TABLE_COLUMNS
}

# Show useful candidate values, not JSON pointers or entire nested rate objects.
# Indexes keep each candidate's fields together without assigning it to the site.
CANDIDATE_COLUMNS = {
    "electrical_permit_candidates": {
        "id": "permit_id",
        "full_address": "address",
        "issue_date": "issue_date",
        "status": "reported_status",
        "volts_existing_service": "reported_existing_service_volts",
        "amps_existing_service": "reported_existing_service_amps",
        "volts_new_service": "reported_new_service_volts",
        "amps_new_service": "reported_new_service_amps",
        "photovoltaic_panels": "reported_pv_panel_count",
        "generators": "reported_generator_count",
        "kva": "reported_kva_raw",
        "proposed_work_description": "work_description",
        "description": "description",
    },
    "solar_permit_candidates": {
        "id": "permit_id",
        "full_address": "address",
        "issue_date": "issue_date",
        "status": "reported_status",
        "work_description": "work_description",
        "solar_energy_type": "reported_energy_type",
        "solar_system_size": "reported_system_size_raw",
        "watt_capacity": "reported_watt_capacity_raw",
        "photovoltaic_panel_count": "reported_panel_count",
        "inverter_make_and_model": "reported_inverter",
        "battery_storage_capacity": "reported_battery_field_raw",
    },
    "applicable_requirements": {"title": "reference_title", "url": "reference_url"},
    "permit_history": {
        "id": "permit_id",
        "full_address": "address",
        "permit_type": "permit_type",
        "status": "reported_status",
        "issue_date": "issue_date",
        "specific_url": "detail_url",
    },
    "utility_candidates": {"TOWN": "municipality", "ELEC": "provider"},
    "annual_energy_candidates": {
        "building_id": "building_id",
        "address": "address",
        "data_year": "data_year",
        "floor_area_sqft": "floor_area_sqft",
        "annual_electricity_kwh": "annual_electricity_kwh",
    },
}


# The compact intake view omits workflow permissions, financial modeling and
# final equipment sizing. The full twelve-category contract remains available.
INTAKE_OMIT = set()
OPTIONAL_FIELDS = {}
GENERIC_PUBLIC_FIELDS = {
    "parcel_attributes",
    "assessor_records",
    "land_records",
    "municipal_archives",
    "tariff_candidates",
    "masscec_context",
    "lidar_samples",
    "wetland_candidates",
    "environmental_candidates",
    "activity_use_candidates",
    "habitat_candidates",
}
EXCLUDE_ATTRIBUTES = {
    "geometry",
    "centroid",
    "coordinates",
    "GlobalID",
    "Shape__Area",
    "Shape__Length",
}


def checklist_table(site, *, include_all=False):
    """Flatten a lookup into a dated table with human-readable provenance.

    Year-only source dates stay year-only. Null dates do not mean today's date.
    Failed fetches have null fetched_at_utc. Candidate dates belong to that
    candidate, not to the site. include_all exposes the full original checklist.
    """
    rows = []
    cached_assets = [
        a for source in site["sources"].values() for a in source.get("artifacts", [])
    ]
    assets_by_url = {
        asset["source_url"]: asset
        for asset in [*cached_assets, *(site.get("evidence") or {}).get("files", [])]
        if asset["status"] == "ok" and asset["kind"] != "extracted_text"
    }
    latitude, longitude = site["location"]["latitude"], site["location"]["longitude"]
    for category in site["checklist"]:
        for field in category["fields"]:
            name = field["name"]
            if not include_all and (
                name in INTAKE_OMIT
                or (
                    name in OPTIONAL_FIELDS
                    and OPTIONAL_FIELDS[name] not in site["sources"]
                )
            ):
                continue
            source_id = field.get("source_id")
            source = site["sources"].get(source_id, {})
            url = (
                source.get("query_url")
                or field.get("source_url")
                or source.get("source_url")
            )
            title = (
                source.get("source_title")
                or field.get("source_title")
                or "Site information still to collect"
            )
            fetched = source.get("retrieved_at_utc")
            if source_id == "request":
                url, title, fetched = (
                    "User-provided coordinates",
                    "Coordinates supplied by the caller",
                    site["requested_at_utc"],
                )
            values = [(name, field["value"], None)]
            records = source.get("records", [])
            if field.get("source_record_indices") is not None:
                records = [records[index] for index in field["source_record_indices"]]
            if name in GENERIC_PUBLIC_FIELDS and records:
                values = [
                    (f"{name}[{index}].{column}", item, record)
                    for index, record in enumerate(records, 1)
                    for column, item in record.items()
                    if item is not None
                    and column not in EXCLUDE_ATTRIBUTES
                    and not column.startswith("_")
                ]
            elif name == "public_service_relationships" and isinstance(
                field["value"], list
            ):
                values = [
                    (f"{name}[{index}].{column}", item, record)
                    for index, record in enumerate(field["value"], 1)
                    for column, item in record.items()
                    if item is not None and not column.startswith("_")
                ]
            elif (
                name
                in (
                    "annual_energy_candidates",
                    "electrical_permit_candidates",
                    "solar_permit_candidates",
                )
                and records
            ):
                values = [
                    (
                        f"{name}[{index}].{CANDIDATE_COLUMNS[name].get(column, column)}",
                        item,
                        record,
                    )
                    for index, record in enumerate(records, 1)
                    for column, item in record.items()
                    if item is not None
                    and column not in EXCLUDE_ATTRIBUTES
                    and not column.startswith("_")
                ]
            elif name in CANDIDATE_COLUMNS and records:
                values = [
                    (f"{name}[{index}].{label}", record.get(column), record)
                    for index, record in enumerate(records, start=1)
                    for column, label in CANDIDATE_COLUMNS[name].items()
                    if name
                    not in ("electrical_permit_candidates", "solar_permit_candidates")
                    or record.get(column) is not None
                ]
            elif field.get("status") == "ambiguous":
                values = [
                    (
                        f"{name}.ambiguous_candidates[{index}]",
                        record.get(field["source_field"]),
                        record,
                    )
                    for index, record in enumerate(records, start=1)
                ]
            elif len(records) == 1:
                values = [(name, field["value"], records[0])]
            if source.get("status") in ("error", "blocked"):
                values.append(
                    (
                        f"{name}.error",
                        source.get("error") or source.get("detail") or source["status"],
                        None,
                    )
                )
            for subcategory, item, record in values:
                date, basis = (
                    source_date(source_id, record, field.get("source_field"))
                    if record
                    else (None, "No dated source record retrieved")
                )
                if source_id == "request":
                    basis = "Caller supplied location; observation date unknown"
                location = (record or {}).get("_location") or record_location(
                    source_id,
                    record or {},
                    latitude,
                    longitude,
                    "caller_coordinates"
                    if source_id == "request"
                    else source.get("match_method", "uncollected"),
                )
                record_url = (
                    (record or {}).get("_source_url")
                    or (record or {}).get("source_url")
                    or (record or {}).get("url")
                    or ((record or {}).get("specific_url") or {}).get("url")
                    or url
                )
                artifact = assets_by_url.get(record_url, {})
                record_title = (record or {}).get("source_title") or title
                if isinstance(item, dict) and subcategory.endswith(".detail_url"):
                    item = item.get("url")
                if item is not None:
                    item = (
                        json.dumps(item, ensure_ascii=False)
                        if isinstance(item, (dict, list))
                        else str(item)
                    )
                rows.append(
                    {
                        "checklist item": category["title"],
                        "subcategory_name": subcategory,
                        "subcategory_value": item,
                        "data_source": record_url,
                        "source_title": record_title,
                        "fetched_at_utc": artifact.get("fetched_at_utc")
                        or (record or {}).get("retrieved_at_utc")
                        or fetched,
                        "source_date": date,
                        "source_date_basis": basis,
                        "local_file": artifact.get("local_file")
                        or (record or {}).get("local_file")
                        or source.get("local_file"),
                        "file_url": artifact.get("file_url") or source.get("file_url"),
                        **location,
                    }
                )
    for index, asset in enumerate(
        (site.get("evidence") or {}).get("files", []), start=1
    ):
        if asset["kind"] == "source_snapshot":
            continue  # Field rows already refer to these files.
        rows.append(
            {
                "checklist item": "Supporting files",
                "subcategory_name": f"{asset['kind']}[{index}]"
                + (".error" if asset["status"] == "error" else ""),
                "subcategory_value": asset.get("error")
                or asset.get("match_status")
                or "Downloaded public source file",
                "data_source": asset["source_url"],
                "source_title": asset["source_title"],
                "fetched_at_utc": asset.get("fetched_at_utc"),
                "source_date": asset.get("source_date"),
                "source_date_basis": asset.get("source_date_basis"),
                "local_file": asset.get("local_file"),
                "file_url": asset.get("file_url"),
                **{key: asset.get(key) for key in LOCATION_COLUMNS},
            }
        )
    findings = [
        *site.get("document_findings", []),
        *site["sources"].get("public_resources", {}).get("requirements", []),
    ]
    for index, record in enumerate(findings, 1):
        url = record.get("url")
        artifact = assets_by_url.get(url, {})
        rows.append(
            {
                "checklist item": "Quoted public document evidence",
                "subcategory_name": f"document_findings[{index}]",
                "subcategory_value": json.dumps(record, ensure_ascii=False),
                "data_source": url,
                "source_title": record.get("source_title"),
                "fetched_at_utc": artifact.get("fetched_at_utc"),
                "source_date": record.get("source_date") or artifact.get("source_date"),
                "source_date_basis": record.get("source_date_basis")
                or "Refer to document page, date and applicability",
                "local_file": artifact.get("local_file"),
                "file_url": (
                    artifact["file_url"]
                    + (f"#page={record['page']}" if record.get("page") else "")
                )
                if artifact.get("file_url")
                else None,
                **record_location(None, {}, latitude, longitude, "document_candidate"),
            }
        )
    return pl.DataFrame(rows, schema=TABLE_SCHEMA)


def lookup_table(
    latitude,
    longitude,
    *,
    sources=None,
    refresh=False,
    download_evidence=True,
    evidence_dir="data/evidence",
    documents=None,
    include_all=False,
):
    """Two coordinates to a dated checklist; download supporting evidence by default."""
    from .site_lookup import lookup_site

    site = lookup_site(
        latitude,
        longitude,
        sources=sources,
        refresh=refresh,
        download_evidence=download_evidence,
        evidence_dir=evidence_dir,
        documents=documents,
    )
    return checklist_table(site, include_all=include_all)
