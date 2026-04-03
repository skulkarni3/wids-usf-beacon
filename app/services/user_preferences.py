"""
user_preferences.py

Persistent user preferences backed by Postgres.

Schema (add to your migrations):

    CREATE TABLE user_preferences (
        user_id     UUID PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
        language    VARCHAR(10) DEFAULT 'en',   -- ISO 639-1, e.g. "en", "es", "zh"
        updated_at  TIMESTAMPTZ DEFAULT NOW()
    );

Language semantics:
    - 'en' is the default (never NULL in DB).
    - Settings is the canonical source of truth for language.
    - The chat agent may *propose* a language change via SSE action chip;
      the user must confirm before this is written.
    - The iOS client reads this once at session/start and passes it on
      MessageRequest — the server does not re-detect language per message.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.services.pg_pool import get_pool

SUPPORTED_LANGUAGES: frozenset[str] = frozenset({
    "en", "es", "zh", "fr", "de", "ko", "ja",
    "vi", "tl", "ar", "hi", "pt", "ru",
})

DEFAULT_LANGUAGE = "en"


@dataclass
class UserPreferences:
    user_id: str
    language: str = DEFAULT_LANGUAGE


def _sanitize_language(code: Optional[str]) -> str:
    """Normalize to a supported ISO 639-1 code, falling back to default."""
    if not code:
        return DEFAULT_LANGUAGE
    normalized = code.strip().lower()[:2]
    return normalized if normalized in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def get_user_preferences(user_id: str) -> UserPreferences:
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT language FROM user_preferences WHERE user_id = $1",
        user_id,
    )
    if row is None:
        return UserPreferences(user_id=user_id, language=DEFAULT_LANGUAGE)
    return UserPreferences(user_id=user_id, language=_sanitize_language(row["language"]))


async def update_language(user_id: str, language: str) -> UserPreferences:
    """
    Persist a confirmed language change. Only call this after the user
    has explicitly confirmed they want to switch (via the action chip).
    """
    lang = _sanitize_language(language)
    pool = await get_pool()
    await pool.execute(
        """
        INSERT INTO user_preferences (user_id, language, updated_at)
        VALUES ($1, $2, NOW())
        ON CONFLICT (user_id) DO UPDATE
            SET language = EXCLUDED.language,
                updated_at = NOW()
        """,
        user_id, lang,
    )
    return UserPreferences(user_id=user_id, language=lang)