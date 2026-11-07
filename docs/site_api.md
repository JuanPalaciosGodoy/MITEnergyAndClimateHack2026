# Option 1 API contract

Call `lookup_site(latitude, longitude)` once, then `checklist_table(site)` for a Polars table. `lookup_table(latitude, longitude)` combines both. Only coordinates identify the facility. No credentials, supplied project documents, private files or manual-document parameter are accepted.

The API advertises schema **2.1**, scope `option_1_site_intake`, six checklist groups, 11 active adapters and 18 table columns. See [option1_scope.md](option1_scope.md) for field decisions.

## Access points

| Endpoint | Result |
| --- | --- |
| `/health` | Process health without provider queries. |
| `/sources` | Scope, schema, table columns, active sources and coverage. |
| `/site?latitude=...&longitude=...` | Scoped record, source results/coverage, missing facts, evidence manifest and exports. |
| `/site/table?latitude=...&longitude=...` | Dated table rows. |
| `/evidence/{file_path}` | Returned public evidence files; path traversal is rejected. |
| `/docs`, `/redoc`, `/openapi.json` | API documentation. |

Optional query parameters are `sources` (comma-separated active IDs), `refresh`, `download_evidence` and compatibility flag `include_all`. Both `include_all` values return the same Option 1 scope. Removed source IDs return HTTP 422. Utilities always resolves Massachusetts coverage. Parcel-dependent adapters add parcels automatically.

## Sources and bounds

- `utilities`, `parcels`, `buildings`: point queries against public MassGIS services. Up to five intersections; ambiguity is exposed. Parcel attributes are limited to identity, ownership, physical attributes and recorded-document references. Building/parcel geometries remain available for matching and imagery.
- `assessor_records`: Cambridge public address-search cards/photos/sketches, Holliston anonymous assessor sections, Northampton cards discovered from current municipal GIS configuration, and Newton municipal property GIS. Other towns are `unsupported`; no example card is substituted.
- `permits`, `electrical_permits`, `solar_permits`: Cambridge historical candidates within 250 m, capped at ten general/five electrical/five solar records. Focused service/equipment attributes remain; costs, insurance, signatures and unrelated form fields are removed. Permit-reported new service ratings describe historical work, not a proposed EQORE battery design.
- `municipal_archives`: Northampton anonymous address search up to 100 results/five document downloads; Holliston assessor permit index; Newton public address-search attempt. No environmental-filings fallback or unrelated registry PDFs are downloaded as site documents. Full-text mentions require property/document review.
- `land_records`: fresh public registry district data locates the point's registry; parcel book/page references are retained. Blocked or unavailable recorded documents remain explicit. A registry landing page is not a deed.
- `lber`: live DOER catalog discovers annual datasets/layer IDs. Query within 250 m in pages of 100, up to 1,000/dataset. Keep property identity, reporting boundary/year when supplied, purchased electricity and onsite electrical generation. Normalize both published kBtu field spellings to kWh. Do not infer energy reporting year from a publication filename. Exclude other fuels, EUI and emissions.
- `tariffs`: discover public business utility pages from the current Massachusetts directory, follow bounded published summary links and extract at most 12 discovered PDFs. Preserve component quotes, units, page and effective date. Script-only/blocked discovery remains partial; no fixed-file fallback or applicable customer rate is invented.
- Imagery is supporting evidence: select the latest matching non-CIR MassGIS edition and cover the parcel envelope with at most nine tiles, reducing zoom as needed. This is not a multi-parcel facility survey or a proposed equipment layout.

## Table

`checklist item`, `subcategory_name`, `subcategory_value`, `value_unit_of_measurement`, `source_title`, `fetched_at_utc`, `checked_at_utc`, `source_date`, `source_date_basis`, `searched_latitude`, `searched_longitude`, `source_latitude`, `source_longitude`, `source_distance_m`, `source_location_basis`, `data_source`, `local_file`, `file_url`.

The five coordinate/distance columns are Float64; other columns are strings/null. `value_unit_of_measurement` is populated for every row, including expected units for missing measurements. Identifiers/text/booleans use `not_applicable`; unestablished units use `unknown`. Nested quantities are separate rows. See [units.md](units.md) for definitions, source dictionaries, rate denominators and exact CSV order. Zero/false values remain intact. `match_method` remains in full source JSON rather than an extra CSV column.

Canonical checklist fields also carry `unit`, including each ambiguous parcel candidate's own area unit. Raw provider records retain their published field names; use the canonical fields/table for the normalized unit contract. `API/scope.py` continues to prevent broader provider attributes from entering the site record.

Fields distinguish missing, candidate, ambiguous and unreviewed evidence. Nearby records and historical ratings are never silently assigned as verified current equipment. Representative points/centroids can differ from the query coordinate; ungeoreferenced documents keep null source coordinates. Annual consumption is not an interval profile, reported ownership is not title verification, and mapped roof area is not usable battery placement area.

## Evidence, freshness and debugging

Each point has `data/evidence/<latitude6>_<longitude6>/files/` and immutable `runs/<timestamp>/` with scoped source snapshots, manifest, site JSON and CSV/Parquet exports. Root indexes link the latest run. Files have hashes, dates and API-relative URLs. Original public PDFs remain unmodified evidence. Native text extraction examines at most 80 pages, exposes page count/truncation and image-only content, and performs no OCR. Only equipment/rating/diagram evidence and tariff quotes enter the intake record; there is no requirements/code-check extraction.

Every lookup queries the providers and revalidates files. ETag/Last-Modified enable HTTP 304; otherwise download again. `checked_at_utc` records the successful check and `fetched_at_utc` records bytes received. `refresh=True` forces full downloads. Network failures never silently return stale content. `download_evidence=False` skips imagery/linked-file packet export, but required public files can still be downloaded for extraction.

Old evidence is preserved as history; pre-scope JSON cannot be passed to the new table builder. Re-fetch after upgrading to schema 2.1. A saved historical PDF can contain information outside intake without adding those fields to the API.

Inspect `public_coverage`, `source_errors`, source `detail`/`document_errors` and `evidence.errors`. `no_data` is an empty query, not proof of absence; `unsupported` means coverage is missing. Out-of-area points, invalid parameters and removed/unknown sources return 422. The deployment region remains Massachusetts; detailed municipality coverage is limited and advertised.

Run `uv run python -m unittest discover -s tests -v`, then execute both notebooks for live retrieval. `scripts/check_links.py` checks the saved scoped lookup's actual URLs/local files and reports blocked/broken links explicitly.
