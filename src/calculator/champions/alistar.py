"""Alistar — slot map for the archetype engine.

Why each slot is non-generic:
- E (Trample) is a custom fn: the cast total is the "Total Magic
  Damage" attribute (all 10 ticks over 5 s — the classifier would pick
  the per-tick "Magic Damage" first), plus the empowered-auto bonus
  that Trample grants once per cast, which scales with champion LEVEL
  (not rank) and is baked into the cast total rather than emitted as an
  on-hit. This is a total-attribute read plus an add-once on-hit addend,
  so the mechanic stays champion-local.
- Q (Pulverize) / W (Headbutt) are fully generic single-hit magic
  damage — auto-mode ``simple_damage``, exactly the generic path the
  legacy module reached by calling the generic parser and patching its
  output.
- R (Unbreakable Will) is damage reduction only and P (Triumphant
  Roar) is healing only — neither is modeled, both absent from the
  slot map.

All numeric values are read from the champion JSON data; nothing is
hardcoded.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .slotlib import damage_entry, extract_cooldown, extract_named, simple_damage


def _extract_e_on_hit_damage(
    ability: dict[str, Any],
    level: int,
) -> float:
    """Extract E's empowered-auto bonus magic damage at a champion level.

    The empowered auto scales with champion level (not ability rank);
    the JSON stores it under "Bonus Magic Damage" as per-level values.
    Per-level arrays may have fewer entries than 18, in which case the
    level is linearly interpolated across the available values.
    (Test seam: tests/test_alistar.py validates the JSON values here.)
    """
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute", "") != "Bonus Magic Damage":
                continue

            modifiers = leveling.get("modifiers", [])
            if not modifiers:
                continue

            values = modifiers[0].get("values", [])
            if not values:
                continue

            if len(values) >= level:
                return float(values[level - 1])

            # The wiki defines per-level arrays over levels 1-18; clamp
            # top-quest levels 19-20 to the array's range so a short array
            # falls back to its level-18 value instead of extrapolating.
            scaling_level = min(level, 18)
            if len(values) >= scaling_level:
                return float(values[scaling_level - 1])

            # Interpolate: map level (1-18) into the values array.
            num_values = len(values)
            if num_values == 1:
                return float(values[0])

            fraction = (scaling_level - 1) / 17.0  # 0.0 at level 1, 1.0 at 18
            index_float = fraction * (num_values - 1)
            low_idx = int(index_float)
            high_idx = min(low_idx + 1, num_values - 1)
            weight = index_float - low_idx
            return (
                float(values[low_idx]) * (1 - weight) + float(values[high_idx]) * weight
            )

    return 0.0


# E (Trample) ticks 10 times over its 5-second duration — the JSON's
# "Total Magic Damage" row is exactly 10x the "Magic Damage Per Tick"
# row at every rank (80/8 .. 200/20), so the tick count is sourced
# rather than invented.  Each tick is one second of the channel's
# 0.5s cadence (5s / 10 ticks).
_E_TICKS = 10
_E_DURATION = 5.0
_E_TICK_INTERVAL = _E_DURATION / _E_TICKS  # "every 0.5 seconds"


def _trample(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: 10 sourced ticks of the per-tick row + level-scaled empowered auto.

    The per-tick value x 10 equals the JSON's "Total Magic Damage" at
    every rank, so the fight prices the full cast total across the
    tick timeline instead of one lump.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    per_tick = extract_named(
        ability, "Magic Damage Per Tick", rank, ctx.stats, ctx.target
    )
    # The empowered auto procs once per E cast (after the 5s trample),
    # so it joins the cast total instead of becoming a per-auto on_hit
    # entry.
    empowered = _extract_e_on_hit_damage(ability, ctx.level)

    name = ability.get("name", "Trample")
    entry = damage_entry(
        name,
        rank,
        extract_cooldown(ability, rank),
        per_tick * _E_TICKS + empowered,
        "magic",
    )
    # E's control belongs to the empowered auto, not to the trample: the
    # ticks only "deal magic damage to nearby enemies", while the 5-stack
    # basic attack that ends Trample "stun[s] the target for 1 second".
    # One cast, two answers, so they are authored per part instead of in
    # MODULE_CC.
    entry["parts"] = (
        DamagePart(
            "magic",
            per_tick,
            count=_E_TICKS,
            time_offset=_E_TICK_INTERVAL,
            hit_interval=_E_TICK_INTERVAL,
            cc_kind="none",
        ),
        DamagePart("magic", empowered, time_offset=_E_DURATION, cc_kind="stun"),
    )
    # Item burns (Liandry's, Blackfire Torch) stay refreshed through the
    # whole 5-second trample (the Cassiopeia rule).
    entry["dot_duration"] = _E_DURATION
    entry["detail"] = (
        f"{_E_TICKS} sourced trample ticks; empowered auto lands after the channel."
    )
    return entry


OPTIONS: list[dict[str, Any]] = []

ASSUMPTIONS = [
    "E Trample deals full duration damage (10 ticks over 5 seconds)",
    "E empowered auto always procs once per cast (5 stacks reached)",
    "Passive (Triumphant Roar) healing is ignored",
    "R (Unbreakable Will) damage reduction is ignored",
]

SLOTS = {
    # Both are one instantaneous hit with no sourced sub-cast phase — the
    # smash lands beneath Alistar and the headbutt on arrival — so each
    # certifies the cast boundary its reviewed control rides on.
    "Q": simple_damage(event_order_certified="single_hit"),
    "W": simple_damage(event_order_certified="single_hit"),
    "E": _trample,
}

# Cached kit review.  Q stuns "and knock[s] them up simultaneously for 1
# second" and W "knocks them back 700 units ... while also stunning them
# for 0.75 seconds": each cast applies two immobilize kinds at once, which
# is what the un-narrowed "immobilize" kind states.  E is absent because
# its two parts disagree (see _trample); R and P deal no damage.
MODULE_CC = {"Q": "immobilize", "W": "immobilize"}

parse_abilities = build_parser(SLOTS, "Alistar", cc_kinds=MODULE_CC)


SOURCES = [
    {
        "label": "Local League Wiki cache",
        "url": "https://wiki.leagueoflegends.com/en-us/Alistar",
        "revision_id": 3892578,
        "revision_timestamp": "2025-05-02T10:24:06Z",
    }
]

from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Alistar")
