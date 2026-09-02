"""Kayn — full-entry reviewed CP10.3 module.

Option key consumed by the shared parser: "form".
"""

from dataclasses import replace
from typing import Any

from ..ability_spec import DamagePart
from .engine import CC_PER_PART, SlotCtx, build_parser
from .module_contract import coverage
from .module_helpers import REVIEWED_MODULE_ASSUMPTIONS, no_damage, typed_damage
from .slotlib import ability_name, extract_cooldown, extract_named, simple_damage
from .source_receipts import load_champion_sources


def _reaping_slash(ctx: SlotCtx) -> dict[str, Any] | None:
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    hits = 2
    form = str(ctx.option("form"))
    value = extract_named(ability, "Total Physical Damage", rank, ctx.stats, ctx.target)
    if form == "darkin":
        per_hit = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
        max_hp = float(ctx.target_stat("target_max_health") or 0.0)
        health_part = max_hp * (0.06 + 0.035 * ctx.stat("bonus_attack_damage") / 100.0)
        value = per_hit * hits + health_part * hits
        parts = (
            DamagePart(
                "physical", per_hit, count=hits, time_offset=0.1, hit_interval=0.15
            ),
            DamagePart(
                "physical",
                health_part,
                count=hits,
                hp_scaled_damage=lambda _missing, amount=health_part: amount,
                time_offset=0.1,
                hit_interval=0.15,
            ),
        )
    else:
        parts = (
            DamagePart(
                "physical", value / hits, count=hits, time_offset=0.1, hit_interval=0.15
            ),
        )
    return {
        "name": ability_name(ability),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "physical",
        "total_raw": value,
        "parts": parts,
        "target_max_health_sensitive": form == "darkin",
        "detail": f"Two ordered Reaping Slash hits; form={form}.",
    }


def _blades_reach(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: one sweep, whose control is the form's, so it rides the part.

    Blade's Reach "deal[s] physical damage to enemies hit and slow[s]
    them by 90% decaying over 1.5 seconds", but the "Darkin Slayer Bonus:
    Blade's Reach knocks up enemies hit for 1 second".  Two kinds for one
    slot, selected by the ``form`` option, is exactly what ``MODULE_CC``
    cannot say, so the reviewed kind is authored per part here instead.
    """
    entry = simple_damage(
        attr="Physical Damage",
        dmg_type="physical",
        event_order_certified="single_hit",
    )(ctx)
    if entry is None:
        return None
    kind = "knockup" if str(ctx.option("form")) == "darkin" else "slow"
    entry["parts"] = tuple(replace(part, cc_kind=kind) for part in entry["parts"])
    return entry


def _umbral_trespass(ctx: SlotCtx) -> dict[str, Any] | None:
    result = typed_damage(ctx, "Physical Damage", "physical", time_offset=0.75)
    if result:
        result["detail"] = (
            "Umbral Trespass recast after the sourced attach/channel delay; "
            f"form={ctx.option('form')}."
        )
    return result


SLOTS = {
    "P": lambda ctx: no_damage(
        ctx,
        name="The Darkin Scythe",
        reason=(
            "Form transformation and Shadow Assassin post-mitigation bonus/Darkin "
            "healing are explicit state; choose form for Q/R branches."
        ),
    ),
    "Q": _reaping_slash,
    "W": _blades_reach,
    "E": lambda ctx: no_damage(
        ctx,
        name="Shadow Step",
        reason="Terrain phasing, movement speed and first-entry heal are utility state.",
    ),
    "R": _umbral_trespass,
}
OPTIONS = [
    {
        "key": "form",
        "type": "select",
        "default": "base",
        "label": "Kayn form",
        "choices": [
            {"value": "base", "label": "Untransformed"},
            {"value": "darkin", "label": "Darkin Slayer"},
            {"value": "shadow_assassin", "label": "Shadow Assassin"},
        ],
    }
]
ASSUMPTIONS = list(REVIEWED_MODULE_ASSUMPTIONS)
SOURCES = load_champion_sources("Kayn")
# Reviewed crowd control, read from the cached kit.  Q (Reaping Slash)
# dashes and swings "dealing physical damage to enemies he passes
# through" with no control clause, and R (Umbral Trespass) "deals
# physical damage to the target and dashes out from their body" with
# none either.  W's answer depends on the form and is authored on its
# part (see ``_blades_reach``).  P and E author no damage part.
MODULE_CC = {"Q": "none", "W": CC_PER_PART, "R": "none"}

parse_abilities = build_parser(SLOTS, "Kayn", cc_kinds=MODULE_CC)

MODULE_COVERAGE = coverage(no_damage="PE")
