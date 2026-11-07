"""Public evidence helps intake without turning neighboring permits into facts."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from API.checklist_table import checklist_table
from API.ma_sources import fetch_source
from API.site_lookup import lookup_site
from test_provenance import provider


def download_response(url, **kwargs):
    image = '/tile/' in url
    return Mock(url=url, content=b'\xff\xd8\xffpublic aerial' if image else b'<html>Public contact/reference</html>',
                headers={'Content-Type': 'image/jpeg' if image else 'text/html'})


class PublicEnrichmentTests(unittest.TestCase):
    @patch('API.site_lookup.fetch_source', side_effect=provider)
    def test_evidence_and_exports_are_contained_in_each_coordinate_folder(self, fetch):
        with tempfile.TemporaryDirectory() as folder, patch('API.evidence.requests.Session') as session:
            session.return_value.__enter__.return_value.get.side_effect = download_response
            first = lookup_site(42.359, -71.093, evidence_dir=folder)
            second = lookup_site(42.360, -71.094, evidence_dir=folder)
            roots = []
            for site in [first, second]:
                evidence = site['evidence'];root = Path(evidence['site_directory']);roots.append(root)
                self.assertTrue(Path(evidence['directory']).is_relative_to(root / 'runs'))
                self.assertTrue(Path(evidence['latest_manifest_file']).is_file())
                self.assertTrue(Path(evidence['index_file']).is_file())
                for asset in evidence['files']:
                    if asset['status'] == 'ok':
                        self.assertTrue(Path(asset['local_file']).is_relative_to(root))
                        self.assertTrue(Path(asset['local_file']).is_file())
                for export in evidence['exports'].values():
                    self.assertTrue(Path(export['local_file']).is_file())
                    self.assertTrue(Path(export['local_file']).is_relative_to(root))
                saved = json.loads(Path(evidence['exports']['site_json']['local_file']).read_text())
                self.assertEqual(saved['location'], site['location'])
            self.assertNotEqual(*roots)
            self.assertFalse((Path(folder) / 'files').exists())

    @patch('API.site_lookup.fetch_source', side_effect=provider)
    def test_neighbors_and_contacts_do_not_become_verified_site_ratings(self, fetch):
        site = lookup_site(42.359, -71.093, download_evidence=False)
        rows = {r['subcategory_name']: r for r in checklist_table(site).to_dicts()}
        self.assertIsNone(rows['service_voltage_v']['subcategory_value'])
        voltage = rows['electrical_permit_candidates[1].reported_existing_service_volts']
        self.assertEqual(voltage['subcategory_value'], '480')
        self.assertGreater(voltage['source_distance_m'], 100)
        self.assertEqual(voltage['match_method'], 'within_250m_candidate')
        self.assertIn('confirm', rows['building_ahj']['subcategory_value'])
        fields = {f['name']: f for c in site['checklist'] for f in c['fields']}
        self.assertEqual(fields['building_ahj']['status'], 'reference_only')
        self.assertIsNone(rows['building_ahj']['source_latitude'])
        self.assertIn('applicable_requirements[1].reference_url', rows)

    def test_detailed_electrical_query_prioritizes_service_fields_and_preserves_zero(self):
        with patch('API.ma_sources.get_json', return_value=[{'id': '001', 'generators': '0', 'volts_existing_service': '208'}]) as get:
            result = fetch_source('electrical_permits', 42.359, -71.093, municipality='CAMBRIDGE')
        params = get.call_args.args[2]
        self.assertIn('within_circle', params['$where'])
        self.assertIn('volts_existing_service IS NOT NULL', params['$where'])
        self.assertEqual(params['$limit'], 5)
        self.assertEqual(result['records'][0]['generators'], '0')
        self.assertIn('specific_url', result['records'][0])

    def test_new_permit_providers_keep_unsupported_municipalities_explicit(self):
        for source in ['electrical_permits', 'solar_permits']:
            with self.subTest(source=source), patch('API.ma_sources.get_json') as get:
                result = fetch_source(source, 42.2, -71.4, municipality='HOLLISTON')
                self.assertEqual(result['status'], 'blocked')
                get.assert_not_called()

    def test_reference_failure_keeps_other_public_records(self):
        def public_records(name, *args, **kwargs):
            result = provider(name, *args, **kwargs)
            if name == 'public_resources':
                result['resource_errors'] = [{'url': 'https://example.org/unavailable', 'error': 'HTTP 503'}]
            return result
        with patch('API.site_lookup.fetch_source', side_effect=public_records):
            site = lookup_site(42.359, -71.093, download_evidence=False)
        self.assertEqual(site['status'], 'partial')
        self.assertIn('public_resources', site['source_errors'])
        self.assertTrue(site['sources']['public_resources']['records'])


if __name__ == '__main__':
    unittest.main()
