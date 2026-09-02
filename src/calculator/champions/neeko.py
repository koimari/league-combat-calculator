"""Neeko — CP10.5 full-entry-reviewed packet module.

P1-3 closures:

- Q (Blooming Burst): the reviewed packet priced only the "Initial Magic
  Damage" hit.  The seed re-blooms "up to 2 times per cast" (0.75s
  apart) whenever the burst hits a champion, so a single-target cast
  prices the initial burst plus 2 subsequent bursts — the wiki's
  "Total Maximum Magic Damage" row (130-530 + 110% AP == initial + 2 x
  subsequent at every rank).

- R (Pop Blossom) shield: the cached wiki page carries no shield row
  (a known-degraded parse), but the game files source it — neeko.bin.json
  NeekoR mSpell DataValues ShieldAmount (75/125/175 by rank) and
  ShieldPerChampion (40/60/80 by rank), with the BaseShield (75% AP) and
  ShieldMultiplier (40% AP) calculations.  In the deterministic 1v1 the
  fight's own target is the one nearby enemy champion, so the shield =
  ShieldAmount + ShieldPerChampion + (75% + 40%) AP for 2 seconds
  (ShieldDuration), riding the R damage event via self_shield_events.

Coverage: P (Inherent Glamour) disguises Neeko as an allied champion or
unit — vision and stealth are axes the engine does not have, and the
disguise carries no enemy-damage formula. The pinned reviewed packet
declares P ``kind: "no_damage"`` with a sourced reason and this module
never overrides P, so the slot already emits the packet's zero-damage
row (``build_packet_module``'s ``no_damage`` branch): MODULE_COVERAGE
reads "no_damage", not "out_of_scope".
"""

from ..ability_spec import DamagePart
from ..binary_roots import (
    calculation_coefficient,
    data_value,
    data_value_at_rank,
    spell_object,
)
from .engine import SlotCtx
from .module_contract import coverage
from .packet_module import build_packet_module
from .slotlib import (
    ability_name,
    attach_self_shield,
    damage_entry,
    extract_cooldown,
    extract_named,
    with_control,
)

PACKET_SHA256 = "ff30f30c58b8eda283a6c9556bf529b98ad0e3b00ae545f8019356d6b7c75acb"

_NEEKO_Q_SPELL = spell_object("Neeko", "NeekoQ")
_Q_BLOOM_DELAY = data_value(_NEEKO_Q_SPELL, "RepeatDelay")


# HARDCODED: verify on patch updates — game-file-sourced R shield rows
# (the cached wiki page omits the shield; neeko.bin.json NeekoR mSpell
# DataValues + mSpellCalculations BaseShield / ShieldMultiplier).
# https://raw.communitydragon.org/latest/game/data/characters/neeko/neeko.bin.json
_NEEKO_R_SPELL = spell_object("Neeko", "NeekoR")
_R_SHIELD_AMOUNT = tuple(
    data_value_at_rank(_NEEKO_R_SPELL, "ShieldAmount", index) for index in (1, 3, 5)
)  # internal DataValue slots by R rank (1-3)
_R_SHIELD_PER_CHAMPION = tuple(
    data_value_at_rank(_NEEKO_R_SPELL, "ShieldPerChampion", rank)
    for rank in range(1, 4)
)  # per nearby enemy champion
_R_SHIELD_AP_RATIO = calculation_coefficient(_NEEKO_R_SPELL, "BaseShield")
_R_SHIELD_PER_CHAMPION_AP_RATIO = calculation_coefficient(
    _NEEKO_R_SPELL, "ShieldMultiplier"
)
_R_SHIELD_DURATION = data_value_at_rank(_NEEKO_R_SPELL, "ShieldDuration", 1)


def _blooming_burst(ctx: SlotCtx):
    """Q: initial burst + up to 2 re-blooms (Total Maximum Magic Damage)."""
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    initial = extract_named(
        ability, "Initial Magic Damage", rank, ctx.stats, ctx.target
    )
    subsequent = extract_named(
        ability, "Subsequent Magic Damage", rank, ctx.stats, ctx.target
    )
    total = initial + 2 * subsequent
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    entry["parts"] = (
        DamagePart("magic", amount=initial, time_offset=0.0),
        DamagePart(
            "magic",
            amount=subsequent,
            count=2,
            time_offset=_Q_BLOOM_DELAY,
            hit_interval=_Q_BLOOM_DELAY,
        ),
    )
    entry["dot_duration"] = 2 * _Q_BLOOM_DELAY
    entry["detail"] = (
        f"initial {initial:g} + 2 re-blooms of {subsequent:g} "
        f"({_Q_BLOOM_DELAY:g}s apart; the burst hits a champion, so both re-blooms fire)"
    )
    return entry


def _pop_blossom(ctx: SlotCtx):
    """R: magic damage + the 2s self-shield (1 nearby enemy champion)."""
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    damage = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        damage,
        "magic",
    )
    shield_rank = min(max(rank, 1), 3) - 1
    ap = float(ctx.stat("ability_power") or 0.0)
    shield = (
        _R_SHIELD_AMOUNT[shield_rank]
        + _R_SHIELD_PER_CHAMPION[shield_rank]
        + ap * (_R_SHIELD_AP_RATIO + _R_SHIELD_PER_CHAMPION_AP_RATIO)
    )
    entry["event_order_certified"] = "single_hit"
    attach_self_shield(
        entry,
        amount=shield,
        duration=_R_SHIELD_DURATION,
        source="Pop Blossom",
        detail=(
            f"game-file R shield: {_R_SHIELD_AMOUNT[shield_rank]:g} + "
            f"{_R_SHIELD_PER_CHAMPION[shield_rank]:g} (1 nearby enemy "
            "champion) + 115% AP for 2s"
        ),
    )
    return entry


# Cached kit review.  Q's seed and re-blooms only "deal magic damage"; W's
# consumed stacks "deal bonus magic damage and grant her bonus movement
# speed".  E's spiral "deals magic damage to enemies hit and roots them for
# a duration".  R is the kit's one two-control cast, but its parts do not
# apply both: the leap knocks up first and deals nothing, and the landing
# burst "deals magic damage to nearby enemies and stuns them" — the stun is
# what the damaging part applies, so it is the kind that rides it.  P is
# absent because Inherent Glamour is a disguise with no damage (its
# "immobilized" wording is about Neeko losing the disguise, not about
# control she applies).
MODULE_CC = {"Q": "none", "W": "none", "E": "root", "R": "stun"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Neeko",
    PACKET_SHA256,
    # Shapesplitter's empowered attack and Tangle-Barbs' spiral each deal
    # their packet once, at the cast — the boundary claim that carries
    # MODULE_CC's reviewed answers into the event ledger.
    single_hit_slots=frozenset({"W", "E"}),
    slot_parsers={
        "Q": _blooming_burst,
        "R": _pop_blossom,
    },
    # Tangle-Barbs carries its sourced root duration onto the spiral's hit.
    slot_wrappers={
        "E": lambda parser: with_control(parser, duration_attr="Root Duration"),
    },
    cc_kinds=MODULE_CC,
)

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "Q (Blooming Burst) prices the full three-burst chain: Initial Magic "
    "Damage + 2 x Subsequent Magic Damage == the wiki's Total Maximum "
    "Magic Damage row (data/champions.json Q); each re-bloom fires "
    "because the burst hits a champion, 0.75s apart.",
    "R (Pop Blossom) shield is priced from the game files (neeko.bin.json "
    "NeekoR: ShieldAmount 75/125/175 + ShieldPerChampion 40/60/80 per "
    "nearby enemy champion + 75% AP + 40% AP, 2s) — the cached wiki page "
    "omits the shield row; the 1v1 fight's own target is the one nearby "
    "enemy champion.",
    "P (Inherent Glamour) is the disguise passive with no enemy-damage "
    "formula in the pinned packet; it emits the sourced zero-damage row "
    "(MODULE_COVERAGE: no_damage, not out_of_scope). P is already a cast "
    "slot in this module (never overridden from build_packet_module's "
    "no_damage branch).",
]
MODULE_COVERAGE = coverage(no_damage="P")
