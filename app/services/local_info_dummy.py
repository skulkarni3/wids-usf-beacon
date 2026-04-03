"""
Dummy local info provider (news + NGO resources).

Not wired into the live chatbot agent yet. We'll later replace this with:
- trusted news sources (Watch Duty, CAL FIRE, county OES, NWS, InciWeb where applicable)
- optional caching
- location-aware queries
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class LocalInfoBundle:
    location_display: Optional[str]
    headlines: list[str]
    hotlines: list[str]
    ngo_resources: list[str]


async def get_local_info(*, location_display: Optional[str] = None) -> LocalInfoBundle:
    """
    Pretend tool: returns static placeholders for now.
    """
    return LocalInfoBundle(
        location_display=location_display,
        headlines=[
            "Placeholder: Check official county OES updates for evacuation orders.",
            "Placeholder: Check CAL FIRE incident updates for containment and road impacts.",
        ],
        hotlines=[
            "Emergency: 911",
            "Placeholder: County non-emergency line (add per-county later)",
        ],
        ngo_resources=[
            "Placeholder: Red Cross shelter info (add region-specific contact later)",
            "Placeholder: Local animal shelter / humane society (add region-specific contact later)",
        ],
    )

