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
- P (Triumphant Roar) is healing only: its slot is a zero-damage
  receipt carrying the Triumph stacks Alistar walks in with, so the
  self-heal rule can complete the seven-stack set inside the fight.
- R (Unbreakable Will) stays `out_of_scope` and off the slot map: it
  reduces incoming damage by 55-75%, and the engine's
  ``incoming_damage_multiplier`` axis is item-only
  (``defensive_effects.py``) — no champion can author a
  damage-reduction-taken row.

All numeric values are read from the champion JSON data; nothing is
hardcoded.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .healing_contract import declare_healing_rule
from .slotlib import damage_entry, extract_cooldown, extract_named, simple_damage
from .source_receipts import load_champion_sources


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


# A carried set of 7 would consume itself before the fight, so the option
# stops one short: 0-6 stacks in hand, and Q/W supply the rest.
_TRIUMPH_CARRY_MAX = 6


def _triumphant_roar(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: the Triumph stacks Alistar carries into the fight.

    "Alistar generates a stack of Triumph for each enemy champion he stuns
    or displaces with his abilities, and each time a nearby enemy minion or
    non-epic monster dies... At 7 stacks, Alistar consumes them all to heal
    himself for 5% of his maximum health."  Q and W each generate one
    against this fight's champion, so a duel reaches at most two — the
    stacks Alistar walked in with are what decide whether the set completes,
    and they are player state the model cannot derive.  The heal formula
    itself stays in the self-heal rule, which reads it from the same cached
    P prose.
    """
    ability = ctx.ability("P")
    if ability is None:
        return None
    stacks = max(0, min(int(ctx.option("p_triumph_stacks")), _TRIUMPH_CARRY_MAX))
    if stacks <= 0:
        return None
    return {
        "name": ability.get("name", "Triumphant Roar"),
        "rank": ctx.level,
        "cooldown": 0.0,
        "damage_type": "magic",
        "total_raw": 0.0,
        "parts": (),
        "self_heal_state": {"stacks": stacks},
        "detail": f"{stacks} Triumph stack(s) carried into the fight",
    }


OPTIONS: list[dict[str, Any]] = [
    {
        "key": "p_triumph_stacks",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": _TRIUMPH_CARRY_MAX,
        "step": 1,
        "label": "Triumph stacks carried into the fight (P Triumphant Roar)",
        "rotation": {
            "role": "self_state",
            "slot": "P",
            "note": (
                "Q and W each add one Triumph stack; the carried stacks "
                "decide whether the seventh lands inside the fight, and "
                "no cast order changes them."
            ),
        },
    },
]

ASSUMPTIONS = [
    "E Trample deals full duration damage (10 ticks over 5 seconds)",
    "E empowered auto always procs once per cast (5 stacks reached)",
    "P (Triumphant Roar) heals 5% of maximum health when the seventh "
    "Triumph stack lands (cached P prose). Q and W each generate one "
    "stack against this fight's champion, so p_triumph_stacks (default "
    "0) supplies the rest; minion and monster deaths are not simulated, "
    "and the wiki's unstated internal cooldown ('only once every few "
    "seconds') is not enforced. The 7%-maximum-health ally heal in the "
    "same sentence belongs to the ally scanner, not to this rule",
    "R (Unbreakable Will) damage reduction is ignored",
]

SLOTS = {
    "P": _triumphant_roar,
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


SOURCES = load_champion_sources("Alistar")

SELF_HEALING_RULE = declare_healing_rule("Alistar")
