"""Tristana: slot map for the archetype engine.

E (Explosive Charge) is the stack system: the charge attaches and every
attack or ability against the target adds 25%, up to four stacks.  The
detonation is priced from ``e_stacks`` (default 4, the sourced max) as
"Minimum Physical Damage" plus ``e_stacks`` x "Bonus Damage Per Stack",
which at four stacks equals the cached "Full Stack Physical Damage" row.
It detonates once per cast.
Q (Rapid Fire) is the attack-speed steroid and the kit's biggest number.
Its 60 to 120% rides a BUFF-phase ``stat_buff`` with a published window
rather than a fight-averaged magnitude, because Rapid Fire is the Q cast
and the engine places a window at the granting row's first cast, making
[0, 7) exact.  The override carries ``active_duration`` and nothing
else: a bare window moves the auto count, never the per-swing formula.
P (Draw a Bead) is ``no_damage``, bonus attack range only.  Range is
inert in this model, since ``is_melee`` is a static champion stat and is
never derived from range.
W (Rocket Jump) and R (Buster Shot) are plain attribute reads; W's
detonation reset is state and R's knockback is control.
"""

import re
from typing import Any

from ..ability_atoms import (
    AbilityAtomQuery,
    ranked_ability_atom_value,
    required_ability_atom,
    required_ranked_attribute_atom,
)
from ..ability_prose import CachedSentence
from ..ability_spec import DamagePart
from ..binary_roots import data_value, spell_object
from .contract_vocabulary import coverage
from .engine import BUFF, SlotCtx, build_parser
from .inputs import int_option
from .module_helpers import ability_slot, ranked_slot
from .slot_control import with_control
from .slot_entries import STEROID_ZERO, damage_entry
from .slot_extract import ability_name, extract_cooldown, extract_named
from .slotlib import simple_damage
from .source_receipts import load_champion_sources

# HARDCODED: verify on patch updates — the 4-stack cap is wiki prose
# ("stacking up to 4 times for a maximum 100% increase"); the damage
# rows themselves are read from the JSON.
_E_MAX_STACKS = int(
    data_value(spell_object("Tristana", "TristanaE"), "ActiveMaxStacks")
)

# Rapid Fire's window is NOT a literal: it is the typed
# ``timing.active_duration`` atom, selected by this exact source path.
_Q_DURATION_SOURCE = "Tristana.Q[0].effects[0].description"


# How long the charge holds, from E's own cached sentence.
_CHARGE_SECONDS = CachedSentence(
    re.compile(r"attaches to them for (?P<value>\d+(?:\.\d+)?) seconds"),
    missing=(
        "Tristana E: the cached entry no longer states how long the charge "
        "holds ('attaches to them for N seconds')"
    ),
)


@ranked_slot
def _explosive_charge(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """E: the detonation — base + e_stacks x per-stack bonus."""

    requested = ctx.options.get("e_stacks")
    stacks = (
        min(_E_MAX_STACKS, max(0, int(requested)))
        if requested is not None
        else _E_MAX_STACKS
    )
    base = extract_named(
        ability, "Minimum Physical Damage", rank, ctx.stats, ctx.target
    )
    per_stack = extract_named(
        ability, "Bonus Damage Per Stack", rank, ctx.stats, ctx.target
    )
    total = base + per_stack * stacks
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        total,
        "physical",
    )
    if requested is None:
        # The charge attaches on the cast and every attack or ability hit
        # against the target while it holds adds a stack, so the level at
        # detonation is the fight's to count (champions/armed_procs.py).
        # The part reprices against the level the walk collected for THIS
        # cast; the declared total above is what a clockless parse reads.
        entry["parts"] = (
            DamagePart(
                "physical",
                total,
                stack_scaled_damage=lambda level: base + per_stack * level,
            ),
        )
        entry["stack_window"] = {
            "arming_slots": (),
            "max_stacks": _E_MAX_STACKS,
            "hits_required": _E_MAX_STACKS,
            "stacks_from_swings": True,
            "stacks_from_ability_hits": True,
            "stack_seconds": _CHARGE_SECONDS.value(ability),
            "collects_after_cast": True,
            "armed_at_start": False,
            "requested": False,
        }
    else:
        entry["parts"] = (DamagePart("physical", total),)
    # One detonation, one blow ("The charge then detonates, dealing
    # physical damage to nearby enemies").
    entry["event_order_certified"] = "single_hit"
    entry["detail"] = (
        (
            f"base {base:.2f} + {per_stack:.2f} per stack, up to "
            f"{_E_MAX_STACKS}: the fight counts the attacks and ability hits "
            "that land while the charge holds"
        )
        if requested is None
        else (
            f"{stacks}/{_E_MAX_STACKS} stack(s); base {base:.2f} + "
            f"{stacks} x {per_stack:.2f} per-stack bonus"
        )
    )
    return entry


@ranked_slot
def _rapid_fire(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """Q: the sourced 7-second attack-speed window (no enemy damage).

    Both numbers ride typed ability atoms and fail closed when the cache
    degrades: the rank magnitude through
    :func:`required_ranked_attribute_atom` and the window through
    :func:`required_ability_atom`.  Nothing here is a literal.
    """

    champion_data = {"name": ctx.champion_name, "abilities": ctx.abilities}
    bonus_as_pct, _as_atom = required_ranked_attribute_atom(
        "Tristana", champion_data, "Q", "Bonus Attack Speed", rank
    )
    duration_atom = required_ability_atom(
        "Tristana",
        champion_data,
        "Q",
        query=AbilityAtomQuery(
            source=_Q_DURATION_SOURCE,
            behavior="timing",
            evidence_prefix="active duration@",
        ),
    )
    if duration_atom.get("units") != ["s"]:
        raise ValueError("Tristana Q active-duration atom must use seconds")
    window = ranked_ability_atom_value(duration_atom, 1, source=_Q_DURATION_SOURCE)

    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        0.0,
        "physical",
        zero_policy=STEROID_ZERO,
    )
    entry["stat_buff"] = {"bonus_attack_speed": bonus_as_pct}
    # A BARE window: no ad_ratio and no crit_as_bonus, so only the auto
    # COUNT moves (the per-swing ratio is crit_as_bonus-only).
    entry["auto_attack_override"] = {"active_duration": window}
    entry["detail"] = (
        f"Self buff, no enemy damage: +{bonus_as_pct:g}% bonus attack "
        f"speed for {window:g}s from the Q cast. The autos ride the base "
        "rate before the cast, the buffed rate inside the window, and the "
        "base rate again after it."
    )
    return entry


_rapid_fire.phase = BUFF


@ability_slot()
def _draw_a_bead(ctx: SlotCtx, ability: dict[str, Any]) -> dict[str, Any] | None:
    """P: bonus attack RANGE — a sourced zero-enemy-damage row.

    Range is inert in this model (``is_melee`` is a static champion stat,
    never derived from attack range), so nothing about the slot would
    change damage if it were modeled: ``no_damage``, not a receipted
    ``out_of_scope`` opening.  The magnitude still rides its typed atom,
    so the row names a sourced number instead of a bare disclaimer.
    """
    champion_data = {"name": ctx.champion_name, "abilities": ctx.abilities}
    bonus_range, _range_atom = required_ranked_attribute_atom(
        "Tristana", champion_data, "P", "Per-Level Scaling", ctx.level
    )
    return damage_entry(
        ability_name(ability),
        ctx.level,
        0.0,
        0.0,
        "physical",
        parts=(),
        detail=(
            f"Innate: +{bonus_range:g} bonus attack range at level "
            f"{ctx.level} (0 : 167.65 by level) on basic attacks, Explosive "
            "Charge and Buster Shot. Range is positioning state with no "
            "damage instance and no damage channel in this model."
        ),
    )


OPTIONS: list[dict[str, Any]] = [
    int_option(
        "e_stacks",
        _E_MAX_STACKS,
        minimum=0,
        maximum=_E_MAX_STACKS,
        label=(
            "Explosive Charge stacks at detonation; unset derives them from "
            "the attacks and ability hits that land while the charge holds"
        ),
        derives=True,
        rotation={"role": "self_state", "slot": "E"},
    ),
]

ASSUMPTIONS = [
    "E (Explosive Charge) detonates once per cast at e_stacks (default 4, the sourced "
    "max).",
    "It prices Minimum Physical Damage + stacks x Bonus Damage Per Stack.",
    "At 4 stacks that equals the wiki's Full Stack Physical Damage row.",
    "The auto-attack rate that adds stacks in a real fight is not modeled: the count "
    "is the option.",
    "The fight's own autos still deal their base AD damage.",
    "The charge's 0-40% (+0-12%) crit-chance bonus to its total damage "
    "is not modeled (no crit in the no-items reference)",
    "Q (Rapid Fire) is a modeled zero-damage buff: the sourced 60/75/90/105/120% "
    "bonus attack speed.",
    "The atom is ability.bonus_attack_speed and the binary's TristanaQ AttackSpeedMod "
    "agrees.",
    "It publishes as a stat_buff over the sourced 7-second window (binary "
    "BuffDuration 7.0 flat).",
    "The auto count splits pre-window, in-window and post-window at the Q cast, not "
    "fight-averaged.",
    "The override carries the window only, no ad_ratio and no crit conversion, so the "
    "formula is untouched.",
    "P (Draw a Bead) is bonus attack range only, 0 to 167.65 by level: a sourced "
    "zero-damage row.",
    "Range is inert here, since is_melee is a static champion stat, never derived "
    "from attack range.",
    "So no damage channel is left unmodeled.",
    "W's takedown/max-stack reset and R's knockback/stun are " "CC/state only",
]

SLOTS = {
    "Q": _rapid_fire,
    # One landing and one cannonball: each row is one blow the ledger can
    # time, which is what carries its MODULE_CC answer.
    "W": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
    "E": _explosive_charge,
    # The interval the target cannot act is the cached "Stun Duration"
    # row (0.4/0.55/0.7s); the knock-back's own row is a DISTANCE, not a
    # time, so the reviewed un-narrowed kind takes the sourced duration.
    "R": with_control(
        simple_damage(
            attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
        ),
        duration_attr="Stun Duration",
    ),
    "P": _draw_a_bead,
}

# Reviewed crowd control, read from the cached kit.  W (Rocket Jump):
# "Upon landing, she deals magic damage to nearby enemies and slows them
# by 40% for 2 seconds".  E (Explosive Charge) detonates "dealing physical
# damage to nearby enemies" and applies none.  R (Buster Shot) deals its
# damage and the targets "are also knocked back and stunned for a
# duration" — two immobilize kinds, so the reviewed answer is the
# un-narrowed one.  Q and P deal no damage.
MODULE_CC = {"W": "slow", "E": "none", "R": "immobilize", "P": "none", "Q": "none"}

parse_abilities = build_parser(SLOTS, "Tristana", cc_kinds=MODULE_CC)

# P is emitted and grants nothing the engine prices (attack range), which
# is what ``no_damage`` states; Q now carries a priced stat_buff row.
MODULE_COVERAGE = coverage(no_damage="P")

SOURCES = load_champion_sources("Tristana")
