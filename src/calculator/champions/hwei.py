"""Hwei's three-subject variants, Signature explosion and despair timeline."""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from .engine import CC_PER_PART, SlotCtx, build_parser
from .inputs import float_option, int_option
from .module_helpers import level_row, no_damage, ranked_slot
from .slotlib import (
    ability_name,
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    proc_damage,
)
from .source_receipts import load_champion_sources


def _signature(ctx: SlotCtx) -> dict[str, Any] | None:
    """Emit Hwei's sourced Signature detonation as an explicit proc count."""
    ability = ctx.ability("P", 0)
    if ability is None:
        return None

    entry = proc_damage(
        level_row("Per-Level Scaling"),
        "magic",
        count_option="p_triggers",
        default_count=1,
        name=ability_name(ability),
        phase_order_events=True,
    )(ctx)
    if entry is not None:
        entry["detail"] = (
            f"{entry['proc_count']} completed Signature mark(s); each sourced mark "
            f"detonates once after the second spell hit."
        )
    return entry


def _subject_damage(ctx: SlotCtx) -> dict[str, Any] | None:
    variant = min(max(int(ctx.option("q_variant")), 0), 2)
    ranked = ctx.ranked("Q", variant + 1)
    if ranked is None:
        return None
    ability, rank = ranked
    if variant == 0:
        value = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
        parts = (DamagePart("magic", value, time_offset=0.25, cc_kind="none"),)
        detail = (
            "Devastating Fire; target-max-health scaling and its monster cap remain "
            "source-backed."
        )
    elif variant == 1:
        base = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
        maximum = extract_named(ability, "Maximum Damage", rank, ctx.stats, ctx.target)
        missing = min(max(float(ctx.option("q_missing_health")), 0.0), 1.0)
        value = base + (maximum - base) * missing
        parts = (
            DamagePart(
                "magic",
                base,
                hp_scaled_damage=lambda ratio: base + (maximum - base) * ratio,
                time_offset=1.0,
                cc_kind="none",
            ),
        )
        detail = (
            f"Severing Bolt missing-health fraction {missing:.2f}; "
            f"isolated/immobilized target gate is explicit."
        )
    else:
        explosions = min(max(int(ctx.option("q_explosions")), 1), 7)
        shock = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
        fissure = extract_named(
            ability, "Total Fissure Magic Damage", rank, ctx.stats, ctx.target
        )
        value = shock * explosions + fissure * explosions
        # The shockwave only damages; the lava fissure it leaves behind is
        # the packet that "slow[s] them by 35%".
        parts = (
            DamagePart(
                "magic",
                shock,
                count=explosions,
                time_offset=0.6,
                hit_interval=0.2,
                cc_kind="none",
            ),
            DamagePart(
                "magic",
                fissure,
                count=explosions,
                time_offset=0.8,
                hit_interval=0.2,
                cc_kind="slow",
            ),
        )
        detail = (
            f"Molten Fissure: {explosions} shockwaves plus one sourced fissure packet "
            f"per eruption."
        )
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        value,
        "magic",
    )
    entry["parts"] = parts
    entry["detail"] = detail
    return entry


def _serenity(ctx: SlotCtx) -> dict[str, Any] | None:
    variant = min(max(int(ctx.option("w_variant")), 0), 2)
    ranked = ctx.ranked("W", variant + 1)
    if ranked is None:
        return None
    ability, rank = ranked
    if variant == 0:
        return no_damage(
            ctx,
            name=ability_name(ability),
            reason="Movement-speed path and ghosting are utility state.",
            slot="W",
        )
    if variant == 1:
        shield = extract_named(
            ability, "Total Maximum Shield", rank, ctx.stats, ctx.target
        )
        return no_damage(
            ctx,
            name=ability_name(ability),
            reason=(
                f"Protective pool; maximum self shield is {shield:g} and ally "
                f"reduction is source-backed."
            ),
            slot="W",
        )
    bonus = extract_named(ability, "Bonus Magic Damage", rank, ctx.stats, ctx.target)
    hits = min(max(int(ctx.option("we_hits")), 1), 3)
    entry = no_damage(
        ctx,
        name=ability_name(ability),
        reason=f"Three empowered hits; {hits} next-hit charges selected.",
        slot="W",
    )
    if entry is not None:
        entry["on_hit"] = {
            "name": "Stirring Lights",
            "damage_per_hit": bonus,
            "damage_type": "magic",
        }
        entry["detail"] = (
            f"{hits} sourced hit(s) receive {bonus:g} bonus magic damage and mana restoration."
        )
    return entry


def _torment(ctx: SlotCtx) -> dict[str, Any] | None:
    variant = min(max(int(ctx.option("e_variant")), 0), 2)
    ranked = ctx.ranked("E", variant + 1)
    if ranked is None:
        return None
    ability, rank = ranked
    value = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        value,
        "magic",
    )
    # One kind per subject, read off each one's own text: Grim Visage
    # "fears them", Gaze of the Abyss "root[s] them", Crushing Maw slows
    # everything it damages (its pull only catches enemies off-centre).
    # The first two carry a sourced duration row; Crushing Maw's cached
    # rows hold the slow's percentage only, so its interval stays unstated
    # rather than invented.
    kind = ("fear", "root", "slow")[variant]
    duration_attr = ("Disable Duration", "Root Duration", None)[variant]
    entry["parts"] = (
        DamagePart(
            "magic",
            value,
            time_offset=0.6 if variant == 2 else 0.3,
            cc_kind=kind,
            cc_duration=(
                extract_value(ability, duration_attr, rank) if duration_attr else 0.0
            ),
        ),
    )
    entry["detail"] = ("Grim Visage", "Gaze of the Abyss", "Crushing Maw")[
        variant
    ] + "; fear/root/pull are explicit control state."
    return entry


@ranked_slot
def _despair(ctx: SlotCtx, ability: dict[str, Any], rank: int) -> dict[str, Any] | None:
    tick = extract_named(ability, "Magic Damage per Tick", rank, ctx.stats, ctx.target)
    explosion = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    # Each tick applies a Despair stack, and "for each stack, the target is
    # slowed by 10%"; the terminal explosion removes the stacks instead of
    # applying anything.
    parts = (
        DamagePart(
            "magic", tick, count=12, time_offset=0.0, hit_interval=0.25, cc_kind="slow"
        ),
        DamagePart("magic", explosion, time_offset=3.0, cc_kind="none"),
    )
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        tick * 12 + explosion,
        "magic",
    )
    entry["parts"] = parts
    entry["event_order_certified"] = "twelve ticks then terminal explosion"
    entry["detail"] = (
        "Three-second aura: twelve 0.25-second Despair ticks and the sourced terminal explosion."
    )
    return entry


SLOTS = {
    "P": _signature,
    "Q": _subject_damage,
    "W": _serenity,
    "E": _torment,
    "R": _despair,
}
# Only P has one answer for the whole slot — the Signature explosion just
# damages.  Every other damaging slot is a mood subject whose control
# differs per variant (and, in QE and R, per part), so those kinds are
# authored on the parts above rather than here.  W's three subjects author
# no damage part at all.
MODULE_CC = {"P": "none", "Q": CC_PER_PART, "E": CC_PER_PART, "R": CC_PER_PART}

parse_abilities = build_parser(SLOTS, "Hwei", cc_kinds=MODULE_CC)
OPTIONS = [
    int_option(
        "q_variant", 0, minimum=0, maximum=2, label="Disaster subject (QQ/QW/QE)"
    ),
    float_option(
        "q_missing_health",
        1.0,
        minimum=0.0,
        maximum=1.0,
        label="Severing Bolt missing-health fraction",
        step=0.1,
    ),
    int_option(
        "q_explosions", 7, minimum=1, maximum=7, label="Molten Fissure explosions"
    ),
    int_option(
        "w_variant", 0, minimum=0, maximum=2, label="Serenity subject (WQ/WW/WE)"
    ),
    int_option("we_hits", 3, minimum=1, maximum=3, label="Stirring Lights hits"),
    int_option(
        "e_variant", 0, minimum=0, maximum=2, label="Torment subject (EQ/EW/EE)"
    ),
    int_option("p_triggers", 1, minimum=0, maximum=8, label="Signature detonations"),
]
ASSUMPTIONS = [
    "The three subject toggles are state-only; the selected QQ/QW/QE, WQ/WW/WE and "
    "EQ/EW/EE entries are explicit variants.",
    "Severing Bolt exposes the source maximum-damage branch without assuming the "
    "immobilized/isolated target gate.",
    "Signature marks and Stirring Lights charges are visible state; no same-cast mark "
    "consumption is inferred.",
]
SOURCES = load_champion_sources("Hwei")
