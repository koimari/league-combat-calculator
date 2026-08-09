"""Fiora's vital proc, on-hit Lunge and two-attack Bladework."""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .module_helpers import no_damage, source_row
from .slotlib import damage_entry, extract_cooldown, extract_named, proc_damage


def _vital(ctx: SlotCtx, ability: dict[str, Any]) -> float:
    return extract_named(ability, "Bonus Damage", ctx.level, ctx.stats, ctx.target)


_vital_proc = proc_damage(
    _vital,
    "true",
    count_option="p_vitals",
    default_count=0,
    name="Duelist's Dance vital",
    phase_order_events=True,
)


def _lunge(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    value = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Lunge"),
        rank,
        extract_cooldown(ability, rank),
        value,
        "physical",
    )
    entry["parts"] = (DamagePart("physical", value, basic_damage=True),)
    entry["applies_item_on_hits"] = {
        "effectiveness": 1.0,
        "hits": 1,
        "triggers": ("on_hit",),
    }
    entry["detail"] = "Lunge's stab applies one full-effectiveness on-hit package."
    return entry


def _riposte(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    value = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Riposte"),
        rank,
        extract_cooldown(ability, rank),
        value,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", value, time_offset=0.5),)
    entry["detail"] = (
        "Defensive stance/stun branch is retained as control state; the shock is one magic hit."
    )
    return entry


def _bladework(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    attacks = min(max(int(ctx.options.get("e_attacks", 2)), 1), 2)
    entry = no_damage(
        ctx,
        name=ability.get("name", "Bladework"),
        reason=f"{attacks} empowered basic attack(s); first cannot crit and second uses the sourced modified critical damage.",
    )
    if entry is None:
        return None
    entry["empowers_next_auto"] = {"hits": attacks}
    entry["detail"] = (
        "Bladework's attack timer reset and slow are state-only; on-hit items ride the attacks."
    )
    return entry


def _grand_challenge(ctx: SlotCtx) -> dict[str, Any] | None:
    return no_damage(
        ctx,
        name="Grand Challenge",
        reason="Vital highlighting and Victory Zone healing are explicit challenge state, not outgoing damage.",
    )


SLOTS = {
    "P": _vital_proc,
    "Q": _lunge,
    "W": _riposte,
    "E": _bladework,
    "R": _grand_challenge,
}
parse_abilities = build_parser(SLOTS, "Fiora")

OPTIONS = [
    {
        "key": "p_vitals",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 4,
        "label": "Duelist's Dance vitals triggered",
    },
    {
        "key": "e_attacks",
        "type": "int",
        "default": 2,
        "min": 1,
        "max": 2,
        "label": "Bladework attacks",
    },
]

ASSUMPTIONS = [
    "Vitals are explicit true-damage procs; the user supplies how many directional hits actually occur.",
    "Lunge is a real attack for item on-hit purposes, while Bladework's first/second crit distinction remains visible in its option detail.",
    "Grand Challenge's Victory Zone heals are not TDD and are not converted into damage.",
]

SOURCES = [
    source_row(
        "Fiora parent entry",
        "https://wiki.leagueoflegends.com/en-us/Fiora",
        3892617,
        "2025-05-02T11:24:34Z",
    ),
    source_row(
        "Fiora Q template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Fiora/Q",
        2863939,
        "2019-11-03T19:56:56Z",
    ),
    source_row(
        "Fiora W template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Fiora/W",
        2864234,
        "2019-11-03T20:09:43Z",
    ),
    source_row(
        "Fiora E template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Fiora/E",
        2864380,
        "2019-11-03T20:12:13Z",
    ),
    source_row(
        "Fiora R template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Fiora/R",
        2864526,
        "2019-11-03T20:15:38Z",
    ),
]
MODULE_COVERAGE = {slot: "modeled" for slot in ("P", "Q", "W", "E", "R")}
REVIEW_STATUS = "reviewed_module"

from .. import healing_helpers as _healing  # pylint: disable=wrong-import-position


# pylint: disable=protected-access,too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument,wrong-import-position
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Resolve Fiora self-healing events from its authored packet."""
    healing = []
    p_level = int(champion_stats.get("level", 0) or 0)
    p_heal = _healing.extract_named(
        _healing._ability(champion_data, "P"), "Bonus Damage", p_level, champion_stats
    )
    for event in _healing._attributed_events(
        damage_events, lambda source, _event: source == "passive"
    ):
        _healing._heal_from_damage(healing, event, p_heal, "Duelist's Dance")
    return sorted(healing, key=lambda event: (event["time"], event["source"]))


from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Fiora", derive_self_healing)
