# EQORE Option 1 site intake

An unfamiliar Massachusetts latitude/longitude pair → a standardized record of existing site facts, public evidence, provenance and missing information. The MVP is limited to **Option 1: Site data without a site visit**. It collects inputs for later work; it does not generate battery designs, check codes or manage compliance.

```sh
uv venv --python 3.12
uv pip install -r requirements.txt
uv run jupyter lab site_checklist.ipynb
```

```python
from API import lookup_site, checklist_table

site = lookup_site(42.2626, -71.8023)
table = checklist_table(site)
```

The site record has six groups: property, utility/service relationships, electricity/rate schedules, existing electrical information, existing onsite energy equipment, and site geometry/historical documents. [docs/option1_scope.md](docs/option1_scope.md) lists the retained fields and exclusions.

## Active public sources

Eleven adapters support those intake fields:

| Sources | Intake purpose |
| --- | --- |
| `utilities`, `parcels`, `buildings` | Published utility area, property identity/owner/use/dimensions, building outlines. |
| `assessor_records`, `land_records` | Public property cards/photos/sketches and registry/recorded-plan references. |
| `permits`, `electrical_permits`, `solar_permits`, `municipal_archives` | Historical public records and old plans describing the site and equipment. |
| `lber` | Annual purchased electricity and onsite renewable generation, with property/reporting-boundary metadata. |
| `tariffs` | Published utility rate schedules and quoted components as intake evidence. |

Aerial imagery is supporting evidence selected from the live MassGIS catalog. LBER editions and public tariff links are discovered on each request. No fixed example facility, supplied blueprint, private spreadsheet, account information or customer-file input is used. Detailed municipal adapters cover selected towns; statewide sources work for other Massachusetts points and gaps are explicit.

Removed from the active catalog and schema: code/submission requirements, AHJ workflow fields, proposed-system approval/compliance placeholders, environmental/construction screening, municipal PTS context, property valuations/sale prices, insurance/signatures and unrelated fuel/EUI/emissions attributes. `include_all=True` cannot restore them. Original public documents can contain broader information; they remain unmodified source evidence rather than extra modeled fields.

## API and notebooks

```sh
uv run uvicorn API.server:app --reload --reload-dir API --port 8002
```

- `/site?latitude=42.2626&longitude=-71.8023` returns the record, source coverage and evidence manifest.
- `/site/table?...` returns the same record as dated, georeferenced table rows.
- `/sources` advertises scope `option_1_site_intake`, schema **2.1**, source coverage and the 18 table columns.
- `/evidence/...` serves returned evidence-file URLs; `/docs` documents the API.

[site_checklist.ipynb](site_checklist.ipynb) demonstrates the narrow record, evidence and unknown-location checks. [site_api_demo.ipynb](site_api_demo.ipynb) tests every active adapter and HTTP access point. Reopen old notebook tabs from disk and restart their kernels. The running API must advertise schema 2.1; an older process may still occupy port 8001.

## Provenance and evidence

Each row includes `value_unit_of_measurement`. The CSV/table columns follow the requested order, with source links and file paths at the end. [docs/units.md](docs/units.md) documents the audited units, `unknown` versus `not_applicable`, nested-value rows and exact headers. Matching methods remain in full source JSON. Fields distinguish missing, candidate, ambiguous and unreviewed information. Historical permit or nearby disclosure data never becomes verified current equipment automatically. Zero values remain zero; unknowns remain null.

`data/evidence/<latitude6>_<longitude6>/files/` holds public downloads and immutable versions. `runs/<timestamp>/` holds scoped source snapshots, manifests, JSON and CSV/Parquet exports; the root index links the latest run. Every request revalidates files with the provider. `checked_at_utc` records that check, and HTTP 304 preserves the original byte-fetch time. Network failures never silently substitute stale content. `refresh=True` forces full downloads; `download_evidence=False` skips the evidence packet.

Older evidence is retained as history. Old full-scope lookup JSON must be refetched before building a new table, so fields removed from Option 1 cannot reappear through an old saved response.

```sh
uv run python -m unittest discover -s tests -v
uv run python scripts/check_links.py
```

Generated evidence and environments are Git-ignored. See [docs/site_api.md](docs/site_api.md) for the contract, bounds and debugging.
