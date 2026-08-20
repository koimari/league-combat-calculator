"""Cho'Gath — slot map for the archetype engine.

Why each slot is non-generic:
- E (Vorpal Spikes) empowers the next THREE basic attacks per cast —
  the generic parser reads a single per-hit value with no hit count, no
  auto-stream coupling, and no Feast rider. Each hit's "+0.5% per Feast
  stack" of target max health lives only in the modifier's UNITS string
  ("% (+ 0.5% per Feast stack) of target's maximum health"), so a
  modifier override resolves it against the ``feast_stacks`` option.
  The JSON's pre-multiplied "Total Magic Damage" and the two Monster
  entries are never read (champion target, per-hit model).
- R (Feast) couples true damage with the Feast-stack bonus health: each
  stack grants 80/120/160 bonus health (retroactive to R rank), and R's
  own "% bonus health" ratio must see that stack health — so R is a
  BUFF-phase fn that mutates ``ctx.stats`` BEFORE extracting its
  "Champion True Damage" (the pre-buff ``stat_buff`` archetype cannot
  express this). The "Non-Champion True Damage" entry (1200 flat) is
  never read. The buff is echoed in ``stat_buff`` for the fight engine
  (max health display, Overlord's Bloodmail conversion).
- Q (Rupture) and W (Feral Scream) are clean single-attribute reads,
  kept explicit ("Magic damage", lowercase d — and W's classifier pick
  must never drift onto the "Silence Duration" entry).
- P (Carnivore) heals and restores mana on kill — no damage to enemies,
  absent from the map.
"""

import re
from typing import Any

from ..ability_spec import DamagePart
from .engine import BUFF, SlotCtx, build_parser
from .module_helpers import delayed_damage
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    find_named_leveling,
    simple_damage,
    sum_modifiers,
)

# E empowers the next 3 basic attacks per cast. The count has no JSON
# attribute of its own; the JSON's "Total Magic Damage" entry is exactly
# 3x the per-hit values (locked by tests/test_chogath.py).
SPIKES_ATTACKS_PER_CAST = 3

# E's Feast rider lives only in the %maxHP modifier's units text
# ("% (+ 0.5% per Feast stack) of target's maximum health") — the regex
# pulls the per-stack percent out of the unit string, so the number
# stays data-driven.
_FEAST_STACK_RIDER = re.compile(
    r"\+\s*(\d+(?:\.\d+)?)%\s+per\s+Feast\s+stack", re.IGNORECASE
)

# Default Feast stacks: the minion / non-epic-monster stack cap.
_DEFAULT_FEAST_STACKS = 6

# Rupture erupts on its own delay: "Cho'Gath ruptures the target location
# after a 0.627 seconds delay ... dealing magic damage to enemies within
# and knocking them up for 1 second", with the cached note "The delay
# before the rupture does not include the cast time."  ``time_offset`` is
# measured from the cast start, so the cached castTime (0.5) is added to
# the cached delay; both numbers come from the same Q entry.
_Q_CAST_TIME_S = 0.5
_Q_RUPTURE_DELAY_S = 0.627
_Q_RUPTURE_FROM_CAST_START_S = _Q_CAST_TIME_S + _Q_RUPTURE_DELAY_S


def _feast_stacks(ctx: SlotCtx) -> int:
    """Current Feast stacks: the option value, or 0 while R is unranked."""
    if ctx.rank_for("R") < 1:
        return 0
    return int(ctx.options.get("feast_stacks", _DEFAULT_FEAST_STACKS))


def _vorpal_spikes(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: 3 empowered attacks; per hit = base + 30% AP + %maxHP + rider.

    The empowered hits are real basic attacks: with an auto stream they
    ride it (item on-hits apply per hit — these ARE autos); with none
    (one-rotation, or timed at zero uptime) the cast forces its 3
    swings, which the fight engine appends via ``empowers_next_auto``'s
    ``hits`` count.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    leveling = find_named_leveling(ability, "Magic Damage")
    if leveling is None:
        return None

    stacks = _feast_stacks(ctx)

    def _stack_rider(unit: str, value: float) -> float | None:
        match = _FEAST_STACK_RIDER.search(unit)
        if match is None:
            return None
        percent = value + float(match.group(1)) * stacks
        return percent / 100.0 * ctx.target_stat("target_max_health")

    per_hit = sum_modifiers(
        leveling, rank, ctx.stats, ctx.target, modifier_override=_stack_rider
    )
    return {
        "name": ability.get("name", "Vorpal Spikes"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "magic",
        "total_raw": per_hit * SPIKES_ATTACKS_PER_CAST,
        "parts": (DamagePart("magic", per_hit, count=SPIKES_ATTACKS_PER_CAST),),
        "empowers_next_auto": {"hits": SPIKES_ATTACKS_PER_CAST},
    }


def _feast(ctx: SlotCtx) -> dict[str, Any] | None:
    """R (BUFF): stack bonus health first, then true damage off buffed stats.

    Unranked R emits nothing — without a rank there are no Feast stacks
    and no damage. The stack health mutates the shared parse stats
    (BUFF-phase guarantee) so R's own "% bonus health" ratio — and any
    other read of Cho'Gath's health — sees stacks plus item health.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    stack_health = _feast_stacks(ctx) * extract_value(
        ability, "Bonus Health Per Stack", rank
    )
    ctx.stats["bonus_health"] = ctx.stat("bonus_health") + stack_health
    ctx.stats["health"] = ctx.stat("health") + stack_health

    total = extract_named(ability, "Champion True Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Feast"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "true",
        # One bite on the target it eats, no travel or tick phase.
        event_order_certified="single_hit",
    )
    entry["stat_buff"] = {"bonus_health": stack_health}
    return entry


_feast.phase = BUFF


OPTIONS: list[dict[str, Any]] = [
    {
        "key": "feast_stacks",
        "type": "int",
        "default": _DEFAULT_FEAST_STACKS,
        "label": "Feast stacks",
        "min": 0,
        "max": 15,
    },
]

ASSUMPTIONS = [
    "Passive (Carnivore) not modeled — heal/mana sustain on kill only",
    "Feast stacks default to 6 (the minion/non-epic-monster cap); "
    "stacks from champions and epic monsters are uncapped — raise the "
    "option to match",
    "Feast stack bonus health is retroactive to the current R rank "
    "(stacks x 80/120/160); with R unranked, stacks grant nothing",
    "R uses the champion damage (300/475/650); the 1200 non-champion "
    "value is not modeled",
    "E models all 3 empowered attacks landing per cast; the monster "
    "damage variant is not modeled",
    "Q knockup/slow, W silence, E slow/bonus range/attack reset, and "
    "Feast's size/attack-range/cast-range growth are utility — not "
    "modeled",
]

SLOTS = {
    "R": _feast,
    "Q": delayed_damage(
        delay=_Q_RUPTURE_FROM_CAST_START_S,
        attr="Magic damage",
        dmg_type="magic",
    ),
    # One roar in a cone, landing at the cast.
    "W": simple_damage(
        attr="Magic damage", dmg_type="magic", event_order_certified="single_hit"
    ),
    "E": _vorpal_spikes,
}

# Cached kit review.  Q's rupture deals its magic damage while "knocking
# them up for 1 second" on the same delayed eruption, which the slot now
# authors; the 60% slow that follows rides the same airborne.  W's only
# debuff is a silence — real control, but neither an immobilizing effect
# nor a slow — and R "deal[s] them true damage" and nothing else.
#
# E's spikes ride the three basic attacks it empowers: "Enemies struck
# are dealt magic damage and slowed by an amount that decays over 1.5
# seconds" — one event per consumed swing, authored by the engine's
# empowered-swing reattribution.
MODULE_CC = {"Q": "knockup", "W": "silence", "E": "slow", "R": "none"}

parse_abilities = build_parser(SLOTS, "Cho'Gath", cc_kinds=MODULE_CC)


# Authoritative review metadata (issue #161).
SOURCES = [
    {
        "label": "Local League Wiki cache",
        "url": "https://wiki.leagueoflegends.com/en-us/Cho%27Gath",
        "revision_id": 3892600,
        "revision_timestamp": "2025-05-02T11:23:54Z",
    }
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in SLOTS else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
