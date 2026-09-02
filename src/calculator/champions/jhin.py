"""Jhin's Every Moment Matters AD, bouncing grenade and four-shot curtain."""

from __future__ import annotations

import math
from typing import Any

from ..ability_spec import DamagePart
from .engine import BUFF, SlotCtx, build_parser
from .inputs import bool_option, float_option, int_option
from .module_helpers import at_level, no_damage
from .slotlib import (
    ability_name,
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    simple_damage,
    with_control,
)
from .source_receipts import load_champion_sources

# HARDCODED: verify on patch updates — wiki prose, not in the JSON.
# Whisper's final round "always critically strikes ... and deals bonus
# physical damage equal to 15% / 20% / 25% (based on level) of the
# target's missing health" (level brackets 1 / 6 / 11, the wiki's
# standard three-breakpoint pattern).
_FOURTH_SHOT_MISSING_RATIOS = ((11, 0.25), (6, 0.20), (1, 0.15))


def _final_round_active(ctx: SlotCtx) -> bool:
    """The next auto is Whisper's final round (4th shot of the clip)."""
    if bool(ctx.option("p_final_shot")):
        return True
    return int(ctx.option("p_shot_number")) >= 4


def _final_round_count(ctx: SlotCtx) -> int:
    """Final rounds in the fight window (auto stream determines stack rate).

    Timed fights with an auto stream: the pre-stacked clip state
    (``p_shot_number``) plus the fight's auto count determines how many
    final rounds land — autos at positions congruent to
    ``(5 - p_shot_number) mod 4``.  One-rotation / no-auto-stream
    fights price exactly the one pre-stacked final round.
    """
    duration = ctx.options.get("fight_duration_seconds")
    if duration is not None:
        uptime = float(ctx.option("auto_attack_uptime"))
        num_autos = math.floor(ctx.stat("attack_speed") * uptime * duration)
        if num_autos > 0:
            pre = min(max(int(ctx.option("p_shot_number")), 1), 4) - 1
            return (pre + num_autos) // 4 - pre // 4
    return 1


def _whisper(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    base_percent = extract_value(ability, "Per-Level Scaling", ctx.level)
    crit = float(ctx.stat("critical_strike_chance"))
    bonus_as = float(ctx.stat("bonus_attack_speed"))
    percent = base_percent + 0.35 * crit + 0.30 * bonus_as
    bonus_ad = ctx.stat("attack_damage") * percent / 100.0
    entry = no_damage(
        ctx,
        name=ability_name(ability),
        reason=(
            f"Every Moment Matters adds {percent:.2f}% AD; the fourth-shot "
            "missing-health branch is priced by the final_round row."
        ),
    )
    if entry is not None:
        entry["stat_buff"] = {"bonus_attack_damage": bonus_ad}
        if _final_round_active(ctx):
            missing = at_level(_FOURTH_SHOT_MISSING_RATIOS, ctx.level)
            entry["parts"] = (
                DamagePart(
                    "physical",
                    0.0,
                    hp_scaled_damage=lambda ratio: missing
                    * float(ctx.target_stat("target_max_health") or 0.0)
                    * ratio,
                    crit_effectiveness=1.0,
                ),
            )
            entry["total_raw"] = 0.0
            entry["detail"] += (
                f" Final round (always crits) adds {missing:.0%} of target "
                "missing health per 4th shot."
            )
    return entry


_whisper.phase = BUFF


def _final_round(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: Whisper's final round — the 4th shot of the 4-round clip.

    The final round always critically strikes and adds the sourced
    missing-health bonus.  The fight engine cannot price a per-auto
    guaranteed-crit swing, so this row prices the sourced bonus at the
    user-declared missing-health ratio (``p_missing_health``): the
    expected contribution of the pre-stacked completion(s).
    """
    if not _final_round_active(ctx):
        return None
    ability = ctx.ability("P")
    if ability is None:
        return None
    target_max = float(ctx.target_stat("target_max_health") or 0.0)
    missing_ratio = min(max(float(ctx.option("p_missing_health")), 0.0), 1.0)
    per_round = (
        at_level(_FOURTH_SHOT_MISSING_RATIOS, ctx.level) * target_max * missing_ratio
    )
    if per_round <= 0.0:
        return None
    count = _final_round_count(ctx)
    if count <= 0:
        return None
    return {
        "name": "Whisper (Final Round)",
        "damage_type": "physical",
        "total_raw": per_round * count,
        "parts": (DamagePart("physical", per_round),),
        "proc_count": count,
        "detail": (
            f"{count} final round(s) x {per_round:.2f} bonus physical damage "
            f"({at_level(_FOURTH_SHOT_MISSING_RATIOS, ctx.level):.0%} of target missing "
            "health at the declared missing-health ratio)."
        ),
    }


def _dancing_grenade(ctx: SlotCtx) -> dict[str, Any] | None:
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    bounces = min(max(int(ctx.option("q_bounces")), 1), 4)
    deaths = min(max(int(ctx.option("q_target_deaths")), 0), 3)
    value = extract_named(
        ability, "Physical Damage", rank, ctx.stats, ctx.target
    ) + deaths * extract_named(
        ability, "Bonus Damage per Target Death", rank, ctx.stats, ctx.target
    )
    entry = damage_entry(
        ability_name(ability),
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


def _captive_audience(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: the summoned Lotus Trap's detonation damage.

    One trap detonates for the full "Magic Damage" row (20-260 + 120%
    AD + 100% AP by rank) and slows 35% for 2 seconds (utility).  The
    wiki notes a champion struck by ANOTHER Lotus Trap within the last
    1 second takes 65% damage ("Reduced Damage" row), so ``e_traps``
    (default 1, max 2 — the charge cap) prices the first trap full and
    each further trap at the reduced row.
    """
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    traps = min(max(int(ctx.option("e_traps")), 1), 2)
    full = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    reduced = extract_named(ability, "Reduced Damage", rank, ctx.stats, ctx.target)
    parts = [DamagePart("magic", full, time_offset=0.0)]
    if traps > 1:
        parts.append(
            DamagePart(
                "magic", reduced, count=traps - 1, time_offset=1.0, hit_interval=0.0
            )
        )
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        full + reduced * (traps - 1),
        "magic",
    )
    entry["parts"] = tuple(parts)
    entry["detail"] = (
        f"{traps} Lotus Trap detonation(s): the first full, each further "
        f"trap at the 65% reduced row (struck by another trap within 1s); "
        "the 35% 2s slow is utility."
    )
    return entry


def _curtain_call(ctx: SlotCtx) -> dict[str, Any] | None:
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    shots = min(max(int(ctx.option("r_shots")), 1), 4)
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
        ability_name(ability),
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
    "final_round": _final_round,
    "Q": _dancing_grenade,
    "W": with_control(
        simple_damage(
            attr="Physical Damage",
            dmg_type="physical",
            event_order_certified="single_hit",
        ),
        duration_attr="Root Duration",
    ),
    "E": _captive_audience,
    "R": _curtain_call,
}

# Q's grenade only damages and bounces.  W "roots them" on a marked
# champion, and Whisper marks every champion "damaged by Jhin" for 4
# seconds — the module's rotation always lands Q's grenade (+0.2s) before
# W's shot, in every fight mode, so the mark is up when W arrives.  E's
# trap "slow[s] enemies within the area by 35% for 2 seconds before
# exploding" and each R bullet stops on a champion, "slowing them by 80%".
# P and its final-round proc row author no cast the ledger reads as an
# ability event.
MODULE_CC = {"Q": "none", "W": "root", "E": "slow", "R": "slow"}

parse_abilities = build_parser(SLOTS, "Jhin", cc_kinds=MODULE_CC)
OPTIONS = [
    bool_option("p_final_shot", False, label="Whisper fourth shot"),
    int_option(
        "p_shot_number", 1, minimum=1, maximum=4, label="Shots into the 4-round clip"
    ),
    float_option(
        "p_missing_health",
        0.0,
        minimum=0.0,
        maximum=1.0,
        label="Target missing-health ratio on the final round",
        step=0.05,
    ),
    int_option("q_bounces", 1, minimum=1, maximum=4, label="Dancing Grenade bounces"),
    int_option(
        "q_target_deaths", 0, minimum=0, maximum=3, label="Deaths after grenade hit"
    ),
    int_option("e_traps", 1, minimum=1, maximum=2, label="Lotus Trap detonations"),
    int_option("r_shots", 4, minimum=1, maximum=4, label="Curtain Call bullets"),
]
ASSUMPTIONS = [
    "Every Moment Matters uses the cached level scaling plus explicit "
    "crit/bonus-AS inputs; its AD grant is applied before later damage.",
    "Whisper's final round is the 4th shot of the 4-round clip: always a "
    "crit, adding 15/20/25% (levels 1/6/11) of target missing health. "
    "p_shot_number is the explicit pre-stack (shots into the clip); "
    "p_missing_health prices the bonus at the fight engine's static "
    "target context (the per-auto dynamic missing-health curve is beyond "
    "the engine's proc model — the expected contribution is priced flat).",
    "Dancing Grenade exposes bounce/death state, while Deadly Flourish "
    "and Lotus Trap use their typed source damage once; e_traps (max 2, "
    "the charge cap) prices the second trap at the 65% reduced row "
    "(champion struck by another Lotus Trap within 1s).",
    "Lotus Trap's 35% 2s slow and the reveal are utility the fight model "
    "does not price; trap arm time and placement are state outside the "
    "damage model.",
    "Curtain Call interpolates each bullet's missing-health range and "
    "keeps the fourth bullet's sourced critical packet separate.",
]
SOURCES = load_champion_sources("Jhin")
