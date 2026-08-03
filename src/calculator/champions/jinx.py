"""Jinx's reviewed packet module.

Switcheroo is a stat/auto-mode ability rather than a spell hit.  Keeping it
in the champion module matters for BIS: Fishbones changes each basic attack
to 110% AD while Pow-Pow's Rev'd Up changes attack cadence.  The W/E/R packet
damage is sourced from the same Wiki snapshot as the generated roster.
"""

from typing import Any

from .engine import BUFF, SlotCtx, build_parser
from .packet_module import build_packet_module
from .slotlib import damage_entry, extract_cooldown, extract_value

_packet_parse, _packet_slots, _packet_assumptions, _packet_sources, _ = (
    build_packet_module("Jinx")
)


def _switcheroo(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    weapon = str(ctx.options.get("jinx_weapon", "minigun")).lower()
    entry = damage_entry(
        ability.get("name", "Switcheroo!"),
        rank,
        extract_cooldown(ability, rank),
        0.0,
        "physical",
    )
    if weapon in {"rocket", "fishbones"}:
        entry["auto_attack_override"] = {
            "name": "Fishbones rockets",
            "damage_ratio": 1.10,
            "damage_type": "physical",
        }
        entry["detail"] = "Fishbones: 110% AD basic attacks"
    else:
        stacks = int(ctx.options.get("jinx_rev_up_stacks", 3))
        stacks = min(max(stacks, 0), 3)
        first = extract_value(ability, "Bonus Attack Speed", rank)
        subsequent = extract_value(ability, "Attack Speed per Subsequent Stack", rank)
        bonus_as = 0.0 if stacks <= 0 else first + max(0, stacks - 1) * subsequent
        ctx.stats["attack_speed"] = (
            ctx.stats.get("attack_speed", 0.0)
            + ctx.stats.get("attack_speed_ratio", 0.0) * bonus_as / 100.0
        )
        entry["stat_buff"] = {"bonus_attack_speed": bonus_as}
        entry["detail"] = (
            f"Pow-Pow: {stacks} Rev'd Up stack(s), {bonus_as:g}% bonus attack speed"
        )
    return entry


_switcheroo.phase = BUFF


def _get_excited(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    stacks = int(ctx.options.get("jinx_get_excited_stacks", 0))
    stacks = min(max(stacks, 0), 5)
    if stacks == 0:
        return None
    bonus_total_as = 25.0 * stacks
    entry = damage_entry(
        ability.get("name", "Get Excited!"),
        1,
        0.0,
        0.0,
        "physical",
    )
    entry["stat_buff"] = {"total_attack_speed_percent": bonus_total_as}
    entry["detail"] = (
        f"{stacks} champion takedown stack(s), {bonus_total_as:g}% total attack speed"
    )
    return entry


_get_excited.phase = BUFF

SLOTS = {**_packet_slots, "P": _get_excited, "Q": _switcheroo}
parse_abilities = build_parser(SLOTS, "Jinx")

OPTIONS = [
    {
        "key": "jinx_weapon",
        "type": "select",
        "default": "minigun",
        "label": "Q weapon",
        "choices": [
            {"value": "minigun", "label": "Pow-Pow minigun"},
            {"value": "rocket", "label": "Fishbones rocket launcher"},
        ],
    },
    {
        "key": "jinx_rev_up_stacks",
        "type": "int",
        "default": 3,
        "min": 0,
        "max": 3,
        "label": "Pow-Pow Rev'd Up stacks",
    },
    {
        "key": "jinx_get_excited_stacks",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 5,
        "label": "Get Excited! champion stacks",
    },
]

ASSUMPTIONS = [
    "Pow-Pow uses the selected Rev'd Up stack count; Fishbones uses 110% AD per basic attack.",
    "Get Excited! is opt-in because takedowns are not implied by a damage package.",
    "W, E, and R use the pinned Wiki rank packets; R's missing-health term is evaluated after prior damage events.",
]
SOURCES = list(_packet_sources) + [
    {
        "label": "Jinx Switcheroo!",
        "url": "https://wiki.leagueoflegends.com/en-us/Jinx",
        "revision_id": 4027661,
        "revision_timestamp": "2026-06-12T16:55:08Z",
    },
]
