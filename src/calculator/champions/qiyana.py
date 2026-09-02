"""Qiyana's element and on-hit state packets."""

from typing import Any

from ..ability_spec import DamagePart
from .engine import CC_PER_PART, ONHIT, SlotCtx, build_parser
from .inputs import bool_option, int_option
from .module_helpers import named_damage, ranked_slot
from .slotlib import (
    ability_name,
    ability_on_hit_entry,
    damage_entry,
    extract_cooldown,
    extract_named,
    on_hit_entry,
    simple_damage,
)
from .source_receipts import load_champion_sources


def _royal_privilege(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability("P")
    if ability is None:
        return None
    total = extract_named(
        ability, "Bonus Physical Damage", ctx.level, ctx.stats, ctx.target
    )
    return on_hit_entry("Royal Privilege", total, "physical")


_royal_privilege.phase = ONHIT


# Q's control is a property of the element, so it is authored per cast
# rather than in MODULE_CC.  The unelemented slash "deal[s] physical damage
# to enemies in a line" and the terrain blast only "deals 60% increased
# damage against enemies below 50%" — neither applies control.  Index 1 is
# the option's grouped "brush/river" element, and those two disagree
# (brush grants Qiyana invisibility; river "roots enemies hit for 0.5
# seconds, then slows them by 20%"), so that index is left unreviewed
# rather than answered with a kind only one of its two elements applies.
_Q_CC_BY_VARIANT = ("none", None, "none")


def _edge_of_ixtal(ctx: SlotCtx) -> dict[str, Any] | None:
    ability_index = 1 if int(ctx.option("q_variant")) > 0 else 0
    ranked = ctx.ranked("Q", ability_index)
    if ranked is None:
        return None
    ability, rank = ranked
    variant = min(max(int(ctx.option("q_variant")), 0), 2)
    low_health = bool(ctx.option("q_target_below_half"))
    attr = "Increased Damage" if variant == 2 and low_health else "Physical Damage"
    total = extract_named(ability, attr, rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ctx.ability("Q", 0) or ability, rank),
        total,
        "physical",
    )
    entry["parts"] = (
        (
            DamagePart(
                "physical", total, time_offset=0.0, cc_kind=_Q_CC_BY_VARIANT[variant]
            )
            if _Q_CC_BY_VARIANT[variant] is not None
            else DamagePart("physical", total, time_offset=0.0)
        ),
    )
    entry["detail"] = (
        "Terrain element, target below 50% HP"
        if variant == 2 and low_health
        else "Elemental Q"
    )
    return entry


@ranked_slot
def _terrashape(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """Terrashape's bonus is an on-hit rider, not a direct spell hit."""
    total = extract_named(ability, "Bonus Magic Damage", rank, ctx.stats, ctx.target)
    return ability_on_hit_entry(
        "Terrashape element",
        rank,
        "magic",
        {
            "name": "Terrashape element (on-hit)",
            "damage_per_hit": total,
            "damage_type": "magic",
        },
    )


_terrashape.phase = ONHIT


_supreme_display = named_damage("Physical Damage", "physical", time_offset=0.0)


SLOTS = {
    "P": _royal_privilege,
    "Q": _edge_of_ixtal,
    "W": _terrashape,
    # Audacity's dash lands one hit on arrival with no sourced sub-cast
    # phase, so it certifies the cast boundary its reviewed answer rides on.
    "E": simple_damage(
        attr="Physical Damage",
        dmg_type="physical",
        event_order_certified="single_hit",
    ),
    "R": _supreme_display,
}

# Cached kit review.  E's dash "deals physical damage" and nothing else.
# R's windblast knocks back but damages nobody; the damage row this module
# prices is the cascading shockwave, which is "dealing physical damage to
# enemies hit, stunning them for 0.5 : 1 (based on proximity) seconds", so
# the stun is what the damaging part applies.  Q answers per cast instead
# of here because its control belongs to the element (``_edge_of_ixtal``).
# P and W are absent: both are on-hit riders on the auto stream.
MODULE_CC = {"Q": CC_PER_PART, "E": "none", "R": "stun", "P": "none", "W": "none"}

parse_abilities = build_parser(SLOTS, "Qiyana", cc_kinds=MODULE_CC)

OPTIONS = [
    int_option(
        "q_variant",
        0,
        minimum=0,
        maximum=2,
        label="Q element (edge, brush/river, terrain)",
    ),
    bool_option(
        "q_target_below_half", False, label="Terrain Q target below 50% health"
    ),
]

ASSUMPTIONS = [
    "Royal Privilege and Terrashape are modeled as on-hit riders; they are not free "
    "direct spell damage.",
    "Terrain Q's increased damage is enabled only when the target-below-half state is explicit.",
    "Element control and per-target passive cooldowns remain explicit scenario state.",
]

SOURCES = load_champion_sources("Qiyana")
