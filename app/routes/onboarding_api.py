"""
onboarding_api.py — FastAPI routes for household onboarding.

Endpoints:
    GET  /onboarding/status      — check if user has completed onboarding
                                   iOS calls this on launch to decide whether to show the flow
    POST /onboarding/household   — save (or update) onboarding answers → writes to household table
    GET  /onboarding/household   — load existing answers (for edit/re-onboarding screen)

user_id is a query param for now. Replace with Depends(get_current_user) once JWT auth is wired up.

Household booleans: null = not asked, false = no, true = yes.
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from typing import Optional

from app.services.onboarding import (
    save_household,
    load_household,
    household_exists,
    upsert_household_answers,
)

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class HouseholdAnswers(BaseModel):
    """
    Mirrors OnboardingAnswers in checklist_api.py — keep in sync.
    Optional[bool]: omit field = no change on POST /household; explicit null clears to unanswered.
    """
    owns_home: Optional[bool] = Field(None, description="True = owner, False = renter, null = not asked")
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


class OnboardingStatusResponse(BaseModel):
    user_id: str
    completed: bool


class HouseholdResponse(BaseModel):
    user_id: str
    answers: HouseholdAnswers


class OnboardingAnswerRequest(BaseModel):
    question_id: str = Field(..., description="Household field id, e.g. has_car, has_pets")
    value: bool


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get(
    "/status",
    response_model=OnboardingStatusResponse,
    summary="Check whether a user has completed onboarding",
)
async def get_onboarding_status(user_id: str):
    """
    iOS calls this on every cold launch.
    If completed=false, show OnboardingView before the main tab bar.
    If completed=true, go straight to the app.
    """
    completed = await household_exists(user_id)
    return OnboardingStatusResponse(user_id=user_id, completed=completed)


@router.post(
    "/household",
    status_code=status.HTTP_201_CREATED,
    summary="Save onboarding answers — writes to household table",
)
async def submit_household(user_id: str, answers: HouseholdAnswers):
    """
    Called when the user taps 'Done' at the end of the onboarding flow.
    Only fields provided in the JSON body are written; omitted fields are left unchanged.
    """
    try:
        payload = answers.model_dump(exclude_unset=True)
        await save_household(user_id, payload)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save household: {type(e).__name__}: {e!r}",
        )
    return {"status": "ok", "user_id": user_id}


@router.post(
    "/answer",
    status_code=status.HTTP_201_CREATED,
    summary="Upsert a single onboarding answer (per-question)",
)
async def submit_onboarding_answer(user_id: str, body: OnboardingAnswerRequest):
    """
    Tool-friendly single-question endpoint. Writes to the same `household` row.
    """
    try:
        await upsert_household_answers(user_id, {body.question_id: body.value})
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save onboarding answer: {type(e).__name__}: {e!r}",
        )
    return {"status": "ok", "user_id": user_id, "question_id": body.question_id, "value": body.value}


@router.get(
    "/household",
    response_model=HouseholdResponse,
    summary="Load existing onboarding answers for a user",
)
async def get_household(user_id: str):
    """
    Used for edit/re-onboarding. Returns nulls for unanswered questions.
    Returns 404 if the user has no household row yet.
    """
    row = await load_household(user_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No household found for this user — onboarding not yet completed.",
        )
    return HouseholdResponse(
        user_id=user_id,
        answers=HouseholdAnswers(
            owns_home=row.get("owns_home"),
            has_car=row.get("has_car"),
            has_garage=row.get("has_garage"),
            has_driveway=row.get("has_driveway"),
            has_pool=row.get("has_pool"),
            has_well=row.get("has_well"),
            has_generator=row.get("has_generator"),
            has_pets=row.get("has_pets"),
            has_livestock=row.get("has_livestock"),
            has_children=row.get("has_children"),
            has_seniors=row.get("has_seniors"),
            has_disabled=row.get("has_disabled"),
        ),
    )