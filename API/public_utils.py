"""Small shared helpers for public pages, cached files and quoted PDF evidence."""

import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from pypdf import PdfReader

from .evidence import _download_file


def public_file(session, url, title, cache_dir, refresh=False, *, kind="document"):
    directory = Path(cache_dir)
    directory.mkdir(parents=True, exist_ok=True)
    return _download_file(
        session,
        {"source_url": url, "source_title": title, "kind": kind},
        directory,
        refresh,
    )


def page(session, url, *, params=None, data=None):
    response = (
        session.post(url, data=data, timeout=(10, 30))
        if data is not None
        else session.get(
            url, params=params, headers={"Cache-Control": "no-cache"}, timeout=(10, 30)
        )
    )
    response.raise_for_status()
    return response, BeautifulSoup(response.text, "html.parser")


def page_links(soup, base_url):
    """Keep visible public HTTP(S) links; no javascript or login submission."""
    return [
        {
            "url": urljoin(base_url, a["href"]),
            "title": a.get_text(" ", strip=True) or Path(a["href"]).name,
        }
        for a in soup.select("a[href]")
        if urlparse(urljoin(base_url, a["href"])).scheme in ("http", "https")
    ]


def page_text(soup):
    copy = BeautifulSoup(str(soup), "html.parser")
    for tag in copy.select("script,style,nav,header,footer"):
        tag.decompose()
    return copy.get_text(" ", strip=True)


def text_findings(text, url, title, *, page_number=None, role="public_document"):
    """Preserve quoted context rather than inventing equipment or code applicability."""
    records = []
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue
        if role == "tariff":
            if not re.search(
                r"customer|demand|distribution|transmission|energy|delivery|rider|minimum|effective",
                line,
                re.I,
            ):
                continue
            money = re.findall(r"\$\s*([0-9,]+(?:\.[0-9]+)?)", line)
            unit = re.search(r"(?:per|/)\s*(kWh|kW|month|meter|day)\b", line, re.I)
            reference = re.search(r"As per M\.D\.P\.U\..*", line, re.I)
            if not money and not reference:
                continue
            records.append(
                {
                    "component_text": line[:700],
                    "amounts_raw": money,
                    "unit_raw": unit.group(0) if unit else None,
                    "cross_reference": reference.group(0) if reference else None,
                    "rate_assignment": "unassigned public schedule mention; inspect columns and applicability",
                }
            )
        elif re.search(
            r"service|switchboard|transformer|disconnect|panel|battery|generator|solar",
            line,
            re.I,
        ):
            ratings = re.findall(
                r"\b[0-9,]+(?:\.[0-9]+)?\s*(?:kVA|kWh|kW|volts?|amps?|VAC)\b",
                line,
                re.I,
            )
            if not ratings and not re.search(
                r"single.line|panel schedule|equipment schedule",
                line,
                re.I,
            ):
                continue
            records.append(
                {
                    "document_excerpt": line[:700],
                    "ratings_raw": ratings,
                    "interpretation": "published document mention; equipment, revision and present installation unverified",
                }
            )
        if records:
            records[-1].update(
                url=url, source_title=title, page=page_number, document_role=role
            )
        if len(records) >= 20:
            break
    return records


def inspect_pdf(asset, *, role="public_document", max_pages=80):
    reader = PdfReader(asset["local_file"])
    records, pages = [], []
    effective_dates = set()
    for number, p in enumerate(reader.pages[:max_pages], 1):
        text = p.extract_text(extraction_mode="layout") or ""
        pages.append(f"\n--- PAGE {number} ---\n{text}")
        findings = text_findings(
            text,
            asset["source_url"],
            asset["source_title"],
            page_number=number,
            role=role,
        )
        effective = re.search(
            r"(?i)(?:rates\s+)?effective\s*:\s*([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(20\d{2})",
            text,
        )
        date = None
        if effective:
            month = (
                effective[1].replace("Sept", "Sep")
                if effective[1].lower() == "sept"
                else effective[1]
            )
            for fmt in ("%B %d %Y", "%b %d %Y"):
                try:
                    date = (
                        datetime.strptime(f"{month} {effective[2]} {effective[3]}", fmt)
                        .date()
                        .isoformat()
                    )
                    break
                except ValueError:
                    pass
        if date:
            effective_dates.add(date)
        for finding in findings:
            finding.update(
                source_date=date,
                source_date_basis="Effective date printed on the same PDF page"
                if date
                else "No effective date recognized on this page",
            )
        records.extend(findings)
    text_path = Path(asset["local_file"]).with_suffix(".txt")
    text_path.write_text("".join(pages))
    return {
        "records": records,
        "text_file": str(text_path),
        "page_count": len(reader.pages),
        "pages_examined": min(len(reader.pages), max_pages),
        "truncated": len(reader.pages) > max_pages,
        "text_status": "text_extracted"
        if any(p.strip().split("---")[-1].strip() for p in pages)
        else "image_only_or_no_text",
        "ocr_performed": False,
        "effective_dates": sorted(effective_dates),
    }


def saved_page(response, cache_dir, title):
    """Keep the actual POST/search response, rather than re-downloading a form."""
    import hashlib

    directory = Path(cache_dir)
    directory.mkdir(parents=True, exist_ok=True)
    content = response.content
    digest = hashlib.sha256(content).hexdigest()
    path = directory / ("public-page-" + digest[:20] + ".html")
    path.write_bytes(content)
    checked = datetime.now(timezone.utc).isoformat()
    return {
        "source_url": response.url,
        "source_title": title,
        "kind": "reference_page",
        "local_file": str(path.resolve()),
        "content_type": "text/html",
        "sha256": digest,
        "fetched_at_utc": checked,
        "checked_at_utc": checked,
        "cache_status": "downloaded",
        "status": "ok",
    }
