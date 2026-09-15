"""Hecarim's movement-scaled AD, Rampage stacks and authored hit cadence."""

from __future__ import annotations

import re
from typing import Any

from .. import healing_helpers as _healing
from ..ability_spec import DamagePart
from ..binary_roots import data_value, spell_object
from .engine import BUFF, SlotCtx, build_parser
from .healing_contract import self_healing_rule
from .inputs import float_option, int_option
from .module_helpers import between_rows, ranked_slot
from .slot_entries import damage_entry
from .slot_extract import ability_name, extract_cooldown, extract_named, extract_value
from .source_receipts import load_champion_sources

_RAMPAGE_RE = re.compile(
    r"a stack of Rampage for (?P<seconds>\d+(?:\.\d+)?) seconds[^.]*?stacking up "
    r"to (?P<stacks>\d+) times\. Each stack increases Rampage's damage by "
    r"(?P<per_stack>\d+(?:\.\d+)?)% \(\+ (?P<per_ad>\d+(?:\.\d+)?)% per 100 "
    r"bonus AD\) and reduces its base cooldown by (?P<refund>\d+(?:\.\d+)?) seconds"
)


def _rampage_cooldown_row(ability: dict[str, Any]) -> tuple[float, ...]:
    """Rampage's cooldown at each stack level, straight from the cache.

    The cached row is indexed BY RAMPAGE STACKS and not by rank, which its
    own units say (" (based on Rampage stacks)"), so a ranked read lands on
    the last value and prices every rank at the fully stacked cooldown.
    """
    row = ability.get("cooldown")
    modifiers = None if row is None else row.get("modifiers")
    for modifier in modifiers if modifiers is not None else ():
        units = modifier.get("units")
        if units is None or not all("Rampage stacks" in str(unit) for unit in units):
            continue
        values = modifier.get("values")
        if values is None:
            continue
        return tuple(float(value) for value in values)
    raise ValueError(
        "Hecarim Q: the cached cooldown row is no longer the per-stack one "
        "(its units no longer say 'based on Rampage stacks')"
    )


def _rampage_stack_terms(ability: dict[str, Any]) -> dict[str, float]:
    """Rampage's own stack rule, read from the cached sentence.

    Five numbers in one clause: how long a stack stands, how many stand at
    once, what one is worth as damage, what it is worth per 100 bonus AD,
    and how many seconds it takes off the base cooldown.
    """
    effects = ability.get("effects")
    for effect in effects if effects else ():
        description = effect.get("description")
        if description is None:
            continue
        match = _RAMPAGE_RE.search(str(description))
        if match is not None:
            return {
                "stack_seconds": float(match.group("seconds")),
                "max_stacks": int(match.group("stacks")),
                "per_stack": float(match.group("per_stack")) / 100.0,
                "per_100_bonus_ad": float(match.group("per_ad")) / 100.0,
                "cooldown_per_stack": float(match.group("refund")),
            }
    raise ValueError(
        "Hecarim Q: the cached active no longer states Rampage's stack rule "
        "('a stack of Rampage for N seconds ... stacking up to N times. Each "
        "stack increases Rampage's damage by N% (+ N% per 100 bonus AD) and "
        "reduces its base cooldown by N seconds')"
    )


def _warpath(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    percent = extract_value(ability, "Per-Level Scaling", ctx.level)
    bonus_ms = float(ctx.option("bonus_movement_speed"))
    if bonus_ms <= 0.0:
        bonus_ms = max(0.0, float(ctx.stat("move_speed")) - 325.0)
    bonus_ad = percent * bonus_ms / 100.0
    ctx.stats["bonus_attack_damage"] = ctx.stat("bonus_attack_damage") + bonus_ad
    ctx.stats["attack_damage"] = ctx.stat("attack_damage") + bonus_ad
    entry = damage_entry(ability_name(ability), ctx.level, 0.0, 0.0, "physical")
    entry["stat_buff"] = {"bonus_attack_damage": bonus_ad}
    entry["detail"] = (
        f"{percent:g}% of {bonus_ms:g} bonus movement speed grants {bonus_ad:g} bonus AD."
    )
    return entry


_warpath.phase = BUFF


@ranked_slot
def _rampage(ctx: SlotCtx, ability: dict[str, Any], rank: int) -> dict[str, Any] | None:
    terms = _rampage_stack_terms(ability)
    maximum = int(terms["max_stacks"])
    by_stacks = _rampage_cooldown_row(ability)
    base = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    per_stack = terms["per_stack"] + terms["per_100_bonus_ad"] * (
        ctx.stat("bonus_attack_damage") / 100.0
    )
    requested = ctx.options.get("q_stacks")
    if requested is None:
        # The level and the cadence decide each other, and a FORWARD walk
        # resolves both: the stacks a cast leaves behind are known from the
        # casts already placed, and they shorten the wait for the next one.
        # The scheduler walks the cooldown (stack_scaled_cooldown) and the
        # cast pricing walks the damage (stack_window), off one rule.
        entry = damage_entry(
            ability_name(ability), rank, by_stacks[0], base, "physical"
        )
        entry["parts"] = (
            DamagePart(
                "physical",
                base,
                time_offset=0.1,
                # The scaled reading REPLACES the part's amount, so it
                # carries the whole packet: the base plus what the level
                # adds, which is the base again at zero stacks.
                stack_scaled_damage=lambda level: base * (1.0 + per_stack * level),
            ),
        )
        entry["stack_window"] = {
            "arming_slots": ("Q",),
            "max_stacks": maximum,
            "hits_required": maximum,
            "stack_seconds": terms["stack_seconds"],
            "stacks_from_ability_hits": True,
            "armed_at_start": False,
            "requested": False,
        }
        entry["stack_scaled_cooldown"] = {
            "by_stacks": by_stacks,
            "stack_seconds": terms["stack_seconds"],
        }
        entry["detail"] = (
            f"Each Rampage stack adds {per_stack * 100:g}% damage and takes "
            f"the cooldown from {by_stacks[0]:g}s to {by_stacks[-1]:g}s, up "
            f"to {maximum} held for {terms['stack_seconds']:g}s; the fight "
            "walks the casts that stack them."
        )
        return entry
    stacks = min(max(int(requested), 0), maximum)
    multiplier = 1.0 + stacks * per_stack
    value = base * multiplier
    return {
        "name": ability_name(ability),
        "rank": rank,
        # The cached row already prices every stack level, so there is
        # nothing to subtract: a ranked read of it lands on the last value
        # and prices the fully stacked cooldown at every rank.
        "cooldown": by_stacks[min(stacks, len(by_stacks) - 1)],
        "damage_type": "physical",
        "total_raw": value,
        "parts": (DamagePart("physical", value, time_offset=0.1),),
        "detail": f"{stacks} Rampage stack(s); damage multiplier {multiplier:.3f}.",
    }


# W (Spirit of Dread) ticks once per second for 5 seconds — the JSON's
# "Total Magic Damage" row is exactly 5x the "Magic Damage Per Tick"
# row at every rank (100/20 .. 300/60), so the tick count is sourced
# rather than invented.
_W_TICKS = 5


@ranked_slot
def _spirit_of_dread(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    ticks = min(max(int(ctx.options.get("w_ticks", _W_TICKS)), 1), _W_TICKS)
    per_tick = extract_named(
        ability, "Magic Damage Per Tick", rank, ctx.stats, ctx.target
    )
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        per_tick * ticks,
        "magic",
    )
    entry["parts"] = (
        DamagePart("magic", per_tick, count=ticks, time_offset=0.0, hit_interval=1.0),
    )
    entry["detail"] = (
        "One sourced area tick per second; healing and bonus resistances remain state "
        "in the ledger."
    )
    return entry


@ranked_slot
def _devastating_charge(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    distance = min(max(float(ctx.option("e_charge")), 0.0), 1.0)
    value = between_rows(
        ctx,
        ability,
        rank,
        "Minimum Physical Damage",
        high="Maximum Physical Damage",
        fraction=distance,
    )
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        value,
        "physical",
    )
    entry["parts"] = (
        DamagePart("physical", value, basic_damage=True, time_offset=0.25),
    )
    entry["empowers_next_auto"] = True
    entry["applies_item_on_hits"] = {
        "effectiveness": 1.0,
        "hits": 1,
        "triggers": ("on_hit",),
    }
    entry["detail"] = (
        f"Distance fraction {distance:.2f}; the next basic attack is empowered and knocks back."
    )
    return entry


@ranked_slot
def _r(ctx: SlotCtx, ability: dict[str, Any], rank: int) -> dict[str, Any] | None:
    return damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        extract_named(ability, "Magic damage", rank, ctx.stats, ctx.target),
        "magic",
        event_order_certified="single_hit",
    )


# Q's cleave and W's aura only damage.  E's charge "knocks them back ...
# stuns them for 0.25 seconds" — the first-listed immobilize is the
# knockback.  R's riders damage on the way through and Hecarim then "fears
# nearby enemies" on arrival.  P is the bonus-AD conversion row and applies
# nothing.
SLOTS = {
    "P": _warpath,
    "Q": _rampage,
    "W": _spirit_of_dread,
    "E": _devastating_charge,
    "R": _r,
}


MODULE_CC = {"Q": "none", "W": "none", "E": "knockback", "R": "fear", "P": "none"}

parse_abilities = build_parser(SLOTS, "Hecarim", cc_kinds=MODULE_CC)
OPTIONS = [
    float_option(
        "bonus_movement_speed",
        0.0,
        minimum=0.0,
        maximum=500.0,
        label="Bonus movement speed",
    ),
    int_option(
        "q_stacks",
        0,
        minimum=0,
        maximum=3,
        label=(
            "Rampage stacks; unset walks the casts that stack them, which "
            "shorten the cooldown to the next cast as well as raising its damage"
        ),
    ),
    int_option(
        "w_ticks", _W_TICKS, minimum=1, maximum=_W_TICKS, label="Spirit of Dread ticks"
    ),
    float_option(
        "e_charge",
        1.0,
        minimum=0.0,
        maximum=1.0,
        label="Devastating Charge distance fraction",
        step=0.25,
    ),
]
ASSUMPTIONS = [
    "Warpath reads the explicit bonus-movement-speed input and updates bonus AD "
    "before later casts.",
    "Rampage stacks and Spirit of Dread ticks are explicit ordered state; ally "
    "healing, fear and displacement are utility.",
    "Devastating Charge is one empowered basic attack and therefore shares the "
    "item/on-hit timeline.",
]
SOURCES = load_champion_sources("Hecarim")

# HARDCODED: verify on patch updates — Spirit of Dread heals Hecarim for
# 25% of the post-mitigation damage dealt to enemies in the area from all
# sources, for the 4 seconds a cast is active (cached W effect[1]).  The
# sourced cap applies only to minions and monsters, so a champion duel
# uses the uncapped share.
# Both rooted in the binary (HecarimW DamageLeechPerc / BuffDuration);
# the cached W effect prose corroborates ("heals ... for 25% ... for
# the 4 seconds a cast is active").
_HECARIM_W_SPELL = spell_object("Hecarim", "HecarimW")
_SPIRIT_OF_DREAD_SHARE = data_value(_HECARIM_W_SPELL, "DamageLeechPerc") / 100.0
_SPIRIT_OF_DREAD_WINDOW_SECONDS = data_value(_HECARIM_W_SPELL, "BuffDuration")


# pylint: disable=too-many-arguments,too-many-positional-arguments,unused-argument
def derive_self_healing(
    champion_data: dict[str, Any],
    champion_stats: dict[str, float],
    ability_damages: dict[str, dict[str, Any]],
    damage_events: list[dict[str, Any]],
    cast_timeline: list[dict[str, Any]] | None = None,
    fight_duration_seconds: float | None = None,
) -> list[dict[str, Any]]:
    """Resolve Hecarim self-healing events from its authored packet.

    Window membership comes from the engine's own cast timeline, and every
    damaging event inside a W window (the W ticks included) is a trigger.
    """
    healing: list[dict[str, Any]] = []
    w_casts = [
        float(cast.get("time", 0.0))
        for cast in (cast_timeline or [])
        if cast.get("slot") == "W"
    ]
    if w_casts:
        for payment in _healing.payments(
            _healing.HealAnchor.DAMAGING_HIT, lambda _source: True, damage_events
        ):
            event = payment.event
            event_time = float(event.get("time", 0.0))
            if not any(
                cast_time <= event_time <= cast_time + _SPIRIT_OF_DREAD_WINDOW_SECONDS
                for cast_time in w_casts
            ):
                continue
            amount = _SPIRIT_OF_DREAD_SHARE * max(0.0, float(event.get("damage", 0.0)))
            _healing.heal_from_damage(healing, event, amount, "Spirit of Dread")
    return healing


SELF_HEALING_RULE = self_healing_rule("Hecarim")(derive_self_healing)
