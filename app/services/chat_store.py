import os
import traceback
from datetime import datetime
from typing import Any, Optional

from google.cloud import firestore
from google.api_core.exceptions import PermissionDenied, GoogleAPICallError


_COLLECTION = os.getenv("CHATBOT_CONVERSATIONS_COLLECTION", "conversations")
_USERS_COLLECTION = os.getenv("CHATBOT_USERS_COLLECTION", "chat_users")
_SESSIONS_SUBCOLLECTION = os.getenv("CHATBOT_USER_SESSIONS_SUBCOLLECTION", "sessions")

_db: Optional[firestore.Client] = None


def _get_db() -> firestore.Client:
    """Initialize the firestore client"""
    global _db
    if _db is None:
        _db = firestore.Client()
    return _db


def _reduce_history_to_text(history: list[dict[str, Any]]) -> list[dict[str, str]]:
    """
    Keep only user/assistant natural-language turns for easy resume.

    Drop Anthropic tool-internal messages (tool_use/tool_result blocks)
    """
    reduced: list[dict[str, str]] = []
    for m in history or []:
        role = m.get("role")
        content = m.get("content")
        if role in ("user", "assistant") and isinstance(content, str):
            reduced.append({"role": role, "content": content})
    return reduced


def _trim_to_last_turns(reduced_history: list[dict[str, str]], last_turns: int) -> list[dict[str, str]]:
    if last_turns <= 0:
        return []

    user_indices = [i for i, m in enumerate(reduced_history) if m.get("role") == "user"]
    if len(user_indices) <= last_turns:
        return reduced_history

    keep_from = user_indices[-last_turns]
    return reduced_history[keep_from:]


def _json_safe(value: Any) -> Any:
    """Best-effort conversion to JSON-serializable primitives."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return str(value)


def _session_doc_ref(user_id: str, conversation_id: str):
    return (
        _get_db()
        .collection(_USERS_COLLECTION)
        .document(user_id)
        .collection(_SESSIONS_SUBCOLLECTION)
        .document(conversation_id)
    )


def _legacy_doc_ref(conversation_id: str):
    return _get_db().collection(_COLLECTION).document(conversation_id)


def save_session(
    conversation_id: str,
    session: dict[str, Any],
    *,
    last_turns: int,
    user_id: Optional[str] = None,
) -> None:
    """
    Persist a conversation state document to Firestore.

    `conversation_id` is the same as the client's `session_id`.
    """
    ts: Optional[datetime] = session.get("timestamp")
    timestamp_iso = ts.isoformat() if isinstance(ts, datetime) else None

    reduced_history = _reduce_history_to_text(session.get("history") or [])
    reduced_history = _trim_to_last_turns(reduced_history, last_turns=last_turns)

    session_user_id = user_id or session.get("user_id") or "anonymous"

    # system_prompt is NOT persisted — it can be 50-100KB and is deterministically
    # rebuilt from location + evac_data at session load time. Storing it was the
    # most likely cause of silent write failures (serialisation size / Firestore limits).
    payload: dict[str, Any] = {
        "user_id": session_user_id,
        "session_id": conversation_id,
        "timestamp_iso": timestamp_iso,
        "location": _json_safe(session.get("location")),
        "evac_data": _json_safe(session.get("evac_data")),
        "language": session.get("language", "en"),
        "has_household": session.get("has_household", False),
        "history": reduced_history,
        "updated_at_iso": datetime.utcnow().isoformat(),
    }

    try:
        print(f"[chat_store] saving session {conversation_id} for {session_user_id} "
              f"({len(reduced_history)} turns, payload ~{len(str(payload))} chars)")
        _session_doc_ref(session_user_id, conversation_id).set(payload, merge=True)
        print(f"[chat_store] session save SUCCESS {conversation_id}")
        # Keep per-user metadata for "previous sessions" browsing.
        user_payload = {
            "updated_at_iso": payload["updated_at_iso"],
            "latest_session_id": conversation_id,
            "sessions_index": {
                conversation_id: {
                    "session_id": conversation_id,
                    "updated_at_iso": payload["updated_at_iso"],
                    "timestamp_iso": timestamp_iso,
                }
            },
        }
        _get_db().collection(_USERS_COLLECTION).document(session_user_id).set(user_payload, merge=True)
        print(f"[chat_store] user index save SUCCESS {session_user_id}")
    except Exception as e:
        print(f"[chat_store] save_session FAILED for {conversation_id}:\n{traceback.format_exc()}")


def load_session(
    conversation_id: str,
    *,
    last_turns: int,
    user_id: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    try:
        doc = None
        if user_id:
            doc = _session_doc_ref(user_id, conversation_id).get()
        if not doc or not doc.exists:
            # Backward compatibility for sessions persisted before user-scoped storage.
            doc = _legacy_doc_ref(conversation_id).get()
    except PermissionDenied as e:
        print(f"[chat_store] load_session PermissionDenied: {e}")
        return None
    except GoogleAPICallError as e:
        print(f"[chat_store] load_session GoogleAPICallError: {e}")
        return None

    if not doc.exists:
        return None

    data = doc.to_dict() or {}

    timestamp_iso = data.get("timestamp_iso")
    timestamp = datetime.fromisoformat(timestamp_iso) if isinstance(timestamp_iso, str) else None

    history = data.get("history") or []
    history = _trim_to_last_turns(history, last_turns=last_turns)

    return {
        "user_id":       data.get("user_id") or user_id,
        "location":      data.get("location"),
        "evac_data":     data.get("evac_data"),
        "language":      data.get("language", "en"),
        "has_household": data.get("has_household", False),
        "history":       history,
        "timestamp":     timestamp,
        # system_prompt is NOT persisted — rebuilt in chatbot_api on load.
        "system_prompt": None,
    }
