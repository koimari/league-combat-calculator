"""Kayn — full-entry reviewed CP10.3 module.

Option key consumed by the shared parser: "form".
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .module_helpers import REVIEWED_MODULE_ASSUMPTIONS, no_damage, typed_damage
from .slotlib import extract_cooldown, extract_named, simple_damage
from .source_receipts import load_champion_sources


def _reaping_slash(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    hits = 2
    form = str(ctx.options.get("form", "base"))
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
        "name": ability.get("name", "Reaping Slash"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "physical",
        "total_raw": value,
        "parts": parts,
        "target_max_health_sensitive": form == "darkin",
        "detail": f"Two ordered Reaping Slash hits; form={form}.",
    }


def _umbral_trespass(ctx: SlotCtx) -> dict[str, Any] | None:
    result = typed_damage(ctx, "Physical Damage", "physical", time_offset=0.75)
    if result:
        result["detail"] = (
            "Umbral Trespass recast after the sourced attach/channel delay; "
            f"form={ctx.options.get('form', 'base')}."
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
    "W": simple_damage(attr="Physical Damage", dmg_type="physical"),
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
parse_abilities = build_parser(SLOTS, "Kayn")

MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "R"} else "no_damage") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
