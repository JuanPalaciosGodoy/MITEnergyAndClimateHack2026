# Public coordinate lookup contract

Use `lookup_site(latitude, longitude)` to fetch once, then `checklist_table(site)` for a Polars table. `lookup_table(latitude, longitude)` combines both. No API keys or customer information are used.

## Access points

| Endpoint | Result |
| --- | --- |
| `GET /health` | Process health; does not query external services. |
| `GET /sources` | API version, schema 1.3, 17 table columns, default sources and source descriptions. |
| `GET /site?latitude=...&longitude=...` | Public lookup JSON, checklist, coverage, raw source records, evidence manifest and exports. |
| `GET /site/table?latitude=...&longitude=...` | The dated, georeferenced table as JSON rows. |
| `GET /evidence/{file_path}` | A saved public file under the configured evidence directory; traversal is rejected. |
| `GET /docs`, `/redoc`, `/openapi.json` | API documentation and OpenAPI schema. |

Optional query parameters: `sources` (comma-separated IDs), `refresh` (false by default), `download_evidence` (true by default), `include_all` (compatibility parameter; both views are public-only). Utilities is always queried. `assessor_records`, `municipal_archives`, `land_records`, `lidar`, `wetlands`, `environmental`, `activity_use_limits` and `protected_habitat` also need parcels; they are added automatically.

`download_evidence=False` does not prevent caching public PDFs/spreadsheets needed to extract source records. It skips imagery/linked-file downloads and the exported evidence packet. Evidence HTTP links are populated when the packet is saved.

## Sources and bounds

The original sources remain: `utilities`, `parcels`, `buildings`, `lber`, `flood`, `permits`, `electrical_permits`, `solar_permits`, `public_resources`, `elevation`.

Ten additional adapters are `assessor_records`, `municipal_archives`, `land_records`, `lidar`, `wetlands`, `environmental`, `activity_use_limits`, `protected_habitat`, `masscec`, `tariffs`.

- Parcel/building intersections: up to five returned assessor/features; ambiguous records are retained rather than silently selected.
- Cambridge permit candidates: 250 m, ten general permits, five detailed electrical and five solar records. Electrical queries prioritize service/equipment fields. Raw non-null electrical/solar attributes are exposed alongside familiar labels. Public parcel/address relationships are not verified active utility connections.
- LBER: 2024 and 2025, 250 m; pages of 100 up to 1,000/year. Each row retains the reporting year, original attributes and that year's actual query URL. Per-year failures and truncation remain visible. Annual consumption is not an interval profile.
- Northampton archive: public anonymous full-text search using the parcel address, up to 100 search results, five native PDF/TIFF/JPEG downloads. Address matches in document titles take priority over incidental mentions. Result and document limits are separate. A search hit is not a verified blueprint/building match.
- Holliston: public assessor address forms retrieve profile/commercial/permit/sketch sections, and the historical permit index provides an archive fallback. The separate building-permit portal is gated; no login is attempted.
- Newton: official GIS municipal attributes and parcel-linked wetland filing index. OpenGov's 403 is preserved; building blueprints are not claimed retrieved.
- Northampton property cards: the city-linked GIS configuration exposes the actual fiscal-year card prefix; cards are requested by parcel ID. Cambridge uses its public number/street form; Cambridge photos/sketches are capped at eight. Newton GIS records are not scanned cards.
- Registry: public MassGIS district polygons route the point to a registry; parcel book/page references stay intact. District website access is attempted anonymously. A blocked registry produces `partial` with `deed_retrieved=false` and `recorded_plan_retrieved=false`. Unmatched landing-page PDFs are never treated as the parcel's deed.
- Environmental layers: use an unambiguous parcel polygon; otherwise use the point. Wetlands/habitat intersect the feature; classified contamination and AUL sites use a 250 m buffer. Up to 100 records/layer, with truncation exposed. Query geometry is POSTed to avoid oversized URLs; the reproducible request body remains in the source JSON. The source link opens layer metadata.
- Lidar: requested point plus a 3×3 parcel-envelope grid, NAVD88 meters, and a 512×512 TIFF of that envelope. Sample ranges are not parcel-wide extrema. The acquisition range is 2013–2021; exact flight dates are unknown.
- Imagery: complete parcel-envelope coverage with at most nine tiles; reduce zoom instead of dropping parts of a large parcel. The envelope does not identify every parcel belonging to an operational facility.
- PTS: all published attributes from up to 50 municipality rows; total count and truncation remain visible. City/ZIP-only data cannot identify the searched facility or supply its coordinates. Report snapshot date differs from each installation date.
- Tariffs: public Eversource Cambridge/eastern/western and National Grid candidate schedules/summaries. Cambridge G-3's M.D.P.U. No. 1 reference is followed. Quotes retain dollar amounts, units, page, effective date where printed, and original conditions. Multiple columns are deliberately unassigned. Unitil/municipal light schedules are not configured. These are public candidates, not a tariff applicability decision.
- Requirements: download state references/battery guidance and supported municipal pages; extract submission excerpts and up to three related commercial/site-plan checklist PDFs per page. Cambridge, Holliston, Newton and Northampton have municipal resources configured. A blocked page remains an error. Historical guides and conditional scope statements never become binding project requirements.

## Table and interpretation

The 17 columns are:

`checklist item`, `subcategory_name`, `subcategory_value`, `data_source`, `source_title`, `fetched_at_utc`, `source_date`, `source_date_basis`, `local_file`, `file_url`, `searched_latitude`, `searched_longitude`, `source_latitude`, `source_longitude`, `source_distance_m`, `source_location_basis`, `match_method`.

Values are strings/null; nested attributes are JSON strings. The five coordinate/distance columns are Float64. Candidate indexes keep fields from one record together. Full raw provider JSON remains in `sources` and snapshots. Zero/false values are retained.

Fetch timestamps describe successful retrieval. Cached files retain their original timestamp. Source dates preserve their actual precision: fiscal/reporting year, imagery year, mosaic acquisition range, permit issue date or PDF effective date. Fetch time never substitutes for source time. Page quotes can have a date different from another page of the same schedule.

Search coordinates are always attached. Source coordinates come from reported WGS84 points, returned centroids or explicitly labeled polygon-envelope centers. Distances are to representative points, not parcel edges. Municipal/context records and ungeoreferenced documents keep null source coordinates. LBER, archives, equipment mentions, tariffs and PTS remain candidates or context. Canonical present service ratings and installed equipment remain null unless there is adequate site-specific evidence; historical mentions never populate them automatically.

The twelve public checklist categories have the same field names across sites. This phase excludes consent, account identifiers, customer bills, interval-data requests and proposed equipment-sizing inputs. Missing public/engineering facts are retained honestly rather than fabricated to eliminate nulls.

## Saved evidence

```text
data/evidence/<latitude6>_<longitude6>/
  README.md
  manifest.json
  files/                  # Cached HTML, images, PDFs, spreadsheets, TIFF, derived text
  runs/<UTC timestamp>/   # Raw sources, manifest, site.json, checklist.csv/parquet
```

Successful artifacts have SHA-256 hashes and API-relative URLs. Source snapshots, extracted text and original PDFs are separate evidence. PDF extraction reads native text from at most 80 pages. `text_status`, `page_count`, `pages_examined`, `text_truncated`, `ocr_performed` or source extraction metadata identify limits; image-only/scanned pages are not OCRed. Quotes identify document/page and do not prove current equipment, approval or as-built status.

Older files remain intact. `refresh=True` creates content-versioned files rather than overwriting previous evidence. `evidence.exports` links to the full response and table. Generated data is ignored in Git.

## Debugging and verification

Inspect `public_coverage`, `source_errors`, `sources.<id>.detail`, `resource_errors`, `document_errors`, `document_access` and `evidence.errors`. `ok` means a public response yielded records; it does not establish a site match. `no_data` does not establish absence. Partial/blocked/unsupported responses are not represented as successful complete retrievals.

Use `sources=<id>` to isolate an adapter. Unknown IDs, invalid coordinates and points outside Massachusetts return HTTP 422. Independent provider failures preserve other results. Public login/challenge responses are not bypassed.

Run `uv run python -m unittest discover -s tests -v` for offline matching/API/extraction regressions. Run both notebooks for live retrieval and evidence-byte checks. `uv run python scripts/check_links.py [saved-site.json]` checks actual remote responses and local files, writes `data/processed/link_checks.csv`, and returns nonzero for blocked/broken links. Public pages can be browser-accessible or search-indexed while returning 403/404 to anonymous scripted requests; those outcomes remain visible.
