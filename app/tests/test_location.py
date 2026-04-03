"""Tests for app/services/location.py — reverse geocoding with mocked HTTP."""
import pytest
from unittest.mock import patch, MagicMock

from app.services.location import get_address_from_lat_lon

LAT, LON = 38.5021, -107.7232


def _mock_response(address: dict) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"address": address}
    return resp


class TestGetAddressFromLatLon:
    def test_city_and_state_returned(self):
        with patch("app.services.location.requests.get") as mock_get:
            mock_get.return_value = _mock_response({"city": "Montrose", "state": "Colorado"})
            result = get_address_from_lat_lon(LAT, LON)
        assert result["city"] == "Montrose"
        assert result["state"] == "Colorado"
        assert result["display"] == "Montrose, Colorado"

    def test_town_used_when_no_city(self):
        with patch("app.services.location.requests.get") as mock_get:
            mock_get.return_value = _mock_response({"town": "Olathe", "state": "Colorado"})
            result = get_address_from_lat_lon(LAT, LON)
        assert result["city"] == "Olathe"

    def test_county_fallback(self):
        with patch("app.services.location.requests.get") as mock_get:
            mock_get.return_value = _mock_response({"county": "Montrose County", "state": "Colorado"})
            result = get_address_from_lat_lon(LAT, LON)
        assert result["city"] == "Montrose County"

    def test_display_without_state(self):
        with patch("app.services.location.requests.get") as mock_get:
            mock_get.return_value = _mock_response({"city": "SomeCity"})
            result = get_address_from_lat_lon(LAT, LON)
        assert result["display"] == "SomeCity"

    def test_fallback_on_http_error(self):
        with patch("app.services.location.requests.get") as mock_get:
            mock_get.side_effect = Exception("timeout")
            result = get_address_from_lat_lon(LAT, LON)
        assert result["city"] == "Unknown"
        assert str(LAT) in result["display"] or f"{LAT:.4f}" in result["display"]

    def test_lat_lon_preserved_on_fallback(self):
        with patch("app.services.location.requests.get") as mock_get:
            mock_get.side_effect = ConnectionError
            result = get_address_from_lat_lon(LAT, LON)
        assert result["lat"] == LAT
        assert result["lon"] == LON

    def test_coordinates_always_returned(self):
        with patch("app.services.location.requests.get") as mock_get:
            mock_get.return_value = _mock_response({"city": "Montrose", "state": "Colorado"})
            result = get_address_from_lat_lon(LAT, LON)
        assert result["lat"] == LAT
        assert result["lon"] == LON
