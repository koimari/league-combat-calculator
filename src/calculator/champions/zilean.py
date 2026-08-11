"""Zilean — CP10.10 full-entry-reviewed packet module."""

from ..ability_spec import ControlEvent
from .packet_module import build_packet_module

from ..champions.skill_orders import get_ability_rank
from .slotlib import extract_value

PACKET_SHA256 = "9b4c1e8f16ad0424b82b068c7d55f47892f0345ff70020773135903cc8233776"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Zilean", PACKET_SHA256
)
PACKET_SPEC = SLOTS.packet_spec

_parse_abilities = parse_abilities


def parse_abilities(
    champion_data,
    level,
    total_ability_power,
    ability_ranks=None,
    champion_options=None,
    champion_stats=None,
    target_stats=None,
):
    """Add the sourced stun when the selected cast is the second bomb."""
    result = _parse_abilities(
        champion_data,
        level,
        total_ability_power,
        ability_ranks=ability_ranks,
        champion_options=champion_options,
        champion_stats=champion_stats,
        target_stats=target_stats,
    )
    entry = result.get("Q")
    if entry is not None and bool((champion_options or {}).get("q_second_bomb", False)):
        ability = champion_data["abilities"]["Q"][0]
        duration = extract_value(ability, "Stun Duration", entry["rank"])
        entry["control_events"] = (ControlEvent("stun", duration, time_offset=0.0),)
    return result


OPTIONS.append(
    {
        "key": "q_second_bomb",
        "type": "bool",
        "default": False,
        "label": "Q second bomb attached to the target",
    }
)

# E8d: sourced Chronoshift revive values.  Cached R leveling (data/
# champions.json, Zilean R Chronoshift) Heal row: 600 / 850 / 1100 (+ 200% AP)
# by R rank; prose: "If the target takes fatal damage within the duration,
# they enter resurrection for 3 seconds ... Afterwards, they revive while
# being healed."  Cooldown is 120 / 90 / 60 by rank.  The engine's revive
# state transition consumes ``StartingDefenses.revive_*`` fields; the shared
# defense resolver wires these per champion.
REVIVE_DELAY_SECONDS = 3.0
_REVIVE_HEAL_BASE = (600.0, 850.0, 1100.0)
_REVIVE_HEAL_AP_RATIO = 2.0  # "+ 200% AP"
_REVIVE_COOLDOWN = (120.0, 90.0, 60.0)


def starting_revive_defense(level: int, stats: dict[str, float]) -> dict[str, float]:
    """Return Zilean's sourced Chronoshift revive fields for StartingDefenses."""
    rank = max(1, min(3, get_ability_rank("R", level, "Zilean")))
    amount = _REVIVE_HEAL_BASE[rank - 1] + _REVIVE_HEAL_AP_RATIO * float(
        stats.get("ability_power", 0.0)
    )
    return {
        "revive_health_amount": amount,
        "revive_delay": REVIVE_DELAY_SECONDS,
        "revive_cooldown": _REVIVE_COOLDOWN[rank - 1],
    }


MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q"} else "out_of_scope") for slot in "PQWER"
}
ASSUMPTIONS = list(ASSUMPTIONS) + [
    "Q's stun is emitted only when the explicit second-bomb state is selected; "
    "the second bomb detonates the first bomb immediately and uses the sourced "
    "Stun Duration row",
    "R (Chronoshift) is modeled as the sourced revive state: 600 / 850 / 1100 "
    "(+ 200% AP) restored after a 3s resurrection on a 120 / 90 / 60s cooldown "
    "by rank (cached R Heal row).",
]
REVIEW_STATUS = "reviewed_module"
