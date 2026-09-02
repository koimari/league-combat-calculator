"""Kayle — full-entry reviewed CP10.3 module.

Option keys consumed by the shared parser: "p_exalted", "e_empowered".

E8d ally-support: W (Celestial Blessing) heals the selected teammate.  The
event is authored by the engine's ally-support scanner from the cached W
leveling (Heal 55-155 + 25% AP; scope one_teammate) at the W cast time; the
module declares W in SLOTS so the fight rotation casts it.
"""

from typing import Any

from ..ability_spec import DamagePart
from ..healing_helpers import ability_json, cast_slot_times, parsed_rank
from .engine import SlotCtx, build_parser
from .healing_contract import self_healing_rule
from .inputs import bool_option
from .module_helpers import (
    REVIEWED_MODULE_ASSUMPTIONS,
    no_damage,
    ranked_slot,
    typed_damage,
)
from .slotlib import (
    ability_name,
    ability_on_hit_entry,
    extract_cooldown,
    extract_named,
    on_hit_entry,
    simple_damage,
)
from .source_receipts import load_champion_sources


def _kayle_passive(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    if ctx.level < 11 or not bool(ctx.option("p_exalted")):
        return no_damage(
            ctx,
            name="Divine Ascent",
            reason=(
                "Before level 11 or without Exalted, Kayle's fire wave is "
                "not available; attack range and Zeal remain state."
            ),
        )
    value = extract_named(
        ability, "Bonus Magic Damage", ctx.level, ctx.stats, ctx.target
    )
    result = on_hit_entry("Divine Ascent (Aflame wave)", value, "magic")
    result["detail"] = (
        "Level 11 Aflame wave on every Exalted basic attack; range and Zeal are state."
    )
    return result


@ranked_slot
def _kayle_e(ctx: SlotCtx, ability: dict[str, Any], rank: int) -> dict[str, Any] | None:
    passive = extract_named(ability, "Passive Damage", rank, ctx.stats, ctx.target)
    active = extract_named(ability, "Bonus Magic Damage", rank, ctx.stats, ctx.target)
    result = ability_on_hit_entry(
        ability_name(ability),
        rank,
        "magic",
        {"name": "Starfire passive", "damage_per_hit": passive, "damage_type": "magic"},
        extract_cooldown(ability, rank),
    )
    result["parts"] = (DamagePart("magic", active, basic_damage=True, time_offset=0.1),)
    result["total_raw"] = active
    result["empowers_next_auto"] = True
    result["target_max_health_sensitive"] = True
    result["detail"] = (
        "Passive on-hit plus one empowered attack; the active rider scales "
        "with target missing health and AP."
    )
    return result


def _kayle_r(ctx: SlotCtx) -> dict[str, Any] | None:
    result = typed_damage(ctx, "Magic Damage", "magic", time_offset=2.5)
    if result:
        result["detail"] = (
            "Divine Judgment damage resolves after the sourced 2.5-second "
            "invulnerability window."
        )
    return result


SLOTS = {
    "P": _kayle_passive,
    # The sword's expansion damages every target it strikes once, at the
    # cast: the boundary claim that carries Q's reviewed slow into the
    # event ledger.
    "Q": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
    "W": lambda ctx: no_damage(
        ctx,
        name="Celestial Blessing",
        reason="Heal, ally targeting and movement speed are support/utility state.",
    ),
    "E": _kayle_e,
    "R": _kayle_r,
}
OPTIONS = [
    bool_option("p_exalted", True, label="Exalted Aflame wave"),
    bool_option("e_empowered", True, label="Starfire empowered attack"),
]
ASSUMPTIONS = list(REVIEWED_MODULE_ASSUMPTIONS)
SOURCES = load_champion_sources("Kayle")

# Cached kit review: Q's struck targets are "slowed for 2 seconds"; R
# rains swords with no control, and the Aflame wave, W's heal and E's
# empowered attack apply none either.
MODULE_CC = {"Q": "slow", "E": "none", "R": "none"}

parse_abilities = build_parser(SLOTS, "Kayle", cc_kinds=MODULE_CC)

_ON_HIT_SPECS: dict[str, dict] = {
    "E": {"effectiveness": 1.0, "hits": 1, "triggers": ("on_hit",)},
}

_parse_abilities = parse_abilities


def parse_abilities(*args, **kwargs):
    """Parse abilities, then declare wiki-sourced item on-hit application."""
    result = _parse_abilities(*args, **kwargs)
    for slot, spec in _ON_HIT_SPECS.items():
        entry = result.get(slot) or (result.get("passive") if slot == "P" else None)
        if entry is not None:
            entry["applies_item_on_hits"] = dict(spec)
    return result


# The wrapper is the module's published parser, so it republishes the
# wiring the inner parser holds — the contract proves declaration and
# wiring are one dict off whichever function the module exports.
parse_abilities.cc_kinds = _parse_abilities.cc_kinds


# pylint: disable=too-many-arguments,too-many-positional-arguments
def derive_self_healing(
    champion_data: dict[str, Any],
    champion_stats: dict[str, float],
    ability_damages: dict[str, dict[str, Any]],
    damage_events: list[dict[str, Any]],
    cast_timeline: list[dict[str, Any]] | None = None,
    fight_duration_seconds: float | None = None,
) -> list[dict[str, Any]]:
    """Price Celestial Blessing's heal: one sourced Heal row per W cast.

    "Kayle blesses herself and the target allied champion, healing them"
    — the heal is paid on the cast, not on damage, so it rides the cast
    timeline and carries ``actor_wide`` for the ally copy.
    """
    del damage_events, fight_duration_seconds
    w_rank = parsed_rank(ability_damages, "W")
    w_heal = extract_named(
        ability_json(champion_data, "W"), "Heal", w_rank, champion_stats
    )
    return [
        {
            "time": cast_time,
            "amount": w_heal,
            "source": "Celestial Blessing",
            "kind": "champion_ability",
            "actor_wide": True,
        }
        for cast_time in cast_slot_times(cast_timeline, "W")
    ]


SELF_HEALING_RULE = self_healing_rule("Kayle")(derive_self_healing)
