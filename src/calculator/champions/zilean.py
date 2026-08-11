"""Zilean — CP10.10 full-entry-reviewed packet module."""

from .inputs import champion_stat
from .packet_module import build_packet_module

from ..champions.skill_orders import get_ability_rank

PACKET_SHA256 = "9b4c1e8f16ad0424b82b068c7d55f47892f0345ff70020773135903cc8233776"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Zilean", PACKET_SHA256
)
PACKET_SPEC = SLOTS.packet_spec

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
        champion_stat(stats, "ability_power")
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
    "R (Chronoshift) is modeled as the sourced revive state: 600 / 850 / 1100 "
    "(+ 200% AP) restored after a 3s resurrection on a 120 / 90 / 60s cooldown "
    "by rank (cached R Heal row).",
]
REVIEW_STATUS = "reviewed_module"
