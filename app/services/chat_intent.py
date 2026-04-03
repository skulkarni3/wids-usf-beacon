"""
chat_intent.py

Single-responsibility: classify a user message into one or more intents
and decide which tools + prompt supplements the agent gets for that turn.

Design rules:
  - One Intent enum, one classify() function, one tool-list function.
  - No business logic here — just routing decisions.
  - Phrase lists are the only things that should change frequently.
"""

from __future__ import annotations
from enum import Flag, auto


# ---------------------------------------------------------------------------
# Intent flags (combinable: a message can be ROUTE | URGENT)
# ---------------------------------------------------------------------------

class Intent(Flag):
    NONE         = 0
    ROUTE        = auto()   # wants map/directions
    CHECKLIST    = auto()   # asking about prep tasks
    ONBOARDING   = auto()   # household questions / settings
    URGENT       = auto()   # fire imminent, needs to leave now
    LANGUAGE     = auto()   # wants to change language / app language setting
    TASK_MENTION = auto()   # user describes completing a prep task ("I cleared zone 0")


# ---------------------------------------------------------------------------
# Phrase tables  (lower-case, checked with `in`)
# ---------------------------------------------------------------------------

_ROUTE = frozenset({
    "route", "directions", "navigate", "turn-by-turn",
    "how do i get to", "way out", "evacuation route",
    "drive there", "fastest way", "which road",
    "map tab", "evacuation map", "show the map", "open the map",
})

_URGENT = frozenset({
    "evacuate", "evacuation order", "mandatory evacuation",
    "leave now", "get out", "get out now", "need to leave",
    "leaving now", "must leave", "help me get out",
    "fire nearby", "fire is coming", "flames",
    "smoke outside", "trapped", "not safe here",
})

_CHECKLIST = frozenset({
    "checklist", "what's left", "whats left", "what is left",
    "on my checklist", "my checklist", "tasks left",
    "still need to do", "what do i still", "what else do i need",
    "what else should i", "what am i missing", "review what",
    "preparedness", "preparation progress", "readiness",
    "have i done", "did i complete", "completed everything",
    "anything i forgot", "steps remaining", "remaining steps",
    "key steps",
})

_ONBOARDING = frozenset({
    "onboarding", "household question", "household answer",
    "redo my onboarding", "redo onboarding", "redo the onboarding",
    "update onboarding", "update my answer", "change my answer",
    "change my onboarding", "household info",
    "questionnaire", "survey questions", "submitted by mistake",
    "by mistake",
    # Ownership / home
    "sold my house", "bought a house", "moved to a new house",
    "i rent", "we rent", "i own", "we own",
    # Vehicles
    "no longer have a car", "don't have a car", "no car",
    "got a new car", "got a car", "i have a car now", "we have a car",
    "sold my car", "sold the car",
    # Pets & animals
    "no longer have pets", "no pets", "don't have pets",
    "pet died", "my pet died", "dog died", "cat died",
    "got a new pet", "got a new dog", "got a new cat", "got a new bird",
    "got a new puppy", "got a new kitten", "got a new rabbit",
    "got a dog", "got a cat", "got a bird", "got a puppy", "got a kitten",
    "new dog", "new cat", "new puppy", "new kitten", "new pet",
    "adopted a dog", "adopted a cat", "adopted a pet", "adopted a puppy",
    "we got a dog", "we got a cat", "we got a pet",
    "rescued a dog", "rescued a cat", "rescued a pet",
    "got rid of", "gave away", "rehomed", "found a home for",
    "no longer have livestock", "sold my horse", "sold the horses",
    "got a horse", "got chickens", "got goats", "got livestock",
    # Pool / well / generator
    "got a pool", "no pool", "filled in the pool", "no longer have a pool",
    "got a generator", "no generator", "no longer have a generator",
    "got a well", "no well",
    # Household composition changes
    "moved out", "moved away", "left my house", "no longer live",
    "moved in", "moving in", "moving out",
    "no more seniors", "no longer have seniors",
    "granddad left", "grandmother left", "grandparent",
    "no longer have children", "kid moved out",
    "no more kids", "kids left", "kids are gone", "kids moved out",
    "no kids", "no children", "no longer have kids",
    "kids will be away", "kids are away", "kids going away",
    "away this summer", "away for the summer", "away for summer",
    "will be away", "going away", "staying with", "staying at",
    "cousin", "family member", "relative left", "relative moved",
    "not living with me", "no longer living with me",
    "moved in with", "lives with me now", "living with me now",
    "new roommate", "roommate left", "roommate moved",
    "my mom", "my dad", "my sister", "my brother", "my partner",
    "my husband", "my wife", "my son", "my daughter",
    "my grandmother", "my grandfather", "my grandma", "my grandpa",
    "my aunt", "my uncle", "my in-law",
    "update my household", "change my household",
    "household has changed", "my situation has changed",
    "situation has changed", "things have changed",
    # Disability / mobility
    "has a disability", "uses a wheelchair", "mobility issue",
    "no longer disabled", "recovered", "is better now",
})

_SETTINGS_NAV = frozenset({
    "settings", "gear tab", "log out", "logout", "sign out",
})

# Explicit language-change requests only — NOT "the model replied in Spanish".
# These mean the user wants to update their stored language setting.
_LANGUAGE = frozenset({
    "change language", "switch language", "change my language",
    "switch to spanish", "switch to english", "switch to french",
    "switch to chinese", "switch to korean", "switch to vietnamese",
    "switch to tagalog", "switch to arabic", "switch to hindi",
    "switch to portuguese", "switch to russian", "switch to german",
    "switch to japanese", "hablar español", "speak spanish",
    "speak english", "speak french", "change app language",
    "language setting", "language preference", "preferred language",
    "respond in spanish", "respond in english", "reply in spanish",
    "reply in english", "translate the app",
})

# User reports completing a preparedness task — agent should offer to check it off.
# Broad enough to catch natural phrasing; Claude does the fuzzy item matching.
_TASK_MENTION = frozenset({
    # Zone / debris clearance
    "cleared zone", "cleared my zone", "cleared the zone",
    "zone 0", "zone 1", "zone 2",
    "removed debris", "cleared debris", "cleared brush", "removed brush",
    "cleared my gutters", "cleaned my gutters", "gutters are clear",
    "moved my firewood", "moved the wood pile", "woodpile is moved",
    # Home hardening
    "installed vent", "covered my vents", "replaced my vents", "vents are done",
    "sealed my vents", "ember-resistant vents",
    "cleared my deck", "deck is cleared", "deck is clean",
    "addressed my garage", "garage door is done",
    "posted my address", "address sign is up",
    "renewed my insurance", "checked my insurance", "insurance is updated",
    # Go-bag / supplies
    "packed my go-bag", "filled my go-bag", "go-bag is packed",
    "assembled my go-bag", "stocked my go-bag", "bag is ready",
    "packed my documents", "documents are packed", "documents are ready",
    "packed my medications", "medications are packed", "meds are packed",
    "packed my charger", "phone charger is packed",
    "got cash", "cash is ready",
    # Vehicle
    "fueled my car", "filled my gas", "tank is full", "car is fueled",
    "car bag is packed",
    # Family / contacts
    "updated my routes", "picked my meeting point", "meeting point is set",
    "signed up for alerts", "alerts are set",
    "contacted the school", "school plan is done",
    "registered my senior", "transport is arranged",
    "registered for access", "disability plan is done",
    # Animals
    "got my pet carrier", "carrier is ready", "pet carrier is ready",
    "microchipped my pet", "got my pets microchipped", "pet is microchipped",
    "got a pet photo", "photo is updated",
    "livestock trailer is ready", "trailer is ready",
    "livestock is tagged", "livestock destination is set",
    # Generic completion signals
    "just finished", "just completed", "just did", "just cleared",
    "just installed", "just packed", "just got",
    "already done", "already finished", "already cleared", "already packed",
    "finished the", "completed the", "done with the",
    "checked that off", "want to check that off", "can you check that off",
    "mark it done", "mark as done", "mark as complete",
})


# ---------------------------------------------------------------------------
# Core classifier
# ---------------------------------------------------------------------------

def classify(text: str) -> Intent:
    """Return the combined Intent flags for a user message."""
    t = (text or "").lower()
    intent = Intent.NONE
    if any(p in t for p in _ROUTE):
        intent |= Intent.ROUTE
    if any(p in t for p in _URGENT):
        intent |= Intent.URGENT
    if any(p in t for p in _CHECKLIST):
        intent |= Intent.CHECKLIST
    if any(p in t for p in _ONBOARDING) or any(p in t for p in _SETTINGS_NAV):
        intent |= Intent.ONBOARDING
    if any(p in t for p in _LANGUAGE):
        intent |= Intent.LANGUAGE
    # Only flag TASK_MENTION if not "I want to / I'd like to" phrasing (intent, not completion).
    # "quiero completar", "want to complete", "i'd like to" = future intent, not done.
    _future_intent = ("want to", "would like to", "i'd like", "quiero", "quisiera",
                      "going to", "planning to", "need to", "should i", "how do i",
                      "can you help me", "let me", "i will")
    is_future_intent = any(p in t for p in _future_intent)
    # Also suppress TASK_MENTION when ONBOARDING fired — household changes take priority
    # (e.g. "I got a new dog" = update household, not check off pet carrier).
    is_household_change = Intent.ONBOARDING in intent
    if any(p in t for p in _TASK_MENTION) and not is_future_intent and not is_household_change:
        intent |= Intent.TASK_MENTION
    return intent


# ---------------------------------------------------------------------------
# Tool-list decisions  (single source of truth)
# ---------------------------------------------------------------------------

def should_include_route_tool(intent: Intent) -> bool:
    """
    Expose get_evacuation_route only when the user clearly needs routing.
    URGENT alone qualifies; CHECKLIST, ONBOARDING, LANGUAGE, and TASK_MENTION alone do not.
    """
    if Intent.ROUTE in intent:
        return True
    if Intent.URGENT in intent and not (
        Intent.CHECKLIST in intent
        or Intent.LANGUAGE in intent
        or Intent.TASK_MENTION in intent
    ):
        return True
    return False


def should_include_checklist_tool(intent: Intent) -> bool:
    """
    Expose toggle_checklist_item when user reports completing a task,
    or is discussing their checklist (so Claude can offer to check things off).
    Never expose mid-evacuation routing.
    """
    if Intent.URGENT in intent or Intent.ROUTE in intent:
        return False
    return Intent.TASK_MENTION in intent or Intent.CHECKLIST in intent


def should_include_language_tool(intent: Intent) -> bool:
    """
    Expose update_user_preferences when the user explicitly requests a language change.
    Also expose for general messages so Claude can offer after auto-detecting user language.
    Never expose mid-emergency.
    """
    if Intent.URGENT in intent:
        return False
    return True  # Available on all non-emergency turns so Claude can offer after detecting language


# ---------------------------------------------------------------------------
# Nav action chips sent to the iOS client
# ---------------------------------------------------------------------------

# Order here = order shown in the app.
_ACTION_MAP: list[tuple[Intent, str, str]] = [
    (Intent.ROUTE,      "open_map",        "Open evacuation map"),
    (Intent.CHECKLIST,  "open_checklist",  "Take me to my checklist"),
    (Intent.ONBOARDING, "open_onboarding", "Update onboarding answers"),
    (Intent.LANGUAGE,   "open_language",   "Change language settings"),
    # TASK_MENTION does not get a chip — Claude handles it conversationally.
]

def suggested_actions(intent: Intent) -> list[dict]:
    """Return stable action dicts for the iOS chip bar.
    When LANGUAGE is the primary intent, suppress ONBOARDING chip to avoid confusion.
    """
    suppress_onboarding = Intent.LANGUAGE in intent
    return [
        {"id": aid, "label": label}
        for flag, aid, label in _ACTION_MAP
        if flag in intent and not (suppress_onboarding and aid == "open_onboarding")
    ]
