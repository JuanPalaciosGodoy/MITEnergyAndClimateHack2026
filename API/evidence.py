"""Local evidence files and a small manifest; no database or crawling service."""

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse
from uuid import uuid4

import requests

from .location import LOCATION_COLUMNS, location_metadata
from .public_gis import imagery_tiles
from .discovery import IMAGERY_CATALOG, latest_raster

FILE_LINK = re.compile(
    r'https?://[^\s"<>]+\.(?:pdf|png|jpg|jpeg|xlsx|docx)(?:\?[^\s"<>]*)?', re.I
)


def _download_file(session, asset, cache, refresh):
    """Cache public files by URL, then keep immutable, content-addressed files."""
    url = asset["source_url"]
    key = hashlib.sha256(url.encode()).hexdigest()[:20]
    metadata_path = cache / f"{key}.json"
    metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
    cached = bool(metadata.get("local_file") and Path(metadata["local_file"]).is_file())
    headers = {"Cache-Control": "no-cache"}
    if cached and not refresh:
        if metadata.get("http_etag"):
            headers["If-None-Match"] = metadata["http_etag"]
        if metadata.get("http_last_modified"):
            headers["If-Modified-Since"] = metadata["http_last_modified"]
    # A network check is mandatory. Failed revalidation never returns stale bytes.
    response = session.get(url, headers=headers, timeout=(10, 45))
    response.raise_for_status()
    checked = datetime.now(timezone.utc).isoformat()
    if response.status_code == 304:
        if not cached:
            raise ValueError("Provider returned 304 without a cached file")
        metadata.update(checked_at_utc=checked, cache_status="revalidated_not_modified")
        temporary = metadata_path.with_suffix(f".{uuid4().hex}.tmp")
        temporary.write_text(json.dumps(metadata, indent=2))
        temporary.replace(metadata_path)
        return {**asset, **metadata, "status": "ok"}
    content_type = response.headers.get("Content-Type", "").split(";")[0]
    if not response.content:
        raise ValueError("Empty download")
    if (
        asset["kind"] == "document"
        and (
            Path(urlparse(url).path).suffix.lower() == ".pdf"
            or asset.get("expected_pdf")
        )
        and not response.content.lstrip().startswith(b"%PDF-")
    ):
        raise ValueError(
            "PDF URL returned non-PDF content (possibly an HTML/login page)"
        )
    # ArcGIS serves some JPEG/PNG tiles as application/octet-stream.
    if response.content.startswith(b"\xff\xd8\xff"):
        content_type = "image/jpeg"
    elif response.content.startswith(b"\x89PNG\r\n\x1a\n"):
        content_type = "image/png"
    if asset.get("kind") == "aerial_image" and not content_type.startswith("image/"):
        raise ValueError(f"Expected imagery, received {content_type}")
    extension = {
        "application/pdf": ".pdf",
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "text/html": ".html",
        "application/json": ".json",
        "image/tiff": ".tif",
        "application/zip": ".zip",
    }.get(content_type)
    extension = extension or Path(urlparse(url).path).suffix or ".bin"
    digest = hashlib.sha256(response.content).hexdigest()
    label = re.sub(r"[^a-z0-9]+", "-", asset["source_title"].lower()).strip("-")[:70]
    path = cache / f"{label}-{key}-{digest[:16]}{extension}"
    temp = path.with_suffix(path.suffix + f".{uuid4().hex}.tmp")
    temp.write_bytes(response.content)
    temp.replace(path)
    metadata = {
        "local_file": str(path.resolve()),
        "sha256": digest,
        "content_type": content_type,
        "fetched_at_utc": checked,
        "checked_at_utc": checked,
        "cache_status": "downloaded" if not cached else "downloaded_again",
        "http_etag": response.headers.get("ETag"),
        "http_last_modified": response.headers.get("Last-Modified"),
        "final_url": response.url,
    }
    temp_metadata = metadata_path.with_suffix(f".{uuid4().hex}.tmp")
    temp_metadata.write_text(json.dumps(metadata, indent=2))
    temp_metadata.replace(metadata_path)
    return {**asset, **metadata, "status": "ok"}


def save_evidence(site, evidence_dir, *, refresh=False):
    """Archive provider JSON, imagery and documents discovered from public sources.

    Nearby permits and discovered plans remain candidates. Downloading a plan
    does not verify that it depicts the requested building or current conditions.
    Each lookup gets a separate manifest; unchanged downloads retain fetch dates.
    """
    root = Path(evidence_dir).resolve()
    location = site["location"]
    latitude, longitude = location["latitude"], location["longitude"]
    site_directory = root / f"{latitude:.6f}_{longitude:.6f}"
    run = (
        site_directory
        / "runs"
        / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    )
    run.mkdir(parents=True, exist_ok=True)
    cache = site_directory / "files"
    cache.mkdir(parents=True, exist_ok=True)
    artifacts = []
    for name, source in site["sources"].items():
        path = run / f"{name}.json"
        source["local_file"] = str(path)
        source["file_url"] = "/evidence/" + quote(
            path.relative_to(root).as_posix(), safe="/"
        )
        path.write_text(json.dumps(source, indent=2, ensure_ascii=False))
        artifacts.append(
            {
                "kind": "source_snapshot",
                "source_id": name,
                "source_title": source["source_title"],
                "source_url": source.get("query_url") or source["source_url"],
                "local_file": str(path),
                "fetched_at_utc": source["retrieved_at_utc"],
                "checked_at_utc": source.get("checked_at_utc"),
                "source_date": None,
                "source_date_basis": "Per-record dates are in the checklist; snapshot can contain multiple dates",
                "status": "ok",
                "provider_status": source["status"],
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    for name in ("electrical_permits", "solar_permits"):
        for record in site["sources"].get(name, {}).get("records", []):
            path = run / f"{name}-{record['id']}.json"
            path.write_text(json.dumps(record, indent=2, ensure_ascii=False))
            artifacts.append(
                {
                    "kind": "permit_record",
                    "source_id": name,
                    "source_title": f"{site['sources'][name]['source_title']} — {record['id']}",
                    "source_url": record["specific_url"]["url"],
                    "local_file": str(path),
                    "status": "ok",
                    "fetched_at_utc": site["sources"][name]["retrieved_at_utc"],
                    "source_date": (record.get("issue_date") or "")[:10] or None,
                    "source_date_basis": "Permit issue date"
                    if record.get("issue_date")
                    else "Issue date unavailable",
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "match_status": "Nearby permit candidate; verify building, service and current equipment",
                    **record.get("_location", {}),
                }
            )
    zoom, tiles, image_extent = imagery_tiles(site["sources"], latitude, longitude)
    assets = []
    imagery = None
    try:
        with requests.Session() as session:
            imagery = latest_raster(session, "imagery")
        for x, y in tiles:
            assets.append(
                {
                    "kind": "aerial_image",
                    "source_id": "imagery",
                    "source_title": f"MassGIS {imagery['source_date']} parcel-envelope imagery — tile {zoom}/{y}/{x}",
                    "source_url": f"{imagery['url']}/tile/{zoom}/{y}/{x}",
                    "source_date": imagery["source_date"],
                    "source_date_basis": "Program year from currently published imagery catalog",
                    "match_status": "Parcel-envelope tile; no placement suitability inferred",
                    "tile": {"zoom": zoom, "x": x, "y": y},
                    **location_metadata(
                        latitude,
                        longitude,
                        math.degrees(
                            math.atan(
                                math.sinh(math.pi * (1 - 2 * (y + 0.5) / 2**zoom))
                            )
                        ),
                        (x + 0.5) / 2**zoom * 360 - 180,
                        basis="Derived tile center",
                        match_method="parcel_envelope_tiles",
                    ),
                }
            )
    except Exception as error:
        artifacts.append(
            {
                "kind": "aerial_image",
                "source_id": "imagery",
                "source_title": "MassGIS live imagery discovery",
                "source_url": IMAGERY_CATALOG,
                "status": "error",
                "local_file": None,
                "fetched_at_utc": None,
                "error": str(error),
            }
        )
    for name, source in site["sources"].items():
        for asset in source.get("artifacts", []):
            artifacts.append(
                {
                    **asset,
                    "source_id": name,
                    "match_status": "Retrieved public source; site association and dates require review",
                    "source_date": asset.get("source_date"),
                    "source_date_basis": asset.get(
                        "source_date_basis", "Public content date unavailable"
                    ),
                    **location_metadata(
                        latitude,
                        longitude,
                        basis="Public document location not established",
                        match_method=source["match_method"],
                    ),
                }
            )
            if asset.get("text_file"):
                path = Path(asset["text_file"])
                artifacts.append(
                    {
                        "kind": "extracted_text",
                        "source_id": name,
                        "source_title": asset["source_title"] + " — extracted text",
                        "source_url": asset["source_url"],
                        "local_file": str(path),
                        "status": "ok",
                        "fetched_at_utc": asset["fetched_at_utc"],
                        "checked_at_utc": asset.get("checked_at_utc"),
                        "source_date": None,
                        "source_date_basis": "Text derivative retains original document provenance",
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    }
                )
        for doc in source.get("documents", [])[:10]:
            assets.append(
                {
                    "kind": doc.get("kind", "document"),
                    "source_id": name,
                    "source_url": doc.get("url") or doc.get("source_url"),
                    "source_title": doc.get("title")
                    or doc.get("source_title")
                    or "Public linked document",
                    "expected_pdf": doc.get("expected_pdf", False),
                    "source_date": doc.get("source_date"),
                    "source_date_basis": doc.get(
                        "source_date_basis", "Linked public document date not verified"
                    ),
                    "match_status": "Public document candidate; review address, parcel, date, revision and present applicability",
                }
            )
    reference = site["references"]["permits"]
    if reference.get("url"):
        assets.append(
            {
                "kind": "reference_page",
                "source_id": "municipal_portal",
                "source_title": f"{location['municipality']} — municipal permit portal",
                "source_url": reference["url"],
                "source_date": None,
                "source_date_basis": "Page has no verified content date",
                "match_status": "General municipal reference",
                **location_metadata(
                    latitude,
                    longitude,
                    basis="Municipal reference page; no facility point",
                    match_method="municipal_reference",
                ),
            }
        )
    with requests.Session() as session:
        # Fetch at most three detailed permit records, favoring building/electrical
        # records. The complete bounded finder response remains in permits.json.
        permits = site["sources"].get("permits", {}).get("records", [])
        ordered = sorted(
            permits,
            key=lambda r: (
                not any(
                    k in r.get("permit_type", "").lower()
                    for k in ("building", "electrical")
                )
            ),
        )
        for record in ordered[:3]:
            url = (record.get("specific_url") or {}).get("url")
            if not url or urlparse(url).hostname != "data.cambridgema.gov":
                continue
            asset = {
                "kind": "permit_detail",
                "source_id": "permits",
                "source_title": f"Cambridge — {record.get('permit_type')} permit {record.get('id')}",
                "source_url": url,
                "source_date": (record.get("issue_date") or "")[:10] or None,
                "source_date_basis": "Permit issue date"
                if record.get("issue_date")
                else "Issue date unavailable",
                "match_status": "Nearby candidate; requires site/building confirmation",
                **record.get("_location", {}),
            }
            assets.append(asset)
        for asset in assets:
            try:
                artifact = _download_file(session, asset, cache, refresh)
            except (requests.RequestException, ValueError, OSError) as error:
                artifact = {
                    **asset,
                    "status": "error",
                    "local_file": None,
                    "fetched_at_utc": None,
                    "error": f"{type(error).__name__}: {error}",
                }
            artifacts.append(artifact)
            if (
                artifact["status"] == "ok"
                and artifact.get("content_type") == "application/pdf"
            ):
                from .public_utils import inspect_pdf

                try:
                    parsed = inspect_pdf(artifact)
                    artifact.update(
                        text_status=parsed["text_status"],
                        page_count=parsed["page_count"],
                        pages_examined=parsed["pages_examined"],
                        text_truncated=parsed["truncated"],
                        ocr_performed=False,
                    )
                    site.setdefault("document_findings", []).extend(parsed["records"])
                    path = Path(parsed["text_file"])
                    artifacts.append(
                        {
                            "kind": "extracted_text",
                            "source_id": artifact["source_id"],
                            "source_title": artifact["source_title"]
                            + " — extracted text",
                            "source_url": artifact["source_url"],
                            "local_file": str(path),
                            "status": "ok",
                            "source_date": artifact.get("source_date"),
                            "source_date_basis": artifact.get("source_date_basis"),
                            "fetched_at_utc": artifact["fetched_at_utc"],
                            "checked_at_utc": artifact.get("checked_at_utc"),
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        }
                    )
                except Exception as error:
                    artifact["text_extraction_error"] = str(error)
        # Retrieve public document links exposed by those detailed permit JSONs.
        # No recursive website traversal or login-protected portal scraping.
        links = []
        for artifact in artifacts:
            if artifact["kind"] == "permit_detail" and artifact["status"] == "ok":
                text = Path(artifact["local_file"]).read_text()
                links.extend(
                    (url, artifact)
                    for url in FILE_LINK.findall(text.replace("\\/", "/"))
                )
        for url, parent in dict(links).items():
            if (
                sum(
                    a["kind"] == "document" and a["source_id"] == "permits"
                    for a in artifacts
                )
                >= 5
            ):
                break
            if not (urlparse(url).hostname or "").endswith(".cambridgema.gov"):
                continue
            asset = {
                "kind": "document",
                "source_id": "permits",
                "source_title": "Cambridge — permit-linked "
                + Path(urlparse(url).path).name,
                "source_url": url,
                "source_date": None,
                "source_date_basis": "Document date not verified",
                "match_status": "Permit-linked candidate; verify building and revisions",
                **{key: parent.get(key) for key in LOCATION_COLUMNS},
                "source_location_basis": "Associated permit location; document extent unverified",
            }
            try:
                artifacts.append(_download_file(session, asset, cache, refresh))
            except (requests.RequestException, ValueError, OSError) as error:
                artifacts.append(
                    {
                        **asset,
                        "status": "error",
                        "local_file": None,
                        "fetched_at_utc": None,
                        "error": str(error),
                    }
                )
    for artifact in artifacts:
        artifact.setdefault("searched_latitude", latitude)
        artifact.setdefault("searched_longitude", longitude)
        if artifact.get("local_file"):
            artifact["file_url"] = "/evidence/" + quote(
                Path(artifact["local_file"]).relative_to(root).as_posix(), safe="/"
            )
    exports = {
        name: {
            "local_file": str(run / filename),
            "file_url": "/evidence/"
            + quote((run / filename).relative_to(root).as_posix(), safe="/"),
        }
        for name, filename in (
            ("site_json", "site.json"),
            ("checklist_csv", "checklist.csv"),
            ("checklist_parquet", "checklist.parquet"),
        )
    }
    manifest = {
        "imagery_coverage": {
            "bbox_wgs84": image_extent,
            "zoom": zoom,
            "tile_count": len(tiles) if imagery else 0,
            "dataset": imagery,
            "scope": "parcel envelope",
        },
        "location": location,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "site_directory": str(site_directory),
        "run_directory": str(run),
        "files": artifacts,
        "exports": exports,
    }
    path = run / "manifest.json"
    encoded = json.dumps(manifest, indent=2, ensure_ascii=False)
    path.write_text(encoded)
    latest = site_directory / "manifest.json"
    temporary = latest.with_suffix(f".{uuid4().hex}.tmp")
    temporary.write_text(encoded)
    temporary.replace(latest)
    index = site_directory / "README.md"
    lines = [
        f"# Evidence for {latitude}, {longitude}",
        "",
        f"Municipality: {location.get('municipality') or 'unresolved'}",
        "",
        "Each run preserves the searched coordinates, raw records, source dates and matching limitations.",
        "",
        "## Latest exports",
        "",
    ]
    lines.extend(
        f"- [{name}]({quote(Path(export['local_file']).relative_to(site_directory).as_posix(), safe='/')})"
        for name, export in exports.items()
    )
    lines.extend(["", "## Evidence files", ""])
    for asset in artifacts:
        if asset["status"] == "ok":
            relative = quote(
                Path(asset["local_file"]).relative_to(site_directory).as_posix(),
                safe="/",
            )
            source_link = (
                f" [Public source]({asset['source_url']})"
                if asset.get("source_url")
                else " Provider not queried for this location."
            )
            lines.append(
                f"- [{asset['source_title']}]({relative}) — source date: {asset.get('source_date') or 'unknown'}; fetched: {asset.get('fetched_at_utc') or 'not retrieved'}."
                + source_link
            )
        else:
            lines.append(
                f"- {asset['source_title']}: download failed — {asset.get('error', 'unknown error')}"
            )
    index.write_text("\n".join(lines) + "\n")
    return {
        "index_file": str(index),
        "index_url": "/evidence/" + quote(index.relative_to(root).as_posix(), safe="/"),
        "imagery_coverage": {
            "bbox_wgs84": image_extent,
            "zoom": zoom,
            "tile_count": len(tiles) if imagery else 0,
            "dataset": imagery,
        },
        "site_directory": str(site_directory),
        "directory": str(run),
        "manifest_file": str(path),
        "latest_manifest_file": str(latest),
        "exports": exports,
        "files": artifacts,
        "errors": [a for a in artifacts if a["status"] == "error"],
    }
