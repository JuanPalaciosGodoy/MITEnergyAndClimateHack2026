"""Option 1 stays narrow in JSON, flat tables, downloads and compatibility views."""

import copy
import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from API import checklist_table, lookup_site
from API.ma_sources import DEFAULT_SOURCES, SOURCES
from API.scope import SCOPE, RECORD_FIELDS
from API.server import app
from test_provenance import provider

REMOVED_SOURCES = {
    "public_resources",
    "masscec",
    "flood",
    "elevation",
    "lidar",
    "wetlands",
    "environmental",
    "activity_use_limits",
    "protected_habitat",
}
REMOVED_FIELDS = {
    "building_ahj",
    "fire_ahj",
    "applicable_requirements",
    "submission_excerpts",
    "interconnection_agreement",
    "equipment_document_references",
    "flood_zone",
    "ground_elevation_m",
    "lidar_samples",
    "wetland_candidates",
    "environmental_candidates",
    "activity_use_candidates",
    "habitat_candidates",
    "masscec_context",
    "bess_power_kw",
    "bess_energy_kwh",
    "commissioning_plan",
    "maintenance_schedule",
    "decommissioning_plan",
    "annual_savings",
}


class OptionOneScopeTests(unittest.TestCase):
    def test_only_intake_sources_are_available_even_when_explicitly_requested(self):
        self.assertFalse(REMOVED_SOURCES & set(SOURCES))
        self.assertEqual(set(DEFAULT_SOURCES), set(RECORD_FIELDS))
        with patch("API.site_lookup.fetch_source") as fetch:
            for name in REMOVED_SOURCES:
                response = TestClient(app).get(
                    "/site",
                    params={
                        "latitude": 42.2626,
                        "longitude": -71.8023,
                        "sources": name,
                        "download_evidence": False,
                    },
                )
                self.assertEqual(response.status_code, 422, name)
            fetch.assert_not_called()

    @patch("API.site_lookup.fetch_source", side_effect=provider)
    def test_both_table_views_and_missing_fields_exclude_other_phases(self, fetch):
        site = lookup_site(42.359, -71.093, download_evidence=False)
        fields = {
            f["name"] for category in site["checklist"] for f in category["fields"]
        }
        self.assertFalse(fields & REMOVED_FIELDS)
        self.assertFalse({f["field"] for f in site["missing_fields"]} & REMOVED_FIELDS)
        self.assertEqual(site["scope"], SCOPE)
        self.assertEqual(len(site["checklist"]), 6)
        self.assertEqual(
            checklist_table(site).to_dicts(),
            checklist_table(site, include_all=True).to_dicts(),
        )
        self.assertTrue(
            {
                "service_voltage_v",
                "single_line_diagram",
                "existing_site_solar",
                "tariff_candidates",
                "annual_energy_candidates",
                "recorded_owner",
            }
            <= fields
        )
        self.assertNotIn("requirements", site["references"])

    def test_provider_form_and_valuation_fields_cannot_leak_into_intake(self):
        def broad_source(name, *args, **kwargs):
            result = provider(name, *args, **kwargs)
            if name == "electrical_permits":
                result["records"][0].update(
                    estimated_value=100000,
                    insurance_company="Private insurer",
                    applicant_signature="signature",
                    commissioning_plan="later",
                    count_of_meters_existing=0,
                )
            if name == "parcels":
                result["records"][0].update(
                    TOTAL_VAL=900000,
                    LS_PRICE=800000,
                    OWN_ADDR="unneeded mailing address",
                )
            if name == "lber":
                result["records"][0].update(
                    Total_Natural_Gas_Use__kBtu_=99,
                    Site_EUI_kBtu_ft=10,
                    annual_savings=500,
                )
            if name == "assessor_records":
                result["records"] = [
                    {
                        "address": "60 VASSAR ST",
                        "reported_assessor_attributes": {
                            "Number of Stories": "3",
                            "Assessed Value": "$900,000",
                            "Sale Price": "$800,000",
                        },
                    }
                ]
            return result

        with patch("API.site_lookup.fetch_source", side_effect=broad_source):
            site = lookup_site(42.359, -71.093, download_evidence=False)
        encoded = json.dumps(site)
        for field in [
            "estimated_value",
            "insurance_company",
            "applicant_signature",
            "commissioning_plan",
            "TOTAL_VAL",
            "LS_PRICE",
            "OWN_ADDR",
            "Total_Natural_Gas_Use",
            "Site_EUI",
            "annual_savings",
            "Assessed Value",
            "Sale Price",
        ]:
            self.assertNotIn(field, encoded, field)
        self.assertEqual(
            site["sources"]["electrical_permits"]["records"][0][
                "count_of_meters_existing"
            ],
            0,
        )
        self.assertEqual(
            site["sources"]["assessor_records"]["records"][0][
                "reported_assessor_attributes"
            ],
            {"Number of Stories": "3"},
        )

    @patch("API.site_lookup.fetch_source", side_effect=provider)
    def test_old_full_scope_lookup_must_be_refetched(self, fetch):
        site = lookup_site(42.359, -71.093, download_evidence=False)
        old = copy.deepcopy(site)
        old.pop("scope")
        with self.assertRaisesRegex(ValueError, "predates the Option 1 scope"):
            checklist_table(old, include_all=True)


if __name__ == "__main__":
    unittest.main()
