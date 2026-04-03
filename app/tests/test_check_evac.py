"""Tests for pure geometry functions in app/services/check_evac.py.
Heavy dependencies (contextily, geopandas, etc.) are mocked in conftest.py.
"""
import pytest
from app.services.check_evac import parse_ewkt_ring, point_in_polygon


SIMPLE_POLYGON = "POLYGON((-108.0 38.0, -107.0 38.0, -107.0 39.0, -108.0 39.0, -108.0 38.0))"
SRID_POLYGON   = "SRID=4326;" + SIMPLE_POLYGON


class TestParseEwktRing:
    def test_plain_polygon(self):
        ring = parse_ewkt_ring(SIMPLE_POLYGON)
        assert len(ring) == 5
        assert ring[0] == (-108.0, 38.0)

    def test_srid_prefix_stripped(self):
        ring = parse_ewkt_ring(SRID_POLYGON)
        assert len(ring) == 5
        assert ring[0] == (-108.0, 38.0)

    def test_coordinate_types_are_float(self):
        ring = parse_ewkt_ring(SIMPLE_POLYGON)
        for lon, lat in ring:
            assert isinstance(lon, float)
            assert isinstance(lat, float)


class TestPointInPolygon:
    # Box: lon -108→-107, lat 38→39
    def test_point_inside(self):
        assert point_in_polygon(-107.5, 38.5, SIMPLE_POLYGON) is True

    def test_point_outside(self):
        assert point_in_polygon(-106.0, 38.5, SIMPLE_POLYGON) is False

    def test_point_on_corner(self):
        # Corner points are edge cases; just ensure no crash
        result = point_in_polygon(-108.0, 38.0, SIMPLE_POLYGON)
        assert isinstance(result, bool)

    def test_point_far_outside(self):
        assert point_in_polygon(0.0, 0.0, SIMPLE_POLYGON) is False
