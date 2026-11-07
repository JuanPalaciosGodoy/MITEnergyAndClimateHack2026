# Measurement units

`value_unit_of_measurement` describes **subcategory_value**, not the dates, coordinates or links beside it. Every table row has an explicit entry. Text, identifiers, statuses, booleans and file references use `not_applicable`. Quantities whose units cannot be established use `unknown`; no unit is guessed from value magnitude or another property's record. Missing measurements retain their expected unit when known.

| Intake quantity | Unit |
| --- | --- |
| Assessor/building/roof/floor areas | `ft²`; these sources can use different definitions of area. |
| Parcel land area | The same record's `LOT_UNITS`: `acre`, `ft²` or `m²`; missing/unrecognized units are `unknown`. Values are not silently converted. |
| Purchased electricity and onsite generation | Native values: `kBtu`; normalized values: `kWh`. These are reporting-period energy totals, not `kW` or a fabricated consumption rate. |
| Voltage, amperage and phase count | `V`, `A`, `phases`. Explicit AC/DC voltage qualifiers are retained when supplied. |
| Transformer apparent power / historical UPS apparent power | `kVA`. The permit's UPS field is labeled `reported_ups_total_kva`; it does not establish transformer capacity. |
| Solar system size | `kW DC`. |
| Each panel's rated power | `W/panel`, distinct from whole-system capacity. |
| Panel, inverter, generator and meter counts | `count`. |
| Stories and years | `stories`, `year`. Source dates distinguish fiscal/reporting/construction context. |
| Source/caller latitude and longitude values | `degrees (WGS84)`. |
| Newton GIS edit timestamp | `ms since Unix epoch (UTC)` for the numeric ArcGIS date value. |
| Monetary tariff amounts | `USD/kW`, `USD/kWh`, `USD/month`, etc. Only unit phrases immediately following that amount are assigned. A compound basis can be `USD/kW/month`. Otherwise: `USD (billing basis unknown)`. |
| Unlabeled municipal lot size, frontage or wall height | `unknown`, unless the value explicitly states a suitable unit. MassGIS parcel area conventions are not applied to a different municipality's schema. |

Cambridge's `battery_storage_capacity` field is a **checkbox asking whether storage is proposed**, not a kWh value. The table calls it `reported_battery_installation_flag` and assigns `not_applicable`.

Nested assessor attributes, price lists and document ratings are split into individual rows so one cell cannot hide several quantities with different units. The original source JSON/documents remain available. A value that conflicts with the declared field unit, or combines incompatible units, is marked `unknown`. Units do not establish that a historical/nearby record describes the facility's current equipment.

## Unit sources

- [MassGIS parcel attribute definitions](https://www.mass.gov/info-details/massgis-data-property-tax-parcels): parcel area uses a companion unit field; building area is reported in square feet with source-specific area definitions.
- [Massachusetts DOER LBER reporting information](https://www.mass.gov/info-details/large-building-energy-reporting-policy): reporting-period energy data and gross floor area in square feet.
- [Cambridge electrical dataset metadata](https://data.cambridgema.gov/api/views/hvtc-3ab9.json): service volts/amps, total panel/feeder ampacity and UPS total kVA.
- [Cambridge solar dataset metadata](https://data.cambridgema.gov/api/views/whpw-w55x.json): system kW DC, panel watt capacity and the storage checkbox.
- [Newton municipal property layer metadata](https://gisweb.newtonma.gov/server/rest/services/Browser/MapServer/20?f=pjson): date type is explicit; lot-size/frontage units are not stated, so they remain unknown.

The unit rules live in `API/units.py`. Tests cover mixed parcel units, missing/zero values, voltage versus current, power versus energy, solar DC/panel units, the battery flag, compound tariff bases and exact CSV/API column order.

## CSV and metadata columns

The CSV and table endpoint use exactly this order:

```text
checklist item,subcategory_name,subcategory_value,value_unit_of_measurement,source_title,fetched_at_utc,checked_at_utc,source_date,source_date_basis,searched_latitude,searched_longitude,source_latitude,source_longitude,source_distance_m,source_location_basis,data_source,local_file,file_url
```

The four coordinate metadata columns are WGS84 decimal degrees; `source_distance_m` is meters. Fetch/check timestamps are UTC ISO 8601. Source dates retain the publisher's precision rather than inventing a month/day. `/sources.table_column_units` states the fixed coordinate/distance units. `match_method` remains in the full source JSON and is not an extra CSV column.

Previously generated historical evidence is unchanged. Re-run a lookup or the notebooks to produce current exports with this layout.
