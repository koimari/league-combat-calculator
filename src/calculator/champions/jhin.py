"""Jhin's Every Moment Matters AD, bouncing grenade and four-shot curtain."""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from .engine import BUFF, SlotCtx, build_parser
from .reviewed_batch_01 import no_damage, source_row
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    simple_damage,
)


def _whisper(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    base_percent = extract_value(ability, "Per-Level Scaling", ctx.level)
    crit = float(ctx.stats.get("critical_strike_chance", 0.0))
    bonus_as = float(ctx.stats.get("bonus_attack_speed", 0.0))
    percent = base_percent + 0.35 * crit + 0.30 * bonus_as
    bonus_ad = ctx.stats.get("attack_damage", 0.0) * percent / 100.0
    entry = no_damage(
        ctx,
        name=ability.get("name", "Whisper"),
        reason=f"Every Moment Matters adds {percent:.2f}% AD; the fourth-shot missing-health branch is opt-in.",
    )
    if entry is not None:
        entry["stat_buff"] = {"bonus_attack_damage": bonus_ad}
        if bool(ctx.options.get("p_final_shot", False)):
            missing = extract_value(ability, "Per-Level Scaling", ctx.level, 0) / 100.0
            entry["parts"] = (
                DamagePart(
                    "physical",
                    0.0,
                    hp_scaled_damage=lambda ratio: missing
                    * float(ctx.target.get("target_max_health", 0.0) or 0.0)
                    * ratio,
                    crit_effectiveness=1.0,
                ),
            )
            entry["total_raw"] = 0.0
            entry[
                "detail"
            ] += f" Final round adds {missing:.2%} of target missing health."
    return entry


_whisper.phase = BUFF


def _dancing_grenade(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    bounces = min(max(int(ctx.options.get("q_bounces", 1)), 1), 4)
    deaths = min(max(int(ctx.options.get("q_target_deaths", 0)), 0), 3)
    value = extract_named(
        ability, "Physical Damage", rank, ctx.stats, ctx.target
    ) + deaths * extract_named(
        ability, "Bonus Damage per Target Death", rank, ctx.stats, ctx.target
    )
    entry = damage_entry(
        ability.get("name", "Dancing Grenade"),
        rank,
        extract_cooldown(ability, rank),
        value * bounces,
        "physical",
    )
    entry["parts"] = (
        DamagePart("physical", value, count=bounces, time_offset=0.2, hit_interval=0.4),
    )
    entry["detail"] = (
        f"{bounces} bounce(s), {deaths} authored target death(s) before the next bounce."
    )
    return entry


def _curtain_call(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    shots = min(max(int(ctx.options.get("r_shots", 4)), 1), 4)
    minimum = extract_named(
        ability, "Minimum Physical Damage per Bullet", rank, ctx.stats, ctx.target
    )
    maximum = extract_named(
        ability, "Maximum Physical Damage per Bullet", rank, ctx.stats, ctx.target
    )
    normal = min(shots, 3)
    parts = [
        DamagePart(
            "physical",
            minimum,
            count=normal,
            hp_scaled_damage=lambda ratio: minimum + (maximum - minimum) * ratio,
            time_offset=0.2,
            hit_interval=1.0,
        )
    ]
    total = maximum * normal
    if shots == 4:
        fourth_min = extract_named(
            ability, "Minimum Fourth Shot Damage", rank, ctx.stats, ctx.target
        )
        fourth_max = extract_named(
            ability, "Maximum Fourth Shot Damage", rank, ctx.stats, ctx.target
        )
        parts.append(
            DamagePart(
                "physical",
                fourth_min,
                hp_scaled_damage=lambda ratio: fourth_min
                + (fourth_max - fourth_min) * ratio,
                crit_effectiveness=1.0,
                time_offset=3.2,
            )
        )
        total += fourth_max
    entry = damage_entry(
        ability.get("name", "Curtain Call"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "physical",
    )
    entry["parts"] = tuple(parts)
    entry["event_order_certified"] = "up to four authored bullets"
    return entry


SLOTS = {
    "P": _whisper,
    "Q": _dancing_grenade,
    "W": simple_damage(attr="Physical Damage", dmg_type="physical"),
    "E": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "R": _curtain_call,
}
parse_abilities = build_parser(SLOTS, "Jhin")
OPTIONS = [
    {
        "key": "p_final_shot",
        "type": "bool",
        "default": False,
        "label": "Whisper fourth shot",
    },
    {
        "key": "q_bounces",
        "type": "int",
        "default": 1,
        "min": 1,
        "max": 4,
        "label": "Dancing Grenade bounces",
    },
    {
        "key": "q_target_deaths",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 3,
        "label": "Deaths after grenade hit",
    },
    {
        "key": "r_shots",
        "type": "int",
        "default": 4,
        "min": 1,
        "max": 4,
        "label": "Curtain Call bullets",
    },
]
ASSUMPTIONS = [
    "Every Moment Matters uses the cached level scaling plus explicit crit/bonus-AS inputs; its AD grant is applied before later damage.",
    "Dancing Grenade exposes bounce/death state, while Deadly Flourish and Lotus Trap use their typed source damage once.",
    "Curtain Call interpolates each bullet's missing-health range and keeps the fourth bullet's sourced critical packet separate.",
]
SOURCES = [
    source_row(
        "Jhin parent entry",
        "https://wiki.leagueoflegends.com/en-us/Jhin",
        4022310,
        "2026-05-24T11:33:51Z",
    ),
    source_row(
        "Jhin Q template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Jhin/Q",
        2863956,
        "2019-11-03T19:57:13Z",
    ),
    source_row(
        "Jhin W template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Jhin/W",
        2864251,
        "2019-11-03T20:10:00Z",
    ),
    source_row(
        "Jhin E template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Jhin/E",
        2864397,
        "2019-11-03T20:12:31Z",
    ),
    source_row(
        "Jhin R template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Jhin/R",
        2864543,
        "2019-11-03T20:15:55Z",
    ),
]
MODULE_COVERAGE = {slot: "modeled" for slot in ("P", "Q", "W", "E", "R")}
REVIEW_STATUS = "reviewed_module"
