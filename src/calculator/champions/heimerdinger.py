"""Heimerdinger's rocket, grenade and source-receipted turret timeline."""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .reviewed_batch_01 import no_damage, source_row
from .slotlib import damage_entry, extract_cooldown, extract_named, extract_recharge


def _turret_damage(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability("Q", min(max(int(ctx.options.get("q_variant", 0)), 0), 1))
    if ability is None:
        return None
    variant = min(max(int(ctx.options.get("q_variant", 0)), 0), 1)
    rank = ctx.rank_for("Q")
    if rank < 1:
        return None
    turret_count = min(max(int(ctx.options.get("q_turrets", 3)), 1), 3)
    attacks = min(max(int(ctx.options.get("q_turret_attacks", 3)), 1), 12)
    if variant == 0:
        shot = (
            7.0
            + (23.0 - 7.0) * (ctx.level - 1) / 17.0
            + 0.35 * ctx.stats.get("ability_power", 0.0)
        )
        beam = 40.0 + 20.0 * (rank - 1) + 0.55 * ctx.stats.get("ability_power", 0.0)
        name = "H-28G Evolution Turret"
    else:
        r_rank = min(max(ctx.rank_for("R"), 1), 3)
        shot = 80.0 + 20.0 * (r_rank - 1) + 0.35 * ctx.stats.get("ability_power", 0.0)
        beam = 100.0 + 40.0 * (r_rank - 1) + 0.70 * ctx.stats.get("ability_power", 0.0)
        name = "H-28Q Apex Turret"
    total_shots = turret_count * attacks
    beam_count = min(max(int(ctx.options.get("q_beams", 1)), 0), turret_count)
    parts = [
        DamagePart(
            "magic",
            shot,
            count=total_shots,
            time_offset=0.0,
            hit_interval=1.0 if variant else 1.75,
        )
    ]
    if beam_count:
        parts.append(
            DamagePart(
                "magic", beam, count=beam_count, time_offset=2.0, hit_interval=1.0
            )
        )
    # Q is a charge ability: the JSON cooldown field holds only the 1s
    # inter-cast timer, and the limiter for sustained use is the 20s
    # rechargeRate.  Without it the engine scheduled 9 deploys in a 10s
    # window — each cast re-priced the full turret swarm.
    cooldown = extract_recharge(ctx.ability("Q", 0), rank)
    entry = damage_entry(
        name,
        rank,
        cooldown,
        sum(p.amount * p.count for p in parts),
        "magic",
    )
    entry["parts"] = tuple(parts)
    entry["event_order_certified"] = "sourced turret attack and beam cadence"
    entry["detail"] = (
        f"{turret_count} {name} unit(s), {attacks} shot(s) each, {beam_count} charged beam(s)."
    )
    return entry


def _micro_rockets(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability("W", 0)
    if ability is None:
        return None
    rank = ctx.rank_for("W")
    if rank < 1:
        return None
    rockets = min(max(int(ctx.options.get("w_rockets", 5)), 1), 5)
    first = extract_named(
        ability, "Initial Rocket Magic Damage", rank, ctx.stats, ctx.target
    )
    later = extract_named(
        ability, "Subsequent Rocket Magic Damage", rank, ctx.stats, ctx.target
    )
    parts = [DamagePart("magic", first, time_offset=0.25)]
    if rockets > 1:
        parts.append(
            DamagePart(
                "magic", later, count=rockets - 1, time_offset=0.35, hit_interval=0.08
            )
        )
    entry = damage_entry(
        ability.get("name", "Hextech Micro-Rockets"),
        rank,
        extract_cooldown(ability, rank),
        first + later * (rockets - 1),
        "magic",
    )
    entry["parts"] = tuple(parts)
    entry["detail"] = (
        f"{rockets} authored rockets; subsequent rockets use the reduced champion damage row."
    )
    return entry


def _grenade(ctx: SlotCtx) -> dict[str, Any] | None:
    variant = min(max(int(ctx.options.get("e_upgrade", 0)), 0), 1)
    ability = ctx.ability("E", variant)
    if ability is None:
        return None
    rank = ctx.rank_for("E")
    if rank < 1:
        return None
    if variant == 0:
        value = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    else:
        r_rank = min(max(ctx.rank_for("R"), 1), 3)
        value = (100.0, 200.0, 300.0)[r_rank - 1] + 0.60 * ctx.stats.get(
            "ability_power", 0.0
        )
    entry = damage_entry(
        ability.get("name", "CH-2 Electron Storm Grenade"),
        rank,
        extract_cooldown(ctx.ability("E", 0), rank),
        value,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", value, time_offset=0.6),)
    entry["detail"] = (
        "One champion damage instance; bounces, stun and slow are sourced control state."
    )
    return entry


def _upgrade(ctx: SlotCtx) -> dict[str, Any] | None:
    return no_damage(
        ctx,
        name="UPGRADE!!!",
        reason="The ultimate is an empowerment toggle; its selected Q/W/E variant carries the outgoing damage.",
    )


SLOTS = {
    "P": lambda ctx: no_damage(
        ctx,
        name="Hextech Affinity",
        reason="The passive is movement speed near allied structures or turrets.",
    ),
    "Q": _turret_damage,
    "W": _micro_rockets,
    "E": _grenade,
    "R": _upgrade,
}
parse_abilities = build_parser(SLOTS, "Heimerdinger")
OPTIONS = [
    {
        "key": "q_variant",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 1,
        "label": "Turret variant (Evolution/Apex)",
    },
    {
        "key": "q_turrets",
        "type": "int",
        "default": 3,
        "min": 1,
        "max": 3,
        "label": "Deployed turrets",
    },
    {
        "key": "q_turret_attacks",
        "type": "int",
        "default": 3,
        "min": 1,
        "max": 12,
        "label": "Turret attacks",
    },
    {
        "key": "q_beams",
        "type": "int",
        "default": 1,
        "min": 0,
        "max": 3,
        "label": "Charged beams",
    },
    {
        "key": "w_rockets",
        "type": "int",
        "default": 5,
        "min": 1,
        "max": 5,
        "label": "Rockets hitting the target",
    },
    {
        "key": "e_upgrade",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 1,
        "label": "Grenade variant",
    },
]
ASSUMPTIONS = [
    "Turret shot/beam values and cadences are copied from the full Wiki Pets entry because the champion slot template intentionally contains no pet formula rows.",
    "Q is a charge ability: its cooldown is the 20s rechargeRate (the "
    "JSON cooldown field is only the 1s inter-cast timer), so one deploy "
    "is priced per 20s window; the q_turrets/q_turret_attacks options set "
    "how many turrets and shots one deploy contributes.",
    "The R upgrade is the q_variant option: the H-28Q Apex Turret rows "
    "scale by R rank (shots 80-120 +35% AP, beams 100-180 +70% AP).",
    "Rocket multi-hit reduction uses the explicit first/subsequent rows; only one champion hit is counted for the upgraded grenade.",
    "UPGRADE!!!, stuns, slows, turret targeting and vision are state/utility, not extra direct champion damage.",
]
SOURCES = [
    source_row(
        "Heimerdinger parent entry",
        "https://wiki.leagueoflegends.com/en-us/Heimerdinger",
        4025016,
        "2026-06-04T11:15:04Z",
    ),
    source_row(
        "Heimerdinger Q template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Heimerdinger/Q",
        2863948,
        "2019-11-03T19:57:05Z",
    ),
    source_row(
        "Heimerdinger W template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Heimerdinger/W",
        2864243,
        "2019-11-03T20:09:52Z",
    ),
    source_row(
        "Heimerdinger E template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Heimerdinger/E",
        2864389,
        "2019-11-03T20:12:23Z",
    ),
    source_row(
        "Heimerdinger R template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Heimerdinger/R",
        2864535,
        "2019-11-03T20:15:47Z",
    ),
]
MODULE_COVERAGE = {slot: "modeled" for slot in ("P", "Q", "W", "E", "R")}
REVIEW_STATUS = "reviewed_module"
