"""Dates, file provenance and partial retrievals that can mislead site intake."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests
import polars as pl
from fastapi.testclient import TestClient

from API.checklist_table import checklist_table
from API.evidence import _download_file
from API.ma_sources import DEFAULT_SOURCES, fetch_source
from API.provenance import source_date
from API.server import app
from API.site_lookup import lookup_site


def provider(name, *args, **kwargs):
    records = {
        "utilities": [{"TOWN": "CAMBRIDGE", "ELEC": "Utility candidate"}],
        "parcels": [{"SITE_ADDR": "60 VASSAR ST", "LOC_ID": "parcel", "FY": 2026, "LAST_EDIT": 20250512}],
        "buildings": [{"STRUCT_ID": "outline", "SOURCEDATE": 20110000}],
        "lber": [{"UBID": "neighbor", "data_year": 2025, "latitude": 42.36, "longitude": -71.093}],
        "flood": [{"FLD_ZONE": "X"}],
        "elevation": [{"elevation_m": 3}],
        "electrical_permits": [{"id": "electric-1", "full_address": "2 NEIGHBOR ST", "volts_existing_service": "480",
                                "latitude": 42.360, "longitude": -71.093,
                                "specific_url": {"url": "https://data.cambridgema.gov/resource/hvtc-3ab9.json?$where=id='electric-1'"}}],
        "solar_permits": [],
        "public_resources": [{"field": "building_ahj", "title": "Municipal building contact — confirm project jurisdiction", "url": "https://example.org/building"},
                             {"field": "fire_ahj", "title": "Municipal fire contact — confirm project jurisdiction", "url": "https://example.org/fire"},
                             {"field": "applicable_requirements", "title": "State code reference", "url": "https://example.org/code"}],
        "permits": [{"id": "1", "issue_date": "2025-02-01T00:00:00.000"},
                    {"id": "2", "issue_date": "2026-07-15T00:00:00.000"}],
    }.get(name, [])
    return {"records": records, "truncated": False}


class ProvenanceTests(unittest.TestCase):
    @patch("API.site_lookup.fetch_source", side_effect=provider)
    def test_default_intake_and_dates_follow_each_record(self, fetch):
        site = lookup_site(42.359, -71.093, download_evidence=False)
        self.assertEqual(set(site["sources"]), set(DEFAULT_SOURCES))
        rows = {r["subcategory_name"]: r for r in checklist_table(site).to_dicts()}
        self.assertEqual(rows["address"]["source_date"], "2026")
        self.assertIn("fiscal", rows["address"]["source_date_basis"])
        self.assertEqual(rows["parcel_id"]["source_date"], "2025-05-12")
        self.assertEqual(rows["mapped_building_id"]["source_date"], "2011")
        self.assertEqual(rows["permit_history[1].permit_id"]["source_date"], "2025-02-01")
        self.assertEqual(rows["permit_history[2].permit_id"]["source_date"], "2026-07-15")
        self.assertIsNone(rows["municipality"]["source_date"])
        self.assertIsNotNone(rows["municipality"]["fetched_at_utc"])
        self.assertIsNone(rows["single_line_diagram"]["fetched_at_utc"])
        self.assertNotIn("owner_consent", rows)
        self.assertNotIn("bess_power_kw", rows)
        self.assertNotIn("municipal_solar_context", rows)
        self.assertTrue(all(r["source_title"] for r in rows.values()))
        self.assertNotIn("bess_power_kw", checklist_table(site, include_all=True)["subcategory_name"].to_list())

    def test_unknown_and_invalid_dates_do_not_become_fetch_dates(self):
        self.assertEqual(source_date("buildings", {"SOURCEDATE": 20110000})[0], "2011")
        self.assertIsNone(source_date("buildings", {"SOURCEDATE": 20111345})[0])
        self.assertIsNone(source_date("flood", {})[0])

    def test_cached_download_dates_and_immutable_versions(self):
        body = b"\xff\xd8\xffexample JPEG"
        response = Mock(url="https://example.org/tile/1", content=body, headers={"Content-Type": "application/octet-stream", "Last-Modified": "Mon, 01 Jan 2024 00:00:00 GMT"})
        session = Mock()
        session.get.return_value = response
        asset = {"source_url": "https://example.org/tile/1", "source_title": "Aerial image", "kind": "aerial_image", "source_date": "2025"}
        with tempfile.TemporaryDirectory() as folder:
            first = _download_file(session, asset, Path(folder), False)
            cached = _download_file(session, asset, Path(folder), False)
            self.assertEqual(session.get.call_count, 1)
            self.assertEqual(first["fetched_at_utc"], cached["fetched_at_utc"])
            self.assertEqual(cached["source_date"], "2025")
            self.assertEqual(cached["content_type"], "image/jpeg")
            self.assertEqual(cached["sha256"], hashlib.sha256(body).hexdigest())
            session.get.return_value = Mock(url="https://example.org/tile/1", content=body + b"changed", headers={"Content-Type": "image/jpeg"})
            fresh = _download_file(session, asset, Path(folder), True)
            self.assertNotEqual(fresh["local_file"], first["local_file"])
            self.assertEqual(Path(first["local_file"]).read_bytes(), body)
            self.assertNotEqual(fresh["fetched_at_utc"], first["fetched_at_utc"])

    @patch("API.site_lookup.fetch_source", side_effect=provider)
    def test_manifest_files_and_download_failure_remain_visible(self, fetch):
        with tempfile.TemporaryDirectory() as folder, patch("API.evidence.requests.Session") as session:
            session.return_value.__enter__.return_value.get.side_effect = requests.HTTPError("503 unavailable")
            site = lookup_site(42.359, -71.093, evidence_dir=folder)
            self.assertEqual(site["status"], "partial")
            manifest = json.loads(Path(site["evidence"]["manifest_file"]).read_text())
            self.assertTrue(manifest["files"])
            row = checklist_table(site).filter(pl.col("subcategory_name") == "address").row(0, named=True)
            self.assertTrue(Path(row["local_file"]).is_file())
            stored = json.loads(Path(row["local_file"]).read_text())
            self.assertEqual(stored["records"][0]["SITE_ADDR"], "60 VASSAR ST")
            failed = [f for f in manifest["files"] if f["status"] == "error"]
            self.assertTrue(failed)
            self.assertTrue(all(f["fetched_at_utc"] is None and f["local_file"] is None for f in failed))

    @patch("API.site_lookup.fetch_source", side_effect=provider)
    def test_table_http_dates_and_download_switch(self, fetch):
        response = TestClient(app).get("/site/table", params={"latitude": 42.359, "longitude": -71.093, "download_evidence": False})
        self.assertEqual(response.status_code, 200)
        rows = {r["subcategory_name"]: r for r in response.json()}
        self.assertEqual(rows["address"]["source_date"], "2026")
        self.assertIsNone(rows["address"]["local_file"])
        self.assertIn("MassGIS", rows["address"]["source_title"])


if __name__ == "__main__":
    unittest.main()
