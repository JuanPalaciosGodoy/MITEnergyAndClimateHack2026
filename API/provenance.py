"""Dates describe the evidence, not the time we happened to download it."""

from datetime import datetime


def source_date(source, record, column=None):
    """Return (date, meaning), preserving year-only precision and unknown dates."""
    if record.get('source_date') is not None:
        return str(record['source_date']), record.get('source_date_basis','Publisher-supplied date')
    if source == "parcels":
        if column == "LOC_ID":
            value = record.get("LAST_EDIT")
            if value:
                return _compact_date(value), "Parcel geometry LAST_EDIT; not a title verification date"
        if record.get("FY"):
            return str(record["FY"]), "Assessor fiscal year FY; not an ownership verification date"
    if source == "buildings" and record.get("SOURCEDATE"):
        return _compact_date(record["SOURCEDATE"]), "Building outline source survey date SOURCEDATE"
    if source == "lber" and record.get("data_year"):
        return str(record["data_year"]), "Annual energy reporting year"
    if source in ("permits", "electrical_permits", "solar_permits"):
        date = record.get("issue_date") or record.get("applicant_submit_date")
        if date:
            return date[:10], "Permit issue date" if record.get("issue_date") else "Permit application date; no issue date supplied"
    return None, "Source does not supply a record date"


def _compact_date(value):
    text = str(int(value))
    if len(text) == 4:
        return text
    # MassGIS uses zeros when month/day are unknown (e.g. 20110000).
    if len(text) == 8:
        if text[4:6] == "00":
            return text[:4]
        if text[6:8] == "00":
            return text[:4] + "-" + text[4:6]
        try:
            return datetime.strptime(text, "%Y%m%d").date().isoformat()
        except ValueError:
            pass
    return None
