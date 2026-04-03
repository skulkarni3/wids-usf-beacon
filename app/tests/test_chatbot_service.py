"""Tests for app/services/chatbot.py — build_system_prompt (pure logic, no external calls)."""
import pytest
from datetime import datetime
from unittest.mock import patch

from app.services.chatbot import build_system_prompt


class TestBuildSystemPromptUrgency:
    def test_low_urgency_no_evac(self, sample_location):
        prompt = build_system_prompt(sample_location, evac_data=[], maps_data=None)
        assert "LOW" in prompt
        assert "None found" in prompt

    def test_high_urgency_with_evac(self, sample_location, sample_evac_data):
        prompt = build_system_prompt(sample_location, evac_data=sample_evac_data, maps_data=None)
        assert "HIGH" in prompt
        assert "1 zone(s)" in prompt

    def test_critical_no_route_with_evac(self, sample_location, sample_evac_data):
        prompt = build_system_prompt(sample_location, evac_data=sample_evac_data, maps_data=None, no_route=True)
        assert "CRITICAL" in prompt
        assert "911" in prompt

    def test_critical_no_route_no_evac(self, sample_location):
        prompt = build_system_prompt(sample_location, evac_data=[], maps_data=None, no_route=True)
        assert "CRITICAL" in prompt
        assert "911" in prompt


class TestBuildSystemPromptDistance:
    def test_distance_converted_to_km(self, sample_location):
        prompt = build_system_prompt(sample_location, evac_data=[], maps_data=None, distance=50000)
        assert "50 km" in prompt

    def test_custom_distance(self, sample_location):
        prompt = build_system_prompt(sample_location, evac_data=[], maps_data=None, distance=5000)
        assert "5 km" in prompt


class TestBuildSystemPromptRoute:
    def test_route_calculated(self, sample_location):
        prompt = build_system_prompt(sample_location, evac_data=[], maps_data={"route": "..."})
        assert "route has been calculated" in prompt

    def test_route_not_yet_calculated(self, sample_location):
        prompt = build_system_prompt(sample_location, evac_data=[], maps_data=None)
        assert "Not yet calculated" in prompt


class TestBuildSystemPromptTimestamp:
    def test_utc_timestamp_in_prompt(self, sample_location, sample_timestamp):
        # Force the UTC fallback path so we get a real datetime string
        with patch("app.services.chatbot._tf") as mock_tf:
            mock_tf.timezone_at.return_value = None
            prompt = build_system_prompt(sample_location, evac_data=[], maps_data=None, timestamp=sample_timestamp)
        assert "2025" in prompt
        assert "UTC" in prompt

    def test_timestamp_fallback_when_no_timezone(self, sample_timestamp):
        with patch("app.services.chatbot._tf") as mock_tf:
            mock_tf.timezone_at.return_value = None
            prompt = build_system_prompt(
                {"lat": 0, "lon": 0, "display": "Unknown"},
                evac_data=[], maps_data=None,
                timestamp=sample_timestamp,
            )
        assert "UTC" in prompt

    def test_no_timestamp_uses_current_time(self, sample_location):
        prompt = build_system_prompt(sample_location, evac_data=[], maps_data=None, timestamp=None)
        assert "Date & Time" in prompt


class TestBuildSystemPromptLocation:
    def test_location_display_in_prompt(self, sample_location):
        prompt = build_system_prompt(sample_location, evac_data=[], maps_data=None)
        assert "Montrose, Colorado" in prompt

    def test_coordinates_in_prompt(self, sample_location):
        prompt = build_system_prompt(sample_location, evac_data=[], maps_data=None)
        assert "38.5021" in prompt
