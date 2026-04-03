"""
onboarding.py — Onboarding service layer.

Reads and writes household onboarding answers to Postgres.
Called by onboarding_api.py routes.

Nullable boolean semantics:
    NULL  = not yet asked
    FALSE = explicit "no"
    TRUE  = explicit "yes"
"""

from __future__ import annotations

from typing import Optional

from app.services.pg_pool import get_pool

# Single source of truth for the household column list.
HOUSEHOLD_ANSWER_FIELDS: tuple[str, ...] = (
    "owns_home",
    "has_car",
    "has_garage",
    "has_driveway",
    "has_pool",
    "has_well",
    "has_generator",
    "has_pets",
    "has_livestock",
    "has_children",
    "has_seniors",
    "has_disabled",
)

_VALID_FIELDS = frozenset(HOUSEHOLD_ANSWER_FIELDS)


def _coerce(v: object) -> Optional[bool]:
    """Normalize any incoming value to bool or None."""
    if v is None:
        return None
    return bool(v)


def _clean(answers: dict) -> dict[str, Optional[bool]]:
    """Strip unknown keys and coerce values. Returns only keys present in answers."""
    return {k: _coerce(v) for k, v in answers.items() if k in _VALID_FIELDS}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def save_household(user_id: str, answers: dict) -> None:
    """
    Upsert a household row.

    Pass model_dump(exclude_unset=True) from the route so omitted fields
    are not touched on UPDATE (they stay NULL or their previous value).
    On INSERT, omitted fields land as NULL (not yet asked).
    """
    patch = _clean(answers)
    if not patch:
        return

    pool = await get_pool()

    # Build SET clause dynamically from only the keys that were supplied.
    # $1 = user_id, $2...$N = column values in patch order.
    cols = list(patch.keys())
    vals = [patch[c] for c in cols]
    set_clause = ", ".join(f"{c} = ${i+2}" for i, c in enumerate(cols))

    # Try UPDATE first; fall back to INSERT if no row exists.
    result = await pool.execute(
        f"UPDATE household SET {set_clause}, updated_at = NOW() WHERE user_id = $1",
        user_id, *vals,
    )

    if result == "UPDATE 0":
        # Row doesn't exist yet — insert with NULLs for all unset fields.
        all_vals = [patch.get(c) for c in HOUSEHOLD_ANSWER_FIELDS]
        col_list = ", ".join(["user_id", *HOUSEHOLD_ANSWER_FIELDS])
        placeholders = ", ".join(f"${i+1}" for i in range(len(HOUSEHOLD_ANSWER_FIELDS) + 1))
        await pool.execute(
            f"INSERT INTO household ({col_list}, updated_at) VALUES ({placeholders}, NOW())",
            user_id, *all_vals,
        )


async def upsert_household_answers(user_id: str, updates: dict) -> None:
    """Convenience wrapper — same semantics as save_household."""
    await save_household(user_id, updates)


async def load_household(user_id: str) -> Optional[dict]:
    """Return the household row as a dict, or None if the user has no row yet."""
    pool = await get_pool()
    row = await pool.fetchrow("SELECT * FROM household WHERE user_id = $1", user_id)
    return dict(row) if row else None


async def household_exists(user_id: str) -> bool:
    """True if any household row exists for this user."""
    pool = await get_pool()
    row = await pool.fetchrow("SELECT 1 FROM household WHERE user_id = $1", user_id)
    return row is not None