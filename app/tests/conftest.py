"""
Shared fixtures for all pytest tests.
Sensitive keys (ANTHROPIC_API_KEY, ORS_API, GOOGLE_CLOUD_PROJECT) are loaded
from the project .env file. Test-only defaults are set for non-secret values.
"""
import sys
from unittest.mock import MagicMock

# Mock packages that are only available in the wids conda env.
# This lets the test suite run in any Python (e.g. base Python 3.13).
_HEAVY_MOCKS = [
    "anthropic",
    "google", "google.cloud", "google.cloud.bigquery",
    "google.cloud.bigquery_storage",
    "google.cloud.firestore", "google.oauth2", "google.auth",
    "google.auth.transport", "google.auth.transport.requests",
    "firebase_admin",
    "contextily", "contextily.place", "contextily.tile",
    "folium",
    "matplotlib", "matplotlib.pyplot", "matplotlib.patches", "matplotlib.lines",
    "geopandas", "pyogrio",
    "shapely", "shapely.geometry", "shapely.ops",
    "rasterio", "openrouteservice",
    "cfgrib", "herbie",
    "numba",
    "timezonefinder", "timezonefinder.timezonefinder", "timezonefinder.utils",
    # NOTE: do NOT mock pytz — pandas imports pytz.tzinfo internally and needs the real package
]
for _mod in _HEAVY_MOCKS:
    sys.modules.setdefault(_mod, MagicMock())

# numba checks scipy.__version__ at import — give the mock a real version string
_scipy_mock = MagicMock()
_scipy_mock.__version__ = "1.17.1"
sys.modules.setdefault("scipy", _scipy_mock)
sys.modules.setdefault("scipy.ndimage", MagicMock())

from dotenv import load_dotenv
import os

# Load real secrets from .env before any app module is imported
load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))

# Non-secret defaults for values that must exist at module load time
os.environ.setdefault("ANTHROPIC_LLM_MODEL",        "claude-sonnet-4-6")
os.environ.setdefault("ANTHROPIC_MAX_TOKENS",       "1500")
os.environ.setdefault("CHATBOT_SUMMARY_THRESHOLD",  "20")
os.environ.setdefault("CHATBOT_HISTORY_LAST_TURNS", "20")

import pytest
from datetime import datetime
from unittest.mock import patch


@pytest.fixture
def sample_location():
    return {
        "lat": 38.5021, "lon": -107.7232,
        "city": "Montrose", "state": "Colorado",
        "display": "Montrose, Colorado",
    }


@pytest.fixture
def sample_evac_data():
    return [{"id": "zone1", "name": "Zone A", "date_modified": "2025-08-21"}]


@pytest.fixture
def sample_timestamp():
    """22:00 UTC → 16:00 MDT for Montrose, CO"""
    return datetime(2025, 8, 21, 22, 0, 0)


@pytest.fixture
def api_client():
    """FastAPI test client with BigQuery patched out (uses real API keys from .env)."""
    from fastapi.testclient import TestClient
    with patch("google.cloud.bigquery.Client"):
        from app.main import app
        return TestClient(app)
