# MIT Energy & Climate Hack 2026

Python ingestion for EQORE Option 1 site intake, using Polars and uv. Start with [site_data_sources.ipynb](site_data_sources.ipynb) for seven building, load, tariff, grid, geometry, and customer-interval sources, followed by a site record with provenance and missing-input requests. The original [data_ingestion.ipynb](data_ingestion.ipynb) demonstrates EIA and Open-Meteo.

## Latitude and longitude API

For a simple four-column table, open [site_checklist.ipynb](site_checklist.ipynb) or call:

```python
from API import lookup_table

table = lookup_table(42.359, -71.093)
```

The columns are `checklist item`, `subcategory_name`, `subcategory_value`, and `data_source`. Missing values stay null. Actual candidate values are shown with candidate labels, and provider errors get separate `*.error` rows. Values are text so addresses and numbers can share one column. The notebook also saves CSV and Parquet files.

Start the backend from the repository root. Two coordinates are sufficient to retrieve available public evidence and the twelve-category site checklist.

```sh
uv pip install -r requirements.txt
uv run --env-file .env uvicorn API.server:app --reload --port 8001
```

```sh
curl 'http://127.0.0.1:8001/site?latitude=42.359&longitude=-71.093'
```

Use `/site/table` with the same parameters to return just the four-column table as JSON rows.

Or call it directly from another Python backend.

```python
from API import lookup_site

site = lookup_site(42.359, -71.093)
```

The eight automated sources cover parcels, municipal utility providers, building outlines, nearby LBER disclosures, candidate tariffs, municipal solar context, FEMA flood zones and terrain elevation. Every source reports its own result or error. Private inputs and archived blueprint access remain explicit follow-up actions. No arbitrary nearby facility or modeled profile is silently assigned to the site.

Open [interactive API docs](http://127.0.0.1:8001/docs), read the [API guide](docs/site_api.md), or run [site_api_demo.ipynb](site_api_demo.ipynb). Use `sources=parcels,buildings` to isolate providers while debugging. The full original source notebook remains available below.

## Run the notebook

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then set up the environment from the repository root.

```sh
uv venv --python 3.12
uv pip install -r requirements.txt
```

For EIA, copy the template once and add your [free EIA API key](https://www.eia.gov/opendata/register.php) to `.env` as `EIA_API_KEY=your_key`. Each teammate keeps their own Git-ignored `.env`.

```sh
cp .env.example .env
```

Launch Jupyter from the repository root.

```sh
uv run --env-file .env jupyter lab data_ingestion.ipynb
```

Restart the Jupyter server after editing `.env` so the kernel inherits the new value. For Open-Meteo alone, you can omit `--env-file .env` and run sections 1–6. The last notebook cell writes `data/isone_demand_weather.csv` and replaces that file on reruns. Local data, environments, and notebook checkpoints are Git-ignored.

## Endpoint guide

| Provider | Client method | What it returns |
| --- | --- | --- |
| [EIA API v2](https://www.eia.gov/opendata/documentation.php) | `get_metadata(route)` | Child routes or dataset fields, frequencies, and facet definitions. Omit the route to browse from the root. |
| EIA | `get_facet(route, facet)` | A page of filter values and `totalFacets`. Use `length` and `offset` for more values. |
| EIA | `iter_data(route, ...)` | An iterator of raw data rows. The notebook shows New England hourly demand and generation by fuel. |
| [Open-Meteo forecast](https://open-meteo.com/en/docs) | `get_weather_forecast` | Requested `hourly`, `daily`, and `current` forecasts plus units. |
| [Open-Meteo archive](https://open-meteo.com/en/docs/historical-weather-api) | `get_historical_weather` | Historical reanalysis for an inclusive date range. |
| [Open-Meteo air quality](https://open-meteo.com/en/docs/air-quality-api) | `get_air_quality` | Modeled pollutants or air quality indices. |
| [Open-Meteo marine](https://open-meteo.com/en/docs/marine-weather-api) | `get_marine_forecast` | Waves and other marine forecasts for offshore points. |
| [Open-Meteo geocoding](https://open-meteo.com/en/docs/geocoding-api) | `get_geocoding` | A `results` list when places match the search. |
| [Open-Meteo elevation](https://open-meteo.com/en/docs/elevation-api) | `get_elevation` | Elevations in meters in the same order as the coordinate pairs. |

The Open-Meteo methods accept provider parameter names such as `hourly`, `timezone`, and `forecast_days`. Pass variable names as strings in a list. Endpoints that support multiple locations accept parallel latitude and longitude lists and return one JSON object per location. Check the endpoint documentation for batch limits and data attribution.

## Scale and debug

- **EIA backfills.** Filter by date and facet on the server. The iterator holds one page at a time, up to 5,000 rows per request. Stream rows into a writer or query one month at a time if the full result is too large for memory. For multiple series, include their identifiers in `sort` after `period` so ties have a consistent order across pages. Prefer closed historical windows for reproducible backfills.
- **Weather backfills.** Fetch one manageable date window at a time, request only the variables you need, and batch coordinates where the endpoint supports it. Both clients can share a `requests.Session` to reuse connections, as shown in the notebook.
- **Time and units.** Use EIA `frequency="hourly"` and Open-Meteo `timezone="GMT"` for UTC joins. EIA-930 timestamps mark the end of the reporting hour. Open-Meteo variables can describe an instant or an interval, so check their definitions before changing the join or aggregating. The demo pairs regional demand with weather at one Cambridge-area point. [EIA-930 time convention](https://www.eia.gov/electricity/930-content/about.html)
- **Request failures.** `APIError` includes the endpoint and either the HTTP status and provider message or the connection error type. A timeout is 30 seconds per request. For an empty EIA result, inspect metadata, facet IDs, and the requested period format. For Open-Meteo, inspect the JSON block and its `*_units` field before converting to a table.

Enable just the client loggers to see sanitized parameters and EIA page offsets. EIA puts its key in the query string, so keep full HTTP debug logging off.

```python
import logging

logging.basicConfig(level=logging.INFO)
logging.getLogger("API").setLevel(logging.DEBUG)
```

## EQORE site data

After installing the requirements, launch the source validation notebook from the repository root.

```sh
uv run --env-file .env jupyter lab site_data_sources.ipynb
```

All seven sources support the small public-data retrievals in the notebook. Green Button uses a public test file labeled `sample`. OpenEI uses `DEMO_KEY` by default. For more requests, set your own `OPENEI_API_KEY` in `.env`. The EIA key is used by the original weather/grid notebook.

| Source and method on `SiteDataClient` | Coverage tested | Data returned |
| --- | --- | --- |
| `california_benchmarking(year=2025)` | CA, energy years 2024 and 2025 | Official annual building disclosures from the CEC workbook. |
| `massachusetts_lber(year=2025)` | MA, energy years 2024 and 2025 | Public energy records from the official LBER map's ArcGIS layers. |
| `comstock_metadata()` and `comstock_profile()` | MA and CA profiles, MA county metadata | Modeled building characteristics and a full year of 15-minute energy. The default release uses 2018 weather. |
| `tariffs(latitude, longitude)` | MA and CA coordinates | Candidate commercial tariffs, effective dates, and complete nested rate definitions in `rate_json`. |
| `national_grid_capacity()` | National Grid MA | Feeder hosting-capacity indicators and WGS84 geometry in `geometry_esri_json`. |
| `building_footprints(latitude, longitude)` | MA and CA tiles | A streamed sample of real Microsoft polygons from the containing zoom-9 tile, retained in `feature_geojson`. |
| `green_button()` or `green_button("data/customer/usage.xml")` | Public test XML, plus offline multi-meter conversion tests | Incremental Wh readings converted to kWh and average interval kW, UTC times, meter links, and quality codes. |

The implementation is in [API/site_sources.py](API/site_sources.py). Each result carries `source_url`, `retrieved_at_utc`, `geography`, and `data_kind`. Building disclosures are labeled `reported`, ComStock `modeled`, tariffs `published_tariff`, grid indicators `published_grid`, and machine-learned footprints `inferred`. Disclosures retain source flags describing estimated or incomplete annual energy.

For the two disclosure datasets, common fields include `building_id`, `address`, `city`, `state`, `latitude`, `longitude`, `building_type`, `floor_area_sqft`, `annual_electricity_kwh`, and `data_year`. Purchased-grid electricity is converted from kBtu using 3.412141633 kBtu per kWh. Original fields are retained. LBER energy year 2025 appears in its 2026 reporting layer.

The notebook validates nonempty data and expected columns, displays samples, and writes source snapshots plus `source_checks.parquet` and a combined `buildings.parquet` to `data/processed`. Each independent check reports PASS, FAIL, or AUTH REQUIRED. The notebook's summary assertion fails if any source did not pass.

Downloads are cached in `data/raw` by source URL. Use `refresh=True` to replace a cached download. Writes use a temporary file and atomic replacement. Cached file results preserve their original download time. The `REFRESH` switch in the notebook defaults to true for live verification.

For larger ArcGIS pulls, set `limit=None` or pass a server-side `where` filter. Use ComStock county metadata to choose a `bldg_id`, then fetch that exact profile. The Microsoft sample reads the start of a potentially large tile through a compressed stream. Its polygons may be many kilometers from the requested point. Spatially matching a street address requires a subsequent geometry query. For URDB, use a personal key and page using `limit` and `offset`.

ComStock clock values are preserved as supplied. Its modeled building ID links to ComStock metadata, while matching to a real property requires an explicitly selected archetype. Tariffs are candidates whose effective dates and eligibility need review. National Grid hosting capacity describes generation constraints, while a battery's charging and interconnection assessment requires utility review.

Source documentation is linked in each notebook section. The Microsoft index snapshot is pinned to August 13, 2026 and the ComStock release to `2025/comstock_amy2018_release_3` for reproducibility.

## Site record and supplied plans

The notebook now builds a 25-field intake record from one explicitly selected MA disclosure. It writes `data/processed/site_record.parquet`, an editable `site_record.csv`, and `site_missing_inputs.csv`. Each field carries its value, unit, provenance, review status, confidence, and missing-input request. Public values start unreviewed. Unavailable service ratings, electrical drawings, measured clearances, and other engineering inputs stay missing.

The supplied plan sets informed [API/site_fields.csv](API/site_fields.csv). See [the reference mapping and intake guide](docs/eqore_site_intake.md) for all six shared materials, page references, field meanings, and customer-data usage. Candidate rates, model profiles, footprints, and grid records remain separate until matched to the actual site.

Green Button supports complete Download My Data Atom XML feeds with incremental Wh energy. It preserves meter-specific units, source hashes, quality codes, and flow direction. Unsupported cumulative registers and power units fail explicitly. The public sample contains 216 hourly intervals and provides no actual customer-site demand. For actual consumption, use a customer-authorized export under ignored `data/customer/`.

Run the offline conversion and evidence tests with uv. Run all notebook cells to repeat the seven live source checks and generate the intake outputs.

```sh
uv run python -m unittest discover -s tests -v
```
