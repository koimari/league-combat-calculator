"""Graves' pellet autos, delayed Q detonation and True Grit state."""

from __future__ import annotations

import re
from typing import Any

from .engine import BUFF, SlotCtx, build_parser
from .inputs import bool_option, int_option
from .module_helpers import named_damage, no_damage, ranked_slot
from .shared_mechanics import multi_pass_damage
from .slot_extract import (
    ability_name,
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


_end_of_line = multi_pass_damage(
    "physical",
    passes=(("Physical Damage", 0.25), ("Physical Damage", 2.25)),
    detail=(
        "Round pass plus powder-trail detonation; terrain collision shortens the sourced delay."
    ),
)


_smoke_screen = named_damage(
    "Magic Damage",
    "magic",
    time_offset=0.25,
    detail="Impact damage plus 4-second nearsight cloud; slow/vision are utility.",
)


_TRUE_GRIT_RE = re.compile(
    r"generating a stack of True Grit for (?P<seconds>\d+(?:\.\d+)?) seconds, "
    r"stacking up to (?P<stacks>\d+) times"
)


def _true_grit_stack_terms(ability: dict[str, Any]) -> tuple[int, float]:
    """True Grit's cached stack cap and the seconds one stack stands."""
    effects = ability.get("effects")
    for effect in effects if effects else ():
        description = effect.get("description")
        if description is None:
            continue
        match = _TRUE_GRIT_RE.search(str(description))
        if match is not None:
            return int(match.group("stacks")), float(match.group("seconds"))
    raise ValueError(
        "Graves E: the cached active no longer states True Grit's stack life "
        "and cap ('a stack of True Grit for N seconds, stacking up to N times')"
    )


@ranked_slot
def _quickdraw(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    per_armor = extract_named(ability, "Bonus Armor", rank, ctx.stats, ctx.target)
    per_mr = extract_named(
        ability, "Bonus Magic Resistance", rank, ctx.stats, ctx.target
    )
    requested = ctx.options.get("e_true_grit_stacks")
    max_stacks, seconds = _true_grit_stack_terms(ability)
    if requested is None:
        entry = no_damage(
            ctx,
            name=ability_name(ability),
            reason=(
                f"True Grit: +{per_armor:g} armor and +{per_mr:g} MR per stack, "
                f"up to {max_stacks} held for {seconds:g}s each; the fight walks "
                "the casts of Quickdraw that stack them.  Dash and reload are "
                "state-only."
            ),
        )
        if entry is not None:
            # Only Quickdraw stacks it, and a dash TOWARD a champion banks two
            # where this walks one, so the level is a floor. The cooldown the
            # schedule uses carries haste but not the pellet refund, which is
            # the same floor from the other side.
            entry["stat_ramp"] = {
                "per_stack": {"armor": per_armor, "magic_resistance": per_mr},
                "max_stacks": max_stacks,
                "stack_duration": seconds,
                "stacks_from_ability_casts": True,
                "arming_slots": ("E",),
                "requested": False,
            }
        return entry
    stacks = min(max(int(requested), 0), max_stacks)
    armor = per_armor * stacks
    mr = per_mr * stacks
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
MODULE_CC = {"Q": "none", "W": "slow", "R": "none", "P": "none", "E": "none"}

parse_abilities = build_parser(SLOTS, "Graves", cc_kinds=MODULE_CC)

OPTIONS = [
    bool_option("p_critical_pellets", False, label="Critical pellet branch"),
    int_option(
        "e_true_grit_stacks",
        1,
        minimum=0,
        maximum=8,
        label=(
            "True Grit stacks; unset walks the ramp over the Quickdraw casts "
            "and serves its fight mean"
        ),
    ),
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
