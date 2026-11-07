# EQORE Option 1 intake

The supplied [challenge brief](https://docs.google.com/document/d/1ldQhkrjIGzRNjUCpFRPsN6hx4ceSVDt5MHX3-hePq2E/edit) asks for a standardized site record with provenance, confidence, and missing-data flags. This implementation gathers evidence for that record. An engineer reviews the selected property and its documents before design.

## What the supplied materials changed

The two JPEGs are installation photographs, despite their filenames containing “Plan.” They show installed equipment, enclosures, conduits, and protective bollards. They provide examples of useful site photographs. They do not establish measurements or conditions at a candidate building.

| Supplied reference | Fields it informs |
| --- | --- |
| [Full Engineered Plan Set](https://drive.google.com/file/d/16G4kOOd73SFwHW8agiF8O8eHzksmNE7L/view), PDF pages 1–3 | Address, AHJ, property context, proposed location, equipment access. |
| Same set, PDF pages 2 and 18, sheets ESS-4.1 and ESS-13.0 | Switchgear, service configuration, metering, point of interconnection, single-line drawing. |
| [BESS IFC Sample1](https://drive.google.com/file/d/1eaaFvw9uDC60DXiZYDLUA1nnC3uA8JqO/view), PDF pages 4–9 | Existing electrical equipment, service ratings, transformer, connection and layout details. |
| [BESS IFC Sample2](https://drive.google.com/file/d/1gZ2Pk1yS7I57OICqKFmWmD-T7gG22tsh/view), PDF pages 3–4 and 6 | Boundaries, measured clearances, access, switchboard/nameplate photos, electrical topology. |
| [Sample Built Plan.jpeg](https://drive.google.com/file/d/1Cv9EQxN6UK8Qn3B16T7qQ0j4lgNdBaMd/view) and [Sample Built Plan 2.jpeg](https://drive.google.com/file/d/1Ls1ouCM9VYlHOYNQykspKdxVqEvU-zyC/view) | Examples of exterior installation evidence. |

PDF page numbers above are one-based file pages. Sheet identifiers inside the drawings can differ. The full engineered set concerns Century-Tywood in Holliston. The sample IFC sets concern other example configurations. Their electrical values and equipment sizes must stay associated with their own projects.

The field checklist in [API/site_fields.csv](../API/site_fields.csv) is editable. It is an intake aid derived from these examples, rather than a jurisdiction-specific permit checklist. Code editions and clearance dimensions quoted by a sample drawing are not copied into automated compliance rules.

## Evidence table

`build_site_record(building)` takes one normalized disclosure row as a dictionary. Each row of the result contains a field, value, unit, source URL, source record locator, retrieval time, evidence kind, confidence, missing flag, and input to request. The source locator identifies the disclosure building ID, energy year, and normalized field. The original provider columns and quality flags remain in the source Parquet snapshot, with transformations visible in `API/site_sources.py`.

All disclosed values start with `status=needs_review` and `confidence=unreviewed`. A missing value has `status=missing`, `confidence=unknown`, and null provenance. Confidence describes review state, not an invented probability. Retrieving a disclosure does not verify that the reporting boundary is one building or that it matches the customer's meter. `site_id` is a provider/state-scoped candidate identifier, not a parcel ID.

The notebook selects one MA candidate explicitly, creates `site_record.parquet` and an editable `site_record.csv`, and exports `site_missing_inputs.csv`. Review the building match and original disclosure flags first. A public annual total does not establish interval demand. A nearby URDB rate, ComStock model, footprint tile sample, and feeder are kept as separate candidate evidence until matched to the actual site. A Microsoft building footprint also does not define property boundaries.

To incorporate a customer document, update the relevant evidence row with its stated value, units, actual document URI, page/sheet locator, retrieval time, and `data_kind=customer_provided`. Keep it unreviewed until an engineer confirms the interpretation and site match. Preserve prior evidence in dated snapshots when revising it.

## Customer interval data

The brief links [Green Button developer resources](https://www.greenbuttonalliance.org/developer-resources). `SiteDataClient.green_button()` retrieves a small [public test XML file](https://archive.greenbuttondata.org/samples/) for a reproducible seventh-source demo. These 216 hourly intervals are labeled `sample`. They are not a candidate property's actual consumption and cannot support a claim about its 15-minute peak demand.

Use a customer-authorized Download My Data XML export for actual work. Place it under ignored `data/customer/`, then call `client.green_button("data/customer/usage.xml")`. No additional key or library is needed. This reader handles complete Atom feeds with linked MeterReading, ReadingType, and IntervalBlock resources. Connect My Data OAuth and utility-specific CSV exports are outside its scope.

The reader supports incremental Wh energy (`uom=72`, `accumulationBehaviour=4`). It resolves each meter's own ReadingType, applies `raw_value * 10 ** powerOfTenMultiplier / 1000` to obtain kWh, and calculates average interval kW using the actual duration. Unsupported power units and cumulative readings fail explicitly. Timestamps use epoch seconds in UTC. No fixed local offset is added. Original values, multiplier, duration, flow direction, phase, commodity, quality codes, source locator, and file SHA-256 remain available.

Before bill modeling, select the correct meter, flow direction, and phase, review reading quality, and check duplicates, gaps, and billing-period coverage. Average kW is not automatically billed demand. The notebook demonstrates a per-meter coverage check without combining streams or upsampling hourly data into fabricated 15-minute observations.

## Run and debug

```sh
uv pip install -r requirements.txt
uv run --env-file .env jupyter lab site_data_sources.ipynb
uv run python -m unittest discover -s tests -v
```

The notebook's first seven sections are live source checks. The remaining sections consume the results and write the site record. Set `REFRESH=False` to reuse downloaded files while iterating on intake logic. ArcGIS and tariff requests still query their providers. Missing/ambiguous Green Button links produce errors identifying the affected meter. Source logs are available through the `API` logger.
