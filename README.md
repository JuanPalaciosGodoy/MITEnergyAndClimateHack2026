# Massachusetts public site-evidence API

Latitude and longitude → a Polars checklist, raw public records and a coordinate-specific evidence folder. This phase uses anonymous public sources only. No customer uploads, credentials, account information or authorization workflow is required.

```sh
uv venv --python 3.12
uv pip install -r requirements.txt
uv run jupyter lab site_checklist.ipynb
```

```python
from API import lookup_site, checklist_table

site = lookup_site(42.359, -71.093)
table = checklist_table(site)
print(site["public_coverage"])
```

Start the HTTP API with `uv run uvicorn API.server:app --reload --reload-dir API --port 8002`. Call `/site/table?latitude=42.359&longitude=-71.093` for table rows or `/site` for JSON and evidence. `/sources` describes all 20 adapters; `/docs` shows the API. Returned `/evidence/...` links serve saved files. [site_api_demo.ipynb](site_api_demo.ipynb) tests every adapter and HTTP access point.

The notebooks require schema **1.3**. If an old notebook tab is open, close it without overwriting the updated file, reopen it, restart the kernel and run all cells. An earlier API process may still occupy port 8001; the demos use 8002.

## Public coverage

| Area | Implemented retrieval | Remaining public-access limits |
| --- | --- | --- |
| Property and service evidence | Full parcel attributes; Cambridge address-search cards/photos/sketches; Holliston anonymous assessor profile/commercial/permit/sketch sections; Northampton FY2026 PDF cards; Newton official municipal property attributes. Public electrical permits expose parcel/address/meter-count relationships. | Historical permits do not establish an active service-to-building assignment. Newton GIS attributes are not a scanned card. |
| Municipal archives | Northampton anonymous full-text address search and public document downloads. Holliston assessor permit index fallback. Newton parcel-linked wetland filing index fallback. | Holliston full building-permit portal requires login; Newton OpenGov returns 403. Those blueprints are not retrieved. Search mentions remain candidates. |
| Recorded property documents | Point-in-registry-district lookup using MassGIS boundaries, parcel book/page references, and an anonymous public registry access attempt. | The tested Middlesex South image/search route is blocked. No deed/plan is marked retrieved merely because jurisdiction and book/page are known. |
| Building energy | Paginated 2024 and 2025 LBER queries within 250 m, retaining every published non-null attribute, including EUI, fuels, generation and reporting boundaries where supplied. | Reporting boundaries and nearby sites need review. Up to 1,000 records/year, with truncation exposed. |
| Terrain and environmental | Lidar point/envelope-grid samples and TIFF; parcel/point wetlands and habitat; contamination/AUL candidates within 250 m; FEMA and Open-Meteo context. Imagery tiles cover the full parcel envelope. | These are screening layers, not clearance, engineering surveys or a complete multi-parcel facility boundary. |
| MassCEC PTS | Public report equipment, installation, cost, capacity and utility fields as municipality context. | Report has city/ZIP, no street/coordinates; no facility assignment. First 50 municipal rows, with count/truncation exposed. |
| Tariffs | Eversource regional and National Grid candidate PDFs, rate-component quotes, units, page references, effective dates and G-3 cross-references. | Curated major-utility coverage; no applicable facility rate or complete bill calculation inferred. |
| Submission guidance | State building/fire/electrical/battery references; municipal responsibilities and submission excerpts; linked commercial/site-plan checklists when exposed. | Rules remain conditional on project scope. Contacts alone do not establish project jurisdiction. No project-specific compliance determination. |

All sources are enabled by default. Use `sources=["parcels", "buildings"]` for a smaller request. Utilities always resolves the town; parcel-dependent adapters automatically request parcels. Independent sources run in a bounded thread pool, followed by the parcel-dependent stage. There is no database, queue, crawler framework or OCR service.

## Evidence and debugging

Each point has `data/evidence/<latitude6>_<longitude6>/files/` for cached downloads and `runs/<UTC timestamp>/` for immutable source snapshots, manifests, JSON and CSV/Parquet exports. Its root `README.md` indexes the latest evidence. `refresh=True` refreshes cached public files while preserving older versions.

Every table row retains the original four columns plus readable source title, fetch/source dates, date meaning, local/API file links, searched/source coordinates, distance and match method. Unknown source dates and locations stay null. PDF quotes preserve page numbers; text extraction examines up to 80 pages and reports image-only content or truncation. Aerial imagery reduces zoom when necessary to cover the entire parcel envelope with at most nine tiles.

`download_evidence=False` skips the exported evidence package; source files needed for extraction are still cached. Check `public_coverage`, `source_errors`, source `detail`/`document_errors`, and `evidence.errors`. `no_data` is an empty query, not proof of absence. `partial`, `blocked`, `unsupported` and `error` are explicit outcomes.

```sh
uv run python -m unittest discover -s tests -v
uv run python scripts/check_links.py
```

The link checker uses the short notebook's saved lookup and writes `data/processed/link_checks.csv`. Blocked/broken links fail visibly. Generated evidence, environments and credentials are Git-ignored. See [docs/site_api.md](docs/site_api.md) for the contract and limits.
