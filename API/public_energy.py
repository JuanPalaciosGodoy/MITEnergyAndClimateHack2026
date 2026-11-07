"""Public utility rate schedules as Option 1 site-intake evidence."""

import re
from urllib.parse import urlparse
from .public_utils import inspect_pdf, page, page_links, public_file, saved_page

RATE_DIRECTORY = (
    "https://www.mass.gov/info-details/massachusetts-electric-rates-and-tariffs"
)


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
    directory_links = page_links(soup, response.url)
    domains = []
    if "eversource" in utilities or "nstar" in utilities:
        domains.append("eversource.com")
    if "national grid" in utilities:
        domains.append("nationalgridus.com")
    if "unitil" in utilities:
        domains.append("unitil.com")
    entries = [
        a
        for a in directory_links
        if any((urlparse(a["url"]).hostname or "").endswith(d) for d in domains)
        and ("business" in a["url"].lower() or "all customers" in a["title"].lower())
    ]
    if "eversource.com" in domains:
        west = "western" in utilities or "wmeco" in utilities
        entries = [
            a
            for a in entries
            if "eversource.com" not in a["url"]
            or ("/ema-" not in a["url"] if west else "/wma/" not in a["url"])
        ]
    selections = {}
    errors = []
    for entry in entries[:4]:
        try:
            r, h = page(session, entry["url"])
            artifacts.append(
                saved_page(r, cache_dir, "Public utility tariff discovery page")
            )
            links = page_links(h, r.url)
            # Follow only explicitly published electric-rate summary/tariff links,
            # one level deep. No guessed PDFs or fixed document fallback.
            related = [
                a
                for a in links
                if ".pdf" not in a["url"].lower()
                and urlparse(a["url"]).hostname == urlparse(r.url).hostname
                and re.search(
                    r"summary.of.electric.rates|electric.delivery.rates", a["url"], re.I
                )
            ]
            for child in related[:2]:
                cr, ch = page(session, child["url"])
                artifacts.append(
                    saved_page(
                        cr, cache_dir, "Public utility rate summary discovery page"
                    )
                )
                links.extend(page_links(ch, cr.url))
            for link in links:
                if (
                    ".pdf" in link["url"].lower()
                    and re.search(
                        r"rate|tariff|electric|G.?3",
                        link["title"] + " " + link["url"],
                        re.I,
                    )
                    and not re.search(
                        r"gas|residential", link["title"] + " " + link["url"], re.I
                    )
                ):
                    selections[link["url"]] = link["title"]
            if not selections:
                errors.append(
                    {
                        "url": entry["url"],
                        "error": "No current tariff PDFs exposed by the public page; region/script-only content is not replaced with fixed historical PDFs.",
                    }
                )
        except Exception as error:
            errors.append({"url": entry["url"], "error": str(error)})
    if not entries:
        errors.append(
            {
                "url": RATE_DIRECTORY,
                "error": "No matching public business utility entry discovered.",
            }
        )
    records = []
    for url, label in list(selections.items())[:12]:
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
        "truncated": len(selections) > 12,
        "discovery_url": RATE_DIRECTORY,
        "discovered_documents": list(selections),
        "directory_links": [
            a
            for a in page_links(soup, response.url)
            if any(x in a["url"] for x in ["eversource", "nationalgrid", "unitil"])
        ],
        "coverage": "PDF candidates discovered from current official pages"
        if selections
        else "public PDF discovery incomplete; no fixed-file fallback",
        "limitations": "Amounts are quoted public components, not a complete applicable tariff or a facility bill. Multiple columns, conditions and riders remain visible in the source PDF.",
    }
