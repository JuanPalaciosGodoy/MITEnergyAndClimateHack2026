"""Unknown-location retrieval must not depend on uploaded or example facility files."""

import inspect
import polars as pl
import json
import tempfile
import unittest
from unittest.mock import Mock, patch

from API import checklist_table, lookup_site, lookup_table
from API.evidence import save_evidence
from API.ma_sources import SOURCES
from API.public_records import assessor, municipal_archive


class CoordinateOnlyTests(unittest.TestCase):
    def test_no_manual_documents_or_uploaded_file_input(self):
        for function in (lookup_site, lookup_table, save_evidence):
            parameters = inspect.signature(function).parameters
            self.assertNotIn("documents", parameters)
            self.assertNotIn("file", parameters)
        with self.assertRaises(TypeError):
            lookup_site(
                42.2626, -71.8023, documents=[{"url": "file:///private/example.pdf"}]
            )

    def test_new_coordinates_drive_public_queries_without_sample_fallback(self):
        observed = []

        def public_response(session, url, params, **kwargs):
            point = json.loads(params["geometry"])
            observed.append((url, point["y"], point["x"]))
            if "ElectricityProviders" in url:
                attributes = {
                    "TOWN": "WORCESTER" if point["x"] > -72 else "SPRINGFIELD"
                }
            else:
                attributes = {
                    "SITE_ADDR": f"public parcel at {point['y']}, {point['x']}",
                    "LOC_ID": str(point["x"]),
                }
            return {"features": [{"attributes": attributes}]}

        with (
            tempfile.TemporaryDirectory() as empty_folder,
            patch("API.ma_sources.get_json", side_effect=public_response),
        ):
            first = lookup_site(
                42.2626,
                -71.8023,
                sources=["parcels"],
                download_evidence=False,
                evidence_dir=empty_folder,
            )
            second = lookup_site(
                42.1015,
                -72.5898,
                sources=["parcels"],
                download_evidence=False,
                evidence_dir=empty_folder,
            )
        self.assertNotEqual(first["location"]["address"], second["location"]["address"])
        self.assertEqual(first["location"]["municipality"], "WORCESTER")
        self.assertEqual(second["location"]["municipality"], "SPRINGFIELD")
        self.assertEqual(
            {(lat, lon) for _, lat, lon in observed},
            {(42.2626, -71.8023), (42.1015, -72.5898)},
        )
        self.assertFalse(first["input_policy"]["uploaded_files_used"])

    def test_missing_public_data_remains_empty_for_unknown_location(self):
        def public_response(session, url, params, **kwargs):
            return (
                {"features": [{"attributes": {"TOWN": "WORCESTER"}}]}
                if "ElectricityProviders" in url
                else {"features": []}
            )

        with patch("API.ma_sources.get_json", side_effect=public_response):
            site = lookup_site(
                42.2626, -71.8023, sources=["parcels"], download_evidence=False
            )
        self.assertIsNone(site["location"]["address"])
        self.assertEqual(site["sources"]["parcels"]["status"], "no_data")
        self.assertFalse(site["sources"]["parcels"]["records"])

    def test_unsupported_town_does_not_advertise_another_towns_record_url(self):
        def public_response(session, url, params, **kwargs):
            attributes = (
                {"TOWN": "WORCESTER"}
                if "ElectricityProviders" in url
                else {"SITE_ADDR": "455 MAIN ST"}
            )
            return {"features": [{"attributes": attributes}]}

        with patch("API.ma_sources.get_json", side_effect=public_response):
            site = lookup_site(
                42.2626,
                -71.8023,
                sources=["parcels", "municipal_archives"],
                download_evidence=False,
            )
        source = site["sources"]["municipal_archives"]
        self.assertEqual(source["status"], "unsupported")
        self.assertIsNone(source["source_url"])
        row = (
            checklist_table(site)
            .filter(pl.col("subcategory_name") == "municipal_archives.coverage")
            .row(0, named=True)
        )
        self.assertIsNone(row["data_source"])
        self.assertIsNone(row["local_file"])

    def test_unconfigured_municipality_never_uses_a_different_town_archive(self):
        context = {"parcels": {"records": [{"SITE_ADDR": "455 MAIN ST"}]}}
        with patch("API.public_records.page") as page:
            for source in (assessor, municipal_archive):
                result = source(Mock(), "WORCESTER", context, "/tmp")
                self.assertEqual(result["status"], "unsupported")
                self.assertFalse(result["records"])
            page.assert_not_called()
        self.assertEqual(
            SOURCES["parcels"]["coverage"]["scope"], "statewide public source"
        )
        self.assertNotIn(
            "WORCESTER", SOURCES["assessor_records"]["coverage"]["municipalities"]
        )


if __name__ == "__main__":
    unittest.main()
