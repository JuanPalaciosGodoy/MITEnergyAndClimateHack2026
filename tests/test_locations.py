"""Catch false site assignments, misleading coordinates and broken file links."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from API.checklist_table import checklist_table
from API.evidence import _download_file
from API.location import record_location
from API.ma_sources import query_point
from API.server import app
from API.site_lookup import lookup_site
from test_provenance import provider


class LocationTests(unittest.TestCase):
    def test_source_point_differs_from_search_and_distance_uses_meters(self):
        location = record_location('permits', {'latitude': '42.360', 'longitude': '-71.093'},
                                   42.359, -71.093, 'within_250m_candidate')
        self.assertEqual(location['searched_latitude'], 42.359)
        self.assertEqual(location['source_latitude'], 42.360)
        self.assertAlmostEqual(location['source_distance_m'], 111.2, delta=.1)
        self.assertEqual(location['match_method'], 'within_250m_candidate')

    def test_polygon_center_is_labeled_and_missing_coordinates_stay_unknown(self):
        polygon = record_location('parcels', {'centroid': {'x': -71.092, 'y': 42.359}},
                                  42.359, -71.093, 'point_intersection')
        self.assertIn('centroid', polygon['source_location_basis'])
        self.assertEqual(polygon['match_method'], 'point_intersection')
        unknown = record_location('utilities', {}, 42.359, -71.093, 'municipality_containing_point')
        self.assertIsNone(unknown['source_latitude'])
        self.assertIsNone(unknown['source_distance_m'])
        invalid = record_location('permits', {'latitude': 'unknown', 'longitude': -71}, 42.359, -71.093, 'within_250m_candidate')
        self.assertIsNone(invalid['source_latitude'])

    @patch('API.site_lookup.fetch_source')
    def test_each_candidate_row_retains_its_own_location_and_link(self, fetch):
        def candidates(name, *args, **kwargs):
            result = provider(name, *args, **kwargs)
            if name == 'permits':
                result['records'] = [
                    {'id': '1', 'latitude': '42.360', 'longitude': '-71.093', 'specific_url': {'url': 'https://data.cambridgema.gov/resource/example.json?$where=id=1'}},
                    {'id': '2', 'latitude': '42.361', 'longitude': '-71.093', 'specific_url': {'url': 'https://data.cambridgema.gov/resource/example.json?$where=id=2'}},
                ]
            return result
        fetch.side_effect = candidates
        site = lookup_site(42.359, -71.093, download_evidence=False)
        rows = {r['subcategory_name']: r for r in checklist_table(site).to_dicts()}
        first, second = rows['permit_history[1].permit_id'], rows['permit_history[2].permit_id']
        self.assertEqual(first['source_latitude'], 42.360)
        self.assertEqual(second['source_latitude'], 42.361)
        self.assertLess(first['source_distance_m'], second['source_distance_m'])
        self.assertEqual(first['searched_latitude'], second['searched_latitude'])
        self.assertTrue(first['data_source'].endswith('id=1'))
        self.assertTrue(second['data_source'].endswith('id=2'))
        missing = rows['single_line_diagram']
        self.assertEqual(missing['searched_latitude'], 42.359)
        self.assertIsNone(missing['source_latitude'])

    def test_point_layers_do_not_request_unsupported_polygon_centroids(self):
        with patch('API.ma_sources.get_json', return_value={'features': []}) as get:
            query_point(Mock(), 'lber', 42.359, -71.093)
            self.assertNotIn('returnCentroid', get.call_args.args[2])
            query_point(Mock(), 'parcels', 42.359, -71.093)
            self.assertEqual(get.call_args.args[2]['returnCentroid'], 'true')

    def test_pdf_url_cannot_silently_download_a_login_page(self):
        session = Mock()
        session.get.return_value = Mock(content=b'<html>Log in</html>', headers={'Content-Type': 'text/html'})
        with tempfile.TemporaryDirectory() as folder, self.assertRaisesRegex(ValueError, 'non-PDF'):
            _download_file(session, {'kind': 'document', 'source_url': 'https://example.org/plan.pdf', 'source_title': 'Plan'}, Path(folder), True)

    def test_evidence_route_serves_files_and_rejects_traversal(self):
        root = Path('data/evidence').resolve();root.mkdir(parents=True, exist_ok=True)
        client = TestClient(app)
        with tempfile.TemporaryDirectory(dir=root) as folder:
            path = Path(folder) / 'example.txt';path.write_text('public evidence')
            response = client.get('/evidence/' + path.relative_to(root).as_posix())
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.text, 'public evidence')
            self.assertEqual(client.get('/evidence/%2e%2e/%2e%2e/.env').status_code, 404)
            self.assertEqual(client.get('/evidence/nonexistent.pdf').status_code, 404)


if __name__ == '__main__':
    unittest.main()
