"""Source-pinned Wiki engine module for champions without a custom model.

This is an explicit registration target, not an implicit parser fallback.  It
keeps every cached champion on the same validated slot engine while the
champion-specific module is being reviewed.  The generic module deliberately
does not invent state-machine behavior: it extracts the best Wiki damage
packet available for each slot and leaves the exact certification boundary to
the reviewed module registry.
"""

from typing import Any

from .engine import build_parser
from .slotlib import on_hit_auto, simple_damage

# Every slot is present so the backend can register and parse a complete
# P/Q/W/E/R kit for every champion in the local Wiki snapshot.  The factories
# still apply the shared classifier/scaling/entry validation used by reviewed
# modules; no heuristic archetype is used to label a champion as exact.
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
    "This registration is runnable backend coverage, not exact event-order certification.",
]
SOURCES = [
    {
        "label": "Local League Wiki cache",
        "url": "https://wiki.leagueoflegends.com/en-us/League_of_Legends_Wiki",
    }
]
REGISTRATION_KIND = "wiki_generic_module"


def parse_abilities(
    champion_data: dict[str, Any],
    level: int,
    total_ability_power: float,
    ability_ranks: dict[str, int] | None = None,
    champion_options: dict[str, Any] | None = None,
    champion_stats: dict[str, float] | None = None,
    target_stats: dict[str, float] | None = None,
) -> dict[str, dict[str, Any]]:
    """Parse one explicitly registered Wiki-backed champion kit."""
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
    # reviewed callers often consume it as a passive-only record.  The fight
    # engine also walks every Q/W/E/R row and requires ``parts`` on that row,
    # so normalize generic registrations into the full engine contract here.
    for entry in result.values():
        if "parts" in entry:
            continue
        entry["parts"] = ()
        entry.setdefault("total_raw", 0.0)
        on_hit = entry.get("on_hit") or {}
        entry.setdefault("damage_type", on_hit.get("damage_type", "physical"))
    return result
