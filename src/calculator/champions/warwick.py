"""Warwick: on-hit rider, blood-hunt steroid and a damage-reduction window.

R (Infinite Duress) prices the cached "Total Magic Damage" over the 1.5-second
suppress channel, which is also what lets the 100%-of-R self-heal rule fire.
P (Eternal Hunger) is the kit's on-hit rider, read from the cached per-level
row and layered onto every basic attack.  Being an on-hit itself, it does not
proc item on-hits; it rides the swing they already proc from.  Its low-health
self-heal is paid from the share this module publishes.
W (Blood Hunt) is the attack-speed steroid, applied through ``stat_buff``.
The active marks the target regardless of current health, so a cast W always
grants the base bonus and only the doubled tier reads
``target_missing_hp_pct``.  Its movement speed has no channel.
E (Primal Howl) is a zero-damage row whose whole mechanic is a
``self_state_events`` window of ``kind: "damage_modifier"`` carrying the
ranked 35 to 55% reduction for up to 2.75 seconds.  It declares the full
``DamageClass`` set because the cached description names no carve-out, unlike
Alistar R.  The module prices the automatic recast the cache describes; a
manual recast would end the window early, and the recast's fear and slow are
control this model does not price.
"""

from functools import partial
from typing import Any

from .. import healing_helpers as _healing
from ..ability_atoms import ability_payload
from ..ability_spec import DamageClass
from ..binary_roots import data_value, spell_object
from ..damage_event_row import event_damage as _row_damage
from .engine import BUFF, ONHIT, SlotCtx
from .healing_contract import SelfHealCtx, self_healing_rule
from .module_helpers import ability_slot, missing_hp_fraction, named_damage, ranked_slot
from .packet_module import build_packet_module
from .shared_mechanics import damage_reduction_window
from .shared_option_keys import TARGET_MISSING_HP_OPTION
from .slot_cc import CC_PER_PART
from .slot_entries import on_hit_entry
from .slot_extract import ability_name, extract_named
from .slotlib import stat_buff, with_item_on_hits

# Sourced channel (wiki R): "deal magic damage every 0.25 seconds" over
# the up-to-1.5s suppress; "applies on-hit effects and triggers
# on-attack effects 3 times over its duration".
_R_CHANNEL_SECONDS = data_value(spell_object("Warwick", "WarwickR"), "RDuration")

# HARDCODED: verify on patch updates — Eternal Hunger's heal is cached
# PROSE, not a leveling row: "While below 50% maximum health, Warwick
# also heals for 100% of the post-mitigation damage dealt by Eternal
# Hunger, increased to 250% while below 25% maximum health."
_WARWICK_P_SPELL = spell_object("Warwick", "WarwickP")
_HUNGER_HEAL_HEALTH_PERCENT = data_value(_WARWICK_P_SPELL, "HealingThreshold") * 100.0
_HUNGER_HEAL_SHARE = data_value(_WARWICK_P_SPELL, "HealingRatio")
_HUNGER_RAGE_HEALTH_PERCENT = (
    data_value(_WARWICK_P_SPELL, "EmpoweredHealingThreshold") * 100.0
)
_HUNGER_RAGE_SHARE = data_value(_WARWICK_P_SPELL, "EmpoweredHealingRatio")

# Blood Hunt's two tiers are the TARGET's health: the passive triggers
# below 50% maximum health and both bonuses are "doubled against enemies
# who are below 25% of their maximum health".  Below 25% maximum health
# is more than 75% missing.
_BLOOD_HUNT_DOUBLED_MISSING = 0.75


# R: Total Magic Damage over the 1.5s suppress channel.
_infinite_duress = named_damage(
    "Total Magic Damage",
    "magic",
    time_offset=0.0,
    dot_duration=_R_CHANNEL_SECONDS,
    detail="Total Magic Damage 175/350/525 + 167% bonus AD over the "
    f"{_R_CHANNEL_SECONDS:g}s suppress channel (magic damage every "
    "0.25s; the wiki's 3 on-hit applications are item on-hit/on-"
    "attack riders, not extra ability damage, and are not "
    "multiplied — the cache publishes no per-tick row)",
)


def _hunger_heal_share(health_percent: float) -> float:
    """The share of Eternal Hunger's damage Warwick heals at a health %."""
    if health_percent < _HUNGER_RAGE_HEALTH_PERCENT:
        return _HUNGER_RAGE_SHARE
    if health_percent < _HUNGER_HEAL_HEALTH_PERCENT:
        return _HUNGER_HEAL_SHARE
    return 0.0


@ability_slot()
def _eternal_hunger(ctx: SlotCtx, ability: dict[str, Any]) -> dict[str, Any] | None:
    """P: bonus magic damage on every basic attack, plus its heal share."""
    per_hit = extract_named(
        ability, "Per-Level Scaling", ctx.level, ctx.stats, ctx.target, level=ctx.level
    )
    if per_hit <= 0:
        return None

    entry = on_hit_entry(ability_name(ability), per_hit, "magic")
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


@ranked_slot
def _primal_howl(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
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

    return damage_reduction_window(
        ctx,
        ability,
        rank,
        duration_source=_E_REDUCTION_SOURCE,
        # A modifier names its classes; this kit's cache names no
        # excluded type, so the full enum IS the declaration, never an
        # empty one, and never Alistar's narrowed pair, which his own
        # cached note sources and this one does not.
        damage_classes=frozenset(DamageClass),
        detail=lambda percent, duration: (
            f"Primal Howl reduces incoming damage by {percent:g}% for "
            f"{duration:g}s (the automatic recast ends it at the duration; a "
            "manual recast — and its fear plus 90% slow — is not modeled)"
        ),
    )


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
MODULE_CC = {
    "Q": "none",
    "R": "suppression",
    "P": "none",
    "W": "none",
    "E": CC_PER_PART,
}

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
        "rotation": {"role": "self_state", "slot": "P"},
    }
)
OPTIONS.append(
    {
        "key": TARGET_MISSING_HP_OPTION,
        "type": "int",
        "default": 50,
        "min": 0,
        "max": 100,
        "label": "Target missing health % (Blood Hunt doubles above 75%)",
        "rotation": {
            "role": "execute",
            "slot": "W",
            "condition": "execute",
            "kind": "execute",
        },
    }
)

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "R (Infinite Duress) prices the wiki Total Magic Damage, 175/350/525 + 167% bonus "
    "AD by rank.",
    "It is one cast over the 1.5-second suppress channel.",
    "The 100%-of-R-damage self-heal rule fires on the R damage event.",
    "The channel's 0.25s ticks and its 3 on-hit applications are documented cadence.",
    "Item on-hits are not multiplied: the cache publishes no per-tick row.",
    "P (Eternal Hunger) is an on-hit rider on every basic attack, the cached "
    "per-level row.",
    "That is 6 to 60.76 + 15% bonus AD + 10% AP magic.",
    "It is an on-hit itself, so item on-hits proc from the swing it rides, not from "
    "it.",
    "Its self-heal is 100% of post-mitigation damage below 50% maximum health, 250% "
    "below 25%.",
    "That is cached prose gated on p_self_health_percent (default 100%): a healthy "
    "Warwick heals nothing.",
    "W (Blood Hunt) grants the sourced 70 to 110% by rank Bonus Attack Speed for the "
    "whole fight.",
    "The active marks the target 'regardless of their current health', so the base "
    "tier is unconditional.",
    "The doubled row, 140 to 220%, applies when target_missing_hp_pct exceeds 75.",
    "W's bonus movement speed and its 8-second mark are not modeled: stat_buff has no "
    "movement key.",
    "E (Primal Howl) is a zero-damage self-state window: the ranked Damage Reduction "
    "row 35/40/45/50/55%.",
    "The required_ranked_attribute_atom prices the multiplier.",
    "The prose 'for up to 2.75 seconds' (timing.active_duration atom) prices the "
    "window.",
    "It arms through self_state_events kind=damage_modifier, the Briar-E and "
    "Alistar-R precedent.",
    "Every DamageClass is declared: the cached E description and notes name no "
    "excluded type.",
    "Narrowing the set would be the invented reading rather than E's conservative "
    "one, an Alistar-R call.",
    "The window priced is the automatic recast's: the cache says it 'does so "
    "automatically'.",
    "A manual recast, legal after 1 second, shortening it is not modeled.",
    "Neither is that recast's 1-second fear or its 90% slow, control on a recast "
    "never issued.",
]
# No MODULE_COVERAGE: with E closed, every slot this module emits is
# ``modeled``, which is exactly what ``default_coverage`` derives from
# SLOTS — and the contract refuses a declaration that only restates it.


def derive_self_healing(ctx: SelfHealCtx) -> list[dict[str, Any]]:
    """Resolve Warwick self-healing events from its authored packet."""
    healing = []
    q = _healing.ability_json(ctx.champion_data, "Q")
    q_rank = _healing.parsed_rank(ctx.ability_damages, "Q")
    q_ratio = extract_named(q, "Healing Percentage", q_rank, ctx.champion_stats, {})
    for event in ctx.damage_events:
        source = _healing.ledger_source_key(event)
        if source == "Q":
            _healing.heal_from_damage(
                healing,
                event,
                _row_damage(event) * q_ratio / 100.0,
                "Jaws of the Beast",
            )
        elif source == "R":
            # Infinite Duress explicitly heals for 100% of all
            # post-mitigation damage dealt to its target.
            _healing.heal_from_damage(
                healing, event, _row_damage(event), "Infinite Duress"
            )
    # Eternal Hunger (P): "While below 50% maximum health, Warwick also
    # heals for 100% of the post-mitigation damage dealt by Eternal Hunger,
    # increased to 250% while below 25% maximum health" (cached P
    # description).  Warwick's own health is module state, so ``_eternal_hunger``
    # owns the threshold and publishes the resulting share on its P entry;
    # this pays that share of every on-hit event the passive authored.  A
    # healthy Warwick publishes 0 and heals none.
    # Warwick's own _eternal_hunger always publishes the share (0.0 when
    # healthy), but the shared healing harness also routes synthetic
    # payloads through this function — an explicit membership check keeps
    # the distinction honest: absence means "not Warwick's P payload",
    # never a silently-defaulted number.
    _p_payload = ability_payload(ctx.ability_damages, "passive")
    if "self_heal_share_of_damage" in _p_payload:
        hunger_share = float(_p_payload["self_heal_share_of_damage"])
    else:
        hunger_share = 0.0
    if hunger_share > 0.0:
        for payment in ctx.payments(
            _healing.HealAnchor.DAMAGING_HIT, "on_hit_ability_passive"
        ):
            event = payment.event
            _healing.heal_from_damage(
                healing,
                event,
                _row_damage(event) * hunger_share,
                "Eternal Hunger",
            )
    return healing


SELF_HEALING_RULE = self_healing_rule("Warwick")(derive_self_healing)
