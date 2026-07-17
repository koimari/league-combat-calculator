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
- P (Icathian Surprise) is a death passive — not modeled, absent from
  the slot map.

All numeric values are read from the champion JSON data; nothing is
hardcoded.
"""

from typing import Any, Callable

from ..ability_spec import DamagePart
from .engine import DEBUFF, SlotCtx, build_parser
from .slotlib import (
    extract_cooldown,
    extract_named,
    extract_value,
    ability_on_hit_entry,
    pct_health_per_hit,
    simple_damage,
)


def _caustic_spittle(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: magic damage + bonus-AS stat buff + resistance shred debuff."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    damage = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry: dict[str, Any] = {
        "name": ability.get("name", "Caustic Spittle"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "magic",
        "parts": (DamagePart("magic", damage),),
        "total_raw": damage,
    }

    # Passive bonus attack speed: the fight engine recalculates auto
    # attacks from the stat_buff.
    bonus_as = extract_value(ability, "Bonus Attack Speed", rank)
    if bonus_as > 0:
        entry["stat_buff"] = {"bonus_attack_speed": bonus_as}

    # Resistance shred: damage.py reduces target armor and MR by this
    # percentage before all other damage calculations.
    shred = extract_value(ability, "Resistances Reduction", rank)
    if ctx.options.get("q_shred", True) and shred > 0:
        entry["target_debuff"] = {
            "armor_reduction_percent": shred,
            "mr_reduction_percent": shred,
        }
    return entry


_caustic_spittle.phase = DEBUFF


def _bio_arcane_barrage(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: on-hit %maxHP magic damage in a castable shell."""
    if not ctx.options.get("w_active", True):
        return None
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    per_hit = pct_health_per_hit(
        ability,
        "Bonus Magic Damage",
        rank,
        ctx.target,
        ap=ctx.stats.get("ability_power", 0.0),
        ap_ratio_per_100=True,
    )
    if per_hit is None:
        return None

    name = ability.get("name", "Bio-Arcane Barrage")
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
    return entry


OPTIONS = [
    {
        "key": "q_shred",
        "type": "bool",
        "default": True,
        "label": "Apply Q Resistance Shred",
    },
    {
        "key": "w_active",
        "type": "bool",
        "default": True,
        "label": "W Active (Bio-Arcane Barrage)",
    },
]

ASSUMPTIONS = [
    "Q resistance shred applied before all other damage",
    "W (Bio-Arcane Barrage) assumed always active during the fight",
    "R damage scales dynamically with target's decreasing HP",
    "Passive (Icathian Surprise) is not modeled",
]

SLOTS = {
    "Q": _caustic_spittle,
    "W": _bio_arcane_barrage,
    "E": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "R": _living_artillery,
}

parse_abilities = build_parser(SLOTS, "Kog'Maw")
