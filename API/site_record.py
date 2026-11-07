"""Turn one selected disclosure into a field-level site-intake checklist."""

from pathlib import Path

import polars as pl


def build_site_record(building):
    """Accept one normalized CA/MA disclosure row (a dict) and flag missing inputs.

    Public disclosures start unreviewed. They do not verify site identity,
    engineering suitability, utility eligibility, or current conditions.
    Values are strings so this evidence table exports cleanly to CSV. Units
    remain explicit and the original typed provider snapshots remain intact.
    """
    fields = pl.read_csv(Path(__file__).with_name("site_fields.csv"))
    values = pl.DataFrame({
        "field": fields["field"],
        "value": [None if building.get(field) is None else str(building[field]) for field in fields["field"]],
    }, schema={"field": pl.String, "value": pl.String})
    record = fields.join(values, on="field", how="left", maintain_order="left").with_columns(
        is_missing=pl.col("value").is_null() | pl.col("value").str.strip_chars().eq(""),
    )
    locator = f"building_id={building['building_id']}, data_year={building['data_year']}"
    return record.with_columns(
        site_id=pl.lit(f"{building['state']}:{building['building_id']}"),
        status=pl.when("is_missing").then(pl.lit("missing")).otherwise(pl.lit("needs_review")),
        confidence=pl.when("is_missing").then(pl.lit("unknown")).otherwise(pl.lit("unreviewed")),
        data_kind=pl.when("is_missing").then(pl.lit(None)).otherwise(pl.lit(building["data_kind"])),
        source_url=pl.when("is_missing").then(pl.lit(None)).otherwise(pl.lit(building["source_url"])),
        source_locator=pl.when("is_missing").then(pl.lit(None)).otherwise(pl.concat_str(pl.lit(locator + ", field="), "field")),
        retrieved_at_utc=pl.when("is_missing").then(pl.lit(None)).otherwise(pl.lit(building["retrieved_at_utc"])),
    ).select(
        "site_id", "field", "value", "unit", "status", "confidence", "is_missing",
        "data_kind", "source_url", "source_locator", "retrieved_at_utc",
        "input_to_request", "reference",
    )
