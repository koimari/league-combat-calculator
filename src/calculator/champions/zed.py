"""Zed — E5-1 corrected slot map for the archetype engine.

Why each slot is non-generic:

- R (Death Mark) is a damage-storage mechanic, not a flat hit: the wiki
  leveling row is "Physical Damage: 100% AD (+ 25 / 40 / 55% of damage
  stored)".  The previous wiki_attribute read resolved only the first
  modifier (100% AD) and silently dropped the stored-damage term (the
  "% of damage stored" unit is not a stat scaling), pricing the mark as
  a flat ~AD hit.  The corrected packet reads BOTH modifiers: the mark
  detonates for 100% AD plus 25 / 40 / 55% of the pre-mitigation damage
  Zed dealt to the target during the mark.  The fight model's one
  rotation prices the stored pool as the pre-mitigation raw spell damage
  of the kit's damaging abilities (Q + E, read from ``ctx.results``);
  basic attacks and Shadow copies are not tracked in the ability parse.
  The detonation lands 3 seconds after the cast ("renders the target
  Marked for Death for 3 seconds ... detonating at the end of the
  duration").
- Q (Razor Shuriken) prices one enemy-champion hit (80 / 120 / 160 /
  200 / 240 + 100% bonus AD); the 60%-reduced second-target branch is
  not the single-target model.
- E (Shadow Slash) is a plain "Physical Damage" read (70 / 92.5 / 115 /
  137.5 / 160 + 70% bonus AD).
- P (Contempt for the Weak) and W (Living Shadow) are explicit
  no-damage slots.

All numeric values are read from the champion JSON data; nothing is
hardcoded.
"""

from typing import Any

from ..ability_spec import DamagePart
from ..binary_roots import data_value, spell_object
from ..cast_dependency import CastDependency
from .engine import SlotCtx, build_parser
from .module_contract import coverage
from .module_helpers import no_damage_parser, ranked_slot
from .slotlib import (
    ability_name,
    extract_cooldown,
    extract_value,
    simple_damage,
)
from .source_receipts import load_champion_sources

# Death Mark detonates at the binary RDeathMarkDuration; the wiki prose
# corroborates ("renders the target Marked for Death for 3 seconds",
# "detonating at the end of the duration").
_ZED_R_SPELL = spell_object("Zed", "ZedR")
_DEATH_MARK_DETONATION_DELAY = data_value(_ZED_R_SPELL, "RDeathMarkDuration")


@ranked_slot
def _death_mark(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """R: 100% AD + 25/40/55% of the mark's stored pre-mitigation damage."""

    # Leveling row "Physical Damage": modifier 0 = 100 (% AD), modifier 1
    # = 25 / 40 / 55 (% of damage stored).  Read each modifier's raw value
    # directly; the "% AD" unit resolves 100 -> 1.0 x total AD, while
    # "% of damage stored" has no stat the scaling layer can resolve.
    ad_percent = extract_value(ability, "Physical Damage", rank, 0)
    stored_percent = extract_value(ability, "Physical Damage", rank, 1)
    ad_damage = (ad_percent / 100.0) * float(ctx.stat("attack_damage"))

    # The stored pool: pre-mitigation raw spell damage the fight rotation
    # prices for the kit's damaging abilities (Q + E).  R is evaluated
    # after Q/E in the slot map, so their entries are already in
    # ``ctx.results`` (the engine guarantees cross-slot reads within a
    # phase for later-listed slots).
    stored_pool = 0.0
    for slot in ("Q", "E"):
        entry = ctx.results.get(slot)
        if isinstance(entry, dict):
            stored_pool += float(entry.get("total_raw", 0.0) or 0.0)
    stored_damage = (stored_percent / 100.0) * stored_pool

    total = ad_damage + stored_damage
    return {
        "name": ability_name(ability),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "physical",
        "total_raw": total,
        "parts": (
            DamagePart(
                "physical",
                total,
                time_offset=_DEATH_MARK_DETONATION_DELAY,
            ),
        ),
        "detail": (
            f"100% AD ({ad_damage:.2f}) + {stored_percent:g}% of stored "
            f"pre-mitigation spell damage ({stored_damage:.2f}); detonates "
            "3s after the mark"
        ),
    }


ASSUMPTIONS = [
    "R (Death Mark) stores the fight rotation's pre-mitigation spell "
    "damage (Q + E raw totals); basic attacks and Shadow copies are not "
    "tracked in the ability parse, so they are excluded from the stored "
    "pool.",
    "The mark detonates 3 seconds after cast ('Marked for Death for 3 "
    "seconds ... detonating at the end of the duration').",
    "Q prices one enemy-champion hit; the 60%-reduced beyond-first-target "
    "branch is not the single-target model.",
    "P and W deal no enemy damage and are explicit no-damage slots.",
]

SOURCES = load_champion_sources("Zed")

SLOTS = {
    "P": no_damage_parser(
        "P",
        "Contempt for the Weak is a % max-HP on-hit rider on basic attacks; "
        "no separate enemy-damage formula is priced for the passive slot.",
    ),
    # One shuriken, one slash — neither packet has a travel or tick phase
    # to place, which is what carries the cast into the event ledger.
    "Q": simple_damage(
        attr="Physical Damage",
        dmg_type="physical",
        event_order_certified="single_hit",
    ),
    "W": no_damage_parser(
        "W",
        "Living Shadow is a shadow/utility placement; no enemy damage.",
    ),
    "E": simple_damage(
        attr="Physical Damage",
        dmg_type="physical",
        event_order_certified="single_hit",
    ),
    "R": _death_mark,
}

MODULE_COVERAGE = coverage(no_damage="PW")

OPTIONS: list[dict[str, Any]] = []

# The revision these declarations were read from, in the shape
# scripts/cast_dependency_audit.py will resolve against the committed
# wiki audit once this phase's audit slice lands -- that script is not
# in the tree yet, so today this string is shape-checked and pinned
# equal to SOURCES by test, nothing more. It is the parent entry
# SOURCES publishes.
_WIKI_SOURCE = "https://wiki.leagueoflegends.com/en-us/Zed@4026038"

_SHADOW_MIMICS_Q_AND_E = (
    "Living Shadow's Shadow mimics Razor Shuriken and Shadow Slash "
    "'regardless of range', so the same cast is one instance before the "
    "Shadow is placed and two after it. The Shadow's copies are outside "
    "this module's single-instance pricing, which is why the ordering is "
    "declared rather than priced: the rotation still has to open on the "
    "placement for the kit it models to be the kit Zed casts."
)

# Head only (D-89). W first is the mechanic above; the rest of the seed
# order — E before Q, R last — is a DPS and scheduling preference no
# declaration can honestly express, so the resolver's hand seed keeps it.
# R in particular is deliberately undeclared: Marked for Death stores the
# damage dealt *during* the mark, so the wiki puts R first while this
# module prices it last off Q and E's raw totals with a 3-second
# detonation offset. Neither direction is a dependency both surfaces
# would agree to, and a declaration that contradicts one of them is worse
# than the seed it would retire.
CAST_DEPENDENCIES = (  # sightline-ok: 32 - module_contract reads it by name
    CastDependency(
        slot="Q",
        requires="W",
        kind="damage_enabler",
        reason=_SHADOW_MIMICS_Q_AND_E,
        source=_WIKI_SOURCE,
    ),
    CastDependency(
        slot="E",
        requires="W",
        kind="damage_enabler",
        reason=_SHADOW_MIMICS_Q_AND_E,
        source=_WIKI_SOURCE,
    ),
)

# Razor Shuriken only "deals physical damage to enemies hit"; Shadow Slash
# is "Zed slashes to deal physical damage to nearby enemies" and its slow
# belongs to a different caster — "enemies hit by a *Shadow's* slash are
# slowed for 1.5 seconds", and the Shadow's copies are outside this
# module's single-instance pricing; Death Mark only stores and detonates
# damage.  P is the on-hit execute rider and W is the Shadow placement;
# both are explicit no-damage slots.
MODULE_CC = {"Q": "none", "E": "none", "R": "none"}

parse_abilities = build_parser(SLOTS, "Zed", cc_kinds=MODULE_CC)
