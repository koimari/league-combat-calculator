"""Warwick — CP10.9 packet module with the E9-1 R gap fix and the FC riders.

E9-1 closes the remaining audit gap: R (Infinite Duress) was declared
no_damage although the wiki cache carries "Total Magic Damage"
175/350/525 + 167% bonus AD over the 1.5-second suppress channel (the
wiki notes the channel deals magic damage every 0.25 seconds and that
on-hit/on-attack effects apply 3 times over its duration).  This
module prices the total as the R cast, which also lets healing.py's
100%-of-R-damage self-heal rule fire.

The coverage-frontier riders close P and W:

- P (Eternal Hunger) is the kit's on-hit rider — "Warwick deals
  6 : 60.76 (based on level) (+ 15% bonus AD) (+ 10% AP) bonus magic
  damage on-hit" — read from the cached per-level row and layered onto
  every basic attack.  It IS an on-hit, so item on-hit effects do not
  proc from it; it rides the swing they already proc from.  Its
  low-health self-heal is paid by the Warwick healing rule off the
  share this module publishes (``self_heal_share_of_damage``).
- W (Blood Hunt) is the attack-speed steroid the cache carries, applied
  through the engine's ``stat_buff`` channel.  The active marks the
  target "regardless of their current health", so a cast W always
  grants the base bonus; the doubled tier reads the shared
  ``target_missing_hp_pct`` option.  Blood Hunt's movement speed has no
  engine channel and stays unpriced.

E (Primal Howl) closes as ``modeled``.  Its 35-55% Damage Reduction is
damage *taken* — an axis this engine did not carry when the slot was
first reviewed, and does carry now: PR 202's champion-authored
``self_state_events`` packet of ``kind: "damage_modifier"`` (precedent:
Briar E, ``briar.py``'s ``_chilling_scream``; Alistar R, ``alistar.py``'s
``_unbreakable_will``), folded by
``participant_timeline._support_effect_templates`` and armed by
``survival.transitions._apply_damage_modifier``.  E is a zero-damage
row: the cast total is 0.0 and the whole mechanic is the self-state
window.  The ranked "Damage Reduction" leveling row (35/40/45/50/55%)
is read through the typed ``required_ranked_attribute_atom`` accessor
and the "for up to 2.75 seconds" window is the same description's prose
``timing.active_duration`` atom.  The declared classes are the full
``DamageClass`` set — the Briar-E convention, because the cached E
description and notes name NO damage-type carve-out (Alistar's
true-damage exclusion is declared there only because his cached note
states it outright).  The recast's fear plus 90% slow are crowd control
the model still does not price, and a *manual* recast (available after
1 second) would end the window early — the module prices the automatic
recast the cache describes, which fires "after the duration".
"""

from functools import partial
from typing import Any

from .. import healing_helpers as _healing
from ..ability_atoms import (
    AbilityAtomQuery,
    ranked_ability_atom_value,
    required_ability_atom,
    required_ranked_attribute_atom,
)
from ..ability_spec import AttackClass, DamageClass, DamagePart
from ..survival.actions import TransitionRank
from .engine import BUFF, ONHIT, SlotCtx
from .healing_contract import self_healing_rule
from .module_helpers import missing_hp_fraction
from .packet_module import build_packet_module
from .slotlib import (
    atom_receipt,
    damage_entry,
    extract_cooldown,
    extract_named,
    on_hit_entry,
    stat_buff,
    with_item_on_hits,
)

# Sourced channel (wiki R): "deal magic damage every 0.25 seconds" over
# the up-to-1.5s suppress; "applies on-hit effects and triggers
# on-attack effects 3 times over its duration".
_R_CHANNEL_SECONDS = 1.5

# HARDCODED: verify on patch updates — Eternal Hunger's heal is cached
# PROSE, not a leveling row: "While below 50% maximum health, Warwick
# also heals for 100% of the post-mitigation damage dealt by Eternal
# Hunger, increased to 250% while below 25% maximum health."
_HUNGER_HEAL_HEALTH_PERCENT = 50.0
_HUNGER_HEAL_SHARE = 1.0
_HUNGER_RAGE_HEALTH_PERCENT = 25.0
_HUNGER_RAGE_SHARE = 2.5

# Blood Hunt's two tiers are the TARGET's health: the passive triggers
# below 50% maximum health and both bonuses are "doubled against enemies
# who are below 25% of their maximum health".  Below 25% maximum health
# is more than 75% missing.
_BLOOD_HUNT_DOUBLED_MISSING = 0.75


def _infinite_duress(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: Total Magic Damage over the 1.5s suppress channel."""
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked

    total = extract_named(ability, "Total Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability["name"],
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", total, time_offset=0.0),)
    entry["dot_duration"] = _R_CHANNEL_SECONDS
    entry["detail"] = (
        "Total Magic Damage 175/350/525 + 167% bonus AD over the "
        f"{_R_CHANNEL_SECONDS:g}s suppress channel (magic damage every "
        "0.25s; the wiki's 3 on-hit applications are item on-hit/on-"
        "attack riders, not extra ability damage, and are not "
        "multiplied — the cache publishes no per-tick row)"
    )
    return entry


def _hunger_heal_share(health_percent: float) -> float:
    """The share of Eternal Hunger's damage Warwick heals at a health %."""
    if health_percent < _HUNGER_RAGE_HEALTH_PERCENT:
        return _HUNGER_RAGE_SHARE
    if health_percent < _HUNGER_HEAL_HEALTH_PERCENT:
        return _HUNGER_HEAL_SHARE
    return 0.0


def _eternal_hunger(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: bonus magic damage on every basic attack, plus its heal share."""
    ability = ctx.ability()
    if ability is None:
        return None
    per_hit = extract_named(
        ability, "Per-Level Scaling", ctx.level, ctx.stats, ctx.target, level=ctx.level
    )
    if per_hit <= 0:
        return None

    entry = on_hit_entry(ability["name"], per_hit, "magic")
    health_percent = min(max(float(ctx.option("p_self_health_percent")), 0.0), 100.0)
    share = _hunger_heal_share(health_percent)
    # ``derive_self_healing`` below pays this share of every post-mitigation
    # Eternal Hunger hit.  The slot owns the health state, so the share is
    # published on the entry rather than re-derived by the resolver.
    entry["self_heal_share_of_damage"] = share
    entry["detail"] = (
        f"{per_hit:.2f} bonus magic damage on-hit (6 : 60.76 based on level "
        "+ 15% bonus AD + 10% AP); Warwick at "
        f"{health_percent:g}% health heals for {share:.0%} of the "
        "post-mitigation damage it deals"
    )
    return entry


_eternal_hunger.phase = ONHIT


_BLOOD_HUNT_TIERS = {
    False: (
        "Bonus Attack Speed",
        stat_buff("Bonus Attack Speed", "bonus_attack_speed"),
    ),
    True: (
        "Increased Attack Speed",
        stat_buff("Increased Attack Speed", "bonus_attack_speed"),
    ),
}


def _blood_hunt(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: the Blood Hunt attack-speed steroid, base or doubled."""
    doubled = missing_hp_fraction(ctx) > _BLOOD_HUNT_DOUBLED_MISSING
    attribute, parser = _BLOOD_HUNT_TIERS[doubled]
    entry = parser(ctx)
    if entry is None:
        return None
    bonus = entry["stat_buff"]["bonus_attack_speed"]
    entry["detail"] = (
        f"{bonus:g}% bonus attack speed (the sourced {attribute} row"
        + (
            " — the target is below 25% maximum health)"
            if doubled
            else "; the active marks the target regardless of its health)"
        )
        + "; Blood Hunt's movement speed has no engine channel"
    )
    return entry


_blood_hunt.phase = BUFF


_E_REDUCTION_SOURCE = "Warwick.E[0].effects[0].description"


def _primal_howl(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: zero damage, a sourced incoming-damage-reduction self-state window.

    "Active: Warwick gains damage reduction for up to 2.75 seconds. Primal
    Howl can be recast after 1 second, and does so automatically after the
    duration." (cached E[0].effects[0].description).  The percent is a normal
    ranked leveling row ("Damage Reduction": 35/40/45/50/55%), read through
    the typed ``required_ranked_attribute_atom`` accessor; the window is the
    same description's prose ``timing.active_duration`` atom (the Briar E /
    Alistar R helper).  Every damage class is declared: unlike Alistar's
    Unbreakable Will, no cached sentence in this kit carves true damage — or
    any other type — out, so the un-narrowed declaration is the sourced one.
    """
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked

    champion_data = {"name": ctx.champion_name, "abilities": ctx.abilities}
    reduction_percent, reduction_atom = required_ranked_attribute_atom(
        ctx.champion_name, champion_data, "E", "Damage Reduction", rank
    )
    # The wiki row carries one unit entry per rank (five '%'); require every
    # entry to be percent (fail-closed on any non-percent unit) rather than
    # pinning the list shape.
    reduction_units = {str(unit).strip().lower() for unit in reduction_atom["units"]}
    if not reduction_units or reduction_units != {"%"}:
        raise ValueError("Warwick E damage-reduction atom must use percent")

    duration_atom = required_ability_atom(
        ctx.champion_name,
        champion_data,
        "E",
        query=AbilityAtomQuery(
            source=_E_REDUCTION_SOURCE,
            behavior="timing",
            evidence_prefix="active duration@",
        ),
    )
    if [str(unit).strip().lower() for unit in duration_atom["units"]] != ["s"]:
        raise ValueError("Warwick E active-duration atom must use seconds")
    duration = ranked_ability_atom_value(duration_atom, 1, source=_E_REDUCTION_SOURCE)

    name = ability["name"]
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
                # 35..55% damage reduction -> take (1 - pct/100) of each
                # incoming packet.
                "multiplier": 1.0 - reduction_percent / 100.0,
                "duration": duration,
                "source": f"{name} · damage reduction",
                "source_atoms": [
                    atom_receipt(reduction_atom),
                    atom_receipt(duration_atom),
                ],
                # The cached prose grants "damage reduction" with no
                # attack/spell-only carve-out, so the modifier gates no
                # source kind (the Briar-E / Glacial-Augment convention).
                "all_sources": True,
                # D-04: a modifier names its classes; this kit's cache names
                # no excluded type, so the full enum IS the declaration —
                # never an empty one, and never Alistar's narrowed pair,
                # which his own cached note sources and this one does not.
                "damage_classes": frozenset(DamageClass),
                "attack_classes": frozenset(AttackClass),
                # An amplification already in force at its own timestamp
                # must price the hit landing at that timestamp.
                "_rank": TransitionRank.AURA_ARM,
            }
        ],
        "detail": (
            f"Primal Howl reduces incoming damage by {reduction_percent:g}% for "
            f"{duration:g}s (the automatic recast ends it at the duration; a "
            "manual recast — and its fear plus 90% slow — is not modeled)"
        ),
    }


PACKET_SHA256 = "2c91dcf27a641c6a177969744e204b672765d8fc7291214c069ecacc64511a19"

# Jaws of the Beast only bites ("dealing magic damage, healing himself...");
# the displacement immunity is Warwick's own.  Infinite Duress "knocks them
# down and channels for up to 1.5 seconds to suppress, reveal, and deal
# magic damage every 0.25 seconds" — the suppression is the control the
# damaged target is under for the whole priced channel.  E (Primal Howl,
# where the fear and 90% slow live) is modeled but authors no damage part:
# its fear rides the *recast*, which this module does not price, so there
# is no event a control review could reach.  W is a pure stat buff and P an
# on-hit rider on basic attacks, so neither authors a part either.
MODULE_CC = {"Q": "none", "R": "suppression"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Warwick",
    PACKET_SHA256,
    assumption_overrides=(
        "Warwick Q's sourced 0.264-second bite delay is applied to the hit "
        "event without inventing a channel lockout.",
    ),
    single_hit_slots=frozenset({"Q"}),
    packet_part_timings={"Q": {"time_offset": 0.264}},
    slot_parsers={
        "P": _eternal_hunger,
        "W": _blood_hunt,
        # The packet compiles E as ``no_damage`` (it carries no enemy-damage
        # formula, which is true); this override keeps that zero and adds the
        # self-state window the packet has no vocabulary for.
        "E": _primal_howl,
        "R": _infinite_duress,
    },
    slot_wrappers={
        "Q": partial(
            with_item_on_hits,
            effectiveness=1.0,
            hits=1,
            triggers=("on_hit", "on_attack"),
        ),
    },
    cc_kinds=MODULE_CC,
)

OPTIONS.append(
    {
        "key": "p_self_health_percent",
        "type": "int",
        "default": 100,
        "min": 0,
        "max": 100,
        "label": (
            "Warwick's own health % (Eternal Hunger heals for 100% of its "
            "damage below 50%, 250% below 25%)"
        ),
    }
)
OPTIONS.append(
    {
        "key": "target_missing_hp_pct",
        "type": "int",
        "default": 50,
        "min": 0,
        "max": 100,
        "label": "Target missing health % (Blood Hunt doubles above 75%)",
    }
)

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "R (Infinite Duress) prices the wiki Total Magic Damage "
    "(175/350/525 + 167% bonus AD by rank) as one cast over the "
    "1.5-second suppress channel; healing.py's existing 100%-of-R-"
    "damage self-heal rule fires on the R damage event.  The channel's "
    "0.25s magic-damage ticks and its 3 on-hit/on-attack applications "
    "are documented cadence: item on-hits are not multiplied (the "
    "cache publishes no per-tick row).",
    "P (Eternal Hunger) is an on-hit rider on every basic attack: the "
    "cached per-level row (6 : 60.76 + 15% bonus AD + 10% AP magic).  "
    "It is an on-hit itself, so item on-hit effects do not proc from "
    "it — they proc from the swing it rides.  Its self-heal (100% of "
    "the post-mitigation damage below 50% maximum health, 250% below "
    "25%) is cached prose, gated on the p_self_health_percent option "
    "(default 100% — a healthy Warwick heals nothing) and paid by the "
    "Warwick healing rule.",
    "W (Blood Hunt) grants the sourced Bonus Attack Speed row "
    "(70-110% by rank) for the whole fight: the active marks the target "
    "'regardless of their current health', so the base tier needs no "
    "condition.  The doubled row (140-220%) applies when "
    "target_missing_hp_pct exceeds 75 (the target below 25% maximum "
    "health).  Blood Hunt's bonus movement speed and its 8-second mark "
    "duration are not modeled — stat_buff has no movement-speed key.",
    "E (Primal Howl) is modeled as a zero-damage self-state window: the "
    "ranked Damage Reduction row (35/40/45/50/55%, required_ranked_"
    "attribute_atom) prices the multiplier and the description's prose "
    "'for up to 2.75 seconds' (timing.active_duration atom) prices the "
    "window, armed through self_state_events kind=damage_modifier "
    "(Briar-E / Alistar-R precedent). Every DamageClass is declared: the "
    "cached E description and notes name no excluded damage type, so "
    "narrowing the set would be the invented reading rather than the "
    "conservative one. The window priced is the automatic recast's — the "
    "cache says Primal Howl 'does so automatically after the duration' — "
    "so a manual recast (legal after 1 second) shortening it is not "
    "modeled, and neither is that recast's 1-second fear or its 90% slow "
    "(crowd control this model does not price on a recast it never "
    "issues).",
]
# No MODULE_COVERAGE: with E closed, every slot this module emits is
# ``modeled``, which is exactly what ``default_coverage`` derives from
# SLOTS — and the contract refuses a declaration that only restates it.


# pylint: disable=too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Resolve Warwick self-healing events from its authored packet."""
    healing = []
    q = _healing.ability_json(champion_data, "Q")
    q_rank = _healing.parsed_rank(ability_damages, "Q")
    q_ratio = _healing.extract_named(
        q, "Healing Percentage", q_rank, champion_stats, {}
    )
    for event in damage_events:
        source = _healing.event_source(event)
        if source == "Q":
            _healing.heal_from_damage(
                healing,
                event,
                float(event.get("damage", 0.0)) * q_ratio / 100.0,
                "Jaws of the Beast",
            )
        elif source == "R":
            # Infinite Duress explicitly heals for 100% of all
            # post-mitigation damage dealt to its target.
            _healing.heal_from_damage(
                healing, event, float(event.get("damage", 0.0)), "Infinite Duress"
            )
    # Eternal Hunger (P): "While below 50% maximum health, Warwick also
    # heals for 100% of the post-mitigation damage dealt by Eternal Hunger,
    # increased to 250% while below 25% maximum health" (cached P
    # description).  Warwick's own health is module state, so ``_eternal_hunger``
    # owns the threshold and publishes the resulting share on its P entry;
    # this pays that share of every on-hit event the passive authored.  A
    # healthy Warwick publishes 0 and heals none.
    passive_entry = ability_damages.get("passive")
    hunger_share = (
        0.0
        if passive_entry is None
        else float(passive_entry["self_heal_share_of_damage"])
    )
    if hunger_share > 0.0:
        for payment in _healing.payments(
            _healing.HealAnchor.DAMAGING_HIT,
            "on_hit_ability_passive",
            damage_events,
        ):
            event = payment.event
            _healing.heal_from_damage(
                healing,
                event,
                float(event.get("damage", 0.0)) * hunger_share,
                "Eternal Hunger",
            )
    return healing


SELF_HEALING_RULE = self_healing_rule("Warwick")(derive_self_healing)
