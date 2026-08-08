"""Graves' pellet autos, delayed Q detonation and True Grit state."""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from .engine import BUFF, SlotCtx, build_parser
from .module_helpers import no_damage, source_row
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    find_named_leveling,
    sum_modifiers,
)


def _level_scaling(
    ability: dict[str, Any],
    occurrence: int,
    level: int,
    stats: dict[str, float],
    target: dict[str, float],
) -> float:
    leveling = find_named_leveling(ability, "Per-Level Scaling", occurrence)
    if leveling is None:
        return 0.0
    return sum_modifiers(leveling, level, stats, target)


def _new_destiny(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    total_ratio = _level_scaling(ability, 2, ctx.level, ctx.stats, ctx.target)
    critical = bool(ctx.options.get("p_critical_pellets", False))
    if critical:
        total_ratio = _level_scaling(ability, 3, ctx.level, ctx.stats, ctx.target)
    entry = no_damage(
        ctx,
        name="New Destiny",
        reason="Shotgun reload/pellet state is explicit; all pellets hitting one target is the selected auto packet.",
        slot="P",
    )
    if entry is not None:
        entry["auto_attack_override"] = {
            "name": "Graves shotgun (all pellets on target)",
            "damage_ratio": total_ratio / 100.0,
            "damage_type": "physical",
        }
        entry["detail"] = (
            f"{total_ratio:g}% AD across the authored pellet cone; critical pellet branch={'on' if critical else 'off'}."
        )
    return entry


def _end_of_line(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    initial = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    detonation = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "End of the Line"),
        rank,
        extract_cooldown(ability, rank),
        initial + detonation,
        "physical",
    )
    entry["parts"] = (
        DamagePart("physical", initial, time_offset=0.25),
        DamagePart("physical", detonation, time_offset=2.25),
    )
    entry["detail"] = (
        "Round pass plus powder-trail detonation; terrain collision shortens the sourced delay."
    )
    return entry


def _smoke_screen(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    value = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Smoke Screen"),
        rank,
        extract_cooldown(ability, rank),
        value,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", value, time_offset=0.25),)
    entry["detail"] = (
        "Impact damage plus 4-second nearsight cloud; slow/vision are utility."
    )
    return entry


def _quickdraw(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    stacks = min(max(int(ctx.options.get("e_true_grit_stacks", 1)), 0), 8)
    armor = extract_named(ability, "Bonus Armor", rank, ctx.stats, ctx.target) * stacks
    mr = (
        extract_named(ability, "Bonus Magic Resistance", rank, ctx.stats, ctx.target)
        * stacks
    )
    entry = no_damage(
        ctx,
        name=ability.get("name", "Quickdraw"),
        reason=f"{stacks} True Grit stack(s): +{armor:g} armor/+{mr:g} MR; dash/reload are state-only.",
    )
    if entry is not None:
        entry["stat_buff"] = {"armor": armor, "magic_resistance": mr}
    return entry


_quickdraw.phase = BUFF


def _collateral_damage(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    secondary = bool(ctx.options.get("r_secondary_target", False))
    attr = "Reduced Damage" if secondary else "Physical Damage"
    value = extract_named(ability, attr, rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Collateral Damage"),
        rank,
        extract_cooldown(ability, rank),
        value,
        "physical",
    )
    entry["parts"] = (DamagePart("physical", value, time_offset=0.25),)
    entry["detail"] = (
        "Primary shell or reduced cone explosion branch selected explicitly."
    )
    return entry


SLOTS = {
    "P": _new_destiny,
    "Q": _end_of_line,
    "W": _smoke_screen,
    "E": _quickdraw,
    "R": _collateral_damage,
}
parse_abilities = build_parser(SLOTS, "Graves")

OPTIONS = [
    {
        "key": "p_critical_pellets",
        "type": "bool",
        "default": False,
        "label": "Critical pellet branch",
    },
    {
        "key": "e_true_grit_stacks",
        "type": "int",
        "default": 1,
        "min": 0,
        "max": 8,
        "label": "True Grit stacks",
    },
    {
        "key": "r_secondary_target",
        "type": "bool",
        "default": False,
        "label": "Collateral Damage secondary cone",
    },
]

ASSUMPTIONS = [
    "The auto packet assumes all pellets hit the primary target; reload timing is exposed as state rather than replacing the attack stream with guessed cadence.",
    "End of the Line keeps pass and detonation as separate ordered physical events; terrain collision is an explicit source note.",
    "True Grit armor/MR is a selected defensive state and cannot inflate outgoing damage.",
]

SOURCES = [
    source_row(
        "Graves parent entry",
        "https://wiki.leagueoflegends.com/en-us/Graves",
        3892615,
        "2025-05-02T11:24:28Z",
    ),
    source_row(
        "Graves Q template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Graves/Q",
        2863946,
        "2019-11-03T19:57:03Z",
    ),
    source_row(
        "Graves W template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Graves/W",
        2864241,
        "2019-11-03T20:09:50Z",
    ),
    source_row(
        "Graves E template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Graves/E",
        2864387,
        "2019-11-03T20:12:20Z",
    ),
    source_row(
        "Graves R template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Graves/R",
        2864533,
        "2019-11-03T20:15:45Z",
    ),
]
MODULE_COVERAGE = {slot: "modeled" for slot in ("P", "Q", "W", "E", "R")}
REVIEW_STATUS = "reviewed_module"
