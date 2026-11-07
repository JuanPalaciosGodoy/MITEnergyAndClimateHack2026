# Option 1 field scope

The EQORE challenge brief defines Option 1 as gathering existing site information without a visit and producing a standardized record with provenance, confidence and missing-data flags. Its named sources are public building records/old plans, imagery, property records and utility schedules. We use the supplied brief only to define requirements; it is not a facility-data input.

This MVP keeps core intake facts. A later workflow can consume them, but this backend does not produce that workflow's engineering, review, financial or compliance outputs.

## Retained record

| Group | Fields |
| --- | --- |
| Site/property | Address, municipality/state/coordinates, parcel IDs, reported owner/use, building and land area/units, construction year/stories, published zoning designation, assessor evidence, deed/plan references. |
| Existing utility/service | Published utility candidates and historical parcel/address/meter/service relationships. |
| Electricity and schedules | Annual purchased electricity, reported onsite electrical generation, reporting boundary/property/year metadata, public tariff components and effective dates. No savings calculation. |
| Existing electrical information | Service voltage/phases/amperage, transformer rating, existing single-line/connection point, historical electrical permit evidence and page-cited equipment/rating mentions. Unknown current ratings remain missing. |
| Existing onsite equipment | Published evidence of solar, generators, batteries and transfer switches, including historical solar permit candidates. This is not a proposed battery configuration. |
| Geometry and documents | Mapped building/roof outline, parcel-envelope aerial imagery, historical site plans, property-card photos/sketches, archive candidates and historical permit records. |

All values retain source identity, dates, searched/source coordinates, matching limitations and evidence links. Existing record status/issue date helps interpret a historical source; it does not track approval of a new EQORE installation. Published zoning is a property attribute; it does not become a zoning or code-compliance decision.

## Removed from this MVP

| Exclusion | Reason |
| --- | --- |
| Applicable code lists, submission excerpts, building/fire AHJ fields | Code interpretation, submission/review and project-specific authority workflows belong to later options. |
| Interconnection agreement placeholder and duplicate equipment-document workflow category | Current-project approvals/compliance tracking and redundant fields are outside the narrow intake record. Existing physical connection information remains. |
| Commissioning, O&M/maintenance, emergency/decommissioning, sign-offs, deadlines and access-role workflows | Option 4 compliance lifecycle; not intake. |
| Proposed battery power/energy/configuration, layout generation, savings/incentive/dispatch modeling | Sizing/economics/design; not collection of existing facts. |
| Lidar, elevation, flood, wetlands, contamination/AUL and habitat providers | Construction/environmental-screening enrichment is excluded from this core intake MVP. Imagery and existing site geometry remain. |
| Municipality-wide MassCEC PTS equipment/cost rows | Unidentified installations elsewhere in a town cannot establish equipment at the requested facility. |
| Property values/sale prices/owner mailing addresses; applicant signatures, insurance, contractor data/costs | Provider form/valuation fields do not serve this intake record. |
| Gas/oil/coal/steam/water use, EUI and GHG attributes | Outside this MVP's electrical baseline; purchased electricity and onsite generation remain. |

## Enforcement

`API/scope.py` contains positive source-record field lists, including nested assessor labels. These apply before source records enter the response. The six-group checklist contains only intake fields. Removed providers are absent from `/sources` and rejected if explicitly requested. Both `include_all` views use the same narrow schema. `checklist_table` refuses pre-scope lookup JSON; fetch the site again instead of reviving old fields.

Original downloaded public PDFs/images are preserved for traceability and can contain broader historical content. They do not add extra fields or workflows to the modeled record. Supplied project files and manually selected documents are not runtime inputs.
