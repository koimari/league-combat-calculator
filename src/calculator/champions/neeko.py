"""Neeko: full-entry-reviewed packet module.

Q (Blooming Burst) re-blooms up to twice per cast, 0.75 seconds apart, whenever
the burst hits a champion, so a single-target cast prices the initial burst plus
two subsequent ones: the cached "Total Maximum Magic Damage" row is exactly that
sum at every rank.
R (Pop Blossom) shields, and the cached page carries no shield row, a
known-degraded parse.  The game files source it, ``NeekoR``'s ``ShieldAmount``
and ``ShieldPerChampion`` with the base and multiplier AP calculations, and in a
duel the fight's own target is the one nearby enemy champion, so the shield is
both terms plus 115% AP for the sourced 2 seconds, riding the R damage event as
a ``self_shield_events`` payload.
P (Inherent Glamour) disguises Neeko as an allied champion or unit.  Vision and
stealth are axes this engine does not have and the disguise carries no
enemy-damage formula, so the slot is ``no_damage``.
"""

from typing import Any

from ..ability_spec import DamagePart
from ..binary_roots import (
    calculation_coefficient,
    data_value,
    data_value_at_rank,
    spell_object,
)
from .contract_vocabulary import coverage
from .engine import SlotCtx
from .module_helpers import named_damage, ranked_slot
from .packet_module import build_packet_module
from .shared_mechanics import with_self_shield
from .slot_control import with_control
from .slot_entries import damage_entry
from .slot_extract import ability_name, extract_cooldown, extract_named

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


@ranked_slot
def _blooming_burst(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """Q: initial burst + up to 2 re-blooms (Total Maximum Magic Damage)."""
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


def _r_shield_rows(ctx: SlotCtx) -> tuple[float, float]:
    """R's flat and per-champion shield rows at the cast's rank."""
    index = min(max(ctx.rank_for("R"), 1), 3) - 1
    return _R_SHIELD_AMOUNT[index], _R_SHIELD_PER_CHAMPION[index]


def _r_shield(ctx: SlotCtx) -> float:
    """R's 2s self-shield: both rows plus the AP share of each."""
    flat, per_champion = _r_shield_rows(ctx)
    ap = float(ctx.stat("ability_power") or 0.0)
    ratio = _R_SHIELD_AP_RATIO + _R_SHIELD_PER_CHAMPION_AP_RATIO
    return flat + per_champion + ap * ratio


def _r_shield_detail(ctx: SlotCtx, _shield: float) -> str:
    """R's published shield row, quoting the game-file rows it sums."""
    flat, per_champion = _r_shield_rows(ctx)
    return (
        f"game-file R shield: {flat:g} + "
        f"{per_champion:g} (1 nearby enemy "
        "champion) + 115% AP for 2s"
    )


# The 1v1 fight's own target is the one nearby enemy champion the shield
# counts, and the burst it rides is R's whole damage.
_pop_blossom = with_self_shield(
    named_damage("Magic Damage", "magic"),
    shield=_r_shield,
    window=_R_SHIELD_DURATION,
    source="Pop Blossom",
    detail=_r_shield_detail,
)


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
MODULE_CC = {"Q": "none", "W": "none", "E": "root", "R": "stun", "P": "none"}

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
    "Q (Blooming Burst) prices Initial + 2 x Subsequent Magic Damage, the cached "
    "Total Maximum row.",
    "Each re-bloom fires because the burst hits a champion, 0.75s apart.",
    "R (Pop Blossom)'s shield comes from the game file: 75/125/175 + 75% AP over 2s.",
    "It adds 40/60/80 + 40% AP per nearby enemy champion; the cached wiki page omits "
    "the shield row.",
    "The 1v1 fight's own target is that one nearby enemy champion.",
    "P (Inherent Glamour) is the disguise passive with no enemy-damage formula in the "
    "pinned packet.",
    "It emits the sourced zero-damage row as no_damage, and P is already a cast slot "
    "here.",
]
MODULE_COVERAGE = coverage(no_damage="P")
