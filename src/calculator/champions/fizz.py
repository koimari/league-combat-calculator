"""Fizz's mixed dash, trident empower and lure-size ultimate."""

from __future__ import annotations

import math
from typing import Any

from ..ability_spec import DamagePart
from ..binary_roots import data_value, spell_object
from .engine import CC_PER_PART, SlotCtx, build_parser
from .inputs import int_option
from .module_helpers import no_damage, ranked_slot
from .slotlib import ability_name, damage_entry, extract_cooldown, extract_named
from .source_receipts import load_champion_sources


def _nimble_fighter(ctx: SlotCtx) -> dict[str, Any] | None:
    return no_damage(
        ctx,
        name="Nimble Fighter",
        reason=(
            "Ghosting and incoming pre-mitigation damage reduction are defensive "
            "state, not outgoing TDD."
        ),
        slot="P",
    )


@ranked_slot
def _urchin_strike(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    magic = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    attack_damage = ctx.stat("attack_damage")
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        magic + attack_damage,
        "mixed",
    )
    # Both packets are the one strike at the end of the fixed-distance dash
    # — the cached packet has no separate travel or tick phase — so they
    # share the cast instant.  Authoring it is what carries the cast into
    # the event ledger; a mixed row cannot use the single-part
    # ``event_order_certified="single_hit"`` certification.
    entry["parts"] = (
        DamagePart("magic", magic, time_offset=0.0),
        DamagePart("physical", attack_damage, basic_damage=True, time_offset=0.0),
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


_FIZZ_W_SPELL = spell_object("Fizz", "FizzW")
# W's passive burn cadence is rooted in the binary's duration and tick rate.
_W_PASSIVE_DURATION = data_value(_FIZZ_W_SPELL, "PassiveDoTDuration")
_W_PASSIVE_TICK_INTERVAL = 1.0 / data_value(_FIZZ_W_SPELL, "DoTTicksPerSecond")
_W_PASSIVE_TICKS = int(_W_PASSIVE_DURATION / _W_PASSIVE_TICK_INTERVAL)


@ranked_slot
def _seastone_trident(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    active = extract_named(ability, "Active Magic Damage", rank, ctx.stats, ctx.target)
    passive_per_tick = extract_named(
        ability, "Passive Magic Damage per Tick", rank, ctx.stats, ctx.target
    )
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        active + passive_per_tick * _W_PASSIVE_TICKS,
        "magic",
    )
    # Every part carries authored timing, so the engine attaches the row's
    # exact event ledger (active hit at the cast instant, then the sourced
    # 0.5s ticks) and the coverage classifier certifies the DoT row by its
    # sum-reconciled events instead of downgrading it at the cast boundary.
    entry["parts"] = (
        DamagePart("magic", active, time_offset=0.0),
        DamagePart(
            "magic",
            passive_per_tick,
            count=_W_PASSIVE_TICKS,
            time_offset=_W_PASSIVE_TICK_INTERVAL,
            hit_interval=_W_PASSIVE_TICK_INTERVAL,
        ),
    )
    # With an ambient auto stream, the empowered attack IS one of that
    # stream's swings — the swing stays priced (and evented) on the auto
    # row, keeping this row's ledger sum-exact (the engine's swing
    # reattribution would otherwise add un-evented swing damage here).
    # Without a stream (one-rotation, zero uptime, or a window shorter
    # than one swing) the cast must force its own attack: declare the
    # empower so the engine appends the swing with this authored timing.
    # The ambient count mirrors the engine's floor(AS x duration x uptime)
    # (Diana P cleave precedent).
    ambient_autos = math.floor(
        ctx.stat("attack_speed")
        * float(ctx.option("fight_duration_seconds"))
        * float(ctx.option("auto_attack_uptime"))
    )
    if ambient_autos < 1:
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
    variant = min(max(int(ctx.option("e_variant")), 0), 1)
    ranked = ctx.ranked("E", variant)
    if ranked is None:
        return None
    ability, rank = ranked
    value = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Playful" if variant == 0 else "Trickster"),
        rank,
        extract_cooldown(ctx.ability("E"), rank),
        value,
        "magic",
    )
    # The control is a property of the variant, not of the slot, so it is
    # authored here rather than in MODULE_CC: Playful's splash "slows them
    # for 2 seconds", Trickster deals "the same magic damage in a smaller
    # radius but not applying the slow".
    entry["parts"] = (
        DamagePart("magic", value, cc_kind="slow" if variant == 0 else "none"),
    )
    entry["event_order_certified"] = "single_hit"
    entry["detail"] = (
        "Playful applies the sourced slow; Trickster is the early, smaller-radius recast."
    )
    return entry


def _chum_the_waters(ctx: SlotCtx) -> dict[str, Any] | None:
    size = min(max(int(ctx.option("r_size")), 0), 2)
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    attributes = ("Guppy Damage", "Chomper Damage", "Gigalodon Damage")
    value = extract_named(ability, attributes[size], rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability_name(ability),
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
# Q dashes and strikes, W rends on-hit — neither applies control.  R's
# shark "knock[s] them back" as well as slowing, and a knockback is the
# immobilize the pair reads.  E is absent because Playful slows and
# Trickster does not, so its kind is authored per variant in _playful; P
# carries no damage part at all.
MODULE_CC = {"Q": "none", "W": "none", "E": CC_PER_PART, "R": "knockback", "P": "none"}

parse_abilities = build_parser(SLOTS, "Fizz", cc_kinds=MODULE_CC)

OPTIONS = [
    int_option(
        "e_variant", 0, minimum=0, maximum=1, label="E variant (0 Playful, 1 Trickster)"
    ),
    int_option(
        "r_size",
        0,
        minimum=0,
        maximum=2,
        label="R lure size (0 Guppy, 1 Chomper, 2 Gigalodon)",
    ),
]

ASSUMPTIONS = [
    "Urchin Strike carries both its magic packet and one 100% AD on-hit attack component.",
    "Seastone Trident's active empower is attached to one basic attack; its bleed and "
    "monster-only riders are not silently applied to champions.",
    "Seastone Trident's empowered attack is one of the ambient stream's swings "
    "when the timed window contains at least one; with no stream the cast "
    "forces its own swing. W therefore casts on cooldown in timed fights even "
    "when the stream is sparse (the sourced 4s empower window is not walked).",
    "The W burn is applied once per W cast (its 6 sourced 0.5s ticks trail the "
    "empowered hit); ordinary basic attacks between casts refresh the same "
    "bleed in game but are not priced as extra applications.",
    "Chum the Waters exposes all three sourced distance branches rather than treating "
    "the largest shark as a default.",
]

SOURCES = load_champion_sources("Fizz")
