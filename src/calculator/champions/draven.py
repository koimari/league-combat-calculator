"""Draven's source-backed attack, axe and two-pass ultimate model."""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from .engine import BUFF, SlotCtx, build_parser
from .module_helpers import no_damage
from .slotlib import damage_entry, extract_cooldown, extract_named, extract_value
from .source_receipts import load_champion_sources
from .inputs import bool_option, int_option


def _spinning_axe(ctx: SlotCtx) -> dict[str, Any] | None:
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    bonus = extract_named(ability, "Bonus Physical Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Spinning Axe"),
        rank,
        extract_cooldown(ability, rank),
        bonus,
        "physical",
    )
    entry["parts"] = (DamagePart("physical", bonus, crit_effectiveness=1.0),)
    entry["empowers_next_auto"] = True
    # One empowered swing, landing with that swing.
    entry["event_order_certified"] = "single_hit"
    entry["detail"] = (
        "One empowered basic attack; the caught axe readies the next cast."
    )
    return entry


def _blood_rush(ctx: SlotCtx) -> dict[str, Any] | None:
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    bonus_as = extract_value(ability, "Bonus Attack Speed", rank)
    entry = damage_entry(
        ability.get("name", "Blood Rush"),
        rank,
        extract_cooldown(ability, rank),
        0.0,
        "physical",
    )
    entry["stat_buff"] = {"bonus_attack_speed": bonus_as}
    entry["detail"] = (
        f"{bonus_as:g}% bonus attack speed for the sourced 3-second Blood Rush window."
    )
    return entry


_blood_rush.phase = BUFF


def _stand_aside(ctx: SlotCtx) -> dict[str, Any] | None:
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    value = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Stand Aside"),
        rank,
        extract_cooldown(ability, rank),
        value,
        "physical",
    )
    entry["parts"] = (DamagePart("physical", value, time_offset=0.25),)
    entry["detail"] = (
        "Line hit; the source also applies the selected rank's slow and knock-aside."
    )
    return entry


def _whirling_death(ctx: SlotCtx) -> dict[str, Any] | None:
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    passes = min(max(int(ctx.option("r_passes")), 1), 2)
    per_pass = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Whirling Death"),
        rank,
        extract_cooldown(ability, rank),
        per_pass * passes,
        "physical",
    )
    entry["parts"] = (
        DamagePart(
            "physical", per_pass, count=passes, time_offset=0.0, hit_interval=1.0
        ),
    )
    entry["event_order_certified"] = "two authored passes"
    entry["detail"] = (
        f"{passes} authored pass{'es' if passes != 1 else ''}; each pass hits once."
    )
    return entry


def _league_of_draven(ctx: SlotCtx) -> dict[str, Any] | None:
    stacks = min(max(int(ctx.option("adoration_stacks")), 0), 10000)
    cash_in = bool(ctx.options.get("adoration_cash_in", False))
    reason = (
        f"{stacks} Adoration stack(s); cash-in yields {25 + 2 * stacks} bonus gold."
        if cash_in
        else f"{stacks} Adoration stack(s) retained; cash-in is not assumed."
    )
    return no_damage(
        ctx,
        name="League of Draven",
        reason=reason,
        slot="P",
    )


SLOTS = {
    "P": _league_of_draven,
    "Q": _spinning_axe,
    "W": _blood_rush,
    "E": _stand_aside,
    "R": _whirling_death,
}
# Cached kit review.  Q's empowered attack and R's two axe passes only add
# damage (R's threshold clause executes, it does not control), while E
# "knock[s] them aside ... and slow[s] them for 2 seconds" — a forced
# displacement, which is the Wiki's airborne class.  W grants Draven attack
# and movement speed and P is a gold counter, neither with a damage part.
MODULE_CC = {"Q": "none", "E": "airborne", "R": "none"}

parse_abilities = build_parser(SLOTS, "Draven", cc_kinds=MODULE_CC)

OPTIONS = [
    int_option(
        "adoration_stacks", 0, minimum=0, maximum=10000, label="Adoration stacks"
    ),
    bool_option(
        "adoration_cash_in", False, label="Cash in Adoration on a champion kill"
    ),
    int_option("r_passes", 2, minimum=1, maximum=2, label="Whirling Death passes"),
]

ASSUMPTIONS = [
    "Spinning Axe is an empowered basic attack and therefore shares the auto/item timeline.",
    "Whirling Death exposes one or two sourced passes; target crossing and execution thresholds remain explicit target state, not guessed damage.",
    "Adoration is an explicit economy state and never silently contributes to TDD.",
]

SOURCES = load_champion_sources("Draven")
