"""Offline API and matching tests. Public source retrieval is demoed in the notebook."""

import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from API._http import APIError
from API.ma_sources import fetch_source, query_point
from API.server import app
from API.site_lookup import lookup_site as _lookup_site
from API.checklist_table import TABLE_COLUMNS, checklist_table as _checklist_table, lookup_table as _lookup_table
from API.ma_sources import SOURCES


# Full-checklist checks exercise the optional MVP providers.
ALL_CONTEXT_SOURCES = ["utilities", "parcels", "buildings", "lber", "flood", "elevation"]


def lookup_site(*args, **kwargs):
    kwargs.setdefault("sources", ALL_CONTEXT_SOURCES)
    return _lookup_site(*args, download_evidence=False, **kwargs)


def lookup_table(*args, **kwargs):
    kwargs.setdefault("sources", ALL_CONTEXT_SOURCES)
    return _lookup_table(*args, download_evidence=False, include_all=True, **kwargs)


def checklist_table(site):
    return _checklist_table(site, include_all=True)


def provider_result(name, latitude, longitude, **kwargs):
    records = {
        "utilities": [{"TOWN": "HOLLISTON", "TOWN_ID": 136, "ELEC": "Example Utility"}],
        "parcels": [{"OBJECTID": 10, "LOC_ID": "example-parcel", "SITE_ADDR": "1 EXAMPLE ST",
                     "OWNER1": "EXAMPLE OWNER", "BLD_AREA": 12000, "USE_DESC": "Industrial", "ZONING": "I"}],
        "buildings": [{"OBJECTID": 11, "STRUCT_ID": "building-11", "AREA_SQ_FT": 4000}],
        "lber": [{"UBID": "nearby-1", "Street_Address": "2 EXAMPLE ST",
                  "Total_Electricity_Use_Purchased_From_Grid_kBtu": 3412.141633,
                  "building_id": "nearby-1", "address": "2 EXAMPLE ST", "data_year": 2025,
                  "floor_area_sqft": 12000, "annual_electricity_kwh": 1000}],
        "flood": [{"FLD_ZONE": "X", "SFHA_TF": "F"}],
        "elevation": [{"elevation_m": 0}],
    }[name]
    return {"records": records, "truncated": False}


def fields(response):
    return {field["name"]: field for category in response["checklist"] for field in category["fields"]}


class LookupTests(unittest.TestCase):
    @patch("API.site_lookup.fetch_source", side_effect=provider_result)
    def test_same_twelve_categories_and_honest_gaps(self, fetch):
        result = lookup_site(42.2, -71.4)
        values = fields(result)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["checklist"]), 12)
        self.assertEqual(len(result["sources"]), 6)
        self.assertEqual(values["address"]["value"], "1 EXAMPLE ST")
        self.assertEqual(values["ground_elevation_m"]["value"], 0)
        self.assertEqual(values["roofprint_area_sqft"]["value"], 4000)
        self.assertEqual(values["assessor_building_area_sqft"]["value"], 12000)
        self.assertEqual(values["annual_energy_candidates"]["status"], "candidate")
        self.assertNotIn("interval_data", values)
        self.assertIsNone(values["existing_site_solar"]["value"])
        self.assertNotIn("actual_tariff_code", values)
        self.assertEqual(result["references"]["permits"]["status"], "manual_lookup")
        self.assertEqual(result["references"]["permits"]["search_address"], "1 EXAMPLE ST")
        self.assertEqual(values["address"]["source_record_id"], 10)

    def test_provider_failure_keeps_other_results(self):
        def failing(name, lat, lon, **kwargs):
            if name == "lber":
                raise APIError("Provider temporarily unavailable")
            return provider_result(name, lat, lon, **kwargs)
        with patch("API.site_lookup.fetch_source", side_effect=failing):
            result = lookup_site(42.2, -71.4)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["source_errors"], ["lber"])
        self.assertEqual(result["sources"]["parcels"]["status"], "ok")
        self.assertIsNone(result["sources"]["lber"]["retrieved_at_utc"])
        self.assertEqual(fields(result)["annual_energy_candidates"]["status"], "unavailable")

    def test_multiple_parcels_are_not_silently_selected(self):
        def boundary(name, lat, lon, **kwargs):
            result = provider_result(name, lat, lon, **kwargs)
            if name == "parcels":
                result["records"].append({"OBJECTID": 20, "SITE_ADDR": "2 EXAMPLE ST", "OWNER1": "OTHER OWNER"})
            return result
        with patch("API.site_lookup.fetch_source", side_effect=boundary):
            result = lookup_site(42.2, -71.4)
        self.assertIsNone(result["location"]["address"])
        self.assertEqual(fields(result)["address"]["status"], "ambiguous")
        self.assertEqual(len(fields(result)["address"]["candidates"]), 2)

    def test_empty_flood_result_is_not_no_risk(self):
        def empty(name, lat, lon, **kwargs):
            return {"records": [], "truncated": False} if name == "flood" else provider_result(name, lat, lon, **kwargs)
        with patch("API.site_lookup.fetch_source", side_effect=empty):
            result = lookup_site(42.2, -71.4)
        self.assertEqual(result["sources"]["flood"]["status"], "no_data")
        self.assertIsNone(fields(result)["flood_zone"]["value"])

    def test_source_filter_and_outside_coverage(self):
        with patch("API.site_lookup.fetch_source", side_effect=provider_result) as fetch:
            result = lookup_site(42.2, -71.4, sources=["parcels"])
        self.assertEqual(set(result["sources"]), {"utilities", "parcels"})
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(fields(result)["flood_zone"]["status"], "not_requested")
        with patch("API.site_lookup.fetch_source", return_value={"records": [], "truncated": False}):
            with self.assertRaisesRegex(ValueError, "Massachusetts"):
                lookup_site(40.7, -74)

    def test_bad_coordinates_and_unknown_sources_do_not_call_providers(self):
        with patch("API.site_lookup.fetch_source") as fetch:
            for lat, lon in [(float("nan"), -71), (float("inf"), -71), (91, -71), (42, 181)]:
                with self.subTest(lat=lat, lon=lon), self.assertRaises(ValueError):
                    lookup_site(lat, lon)
            with self.assertRaisesRegex(ValueError, "Unknown sources"):
                lookup_site(42, -71, sources=["unknown"])
            fetch.assert_not_called()

    def test_arcgis_query_is_spatial_and_bounded(self):
        with patch("API.ma_sources.get_json", return_value={
            "features": [{"attributes": {"LOC_ID": "p1"}, "geometry": {"rings": []}}],
            "exceededTransferLimit": True,
        }) as get:
            result = query_point(Mock(), "parcels", 42.2, -71.4)
        params = get.call_args.args[2]
        self.assertIn('"x": -71.4', params["geometry"])
        self.assertEqual(params["inSR"], 4326)
        self.assertEqual(params["resultRecordCount"], 5)
        self.assertEqual(params["spatialRel"], "esriSpatialRelIntersects")
        self.assertTrue(result["truncated"])
        self.assertIn("geometry", result["records"][0])

    def test_lber_normalization_preserves_candidates_and_units(self):
        sample = {"records": [{"UBID": "nearby-1", "Street_Address": "2 EXAMPLE ST", "City": "Holliston",
                               "Gross_Floor_Area": 12000, "Total_Electricity_Use_Purchased_From_Grid_kBtu": 3412.141633}],
                  "truncated": False}
        with patch("API.ma_sources.get_json", return_value={"features":[{"attributes":sample["records"][0]}]}):
            result = fetch_source("lber", 42.2, -71.4)
        record = result["records"][0]
        self.assertAlmostEqual(record["annual_electricity_kwh"], 1000)
        self.assertEqual(record["building_id"], "nearby-1")
        self.assertEqual(record["data_year"], 2025)
        self.assertIn("Total_Electricity_Use_Purchased_From_Grid_kBtu", record)


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health_catalog_and_openapi(self):
        with patch("API.site_lookup.fetch_source") as fetch:
            self.assertEqual(self.client.get("/health").json(), {"status": "ok"})
            catalog = self.client.get("/sources").json()
            self.assertEqual(catalog["api_version"], app.version)
            self.assertEqual(catalog["schema_version"], "1.3")
            self.assertEqual(catalog["table_columns"], TABLE_COLUMNS)
            self.assertEqual(len(catalog["automated"]), len(SOURCES))
            self.assertEqual(catalog["references"]["permits"]["status"], "manual_lookup")
            self.assertEqual(self.client.get("/openapi.json").status_code, 200)
            fetch.assert_not_called()

    @patch("API.site_lookup.fetch_source", side_effect=provider_result)
    def test_http_endpoint_and_selected_sources(self, fetch):
        response = self.client.get("/site", params={"latitude": 42.2, "longitude": -71.4, "sources": "parcels,buildings", "download_evidence": False, "include_all": True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["checklist"]), 12)
        self.assertEqual(set(response.json()["sources"]), {"utilities", "parcels", "buildings"})

    def test_invalid_parameters_and_unknown_sources(self):
        for params in [{}, {"latitude": 200, "longitude": -71},
                       {"latitude": 42, "longitude": -71, "sources": "not-a-source"}]:
            with self.subTest(params=params):
                self.assertEqual(self.client.get("/site", params=params).status_code, 422)

    def test_frontend_origin(self):
        response = self.client.options("/site", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], "http://localhost:5173")

    @patch("API.site_lookup.fetch_source", side_effect=provider_result)
    def test_dated_coordinate_http_table(self, fetch):
        response = self.client.get("/site/table", params={"latitude": 42.2, "longitude": -71.4, "sources": "parcels,buildings", "download_evidence": False, "include_all": True})
        self.assertEqual(response.status_code, 200)
        rows = response.json()
        self.assertTrue(rows)
        self.assertTrue(all(list(row) == TABLE_COLUMNS for row in rows))
        self.assertEqual(len({row["checklist item"] for row in rows}), 12)
        bad = self.client.get("/site/table", params={"latitude": 91, "longitude": -71})
        self.assertEqual(bad.status_code, 422)


class ChecklistTableTests(unittest.TestCase):
    @patch("API.site_lookup.fetch_source", side_effect=provider_result)
    def test_values_nulls_zero_candidates_and_exact_columns(self, fetch):
        result = lookup_site(42.2, -71.4)
        frame = checklist_table(result)
        self.assertEqual(frame.columns, TABLE_COLUMNS)
        values = {row["subcategory_name"]: row for row in frame.to_dicts()}
        self.assertEqual(frame["checklist item"].n_unique(), 12)
        self.assertEqual(values["address"]["subcategory_value"], "1 EXAMPLE ST")
        self.assertEqual(values["ground_elevation_m"]["subcategory_value"], "0")
        self.assertNotIn("interval_data", values)
        self.assertEqual(values["utility_candidates[1].provider"]["subcategory_value"], "Example Utility")
        self.assertEqual(values["annual_energy_candidates[1].annual_electricity_kwh"]["subcategory_value"], "1000")
        self.assertIsNone(values["existing_site_solar"]["subcategory_value"])
        self.assertFalse(any("records_path" in (row["subcategory_value"] or "") for row in frame.to_dicts()))

    def test_source_error_stays_visible_with_null_disclosure_value(self):
        def limited(name, lat, lon, **kwargs):
            if name == "lber":
                raise APIError("HTTP 429 OVER_RATE_LIMIT")
            return provider_result(name, lat, lon, **kwargs)
        with patch("API.site_lookup.fetch_source", side_effect=limited):
            frame = lookup_table(42.2, -71.4)
        values = {row["subcategory_name"]: row for row in frame.to_dicts()}
        self.assertIsNone(values["annual_energy_candidates"]["subcategory_value"])
        self.assertIn("429", values["annual_energy_candidates.error"]["subcategory_value"])
        self.assertEqual(values["address"]["subcategory_value"], "1 EXAMPLE ST")

    def test_ambiguous_addresses_stay_labeled(self):
        def boundary(name, lat, lon, **kwargs):
            result = provider_result(name, lat, lon, **kwargs)
            if name == "parcels":
                result["records"].append({"OBJECTID": 20, "SITE_ADDR": "2 EXAMPLE ST"})
            return result
        with patch("API.site_lookup.fetch_source", side_effect=boundary):
            frame = lookup_table(42.2, -71.4)
        values = {row["subcategory_name"]: row["subcategory_value"] for row in frame.to_dicts()}
        self.assertNotIn("address", values)
        self.assertIn("address.ambiguous_candidates[2]", values)
        self.assertIn("2 EXAMPLE ST", values["address.ambiguous_candidates[2]"])


if __name__ == "__main__":
    unittest.main()
