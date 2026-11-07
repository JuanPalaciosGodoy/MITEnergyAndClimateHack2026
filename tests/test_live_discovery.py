"""Verify data changes and new published editions are visible without code changes."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from API.discovery import lber_datasets, latest_raster
from API.evidence import _download_file
from API.public_energy import tariffs


class LiveDiscoveryTests(unittest.TestCase):
    def test_changed_file_at_same_url_is_fetched_and_old_version_preserved(self):
        session = Mock()
        url = "https://example.org/report.csv"
        session.get.side_effect = [
            Mock(
                status_code=200,
                url=url,
                headers={"Content-Type": "text/csv", "ETag": '"one"'},
                content=b"new report one",
            ),
            Mock(
                status_code=200,
                url=url,
                headers={"Content-Type": "text/csv", "ETag": '"two"'},
                content=b"new report two",
            ),
        ]
        asset = {
            "source_url": url,
            "source_title": "Live report",
            "kind": "source_document",
        }
        with tempfile.TemporaryDirectory() as folder:
            first = _download_file(session, asset, Path(folder), False)
            second = _download_file(session, asset, Path(folder), False)
            self.assertNotEqual(first["sha256"], second["sha256"])
            self.assertEqual(Path(first["local_file"]).read_bytes(), b"new report one")
            self.assertEqual(Path(second["local_file"]).read_bytes(), b"new report two")
            self.assertEqual(
                session.get.call_args.kwargs["headers"]["If-None-Match"], '"one"'
            )
            self.assertTrue(second["checked_at_utc"])

    def test_revalidation_failure_never_silently_returns_cached_file(self):
        session = Mock()
        url = "https://example.org/report.csv"
        session.get.return_value = Mock(
            status_code=200,
            url=url,
            headers={"Content-Type": "text/csv"},
            content=b"old content",
        )
        asset = {"source_url": url, "source_title": "Report", "kind": "document"}
        with tempfile.TemporaryDirectory() as folder:
            _download_file(session, asset, Path(folder), False)
            session.get.side_effect = requests.ConnectionError("offline")
            with self.assertRaises(requests.ConnectionError):
                _download_file(session, asset, Path(folder), False)

    def test_new_lber_edition_and_actual_layer_id_are_discovered(self):
        with patch(
            "API.discovery.get_json",
            side_effect=[
                {
                    "services": [
                        {
                            "name": "2031_LBER_Annual_Report_Data",
                            "type": "FeatureServer",
                        }
                    ]
                },
                {
                    "layers": [{"id": 7, "name": "Properties"}],
                    "serviceItemId": "new-item",
                },
            ],
        ):
            datasets = lber_datasets(Mock())
        self.assertIn("2031", datasets[0]["url"])
        self.assertTrue(datasets[0]["url"].endswith("/7"))

    def test_new_imagery_edition_replaces_old_catalog_entries(self):
        services=[{'name':'Massachusetts_Aerial_Imagery_2025','type':'MapServer'},
                  {'name':'Massachusetts_Aerial_Imagery_2030','type':'MapServer'},
                  {'name':'Massachusetts_Aerial_Imagery_2031_CIR','type':'MapServer'}]
        with patch('API.discovery.get_json',return_value={'services':services}):
            imagery=latest_raster(Mock(),'imagery')
        self.assertEqual(imagery['source_date'],'2030')


    def test_tariff_pdf_is_discovered_from_current_page_not_a_configured_filename(self):
        directory = Mock(
            url="https://www.mass.gov/rates", content=b"<html>Directory</html>"
        )
        utility = Mock(
            url="https://www.example.org/business/tariffs",
            content=b"<html>Tariffs</html>",
        )
        asset = {
            "source_url": "https://www.eversource.com/new-2030-schedule.pdf",
            "source_title": "New schedule",
        }
        with (
            patch(
                "API.public_energy.page",
                side_effect=[(directory, Mock()), (utility, Mock())],
            ),
            patch(
                "API.public_energy.page_links",
                side_effect=[
                    [
                        {
                            "url": "https://www.eversource.com/business/tariffs",
                            "title": "Business",
                        }
                    ],
                    [{"url": asset["source_url"], "title": "Electric tariff G3"}],
                    [],
                ],
            ),
            patch("API.public_energy.saved_page", return_value={}),
            patch("API.public_energy.public_file", return_value=asset) as download,
            patch(
                "API.public_energy.inspect_pdf",
                return_value={
                    "text_file": "/tmp/text",
                    "page_count": 1,
                    "effective_dates": [],
                    "records": [],
                },
            ),
        ):
            result = tariffs(
                Mock(),
                "CAMBRIDGE",
                {"utilities": {"records": [{"ELEC": "Eversource"}]}},
                "/tmp",
            )
        self.assertEqual(download.call_args.args[1], asset["source_url"])
        self.assertEqual(result["discovered_documents"], [asset["source_url"]])

    def test_discovery_outage_never_selects_a_pinned_raster(self):
        with patch("API.discovery.get_json", return_value={"services": []}):
            with self.assertRaisesRegex(ValueError, "No imagery dataset"):
                latest_raster(Mock(), "imagery")


if __name__ == "__main__":
    unittest.main()
