"""Public PTS context and utility-published schedule extraction, without accounts."""

import json

import fastexcel
import polars as pl

from .public_utils import inspect_pdf, page, page_links, public_file, saved_page

PTS_PAGE = "https://www.masscec.com/production-tracking-system-pts"
PTS_FILE = "https://www.masscec.com/sites/default/files/documents/Solar-PV-Systems-in-MA-as-of-Jan-2025.xlsx"
RATE_DIRECTORY = (
    "https://www.mass.gov/info-details/massachusetts-electric-rates-and-tariffs"
)
UTILITY_PDFS = {
    "eversource_cambridge": [
        (
            "Cambridge G-3",
            "https://www.eversource.com/content/docs/default-source/rates-tariffs/ma-electric/21-tariff-ma.pdf",
        ),
        (
            "Cambridge delivery summary",
            "https://www.eversource.com/docs/default-source/rates-tariffs/ema-cambridge-rates.pdf",
        ),
        (
            "Referenced M.D.P.U. No. 1 rates",
            "https://www.eversource.com/content/docs/default-source/rates-tariffs/ma-electric/1-tariff-ma.pdf",
        ),
    ],
    "eversource_east": [
        (
            "Greater Boston G-3",
            "https://www.eversource.com/content/docs/default-source/rates-tariffs/ma-electric/13-tariff-ma.pdf",
        ),
        (
            "Greater Boston delivery summary",
            "https://www.eversource.com/docs/default-source/rates-tariffs/ema-greater-boston-rates.pdf",
        ),
    ],
    "eversource_west": [
        (
            "Western Massachusetts delivery summary",
            "https://www.eversource.com/content/docs/default-source/rates-tariffs/wma-rates.pdf",
        )
    ],
    "national_grid": [
        (
            "Massachusetts Electric G-3",
            "https://www.nationalgridus.com/media/pdfs/billing-payments/tariffs/mae/meco_g3.pdf",
        ),
        (
            "Industrial basic service summary",
            "https://www.nationalgridus.com/media/pdfs/billing-payments/electric-rates/ma/indtable.pdf",
        ),
    ],
}


def masscec(session, municipality, context, cache_dir, refresh=False):
    response, soup = page(session, PTS_PAGE)
    links = [
        x
        for x in page_links(soup, response.url)
        if ".xlsx" in x["url"].lower()
        and "solar" in (x["title"] + " " + x["url"]).lower()
    ]
    url = links[0]["url"] if links else PTS_FILE
    asset = public_file(
        session,
        url,
        "MassCEC public PTS solar systems report",
        cache_dir,
        refresh,
        kind="source_document",
    )
    frame = (
        fastexcel.read_excel(asset["local_file"])
        .load_sheet(0, header_row=10, schema_sample_rows=None)
        .to_polars()
    )
    local = frame.filter(
        pl.col("City").str.to_uppercase() == (municipality or "").upper()
    )
    rows = json.loads(local.head(50).write_json())
    for index, record in enumerate(rows, 1):
        record.update(
            public_context_row=index,
            source_url=url,
            source_date="2025-01" if "Jan-2025" in url else None,
            source_date_basis="Report snapshot month in publisher filename"
            if "Jan-2025" in url
            else "Report date unavailable",
            match_method="municipality_context",
            location_limit="Public report has city/ZIP but no street address or site coordinates; no facility assignment",
        )
    return {
        "records": rows,
        "total_municipal_records": local.height,
        "truncated": local.height > 50,
        "artifacts": [asset],
        "source_url": url,
        "retrieved_at_utc": asset["fetched_at_utc"],
        "limitations": "Municipal context only. Capacities, equipment and in-service dates belong to unidentified registered systems, not the searched facility.",
    }


def tariffs(session, municipality, context, cache_dir, refresh=False):
    response, soup = page(session, RATE_DIRECTORY)
    artifacts = [
        saved_page(
            response, cache_dir, "Massachusetts official electric rate directory"
        )
    ]
    utilities = " ".join(
        r.get("ELEC", "") for r in context.get("utilities", {}).get("records", [])
    ).lower()
    selections = []
    if "eversource" in utilities or "nstar" in utilities:
        selections += UTILITY_PDFS[
            "eversource_cambridge"
            if municipality == "CAMBRIDGE"
            else "eversource_west"
            if "western" in utilities or "wmeco" in utilities
            else "eversource_east"
        ]
    if "national grid" in utilities:
        selections += UTILITY_PDFS["national_grid"]
    records, errors = [], []
    for label, url in selections:
        try:
            asset = public_file(
                session, url, "Utility-published " + label, cache_dir, refresh
            )
            parsed = inspect_pdf(asset, role="tariff")
            asset.update(text_file=parsed["text_file"], page_count=parsed["page_count"])
            asset.update(
                effective_dates=parsed["effective_dates"],
                source_date=parsed["effective_dates"][0]
                if len(parsed["effective_dates"]) == 1
                else None,
                source_date_basis="Printed schedule effective date"
                if len(parsed["effective_dates"]) == 1
                else "Multiple or unknown effective dates; inspect each page",
            )
            artifacts.append(asset)
            for record in parsed["records"]:
                record.update(
                    schedule=label,
                    match_method="utility_area_schedule_candidate",
                    eligibility="Candidate schedule for published utility/service area; applicability not established from coordinates",
                )
            records.extend(parsed["records"])
        except Exception as error:
            errors.append({"url": url, "error": f"{type(error).__name__}: {error}"})
    return {
        "records": records,
        "artifacts": artifacts,
        "document_errors": errors,
        "truncated": False,
        "directory_links": [
            a
            for a in page_links(soup, response.url)
            if any(x in a["url"] for x in ["eversource", "nationalgrid", "unitil"])
        ],
        "coverage": "configured major-utility public schedule candidates"
        if selections
        else "utility schedule not configured",
        "limitations": "Amounts are quoted public components, not a complete applicable tariff or a facility bill. Multiple columns, conditions and riders remain visible in the source PDF.",
    }
