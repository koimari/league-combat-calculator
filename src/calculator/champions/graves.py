"""Graves' pellet autos, delayed Q detonation and True Grit state."""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from .engine import BUFF, SlotCtx, build_parser
from .inputs import bool_option, int_option
from .module_helpers import named_damage, no_damage, ranked_slot
from .slotlib import (
    ability_name,
    damage_entry,
    extract_cooldown,
    extract_named,
    find_named_leveling,
    sum_modifiers,
)
from .source_receipts import load_champion_sources


def _level_scaling(
    ability: dict[str, Any],
    occurrence: int,
    level: int,
    stats: dict[str, float],
    *,
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
    total_ratio = _level_scaling(ability, 2, ctx.level, ctx.stats, target=ctx.target)
    critical = bool(ctx.option("p_critical_pellets"))
    if critical:
        total_ratio = _level_scaling(
            ability, 3, ctx.level, ctx.stats, target=ctx.target
        )
    entry = no_damage(
        ctx,
        name="New Destiny",
        reason=(
            "Shotgun reload/pellet state is explicit; all pellets hitting one target "
            "is the selected auto packet."
        ),
        slot="P",
    )
    if entry is not None:
        entry["auto_attack_override"] = {
            "name": "Graves shotgun (all pellets on target)",
            "damage_ratio": total_ratio / 100.0,
            "damage_type": "physical",
        }
        entry["detail"] = (
            f"{total_ratio:g}% AD across the authored pellet cone; critical pellet "
            f"branch={'on' if critical else 'off'}."
        )
    return entry


@ranked_slot
def _end_of_line(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    initial = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    detonation = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability_name(ability),
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


_smoke_screen = named_damage(
    "Magic Damage",
    "magic",
    time_offset=0.25,
    detail="Impact damage plus 4-second nearsight cloud; slow/vision are utility.",
)


@ranked_slot
def _quickdraw(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    stacks = min(max(int(ctx.option("e_true_grit_stacks")), 0), 8)
    armor = extract_named(ability, "Bonus Armor", rank, ctx.stats, ctx.target) * stacks
    mr = (
        extract_named(ability, "Bonus Magic Resistance", rank, ctx.stats, ctx.target)
        * stacks
    )
    entry = no_damage(
        ctx,
        name=ability_name(ability),
        reason=(
            f"{stacks} True Grit stack(s): +{armor:g} armor/+{mr:g} MR; dash/reload "
            f"are state-only."
        ),
    )
    if entry is not None:
        entry["stat_buff"] = {"armor": armor, "magic_resistance": mr}
    return entry


_quickdraw.phase = BUFF


_collateral_damage = named_damage(
    lambda ctx: (
        "Reduced Damage"
        if bool(ctx.option("r_secondary_target"))
        else "Physical Damage"
    ),
    "physical",
    time_offset=0.25,
    detail="Primary shell or reduced cone explosion branch selected explicitly.",
)


SLOTS = {
    "P": _new_destiny,
    "Q": _end_of_line,
    "W": _smoke_screen,
    "E": _quickdraw,
    "R": _collateral_damage,
}
# W's canister "slows them by 50% for 0.5 seconds" (its nearsight is not an
# immobilize and has no kind in the vocabulary); Q's round and detonation
# and R's shell only damage.  P's Buckshot knockback lands on non-champion
# units only, and the row authors no damage part anyway; E deals no damage.
MODULE_CC = {"Q": "none", "W": "slow", "R": "none"}

parse_abilities = build_parser(SLOTS, "Graves", cc_kinds=MODULE_CC)

OPTIONS = [
    bool_option("p_critical_pellets", False, label="Critical pellet branch"),
    int_option("e_true_grit_stacks", 1, minimum=0, maximum=8, label="True Grit stacks"),
    bool_option("r_secondary_target", False, label="Collateral Damage secondary cone"),
]

ASSUMPTIONS = [
    "The auto packet assumes all pellets hit the primary target; reload timing is "
    "exposed as state rather than replacing the attack stream with guessed cadence.",
    "End of the Line keeps pass and detonation as separate ordered physical events; "
    "terrain collision is an explicit source note.",
    "True Grit armor/MR is a selected defensive state and cannot inflate outgoing damage.",
]

SOURCES = load_champion_sources("Graves")
