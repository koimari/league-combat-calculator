"""Kog'Maw — slot map for the archetype engine.

Why each slot is non-generic:
- Q (Caustic Spittle) is a DEBUFF-phase custom fn: magic damage plus a
  bonus-attack-speed ``stat_buff`` and a percentage resistance shred
  emitted as ``target_debuff`` (gated by the ``q_shred`` option,
  default True). damage.py applies both at fight time; the parse-time
  target context is left unmutated because no parse-time scaling reads
  target resistances — the DEBUFF phase stamp documents what the slot
  does and guarantees it runs before every damage slot.
- W (Bio-Arcane Barrage) is a pure on-hit buff (``w_active`` option,
  default True): % of target max health as magic damage per auto, with
  extra % per 100 AP — the shared ``pct_health_per_hit`` math inside a
  custom fn, because the emitted shape is a castable shell
  (rank/cooldown/zero damage keys) around the on-hit dict.
- E (Void Ooze) is a plain "Magic Damage" attribute read.
- R (Living Artillery) is a "Minimum Magic Damage" read whose part
  carries the wiki missing-HP curve as a ``hp_scaled_damage`` closure
  (+50% linearly to 60% missing, then +100%) — the engine re-evaluates
  it per shot against the target's falling HP.
- P (Icathian Surprise) is a self-death trigger: after Kog'Maw takes
  FATAL damage he rides out a 4-second zombie state, then explodes for
  the cached "Bonus True Damage" (140 : 650 over levels 1-18). Roadmap
  session 4 batch C (2026-08-21): closes the single out_of_scope slot
  with an explicit zero-damage boundary receipt (the Karthus P "Death
  Defied" pattern) rather than leaving MODULE_COVERAGE reading
  "out_of_scope" for a death-only trigger this calculator's
  deterministic alive-state 1v1 fight cannot enter (the main never
  dies in the model). The sourced explosion magnitude is computed and
  reported in the row's detail text for traceability, but priced at
  zero damage since the trigger never fires here.

All numeric values are read from the champion JSON data; nothing is
hardcoded.
"""

from typing import Any, Callable

from ..ability_spec import DamagePart
from .engine import DEBUFF, SlotCtx, build_parser
from .slotlib import (
    ability_name,
    ability_on_hit_entry,
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    pct_health_per_hit,
    simple_damage,
)
from .source_receipts import load_champion_sources
from .inputs import bool_option

# Caustic Spittle's shred lasts 4s ("reduces their armor and magic
# resistance for 4 seconds") — it is not permanent.
Q_SHRED_DURATION = 4.0


def _caustic_spittle(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: magic damage + bonus-AS stat buff + resistance shred debuff."""
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked

    damage = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry: dict[str, Any] = {
        "name": ability_name(ability),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "magic",
        "parts": (DamagePart("magic", damage),),
        "total_raw": damage,
        # One wad, first enemy hit, no travel row in the cached packet:
        # the cast boundary is the hit, which is what carries MODULE_CC's
        # reviewed answer for Q into the event ledger.
        "event_order_certified": "single_hit",
    }

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


def _icathian_surprise(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: zero-damage receipt — a death-only trigger outside the fight.

    Icathian Surprise's explosion (cached "Bonus True Damage": 140 : 650
    over levels 1-18) only fires after Kog'Maw takes FATAL damage and
    rides out a 4-second zombie state. The deterministic single-target
    fight has no death event for the main, so the passive contributes
    zero damage here; this receipt documents the boundary — with the
    sourced would-be magnitude — so the alive-state package is complete.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    entry = damage_entry(
        ability_name(ability),
        ctx.level,
        0.0,
        0.0,
        "true",
    )
    entry["parts"] = ()
    would_be = extract_named(
        ability, "Bonus True Damage", ctx.level, ctx.stats, ctx.target
    )
    entry["detail"] = (
        "Death-only trigger: after taking fatal damage, Kog'Maw enters a "
        "4-second zombie state then explodes for the sourced "
        f"{would_be:g} true damage (cached 'Bonus True Damage' at champion "
        f"level {ctx.level}) to nearby enemies. The deterministic "
        "alive-state fight cannot enter (the main never dies in the "
        "model); priced at zero damage as a documented boundary."
    )
    return entry


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
    bool_option("q_shred", True, label="Apply Q Resistance Shred"),
    bool_option("w_active", True, label="W Active (Bio-Arcane Barrage)"),
]

ASSUMPTIONS = [
    "Q resistance shred applied before all other damage",
    "W (Bio-Arcane Barrage) assumed always active during the fight",
    "R damage scales dynamically with target's decreasing HP",
    "R Living Artillery stacks (cap 9, +40 mana cost per stack) only "
    "raise the spell's mana cost — no damage impact, so the stack count "
    "is not modeled",
    "Passive (Icathian Surprise) is a self-death trigger: after taking "
    "fatal damage Kog'Maw explodes for the sourced 140 : 650 (by "
    "champion level) true damage. The deterministic alive-state fight "
    "never kills the main, so this boundary is priced at zero damage "
    "(MODULE_COVERAGE: modeled, not out_of_scope) — the would-be "
    "magnitude is reported in the row's detail text",
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
MODULE_CC = {"Q": "none", "E": "slow", "R": "none"}

parse_abilities = build_parser(SLOTS, "Kog'Maw", cc_kinds=MODULE_CC)


SOURCES = load_champion_sources("Kog'Maw")
