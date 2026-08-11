"""Elise's form-aware Q, spider on-hit and explicit utility forms."""

from __future__ import annotations

from typing import Any

from .engine import ONHIT, SlotCtx, build_parser
from .module_helpers import no_damage, source_row
from .slotlib import damage_entry, extract_cooldown, extract_named

_SPIDER_FORM_LEVELS = (1, 6, 11, 16)
_SPIDER_BONUS_DAMAGE = (12.0, 22.0, 32.0, 42.0)
_SPIDER_HEAL = (6.0, 8.0, 10.0, 12.0)


def _spider_tier(level: int) -> int:
    return min(sum(level >= threshold for threshold in _SPIDER_FORM_LEVELS) - 1, 3)


def _spider_queen(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    if not bool(ctx.options.get("spider_form", False)):
        return None
    tier = _spider_tier(ctx.level)
    bonus = _SPIDER_BONUS_DAMAGE[tier] + 0.15 * ctx.stat("ability_power")
    entry = no_damage(
        ctx,
        name="Spider Queen",
        reason="Spider Form basic attacks carry the sourced bonus magic on-hit and heal Elise.",
        slot="P",
    )
    if entry is not None:
        entry["on_hit"] = {
            "name": "Spider Queen on-hit",
            "damage_per_hit": bonus,
            "damage_type": "magic",
        }
        entry["detail"] = (
            f"Spider Form: {bonus:g} bonus magic damage per attack; "
            f"heal {_SPIDER_HEAL[tier]:g} + 8% AP is recorded as non-TDD sustain."
        )
    return entry


_spider_queen.phase = ONHIT


def _neurotoxin_or_bite(ctx: SlotCtx) -> dict[str, Any] | None:
    form = int(ctx.option("q_form"))
    form = min(max(form, 0), 1)
    ability = ctx.ability("Q", form)
    if ability is None:
        return None
    rank = ctx.rank_for("Q")
    if rank < 1:
        return None
    name = "Neurotoxin" if form == 0 else "Venomous Bite"
    value = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        name, rank, extract_cooldown(ctx.ability("Q"), rank), value, "magic"
    )
    entry["parts"] = (entry["parts"][0],)
    entry["detail"] = (
        "Human-form Q reads target current health; spider-form Q reads target missing health."
    )
    entry["target_max_health_sensitive"] = True
    # Wiki: Venomous Bite (spider Q) applies on-hit effects at 100%.
    if form == 1:
        entry["applies_item_on_hits"] = {
            "effectiveness": 1.0,
            "hits": 1,
            "triggers": ("on_hit",),
        }
    return entry


def _volatile_spiderling(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    value = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Volatile Spiderling"),
        rank,
        extract_cooldown(ability, rank),
        value,
        "magic",
    )
    entry["detail"] = (
        "One untargetable spider explosion; target selection is a sourced proximity branch."
    )
    return entry


def _cocoon(ctx: SlotCtx) -> dict[str, Any] | None:
    return no_damage(
        ctx,
        name="Cocoon",
        reason="Stun/reveal only; the parent entry has no outgoing damage formula.",
    )


def _form_toggle(ctx: SlotCtx) -> dict[str, Any] | None:
    form = "Spider" if bool(ctx.options.get("spider_form", False)) else "Human"
    return no_damage(
        ctx,
        name="Spider Form / Human Form",
        reason=f"Explicit {form} form selected; transformation and spiderling state are not outgoing damage.",
    )


SLOTS = {
    "P": _spider_queen,
    "Q": _neurotoxin_or_bite,
    "W": _volatile_spiderling,
    "E": _cocoon,
    "R": _form_toggle,
}
parse_abilities = build_parser(SLOTS, "Elise")

OPTIONS = [
    {"key": "spider_form", "type": "bool", "default": False, "label": "Spider Form"},
    {
        "key": "q_form",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 1,
        "label": "Q form (0 human, 1 spider)",
    },
]

ASSUMPTIONS = [
    "Q is a real form variant: Neurotoxin scales from target current health, while Venomous Bite scales from target missing health.",
    "Spiderlings, Rappel untargetability and the Spider Form heal are explicit state/utility rows; only Spider Form's on-hit damage enters TDD.",
]

SOURCES = [
    source_row(
        "Elise parent entry",
        "https://wiki.leagueoflegends.com/en-us/Elise",
        4008134,
        "2026-04-13T19:00:09Z",
    ),
    source_row(
        "Elise Q template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Elise/Q",
        2863935,
        "2019-11-03T19:56:52Z",
    ),
    source_row(
        "Elise W template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Elise/W",
        2864230,
        "2019-11-03T20:09:39Z",
    ),
    source_row(
        "Elise E template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Elise/E",
        2864376,
        "2019-11-03T20:12:09Z",
    ),
    source_row(
        "Elise R template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Elise/R",
        2864522,
        "2019-11-03T20:15:34Z",
    ),
]
MODULE_COVERAGE = {slot: "modeled" for slot in ("P", "Q", "W", "E", "R")}
REVIEW_STATUS = "reviewed_module"
