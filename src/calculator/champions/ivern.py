"""Ivern's brush on-hit, Triggerseed explosion and explicit pet boundary."""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from .engine import ONHIT, SlotCtx, build_parser
from .reviewed_batch_01 import no_damage, source_row
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    on_hit_entry,
    simple_damage,
)


def _brushmaker(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    if not bool(ctx.options.get("w_in_brush", True)):
        return no_damage(
            ctx,
            name=ability.get("name", "Brushmaker"),
            reason="Brushmaker is active utility while not in brush.",
            slot="W",
        )
    value = extract_named(
        ability, "Additional Magic Damage", ctx.rank_for(), ctx.stats, ctx.target
    )
    entry = on_hit_entry(ability.get("name", "Brushmaker"), value, "magic")
    entry["detail"] = (
        "Brushmaker bonus attack magic damage; brush duration and allied-brush branch are explicit state."
    )
    return entry


_brushmaker.phase = ONHIT


def _triggerseed(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    value = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Triggerseed"),
        rank,
        extract_cooldown(ability, rank),
        value,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", value, time_offset=2.0),)
    entry["detail"] = (
        "Shield is granted immediately; the sourced explosion occurs after two seconds."
    )
    return entry


SLOTS = {
    "P": lambda ctx: no_damage(
        ctx,
        name="Friend of the Forest",
        reason="Grove channel, health/mana cost, camp release and full bounty are jungle utility state.",
    ),
    "Q": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "W": _brushmaker,
    "E": _triggerseed,
    "R": lambda ctx: no_damage(
        ctx,
        name="Daisy!",
        reason="Daisy is a controllable pet; pet attacks are not silently inferred from a champion ability packet.",
    ),
}
parse_abilities = build_parser(SLOTS, "Ivern")
OPTIONS = [
    {"key": "w_in_brush", "type": "bool", "default": True, "label": "Ivern is in brush"}
]
ASSUMPTIONS = [
    "Ivern's non-epic monster prohibition and grove economics are preserved as utility/state.",
    "Brushmaker's self bonus attack is an on-hit package; allied champion bolts are a separate roster branch.",
    "Daisy's pet attack packet is not guessed from the champion slot and remains visibly outside TDD until a pet receipt is added.",
]
SOURCES = [
    source_row(
        "Ivern parent entry",
        "https://wiki.leagueoflegends.com/en-us/Ivern",
        4015438,
        "2026-05-04T18:32:23Z",
    ),
    source_row(
        "Ivern Q template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Ivern/Q",
        2863951,
        "2019-11-03T19:57:08Z",
    ),
    source_row(
        "Ivern W template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Ivern/W",
        2864246,
        "2019-11-03T20:09:55Z",
    ),
    source_row(
        "Ivern E template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Ivern/E",
        2864392,
        "2019-11-03T20:12:26Z",
    ),
    source_row(
        "Ivern R template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Ivern/R",
        2864538,
        "2019-11-03T20:15:50Z",
    ),
]
MODULE_COVERAGE = {slot: "modeled" for slot in ("P", "Q", "W", "E", "R")}
REVIEW_STATUS = "reviewed_module"
