# Excel checklist → public Option 1 intake

The original Excel workbook describes a broader deployment checklist. This pipeline retains the existing-site facts that help intake. It does not collect permissions, private customer records, proposed battery designs or new-project approval/compliance workflows. The workbook is a requirements reference, never an input containing facility data.

| Excel category | Option 1 information retained | Public retrieval and limits |
| --- | --- | --- |
| Site identity and boundaries | Address, postal code, coordinates, parcel IDs, owner, use, building/land area, stories/year/style, assessor unit count, mapped roof outline and deed references | Statewide MassGIS point queries; supported municipal assessor cards. Parcel and building geometry remain in source JSON. An assessor unit is not an electrical meter or a count of buildings served. |
| Contacts and authority | Recorded property owner only | Assessor/registry records. Owner consent, contacts and authorization are excluded. |
| Objectives and operations | Published historical work descriptions and use | Municipal permit narratives. They do not establish operating hours, actual shifts, objectives or future customer plans. |
| Utility accounts and meters | Utility territory candidates and historical public service/meter relationships | MassGIS utility layer; Cambridge electrical permits. Active account numbers/supplier/service assignments are not inferred. |
| Bills and applicable tariff | Published schedule/component candidates, effective dates and retrieval failures | Official Massachusetts directory → utility website → currently linked PDFs. A published rate is not an applicable customer tariff. No private bills are retrieved. |
| Interval consumption | Annual purchased electricity and onsite generation where publicly disclosed; address/reporting-boundary metadata | Live multi-year LBER catalog. Different addresses are explicitly labeled neighboring records. No actual interval data is fabricated from annual totals or modeled profiles. |
| Existing electrical infrastructure | Service voltage/phases/amperage, switchboard and main-breaker ratings, transformer rating, single-line diagram, connection point, equipment nameplates, permit and quoted drawing evidence | Detailed Cambridge permits and publicly discoverable plans. The canonical current-equipment fields stay blank when evidence cannot establish them. A proposed-service rating is not an existing-service rating. |
| Existing energy systems | Existing solar/generator/battery/transfer-switch evidence and historical candidates | Public electrical/solar permits and document excerpts. A battery application or new-equipment schedule does not prove an installed system. Unlocated town-level solar projects are excluded. |
| Candidate battery location | Existing parcel/building geometry, aerial images, historical site plans and property photos | Statewide MassGIS imagery/roof outlines plus public plan/photo adapters. This records existing geometry; it does not select a battery location or certify clearances. |
| Construction and site constraints | Existing public plans and relevant equipment/rating excerpts | Public municipal attachments. No trench/foundation design, environmental screening or future shutdown plan is generated. |
| Authorities and approvals | Historical permit descriptions/dates, published zoning designation | Historical context only. AHJ interpretation, submission requirements and new-project approval status are excluded. |
| Proposed battery system | Excluded | Proposed system configuration/sizing belongs to the later design stage. Original public plan files may contain broader content; extracted mentions remain unverified documentary evidence. |

## Public retrieval added for Attleboro

The [city Building Inspection page](https://cityofattleboro.us/167/Building-Inspection) publishes an [anonymous permit view](https://permiteyes.net/Attleboro/building/homepage.asp). The adapter follows that redirect, discovers the search endpoint in the public page, searches the **live parcel address**, and retains exact normalized address matches. It reads the public attachment listing and download configuration for each match. No application ID, attachment ID, drawing filename, project coordinate or file year is fixed in backend code.

Search is bounded to 100 results; up to 10 relevant plan/drawing/equipment/photo attachments are downloaded. Truncation and per-application failures remain explicit. Insurance, contracts, authorization forms and construction-control documents are excluded from attachment selection. The generic statewide lookup still works for other locations; it does not claim an Attleboro adapter covers other towns.

For the user's example `41.90146, -71.33839`, the live parcel resolves to `1 VENUS WAY`. The public search returned eight address-matched historical permit candidates and two relevant plan PDFs during verification. These are publicly discovered documents, not the files supplied for the hackathon. One attachment's filename refers to a different street number: its association comes from the public application, and its drawing address/revision/current applicability still requires review. Submitted or permitted work is never promoted to verified existing equipment.

## Reading completeness honestly

Use the notebooks' **Compare intake coverage with the Excel checklist** view. It lists canonical fields and their collection status/missing reason, separately from the long evidence table. `/site` supplies `missing_fields` with reasons and `public_coverage` with source status. `/site/table` preserves the requested 18 columns and includes explicit retrieval-issue rows even when a partially failed tariff provider returns no records.

Retrieved record counts are not a completeness score. Provenance, neighboring buildings and multiple document excerpts do not fill missing site-specific electrical facts. The [MassGIS parcel specification](https://www.mass.gov/info-details/massgis-data-property-tax-parcels) explains the limitations of assessor building area, units and parcel boundaries.
