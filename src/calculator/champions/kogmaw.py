"""Kog'Maw: slot map for the archetype engine.

Q (Caustic Spittle) is a DEBUFF-phase slot: magic damage plus a bonus
attack-speed ``stat_buff`` and a percentage resistance shred emitted as a
``target_debuff`` under ``q_shred``.  The parse-time target context is left
unmutated because no parse-time scaling reads target resistances, and the
DEBUFF stamp is what guarantees the slot runs before every damage slot.
W (Bio-Arcane Barrage) is a pure on-hit buff under ``w_active``: a percent of
the target's maximum health as magic per auto, plus a further percent per 100
AP.  The emitted shape is a castable shell around the on-hit dict.
E (Void Ooze) is a plain "Magic Damage" read.
R (Living Artillery) reads "Minimum Magic Damage" and carries the wiki's
missing-health curve as an ``hp_scaled_damage`` closure, rising by half up to
60% missing health and doubling past it, which the engine re-evaluates per shot
against the target's falling health.
P (Icathian Surprise) fires only after Kog'Maw takes FATAL damage, which this
deterministic duel never reaches, so the slot prices zero and reports the
sourced explosion magnitude in its row detail.
"""

from collections.abc import Callable
from typing import Any

from ..ability_spec import DamagePart
from ..binary_roots import data_value, spell_object
from .engine import DEBUFF, SlotCtx, build_parser
from .inputs import bool_option
from .module_helpers import ranked_slot
from .shared_mechanics import unreachable_innate
from .slot_entries import ability_on_hit_entry, damage_entry
from .slot_extract import (
    ability_name,
    extract_cooldown,
    extract_named,
    extract_value,
    pct_health_per_hit,
)
from .slotlib import simple_damage
from .source_receipts import load_champion_sources

# Caustic Spittle's shred lasts 4s ("reduces their armor and magic
# resistance for 4 seconds") — it is not permanent.
Q_SHRED_DURATION = data_value(spell_object("Kog'Maw", "KogMawQ"), "ShredDuration")


@ranked_slot
def _caustic_spittle(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """Q: magic damage + bonus-AS stat buff + resistance shred debuff."""

    damage = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        damage,
        "magic",
        # One wad, first enemy hit, no travel row in the cached packet: the
        # cast boundary is the hit, which is what carries MODULE_CC's
        # reviewed answer for Q into the event ledger.
        event_order_certified="single_hit",
        parts=(DamagePart("magic", damage),),
    )

    # Passive bonus attack speed: the fight engine recalculates auto
    # attacks from the stat_buff.
    bonus_as = extract_value(ability, "Bonus Attack Speed", rank)
    if bonus_as > 0:
        entry["stat_buff"] = {"bonus_attack_speed": bonus_as}
        # "Passive: Kog'Maw gains bonus attack speed" (cached Q effect 0):
        # ranking Q buys it, casting Q does not, so autos-only keeps it.
        entry["innate_grant"] = True

    # Resistance shred: damage.py reduces target armor and MR by this
    # percentage before all other damage calculations.
    shred = extract_value(ability, "Resistances Reduction", rank)
    if ctx.option("q_shred") and shred > 0:
        entry["target_debuff"] = {
            "armor_reduction_percent": shred,
            "mr_reduction_percent": shred,
            "duration": Q_SHRED_DURATION,
        }
    return entry


_caustic_spittle.phase = DEBUFF


def _bio_arcane_barrage(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: on-hit %maxHP magic damage in a castable shell."""
    if not ctx.option("w_active"):
        return None
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked

    per_hit = pct_health_per_hit(
        ability,
        "Bonus Magic Damage",
        rank,
        ctx.target,
        ap=ctx.stat("ability_power"),
        ap_ratio_per_100=True,
    )
    if per_hit is None:
        return None

    name = ability_name(ability)
    return ability_on_hit_entry(
        name,
        rank,
        "magic",
        {
            "name": f"{name} (on-hit)",
            "damage_per_hit": per_hit,
            "damage_type": "magic",
        },
        cooldown=extract_cooldown(ability, rank),
    )


def _icathian_surprise_detail(ctx: SlotCtx, would_be: float) -> str:
    """The published boundary text, quoting the explosion this fight never sees."""

    return (
        "Death-only trigger: after taking fatal damage, Kog'Maw enters a "
        "4-second zombie state then explodes for the sourced "
        f"{would_be:g} true damage (cached 'Bonus True Damage' at champion "
        f"level {ctx.level}) to nearby enemies. The deterministic "
        "alive-state fight cannot enter (the main never dies in the "
        "model); priced at zero damage as a documented boundary."
    )


def _icathian_surprise(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: the death-only explosion this fight never reaches (module docstring)."""

    return unreachable_innate(
        ctx,
        row="Bonus True Damage",
        dmg_type="true",
        detail=_icathian_surprise_detail,
    )


_living_artillery_base = simple_damage(attr="Minimum Magic Damage", dmg_type="magic")


def _living_artillery_scaled(base: float) -> Callable[[float], float]:
    """R missing-HP curve: +50% linearly to 60% missing, then +100%."""

    def scaled(missing_ratio: float) -> float:
        if missing_ratio >= 0.6:
            return base * 2.0
        return base * (1.0 + 0.5 * (missing_ratio / 0.6))

    return scaled


def _living_artillery(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: minimum-damage entry scaled per shot by the missing-HP curve."""
    entry = _living_artillery_base(ctx)
    if entry is not None:
        base = entry["parts"][0].amount
        entry["parts"] = (
            DamagePart("magic", hp_scaled_damage=_living_artillery_scaled(base)),
        )
        entry["event_order_certified"] = "single_hit"
    return entry


OPTIONS = [
    bool_option(
        "q_shred",
        True,
        label="Apply Q Resistance Shred",
        rotation={"role": "self_state", "slot": "Q"},
    ),
    bool_option(
        "w_active",
        True,
        label="W Active (Bio-Arcane Barrage)",
        rotation={"role": "self_state", "slot": "W"},
    ),
]

ASSUMPTIONS = [
    "Q resistance shred applied before all other damage",
    "W (Bio-Arcane Barrage) assumed always active during the fight",
    "R damage scales dynamically with target's decreasing HP",
    "R Living Artillery stacks (cap 9, +40 mana each) raise only mana cost, so the "
    "count is not modeled.",
    "Passive (Icathian Surprise) explodes on death for the sourced 140 to 650 by "
    "level true damage.",
    "The passive's boundary prices zero, since the alive-state fight never kills the "
    "main; detail holds it.",
]

SLOTS = {
    "P": _icathian_surprise,
    "Q": _caustic_spittle,
    "W": _bio_arcane_barrage,
    "E": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
    "R": _living_artillery,
}

# Cached kit review: E's ooze field "slow[s] enemies within the area every
# 0.25 seconds"; Q reduces resistances (not control), W empowers basic
# attacks and R reveals the targets it hits.  P's death-boundary row
# prices nothing and authors no part, so it declares no kind.
MODULE_CC = {"Q": "none", "E": "slow", "R": "none", "P": "none", "W": "none"}

parse_abilities = build_parser(SLOTS, "Kog'Maw", cc_kinds=MODULE_CC)


SOURCES = load_champion_sources("Kog'Maw")
