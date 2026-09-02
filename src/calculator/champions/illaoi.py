"""Illaoi's Tentacle proc, health-scaled Harsh Lesson and Leap of Faith."""

from __future__ import annotations

from typing import Any

from .. import healing_helpers as _healing
from ..ability_spec import DamagePart
from .engine import ONHIT, SlotCtx, build_parser
from .healing_contract import self_healing_rule
from .inputs import int_option
from .module_helpers import no_damage
from .slotlib import (
    ability_name,
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
)
from .source_receipts import load_champion_sources


def _tentacle(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    count = min(max(int(ctx.option("p_tentacles")), 0), 12)
    if count <= 0:
        return None
    value = extract_named(
        ability, "Bonus Physical Damage", ctx.level, ctx.stats, ctx.target
    )
    q = ctx.ability("Q")
    increase = extract_value(q, "Damage Increase", ctx.rank_for("Q")) if q else 0.0
    value *= 1.0 + increase / 100.0
    # ``proc_count`` is the number of DISCRETE proc instances and
    # ``DamagePart.count`` is the number of hits INSIDE one instance;
    # ``_add_precomputed_proc_damage`` prices
    # ``sum(part.amount * part.count) * proc_count``, so carrying the
    # tentacle count in both fields multiplies it in twice (a
    # count-squared overstatement, and ``_apply_basic_amp`` would also be
    # told about ``count x proc_count`` damage instances). One Tentacle
    # strike is one part; the tentacle count is the proc count.
    return {
        "name": ability_name(ability),
        "damage_type": "physical",
        "total_raw": value * count,
        "parts": (
            DamagePart("physical", value, count=1, time_offset=0.0, hit_interval=0.5),
        ),
        "proc_count": count,
        "event_phase": "effect",
        "damage_events": [
            {
                "time": i * 0.5,
                "damage_type": "physical",
                "damage": value,
                "event_precision": "phase_order",
            }
            for i in range(count)
        ],
        "detail": (
            f"{count} Tentacle strike(s), including the sourced Q rank increase of "
            f"{increase:g}%."
        ),
    }


_tentacle.phase = ONHIT


def _harsh_lesson(ctx: SlotCtx) -> dict[str, Any] | None:
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    target_max = float(ctx.target_stat("target_max_health") or 0.0)
    pct = extract_value(ability, "Additional Physical Damage", rank) / 100.0
    ad_ratio = extract_value(ability, "Additional Physical Damage", rank, 1) / 100.0
    minimum = extract_value(ability, "Minimum Physical Damage", rank)
    value = max(minimum, pct * target_max + ad_ratio * ctx.stat("attack_damage"))
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        value,
        "physical",
    )
    entry["parts"] = (
        DamagePart("physical", value, basic_damage=True, time_offset=0.1),
    )
    entry["empowers_next_auto"] = True
    entry["applies_item_on_hits"] = {
        "effectiveness": 1.0,
        "hits": 1,
        "triggers": ("on_hit",),
    }
    entry["detail"] = (
        f"Empowered attack: max-health ratio {pct:.3f}, AD ratio {ad_ratio:.3f}, "
        f"minimum {minimum:g}."
    )
    return entry


def _leap_of_faith(ctx: SlotCtx) -> dict[str, Any] | None:
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    value = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        value,
        "physical",
    )
    entry["parts"] = (DamagePart("physical", value, time_offset=0.4),)
    entry["detail"] = (
        "One area slam; the champion-hit tentacle summons and Harsh Lesson cooldown "
        "reduction are explicit state."
    )
    return entry


SLOTS = {
    "P": _tentacle,
    "Q": lambda ctx: no_damage(
        ctx,
        name="Tentacle Smash",
        reason=(
            "The active commands a Tentacle; its damage is represented by the "
            "explicit Tentacle proc count."
        ),
    ),
    "W": _harsh_lesson,
    "E": lambda ctx: no_damage(
        ctx,
        name="Test of Spirit",
        reason=(
            "Spirit health/armor/magic-resist redirection and Vessel spawning are "
            "target-state branches, not direct outgoing damage."
        ),
    ),
    "R": _leap_of_faith,
}
# W's empowered attack and R's idol slam only damage — Illaoi's control is
# E's tether severance (a slow that lands with no damage packet of its own)
# and it is not on either damaging cast.  Q and E author no damage part;
# P's Tentacle strikes are an effect-phase proc row whose event list the
# module builds itself, so a slot marker there would never reach the
# ledger.
MODULE_CC = {"W": "none", "R": "none"}

parse_abilities = build_parser(SLOTS, "Illaoi", cc_kinds=MODULE_CC)
OPTIONS = [
    int_option("p_tentacles", 1, minimum=0, maximum=12, label="Tentacle strikes")
]
ASSUMPTIONS = [
    "Tentacle strikes use the level-scaled parent formula and Q rank increase; the "
    "user supplies how many authored strikes land.",
    "Harsh Lesson is one item-coupled empowered attack; Test of Spirit's redirected "
    "damage remains explicit target state.",
    "Leap of Faith's slam is separate from the summoned Tentacle strikes.",
    "Each Tentacle that hits an enemy champion heals Illaoi for 5% of her "
    "missing health (cached P description prose); the E1 self-heal rule "
    "authors one live missing-health heal per tentacle hit event.",
]
SOURCES = load_champion_sources("Illaoi")


# pylint: disable=too-many-arguments,too-many-positional-arguments,unused-argument
def derive_self_healing(
    champion_data: dict[str, Any],
    champion_stats: dict[str, float],
    ability_damages: dict[str, dict[str, Any]],
    damage_events: list[dict[str, Any]],
    cast_timeline: list[dict[str, Any]] | None = None,
    fight_duration_seconds: float | None = None,
) -> list[dict[str, Any]]:
    """Resolve Illaoi self-healing events from its authored packet."""
    healing = []
    tentacle_hits = _healing.attributed_events(
        damage_events, lambda source, _event: source == "passive"
    )
    healing.extend(
        {
            "time": float(event.get("time", 0.0)),
            "amount": 0.0,
            "amount_formula": lambda current_health, maximum_health: (
                max(0.0, maximum_health - current_health) * 0.05
            ),
            "source": "Prophet of an Elder God",
            "kind": "champion_passive",
            **_healing.trigger_fields(event),
        }
        for event in tentacle_hits
    )
    return healing


SELF_HEALING_RULE = self_healing_rule("Illaoi")(derive_self_healing)
