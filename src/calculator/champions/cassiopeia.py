"""Cassiopeia — slot map for the archetype engine.

Why each slot is non-generic:
- Q (Noxious Blast) must read "Total Magic Damage" (the full 3s poison);
  the classifier picks the 7-tick "Magic Damage Per Tick" breakdown.
- W (Miasma) must read "Total Magic Damage" (the full 5s zone); the
  classifier picks "Magic Damage Per Second".
- E (Twin Fang) is champion-local: its unpoisoned base is a PER-LEVEL
  40-entry array (52 + 4/level, valid through the level-20 cap) plus
  10% AP, and the poisoned bonus is a separate rank-scaled leveling
  entry (20-120 + 55% AP) gated by the ``target_poisoned`` option. The
  JSON's pre-summed "Total Enhanced Damage" attribute is deliberately
  avoided — its level component carries only 18 values, so it cannot
  represent levels 19-20; the components are summed here instead.
- R (Petrifying Gaze) pins "Magic Damage" (the classifier happens to
  agree, but the module replaces the whole slot map).
- P (Serpentine Grace) increases movement-speed-bonus effectiveness by a
  percentage — pure stat-effectiveness state with no combat-damage
  interaction anywhere in this calculator (no positioning/MS-to-damage
  kernel). Roadmap session 4 batch B (2026-08-21): closes the single
  out_of_scope slot with an explicit ``no_damage`` row via
  ``module_helpers.no_damage`` (same pattern as Kled's P, Skaarl the
  Cowardly Lizard) rather than leaving MODULE_COVERAGE reading
  "out_of_scope" for an intentionally-unmodeled state passive.
  Cassiopeia is in ``rotation_resolver.COMBO_TABLE``, but its
  ``_CAST_SLOTS = (Q, Q2, W, E, R)`` structurally excludes P from cast
  order — no combo table edit needed.

Both of E's leveling entries are named "Bonus Magic Damage", so
``extract_named`` (first match wins) cannot reach the poisoned bonus —
``_bonus_magic_damage_levelings`` collects both in JSON order.
"""

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from ..ability_atoms import (
    AbilityAtomQuery,
    ranked_ability_atom_value,
    required_ability_atom,
)
from ..binary_roots import data_value_at_rank, spell_object
from .engine import CC_PER_PART, SlotCtx, build_parser
from .inputs import bool_option
from .module_contract import coverage
from .module_helpers import named_damage, no_damage, ranked_slot
from .slotlib import (
    ability_name,
    damage_entry,
    extract_cooldown,
    simple_damage,
    sum_modifiers,
)
from .source_receipts import load_champion_sources


def _bonus_magic_damage_levelings(
    ability: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """E's two "Bonus Magic Damage" entries: (per-level base, poisoned bonus).

    Raises IndexError if the JSON shape changes — a loud failure beats a
    silently unpoisoned Twin Fang.
    """
    matches = [
        leveling
        for effect in ability.get("effects", [])
        for leveling in effect.get("leveling", [])
        if leveling.get("attribute") == "Bonus Magic Damage"
    ]
    return matches[0], matches[1]


@ranked_slot
def _twin_fang(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """E: per-level base + 10% AP; poisoned targets add rank bonus + 55% AP."""

    base_leveling, poison_leveling = _bonus_magic_damage_levelings(ability)
    # Base scales per champion LEVEL: modifier 0 is the 40-entry array
    # (indexed level-1), modifier 1 the 10% AP ratio.
    total = sum_modifiers(base_leveling, ctx.level, ctx.stats, ctx.target)
    if ctx.option("target_poisoned"):
        # Poisoned: + rank-scaled bonus and +55% AP (65% AP total).
        total += sum_modifiers(poison_leveling, rank, ctx.stats, ctx.target)

    return damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
        # One targeted launch, no travel or tick phase in the packet.
        event_order_certified="single_hit",
    )


# Q's poison ticks are the wiki packet's authored 0.429s cadence (seven
# over 3s); W's five ticks are the Total/Per-Second ratio (each tick is
# one second of the per-second row), which is the count the worklist
# sources.  Keeping the ticks explicit lets the coupled fight ledger
# order burns and incoming effects against Cassiopeia's damage instead
# of marking Q/W as aggregate cast-boundary damage.
_CASSIOPEIA_Q_SPELL = spell_object("Cassiopeia", "CassiopeiaQ")
_CASSIOPEIA_W_SPELL = spell_object("Cassiopeia", "CassiopeiaW")
_Q_TICKS = int(data_value_at_rank(_CASSIOPEIA_Q_SPELL, "NumDamageTicks", 1))
_Q_FIRST_TICK = 0.429
_Q_TICK_INTERVAL = 0.429
_Q_DURATION = data_value_at_rank(_CASSIOPEIA_Q_SPELL, "PoisonDuration", 1)
_W_TICKS = 5
_W_DURATION = data_value_at_rank(_CASSIOPEIA_W_SPELL, "CloudDuration", 1)
_W_TICK_INTERVAL = _W_DURATION / _W_TICKS  # "every 1.0 seconds"


# Q: full-poison total across seven sourced ticks (0.429s cadence).
#
# The "Total Magic Damage" row is read directly (75..215 at 0 AP) so
# the priced sum is exact at every rank; the per-tick row (10.71..30.71)
# is its rounded 1/7th, which would drift by ~0.03 per rank.  The seven
# ticks are still emitted as events for the coupled ledger.
_noxious_blast = named_damage(
    "Total Magic Damage",
    "magic",
    ticks=_Q_TICKS,
    time_offset=_Q_FIRST_TICK,
    hit_interval=_Q_TICK_INTERVAL,
    dot_duration=_Q_DURATION,
    detail="7 poison ticks at 0.429s intervals",
)


# W: full-zone total across five sourced per-second ticks.
#
# The "Total Magic Damage" row is exactly five times the "Magic Damage
# Per Second" row at every rank (100/20 .. 200/40), so the zone is
# priced as five per-second ticks over the five-second duration and
# the sum is exact.  (The wiki packet's raw 0.263s cadence would be
# 19 x per-second/4 = 95% of the total — the round-off the worklist
# targets.)
_miasma = named_damage(
    "Total Magic Damage",
    "magic",
    ticks=_W_TICKS,
    time_offset=_W_TICK_INTERVAL,
    hit_interval=_W_TICK_INTERVAL,
    dot_duration=_W_DURATION,
    detail="5 per-second zone ticks over the 5s duration",
)


def _petrifying_gaze(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: damage plus a facing-selected stun or slow state.

    One cone blast, no travel or tick phase in the packet, so the row is
    certified as one landing — which is also what puts it in the event
    ledger where the control marker below can be read.
    """
    parser = simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    )
    entry = parser(ctx)
    if entry is None:
        return None
    source = "Cassiopeia.R[0].effects[0].description"
    atom = required_ability_atom(
        ctx.champion_name,
        {"name": ctx.champion_name, "abilities": ctx.abilities},
        "R",
        query=AbilityAtomQuery(
            source=source,
            behavior="timing",
            evidence_prefix="control duration@",
        ),
    )
    duration = ranked_ability_atom_value(atom, 1, source=source)
    if atom.get("units") != ["s"]:
        raise ValueError("Cassiopeia R control duration atom must use seconds")
    kind = "stun" if bool(ctx.option("r_target_facing")) else "slow"
    part = entry["parts"][0]
    entry["parts"] = (
        replace(
            part,
            cc_kind=kind,
            cc_duration=duration,
            control_source_atoms=(
                *part.control_source_atoms,
                {
                    key: atom[key]
                    for key in (
                        "atom_id",
                        "behavior",
                        "source",
                        "values",
                        "units",
                        "evidence",
                        "hash",
                    )
                },
            ),
        ),
    )
    entry["detail"] = f"Petrifying Gaze facing branch: {kind} for {duration:g}s"
    return entry


OPTIONS: list[dict[str, Any]] = [
    bool_option("target_poisoned", True, label="Target poisoned (E enhanced damage)"),
    bool_option(
        "r_target_facing",
        True,
        label="R target faces Cassiopeia (stun instead of slow)",
    ),
]

ASSUMPTIONS = [
    "Target is poisoned for every Twin Fang cast (toggleable); in a real "
    "rotation Q/W keep poison up near-continuously",
    "W (Miasma) assumes the target remains in the zone for its full "
    "5-second duration",
    "E's healing against poisoned targets is not modeled (damage calculator)",
    "P (Serpentine Grace) increases movement-speed-bonus effectiveness by "
    "6-40% (based on level); it is stat-effectiveness state with no "
    "combat-damage interaction, so it emits a sourced zero-damage row",
    "R's facing condition does not change damage either way; for crowd "
    "control it selects the branch — R applies the sourced stun when the "
    "target faces Cassiopeia ('Enemies with their facing direction "
    "towards her are instead stunned'), which the duel's target engaged "
    "with her is, and the r_target_facing option selects the sourced "
    "slow branch when it faces away.  The duration is read from the "
    "cached R description atom, never a literal",
]

SLOTS = {
    "P": lambda ctx: no_damage(
        ctx,
        name="Serpentine Grace",
        reason=(
            "Movement-speed-bonus effectiveness (6-40% by level) is "
            "stat-effectiveness state; no positioning/MS-to-damage kernel "
            "exists in this calculator."
        ),
    ),
    # Q/W poison ticks are ability damage past the cast, so item burns
    # (Liandry's, Blackfire) stay refreshed for the DoT tail
    # (dot_duration, like Brand's Blaze): Q poisons 3s, W ticks 5s.
    "Q": _noxious_blast,
    "W": _miasma,
    "E": _twin_fang,
    "R": _petrifying_gaze,
}

# Cached kit review.  Q's blast only poisons ("taking magic damage every
# 0.429 seconds"), W's clouds leave enemies "grounded and slowed" — a
# ground is not an immobilizing effect, the slow is the control — and E's
# fangs apply nothing at all; P is Cassiopeia's own movement speed.  R is
# absent because its kind is a property of the cast rather than of the
# slot: the facing branch selects stun or
# slow, so ``_petrifying_gaze`` authors the kind (and its sourced
# duration) on the part itself.
MODULE_CC = {"P": "none", "Q": "none", "W": "slow", "E": "none", "R": CC_PER_PART}

parse_abilities = build_parser(SLOTS, "Cassiopeia", cc_kinds=MODULE_CC)


SOURCES = load_champion_sources("Cassiopeia")

# P is emitted, but its row is a sourced zero — not a fact SLOTS derives.
MODULE_COVERAGE = coverage(no_damage="P")
