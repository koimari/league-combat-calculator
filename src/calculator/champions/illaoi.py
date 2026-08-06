"""Illaoi's Tentacle proc, health-scaled Harsh Lesson and Leap of Faith."""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from .engine import ONHIT, SlotCtx, build_parser
from .reviewed_batch_01 import no_damage, source_row
from .slotlib import damage_entry, extract_cooldown, extract_named, extract_value


def _tentacle(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    count = min(max(int(ctx.options.get("p_tentacles", 1)), 0), 12)
    if count <= 0:
        return None
    value = extract_named(
        ability, "Bonus Physical Damage", ctx.level, ctx.stats, ctx.target
    )
    q = ctx.ability("Q")
    increase = extract_value(q, "Damage Increase", ctx.rank_for("Q")) if q else 0.0
    value *= 1.0 + increase / 100.0
    return {
        "name": ability.get("name", "Prophet of an Elder God"),
        "damage_type": "physical",
        "total_raw": value * count,
        "parts": (
            DamagePart(
                "physical", value, count=count, time_offset=0.0, hit_interval=0.5
            ),
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
        "detail": f"{count} Tentacle strike(s), including the sourced Q rank increase of {increase:g}%.",
    }


_tentacle.phase = ONHIT


def _harsh_lesson(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    target_max = float(ctx.target.get("target_max_health", 0.0) or 0.0)
    pct = extract_value(ability, "Additional Physical Damage", rank) / 100.0
    ad_ratio = extract_value(ability, "Additional Physical Damage", rank, 1) / 100.0
    minimum = extract_value(ability, "Minimum Physical Damage", rank)
    value = max(
        minimum, pct * target_max + ad_ratio * ctx.stats.get("attack_damage", 0.0)
    )
    entry = damage_entry(
        ability.get("name", "Harsh Lesson"),
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
        f"Empowered attack: max-health ratio {pct:.3f}, AD ratio {ad_ratio:.3f}, minimum {minimum:g}."
    )
    return entry


def _leap_of_faith(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    value = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Leap of Faith"),
        rank,
        extract_cooldown(ability, rank),
        value,
        "physical",
    )
    entry["parts"] = (DamagePart("physical", value, time_offset=0.4),)
    entry["detail"] = (
        "One area slam; the champion-hit tentacle summons and Harsh Lesson cooldown reduction are explicit state."
    )
    return entry


SLOTS = {
    "P": _tentacle,
    "Q": lambda ctx: no_damage(
        ctx,
        name="Tentacle Smash",
        reason="The active commands a Tentacle; its damage is represented by the explicit Tentacle proc count.",
    ),
    "W": _harsh_lesson,
    "E": lambda ctx: no_damage(
        ctx,
        name="Test of Spirit",
        reason="Spirit health/armor/magic-resist redirection and Vessel spawning are target-state branches, not direct outgoing damage.",
    ),
    "R": _leap_of_faith,
}
parse_abilities = build_parser(SLOTS, "Illaoi")
OPTIONS = [
    {
        "key": "p_tentacles",
        "type": "int",
        "default": 1,
        "min": 0,
        "max": 12,
        "label": "Tentacle strikes",
    }
]
ASSUMPTIONS = [
    "Tentacle strikes use the level-scaled parent formula and Q rank increase; the user supplies how many authored strikes land.",
    "Harsh Lesson is one item-coupled empowered attack; Test of Spirit's redirected damage remains explicit target state.",
    "Leap of Faith's slam is separate from the summoned Tentacle strikes.",
    "Each Tentacle that hits an enemy champion heals Illaoi for 5% of her "
    "missing health (cached P description prose); the E1 self-heal rule "
    "authors one live missing-health heal per tentacle hit event.",
]
SOURCES = [
    source_row(
        "Illaoi parent entry",
        "https://wiki.leagueoflegends.com/en-us/Illaoi",
        4033192,
        "2026-06-21T14:50:24Z",
    ),
    source_row(
        "Illaoi Q template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Illaoi/Q",
        2863949,
        "2019-11-03T19:57:06Z",
    ),
    source_row(
        "Illaoi W template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Illaoi/W",
        2864244,
        "2019-11-03T20:09:53Z",
    ),
    source_row(
        "Illaoi E template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Illaoi/E",
        2864390,
        "2019-11-03T20:12:24Z",
    ),
    source_row(
        "Illaoi R template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Illaoi/R",
        2864536,
        "2019-11-03T20:15:49Z",
    ),
]
MODULE_COVERAGE = {slot: "modeled" for slot in ("P", "Q", "W", "E", "R")}
REVIEW_STATUS = "reviewed_module"
