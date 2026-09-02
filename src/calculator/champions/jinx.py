"""Jinx's reviewed packet module.

Switcheroo is a stat/auto-mode ability rather than a spell hit.  Keeping it
in the champion module matters for BIS: Fishbones changes each basic attack
to 110% AD while Pow-Pow's Rev'd Up changes attack cadence.  The W/E/R packet
damage is sourced from the same Wiki snapshot as the generated roster.
"""

from typing import Any

from ..binary_roots import data_value, spell_object
from .engine import BUFF, SlotCtx
from .inputs import int_option
from .packet_module import build_packet_module
from .slotlib import ability_name, damage_entry, extract_cooldown, extract_value

PACKET_SHA256 = "8e7f7c3e75ab1a7eb65ec2d5deb23878aa47b44ee0044807d13f064afc55cafd"

# Flame Chompers do not damage at the cast: the Chompers are "landing
# after 0.4 seconds, arming after 0.5 seconds, and exploding after 5
# seconds to deal magic damage to nearby enemies", and "Each Chomper
# explodes on contact with an enemy champion, knocking them down and
# rooting them for 1.5 seconds".  Against a champion standing in them the
# explosion is the contact one, so the earliest instant this row's damage
# can land is the arming time — the 5-second figure is the untouched
# timeout, not the champion case.
_E_ARMING_SECONDS = data_value(spell_object("Jinx", "JinxE"), "GrenadeArmTime")
_JINX_PASSIVE_AS_PERCENT = data_value(
    spell_object("Jinx", "JinxPassiveMarker"), "ASBuff"
)


def _switcheroo(ctx: SlotCtx) -> dict[str, Any] | None:
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    weapon = str(ctx.option("jinx_weapon")).lower()
    entry = damage_entry(
        ability_name(ability),
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
        stacks = int(ctx.option("jinx_rev_up_stacks"))
        stacks = min(max(stacks, 0), 3)
        first = extract_value(ability, "Bonus Attack Speed", rank)
        subsequent = extract_value(ability, "Attack Speed per Subsequent Stack", rank)
        bonus_as = 0.0 if stacks <= 0 else first + max(0, stacks - 1) * subsequent
        ctx.stats["attack_speed"] = (
            ctx.stat("attack_speed") + ctx.stat("attack_speed_ratio") * bonus_as / 100.0
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
    stacks = int(ctx.option("jinx_get_excited_stacks"))
    stacks = min(max(stacks, 0), 5)
    if stacks == 0:
        return None
    bonus_total_as = _JINX_PASSIVE_AS_PERCENT * stacks
    entry = damage_entry(
        ability_name(ability),
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


# Reviewed crowd control, read from the cached kit.  R's rocket only
# explodes for damage and sight.  W's blast "deals physical damage to the
# first enemy it hits and reveals and slows them for 2 seconds".  E's
# Chomper "explodes on contact with an enemy champion, knocking them down
# and rooting them for 1.5 seconds" — the root is the immobilizing half
# of the same explosion this row prices, now placed at its arming time.
# P and Q are zero-damage stat rows (Get Excited! stacks, the weapon
# toggle).
MODULE_CC = {"W": "slow", "E": "root", "R": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Jinx",
    PACKET_SHA256,
    assumption_overrides=(
        "Pow-Pow uses the selected Rev'd Up stack count; Fishbones uses 110% AD per basic attack.",
        "Get Excited! is opt-in because takedowns are not implied by a damage package.",
        "W, E, and R use the pinned Wiki rank packets; R's missing-health term is evaluated after "
        "prior damage events.",
    ),
    # W's one shock blast lands at the cast: "Jinx fires a shock blast
    # in the target direction that deals physical damage to the first
    # enemy it hits", with no travel duration in the cached entry, and
    # the cast is "from wherever the caster is at the start of the cast
    # time".  R's rocket is likewise one explosion.
    single_hit_slots=frozenset({"W", "R"}),
    packet_part_timings={"E": {"time_offset": _E_ARMING_SECONDS}},
    slot_parsers={
        "P": _get_excited,
        "Q": _switcheroo,
    },
    cc_kinds=MODULE_CC,
)

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
    int_option(
        "jinx_rev_up_stacks", 3, minimum=0, maximum=3, label="Pow-Pow Rev'd Up stacks"
    ),
    int_option(
        "jinx_get_excited_stacks",
        0,
        minimum=0,
        maximum=5,
        label="Get Excited! champion stacks",
    ),
]
