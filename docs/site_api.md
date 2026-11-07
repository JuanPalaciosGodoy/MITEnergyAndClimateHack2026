# Massachusetts site API

Provide WGS84 latitude and longitude. The backend queries public services and returns the same twelve checklist categories for every site. It exposes real source records, provenance, candidate matches and missing inputs. It uses FastAPI, requests and Polars. There is no database, queue or scraping framework.

## Start

From the repository root, install the requirements and start the server. The existing `.env` can supply an optional OpenEI key. The public `DEMO_KEY` supports small tariff tests. No EIA key is needed for this endpoint.

```sh
uv pip install -r requirements.txt
uv run --env-file .env uvicorn API.server:app --reload --port 8001
```

Interactive documentation is at [http://127.0.0.1:8001/docs](http://127.0.0.1:8001/docs). The machine-readable schema is at `/openapi.json`.

```sh
curl 'http://127.0.0.1:8001/site?latitude=42.359&longitude=-71.093'
```

Choose a point on the actual facility. The example intersects an MIT campus parcel in Cambridge whose assessor address is 60 Vassar St. A campus parcel, building outline and meter can have different boundaries. An address returned by an assessor is not a verified customer service address.

## Call from Python or a frontend

For a Polars table with exactly `checklist item`, `subcategory_name`, `subcategory_value`, and `data_source`, use the short [site_checklist.ipynb](../site_checklist.ipynb) notebook or call:

```python
from API import lookup_table

table = lookup_table(42.359, -71.093)
```

Values are strings or null because the value column contains several data types. Candidate records expand into labeled rows such as `annual_energy_candidates[1].annual_electricity_kwh`. Municipal solar context shows the municipality, registered-system count and workbook date. Ambiguous matches retain their candidate labels. Failed providers add `*.error` rows rather than substituting estimated or cached values. `data_source` is the provider URL, or the explicit user-input label for coordinates. Missing customer inputs without retrieved evidence have null source and value.

If the full lookup has already been fetched, `checklist_table(site)` formats that response without additional provider calls. Full raw records, units and review statuses remain in the full response.

Use the Python function directly when another Python backend owns the HTTP layer.

```python
from API import lookup_site

site = lookup_site(42.359, -71.093)
print(site["location"])
print(site["missing_fields"])
```

Or call the running API.

```python
import requests

response = requests.get(
    "http://127.0.0.1:8001/site",
    params={"latitude": 42.359, "longitude": -71.093},
    timeout=120,
)
response.raise_for_status()
site = response.json()
```

```javascript
const query = new URLSearchParams({ latitude: 42.359, longitude: -71.093 });
const response = await fetch(`http://127.0.0.1:8001/site?${query}`);
if (!response.ok) throw new Error(await response.text());
const site = await response.json();
console.log(site.checklist, site.missing_fields);
```

Local frontend origins on ports 3000 and 5173 are allowed by default. Set `CORS_ORIGINS` to a comma-separated list before starting the server for another frontend origin. This is a local development API with no authentication layer.

## Routes

| Route | Result |
| --- | --- |
| `GET /site?latitude=...&longitude=...` | Location, public evidence, twelve checklist categories, manual references and missing fields. |
| `GET /site/table?latitude=...&longitude=...` | JSON rows with exactly the four table columns. Source failures remain visible in `*.error` rows. Accepts the same optional `sources` and `refresh` parameters. |
| `GET /site?...&sources=parcels,buildings,lber` | Fetch only the selected automated sources. Utilities is always included for municipality and Massachusetts coverage. |
| `GET /site?...&refresh=true` | Download a fresh MassCEC workbook. Other providers are queried on every request. |
| `GET /sources` | Provider IDs, URLs, descriptions, spatial matching methods and manual references. |
| `GET /health` | Process health without calling external providers. |

The direct Python function accepts `sources=["parcels", "buildings"]`, `refresh=True`, and an optional `cache_dir` for the downloaded workbook.

## Automated sources

| ID | What is retrieved | Matching and limits |
| --- | --- | --- |
| `utilities` | Official MassGIS municipality and published electricity provider records. | Municipality containing the point. Provider candidates need confirmation against a bill. |
| `parcels` | Official assessor records and parcel geometry, including owner, address, fiscal year, use, zoning and deed references. | Up to five parcel records intersecting the point. Multiple matches remain ambiguous. A parcel can contain several buildings. |
| `buildings` | Official MassGIS building/roof outlines, area and source-date attributes. | Up to five outlines intersecting the point. Roof area is distinct from floor area and usable battery space. |
| `lber` | Energy-year 2025 disclosures, with normalized address, area and purchased electricity in kWh alongside raw attributes. | Up to five candidates within 250 m. No automatic site or meter assignment. |
| `tariffs` | Two nearby commercial URDB candidates with effective dates and full nested `rate` objects. | Candidate utility/rates can be historical or inapplicable. Confirm actual rate code and dates from bills and official tariffs. |
| `solar` | A five-row sample and total record count for the municipality from the public January 2025 MassCEC workbook. | Municipal context only. This workbook has no street addresses or coordinates and cannot identify the facility's solar system. |
| `flood` | FEMA flood-zone attributes at the coordinate. | A point assessment does not cover the entire parcel. No returned feature leaves risk unknown. |
| `elevation` | Open-Meteo terrain elevation in meters. | Terrain sample, not a survey, foundation assessment, or finished floor/pad elevation. |

Spatial requests are bounded, rather than downloading statewide data. Returned geometry uses WGS84 Esri JSON (`rings`, or `x`/`y`). The original source attributes are preserved. `truncated=true` indicates a limited sample or provider transfer limit, not a complete result set.

The public MassCEC workbook is approximately 13 MB and is cached in `data/raw` by URL using atomic replacement. Its parsed Polars table is cached in memory for that file version. Cached results preserve the download time. Other sources make live HTTP requests. Independent providers run concurrently in a pool with at most six workers per lookup and individual request timeouts. This keeps the initial implementation simple. It does not provide a hard overall request deadline or persistent jobs.

## Response contract

`schema_version` is `1.0`. The top-level fields are:

| Field | Meaning |
| --- | --- |
| `status` | `ok` when the selected automatic calls completed, or `partial` when a provider failed/was blocked. This is not engineering readiness. |
| `location` | Requested coordinates, resolved municipality and an unambiguous assessor address where available. |
| `sources` | Actual provider results keyed by ID. Each includes status, records, source URL, matching method, query, evidence kind, retrieval time and duration. |
| `references` | Explicit manual, authorized or selection-based follow-up routes. No retrieved documents are implied. |
| `checklist` | Twelve categories containing expected fields, values, units, evidence status, source references and the next human input. |
| `missing_fields` | Fields without a resolved value, with category and next action. Includes ambiguous and unavailable fields. |
| `source_errors` | IDs of failed or blocked providers, for retries and frontend messaging. |

Automatic source statuses are `ok`, `no_data`, `error`, and `blocked`. An empty result is distinct from an upstream failure. A failed attempt has `attempted_at_utc` and null `retrieved_at_utc`. Reference statuses are `manual_lookup`, `reference_only`, `authorization_required`, and `selection_required`.

Checklist field statuses are `provided`, `unreviewed`, `candidate`, `ambiguous`, `missing`, `unavailable`, and `not_requested`. Published data starts unreviewed. Multiple intersecting parcels/outlines are retained as candidates rather than silently selecting the first. Missing values remain JSON null, while a real zero is preserved.

Candidate/context checklist values contain a `records_path`, such as `sources.lber.records`, pointing to the actual source records in the response. This avoids repeating large data blocks. Inspect all candidates and original quality flags before attaching a disclosure or rate to a real facility.

Independent provider failures return HTTP 200 with `status=partial`, so usable evidence is retained. Invalid coordinates, unknown source IDs and points outside the municipal land coverage return HTTP 422. If the municipality service fails, the API returns a partial result and leaves municipality-dependent information unresolved.

## Blueprint and private-data boundaries

The response includes municipal permit links for Holliston, Newton, Northampton, Cambridge and Boston when the point resolves to one of those municipalities. Other municipalities return a null portal URL and the municipality/address to use for discovery. The API does not automatically search these portal applications, download their archived blueprints, OCR plans, or verify permit status. These steps remain `manual_lookup`.

Massachusetts Land Records and state code/tariff directories are returned as references. Deed book/page references, if available, remain in `sources.parcels.records`. The API does not infer owner consent, identify a private utility account, retrieve customer bills, or assign an arbitrary ComStock model. The existing source clients and notebook remain available for authorized interval exports and explicitly selected modeled profiles.

## Debug and test

Start with a small source selection to isolate a provider. Inspect its `status`, `error`, `query`, `match_method`, `retrieved_at_utc` and `elapsed_seconds`. Enable `logging.getLogger("API").setLevel(logging.DEBUG)` to see sanitized request parameters. Avoid full HTTP debug logging because the tariff API puts its key in the query string.

```sh
uv run python -m unittest discover -s tests -v
uv run --env-file .env jupyter lab site_api_demo.ipynb
```

The notebook calls the real HTTP API and tests `/health`, `/sources`, `/openapi.json`, `/docs`, `/redoc`, and `/site`. It queries each of the eight automated providers separately, shows records with Polars, compares the field contract at two facilities, and verifies four expected HTTP 422 responses. It saves the response and test summaries under ignored `data/processed/api_demo`. Start the server first, then run all notebook cells. HTTP checks and provider availability are reported separately. An unexpected HTTP status fails its cell. A failed provider always appears as FAIL in the summary, and `REQUIRE_ALL_PROVIDERS=True` also makes it fail the final cell. Empty source results remain visible as `no_data`.

OpenEI's shared demo key can return HTTP 429. Set your own `OPENEI_API_KEY` in `.env`, restart the server so it inherits the key, and rerun the tariff lookup and summary. Rerun the combined lookup too if it had provider errors. No notebook fallback turns a rate-limited request into a successful retrieval.

The offline tests cover HTTP validation, partial failures, spatial filters, ambiguous parcels, missing private inputs, and the separation of municipal/model data from actual site evidence.
