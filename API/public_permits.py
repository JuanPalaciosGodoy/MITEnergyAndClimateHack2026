"""Anonymous PermitEyes search; addresses and file IDs always come from live data."""

import re
from datetime import datetime
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup

from .public_records import context_address
from .public_utils import page, saved_page

ATTLEBORO_PUBLIC = "https://permiteyes.net/Attleboro/building/homepage.asp"


def address_key(value):
    """Conservative equality: punctuation/case only, never a nearby house number."""
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def attleboro_permits(session, context, cache_dir):
    address = context_address(context)
    if not address:
        return {
            "status": "blocked",
            "records": [],
            "detail": "No unambiguous parcel address to search.",
        }
    response, soup = page(session, ATTLEBORO_PUBLIC)
    artifacts = [saved_page(response, cache_dir, "Attleboro anonymous permit search")]
    # The public page publishes this DataTables request. Do not query a private API.
    endpoint = re.search(
        r'["\']url["\']\s*:\s*["\']([^"\']*getpublichome\.php)["\']', str(soup)
    )
    if not endpoint:
        return {
            "status": "partial",
            "records": [],
            "artifacts": artifacts,
            "detail": "Public permit page no longer exposes its search endpoint.",
        }
    query = {
        "draw": 1,
        "start": 0,
        "length": 100,
        "search[value]": address,
        "search[regex]": "false",
        "order[0][column]": 6,
        "order[0][dir]": "desc",
    }
    for index in range(16):
        query.update(
            {
                f"columns[{index}][data]": index,
                f"columns[{index}][name]": "",
                f"columns[{index}][searchable]": "true",
                f"columns[{index}][orderable]": "true",
                f"columns[{index}][search][value]": "",
                f"columns[{index}][search][regex]": "false",
            }
        )
    result = session.post(
        urljoin(response.url, endpoint[1]), data=query, timeout=(10, 30)
    )
    result.raise_for_status()
    payload = result.json()
    records, documents, errors = [], [], []
    for row in payload.get("data", []):
        cells = [BeautifulSoup(str(cell), "html.parser") for cell in row]
        if len(cells) < 16 or address_key(cells[9].get_text()) != address_key(address):
            continue
        app = cells[0].select_one("[data-application-id]")
        if not app:
            continue
        dates = [
            datetime.strptime(text, "%m/%d/%y").date().isoformat() if text else None
            for index in (7, 8)
            for text in [cells[index].get_text(strip=True)]
        ]
        application_id = app["data-application-id"]
        detail_url = (
            urljoin(
                response.url, app["data-folderpath"] + "/" + app["data-permit-file"]
            )
            + "?"
            + urlencode(
                {
                    "application_id": application_id,
                    "permit_file": app["data-permit-file"],
                    "permit_id": app["data-permit-id"],
                }
            )
        )
        description = cells[6].select_one("[title]")
        records.append(
            {
                "id": cells[6].get_text(strip=True),
                "full_address": cells[9].get_text(" ", strip=True),
                "issue_date": dates[1],
                "applicant_submit_date": dates[0],
                "permit_type": cells[12].get_text(" ", strip=True),
                "permit_number": cells[13].get_text(" ", strip=True),
                "status": cells[14].get_text(" ", strip=True),
                "description": description.get("title") if description else None,
                "source_title": "Attleboro — public historical permit",
                "specific_url": {"url": detail_url},
                "search_address": address,
                "match_method": "exact_normalized_address; historical application, current installation unverified",
            }
        )
        if not cells[15].select_one(".Attachmentclass"):
            continue
        try:
            _, attachment_page = page(
                session,
                urljoin(response.url, "publicattachments.php"),
                params={"application_id": application_id},
            )
            script = str(attachment_page)
            controller = re.search(
                r'url\s*=\s*["\'](controller/publicattachments_controller\.php)["\']',
                script,
            )
            prefix = re.search(
                r'var AttachmentBasePath\s*=\s*["\']([^"\']+)["\']', script
            )
            if not controller or not prefix or "readfiles2.php?file=" not in script:
                raise ValueError(
                    "Public attachment page no longer exposes its download configuration"
                )
            listing = session.post(
                urljoin(response.url, controller[1]),
                data={"action": "displayAttach", "ApplicationId": application_id},
                timeout=(10, 30),
            )
            listing.raise_for_status()
            for item in listing.json().get("Attachments") or []:
                title = (
                    item.get("AttachmentName")
                    or item.get("FileName")
                    or "Public attachment"
                )
                # Scope is physical intake evidence, not insurance/contracts/signatures.
                label = title + " " + item.get("FileName", "")
                if not re.search(
                    r"plan|drawing|single.line|panel|equipment|nameplate|photo|site|sketch",
                    label,
                    re.I,
                ) or re.search(
                    r"insurance|affidavit|contract|authorization|control.document",
                    label,
                    re.I,
                ):
                    continue
                if not item.get("AttachmentPath"):
                    continue
                file_url = (
                    urljoin(response.url, "/readfiles2.php")
                    + "?"
                    + urlencode({"file": prefix[1] + item["AttachmentPath"]})
                )
                documents.append(
                    {
                        "url": file_url,
                        "title": f"Attleboro — {address} — {title}",
                        "source_date": (item.get("UploadDateTime") or "")[:10] or None,
                        "source_date_basis": "Public permit attachment upload date; not drawing revision/as-built date",
                        "permit_id": records[-1]["id"],
                        "kind": "document",
                        "expected_pdf": item.get("FileName", "")
                        .lower()
                        .endswith(".pdf"),
                    }
                )
        except Exception as error:
            errors.append(
                {"url": detail_url, "error": f"{type(error).__name__}: {error}"}
            )
    return {
        "records": records,
        "documents": documents,
        "artifacts": artifacts,
        "document_errors": errors,
        "query_url": result.url,
        "query": query,
        "source_title": "Attleboro — anonymous public permit and plan search",
        "source_url": response.url,
        "search_url": response.url,
        "truncated": int(payload.get("recordsFiltered", 0))
        > len(payload.get("data", []))
        or len(documents) > 10,
        "limitations": "Exact address candidates only. Permitted/proposed work is not evidence of current equipment. The public search is bounded to 100 results and 10 downloaded attachments.",
    }
