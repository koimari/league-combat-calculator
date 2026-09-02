"""Garen's empowered Q, spin cadence and missing-health ultimate."""

from __future__ import annotations

from typing import Any

from .. import healing_helpers as _healing
from ..ability_spec import DamagePart
from .engine import BUFF, SlotCtx, build_parser
from .healing_contract import self_healing_rule
from .inputs import bool_option, champion_stat
from .module_helpers import named_damage, no_damage, ranked_slot
from .slotlib import ability_name, damage_entry, extract_cooldown, extract_named
from .source_receipts import load_champion_sources


def _perseverance(ctx: SlotCtx) -> dict[str, Any] | None:
    return no_damage(
        ctx,
        name="Perseverance",
        reason="Out-of-combat regeneration is self sustain, not outgoing damage.",
        slot="P",
    )


_decisive_strike = named_damage(
    "Bonus Physical Damage",
    "physical",
    basic_damage=True,
    event_order_certified="single_hit",
    empowers_next_auto=True,
    detail="One uncancellable, silencing empowered basic attack; slow cleanse/movement "
    "speed are state-only.",
)


def _courage(ctx: SlotCtx) -> dict[str, Any] | None:
    return no_damage(
        ctx,
        name="Courage",
        reason="Courage resist stacks, shield and damage reduction are defensive state.",
    )


_courage.phase = BUFF


@ranked_slot
def _judgment(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    nearest = bool(ctx.option("e_nearest_target"))
    spins = 7 + int(max(0.0, ctx.stat("bonus_attack_speed")) // 25.0)
    spins = min(max(spins, 7), 15)
    attr = "Increased Damage Per Spin" if nearest else "Physical Damage Per Spin"
    per_spin = extract_named(ability, attr, rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        per_spin * spins,
        "physical",
    )
    entry["parts"] = (
        DamagePart(
            "physical", per_spin, count=spins, time_offset=0.0, hit_interval=3.0 / spins
        ),
    )
    entry["detail"] = (
        f"{spins} spin(s); nearest-target 25% branch={'on' if nearest else 'off'}. Six "
        f"hits apply the sourced 25% armor reduction."
    )
    entry["target_debuff"] = {
        "armor_reduction_percent": 25.0,
        "duration": 6.0,
        "threshold_hits": 6,
    }
    return entry


_demacian_justice = named_damage(
    "True Damage",
    "true",
    time_offset=0.435,
    event_order_certified="single_hit",
    target_max_health_sensitive=True,
    detail="True damage scales from target missing health; the execute/reveal threshold "
    "is target state.",
)


SLOTS = {
    "P": _perseverance,
    "Q": _decisive_strike,
    "W": _courage,
    "E": _judgment,
    "R": _demacian_justice,
}
# Garen's damaging casts apply no immobilize and no slow: Q's empowered
# attack silences (a silence is neither, and the vocabulary has no kind for
# it), E only spins and shreds armor, R deals true damage and reveals.  Q's
# own text cleanses slows *from Garen* rather than applying one.  P and W
# author no damage part.
MODULE_CC = {"Q": "none", "E": "none", "R": "none"}

parse_abilities = build_parser(SLOTS, "Garen", cc_kinds=MODULE_CC)

OPTIONS = [
    bool_option("e_nearest_target", True, label="Judgment nearest-target branch"),
]

ASSUMPTIONS = [
    "Judgment uses the sourced 7 + 1 per 25% bonus attack speed spin count and "
    "exposes the nearest-target 25% branch.",
    "The armor reduction is retained as an ordered effect after the six-hit "
    "threshold; it is never allowed to boost the first six spins.",
    "Perseverance and Courage are defensive/self-state rows and do not enter TDD.",
]

SOURCES = load_champion_sources("Garen")


# pylint: disable=too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument
def derive_self_healing(
    champion_data: dict[str, Any],
    champion_stats: dict[str, float],
    ability_damages: dict[str, dict[str, Any]],
    damage_events: list[dict[str, Any]],
    cast_timeline: list[dict[str, Any]] | None = None,
    fight_duration_seconds: float | None = None,
) -> list[dict[str, Any]]:
    """Resolve Garen self-healing events from its authored packet."""
    healing = []
    p = _healing.ability_json(champion_data, "P")
    p_level = int(champion_stat(champion_stats, "level"))
    per_tick = 0.0
    for effect in p.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute") != "Max Health Damage":
                continue
            modifiers = leveling.get("modifiers", [])
            if not modifiers:
                continue
            values = modifiers[0].get("values", [])
            if not values:
                continue
            per_tick = float(values[min(max(p_level, 1) - 1, len(values) - 1)]) / 100.0
    duration = max(0.0, float(fight_duration_seconds or 0.0))
    if per_tick > 0.0 and duration > 0.0:
        tick = 0.5
        sequence = 0
        while tick <= duration + 1e-9:
            healing.append(
                {
                    "time": tick,
                    "amount": 0.0,
                    "amount_formula": (
                        lambda _current_health, maximum_health, ratio=per_tick: (
                            maximum_health * ratio
                        )
                    ),
                    "source": "Perseverance",
                    "kind": "regen",
                    "actor_wide": True,
                    "requires_damage_free_seconds": 8.0,
                    "sequence": sequence,
                }
            )
            sequence += 1
            tick += 0.5
    return healing


SELF_HEALING_RULE = self_healing_rule("Garen")(derive_self_healing)
