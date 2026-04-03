"""
memory_service.py

Cross-session semantic memory for Beacon using mem0 + Qdrant Cloud.

Write pattern: call add_memory() in the post-stream hook with the last
  user+assistant exchange. Best-effort — never blocks the response.

Read pattern: call search_memories() at session/start after evac data
  is fetched. Returns a formatted string ready to inject into the system prompt.

Anonymous users (user_id == "anonymous") are silently skipped.
"""

from __future__ import annotations

import asyncio
import os
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

_ANON = "anonymous"
_COLLECTION = "beacon_user_memories"
_TOP_K = 5

# Fixed search query — broad enough to retrieve any household/preference fact.
_SEARCH_QUERY = (
    "user household facts: pets, children, seniors, mobility needs, "
    "property features, stated concerns, evacuation preferences, language"
)

# What mem0 should extract and remember — injected as the mem0 system prompt.
_MEM0_INSTRUCTIONS = """
You are a memory extractor for a wildfire evacuation assistant called Beacon.
Extract and store ONLY facts that are true about this person across time and would
help Beacon respond better in future sessions. Store concise, factual statements.

STORE:
- Household composition: pets (species/name if given), livestock, children, seniors, disabled members
- Property facts: owns/rents home, has garage, generator, pool, well, driveway
- Stated concerns or fears (e.g. "worried about her horses", "mom needs oxygen equipment")
- Evacuation preferences or past decisions (e.g. "wants to evacuate to sister's in Pasadena")
- Language preference if mentioned conversationally

DO NOT STORE:
- Emergency event details (fire locations, road closures) — these are ephemeral
- Route data or timestamps of past evacuations
- Checklist completion status — that lives in the database
- Anything speculative or inferred without the user stating it
"""

_client: Optional[object] = None


def _get_client():
    global _client
    if _client is not None:
        return _client

    from mem0 import Memory

    config = {
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "collection_name": _COLLECTION,
                "url": os.getenv("QDRANT_URL"),
                "api_key": os.getenv("QDRANT_API_KEY"),
            },
        },
        "llm": {
            "provider": "anthropic",
            "config": {
                "model": os.getenv("ANTHROPIC_LLM_MODEL", "claude-sonnet-4-6"),
                "api_key": os.getenv("ANTHROPIC_API_KEY"),
            },
        },
        "embedder": {
            "provider": "openai",
            "config": {
                "api_key": os.getenv("OPENAI_API_KEY"),
                "model": "text-embedding-3-small",
            },
        },
        "custom_prompt": _MEM0_INSTRUCTIONS,
    }

    _client = Memory.from_config(config)
    return _client


async def add_memory(user_id: str, messages: list[dict]) -> None:
    """
    Extract and store facts from a user+assistant message exchange.
    messages: the last 2 dicts from session["history"] in {"role", "content"} format.
    Best-effort — exceptions are logged and swallowed.
    """
    if not user_id or user_id == _ANON:
        return
    # Only pass string-content messages (skip tool_use / tool_result blocks)
    clean = [
        {"role": m["role"], "content": m["content"]}
        for m in messages
        if isinstance(m.get("content"), str) and m.get("content", "").strip()
    ]
    if not clean:
        return

    try:
        await asyncio.to_thread(_get_client().add, clean, user_id=user_id)
    except Exception as e:
        print(f"[memory] add_memory failed for {user_id}: {e}")


async def search_memories(user_id: str, query: str = _SEARCH_QUERY) -> str:
    """
    Search for stored facts about this user.
    Returns a formatted string ready to inject into the system prompt,
    or an empty string if no memories exist or on any error.
    """
    if not user_id or user_id == _ANON:
        return ""

    try:
        results = await asyncio.to_thread(
            _get_client().search,
            query,
            user_id=user_id,
            limit=_TOP_K,
        )
        memories = results.get("results", results) if isinstance(results, dict) else results
        if not memories:
            return ""
        lines = [m.get("memory", str(m)) for m in memories if m]
        return "\n".join(f"- {line}" for line in lines if line)
    except Exception as e:
        print(f"[memory] search_memories failed for {user_id}: {e}")
        return ""
