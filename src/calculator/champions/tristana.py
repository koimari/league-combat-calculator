"""Tristana — slot map for the archetype engine (E3 stack systems).

Why each slot is non-generic:
- E (Explosive Charge) is the stack system: the charge attaches to the
  target and each of Tristana's basic attacks / abilities against it
  increases the detonation damage by 25%, stacking up to 4 times (100%)
  and detonating instantly at max stacks. The detonation is priced from
  the ``e_stacks`` option (default 4 = the sourced max): "Minimum
  Physical Damage" (the 0-stack base) plus ``e_stacks`` x "Bonus Damage
  Per Stack" — at 4 stacks this equals the wiki's "Full Stack Physical
  Damage" row at every rank. The charge detonates once per cast.
- Q (Rapid Fire) is the attack-speed steroid, and for a marksman whose
  output is basic attacks it is the biggest number in the kit: the
  "Bonus Attack Speed" row (60-120%) rides a BUFF-phase ``stat_buff`` so
  the fight engine's auto count scales with it.  It is published with a
  sourced WINDOW rather than a fight-averaged magnitude — see below.
- P (Draw a Bead) is attack range only: an emitted zero-damage row.
- W (Rocket Jump) and R (Buster Shot) are plain attribute reads; W's
  takedown/max-stack-detonation reset is CC/state only, and R's
  knockback/stun is CC only.

Roadmap session 5 batch L (2026-08-21): Q's magnitude and window both
move onto typed ability atoms, and the window is published to the engine
instead of being averaged into the magnitude.

  Both roots are typed atoms — ``ability.bonus _attack _speed``
  (60/75/90/105/120% by rank) and ``timing.active_duration`` (7.0s) — and
  the game binary agrees (``TristanaQ`` ``AttackSpeedMod``
  [.45 .60 .75 .90 1.05 1.20 1.35]; Riot spell DataValues are
  rank-0-indexed, so ranks 1-5 are indices 1..5 = 60/75/90/105/120%, with
  ``BuffDuration`` 7.0 flat at every rank index).  Nothing here is a
  literal, so a degraded cache raises instead of zeroing out.

  Why a published window beats ``module_helpers.buff_window_share`` HERE:
  the share helper weights the MAGNITUDE by the fraction of the fight the
  buff covers, which is the only option when the engine cannot place the
  window.  ``damage.py`` CAN place this one — it resolves the window
  start by walking ``state.cast_order`` and breaking on ``"Q"`` — and
  Rapid Fire IS the Q cast, so [0, 7) is its real window.  The engine
  then splits the fight into pre-window / in-window / post-window auto
  counts at the full magnitude, which is the exact answer rather than a
  fight-averaged one.  (The Miss Fortune W / Teemo P boundary, from the
  other side: a steroid stuck in a non-Q slot has no placeable window and
  keeps the share helper.)

  The override carries ``active_duration`` and NOTHING else on purpose.
  ``ad_ratio`` defaults to 1.0 and the per-swing ``swing_window_ratio``
  that consumes it is read only inside the ``crit_as_bonus`` branch
  (Ashe's flurry), so a bare window changes the auto COUNT and never the
  per-swing formula — which is exactly what Rapid Fire does.

  P (Draw a Bead) closes as ``no_damage``.  Its whole payload is bonus
  attack RANGE (0 : 167.65 by level, atom ``ability.per-_level
  _scaling``); ``damageType`` is ``None`` and the slot has no timing or
  damage atom at all.  Attack range is inert in this model — ``is_melee``
  is a static champion stat, never derived from range — so unlike an
  unmodeled attack-speed steroid nothing about it would change damage if
  it were modeled.  That is the settled ``no_damage`` shape, not an
  ``out_of_scope`` receipt (the Olaf-R / Sivir-R rule).
"""

from typing import Any

from ..ability_atoms import (
    AbilityAtomQuery,
    ranked_ability_atom_value,
    required_ability_atom,
    required_ranked_attribute_atom,
)
from ..ability_spec import DamagePart
from ..binary_roots import data_value, spell_object
from .engine import BUFF, SlotCtx, build_parser
from .inputs import int_option
from .module_contract import coverage
from .module_helpers import ranked_slot
from .slotlib import (
    STEROID_ZERO,
    ability_name,
    damage_entry,
    extract_cooldown,
    extract_named,
    simple_damage,
    with_control,
)
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


@ranked_slot
def _explosive_charge(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """E: the detonation — base + e_stacks x per-stack bonus."""

    stacks = min(_E_MAX_STACKS, max(0, int(ctx.options.get("e_stacks", _E_MAX_STACKS))))
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
    entry["parts"] = (DamagePart("physical", total),)
    # One detonation, one blow ("The charge then detonates, dealing
    # physical damage to nearby enemies").
    entry["event_order_certified"] = "single_hit"
    entry["detail"] = (
        f"{stacks}/4 stack(s); "
        f"base {base:.2f} + {stacks} x {per_stack:.2f} per-stack bonus"
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


def _draw_a_bead(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: bonus attack RANGE — a sourced zero-enemy-damage row.

    Range is inert in this model (``is_melee`` is a static champion stat,
    never derived from attack range), so nothing about the slot would
    change damage if it were modeled: ``no_damage``, not a receipted
    ``out_of_scope`` opening.  The magnitude still rides its typed atom,
    so the row names a sourced number instead of a bare disclaimer.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    champion_data = {"name": ctx.champion_name, "abilities": ctx.abilities}
    bonus_range, _range_atom = required_ranked_attribute_atom(
        "Tristana", champion_data, "P", "Per-Level Scaling", ctx.level
    )
    return {
        "name": ability_name(ability),
        "rank": ctx.level,
        "cooldown": 0.0,
        "damage_type": "physical",
        "total_raw": 0.0,
        "parts": (),
        "detail": (
            f"Innate: +{bonus_range:g} bonus attack range at level "
            f"{ctx.level} (0 : 167.65 by level) on basic attacks, Explosive "
            "Charge and Buster Shot. Range is positioning state with no "
            "damage instance and no damage channel in this model."
        ),
    }


OPTIONS: list[dict[str, Any]] = [
    int_option(
        "e_stacks",
        _E_MAX_STACKS,
        minimum=0,
        maximum=_E_MAX_STACKS,
        label="Explosive Charge stacks when it detonates "
        "(4 = max 100% increase, instant detonation)",
    ),
]

ASSUMPTIONS = [
    "E (Explosive Charge) detonates once per cast with e_stacks stacks "
    "(default 4 = the sourced max): Minimum Physical Damage + stacks x "
    "Bonus Damage Per Stack, equal to the wiki's Full Stack Physical "
    "Damage row at 4 stacks",
    "The auto-attack rate that adds stacks in a real fight is not "
    "modeled — the stack count is the option; the fight's own autos "
    "still deal their base AD damage",
    "The charge's 0-40% (+0-12%) crit-chance bonus to its total damage "
    "is not modeled (no crit in the no-items reference)",
    "Q (Rapid Fire) is a modeled zero-damage buff: the sourced "
    "60/75/90/105/120% bonus attack speed (atom ability.bonus _attack "
    "_speed; binary TristanaQ AttackSpeedMod agrees) is published as a "
    "stat_buff with the sourced 7-second window (atom "
    "timing.active_duration; binary BuffDuration 7.0 flat), so the "
    "fight's auto count splits into pre-window / in-window / post-window "
    "at the Q cast rather than carrying a fight-averaged magnitude. The "
    "override carries the window only — no ad_ratio and no crit "
    "conversion — so the per-swing formula is untouched",
    "P (Draw a Bead) is bonus attack RANGE only (0 : 167.65 by level): a "
    "sourced zero-damage row (MODULE_COVERAGE: no_damage). Range is inert "
    "in this model — is_melee is a static champion stat, never derived "
    "from attack range — so no damage channel is left unmodeled",
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
MODULE_CC = {"W": "slow", "E": "none", "R": "immobilize"}

parse_abilities = build_parser(SLOTS, "Tristana", cc_kinds=MODULE_CC)

# P is emitted and grants nothing the engine prices (attack range), which
# is what ``no_damage`` states; Q now carries a priced stat_buff row.
MODULE_COVERAGE = coverage(no_damage="P")

SOURCES = load_champion_sources("Tristana")
