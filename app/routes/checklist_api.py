"""
checklist_api.py
Checklist routes: onboarding questions (until household exists) or personalized
evacuation checklist (after onboarding). Replaces the old static default checklist.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.services.checklist import generate_checklist, get_checklist_summary
from app.services.onboarding import HOUSEHOLD_ANSWER_FIELDS
from app.services.pg_pool import get_pool

router = APIRouter()

# ---------------------------------------------------------------------------
# Same sections as iOS OnboardingView — ids are household column names (snake_case)
# ---------------------------------------------------------------------------

_ONBOARDING_SECTIONS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "Your Home",
        [
            ("owns_home", "I own my home"),
            ("has_car", "I have a vehicle to evacuate with"),
            ("has_garage", "I have a garage"),
            ("has_driveway", "I have a driveway"),
            ("has_pool", "I have a pool or spa"),
            ("has_well", "I have a private well"),
            ("has_generator", "I have a generator"),
        ],
    ),
    (
        "Your Household",
        [
            ("has_children", "Children (under 18)"),
            ("has_seniors", "Seniors (65+)"),
            ("has_disabled", "Someone with mobility needs"),
        ],
    ),
    (
        "Animals",
        [
            ("has_pets", "Pets (dogs, cats, etc.)"),
            ("has_livestock", "Livestock (horses, goats, etc.)"),
        ],
    ),
]


def _serialize_onboarding_categories(household: Optional[dict]) -> list[dict]:
    """Build checklist-shaped categories from onboarding questions; values from household row if any."""
    def val(key: str) -> bool:
        if not household:
            return False
        # Only explicit True shows as checked; NULL and False stay unchecked in the UI.
        return household.get(key) is True

    out: list[dict] = []
    for title, items in _ONBOARDING_SECTIONS:
        out.append(
            {
                "title": title,
                "items": [
                    {"id": iid, "title": label, "checked": val(iid)}
                    for iid, label in items
                ],
            }
        )
    return out


def _category_display_name(slug: str) -> str:
    return slug.replace("_", " ").title()


def _serialize_evacuation_categories(
    raw: dict[str, list[dict]],
    saved_states: dict[str, bool],
) -> list[dict]:
    """Turn generate_checklist() output into tab wire format."""
    categories: list[dict] = []
    for slug, items in raw.items():
        categories.append(
            {
                "title": _category_display_name(slug),
                "items": [
                    {
                        "id": item["id"],
                        "title": item["text"],
                        "checked": saved_states.get(item["id"], False),
                    }
                    for item in items
                ],
            }
        )
    return categories


def _onboarding_tab_response() -> "ChecklistTabResponse":
    return ChecklistTabResponse(
        mode="onboarding",
        categories=[
            ChecklistTabCategory(**c) for c in _serialize_onboarding_categories(None)
        ],
    )


# ---------------------------------------------------------------------------
# Pydantic — wire envelope for checklist tab
# ---------------------------------------------------------------------------

class ChecklistTabItem(BaseModel):
    id: str
    title: str
    checked: bool


class ChecklistTabCategory(BaseModel):
    title: str
    items: list[ChecklistTabItem]


class ChecklistTabResponse(BaseModel):
    mode: Literal["onboarding", "evacuation"]
    categories: list[ChecklistTabCategory]


class OnboardingAnswers(BaseModel):
    """Preview / API body; omit = unknown. For generator, unknown is treated like False."""
    owns_home: Optional[bool] = Field(None)
    has_car: Optional[bool] = None
    has_garage: Optional[bool] = None
    has_driveway: Optional[bool] = None
    has_pool: Optional[bool] = None
    has_well: Optional[bool] = None
    has_generator: Optional[bool] = None
    has_pets: Optional[bool] = None
    has_livestock: Optional[bool] = None
    has_children: Optional[bool] = None
    has_seniors: Optional[bool] = None
    has_disabled: Optional[bool] = None


class ChecklistItemOut(BaseModel):
    id: str
    text: str
    detail: Optional[str] = None
    completed: bool = False


class ChecklistResponse(BaseModel):
    summary: dict
    checklist: dict[str, list[ChecklistItemOut]]


class PatchItemRequest(BaseModel):
    item_id: str
    checked: bool
    user_id: Optional[str] = None


def _answers_dict_for_generator_from_household(household: dict) -> dict[str, bool]:
    """Only explicit DB TRUE enables requires_* gates; NULL/FALSE behave like not-yes."""
    return {k: household.get(k) is True for k in HOUSEHOLD_ANSWER_FIELDS}


def _answers_dict_for_generator_from_preview(body: OnboardingAnswers) -> dict[str, bool]:
    d = body.model_dump(exclude_unset=True)
    return {k: d.get(k) is True for k in HOUSEHOLD_ANSWER_FIELDS}


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _recurrence_type_for_item(item_id: str) -> str:
    # Keep strings aligned with your Postgres ENUM `recurrence_type`.
    return {
        # Defensible space
        "ds_zone0": "weekly",
        "ds_zone1": "monthly",
        "ds_zone2": "quarterly",
        "ds_roof_gutters": "monthly",
        "ds_wood_pile": "annual",
        "ds_fence": "none",
        "ds_driveway_clearance": "quarterly",
        "ds_pool_pump": "monthly",
        "ds_well_manual": "annual",
        "ds_gate_code": "annual",
        "ds_livestock_pasture": "monthly",
        # Home hardening
        "hh_vents": "none",
        "hh_windows": "none",
        "hh_deck": "quarterly",
        "hh_deck_material": "none",
        "hh_roof": "none",
        "hh_garage_door": "quarterly",
        "hh_garage_interior": "quarterly",
        "hh_generator_placement": "quarterly",
        "hh_address": "none",
        "hh_insurance": "annual",
        # Evacuation
        "ev_go_bag": "quarterly",
        "ev_documents": "annual",
        "ev_medications": "monthly",
        "ev_phone_charger": "quarterly",
        "ev_cash": "quarterly",
        "ev_routes": "annual",
        "ev_meeting_point": "annual",
        "ev_alerts": "annual",
        "ev_car_fueled": "weekly",
        "ev_car_bag": "quarterly",
        "ev_child_school": "annual",
        "ev_child_contact": "annual",
        "ev_senior_transport": "annual",
        "ev_senior_register": "annual",
        "ev_disabled_plan": "annual",
        "ev_disabled_equipment": "monthly",
        "ev_disabled_register": "annual",
        # Animals
        "an_pet_carrier": "none",
        "an_pet_bag": "quarterly",
        "an_pet_id": "annual",
        "an_pet_photo": "quarterly",
        "an_pet_shelter": "annual",
        "an_livestock_trailer": "quarterly",
        "an_livestock_id": "annual",
        "an_livestock_destination": "annual",
        "an_livestock_early": "none",
        "an_livestock_release": "annual",
    }.get(item_id, "none")


def _compute_next_due(recurrence_type: str, completed_at: datetime) -> Optional[datetime]:
    # Keep this deterministic and simple; you can refine to calendar-aware later.
    rt = (recurrence_type or "none").lower()
    if rt == "none":
        return None
    if completed_at.tzinfo is None:
        completed_at = completed_at.replace(tzinfo=timezone.utc)
    if rt == "weekly":
        return completed_at + timedelta(days=7)
    if rt == "monthly":
        return completed_at + timedelta(days=30)
    if rt == "quarterly":
        return completed_at + timedelta(days=90)
    if rt == "annual":
        return completed_at + timedelta(days=365)
    # Unknown enum value -> don't schedule
    return None


async def _load_checked_states(user_id: str) -> dict[str, bool]:
    """Returns {item_id: completed} for all saved rows for this user (auto-unchecks overdue recurring items)."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT item_id, completed, recurrence_type, next_due_date
        FROM checklist_progress
        WHERE user_id = $1
        """,
        user_id,
    )

    now = datetime.now(timezone.utc)
    states: dict[str, bool] = {}
    overdue_item_ids: list[str] = []
    for row in rows:
        item_id = row["item_id"]
        completed = bool(row["completed"])
        rt = (row.get("recurrence_type") or "none")
        due = row.get("next_due_date")

        if completed and rt != "none" and due is not None:
            if due.tzinfo is None:
                due = due.replace(tzinfo=timezone.utc)
            if now >= due:
                # Auto-uncheck when it becomes due again.
                completed = False
                overdue_item_ids.append(item_id)

        states[item_id] = completed

    if overdue_item_ids:
        # Best-effort: persist the auto-uncheck so other clients see consistent state.
        try:
            await pool.execute(
                """
                UPDATE checklist_progress
                SET completed = FALSE
                WHERE user_id = $1
                  AND item_id = ANY($2::text[])
                """,
                user_id,
                overdue_item_ids,
            )
        except Exception as e:
            print(f"[checklist] auto-uncheck persist failed: {e}")

    return states


async def _upsert_checked_state(user_id: str, item_id: str, checked: bool) -> None:
    """Insert or update a single checklist item's completion state."""
    pool = await get_pool()
    rt = _recurrence_type_for_item(item_id)
    now = datetime.now(timezone.utc)
    next_due = _compute_next_due(rt, now) if checked else None
    await pool.execute(
        """
        INSERT INTO checklist_progress (
            user_id, item_id,
            completed, completed_at,
            recurrence_type, next_due_date
        )
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (user_id, item_id)
        DO UPDATE SET
            recurrence_type = checklist_progress.recurrence_type,
            completed       = EXCLUDED.completed,
            completed_at    = CASE
                WHEN EXCLUDED.completed THEN EXCLUDED.completed_at
                ELSE checklist_progress.completed_at
            END,
            next_due_date   = CASE
                WHEN EXCLUDED.completed THEN EXCLUDED.next_due_date
                ELSE checklist_progress.next_due_date
            END
        """,
        user_id,
        item_id,
        checked,
        now if checked else None,
        rt,
        next_due,
    )


async def _load_household(user_id: str) -> Optional[dict]:
    """Fetch the household onboarding row for a user. Returns None if not found."""
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM household WHERE user_id = $1",
        user_id,
    )
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/checklist", response_model=ChecklistTabResponse)
async def get_checklist(user_id: Optional[str] = None):
    """
    Checklist tab payload:
    - No user_id → onboarding questions (all unchecked); does not error.
    - user_id, no household row → onboarding questions (all unchecked).
    - user_id, household exists → personalized evacuation checklist + saved progress.
    """
    if not user_id:
        return _onboarding_tab_response()

    try:
        household = await _load_household(user_id)
    except Exception as e:
        print(f"[checklist] DB error, onboarding fallback: {e}")
        return _onboarding_tab_response()

    if household is None:
        return _onboarding_tab_response()

    raw = generate_checklist(_answers_dict_for_generator_from_household(household))
    saved = await _load_checked_states(user_id)
    cats = _serialize_evacuation_categories(raw, saved)
    return ChecklistTabResponse(
        mode="evacuation",
        categories=[ChecklistTabCategory(**c) for c in cats],
    )


@router.patch("/checklist/item")
async def update_checklist_item(body: PatchItemRequest):
    """
    Persists evacuation item completion only when user_id is set (ignored for onboarding toggles).
    """
    if body.user_id:
        try:
            await _upsert_checked_state(body.user_id, body.item_id, body.checked)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to persist checklist state: {e}",
            )

    return {"status": "ok", "item_id": body.item_id, "checked": body.checked}


@router.post(
    "/generate",
    response_model=ChecklistResponse,
    summary="Generate a personalized checklist from onboarding answers (preview)",
)
async def generate_checklist_from_answers(answers: OnboardingAnswers):
    raw = generate_checklist(_answers_dict_for_generator_from_preview(answers))
    summary = get_checklist_summary(raw)
    checklist_with_state = {
        category: [ChecklistItemOut(**item) for item in items]
        for category, items in raw.items()
    }
    return ChecklistResponse(summary=summary, checklist=checklist_with_state)


@router.get("/me", response_model=ChecklistResponse)
async def get_my_checklist(user_id: str):
    """
    Legacy JSON shape for clients that expect summary + checklist dict.
    Prefer GET /checklist for the tab.
    """
    household = await _load_household(user_id)
    if household is None:
        return ChecklistResponse(
            summary={"source": "onboarding_required", "total_items": 0},
            checklist={},
        )

    raw = generate_checklist(_answers_dict_for_generator_from_household(household))
    summary = get_checklist_summary(raw)
    saved_states = await _load_checked_states(user_id)
    checklist_with_state = {
        category: [
            ChecklistItemOut(
                **item,
                completed=saved_states.get(item["id"], False),
            )
            for item in items
        ]
        for category, items in raw.items()
    }
    return ChecklistResponse(summary=summary, checklist=checklist_with_state)
