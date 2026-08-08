"""Fizz's mixed dash, trident empower and lure-size ultimate."""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .module_helpers import no_damage, source_row
from .slotlib import damage_entry, extract_cooldown, extract_named


def _nimble_fighter(ctx: SlotCtx) -> dict[str, Any] | None:
    return no_damage(
        ctx,
        name="Nimble Fighter",
        reason="Ghosting and incoming pre-mitigation damage reduction are defensive state, not outgoing TDD.",
        slot="P",
    )


def _urchin_strike(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    magic = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    attack_damage = ctx.stats.get("attack_damage", 0.0)
    entry = damage_entry(
        ability.get("name", "Urchin Strike"),
        rank,
        extract_cooldown(ability, rank),
        magic + attack_damage,
        "mixed",
    )
    entry["parts"] = (
        DamagePart("magic", magic),
        DamagePart("physical", attack_damage, basic_damage=True),
    )
    entry["applies_item_on_hits"] = {
        "effectiveness": 1.0,
        "hits": 1,
        "triggers": ("on_hit",),
    }
    entry["detail"] = (
        "Fixed-distance dash: magic spell damage plus one 100% AD attack component."
    )
    return entry


# W's passive burn ticks 6 times over its 3-second duration — the JSON's
# "Total Passive Magic Damage" row is exactly 6x the "Passive Magic
# Damage per Tick" row at every rank (30/5 .. 90/15), so the tick count
# is sourced rather than invented.  Each tick is one 0.5s step of the
# burn.
_W_PASSIVE_TICKS = 6
_W_PASSIVE_DURATION = 3.0
_W_PASSIVE_TICK_INTERVAL = _W_PASSIVE_DURATION / _W_PASSIVE_TICKS


def _seastone_trident(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    active = extract_named(ability, "Active Magic Damage", rank, ctx.stats, ctx.target)
    passive_per_tick = extract_named(
        ability, "Passive Magic Damage per Tick", rank, ctx.stats, ctx.target
    )
    entry = damage_entry(
        ability.get("name", "Seastone Trident"),
        rank,
        extract_cooldown(ability, rank),
        active + passive_per_tick * _W_PASSIVE_TICKS,
        "magic",
    )
    entry["parts"] = (
        DamagePart(
            "magic",
            passive_per_tick,
            count=_W_PASSIVE_TICKS,
            time_offset=_W_PASSIVE_TICK_INTERVAL,
            hit_interval=_W_PASSIVE_TICK_INTERVAL,
        ),
        DamagePart("magic", active),
    )
    # Dict form with authored timing: the forced swing and the active
    # bonus land at the cast instant, and the engine then attaches the
    # per-tick passive events to the row instead of collapsing it to a
    # single cast-boundary hit (the bool form leaves no row timing).
    entry["empowers_next_auto"] = {
        "hits": 1,
        "authored_timing": {"first_attack_delay": 0.0, "attack_interval": 0.0},
    }
    entry["dot_duration"] = _W_PASSIVE_DURATION
    entry["detail"] = (
        "Active trident damage rides the next basic attack; the sourced "
        "6-tick passive burn trails the empowered hit (post-kill refund "
        "remains explicit state)."
    )
    return entry


def _playful(ctx: SlotCtx) -> dict[str, Any] | None:
    variant = min(max(int(ctx.options.get("e_variant", 0)), 0), 1)
    ability = ctx.ability("E", variant)
    if ability is None:
        return None
    rank = ctx.rank_for("E")
    if rank < 1:
        return None
    value = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Playful" if variant == 0 else "Trickster"),
        rank,
        extract_cooldown(ctx.ability("E"), rank),
        value,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", value),)
    entry["detail"] = (
        "Playful applies the sourced slow; Trickster is the early, smaller-radius recast."
    )
    return entry


def _chum_the_waters(ctx: SlotCtx) -> dict[str, Any] | None:
    size = min(max(int(ctx.options.get("r_size", 0)), 0), 2)
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    attributes = ("Guppy Damage", "Chomper Damage", "Gigalodon Damage")
    value = extract_named(ability, attributes[size], rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Chum the Waters"),
        rank,
        extract_cooldown(ability, rank),
        value,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", value, time_offset=2.0),)
    entry["detail"] = ("Guppy", "Chomper", "Gigalodon")[
        size
    ] + " lure size selected; slow/radius/knockback remain sourced utility."
    return entry


SLOTS = {
    "P": _nimble_fighter,
    "Q": _urchin_strike,
    "W": _seastone_trident,
    "E": _playful,
    "R": _chum_the_waters,
}
parse_abilities = build_parser(SLOTS, "Fizz")

OPTIONS = [
    {
        "key": "e_variant",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 1,
        "label": "E variant (0 Playful, 1 Trickster)",
    },
    {
        "key": "r_size",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 2,
        "label": "R lure size (0 Guppy, 1 Chomper, 2 Gigalodon)",
    },
]

ASSUMPTIONS = [
    "Urchin Strike carries both its magic packet and one 100% AD on-hit attack component.",
    "Seastone Trident's active empower is attached to one basic attack; its bleed and monster-only riders are not silently applied to champions.",
    "Chum the Waters exposes all three sourced distance branches rather than treating the largest shark as a default.",
]

SOURCES = [
    source_row(
        "Fizz parent entry",
        "https://wiki.leagueoflegends.com/en-us/Fizz",
        3892616,
        "2025-05-02T11:24:31Z",
    ),
    source_row(
        "Fizz Q template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Fizz/Q",
        2863940,
        "2019-11-03T19:56:57Z",
    ),
    source_row(
        "Fizz W template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Fizz/W",
        2864236,
        "2019-11-03T20:09:45Z",
    ),
    source_row(
        "Fizz E template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Fizz/E",
        2864381,
        "2019-11-03T20:12:14Z",
    ),
    source_row(
        "Fizz R template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Fizz/R",
        2864527,
        "2019-11-03T20:15:39Z",
    ),
]
MODULE_COVERAGE = {slot: "modeled" for slot in ("P", "Q", "W", "E", "R")}
REVIEW_STATUS = "reviewed_module"
