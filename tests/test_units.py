"""Prevent area, power/energy, checkbox and tariff-basis unit mistakes."""

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import polars as pl
from fastapi.testclient import TestClient

from API import checklist_table, lookup_site
from API.checklist_table import TABLE_COLUMNS
from API.server import app
from API.units import value_unit
from test_provenance import provider

WANTED_COLUMNS = [
    "checklist item",
    "subcategory_name",
    "subcategory_value",
    "value_unit_of_measurement",
    "source_title",
    "fetched_at_utc",
    "checked_at_utc",
    "source_date",
    "source_date_basis",
    "searched_latitude",
    "searched_longitude",
    "source_latitude",
    "source_longitude",
    "source_distance_m",
    "source_location_basis",
    "data_source",
    "local_file",
    "file_url",
]


class UnitTests(unittest.TestCase):
    def test_known_measurements_and_missing_measurements_have_explicit_units(self):
        cases = [
            ("assessor_building_area_sqft", None, "ft²"),
            ("roofprint_area_sqft", 0, "ft²"),
            ("floor_area_sqft", 100, "ft²"),
            ("service_voltage_v", 480, "V"),
            ("reported_existing_service_amps", 400, "A"),
            ("service_phases", 3, "phases"),
            ("transformer_rating_kva", 1000, "kVA"),
            ("reported_ups_total_kva", "100", "kVA"),
            ("annual_electricity_kwh", 1000, "kWh"),
            ("annual_onsite_generation_kwh", 0, "kWh"),
            ("Total_Electricity_Use_Purchased_From_Grid__kBtu_", 3412.141633, "kBtu"),
            ("reported_system_size_raw", "226.1", "kW DC"),
            ("reported_watt_capacity_raw", "480", "W/panel"),
            ("reported_panel_count", 471, "count"),
            ("existing_meter_count", 0, "count"),
            ("number_of_stories", 4, "stories"),
            ("year_built", 1890, "year"),
            ("latitude", 42.2626, "degrees (WGS84)"),
        ]
        for name, value, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(value_unit(None, name, value), expected)

    def test_land_area_uses_each_parcels_unit_never_magnitude(self):
        for native, expected in [
            ("Acres", "acre"),
            ("AC", "acre"),
            ("Square Feet", "ft²"),
            ("SF", "ft²"),
            ("ft²", "ft²"),
            ("m²", "m²"),
            (None, "unknown"),
            ("not reported", "unknown"),
        ]:
            with self.subTest(native=native):
                self.assertEqual(
                    value_unit(
                        "parcels", "parcel_land_area", 3.66, {"LOT_UNITS": native}
                    ),
                    expected,
                )
        self.assertEqual(
            value_unit("assessor_records", "assessor_records[1].Lot_Size", 1000),
            "unknown",
        )
        self.assertEqual(
            value_unit("assessor_records", "assessor_records[1].Frontage", 50),
            "unknown",
        )
        self.assertEqual(
            value_unit("assessor_records", "assessor_records[1].Frontage", "50 ft"),
            "ft",
        )

    def test_battery_checkbox_and_identifiers_are_not_energy_or_counts(self):
        for name, value in [
            ("reported_battery_installation_flag", False),
            ("reported_battery_installation_flag", True),
            ("battery_storage_capacity", "false"),
            ("parcel_id", "12345"),
            ("permit_id", "001"),
            ("ZIP_Code", "02142"),
            ("issue_date", "2026-01-01"),
        ]:
            with self.subTest(name=name):
                self.assertEqual(
                    value_unit("solar_permits", name, value), "not_applicable"
                )
        self.assertEqual(
            value_unit(None, "unexplained_new_measurement", 123), "unknown"
        )

    def test_explicit_unit_conflicts_and_multiple_units_are_not_mislabeled(self):
        self.assertEqual(
            value_unit("solar_permits", "reported_system_size_raw", "100 kW AC"),
            "unknown",
        )
        self.assertEqual(
            value_unit(None, "service_voltage_v", "208 V and 400 A"), "unknown"
        )
        self.assertEqual(value_unit(None, "service_voltage_v", "208 VAC"), "V AC")
        self.assertEqual(
            value_unit(None, "reported_ups_total_kva", "100 kVAr"), "unknown"
        )
        self.assertEqual(
            value_unit(None, "document_findings[1].ratings_raw[1]", "2 MW"), "MW"
        )
        self.assertEqual(
            value_unit(None, "document_findings[1].ratings_raw[1]", "2 mW"), "mW"
        )

    def test_rate_amounts_keep_their_billing_denominator(self):
        for quote, expected in [
            ("Demand charge $12.50 per kW", "USD/kW"),
            ("Electricity $0.12/kWh", "USD/kWh"),
            ("Customer charge $50 per month", "USD/month"),
            ("Demand $12.50/kW; energy $0.12/kWh", "USD/kW"),
            ("Minimum charge $50", "USD (billing basis unknown)"),
        ]:
            with self.subTest(quote=quote):
                self.assertEqual(
                    value_unit(
                        "tariffs",
                        "tariff_candidates[1].amounts_raw[1]",
                        "12.50",
                        {"component_text": quote},
                    ),
                    expected,
                )
        self.assertEqual(
            value_unit("tariffs", "tariff_candidates[1].amounts_raw", [], {}),
            "not_applicable",
        )
        record = {"component_text": "Customer $50.00; demand $12.50 per kW"}
        self.assertEqual(
            value_unit(
                "tariffs", "tariff_candidates[1].amounts_raw[1]", "50.00", record
            ),
            "USD (billing basis unknown)",
        )
        self.assertEqual(
            value_unit(
                "tariffs", "tariff_candidates[1].amounts_raw[2]", "12.50", record
            ),
            "USD/kW",
        )
        record = {"component_text": "Demand $12.50 per kW per month"}
        self.assertEqual(
            value_unit(
                "tariffs", "tariff_candidates[1].amounts_raw[1]", "12.50", record
            ),
            "USD/kW/month",
        )

    def test_heterogeneous_assessor_and_document_values_are_separate_unit_rows(self):
        def records(name, *args, **kwargs):
            result = provider(name, *args, **kwargs)
            if name == "assessor_records":
                result["records"] = [
                    {
                        "reported_assessor_attributes": {
                            "Land Area (sq. ft)": "1,500",
                            "Number of Stories": "3",
                            "Wall Height": "14",
                            "Year Built": "2007",
                        }
                    }
                ]
            return result

        with patch("API.site_lookup.fetch_source", side_effect=records):
            site = lookup_site(42.359, -71.093, download_evidence=False)
        site["document_findings"] = [
            {
                "document_excerpt": "Transformer 100 kVA, service 480 volts",
                "ratings_raw": ["100 kVA", "480 volts"],
                "url": "https://example.org/public-plan.pdf",
                "page": 2,
                "source_title": "Public plan",
            }
        ]
        rows = {r["subcategory_name"]: r for r in checklist_table(site).to_dicts()}
        expected = {
            "assessor_records[1].reported_assessor_attributes.Land Area (sq. ft)": "ft²",
            "assessor_records[1].reported_assessor_attributes.Number of Stories": "stories",
            "assessor_records[1].reported_assessor_attributes.Wall Height": "unknown",
            "assessor_records[1].reported_assessor_attributes.Year Built": "year",
            "document_findings[1].ratings_raw[1]": "kVA",
            "document_findings[1].ratings_raw[2]": "V",
        }
        for name, unit in expected.items():
            self.assertEqual(rows[name]["value_unit_of_measurement"], unit)

    def test_ambiguous_parcels_do_not_share_the_first_candidates_area_unit(self):
        def records(name, *args, **kwargs):
            result = provider(name, *args, **kwargs)
            if name == "parcels":
                result["records"] = [
                    {"LOT_SIZE": 1, "LOT_UNITS": "Acres"},
                    {"LOT_SIZE": 43560, "LOT_UNITS": "SF"},
                ]
            return result

        with patch("API.site_lookup.fetch_source", side_effect=records):
            site = lookup_site(
                42.359, -71.093, sources=["parcels"], download_evidence=False
            )
        rows = {r["subcategory_name"]: r for r in checklist_table(site).to_dicts()}
        self.assertEqual(
            rows["parcel_land_area.ambiguous_candidates[1]"][
                "value_unit_of_measurement"
            ],
            "acre",
        )
        self.assertEqual(
            rows["parcel_land_area.ambiguous_candidates[2]"][
                "value_unit_of_measurement"
            ],
            "ft²",
        )
        field = next(
            f
            for c in site["checklist"]
            for f in c["fields"]
            if f["name"] == "parcel_land_area"
        )
        self.assertEqual([r["unit"] for r in field["candidates"]], ["acre", "ft²"])

    @patch("API.site_lookup.fetch_source", side_effect=provider)
    def test_csv_api_and_canonical_fields_follow_the_requested_contract(self, fetch):
        site = lookup_site(42.359, -71.093, download_evidence=False)
        table = checklist_table(site)
        self.assertEqual(TABLE_COLUMNS, WANTED_COLUMNS)
        self.assertEqual(table.columns, WANTED_COLUMNS)
        self.assertTrue(table["value_unit_of_measurement"].is_not_null().all())
        self.assertTrue(all(f["unit"] for c in site["checklist"] for f in c["fields"]))
        self.assertEqual(table.schema["source_distance_m"], pl.Float64)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "checklist.csv"
            table.write_csv(path)
            with path.open(encoding="utf-8", newline="") as stream:
                self.assertEqual(next(csv.reader(stream)), WANTED_COLUMNS)
            self.assertEqual(
                pl.read_csv(path)["value_unit_of_measurement"].to_list(),
                table["value_unit_of_measurement"].to_list(),
            )
        response = TestClient(app).get(
            "/site/table",
            params={
                "latitude": 42.359,
                "longitude": -71.093,
                "sources": "parcels",
                "download_evidence": False,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(all(list(row) == WANTED_COLUMNS for row in response.json()))
        self.assertNotIn("match_method", response.json()[0])
        catalog = TestClient(app).get("/sources").json()
        self.assertEqual(catalog["table_column_units"]["source_distance_m"], "m")
        self.assertEqual(catalog["table_columns"], WANTED_COLUMNS)


if __name__ == "__main__":
    unittest.main()
