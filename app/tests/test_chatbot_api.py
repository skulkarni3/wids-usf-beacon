"""Tests for POST /chat/session/start and POST /chat/message endpoints."""
pytest = __import__("pytest")
fastapi = pytest.importorskip("fastapi", reason="fastapi not installed in this environment")

import json
from unittest.mock import patch, MagicMock, AsyncMock


SESSION_START_PAYLOAD = {
    "lat": 38.5021,
    "lon": -107.7232,
    "timestamp": "2025-08-21T22:00:00Z",
    "user_id": "test-user",
    "distance": 50000,
    "hwp_threshold": 50,
    "hwp_max_fraction": 0.1,
    "max_candidates": 100,
    "dropby_type": "store",
}


def _mock_session_deps():
    """Context managers to patch all external calls in session/start."""
    return (
        patch("app.routes.chatbot_api.check_evac.return_evac_records",
              return_value=MagicMock(
                  __getitem__=lambda self, k: self,
                  to_numpy=lambda self: [],
              )),
        patch("app.services.location.requests.get",
              return_value=MagicMock(
                  raise_for_status=lambda: None,
                  json=lambda: {"address": {"city": "Montrose", "state": "Colorado"}},
              )),
        patch("app.routes.chatbot_api.chat_store.save_session", new_callable=AsyncMock),
    )


class TestSessionStart:
    def test_returns_session_id(self, api_client):
        evac_df = MagicMock()
        evac_df.__getitem__ = MagicMock(return_value=evac_df)
        evac_df.to_numpy = MagicMock(return_value=[])

        with patch("app.routes.chatbot_api.check_evac.return_evac_records", return_value=evac_df), \
             patch("app.services.location.requests.get") as mock_geo, \
             patch("app.routes.chatbot_api.chat_store.save_session", new_callable=AsyncMock):

            mock_geo.return_value.raise_for_status.return_value = None
            mock_geo.return_value.json.return_value = {
                "address": {"city": "Montrose", "state": "Colorado"}
            }

            resp = api_client.post("/chat/session/start", json=SESSION_START_PAYLOAD)

        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data
        assert len(data["session_id"]) > 0

    def test_location_in_response(self, api_client):
        evac_df = MagicMock()
        evac_df.__getitem__ = MagicMock(return_value=evac_df)
        evac_df.to_numpy = MagicMock(return_value=[])

        with patch("app.routes.chatbot_api.check_evac.return_evac_records", return_value=evac_df), \
             patch("app.services.location.requests.get") as mock_geo, \
             patch("app.routes.chatbot_api.chat_store.save_session", new_callable=AsyncMock):

            mock_geo.return_value.raise_for_status.return_value = None
            mock_geo.return_value.json.return_value = {
                "address": {"city": "Montrose", "state": "Colorado"}
            }

            resp = api_client.post("/chat/session/start", json=SESSION_START_PAYLOAD)

        assert resp.status_code == 200
        data = resp.json()
        assert data["location"]["display"] == "Montrose, Colorado"

    def test_geojson_is_none(self, api_client):
        """session/start must never return a geojson — map uses /route/generate."""
        evac_df = MagicMock()
        evac_df.__getitem__ = MagicMock(return_value=evac_df)
        evac_df.to_numpy = MagicMock(return_value=[])

        with patch("app.routes.chatbot_api.check_evac.return_evac_records", return_value=evac_df), \
             patch("app.services.location.requests.get") as mock_geo, \
             patch("app.routes.chatbot_api.chat_store.save_session", new_callable=AsyncMock):

            mock_geo.return_value.raise_for_status.return_value = None
            mock_geo.return_value.json.return_value = {"address": {"city": "Montrose", "state": "Colorado"}}

            resp = api_client.post("/chat/session/start", json=SESSION_START_PAYLOAD)

        assert resp.json().get("geojson") is None


class TestChatMessage:
    def test_unknown_session_returns_404(self, api_client):
        resp = api_client.post("/chat/message", json={
            "session_id": "nonexistent-session-id",
            "message": "Hello",
        })
        assert resp.status_code == 404


class TestRouteToolGating:
    def test_checklist_message_omits_route_tool(self):
        from app.services.chat_intent import should_include_route_tool

        assert should_include_route_tool("What key steps are remaining for me?") is False

    def test_onboarding_message_omits_route_tool(self):
        from app.services.chat_intent import should_include_route_tool

        assert should_include_route_tool("I need to redo onboarding") is False

    def test_explicit_route_includes_tool(self):
        from app.services.chat_intent import should_include_route_tool

        assert should_include_route_tool("Show me the evacuation route") is True

    def test_urgency_includes_tool(self):
        from app.services.chat_intent import should_include_route_tool

        assert should_include_route_tool("We need to leave now the fire is close") is True

    def test_checklist_plus_route_includes_tool(self):
        from app.services.chat_intent import should_include_route_tool

        assert should_include_route_tool("What's on my checklist and show me the map route") is True

    def test_smalltalk_omits_route_tool(self):
        from app.services.chat_intent import should_include_route_tool

        assert should_include_route_tool("Hello") is False


class TestSuggestedChatActions:
    def test_checklist_phrase(self):
        from app.services.chat_intent import suggested_chat_actions

        acts = suggested_chat_actions("What's left on my checklist?")
        ids = [a["id"] for a in acts]
        assert "open_checklist" in ids

    def test_onboarding_phrase(self):
        from app.services.chat_intent import suggested_chat_actions

        acts = suggested_chat_actions("I need to redo onboarding")
        ids = [a["id"] for a in acts]
        assert "open_onboarding" in ids

    def test_route_phrase(self):
        from app.services.chat_intent import suggested_chat_actions

        acts = suggested_chat_actions("Show me evacuation directions")
        ids = [a["id"] for a in acts]
        assert "open_map" in ids

    def test_combined_intents(self):
        from app.services.chat_intent import suggested_chat_actions

        acts = suggested_chat_actions("What's on my checklist and how do I get out — route?")
        ids = [a["id"] for a in acts]
        assert "open_checklist" in ids
        assert "open_map" in ids
