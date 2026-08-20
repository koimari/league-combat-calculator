"""Leona — full-entry reviewed CP10.3 module.

E8c addition over the reviewed module:
- W (Eclipse) is defense, not a shield: cached leveling rows carry a
  per-instance "Flat Damage Reduction" (8/12/16/20/24, prose-capped at
  50% of the damage instance) plus bonus armor and bonus magic
  resistance (20/27.5/35/42.5/50 + 20% of bonus, 3s, extended 3s when
  the detonation hits).  The shared ledger's shield events price
  absorbing barriers, and its stat-buff events carry no armor/MR axis,
  so Eclipse is documented as mitigation state with the sourced
  constants pinned here — no flat shield amount is invented.  The W
  detonation damage keeps its reviewed packet read.

Option key consumed by the shared parser: "p_marks".
"""

from typing import Any

from .engine import ONHIT, SlotCtx, build_parser
from .module_helpers import REVIEWED_MODULE_ASSUMPTIONS, delayed_damage
from .slotlib import (
    ability_on_hit_entry,
    extract_cooldown,
    extract_named,
    proc_damage,
    simple_damage,
)
from .source_receipts import load_champion_sources


def _sunlight(ctx: SlotCtx) -> dict[str, Any] | None:
    result = proc_damage(
        lambda current, ability: extract_named(
            ability,
            "Per-Level Scaling",
            current.level,
            current.stats,
            current.target,
        ),
        "magic",
        count_option="p_marks",
        default_count=1,
        name="Sunlight (ally detonation)",
        phase_order_events=True,
    )(ctx)
    if result:
        result["detail"] = (
            "One sourced ally-triggered Sunlight detonation per marked target; "
            "marking is ordered state."
        )
    return result


def _shield_of_daybreak(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    value = extract_named(ability, "Bonus Magic Damage", rank, ctx.stats, ctx.target)
    result = ability_on_hit_entry(
        ability.get("name", "Shield of Daybreak"),
        rank,
        "magic",
        {
            "name": "Shield of Daybreak",
            "damage_per_hit": value,
            "damage_type": "magic",
        },
        extract_cooldown(ability, rank),
    )
    result["empowers_next_auto"] = True
    result["detail"] = "One empowered basic attack; the stun is control state."
    return result


_sunlight.phase = ONHIT


# Eclipse's damage is its detonation, not its cast: "Leona raises her
# guard for 3 seconds ... Her shield detonates after the duration, dealing
# magic damage to nearby enemies" (data/champions.json Leona W).
_W_DETONATION_SECONDS = 3.0
# Solar Flare "strikes upon the target location after 0.625 seconds"; the
# cached entry attaches no cast-time qualifier to that number, so it is
# read from the cast start as written.
_R_IMPACT_SECONDS = 0.625

SLOTS = {
    "P": _sunlight,
    "Q": _shield_of_daybreak,
    "W": delayed_damage(
        delay=_W_DETONATION_SECONDS, attr="Magic Damage", dmg_type="magic"
    ),
    # The sword's flight has no sourced duration in the cached entry, so
    # the cast boundary is the only placement its one hit has.
    "E": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
    "R": delayed_damage(delay=_R_IMPACT_SECONDS, attr="Magic Damage", dmg_type="magic"),
}
OPTIONS = [
    {
        "key": "p_marks",
        "type": "int",
        "default": 1,
        "min": 0,
        "max": 6,
        "label": "Sunlight ally detonations",
    }
]
ASSUMPTIONS = list(REVIEWED_MODULE_ASSUMPTIONS)
SOURCES = load_champion_sources("Leona")
# Reviewed crowd control, read from the cached kit.  Eclipse's detonation
# only "deal[s] magic damage to nearby enemies" (the extension it buys is
# Leona's own guard).  Zenith Blade "deals magic damage to enemies hit"
# and then "roots them for 0.5 seconds" — the last champion struck is the
# damaged target in a duel.  Solar Flare's impact leaves every enemy hit
# "slowed by 80% for 1.75 seconds"; the same-duration stun is conditional
# on the epicenter, which this model does not place, so the unconditional
# slow is the reviewed kind.
#
# Shield of Daybreak "empower[s] his next basic attack within 6 seconds
# to have an uncancellable windup, gain 50 bonus range, deal bonus magic
# damage and stun the target for 1 second" — the stun rides the swing the
# cast forces, which is the event the engine reattributes to this row.
MODULE_CC = {"Q": "stun", "W": "none", "E": "root", "R": "slow"}

parse_abilities = build_parser(SLOTS, "Leona", cc_kinds=MODULE_CC)

# HARDCODED: verify on patch updates — Eclipse's defense rows are cached
# leveling data (data/champions.json, Leona W): Flat Damage Reduction
# 8/12/16/20/24 (prose: "up to 50% of the damage instance"), Bonus
# Armor and Bonus Magic Resistance 20/27.5/35/42.5/50 + 20% of bonus,
# duration 3s extended 3s on hit (prose).  The ledger's shield events
# cannot price per-instance pre-mitigation reduction or resistance
# buffs, so these stay documented constants.
_ECLIPSE_FLAT_REDUCTION_RANKED = (8.0, 12.0, 16.0, 20.0, 24.0)
_ECLIPSE_REDUCTION_CAP = 0.50  # capped at 50% of the damage instance
_ECLIPSE_BONUS_RESIST_RANKED = (20.0, 27.5, 35.0, 42.5, 50.0)
_ECLIPSE_BONUS_RESIST_RATIO = 0.20  # +20% of bonus resist
_ECLIPSE_DURATION_SECONDS = 3.0
_ECLIPSE_EXTENSION_SECONDS = 3.0

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "W (Eclipse) is documented as mitigation state, not a shield: "
    "per-instance flat damage reduction 8/12/16/20/24 (capped at 50% of "
    "the instance) plus bonus armor/MR 20/27.5/35/42.5/50 + 20% of "
    "bonus for 3s (extended 3s on detonation hit) — cached leveling "
    "constants; the ledger's shield events cannot express pre-mitigation "
    "reduction or resistance buffs, so no flat shield amount is invented",
]

MODULE_COVERAGE = {slot: "modeled" for slot in "PQWER"}
REVIEW_STATUS = "reviewed_module"
