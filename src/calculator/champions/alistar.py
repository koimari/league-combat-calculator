"""Alistar: slot map for the archetype engine.

E (Trample) reads the "Total Magic Damage" attribute, all ten ticks over five
seconds, because the classifier would pick the per-tick row first.  The
empowered-auto bonus Trample grants once per cast scales with champion level
rather than rank and is baked into the cast total rather than emitted as an
on-hit.
Q (Pulverize) and W (Headbutt) are generic single-hit magic damage.
P (Triumphant Roar) heals only.  Its slot is a zero-damage receipt carrying
the Triumph stacks Alistar walks in with, so ``derive_self_healing`` can
complete the seven-stack set inside the fight.  The same sentence heals allies
for 7% of his maximum health against his own 5%, and the heal fan-out clones
one shared amount to every recipient, so the ally half belongs to the scanner.
R (Unbreakable Will) is a zero-damage row whose whole mechanic is a
``self_state_events`` window of ``kind: "damage_modifier"`` carrying the
ranked 55/65/75% reduction for seven seconds.  It declares physical and magic
only, never true, because the cached note is explicit that true damage reaches
him in full.  His self-cleanse has no channel here.
"""

import re
from collections.abc import Mapping
from typing import Any

from ..ability_atoms import ability_payload
from ..ability_prose import CachedSentence
from ..ability_spec import DamageClass, DamagePart
from ..damage_event_row import event_time as _row_time
from ..healing_helpers import HealAnchor, ability_json, trigger_fields
from .engine import SlotCtx, build_parser
from .healing_contract import SelfHealCtx, self_healing_rule
from .inputs import champion_stat, int_option
from .module_helpers import ability_slot, ranked_slot
from .shared_mechanics import damage_reduction_window
from .slot_cc import CC_PER_PART
from .slot_entries import damage_entry
from .slot_extract import ability_name, extract_cooldown, extract_named
from .slotlib import simple_damage
from .source_receipts import load_champion_sources


def _extract_e_on_hit_damage(
    ability: Mapping[str, Any],
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


@ranked_slot
def _trample(ctx: SlotCtx, ability: dict[str, Any], rank: int) -> dict[str, Any] | None:
    """E: 10 sourced ticks of the per-tick row + level-scaled empowered auto.

    The per-tick value x 10 equals the JSON's "Total Magic Damage" at
    every rank, so the fight prices the full cast total across the
    tick timeline instead of one lump.
    """

    per_tick = extract_named(
        ability, "Magic Damage Per Tick", rank, ctx.stats, ctx.target
    )
    # The empowered auto procs once per E cast (after the 5s trample),
    # so it joins the cast total instead of becoming a per-auto on_hit
    # entry.
    empowered = _extract_e_on_hit_damage(ability, ctx.level)

    name = ability_name(ability)
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


@ability_slot("P")
def _triumphant_roar(ctx: SlotCtx, ability: dict[str, Any]) -> dict[str, Any] | None:
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
    stacks = max(0, min(int(ctx.option("p_triumph_stacks")), _TRIUMPH_CARRY_MAX))
    if stacks <= 0:
        return None
    return {
        "name": ability_name(ability),
        "rank": ctx.level,
        "cooldown": 0.0,
        "damage_type": "magic",
        "total_raw": 0.0,
        "parts": (),
        "self_heal_state": {"stacks": stacks},
        "detail": f"{stacks} Triumph stack(s) carried into the fight",
    }


_R_DURATION_SOURCE = "Alistar.R[0].effects[0].description"

# Triumphant Roar is prose only: the innate states how many stacks a heal
# costs and what share of Alistar's maximum health it pays, and no P
# leveling row carries either.
_TRIUMPHANT_ROAR_STACKS = CachedSentence(
    re.compile(r"At\s+(?P<value>\d+)\s+stacks", re.IGNORECASE),
    missing=(
        "Alistar P (Triumphant Roar): the cached innate no longer states the "
        "stack cost of a heal ('At N stacks')"
    ),
)
_TRIUMPHANT_ROAR_SELF_HEAL = CachedSentence(
    re.compile(
        r"heal(?:s|ing)? himself for\s+(?P<value>\d+(?:\.\d+)?)%\s+"
        r"of his maximum health",
        re.IGNORECASE,
    ),
    missing=(
        "Alistar P (Triumphant Roar): the cached innate no longer states the "
        "self-heal share ('heals himself for N% of his maximum health')"
    ),
)


@ranked_slot
def _unbreakable_will(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """R: zero damage, a sourced incoming-damage-reduction self-state window.

    "Active: Alistar cleanses himself of all crowd control. For the next
    7 seconds, he reduces incoming damage taken." (cached R[0].effects[0]
    description).  The percent is a normal ranked leveling row
    ("Damage Reduction": 55/65/75%), read through the typed
    ``required_ranked_attribute_atom`` accessor; the "7 seconds" window
    is the same description's prose ``timing.active_duration`` atom
    (the Briar E / Sivir E helper).  True damage is excluded from the
    declared classes: the cached ability note states "True damage cannot
    be reduced by any means and will deal full damage to Alistar during
    Unbreakable Will."  The self-CC-cleanse has no channel in this engine
    and stays unmodeled (see the module docstring).
    """

    return damage_reduction_window(
        ctx,
        ability,
        rank,
        duration_source=_R_DURATION_SOURCE,
        # True damage is explicitly excluded by the cached ability
        # note ("True damage cannot be reduced by any means"), so the
        # declared set is physical + magic only, NOT the full enum.
        damage_classes=frozenset({DamageClass.PHYSICAL, DamageClass.MAGIC}),
        detail=lambda percent, duration: (
            f"Unbreakable Will reduces incoming physical/magic damage by "
            f"{percent:g}% for {duration:g}s (true damage is not "
            "reduced)."
        ),
    )


OPTIONS: list[dict[str, Any]] = [
    int_option(
        "p_triumph_stacks",
        0,
        minimum=0,
        maximum=_TRIUMPH_CARRY_MAX,
        label="Triumph stacks carried into the fight (P Triumphant Roar)",
        step=1,
        rotation={
            "role": "self_state",
            "slot": "P",
            "note": (
                "Q and W each add one Triumph stack; the carried stacks "
                "decide whether the seventh lands inside the fight, and "
                "no cast order changes them."
            ),
        },
    ),
]

ASSUMPTIONS = [
    "E Trample deals full duration damage (10 ticks over 5 seconds)",
    "E empowered auto always procs once per cast (5 stacks reached)",
    "P (Triumphant Roar) heals 5% of maximum health on the seventh Triumph stack "
    "(cached P prose).",
    "Q and W each bank one stack here, so p_triumph_stacks (default 0) supplies the "
    "rest; minion deaths are not simulated.",
    "The wiki's unstated internal cooldown is not enforced, and the 7% ally heal is "
    "the ally scanner's, not this rule.",
    "R (Unbreakable Will) is a zero-damage self-state window: 55/65/75% Damage "
    "Reduction over the 7s duration atom.",
    "R arms self_state_events damage_modifier over physical and magic only; the "
    "cached R note excludes true damage.",
    "Alistar's self-cleanse of his own crowd control has no channel in this engine "
    "and stays unmodeled.",
]

SLOTS = {
    "P": _triumphant_roar,
    # Both are one instantaneous hit with no sourced sub-cast phase — the
    # smash lands beneath Alistar and the headbutt on arrival — so each
    # certifies the cast boundary its reviewed control rides on.
    "Q": simple_damage(event_order_certified="single_hit"),
    "W": simple_damage(event_order_certified="single_hit"),
    "E": _trample,
    "R": _unbreakable_will,
}

# Cached kit review.  Q stuns "and knock[s] them up simultaneously for 1
# second" and W "knocks them back 700 units ... while also stunning them
# for 0.75 seconds": each cast applies two immobilize kinds at once, which
# is what the un-narrowed "immobilize" kind states.  E is absent because
# its two parts disagree (see _trample); P deals no damage and R's own
# self-cleanse is not a control effect applied to a target, so neither
# names a CC kind here.
MODULE_CC = {
    "Q": "immobilize",
    "W": "immobilize",
    "E": CC_PER_PART,
    "P": "none",
    "R": "none",
}

parse_abilities = build_parser(SLOTS, "Alistar", cc_kinds=MODULE_CC)


SOURCES = load_champion_sources("Alistar")


def derive_self_healing(ctx: SelfHealCtx) -> list[dict[str, Any]]:
    """Price Triumphant Roar: 5% maximum health per completed 7-stack set.

    Both numbers are read from the cached P prose ("At 7 stacks, Alistar
    consumes them all to heal himself for 5% of his maximum health").  Q
    and W each generate one Triumph stack per enemy champion hit, so the
    stacks count *casts*, not the parts a cast is priced with — hence the
    ``CAST`` anchor.  A duel reaches at most two stacks on its own, so the
    set completes only with stacks already in hand, which the P row
    carries from its declared option.  A nearby champion death would grant
    all seven at once, but a 1v1 kill ends the fight before any heal
    receipt can apply.
    """
    healing: list[dict[str, Any]] = []
    passive = ability_json(ctx.champion_data, "P")
    stack_cap = int(_TRIUMPHANT_ROAR_STACKS.value(passive))
    if stack_cap <= 0:
        return healing
    self_ratio = _TRIUMPHANT_ROAR_SELF_HEAL.value(passive) / 100.0
    casts = sorted(
        ctx.payments(HealAnchor.CAST, "Q") + ctx.payments(HealAnchor.CAST, "W"),
        key=lambda payment: _row_time(payment.event),
    )
    carried = ability_payload(ctx.ability_damages, "passive").get("self_heal_state")
    qw_seen = int(carried.get("stacks", 0) or 0) if isinstance(carried, dict) else 0
    for payment in casts:
        event = payment.event
        qw_seen += 1
        if qw_seen % stack_cap == 0:
            healing.append(
                {
                    "time": _row_time(event),
                    "amount": self_ratio * champion_stat(ctx.champion_stats, "health"),
                    "source": "Triumphant Roar",
                    "kind": "champion_passive",
                    **trigger_fields(event),
                }
            )
    return healing


SELF_HEALING_RULE = self_healing_rule("Alistar")(derive_self_healing)
