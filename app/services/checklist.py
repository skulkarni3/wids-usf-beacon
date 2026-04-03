"""
checklist.py — Wildfire preparedness checklist generator
Generates a personalized checklist from onboarding answers.
Based on CAL FIRE / ReadyForWildfire guidance.

Onboarding answers schema (all bool unless noted):
    owns_home       : True = owner, False = renter
    has_car         : has a vehicle
    has_garage      : has an attached garage
    has_driveway    : has a driveway
    has_pool        : has a pool or spa
    has_well        : has a private well (needs manual pump)
    has_generator   : has a backup generator
    has_pets        : cats, dogs, small animals
    has_livestock   : horses, goats, chickens, etc.
    has_children    : minors in household
    has_seniors     : adults 65+ in household
    has_disabled    : persons with mobility/medical needs
"""

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ChecklistItem:
    id: str
    text: str
    detail: Optional[str] = None         # optional one-liner tip
    # Condition flags — item is included when the matching answer is True.
    # None means "always include regardless of answer."
    requires_owner: Optional[bool] = None       # None = both owners & renters
    requires_car: Optional[bool] = None
    requires_garage: Optional[bool] = None
    requires_driveway: Optional[bool] = None
    requires_pool: Optional[bool] = None
    requires_well: Optional[bool] = None
    requires_generator: Optional[bool] = None
    requires_pets: Optional[bool] = None
    requires_livestock: Optional[bool] = None
    requires_children: Optional[bool] = None
    requires_seniors: Optional[bool] = None
    requires_disabled: Optional[bool] = None


# ---------------------------------------------------------------------------
# Item bank  (CAL FIRE / ReadyForWildfire guidance)
# ---------------------------------------------------------------------------

ITEM_BANK: dict[str, list[ChecklistItem]] = {

    # ── DEFENSIBLE SPACE ────────────────────────────────────────────────────
    "defensible_space": [
        ChecklistItem(
            id="ds_zone0",
            text="Clear Zone 0 (0–5 ft from home)",
            detail="Remove all dead plants, leaves, wood piles, and combustible items directly against the structure.",
        ),
        ChecklistItem(
            id="ds_zone1",
            text="Maintain Zone 1 (5–30 ft from home)",
            detail="Keep grass mowed to 4 inches, space plants to limit fire spread, remove dead vegetation.",
        ),
        ChecklistItem(
            id="ds_zone2",
            text="Manage Zone 2 (30–100 ft from home)",
            detail="Reduce fuel load by spacing shrubs and trees, remove ladder fuels.",
        ),
        ChecklistItem(
            id="ds_roof_gutters",
            text="Clean gutters and roof of dead leaves and debris",
            detail="Ember cast is the #1 cause of home ignition — keep gutters metal or covered.",
            requires_owner=True,
        ),
        ChecklistItem(
            id="ds_wood_pile",
            text="Move firewood and lumber at least 30 ft from home",
            requires_owner=True,
        ),
        ChecklistItem(
            id="ds_fence",
            text="Use non-combustible fencing material within 5 ft of home",
            requires_owner=True,
        ),
        ChecklistItem(
            id="ds_driveway_clearance",
            text="Keep driveway clear: 10 ft wide, 15 ft vertical clearance",
            detail="Emergency vehicles and your own evacuation depend on this.",
            requires_driveway=True,
        ),
        ChecklistItem(
            id="ds_pool_pump",
            text="Ensure pool pump is operational and accessible to fire crews",
            requires_pool=True,
        ),
        ChecklistItem(
            id="ds_well_manual",
            text="Install or test a manual pump for your well",
            detail="Electric pumps fail in power outages during fires.",
            requires_well=True,
        ),
        ChecklistItem(
            id="ds_gate_code",
            text="Post gate code / emergency access info at driveway entrance",
            requires_driveway=True,
        ),
        ChecklistItem(
            id="ds_livestock_pasture",
            text="Clear vegetation around livestock pens and pastures",
            requires_livestock=True,
        ),
    ],

    # ── HOME HARDENING ───────────────────────────────────────────────────────
    "home_hardening": [
        ChecklistItem(
            id="hh_vents",
            text="Screen all vents with 1/16″ metal mesh",
            detail="Embers enter through vents — this is one of the highest-impact upgrades.",
            requires_owner=True,
        ),
        ChecklistItem(
            id="hh_windows",
            text="Upgrade to dual-pane or tempered glass windows",
            requires_owner=True,
        ),
        ChecklistItem(
            id="hh_deck",
            text="Remove combustible items from deck/porch before fire season",
        ),
        ChecklistItem(
            id="hh_deck_material",
            text="Consider replacing wood deck with composite or non-combustible material",
            requires_owner=True,
        ),
        ChecklistItem(
            id="hh_roof",
            text="Ensure roof is Class A fire-rated (tile, metal, or asphalt composite)",
            requires_owner=True,
        ),
        ChecklistItem(
            id="hh_garage_door",
            text="Seal gaps around garage door to prevent ember intrusion",
            requires_garage=True,
        ),
        ChecklistItem(
            id="hh_garage_interior",
            text="Store combustibles (gasoline, propane) away from garage interior walls",
            requires_garage=True,
        ),
        ChecklistItem(
            id="hh_generator_placement",
            text="Keep generator at least 10 ft from structure, vent exhaust away from windows",
            requires_generator=True,
        ),
        ChecklistItem(
            id="hh_address",
            text="Post clearly visible address numbers (4 in. minimum) at road entry",
            detail="Critical for emergency responders.",
        ),
        ChecklistItem(
            id="hh_insurance",
            text="Review homeowner's insurance — document belongings with photos/video",
            requires_owner=True,
        ),
    ],

    # ── EVACUATION CHECKLIST ─────────────────────────────────────────────────
    "evacuation": [
        ChecklistItem(
            id="ev_go_bag",
            text="Pack a go-bag with 72 hours of supplies",
            detail="Water (1 gal/person/day), non-perishable food, flashlight, radio, extra batteries.",
        ),
        ChecklistItem(
            id="ev_documents",
            text="Prepare a document kit (copies in a waterproof bag)",
            detail="IDs, insurance, deed/lease, prescriptions, vaccination records.",
        ),
        ChecklistItem(
            id="ev_medications",
            text="Pack a 7-day supply of medications",
        ),
        ChecklistItem(
            id="ev_phone_charger",
            text="Include a portable phone charger (power bank) in go-bag",
        ),
        ChecklistItem(
            id="ev_cash",
            text="Keep $200–300 cash in go-bag",
            detail="ATMs and card readers may be down in evacuation zones.",
        ),
        ChecklistItem(
            id="ev_routes",
            text="Know 2 evacuation routes from your home",
            detail="Primary and an alternate in case roads are blocked.",
        ),
        ChecklistItem(
            id="ev_meeting_point",
            text="Designate a family meeting point outside your neighborhood",
        ),
        ChecklistItem(
            id="ev_alerts",
            text="Sign up for your county's emergency alert system",
        ),
        ChecklistItem(
            id="ev_car_fueled",
            text="Keep car gas tank at least half full during fire season",
            requires_car=True,
        ),
        ChecklistItem(
            id="ev_car_bag",
            text="Keep go-bag and documents accessible in car — not buried in trunk",
            requires_car=True,
        ),
        ChecklistItem(
            id="ev_child_school",
            text="Know your child's school evacuation plan and reunification site",
            requires_children=True,
        ),
        ChecklistItem(
            id="ev_child_contact",
            text="Program an out-of-area emergency contact into your child's phone/backpack",
            requires_children=True,
        ),
        ChecklistItem(
            id="ev_senior_transport",
            text="Pre-arrange evacuation transport for seniors who can't drive",
            requires_seniors=True,
        ),
        ChecklistItem(
            id="ev_senior_register",
            text="Register seniors with your county's Access & Functional Needs (AFN) registry",
            requires_seniors=True,
        ),
        ChecklistItem(
            id="ev_disabled_plan",
            text="Create a personal evacuation plan for household members with disabilities",
            requires_disabled=True,
        ),
        ChecklistItem(
            id="ev_disabled_equipment",
            text="Ensure mobility equipment (wheelchair, walker) is ready to load quickly",
            requires_disabled=True,
        ),
        ChecklistItem(
            id="ev_disabled_register",
            text="Register with county AFN registry for evacuation assistance",
            requires_disabled=True,
        ),
    ],

    # ── ANIMAL EVACUATION ────────────────────────────────────────────────────
    "animal_evacuation": [
        ChecklistItem(
            id="an_pet_carrier",
            text="Have a pet carrier or crate for each animal",
            requires_pets=True,
        ),
        ChecklistItem(
            id="an_pet_bag",
            text="Pack a pet go-bag: food, water, medications, vaccination records, leash",
            requires_pets=True,
        ),
        ChecklistItem(
            id="an_pet_id",
            text="Ensure pets are microchipped and tags are current",
            requires_pets=True,
        ),
        ChecklistItem(
            id="an_pet_photo",
            text="Keep a recent photo of each pet on your phone in case of separation",
            requires_pets=True,
        ),
        ChecklistItem(
            id="an_pet_shelter",
            text="Identify pet-friendly shelters or boarding facilities on your evacuation route",
            requires_pets=True,
        ),
        ChecklistItem(
            id="an_livestock_trailer",
            text="Ensure livestock trailer is accessible and functional",
            requires_livestock=True,
        ),
        ChecklistItem(
            id="an_livestock_id",
            text="Tag or brand all livestock; photograph for records",
            requires_livestock=True,
        ),
        ChecklistItem(
            id="an_livestock_destination",
            text="Pre-arrange an evacuation destination for livestock (fairgrounds, ranch, etc.)",
            requires_livestock=True,
        ),
        ChecklistItem(
            id="an_livestock_early",
            text="Evacuate livestock EARLY — don't wait for mandatory order",
            detail="Large animals take significantly more time and logistics.",
            requires_livestock=True,
        ),
        ChecklistItem(
            id="an_livestock_release",
            text="If unable to evacuate livestock in time, know your county's guidance on release vs. shelter-in-place",
            requires_livestock=True,
        ),
    ],
}


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def _item_applies(item: ChecklistItem, answers: dict) -> bool:
    """
    Returns True if a checklist item should be included given the user's answers.
    A condition field of None means 'no restriction — always include.'
    A condition field of True means 'only include if user answered True for this.'
    """
    checks = [
        ("owns_home",    item.requires_owner),
        ("has_car",      item.requires_car),
        ("has_garage",   item.requires_garage),
        ("has_driveway", item.requires_driveway),
        ("has_pool",     item.requires_pool),
        ("has_well",     item.requires_well),
        ("has_generator",item.requires_generator),
        ("has_pets",     item.requires_pets),
        ("has_livestock",item.requires_livestock),
        ("has_children", item.requires_children),
        ("has_seniors",  item.requires_seniors),
        ("has_disabled", item.requires_disabled),
    ]
    for answer_key, required_value in checks:
        if required_value is None:
            continue  # no restriction
        user_value = answers.get(answer_key, False)
        if user_value != required_value:
            return False
    return True


def generate_checklist(answers: dict) -> dict[str, list[dict]]:
    """
    Given a dict of onboarding answers, return a filtered checklist
    grouped by category.

    Args:
        answers: dict with any subset of the onboarding keys (see module docstring).
                 Missing keys default to False.

    Returns:
        {
            "defensible_space": [{"id": ..., "text": ..., "detail": ...}, ...],
            "home_hardening":   [...],
            "evacuation":       [...],
            "animal_evacuation":[...],
        }
    """
    result = {}
    for category, items in ITEM_BANK.items():
        filtered = [
            {
                "id": item.id,
                "text": item.text,
                **({"detail": item.detail} if item.detail else {}),
            }
            for item in items
            if _item_applies(item, answers)
        ]
        if filtered:  # omit empty categories (e.g. no animals → skip animal_evacuation)
            result[category] = filtered
    return result


def get_checklist_summary(checklist: dict[str, list[dict]]) -> dict:
    """Returns a summary with item counts per category."""
    return {
        "total_items": sum(len(v) for v in checklist.values()),
        "by_category": {k: len(v) for k, v in checklist.items()},
    }