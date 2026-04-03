"""Tests for GET /route/generate endpoint."""
pytest = __import__("pytest")
fastapi = pytest.importorskip("fastapi", reason="fastapi not installed in this environment")

import json
from unittest.mock import patch, MagicMock

ROUTE_PARAMS = {
    "lat": 38.5021,
    "lon": -107.7232,
    "timestamp": "2025-08-21T22:00:00Z",
    "distance": 50000,
    "hwp_threshold": 50,
    "hwp_max_fraction": 0.1,
    "max_candidates": 100,
    "dropby_type": "store",
}

MOCK_GEOJSON = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[-107.7, 38.5], [-107.6, 38.6]]}, "properties": {}}
    ]
}


class TestGenerateRoute:
    def test_success_returns_geojson(self, api_client):
        mock_df = MagicMock()
        mock_df.__getitem__ = MagicMock(return_value=mock_df)
        mock_df.to_numpy = MagicMock(return_value=[])

        mock_result = {
            "route": [(-107.7, 38.5), (-107.6, 38.6)],
            "dropbys_on_route": [],
        }

        with patch("app.routes.maps_api.check_evac.return_evac_records", return_value=mock_df), \
             patch("app.routes.maps_api.bigquery.BigQueryClient") as mock_bq, \
             patch("app.routes.maps_api.ors_route.return_optimal_end_candidate", return_value=mock_result), \
             patch("app.routes.maps_api.ors_route.export_geojson", return_value=MOCK_GEOJSON), \
             patch("app.routes.maps_api.ors_route.parse_all_polygons", return_value=[]):

            mock_bq.return_value.select_single_table.return_value = MagicMock()
            resp = api_client.get("/route/generate", params=ROUTE_PARAMS)

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "geojson" in data
        geojson = json.loads(data["geojson"])
        assert geojson["type"] == "FeatureCollection"

    def test_no_route_returns_status_and_candidates(self, api_client):
        mock_df = MagicMock()
        mock_df.__getitem__ = MagicMock(return_value=mock_df)
        mock_df.to_numpy = MagicMock(return_value=[])

        with patch("app.routes.maps_api.check_evac.return_evac_records", return_value=mock_df), \
             patch("app.routes.maps_api.bigquery.BigQueryClient") as mock_bq, \
             patch("app.routes.maps_api.ors_route.return_optimal_end_candidate", return_value=None), \
             patch("app.routes.maps_api.ors_route.parse_all_polygons", return_value=[]):

            mock_bq.return_value.select_single_table.return_value = MagicMock()
            resp = api_client.get("/route/generate", params=ROUTE_PARAMS)

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "no_routes"
        assert data["max_candidates"] == 100

    def test_no_dropby_when_type_none(self, api_client):
        """When dropby_type=none, facilities table should not be queried."""
        params = {**ROUTE_PARAMS, "dropby_type": "none"}
        mock_df = MagicMock()
        mock_df.__getitem__ = MagicMock(return_value=mock_df)
        mock_df.to_numpy = MagicMock(return_value=[])

        with patch("app.routes.maps_api.check_evac.return_evac_records", return_value=mock_df), \
             patch("app.routes.maps_api.bigquery.BigQueryClient") as mock_bq, \
             patch("app.routes.maps_api.ors_route.return_optimal_end_candidate", return_value=None), \
             patch("app.routes.maps_api.ors_route.parse_all_polygons", return_value=[]):

            mock_bq_instance = mock_bq.return_value
            mock_bq_instance.select_single_table.return_value = MagicMock()
            resp = api_client.get("/route/generate", params=params)

        assert resp.status_code == 200
        # facilities table (CO_facilities) should only be queried for dropby_type=store
        calls = [str(c) for c in mock_bq_instance.select_single_table.call_args_list]
        assert not any("CO_facilities" in c for c in calls)
