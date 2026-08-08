"""Source-pinned Wiki parser for synthetic and development fixtures.

This utility is never a runtime registration target. It deliberately does not
invent state-machine behavior; production dispatch requires a validated named
champion module and fails closed for unknown names.
"""

from typing import Any

from .engine import build_parser
from .slotlib import on_hit_auto, simple_damage

# Every slot is present so synthetic fixtures can exercise the shared
# classifier/scaling/entry validation without claiming production exactness.
GENERIC_SLOTS = {
    "Q": simple_damage(),
    "W": simple_damage(),
    "E": simple_damage(),
    "R": simple_damage(),
    "P": on_hit_auto(),
}

OPTIONS: list[dict[str, Any]] = []
ASSUMPTIONS = [
    "Uses the champion's local Wiki damage packets and shared scaling resolver.",
    "Passive, attack-triggered, multi-stage, alternate-form, and stateful effects remain review-pending unless a custom module models them.",
    "This synthetic parser is development coverage, not runtime registration or exact event-order certification.",
]
SOURCES = [
    {
        "label": "Local League Wiki cache",
        "url": "https://wiki.leagueoflegends.com/en-us/League_of_Legends_Wiki",
    }
]


def parse_abilities(
    champion_data: dict[str, Any],
    level: int,
    total_ability_power: float,
    ability_ranks: dict[str, int] | None = None,
    champion_options: dict[str, Any] | None = None,
    champion_stats: dict[str, float] | None = None,
    target_stats: dict[str, float] | None = None,
) -> dict[str, dict[str, Any]]:
    """Parse one explicit synthetic Wiki-backed fixture."""
    parser = build_parser(GENERIC_SLOTS, champion_data.get("name", ""))
    result = parser(
        champion_data,
        level,
        total_ability_power,
        ability_ranks=ability_ranks,
        champion_options=champion_options,
        champion_stats=champion_stats,
        target_stats=target_stats,
    )
    # The shared on-hit factory intentionally emits a compact payload because
    # reviewed callers often consume it as a passive-only record. Normalize
    # synthetic fixtures into the full engine result shape for test tooling.
    for entry in result.values():
        if "parts" in entry:
            continue
        entry["parts"] = ()
        entry.setdefault("total_raw", 0.0)
        on_hit = entry.get("on_hit") or {}
        entry.setdefault("damage_type", on_hit.get("damage_type", "physical"))
    return result
