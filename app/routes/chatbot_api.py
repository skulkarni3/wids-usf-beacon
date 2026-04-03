"""
chatbot_api.py

FastAPI routes for the Beacon chat agent.

Endpoints:
    POST /chat/session/start   — build session context from GPS coords
    GET  /chat/session/{id}    — fetch persisted state for a returning user
    POST /chat/message         — stream Claude's reply (SSE)

Language architecture:
    - user_preferences.language is the single source of truth.
    - The iOS client sends preferred_language on MessageRequest (read from its
      own SettingsManager). The server uses that to build the system prompt.
    - Claude auto-detects the language the user WRITES in and responds in that
      language. If it differs from preferred_language, Claude offers to update
      the stored preference by calling update_user_preferences.
    - PATCH /user/preferences/language is also called directly by the iOS
      Settings picker when the user manually changes the language.
    - No SSE overwriting Settings without user confirmation.

Tool dispatch:
    - chat_intent.classify() decides which tools the agent receives per turn.
    - Supplements are injected only for non-emergency in-app flows.

Async notes:
    - chat_message and generate() are async so they can await DB calls made
      by tool handlers (checklist upsert, language preference update).
    - The Anthropic AsyncAnthropic client is used throughout.
    - maps_api.generate_route is also async; awaited directly.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

import anthropic
import openai as _openai_module
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..services import chatbot, check_evac, location as location_svc
from ..services import chat_store
from ..services.memory_service import add_memory, search_memories
from ..services.chat_intent import (
    Intent, classify,
    should_include_route_tool,
    should_include_checklist_tool,
    should_include_language_tool,
    suggested_actions,
)
from ..services.user_preferences import get_user_preferences, update_language, DEFAULT_LANGUAGE
from ..services.onboarding import load_household, HOUSEHOLD_ANSWER_FIELDS
from ..services.checklist import generate_checklist
from .checklist_api import _upsert_checked_state, _recurrence_type_for_item, _compute_next_due
from . import maps_api

load_dotenv()

router = APIRouter()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_MODEL             = os.getenv("ANTHROPIC_LLM_MODEL")
_MAX_TOKENS        = int(os.getenv("ANTHROPIC_MAX_TOKENS"))
_SUMMARY_THRESHOLD = int(os.getenv("CHATBOT_SUMMARY_THRESHOLD"))
_HISTORY_TURNS     = int(os.getenv("CHATBOT_HISTORY_LAST_TURNS", "20"))
_ANON              = "anonymous"

client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

_openai_client = _openai_module.AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

sessions: dict = {}
_session_locks: dict[str, asyncio.Lock] = {}


def _get_session_lock(session_id: str) -> asyncio.Lock:
    if session_id not in _session_locks:
        _session_locks[session_id] = asyncio.Lock()
    return _session_locks[session_id]


# ---------------------------------------------------------------------------
# Layer-2 semantic classifier (GPT-4o-mini, only fires when Layer-1 = NONE)
# ---------------------------------------------------------------------------

_SEMANTIC_CLASSIFY_SYSTEM = (
    "Classify the user message into exactly one category. "
    "Reply with ONLY the category name — no punctuation, no explanation.\n\n"
    "Categories:\n"
    "  onboarding — any mention of household members, pets, livestock, property features, "
    "family changes, visitors, or anything that would change the user's household profile "
    "(e.g. 'my grandad is visiting', 'we got a puppy', 'sold the house', 'mom moved in')\n"
    "  checklist  — user reports completing a preparedness task or doing something on their list\n"
    "  route      — user wants evacuation directions or to leave now\n"
    "  urgent     — fire is imminent or person is in immediate danger\n"
    "  general    — anything else (questions, greetings, unrelated topics)"
)

async def _semantic_classify(message: str) -> Intent:
    """
    GPT-4o-mini fallback classifier for messages that scored Intent.NONE from keyword matching.
    ~100-150ms, costs ~$0.00015 per call at gpt-4o-mini pricing.
    """
    try:
        resp = await _openai_client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=10,
            temperature=0,
            messages=[
                {"role": "system", "content": _SEMANTIC_CLASSIFY_SYSTEM},
                {"role": "user",   "content": message},
            ],
        )
        label = resp.choices[0].message.content.strip().lower()
        return {
            "onboarding": Intent.ONBOARDING,
            "checklist":  Intent.CHECKLIST,
            "route":      Intent.ROUTE,
            "urgent":     Intent.URGENT,
        }.get(label, Intent.NONE)
    except Exception as e:
        print(f"[semantic_classify] failed, defaulting to NONE: {e}")
        return Intent.NONE


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

ROUTE_TOOL = {
    "name": "get_evacuation_route",
    "description": (
        "Compute and display the evacuation route from the user's current GPS location. "
        "Call ONLY when the user explicitly wants turn-by-turn routing right now: "
        "'how do I get out', 'show my route', 'which way should I drive'. "
        "Do NOT call for: checklist status, onboarding questions, settings, language, "
        "or general prep advice.\n\n"
        "prefer_dropby: set to true ONLY when the user has already been offered a drop-by "
        "option and confirmed they want to include a stop. Default false."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "prefer_dropby": {
                "type": "boolean",
                "description": "True only when user confirmed they want a drop-by stop.",
            }
        },
        "required": [],
    },
}

CHECKLIST_TOOL = {
    "name": "toggle_checklist_item",
    "description": (
        "Check off or uncheck a specific item on the user's personal evacuation checklist. "
        "Match the user's words to the closest item ID from the checklist context in your system prompt.\n\n"
        "When to call immediately (no confirmation needed):\n"
        "- The user clearly reports completing a task: 'I cleared zone 0', 'my go-bag is packed', etc.\n"
        "- The user has already confirmed in this conversation: 'yes', 'go ahead', 'please do', etc.\n\n"
        "When to ask first:\n"
        "- It is ambiguous whether the task is done or just planned.\n\n"
        "Do not call speculatively without a clear completion signal or confirmation."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "item_id": {
                "type": "string",
                "description": "The checklist item ID from the system prompt, e.g. 'ds_zone0'",
            },
            "checked": {
                "type": "boolean",
                "description": "True to mark complete, False to uncheck.",
            },
        },
        "required": ["item_id", "checked"],
    },
}

def _make_checklist_tool(item_ids: list[str]) -> dict:
    """Return CHECKLIST_TOOL with item_id constrained to the user's actual item IDs."""
    return {
        **CHECKLIST_TOOL,
        "input_schema": {
            **CHECKLIST_TOOL["input_schema"],
            "properties": {
                "item_id": {
                    "type": "string",
                    "enum": item_ids,
                    "description": "Exact item ID from == USER'S CHECKLIST ITEMS ==. Must be one of the listed values.",
                },
                "checked": CHECKLIST_TOOL["input_schema"]["properties"]["checked"],
            },
        },
    }


LANGUAGE_TOOL = {
    "name": "update_user_preferences",
    "description": (
        "Persist the user's preferred app language. "
        "Call ONLY after the user explicitly confirms they want to change the language — "
        "never call automatically just because they wrote in a different language. "
        "Never call mid-emergency (urgency HIGH or CRITICAL). "
        "The language parameter must be a valid ISO 639-1 code (e.g. 'es', 'zh', 'fr')."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "language": {
                "type": "string",
                "description": "ISO 639-1 language code to save, e.g. 'es'",
            },
        },
        "required": ["language"],
    },
}


# ---------------------------------------------------------------------------
# Tool-list builder  (single source of truth)
# ---------------------------------------------------------------------------

def _tool_list(intent: Intent) -> list[dict]:
    tools = []
    if should_include_route_tool(intent):
        tools.append(ROUTE_TOOL)
    if should_include_checklist_tool(intent):
        tools.append(CHECKLIST_TOOL)
    if should_include_language_tool(intent):
        tools.append(LANGUAGE_TOOL)
    return tools


# ---------------------------------------------------------------------------
# Checklist context for system prompt
# ---------------------------------------------------------------------------

def _checklist_prompt_context(items_by_category: dict) -> str:
    """
    Build a compact checklist listing for the system prompt so Claude can
    fuzzy-match user statements to item IDs when calling toggle_checklist_item.
    """
    lines = [
        "== USER'S CHECKLIST ITEMS ==",
        "When the user describes completing a task, match it to the closest item ID below.",
        "Always confirm with the user before calling toggle_checklist_item.",
    ]
    for cat, items in items_by_category.items():
        lines.append(f"\n[{cat.replace('_', ' ').title()}]")
        for item in items:
            lines.append(f"  {item['id']}: {item['text']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# System-prompt supplements
# ---------------------------------------------------------------------------

_SUPPLEMENTS: dict[Intent, str] = {
    Intent.ONBOARDING: (
        "== THIS-TURN OVERRIDE — READ CAREFULLY ==\n"
        "The user mentioned a household change or wants to update onboarding answers.\n"
        "YOUR ENTIRE RESPONSE must be ≤2 sentences:\n"
        "  Sentence 1: Acknowledge the specific change they mentioned (1 sentence, no bullet points).\n"
        "  Sentence 2: EXACTLY this: 'Tap the button below to update your household info right now.'\n"
        "FORBIDDEN — do NOT write any of these:\n"
        "  - 'Go to Settings'\n"
        "  - 'Open the gear tab'\n"
        "  - 'Navigate to Settings → Update onboarding answers'\n"
        "  - Any step-by-step navigation instructions\n"
        "  - More than 2 sentences\n"
        "  - Bullet points or numbered lists\n"
        "A button labeled 'Update onboarding answers' will automatically appear below your message.\n"
        "CRITICAL: There is NO tool for updating household answers — do not attempt any tool call."
    ),
    Intent.CHECKLIST: (
        "== THIS-TURN CHECKLIST ==\n"
        "The user is asking about their checklist or prep tasks.\n"
        "If they want to SEE their checklist: tell them to open the Checklist tab (✓ icon) — 1 sentence.\n"
        "If they mention completing something: call toggle_checklist_item IMMEDIATELY, then respond in ≤3 sentences:\n"
        "  1. 'Checked off [item] for you.'\n"
        "  2. One relevant safety fact (optional, only if it adds real value).\n"
        "  3. 'Let me know what else you've completed.' — or similar encouragement.\n"
        "STOP at 3 sentences. No bullet points. No additional tips. No explaining items they didn't ask about.\n"
        "Do NOT call get_evacuation_route for checklist questions."
    ),
    Intent.LANGUAGE: (
        "== THIS-TURN LANGUAGE ==\n"
        "The user wants to change their language setting.\n"
        "Respond in ≤2 sentences: confirm you understand, tell them you can update it right here.\n"
        "Ask: 'Would you like me to save [Language] as your app language now?' "
        "If they say yes, call update_user_preferences(language=...) with the ISO 639-1 code.\n"
        "The 'Change language settings' button below also takes them to the Settings picker."
    ),
    Intent.TASK_MENTION: (
        "== THIS-TURN TASK COMPLETION ==\n"
        "The user is reporting they completed a preparedness task.\n"
        "Match what they said to the closest item in == USER'S CHECKLIST ITEMS ==.\n"
        "IMMEDIATELY call toggle_checklist_item — do NOT ask for confirmation first.\n"
        "After the tool returns, reply in 1-2 sentences: 'I went ahead and checked off \"[item name]\" for you.' "
        "If the item is recurring (weekly/monthly/quarterly/annual), add one sentence: "
        "'This is a [weekly/monthly] task — the app will automatically reset it when it's due again.'\n"
        "Do NOT say 'Should I check this off?' or 'Want me to mark that?' — just do it."
    ),
}


_URGENT_SUPPLEMENT = (
    "== THIS-TURN EMERGENCY PROTOCOL ==\n"
    "The user is in immediate danger. Follow this exact sequence:\n"
    "1. BEFORE calling get_evacuation_route, stream 2-3 sentences of immediate life-safety "
    "instructions in plain language. Examples: 'Leave now. Take your keys, phone, and medications — "
    "nothing else. Close all doors behind you but do not lock them.' or 'Cover your nose and mouth. "
    "Stay low if there is smoke. Do not stop for belongings.' Match the instructions to what "
    "the user described (faint/smoke/flames/trapped).\n"
    "2. THEN call get_evacuation_route to calculate their route.\n"
    "3. After the route returns, give the first 2-3 turns and say to watch for road signs.\n"
    "CRITICAL: Respond in the EXACT language of THIS message — not any earlier message in the conversation.\n"
    "CRITICAL: Never promise to send reminders. Never ask about onboarding or language settings."
)


def _build_system_prompt(base: str, intent: Intent, language: str = "en", language_offer_made: bool = False) -> str:
    """
    Append supplements based on intent.
    URGENT gets its own supplement (pre-route safety instructions).
    Other in-app intents get their usual redirects.
    Per-turn language is always injected so history language doesn't bleed through.
    """
    parts = [base]

    # Always inject a language rule so history in another language doesn't bleed through.
    parts.append(
        f"== CURRENT TURN LANGUAGE — HIGHEST PRIORITY ==\n"
        f"Detect the language of THE MOST RECENT USER MESSAGE and reply in that language ONLY.\n"
        f"Ignore all previous messages when deciding which language to use.\n"
        f"Examples: user writes English → reply in English. User writes Spanish → reply in Spanish.\n"
        f"User writes a mix → match the dominant language of the current message.\n"
        f"The stored app language preference ('{language}') is used only for UI strings, NOT for your replies."
    )

    if Intent.URGENT in intent or Intent.ROUTE in intent:
        parts.append(_URGENT_SUPPLEMENT)
    else:
        extras = [body for flag, body in _SUPPLEMENTS.items() if flag in intent]
        parts.extend(extras)

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class StartRequest(BaseModel):
    lat: float
    lon: float
    timestamp: Optional[str] = None
    user_id: Optional[str] = None
    distance: float = 50000
    hwp_threshold: float = 50
    hwp_max_fraction: float = 0.1
    max_candidates: int = 100
    dropby_type: str = "store"
    language: Optional[str] = None    # ISO 639-1 code from client; skips detection on first message

class StartResponse(BaseModel):
    session_id: str
    location: dict
    evac_data: Optional[list]
    geojson: Optional[dict]
    language: str  # resolved language — iOS reads this to sync SettingsManager

class MessageRequest(BaseModel):
    session_id: str
    message: str
    # Client sends its current language so the server never needs to detect it.
    # Defaults to 'en' if the client is on an old build that doesn't send it yet.
    preferred_language: str = DEFAULT_LANGUAGE

class SessionStateResponse(BaseModel):
    session_id: str
    location: Optional[dict]
    evac_data: Optional[list]
    history: list[dict]
    timestamp: Optional[datetime]
    language: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _session_id(user_id: str) -> str:
    return f"{user_id}:{uuid.uuid4()}"

def _user_id_from_session(session_id: str) -> str:
    if ":" not in session_id:
        return _ANON
    uid, _ = session_id.split(":", 1)
    return uid or _ANON

async def _maybe_summarize(session: dict) -> None:
    if len(session["history"]) < _SUMMARY_THRESHOLD:
        return
    history_text = "\n".join(
        f"{m['role'].upper()}: {m['content']}"
        for m in session["history"]
        if isinstance(m.get("content"), str)
    )
    resp = await client.messages.create(
        model=_MODEL,
        max_tokens=512,
        messages=[{"role": "user", "content": (
            "Summarize this emergency chat concisely, keeping all safety details, "
            "locations, and decisions made:\n\n" + history_text
        )}],
    )
    session["history"] = [
        {"role": "user",      "content": f"Summary of our conversation so far: {resp.content[0].text}"},
        {"role": "assistant", "content": "Understood. I have the context from our previous conversation."},
    ]

async def _save_session(session_id: str, session: dict, user_id: str, label: str = "") -> None:
    try:
        await asyncio.to_thread(
            chat_store.save_session, session_id, session,
            last_turns=_HISTORY_TURNS, user_id=user_id,
        )
    except Exception as e:
        print(f"[chat_store] save({label}) failed: {e}")


def _block_type(block) -> str:
    return block.type if hasattr(block, "type") else block.get("type", "")


def _block_id(block) -> str:
    return getattr(block, "id", None) or block.get("id", "")


def _block_tool_use_id(block) -> str:
    return getattr(block, "tool_use_id", None) or block.get("tool_use_id", "")


def _strip_dangling_tool_use(history: list[dict]) -> list[dict]:
    """
    Remove turns that would cause Claude to return a 400:
      - assistant turn with tool_use blocks whose ids have no matching
        tool_result in the immediately following user turn.
      - user turn with tool_result blocks whose tool_use_ids have no matching
        tool_use in the immediately preceding assistant turn.
    Both directions are handled so one-sided orphans from either type of
    stream failure are cleaned up automatically.
    """
    # Collect all tool_use ids that are properly paired.
    paired_ids: set[str] = set()
    for i, msg in enumerate(history):
        if msg["role"] == "assistant" and isinstance(msg.get("content"), list):
            use_ids = {_block_id(b) for b in msg["content"] if _block_type(b) == "tool_use"}
            if not use_ids:
                continue
            next_msg = history[i + 1] if i + 1 < len(history) else None
            if (
                next_msg is not None
                and next_msg["role"] == "user"
                and isinstance(next_msg.get("content"), list)
            ):
                result_ids = {_block_tool_use_id(b) for b in next_msg["content"] if _block_type(b) == "tool_result"}
                paired_ids |= use_ids & result_ids

    cleaned = []
    for i, msg in enumerate(history):
        content = msg.get("content")
        if not isinstance(content, list):
            cleaned.append(msg)
            continue

        if msg["role"] == "assistant":
            use_ids = {_block_id(b) for b in content if _block_type(b) == "tool_use"}
            if use_ids and not use_ids.issubset(paired_ids):
                print(f"[chat] stripping dangling tool_use at history index {i} (ids={use_ids - paired_ids})")
                continue

        if msg["role"] == "user":
            result_ids = {_block_tool_use_id(b) for b in content if _block_type(b) == "tool_result"}
            if result_ids and not result_ids.issubset(paired_ids):
                print(f"[chat] stripping dangling tool_result at history index {i} (ids={result_ids - paired_ids})")
                continue

        cleaned.append(msg)
    return cleaned


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/chat/session/start", response_model=StartResponse)
async def session_start(body: StartRequest):
    effective_dt = (
        datetime.fromisoformat(body.timestamp.replace("Z", "+00:00")).replace(tzinfo=None)
        if body.timestamp else datetime.now()
    )
    user_id = body.user_id or _ANON

    # Resolve language from persisted preferences (single source of truth).
    # Anonymous users get the default.
    if user_id != _ANON:
        prefs = await get_user_preferences(user_id)
        language = prefs.language
    else:
        language = DEFAULT_LANGUAGE

    loc_data = await asyncio.to_thread(location_svc.get_address_from_lat_lon, body.lat, body.lon)
    session_id = _session_id(user_id)

    # Load checklist context for logged-in users so Claude can match task mentions.
    checklist_ctx: Optional[str] = None
    checklist_item_ids: list[str] = []
    has_household = False
    if user_id != _ANON:
        try:
            household = await load_household(user_id)
            if household:
                has_household = True
                answers = {k: household.get(k) is True for k in HOUSEHOLD_ANSWER_FIELDS}
                raw_items = generate_checklist(answers)
                checklist_ctx = _checklist_prompt_context(raw_items)
                checklist_item_ids = [item["id"] for items in raw_items.values() for item in items]
        except Exception as e:
            print(f"[session_start] checklist context load failed: {e}")

    base_prompt = chatbot.build_system_prompt(loc_data, None, None, language=language)
    new_user_notice = (
        "\n\n== NEW USER — ONBOARDING NOT COMPLETE ==\n"
        "This user has NOT yet completed their household onboarding questions.\n"
        "At the start of this conversation, proactively guide them:\n"
        "1. Briefly introduce yourself and the app (1-2 sentences max).\n"
        "2. Encourage them to complete the onboarding questions in the Checklist tab first — "
        "tell them it takes 1 minute and personalizes their evacuation checklist.\n"
        "3. Once they signal readiness or ask a prep question, explain the evacuation checklist purpose.\n"
        "Do NOT wait for the user to ask about onboarding. Lead with it on the first message."
    ) if (user_id != _ANON and not has_household) else ""
    full_prompt = f"{base_prompt}{new_user_notice}\n\n{checklist_ctx}" if checklist_ctx else f"{base_prompt}{new_user_notice}"

    session: dict = {
        "user_id":        user_id,
        "location":       loc_data,
        "evac_data":      None,
        "geojson":        None,
        "system_prompt":  full_prompt,
        "history":        [],
        "timestamp":      effective_dt,
        "language":       language,
        # Route params stored so the route tool can use them
        "dropby_type":    body.dropby_type,
        "distance":       body.distance,
        "hwp_threshold":  body.hwp_threshold,
        "hwp_max_fraction": body.hwp_max_fraction,
        "max_candidates": body.max_candidates,
        "has_household":      has_household,
        "checklist_item_ids": checklist_item_ids,
    }
    sessions[session_id] = session
    await _save_session(session_id, session, user_id, "initial")

    # Run evac lookup and memory search in parallel.
    evac_task = asyncio.create_task(asyncio.to_thread(
        check_evac.return_evac_records, body.lon, body.lat, effective_dt, body.distance
    ))
    memory_task = asyncio.create_task(search_memories(user_id))

    try:
        df = await evac_task
        evac_data = (
            df.drop(columns=["geo_json"], errors="ignore").to_dict(orient="records")
            if not df.empty else None
        )
    except Exception as e:
        print(f"[evac] lookup failed: {e}")
        evac_data = None

    try:
        memories = await memory_task
    except Exception as e:
        print(f"[memory] search failed at session start: {e}")
        memories = ""

    updated_base = chatbot.build_system_prompt(
        loc_data, evac_data, None,
        language=language,
        distance=body.distance,
        timestamp=effective_dt,
        memories=memories,
    )
    updated_full = f"{updated_base}{new_user_notice}\n\n{checklist_ctx}" if checklist_ctx else f"{updated_base}{new_user_notice}"
    session.update({
        "evac_data":    evac_data,
        "system_prompt": updated_full,
    })
    await _save_session(session_id, session, user_id, "updated")

    return StartResponse(
        session_id=session_id,
        location=loc_data,
        evac_data=evac_data,
        geojson=None,
        language=language,   # iOS syncs SettingsManager from this on session start
    )


@router.get("/chat/session/{session_id}", response_model=SessionStateResponse)
def get_session_state(session_id: str):
    user_id = _user_id_from_session(session_id)
    if session := sessions.get(session_id):
        # fire-and-forget save — acceptable for read-only state fetch
        asyncio.create_task(_save_session(session_id, session, user_id, "get_state"))

    persisted = chat_store.load_session(session_id, last_turns=_HISTORY_TURNS, user_id=user_id)
    if not persisted:
        raise HTTPException(status_code=404, detail="Session not found. Call /chat/session/start first.")

    return SessionStateResponse(
        session_id=session_id,
        location=persisted.get("location"),
        evac_data=persisted.get("evac_data"),
        history=persisted.get("history") or [],
        timestamp=persisted.get("timestamp"),
        language=persisted.get("language", DEFAULT_LANGUAGE),
    )


@router.patch("/user/preferences/language")
async def set_language(user_id: str, language: str):
    """
    Called by iOS after the user confirms a language change in the settings picker.
    This is the only place that writes to user_preferences — not the SSE stream.
    """
    updated = await update_language(user_id, language)
    return {"status": "ok", "user_id": user_id, "language": updated.language}


@router.post("/chat/message")
async def chat_message(body: MessageRequest):
    user_id = _user_id_from_session(body.session_id)

    session = sessions.get(body.session_id) or chat_store.load_session(
        body.session_id, last_turns=_HISTORY_TURNS, user_id=user_id
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found. Call /chat/session/start first.")

    sessions[body.session_id] = session
    session.setdefault("user_id", user_id)

    # Use client-sent language — no detection, no second Claude call.
    # If client is on an old build, falls back to what's in the session or default.
    language = body.preferred_language or session.get("language", DEFAULT_LANGUAGE)

    # Rebuild system_prompt if it's missing (session was loaded from Firestore, not in-memory).
    if not session.get("system_prompt"):
        try:
            memories = await search_memories(user_id)
        except Exception:
            memories = ""
        base_prompt = chatbot.build_system_prompt(
            session.get("location"), session.get("evac_data"), None,
            language=language,
            timestamp=session.get("timestamp"),
            memories=memories,
        )
        checklist_ctx = None
        if user_id != _ANON:
            try:
                household = await load_household(user_id)
                if household:
                    answers = {k: household.get(k) is True for k in HOUSEHOLD_ANSWER_FIELDS}
                    gen_cl = generate_checklist(answers)
                    checklist_ctx = _checklist_prompt_context(gen_cl)
                    session["checklist_item_ids"] = [item["id"] for items in gen_cl.values() for item in items]
            except Exception:
                pass
        session["system_prompt"] = f"{base_prompt}\n\n{checklist_ctx}" if checklist_ctx else base_prompt

    await _maybe_summarize(session)

    # Layer 1: fast keyword match (free)
    intent = classify(body.message)
    # Layer 2: GPT-4o-mini semantic fallback (only on genuinely ambiguous messages)
    if intent == Intent.NONE:
        intent = await _semantic_classify(body.message)

    tool_list = _tool_list(intent)

    # If Claude offered to check off an item and the user is confirming,
    # the confirmation message ("yes", "go ahead", etc.) won't trigger TASK_MENTION
    # or CHECKLIST intent — so the tool would be missing on the turn it's most needed.
    # Detect this by looking at the last assistant message.
    if CHECKLIST_TOOL not in tool_list:
        last_assistant = next(
            (m["content"] for m in reversed(session["history"]) if m["role"] == "assistant"),
            ""
        )
        if isinstance(last_assistant, str):
            la = last_assistant.lower()
            if any(p in la for p in (
                "check off", "check that off", "mark it", "mark that",
                "want me to check", "shall i check", "should i check",
                "would you like me to check", "go ahead and check",
            )):
                tool_list = tool_list + [CHECKLIST_TOOL]

    # Replace static CHECKLIST_TOOL with enum-constrained version so Claude
    # cannot invent item IDs — it must pick from the user's actual item IDs.
    checklist_ids = session.get("checklist_item_ids")
    if checklist_ids:
        tool_list = [
            _make_checklist_tool(checklist_ids) if (isinstance(t, dict) and t.get("name") == "toggle_checklist_item") else t
            for t in tool_list
        ]

    system_prompt = _build_system_prompt(session["system_prompt"], intent, language)
    actions = suggested_actions(intent)

    session["history"].append({"role": "user", "content": body.message})
    await _save_session(body.session_id, session, user_id, "pre-stream")

    async def generate():
        nonlocal language   # allow reassignment when update_user_preferences runs
        route_has_nearby_dropby = False
        checklist_was_updated = False

        lock = _get_session_lock(body.session_id)
        async with lock:
            # Sanitize before every API call — removes any tool_use/tool_result turn
            # that was persisted without its pair (caused by a previous stream error).
            session["history"] = _strip_dangling_tool_use(session["history"])

            try:
                async with client.messages.stream(
                    model=_MODEL,
                    max_tokens=_MAX_TOKENS,
                    system=system_prompt,
                    messages=session["history"],
                    tools=tool_list,
                ) as stream:
                    first_text = ""
                    async for chunk in stream.text_stream:
                        first_text += chunk
                        yield f"data: {json.dumps({'text': chunk})}\n\n"
                    final_msg = await stream.get_final_message()

                if final_msg.stop_reason == "tool_use":
                    tool_block = next(b for b in final_msg.content if b.type == "tool_use")
                    tool_name = tool_block.name

                    session["history"].append({"role": "assistant", "content": final_msg.content})

                    # ── Route tool ──────────────────────────────────────────────
                    if tool_name == "get_evacuation_route":
                        _fetching_msg = json.dumps({"text": "\n\n_Fetching your evacuation route\u2026_\n\n"})
                        yield f"data: {_fetching_msg}\n\n"

                        prefer_dropby = bool(tool_block.input.get("prefer_dropby", False))
                        loc = session["location"]
                        route_result = await maps_api.generate_route(
                            lat=loc["lat"],
                            lon=loc["lon"],
                            timestamp=session.get("timestamp", datetime.now()),
                            prefer_dropby=prefer_dropby,
                            dropby_type=session.get("dropby_type", "store"),
                            distance=session.get("distance", 50000),
                            hwp_threshold=session.get("hwp_threshold", 50),
                            hwp_max_fraction=session.get("hwp_max_fraction", 0.1),
                            max_candidates=session.get("max_candidates", 100),
                            language=language,
                        )

                        if route_result.get("status") == "no_routes":
                            tool_content = (
                                "No evacuation route could be found. "
                                "Tell the user to call 911 immediately."
                            )
                        else:
                            s = route_result.get("summary", {})
                            dest     = s.get("destination", "nearest shelter")
                            dist     = s.get("distance_km", "?")
                            dur      = s.get("duration_min", "?")
                            dropbys  = s.get("dropbys_on_route", [])

                            tool_content = (
                                f"Route found: {dest}, {dist} km (~{dur} min). "
                                f"The route is now shown on the map tab."
                            )
                            if dropbys and not prefer_dropby:
                                names = ", ".join(dropbys[:3])
                                tool_content += (
                                    f"\n\nNearby drop-by locations found close to this route: {names}. "
                                    "These are NOT currently included as a stop. "
                                    "Offer the user the option to add one — action chips 'add_dropby' "
                                    "and 'skip_dropby' will appear after your message. "
                                    "Do not force a choice."
                                )
                                route_has_nearby_dropby = True
                            elif dropbys and prefer_dropby:
                                names = ", ".join(dropbys[:3])
                                tool_content += f" Drop-by stop included: {names}."

                    # ── Checklist tool ───────────────────────────────────────────
                    elif tool_name == "toggle_checklist_item":
                        item_id = tool_block.input.get("item_id", "")
                        checked  = bool(tool_block.input.get("checked", True))
                        rt       = _recurrence_type_for_item(item_id)

                        if user_id != _ANON:
                            try:
                                await _upsert_checked_state(user_id, item_id, checked)
                                checklist_was_updated = True
                                next_due = _compute_next_due(rt, datetime.now(timezone.utc))
                                tool_content = json.dumps({
                                    "status":          "ok",
                                    "item_id":         item_id,
                                    "checked":         checked,
                                    "recurrence_type": rt,
                                    "next_due_date":   next_due.isoformat() if next_due else None,
                                })
                            except Exception as e:
                                tool_content = json.dumps({"status": "error", "message": str(e)})
                        else:
                            tool_content = json.dumps({
                                "status":  "error",
                                "message": "Cannot update checklist: user not logged in.",
                            })

                    # ── Language tool ────────────────────────────────────────────
                    elif tool_name == "update_user_preferences":
                        new_lang = tool_block.input.get("language", "")
                        if user_id != _ANON and new_lang:
                            try:
                                updated = await update_language(user_id, new_lang)
                                session["language"] = updated.language
                                language = updated.language
                                tool_content = json.dumps({
                                    "status":   "ok",
                                    "language": updated.language,
                                })
                            except Exception as e:
                                tool_content = json.dumps({"status": "error", "message": str(e)})
                        else:
                            tool_content = json.dumps({
                                "status":  "error",
                                "message": "Cannot update language: user not logged in or no language provided.",
                            })

                    else:
                        tool_content = json.dumps({"status": "error", "message": f"Unknown tool: {tool_name}"})

                    session["history"].append({
                        "role": "user",
                        "content": [{"type": "tool_result", "tool_use_id": tool_block.id, "content": tool_content}],
                    })

                    async with client.messages.stream(
                        model=_MODEL,
                        max_tokens=_MAX_TOKENS,
                        system=system_prompt,
                        messages=session["history"],
                    ) as stream2:
                        full_reply = first_text
                        if tool_name == "get_evacuation_route":
                            full_reply = "\n\n_Fetching your evacuation route…_\n\n"
                        async for chunk in stream2.text_stream:
                            full_reply += chunk
                            yield f"data: {json.dumps({'text': chunk})}\n\n"
                    session["history"].append({"role": "assistant", "content": full_reply})

                else:
                    session["history"].append({"role": "assistant", "content": first_text})

            except Exception as e:
                print(f"[chat/message] stream error: {e}")
                # Strip any dangling tool_use/tool_result that caused the error
                # so the next message doesn't hit the same 400.
                session["history"] = _strip_dangling_tool_use(session["history"])
                yield f"data: {json.dumps({'text': 'Something went wrong. Please try again.'})}\n\n"

            # Action chips
            all_actions = list(actions)
            already_has_onboarding = any(a["id"] == "open_onboarding" for a in all_actions)
            if (not already_has_onboarding
                    and Intent.LANGUAGE not in intent):
                full_reply_text = session["history"][-1].get("content", "") if session["history"] else ""
                if isinstance(full_reply_text, str):
                    rl = full_reply_text.lower()
                    if any(kw in rl for kw in (
                        "onboarding", "household questions", "update your household",
                        "household info", "household information",
                    )):
                        all_actions.insert(0, {"id": "open_onboarding", "label": "Update onboarding answers"})
            if route_has_nearby_dropby:
                all_actions += [
                    {"id": "add_dropby",  "label": "Add drop-by stop"},
                    {"id": "skip_dropby", "label": "Skip, continue route"},
                ]
            if checklist_was_updated:
                if not any(a["id"] == "open_checklist" for a in all_actions):
                    all_actions.append({"id": "open_checklist", "label": "Take me to my checklist"})
                yield f"data: {json.dumps({'checklist_updated': True})}\n\n"
            if all_actions:
                yield f"data: {json.dumps({'actions': all_actions})}\n\n"

            yield f"data: {json.dumps({'language': language})}\n\n"
            yield "data: [DONE]\n\n"

            await _save_session(body.session_id, session, user_id, "post-stream")

            # Best-effort memory write — take the last user+assistant exchange.
            if len(session["history"]) >= 2:
                last_exchange = session["history"][-2:]
            try:
                await add_memory(user_id, last_exchange)
            except Exception as e:
                print(f"[memory] post-stream add_memory failed: {e}")

    return StreamingResponse(generate(), media_type="text/event-stream")
