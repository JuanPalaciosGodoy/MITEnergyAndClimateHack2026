"""Public assessor/registry records and municipal document-search adapters.

Only anonymous public searches are used. Challenge/login responses are exposed,
never answered with credentials or treated as absence of records.
"""

import io
from datetime import datetime
import re
import zipfile
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlparse, parse_qs

import requests
import shapefile
from pyproj import CRS, Transformer

from ._http import get_json
from .public_utils import (
    page,
    page_links,
    page_text,
    public_file,
    saved_page,
    inspect_pdf,
)

REGISTRY_ZIP = "https://s3.us-east-1.amazonaws.com/download.massgis.digital.mass.gov/shapefiles/state/regdeeds.zip"
LASER = "https://portal.laserfiche.com/Portal/"
REPO = "r-65c20b5e"


def context_address(context):
    parcels = context.get("parcels", {}).get("records", [])
    addresses = {p.get("SITE_ADDR") for p in parcels if p.get("SITE_ADDR")}
    return next(iter(addresses)) if len(addresses) == 1 else None


def assessor(session, municipality, context, cache_dir, refresh=False):
    address = context_address(context)
    if not address:
        return {
            "status": "blocked",
            "records": [],
            "detail": "No unambiguous parcel address was returned.",
        }
    parcels = context["parcels"]["records"]
    parcel = parcels[0]
    urls = {
        "CAMBRIDGE": "https://www.cambridgema.gov/propertydatabase",
        "HOLLISTON": "https://mapublicaccess.tylerhost.net/search/commonsearch.aspx?mode=address&sjur=MA136",
        "NEWTON": "https://gis.vgsi.com/newtonma/",
        "NORTHAMPTON": "https://gis.vgsi.com/northamptonma/",
    }
    if municipality not in urls:
        return {
            "status": "unsupported",
            "records": [],
            "detail": "No public assessor adapter configured for this municipality.",
        }
    if municipality == "NORTHAMPTON":
        settings_url = (
            "https://hosting.tighebond.com/northamptonma_public/assets/js/settings.js"
        )
        response = session.get(settings_url, timeout=30)
        response.raise_for_status()
        prefix = re.search(
            r'"prefix"\s*:\s*"(https://northamptonma.s3.amazonaws.com/recordcards[^" ]+/)"',
            response.text,
        )
        parcel_id = str(parcel.get("MAP_PAR_ID") or "")
        if not prefix:
            return {
                "status": "blocked",
                "records": [],
                "detail": "Published assessor map did not expose the property-card link configuration.",
            }
        card = prefix[1] + parcel_id + ".pdf"
        asset = public_file(
            session,
            card,
            f"Northampton assessor property card — {address}",
            cache_dir,
            refresh,
        )
        parsed = inspect_pdf(asset)
        asset.update(
            text_file=parsed["text_file"],
            text_status=parsed["text_status"],
            page_count=parsed["page_count"],
        )
        year = re.search(r"fy(\d+)", prefix[1])
        return {
            "records": [
                {
                    "address": address,
                    "municipal_parcel_id": parcel_id,
                    "source_url": card,
                    "source_title": "Northampton public assessor property card",
                    "source_date": "20" + year[1] if year else None,
                    "source_date_basis": "Fiscal year in published assessor-card directory",
                    "parcel_match": "published map/lot card link",
                    "published_text": Path(parsed["text_file"]).read_text()[:30000],
                    "text_status": parsed["text_status"],
                    "document_role": "assessor_card",
                    "local_file": asset["local_file"],
                }
            ],
            "artifacts": [asset],
            "query": {"parcel_id": parcel_id, "configuration_url": settings_url},
            "truncated": False,
        }
    if municipality == "NEWTON":
        parcel_id = str(parcel.get("MAP_PAR_ID") or "").replace("'", "''")
        url = "https://gisweb.newtonma.gov/server/rest/services/Browser/MapServer/20"
        params = {
            "f": "json",
            "where": f"MAP_PAR_ID='{parcel_id}'",
            "outFields": "*",
            "returnGeometry": "false",
        }
        data = get_json(session, url + "/query", params)
        return {
            "records": [
                {
                    **f["attributes"],
                    "source_url": url + "/query?" + urlencode(params),
                    "source_title": "Newton official GIS municipal property attributes",
                    "parcel_match": "municipal map/lot identifier",
                    "record_kind": "municipal assessor GIS; not a scanned card",
                }
                for f in data.get("features", [])
            ],
            "query": params,
            "truncated": bool(data.get("exceededTransferLimit")),
            "limitations": "Municipal attributes are retrieved; a scanned assessor card is not supplied by this layer.",
        }
    url = urls[municipality]
    response, soup = page(session, url)
    artifacts = [saved_page(response, cache_dir, f"{municipality} assessor search")]
    if municipality == "CAMBRIDGE":
        parts = address.split(maxsplit=1)
        data = {
            x["name"]: x.get("value", "")
            for x in soup.select("input[type=hidden][name]")
        }
        data.update(
            {
                "body_0$content_0$txtStreetNum": parts[0],
                "body_0$content_0$txtStreetName": parts[1] if len(parts) > 1 else "",
                "body_0$content_0$btnBasicSearchSubmit": "Search",
            }
        )
        response, soup = page(session, url, data=data)
        artifact = saved_page(
            response, cache_dir, f"{municipality} assessor record for {address}"
        )
        artifacts.append(artifact)
        values = {}
        for row in soup.select("table tr"):
            cells = [
                c.get_text(" ", strip=True)
                for c in row.find_all(["th", "td"], recursive=False)
            ]
            if len(cells) == 2:
                values[cells[0]] = cells[1]
        matched = values.get("Map/Lot") == parcel.get("MAP_PAR_ID")
        links = page_links(soup, response.url)
        photos = [
            x
            for x in links
            if any(t in x["url"].lower() for t in ["/photos/", "/sketches/"])
        ]
        records = [
            {
                "address": address,
                "municipal_parcel_id": values.get("Map/Lot"),
                "massgis_parcel_id": parcel.get("LOC_ID"),
                "parcel_match": "exact assessor map/lot"
                if matched
                else "address-search candidate; parcel identifier needs review",
                "reported_assessor_attributes": values,
                "source_url": url,
                "source_title": f"Cambridge assessor — {address}",
                "document_role": "assessor_card",
                "source_date": values.get("Year of Assessment"),
                "source_date_basis": "Municipal assessor assessment year",
                "search_method": "POST public address form",
                "search_address": address,
                "local_file": artifact["local_file"],
            }
        ]
        return {
            "records": records,
            "artifacts": artifacts,
            "documents": [dict(x, kind="assessor_image") for x in photos[:8]],
            "truncated": len(photos) > 8,
            "available_image_count": len(photos),
            "query": {"address": address, "parcel_id": parcel.get("MAP_PAR_ID")},
        }
    if municipality == "HOLLISTON":
        parts = address.split(maxsplit=1)
        data = {x["name"]: x.get("value", "") for x in soup.select("input[name]")}
        data.update(
            inpNumber=parts[0],
            inpStreet=parts[1],
            hdAction="Search",
            PageNum="1",
            mode="ADDRESS",
        )
        response, soup = page(
            session,
            "https://mapublicaccess.tylerhost.net/search/CommonSearch.aspx?mode=ADDRESS",
            data=data,
        )
        artifacts.append(
            saved_page(
                response, cache_dir, f"Holliston public address search {address}"
            )
        )
        text = page_text(soup)
        pin = re.search(r"PARID:\s*(\d+)", text)
        if (
            pin
            and re.sub(r"\s+", " ", address).upper()
            in re.sub(r"\s+", " ", text).upper()
        ):
            # Convert the actual returned session card to a stable published pin URL.
            url = (
                "https://mapublicaccess.tylerhost.net/datalets/datalet.aspx?"
                + urlencode(
                    {
                        "mode": "profileall",
                        "UseSearch": "no",
                        "pin": pin[1],
                        "jur": "MA136",
                    }
                )
            )
            records = []
            documents = []
            errors = []
            for link in [
                {"url": url, "title": "Profile"},
                *[
                    x
                    for x in page_links(soup, response.url)
                    if x["title"] in ("Commercial", "Permits", "Sketch", "Photos")
                ],
            ]:
                mode = parse_qs(urlparse(link["url"]).query).get(
                    "mode", ["profileall"]
                )[0]
                stable = (
                    urljoin(link["url"], urlparse(link["url"]).path)
                    + "?"
                    + urlencode(
                        {"mode": mode, "UseSearch": "no", "pin": pin[1], "jur": "MA136"}
                    )
                )
                if "/idoc2/" in link["url"]:
                    stable = link["url"]
                try:
                    r, h = page(session, stable)
                except requests.RequestException as error:
                    errors.append({"url": stable, "error": str(error)})
                    continue
                asset = saved_page(
                    r, cache_dir, f"Holliston {link['title']} — {address}"
                )
                artifacts.append(asset)
                records.append(
                    {
                        "address": address,
                        "municipal_property_id": pin[1],
                        "section": link["title"],
                        "source_url": url if "/idoc2/" in r.url else r.url,
                        "retrieved_url": r.url,
                        "source_title": f"Holliston assessor {link['title']}",
                        "published_text": page_text(h)[:24000],
                        "parcel_match": "public number/street search; returned address matched",
                        "local_file": asset["local_file"],
                        "source_date": re.search(r"PARCEL YEAR:\s*(20\d{2})", text)[1]
                        if re.search(r"PARCEL YEAR:\s*(20\d{2})", text)
                        else None,
                        "source_date_basis": "Assessor parcel year; section may contain older history",
                    }
                )
                for image in h.select("img[src]"):
                    src = urljoin(r.url, image["src"])
                    if any(t in src.lower() for t in ("sketch", "photo", "image.aspx")):
                        documents.append(
                            {
                                "url": src,
                                "title": f"Holliston {link['title']} image",
                                "kind": "assessor_image",
                            }
                        )
            return {
                "records": records,
                "artifacts": artifacts,
                "documents": documents[:8],
                "truncated": len(documents) > 8,
                "query": {"address": address},
                "document_errors": errors,
                "limitations": "Assessor permit summaries and sketches are historical evidence, not a complete building-plan archive.",
            }
    return {
        "status": "blocked",
        "records": [],
        "artifacts": artifacts,
        "search_url": response.url,
        "detail": "Public provider search page retrieved; automatic property-card selection is not supported by this response. No account/login was attempted.",
        "query": {"address": address, "parcel_id": parcel.get("MAP_PAR_ID")},
    }


def municipal_archive(session, municipality, context, cache_dir):
    address = context_address(context)
    if not address:
        return {
            "status": "blocked",
            "records": [],
            "detail": "No unambiguous parcel address available for document search.",
        }
    if municipality == "NORTHAMPTON":
        search_address = re.sub(
            r"\s+(ST|STREET|AVE|AVENUE|RD|ROAD|DR|DRIVE|LN|LANE)$",
            "",
            address,
            flags=re.I,
        )
        response, soup = page(
            session,
            LASER + "Search.aspx",
            params={
                "repo": REPO,
                "searchcommand": '"' + search_address.replace('"', "") + '"',
            },
        )
        artifacts = [
            saved_page(response, cache_dir, "Northampton public archive address search")
        ]
        payload = {
            "repoName": REPO,
            "searchSyn": '"' + search_address.replace('"', "") + '"',
            "searchUuid": None,
            "sortColumn": "",
            "startIdx": 0,
            "endIdx": 100,
            "getNewListing": True,
            "sortOrder": 0,
            "displayInGridView": False,
        }
        response = session.post(
            LASER + "SearchService.aspx/GetSearchListing",
            json=payload,
            timeout=(10, 30),
        )
        if response.status_code != 200:
            return {
                "status": "blocked",
                "records": [],
                "artifacts": artifacts,
                "query": {
                    "address": address,
                    "public_search_url": artifacts[0]["source_url"],
                },
                "detail": f"Anonymous archive search returned HTTP {response.status_code}: {response.text[:180]}. Public archive form remains available; no authentication attempted.",
            }
        data = response.json()
        data = data.get("data", data.get("d", data))
        records = []
        documents = []
        for item in data.get("results", []):
            modified = re.search(
                r"Last modified (\d{1,2}/\d{1,2}/\d{4})",
                item.get("entryProperties") or "",
            )
            date = (
                datetime.strptime(modified[1], "%m/%d/%Y").date().isoformat()
                if modified
                else None
            )
            entry = item.get("entryId")
            viewer = LASER + "DocView.aspx?" + urlencode({"id": entry, "repo": REPO})
            records.append(
                {
                    "entry_id": entry,
                    "name": item.get("name"),
                    "extension": item.get("extension"),
                    "source_date": date,
                    "source_date_basis": "Archive entry last-modified date; not document preparation or approval date",
                    "entry_properties": item.get("entryProperties"),
                    "metadata": item.get("metadata"),
                    "context_hits": item.get("contexthits"),
                    "source_url": viewer,
                    "search_address": address,
                    "match_method": "archive_fulltext_address_candidate",
                    "location_limit": "Address appears in search index; exact property/document match unverified",
                }
            )
            if str(item.get("extension", "")).lower() in ("pdf", "tif", "tiff", "jpg"):
                documents.append(
                    {
                        "url": LASER
                        + "ElectronicFile.aspx?"
                        + urlencode({"docid": entry, "repo": REPO}),
                        "title": item.get("name") or f"Northampton archive {entry}",
                        "kind": "document",
                        "source_date": date,
                        "source_date_basis": "Archive entry last-modified date; not document preparation or approval date",
                    }
                )
        tokens = search_address.upper().split()
        documents.sort(
            key=lambda d: (
                not all(t in d["title"].upper() for t in tokens),
                not bool(re.search(r"plan|blueprint|drawing|permit", d["title"], re.I)),
            )
        )
        return {
            "records": records,
            "artifacts": artifacts,
            "documents": documents[:5],
            "query": {
                "address": address,
                "public_search_url": artifacts[0]["source_url"],
            },
            "total_results": data.get("hitCount"),
            "truncated": data.get("hitCount", 0) > len(records),
            "available_document_count": len(documents),
            "download_limit": 5,
            "documents_truncated": len(documents) > 5,
        }
    if municipality == "NEWTON":
        url = "https://api-east.viewpointcloud.com/v2/newtonma/search_results"
        response = session.get(
            url, params={"query": address, "limit": 25}, timeout=(10, 30)
        )
        if response.status_code in (401, 403, 429):
            records = []
            parcel_ids = {
                str(p.get("MAP_PAR_ID"))
                for p in context.get("parcels", {}).get("records", [])
            }
            for parcel_id in parcel_ids:
                layer = "https://gisweb.newtonma.gov/server/rest/services/Permitting/MapServer/26"
                params = {
                    "f": "json",
                    "where": "Parcels.MAP_PAR_ID='"
                    + parcel_id.replace("'", "''")
                    + "'",
                    "outFields": "*",
                    "returnGeometry": "false",
                }
                data = get_json(session, layer + "/query", params)
                records.extend(
                    {
                        **f["attributes"],
                        "source_url": layer + "/query?" + urlencode(params),
                        "record_kind": "published wetland filing index; not building blueprint",
                        "match_method": "municipal_parcel_identifier",
                    }
                    for f in data.get("features", [])
                )
            return {
                "status": "partial" if records else "blocked",
                "records": records,
                "query": {"address": address, "url": response.url},
                "detail": f"OpenGov address search returned HTTP {response.status_code}. Official Newton GIS wetland filing index queried by parcel as a public fallback; building blueprints remain inaccessible.",
            }
        response.raise_for_status()
        payload = response.json()
        return {
            "records": payload.get("data", []),
            "query": {"address": address, "url": response.url},
            "truncated": True,
        }
    if municipality == "HOLLISTON":
        url = "https://www.mapsonline.net/simplicity/building_permits.php"
        response, soup = page(
            session, url, params={"client": "hollistonma", "use_react": "no"}
        )
        artifacts = [
            saved_page(response, cache_dir, "Holliston public permitting route")
        ]
        if soup.select("input[type=password]"):
            # The separate anonymous assessor system exposes a historical permit
            # index. It is useful fallback evidence, not a blueprint archive.
            search = "https://mapublicaccess.tylerhost.net/search/commonsearch.aspx?mode=address&sjur=MA136"
            r, h = page(session, search)
            parts = address.split(maxsplit=1)
            data = {x["name"]: x.get("value", "") for x in h.select("input[name]")}
            data.update(
                inpNumber=parts[0],
                inpStreet=parts[1],
                hdAction="Search",
                PageNum="1",
                mode="ADDRESS",
            )
            r, h = page(
                session,
                "https://mapublicaccess.tylerhost.net/search/CommonSearch.aspx?mode=ADDRESS",
                data=data,
            )
            pin = re.search(r"PARID:\s*(\d+)", page_text(h))
            links = (
                [x for x in page_links(h, r.url) if x["title"] == "Permits"]
                if pin and address in page_text(h)
                else []
            )
            records = []
            for link in links[:1]:
                stable = (
                    "https://mapublicaccess.tylerhost.net/datalets/datalet.aspx?"
                    + urlencode(
                        {
                            "mode": "permits",
                            "UseSearch": "no",
                            "pin": pin[1],
                            "jur": "MA136",
                        }
                    )
                )
                r, h = page(session, stable)
                artifacts.append(
                    saved_page(
                        r,
                        cache_dir,
                        f"Holliston public assessor permit index — {address}",
                    )
                )
                records.append(
                    {
                        "address": address,
                        "source_url": r.url,
                        "source_title": "Holliston public assessor permit index",
                        "published_text": page_text(h)[:24000],
                        "record_kind": "historical assessor permit index; not building blueprint",
                        "match_method": "public_address_search_candidate",
                    }
                )
            return {
                "status": "partial" if records else "blocked",
                "records": records,
                "artifacts": artifacts,
                "query": {"address": address, "url": response.url},
                "detail": "Full building-permit route presents an email/password gate. Anonymous assessor address search retrieves its historical permit index when exposed; full blueprints are not supplied.",
            }
        links = [
            x for x in page_links(soup, response.url) if ".pdf" in x["url"].lower()
        ]
        return {
            "records": [
                {
                    "search_address": address,
                    "source_url": response.url,
                    "available_public_documents": len(links),
                }
            ],
            "documents": links[:5],
            "artifacts": artifacts,
            "truncated": len(links) > 5,
        }
    return {
        "status": "unsupported",
        "records": [],
        "detail": "Municipal archive adapter currently covers Holliston, Newton and Northampton; Cambridge permits use separate public datasets.",
    }


def _contains(rings, x, y):
    inside = False
    for ring in rings:
        for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
            if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                inside = not inside
    return inside


def land_records(session, latitude, longitude, context, cache_dir, refresh=False):
    asset = public_file(
        session,
        REGISTRY_ZIP,
        "MassGIS registries of deeds districts",
        cache_dir,
        refresh,
        kind="source_document",
    )
    with zipfile.ZipFile(asset["local_file"]) as archive:
        shp = next(n for n in archive.namelist() if n.lower().endswith(".shp"))
        stem = shp[:-4]
        reader = shapefile.Reader(
            shp=io.BytesIO(archive.read(shp)),
            shx=io.BytesIO(archive.read(stem + ".shx")),
            dbf=io.BytesIO(archive.read(stem + ".dbf")),
        )
        crs = CRS.from_wkt(archive.read(stem + ".prj").decode())
        x, y = Transformer.from_crs(4326, crs, always_xy=True).transform(
            longitude, latitude
        )
        districts = []
        for sr in reader.iterShapeRecords():
            shape = sr.shape
            rings = [
                shape.points[a:b]
                for a, b in zip(
                    shape.parts, list(shape.parts[1:]) + [len(shape.points)]
                )
            ]
            if _contains(rings, x, y):
                districts.append(sr.record.as_dict())
    parcels = context.get("parcels", {}).get("records", [])
    records = []
    artifacts = [asset]
    documents = []
    for district in districts:
        url = district.get("WEBSITE") or district.get("URL")
        row = {
            **district,
            "source_date": "2022-04",
            "source_date_basis": "MassGIS district dataset publication month",
            "source_url": REGISTRY_ZIP,
            "record_kind": "registry jurisdiction; not a deed",
            "match_method": "district_containing_point",
            "parcel_deed_references": [
                {
                    k: p.get(k)
                    for k in [
                        "LOC_ID",
                        "MAP_PAR_ID",
                        "LS_BOOK",
                        "LS_PAGE",
                        "REG_ID",
                        "PLAN_ID",
                        "OWNER1",
                    ]
                }
                for p in parcels
            ],
            "deed_retrieved": False,
            "recorded_plan_retrieved": False,
        }
        if url:
            url = url if url.startswith("http") else "https://" + url
            row["registry_website"] = url
            try:
                response, soup = page(session, url)
                artifacts.append(
                    saved_page(response, cache_dir, "Public registry landing page")
                )
                if soup.select("input[type=password]") or re.search(
                    r"captcha|incapsula|challenge", response.text, re.I
                ):
                    row["document_access"] = "blocked"
                    row["access_detail"] = (
                        "Registry search is gated; no login or challenge attempted."
                    )
                else:
                    # Only actual exposed PDF/image URLs are queued. No guessed
                    # document identifiers or owner-name claims are manufactured.
                    links = [
                        a
                        for a in page_links(soup, response.url)
                        if re.search(r"\.(pdf|tif|jpg)(?:\?|$)", a["url"], re.I)
                    ]
                    documents.extend(links[:5])
                    row["document_access"] = "public_landing_page"
                    row["access_detail"] = (
                        "Book/page references resolved to this registry; no searchable deed result returned by the landing page."
                    )
            except requests.RequestException as error:
                row["document_access"] = "blocked"
                row["access_detail"] = f"{type(error).__name__}: {error}"
        records.append(row)
    return {
        "status": "partial" if not documents else "ok",
        "records": records,
        "artifacts": artifacts,
        "documents": documents,
        "truncated": False,
        "document_access": "blocked_or_not_exposed"
        if not documents
        else "unmatched_public_document_candidates",
        "limitations": "Registry district and book/page metadata are retrieved. A deed or recorded plan is marked retrieved only after an actual document response; blocked image search remains explicit.",
    }
