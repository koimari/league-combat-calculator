"""Ekko's three-hit passive, two-pass Q and target-health state."""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from .engine import BUFF, ONHIT, SlotCtx, build_parser
from .reviewed_batch_01 import no_damage, source_row
from .slotlib import damage_entry, extract_cooldown, extract_named, proc_damage


def _resonance(ctx: SlotCtx, ability: dict[str, Any]) -> float:
    """One Z-Drive Resonance detonation: the third stack consumes all
    three to deal the sourced bonus magic damage (30 : 150 by level,
    + 80% AP).  The detonation is priced per completed 3-stack cycle."""
    return extract_named(
        ability, "Bonus Magic Damage", ctx.level, ctx.stats, ctx.target
    )


_resonance_proc = proc_damage(
    _resonance,
    "magic",
    count_option="p_procs",
    default_count=0,
    name="Z-Drive Resonance",
    phase_order_events=True,
)


def _timewinder(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    initial = extract_named(
        ability, "Initial Magic Damage", rank, ctx.stats, ctx.target
    )
    returned = extract_named(
        ability, "Return Magic Damage", rank, ctx.stats, ctx.target
    )
    return_entry = damage_entry(
        ability.get("name", "Timewinder"),
        rank,
        extract_cooldown(ability, rank),
        initial + returned,
        "magic",
    )
    return_entry["parts"] = (
        DamagePart("magic", initial, time_offset=0.25),
        DamagePart("magic", returned, time_offset=2.0),
    )
    return_entry["detail"] = (
        "Initial grenade and authored return pass; each pass hits a target once."
    )
    return return_entry


def _parallel_convergence(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    ready = bool(ctx.options.get("w_passive_ready", False))
    entry = no_damage(
        ctx,
        name=ability.get("name", "Parallel Convergence"),
        reason="Active W creates a sourced shield/stun zone; its passive on-hit is opt-in below 30% target health.",
    )
    if entry is None:
        return None
    if ready:
        target_max = float(ctx.target.get("target_max_health", 0.0) or 0.0)
        missing_ratio = float(ctx.options.get("w_target_missing_health", 0.5))
        missing_ratio = min(max(missing_ratio, 0.0), 1.0)
        base = max(
            15.0,
            target_max
            * (0.03 + 0.03 * ctx.stats.get("ability_power", 0.0) / 100.0)
            * missing_ratio,
        )
        entry["on_hit"] = {
            "name": "Parallel Convergence passive",
            "damage_per_hit": base,
            "damage_type": "magic",
        }
        entry["detail"] = "Passive on-hit enabled: target is below 30% max health."
    return entry


_parallel_convergence.phase = ONHIT


def _phase_dive(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    bonus = extract_named(ability, "Bonus Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Phase Dive"),
        rank,
        extract_cooldown(ability, rank),
        bonus,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", bonus),)
    entry["empowers_next_auto"] = True
    entry["detail"] = (
        "Empowers one basic attack; the blink and attack reset are state-only."
    )
    return entry


def _chronobreak(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    damage = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Chronobreak"),
        rank,
        extract_cooldown(ability, rank),
        damage,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", damage, time_offset=0.5),)
    entry["event_order_certified"] = "single arrival explosion"
    entry["detail"] = (
        "Explosion at the afterimage; the sourced self-heal/stasis is not outgoing damage."
    )
    return entry


SLOTS = {
    "P": _resonance_proc,
    "Q": _timewinder,
    "W": _parallel_convergence,
    "E": _phase_dive,
    "R": _chronobreak,
}
parse_abilities = build_parser(SLOTS, "Ekko")

OPTIONS = [
    {
        "key": "p_procs",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 10,
        "label": "Z-Drive Resonance detonations (3 stacks each)",
    },
    {
        "key": "w_passive_ready",
        "type": "bool",
        "default": False,
        "label": "Parallel Convergence passive ready",
    },
    {
        "key": "w_target_missing_health",
        "type": "float",
        "default": 0.5,
        "min": 0.0,
        "max": 1.0,
        "step": 0.05,
        "label": "W target missing-health ratio",
    },
]

ASSUMPTIONS = [
    "Resonance stacks up to 3 (cap) and the third stack consumes all three to detonate; each p_procs entry is one completed 3-stack detonation (30 : 150 by level + 80% AP), priced because the rotation does not imply three prior applications.",
    "Resonance's per-target 4-second stack window and monster 270% multiplier are boundary state; the detonation value is the champion-target sourced value.",
    "Q's return is a separate authored event and W's passive is disabled unless the target-health gate is selected.",
    "Chronobreak's heal, stasis and movement are recorded as non-TDD state; only the arrival explosion enters damage.",
]

SOURCES = [
    source_row(
        "Ekko parent entry",
        "https://wiki.leagueoflegends.com/en-us/Ekko",
        4007951,
        "2026-04-12T23:57:12Z",
    ),
    source_row(
        "Ekko Q template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Ekko/Q",
        2863934,
        "2019-11-03T19:56:51Z",
    ),
    source_row(
        "Ekko W template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Ekko/W",
        2864229,
        "2019-11-03T20:09:38Z",
    ),
    source_row(
        "Ekko E template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Ekko/E",
        2864375,
        "2019-11-03T20:12:09Z",
    ),
    source_row(
        "Ekko R template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Ekko/R",
        2864521,
        "2019-11-03T20:15:33Z",
    ),
]
MODULE_COVERAGE = {slot: "modeled" for slot in ("P", "Q", "W", "E", "R")}
REVIEW_STATUS = "reviewed_module"
