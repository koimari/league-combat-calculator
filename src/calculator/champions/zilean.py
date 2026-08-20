"""Zilean — CP10.10 full-entry-reviewed packet module.

Roadmap session 1 (2026-08-20): P, W, and E are reclassified from
out_of_scope to no_damage, and R is reclassified from out_of_scope to
modeled. This closes all 4 of Zilean's out_of_scope slots.

  - P (Time in a Bottle): cached leveling is empty (``[]``) for every
    effect row — the ability grants Zilean and a selected ally
    experience only, no damage/heal/shield/CC number of any kind
    (data/champions.json Zilean P: "leveling": []). Confirmed zero
    numeric combat effect.
  - W (Rewind): cached leveling is empty; the sourced effect is "reduces
    the remaining cooldowns of Time Bomb and Time Warp by 10 seconds
    each" — no damage/heal/shield number, and the fight engine has no
    live cast-scheduling model that varies an ability's cast count from
    a mid-fight cooldown reduction (every champion's rotation is a
    static per-fight count), so W's only effect is inert under the
    current engine. The packet compiler already emits a bare
    total_raw=0.0 entry for this slot (see build_packet_module output),
    confirming the label was simply stale.
  - E (Time Warp): cached leveling carries only a "Movement Speed
    Modifier" row (40/55/70/85/99%, applied as a slow to an enemy target
    or a haste to an allied target) — no damage/heal/shield row, and
    ``ability_spec.ACTION_BLOCKING_CC_KINDS`` deliberately excludes
    "slow" ("Slow effects stay outside this set because they change
    movement, not the ability to act"), so a pure movement-speed change
    creates no action-downtime number either. Confirmed zero numeric
    combat effect in this engine's model (compare Veigar's E, a real
    stun, which is still classified no_damage under the same convention
    because a CC-only effect carries no damage/heal/shield HP number).
  - R (Chronoshift): already fully modeled as the sourced revive state
    via ``starting_revive_defense`` below (600/850/1100 + 200% AP by
    rank, wired through ``StartingDefenses.revive_*``); the label was
    simply stale. The generic ally-support scanner's "Heal" match on R's
    leveling was a live double-count bug (an unconditional heal event at
    cast time, ignoring the resurrection-on-fatal-damage gate) fixed
    this session in support_effects.py's ``_STATE_AUTHORED_HEAL_SLOTS``;
    R's correct behavior is pinned in
    tests/test_e8_support.py::test_zilean_chronoshift_revives_with_sourced_flat_ap_heal
    and tests/test_e1_healing_b5.py::test_zilean_chronoshift_has_no_sourced_fight_trigger.
"""

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
    "P": "no_damage",
    "Q": "modeled",
    "W": "no_damage",
    "E": "no_damage",
    "R": "modeled",
}
ASSUMPTIONS = list(ASSUMPTIONS) + [
    "Q's stun is emitted only when the explicit second-bomb state is selected; "
    "the second bomb detonates the first bomb immediately and uses the sourced "
    "Stun Duration row",
    "R (Chronoshift) is modeled as the sourced revive state: 600 / 850 / 1100 "
    "(+ 200% AP) restored after a 3s resurrection on a 120 / 90 / 60s cooldown "
    "by rank (cached R Heal row).",
    "P (Time in a Bottle), W (Rewind), and E (Time Warp) carry no sourced "
    "damage/heal/shield row (P and W leveling are empty; E's only leveling "
    "row is a Movement Speed Modifier, and slow/haste effects create no "
    "action downtime in this engine) — all three are no_damage, not "
    "out_of_scope.",
]
REVIEW_STATUS = "reviewed_module"
