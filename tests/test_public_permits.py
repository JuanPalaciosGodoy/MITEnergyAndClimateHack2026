"""Public records must follow the requested address, not a demonstration property."""

import tempfile
import unittest
from unittest.mock import Mock, patch

import polars as pl

from API import lookup_site, checklist_table
from API.public_permits import attleboro_permits
from test_provenance import provider


def permit_row(address, app_id="live-id"):
    row = [""] * 16
    row[0] = (
        f'<a data-application-id="{app_id}" data-folderpath="building" data-permit-file="electricview.php" data-permit-id="electric-form"></a>'
    )
    row[6] = '<span title="Repair existing emergency lighting">123</span>'
    row[7], row[8], row[9] = "08/16/23", "08/21/23", address
    row[12], row[13], row[14] = "ELECT.", "E-23-1", "Permit Issued"
    row[15] = '<a class="Attachmentclass"></a>'
    return row


class PublicPermitTests(unittest.TestCase):
    def test_live_address_filter_and_published_attachment_paths(self):
        session = Mock()
        search = Mock(url="https://permiteyes.us/attleboro/publicview.php")
        search.text = '<script>var options={"url":"ajax/getpublichome.php"};</script>'
        attachments = Mock(url="https://permiteyes.us/attleboro/publicattachments.php")
        attachments.text = """<script>var AttachmentBasePath="/published/";
            url="controller/publicattachments_controller.php";
            var link="/readfiles2.php?file=";</script>"""
        session.get.side_effect = [search, attachments]
        listing = Mock(url="https://permiteyes.us/attleboro/ajax/getpublichome.php")
        listing.json.return_value = {
            "data": [permit_row("10 VENUS WAY", "neighbor"), permit_row("1 venus way")],
            "recordsFiltered": "2",
        }
        files = Mock()
        files.json.return_value = {
            "Attachments": [
                {
                    "AttachmentName": "Single line drawing",
                    "FileName": "drawing.pdf",
                    "AttachmentPath": "changed-id.pdf",
                    "UploadDateTime": "2024-03-01 12:00:00",
                },
                {
                    "AttachmentName": "Certificate of Insurance",
                    "FileName": "insurance.pdf",
                    "AttachmentPath": "private-irrelevant.pdf",
                },
            ]
        }
        session.post.side_effect = [listing, files]
        with (
            tempfile.TemporaryDirectory() as folder,
            patch("API.public_permits.saved_page", return_value={}),
        ):
            result = attleboro_permits(
                session,
                {"parcels": {"records": [{"SITE_ADDR": "1 VENUS WAY"}]}},
                folder,
            )
        self.assertEqual(len(result["records"]), 1)
        self.assertEqual(result["records"][0]["issue_date"], "2023-08-21")
        self.assertEqual(
            result["records"][0]["description"], "Repair existing emergency lighting"
        )
        self.assertIn(
            "application_id=live-id", result["records"][0]["specific_url"]["url"]
        )
        self.assertEqual(len(result["documents"]), 1)
        self.assertIn("changed-id.pdf", result["documents"][0]["url"])
        self.assertIn("readfiles2.php?file=", result["documents"][0]["url"])
        self.assertEqual(result["documents"][0]["source_date"], "2024-03-01")
        self.assertTrue(result["documents"][0]["expected_pdf"])
        self.assertEqual(
            session.post.call_args_list[0].kwargs["data"]["search[value]"],
            "1 VENUS WAY",
        )
        self.assertNotIn("neighbor", str(session.post.call_args_list))

    def test_missing_address_does_not_substitute_a_sample(self):
        session = Mock()
        self.assertEqual(
            attleboro_permits(session, {}, "/tmp/unused")["status"], "blocked"
        )
        session.get.assert_not_called()

    def test_neighbor_disclosure_and_partial_tariff_failure_are_visible(self):
        def response(name, *args, **kwargs):
            result = provider(name, *args, **kwargs)
            if name == "lber":
                result["records"][0]["address"] = "2 NEIGHBOR ST"
            if name == "tariffs":
                result.update(
                    status="partial",
                    document_errors=[
                        {"url": "https://example.org/rates", "error": "HTTP 403"}
                    ],
                )
            return result

        with patch("API.site_lookup.fetch_source", side_effect=response):
            site = lookup_site(42.359, -71.093, download_evidence=False)
        self.assertIn(
            "Different published street address",
            site["sources"]["lber"]["records"][0]["site_address_match"],
        )
        table = checklist_table(site)
        self.assertEqual(
            table.filter(
                pl.col("subcategory_name") == "tariff_candidates.retrieval_issue[1]"
            )["subcategory_value"][0],
            "HTTP 403",
        )
        self.assertTrue(all(field["reason"] for field in site["missing_fields"]))
        self.assertTrue(
            {
                "switchboard_rating_a",
                "main_breaker_rating_a",
                "equipment_nameplates",
                "site_photos",
            }
            <= {field["field"] for field in site["missing_fields"]}
        )


if __name__ == "__main__":
    unittest.main()
