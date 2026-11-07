"""Regressions for public-only matching, archive payloads and extracted evidence."""

import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from API import checklist_table, lookup_site
from API.ma_sources import fetch_source
from API.public_gis import imagery_tiles
from API.public_records import municipal_archive
from API.public_utils import inspect_pdf, text_findings
from test_provenance import provider


class PublicExpansionTests(unittest.TestCase):
    @patch("API.site_lookup.fetch_source", side_effect=provider)
    def test_public_only_and_automatic_parcel_dependency(self, fetch):
        site = lookup_site(
            42.359, -71.093, sources=["assessor_records"], download_evidence=False
        )
        self.assertEqual(
            set(site["sources"]), {"utilities", "parcels", "assessor_records"}
        )
        self.assertTrue(site["public_only"])
        names = set(checklist_table(site)["subcategory_name"])
        self.assertFalse(
            names
            & {"owner_consent", "interval_data", "actual_tariff_code", "bess_power_kw"}
        )

    def test_lber_paginates_each_year_and_preserves_all_raw_fields(self):
        sample = {
            "UBID": "A",
            "Total_Electricity_Use_Purchased_From_Grid_kBtu": 3412.141633,
            "Onsite_Generation_kBtu": 90,
            "Reporting_Boundary": "campus",
        }
        page = {"features": [{"attributes": sample}], "exceededTransferLimit": True}
        last = {"features": [], "exceededTransferLimit": False}
        with (
            patch(
                "API.ma_sources.lber_datasets",
                return_value=[
                    {"name": "edition-A", "url": "https://example.org/a/0"},
                    {"name": "edition-B", "url": "https://example.org/b/0"},
                ],
            ),
            patch(
                "API.ma_sources.get_json", side_effect=[page, last, page, last]
            ) as get,
        ):
            result = fetch_source("lber", 42.359, -71.093)
        self.assertEqual(get.call_count, 4)
        self.assertTrue(any("resultOffset=0" in u for u in result["queries"]))
        self.assertTrue(any("resultOffset=100" in u for u in result["queries"]))
        self.assertEqual(
            {r["dataset_name"] for r in result["records"]}, {"edition-A", "edition-B"}
        )
        self.assertTrue(all(r["data_year"] is None for r in result["records"]))
        self.assertEqual(result["records"][0]["Onsite_Generation_kBtu"], 90)
        self.assertEqual(result["records"][0]["Reporting_Boundary"], "campus")
        self.assertAlmostEqual(result["records"][0]["annual_electricity_kwh"], 1000)


    def test_imagery_tiles_cover_all_four_parcel_corners(self):
        context = {
            "parcels": {
                "records": [
                    {
                        "geometry": {
                            "rings": [
                                [
                                    [-71.1, 42.3],
                                    [-71.08, 42.3],
                                    [-71.08, 42.32],
                                    [-71.1, 42.32],
                                    [-71.1, 42.3],
                                ]
                            ]
                        }
                    }
                ]
            }
        }
        zoom, tiles, bbox = imagery_tiles(context, 42.31, -71.09)
        self.assertLessEqual(len(tiles), 9)
        for x in (bbox[0], bbox[2]):
            for y in (bbox[1], bbox[3]):
                tile = (
                    int((x + 180) / 360 * 2**zoom),
                    int(
                        (1 - math.asinh(math.tan(math.radians(y))) / math.pi)
                        / 2
                        * 2**zoom
                    ),
                )
                self.assertIn(tile, tiles)


    def test_archive_uses_anonymous_public_payload_and_prioritizes_address_title(self):
        session = Mock()
        session.post.return_value = Mock(
            status_code=200,
            json=lambda: {
                "data": {
                    "hitCount": 2,
                    "results": [
                        {
                            "entryId": 1,
                            "name": "Unrelated report mentioning address",
                            "extension": "pdf",
                        },
                        {"entryId": 2, "name": "202 Main Street", "extension": "pdf"},
                    ],
                }
            },
        )
        response = Mock(
            url="https://example.org/search", content=b"<html>search</html>"
        )
        context = {"parcels": {"records": [{"SITE_ADDR": "202 MAIN ST"}]}}
        with (
            tempfile.TemporaryDirectory() as folder,
            patch("API.public_records.page", return_value=(response, Mock())),
        ):
            result = municipal_archive(session, "NORTHAMPTON", context, folder)
        payload = session.post.call_args.kwargs["json"]
        self.assertIsNone(payload["searchUuid"])
        self.assertEqual(payload["searchSyn"], '"202 MAIN"')
        self.assertIn("docid=2", result["documents"][0]["url"])
        self.assertEqual(
            result["records"][0]["match_method"], "archive_fulltext_address_candidate"
        )


    def test_pdf_effective_dates_page_numbers_and_image_only_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            asset = {
                "local_file": str(Path(folder) / "schedule.pdf"),
                "source_url": "https://example.org/rates.pdf",
                "source_title": "Public rate",
            }
            with patch(
                "API.public_utils.PdfReader",
                return_value=Mock(
                    pages=[
                        Mock(
                            extract_text=lambda **k: (
                                "Rates Effective: September 1, 2026\nDemand charge $12.50 per kW"
                            )
                        )
                    ]
                ),
            ):
                parsed = inspect_pdf(asset, role="tariff")
            record = parsed["records"][0]
            self.assertEqual(record["source_date"], "2026-09-01")
            self.assertEqual(record["page"], 1)
            self.assertEqual(record["amounts_raw"], ["12.50"])
            self.assertIn("unassigned", record["rate_assignment"])
            with patch(
                "API.public_utils.PdfReader",
                return_value=Mock(pages=[Mock(extract_text=lambda **k: "")]),
            ):
                blank = inspect_pdf(asset)
            self.assertEqual(blank["text_status"], "image_only_or_no_text")
            self.assertFalse(blank["ocr_performed"])
        refs = text_findings(
            "Distribution Demand Charge: As per M.D.P.U. No. 1",
            "https://example.org",
            "G-3",
            role="tariff",
        )
        self.assertTrue(refs[0]["cross_reference"])


if __name__ == "__main__":
    unittest.main()
