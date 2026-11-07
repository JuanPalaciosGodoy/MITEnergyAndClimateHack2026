"""Readable four-column tables from the existing site lookup response."""

import json

import polars as pl

from .site_lookup import lookup_site

TABLE_COLUMNS = ["checklist item", "subcategory_name", "subcategory_value", "data_source"]

# Show useful candidate values, not JSON pointers or entire nested rate objects.
# Indexes keep each candidate's fields together without assigning it to the site.
CANDIDATE_COLUMNS = {
    "utility_candidates": {"TOWN": "municipality", "ELEC": "provider"},
    "tariff_candidates": {"label": "rate_id", "utility": "utility", "name": "rate_name",
                          "startdate": "start_epoch_seconds", "enddate": "end_epoch_seconds"},
    "annual_energy_candidates": {"building_id": "building_id", "address": "address", "data_year": "data_year",
                                 "floor_area_sqft": "floor_area_sqft", "annual_electricity_kwh": "annual_electricity_kwh"},
}


def checklist_table(site):
    """Flatten one lookup result into exactly four Polars string columns.

    Nulls remain null and zero remains "0". Candidate field names retain their
    scope. Errors are separate *.error rows and do not become successful values.
    The full /site response retains units, review status and raw source records.
    """
    rows = []
    for category in site["checklist"]:
        for field in category["fields"]:
            name = field["name"]
            source = site["sources"].get(field.get("source_id"), {})
            url = field.get("source_url") or source.get("source_url")
            if field.get("source_id") == "request":
                url = "User-provided coordinates"
            value = field["value"]
            values = {name: value}
            if name in CANDIDATE_COLUMNS and source.get("records"):
                values = {
                    f"{name}[{index}].{label}": record.get(column)
                    for index, record in enumerate(source["records"], start=1)
                    for column, label in CANDIDATE_COLUMNS[name].items()
                }
            elif name == "municipal_solar_context" and source.get("records"):
                values = {
                    f"{name}.municipality": source["records"][0].get("City"),
                    f"{name}.total_registered_systems": source.get("total_municipal_records"),
                    f"{name}.data_as_of": source.get("data_as_of"),
                }
            elif field.get("status") == "ambiguous":
                values = {f"{name}.ambiguous_candidates": field.get("candidates", [])}
            if source.get("status") in ("error", "blocked"):
                values[f"{name}.error"] = source.get("error") or source.get("detail") or source["status"]
            for subcategory, item in values.items():
                if item is not None:
                    item = json.dumps(item, ensure_ascii=False) if isinstance(item, (dict, list)) else str(item)
                rows.append({"checklist item": category["title"], "subcategory_name": subcategory,
                             "subcategory_value": item, "data_source": url})
    return pl.DataFrame(rows, schema={column: pl.String for column in TABLE_COLUMNS})


def lookup_table(latitude, longitude, *, sources=None, cache_dir="data/raw", refresh=False):
    """Two coordinates to the four-column checklist table."""
    return checklist_table(lookup_site(latitude, longitude, sources=sources, cache_dir=cache_dir, refresh=refresh))
