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
  receipt carrying the Triumph stacks Alistar walks in with, so
  ``derive_self_healing`` can complete the seven-stack set inside the
  fight.  The same cached sentence also heals *allies* for 7% of his
  maximum health on the same trigger — a different amount than his own
  5%, which the engine's heal fan-out (``participant_timeline.py``
  clones one shared ``amount`` to every recipient) cannot express, so it
  belongs to the ally scanner rather than to this rule.
- R (Unbreakable Will) IS on the slot map: the old "no champion-authored
  incoming-damage-reduction hook" receipt is obsolete.  PR #202 gave the
  engine a champion-authored ``self_state_events`` packet of
  ``kind: "damage_modifier"`` (precedent: Briar E, ``briar.py``'s
  ``_chilling_scream``; Sivir E, ``sivir.py``'s ``_spell_shield``),
  consumed by ``participant_timeline._support_effect_templates`` (which
  folds ``result["self_state_events"]`` into a self-targeted support
  template) and armed by
  ``survival.transitions._apply_damage_modifier`` /
  ``_apply_cross_participant_modifiers``.  R is a zero-damage row: the
  cast total is 0.0 and the mechanic is entirely the self-state window.
  The ranked "Damage Reduction" leveling row (55/65/75%) is read through
  the typed ``required_ranked_attribute_atom`` accessor, exactly like a
  normal named-attribute read; the "for the next 7 seconds" active
  window is the cached description's prose ``timing.active_duration``
  atom (the same helper Briar E and Sivir E use).  The modifier
  declares physical + magic only — NOT true — because the cached ability
  note is explicit: "True damage cannot be reduced by any means and
  will deal full damage to Alistar during Unbreakable Will."  The
  self-cleanse of Alistar's own CC has no channel in this engine (no
  champion module clears an already-armed CC on itself) and stays
  unmodeled, same as before.


All numeric values are read from the champion JSON data; nothing is
hardcoded.
"""

import re
from typing import Any

from ..ability_atoms import (
    AbilityAtomQuery,
    ranked_ability_atom_value,
    required_ability_atom,
    required_ranked_attribute_atom,
)
from ..ability_spec import AttackClass, DamageClass, DamagePart
from ..healing_helpers import HealAnchor, _payments, _ability, _trigger_fields
from ..survival.actions import TransitionRank
from .inputs import champion_stat
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


_R_DURATION_SOURCE = "Alistar.R[0].effects[0].description"

_ATOM_RECEIPT_KEYS = (
    "atom_id",
    "behavior",
    "source",
    "values",
    "units",
    "evidence",
    "hash",
)


def _atom_receipt(atom: dict[str, Any]) -> dict[str, Any]:
    """Keep the provenance fields that identify one runtime atom."""
    return {key: atom[key] for key in _ATOM_RECEIPT_KEYS}


def _unbreakable_will(ctx: SlotCtx) -> dict[str, Any] | None:
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
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    champion_data = {"name": ctx.champion_name, "abilities": ctx.abilities}
    reduction_percent, reduction_atom = required_ranked_attribute_atom(
        ctx.champion_name, champion_data, "R", "Damage Reduction", rank
    )
    # The wiki row carries one unit entry per rank (['%', '%', '%']); require
    # every entry to be percent (fail-closed on any non-percent unit) rather
    # than pinning the list shape.
    reduction_units = {str(unit).strip().lower() for unit in reduction_atom["units"]}
    if not reduction_units or reduction_units != {"%"}:
        raise ValueError("Alistar R damage-reduction atom must use percent")

    duration_atom = required_ability_atom(
        ctx.champion_name,
        champion_data,
        "R",
        query=AbilityAtomQuery(
            source=_R_DURATION_SOURCE,
            behavior="timing",
            evidence_prefix="active duration@",
        ),
    )
    if [str(unit).strip().lower() for unit in duration_atom["units"]] != ["s"]:
        raise ValueError("Alistar R active-duration atom must use seconds")
    duration = ranked_ability_atom_value(duration_atom, 1, source=_R_DURATION_SOURCE)

    name = ability.get("name", "Unbreakable Will")
    return {
        "name": name,
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "magic",
        "total_raw": 0.0,
        "parts": (),
        "self_state_events": [
            {
                "kind": "damage_modifier",
                # 55/65/75% damage reduction -> take (1 - pct/100) of each
                # incoming physical/magic packet.
                "multiplier": 1.0 - reduction_percent / 100.0,
                "duration": duration,
                "source": f"{name} · damage reduction",
                "source_atoms": [
                    _atom_receipt(reduction_atom),
                    _atom_receipt(duration_atom),
                ],
                # The cached prose reduces "incoming damage taken" with no
                # attack/spell-only carve-out, so the modifier gates no
                # source kind (the Briar-E / Glacial-Augment convention).
                "all_sources": True,
                # D-04: true damage is explicitly excluded by the cached
                # ability note ("True damage cannot be reduced by any
                # means"), so the declared set is physical + magic only —
                # NOT the full DamageClass enum.
                "damage_classes": frozenset({DamageClass.PHYSICAL, DamageClass.MAGIC}),
                "attack_classes": frozenset(AttackClass),
                # An amplification already in force at its own timestamp
                # must price the hit landing at that timestamp.
                "_rank": TransitionRank.AURA_ARM,
            }
        ],
        "detail": (
            f"Unbreakable Will reduces incoming physical/magic damage by "
            f"{reduction_percent:g}% for {duration:g}s (true damage is not "
            "reduced)."
        ),
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
    "Triumph stack lands (cached P prose), through SELF_HEALING_RULE. Q "
    "and W each generate one stack against this fight's champion, so "
    "p_triumph_stacks (default 0) supplies the rest; minion and monster "
    "deaths are not simulated, and the wiki's unstated internal cooldown "
    "('only once every few seconds') is not enforced. The 7%-of-maximum-"
    "health ally heal in the same sentence is a different amount than "
    "the 5% self heal, and the engine's champion-authored heal fan-out "
    "clones one shared amount to every recipient — so it belongs to the "
    "ally scanner, not to this rule",
    "R (Unbreakable Will) is modeled as a zero-damage self-state window: "
    "the ranked Damage Reduction row (55/65/75%, required_ranked_"
    "attribute_atom) prices the multiplier and the description's prose "
    "'for the next 7 seconds' (timing.active_duration atom) prices the "
    "window, armed through self_state_events kind=damage_modifier "
    "(Briar-E / Sivir-E precedent). Declared classes are physical + "
    "magic only: true damage is explicitly excluded ('True damage "
    "cannot be reduced by any means and will deal full damage to "
    "Alistar during Unbreakable Will', cached R note). The self-cleanse "
    "of Alistar's own crowd control has no channel in this engine (no "
    "champion module clears an already-armed CC on itself) and stays "
    "unmodeled",
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
MODULE_CC = {"Q": "immobilize", "W": "immobilize"}

parse_abilities = build_parser(SLOTS, "Alistar", cc_kinds=MODULE_CC)


SOURCES = load_champion_sources("Alistar")


# pylint: disable=too-many-arguments,too-many-positional-arguments,protected-access
def derive_self_healing(
    champion_data: dict[str, Any],
    champion_stats: dict[str, float],
    ability_damages: dict[str, dict[str, Any]],
    damage_events: list[dict[str, Any]],
    cast_timeline: list[dict[str, Any]] | None = None,
    fight_duration_seconds: float | None = None,
) -> list[dict[str, Any]]:
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
    del fight_duration_seconds
    healing: list[dict[str, Any]] = []
    p_text = " ".join(
        effect.get("description", "")
        for effect in _ability(champion_data, "P").get("effects", [])
    )
    stack_match = re.search(r"At\s+(\d+)\s+stacks", p_text, flags=re.IGNORECASE)
    stack_cap = int(stack_match.group(1)) if stack_match else 0
    if stack_cap <= 0:
        return healing
    self_match = re.search(
        r"heal(?:s|ing)? himself for\s+(\d+(?:\.\d+)?)%\s+of his maximum health",
        p_text,
        flags=re.IGNORECASE,
    )
    self_ratio = float(self_match.group(1)) / 100.0 if self_match else 0.0
    casts = sorted(
        _payments(HealAnchor.CAST, "Q", damage_events, cast_timeline)
        + _payments(HealAnchor.CAST, "W", damage_events, cast_timeline),
        key=lambda payment: float(payment.event.get("time", 0.0)),
    )
    carried = ability_damages.get("passive", {}).get("self_heal_state")
    qw_seen = int(carried.get("stacks", 0) or 0) if isinstance(carried, dict) else 0
    for payment in casts:
        event = payment.event
        qw_seen += 1
        if qw_seen % stack_cap == 0:
            healing.append(
                {
                    "time": float(event.get("time", 0.0)),
                    "amount": self_ratio * champion_stat(champion_stats, "health"),
                    "source": "Triumphant Roar",
                    "kind": "champion_passive",
                    **_trigger_fields(event),
                }
            )
    return sorted(healing, key=lambda event: (event["time"], event["source"]))


SELF_HEALING_RULE = declare_healing_rule("Alistar", derive_self_healing)
