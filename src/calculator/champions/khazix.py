"""Kha'Zix — full-entry reviewed CP10.3 module.

Option keys consumed by the shared parser: "p_ready", "q_isolated".
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .module_helpers import REVIEWED_MODULE_ASSUMPTIONS, no_damage
from .slotlib import extract_cooldown, extract_named, on_hit_entry, simple_damage
from .source_receipts import load_champion_sources


def _unseen_threat(ctx: SlotCtx) -> dict[str, Any] | None:
    if not bool(ctx.options.get("p_ready", True)):
        return no_damage(
            ctx,
            name="Unseen Threat",
            reason="The isolated-stealth empowered attack is not armed in this scenario.",
        )
    ability = ctx.ability()
    if ability is None:
        return None
    value = extract_named(
        ability, "Bonus Magic Damage", ctx.level, ctx.stats, ctx.target
    )
    result = on_hit_entry("Unseen Threat", value, "magic")
    result["detail"] = (
        "One empowered next basic attack after Kha'Zix leaves enemy vision; "
        "isolation is a target-state option."
    )
    return result


def _taste_their_fear(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    isolated = bool(ctx.options.get("q_isolated", True))
    attribute = "Isolated Target Physical Damage" if isolated else "Physical Damage"
    value = extract_named(ability, attribute, rank, ctx.stats, ctx.target)
    return {
        "name": ability.get("name", "Taste Their Fear"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "physical",
        "total_raw": value,
        "parts": (DamagePart("physical", value),),
        "detail": (
            "Isolated target branch is explicit; nearby-allies state disables "
            "the 210% branch."
        ),
    }


SLOTS = {
    "P": _unseen_threat,
    "Q": _taste_their_fear,
    "W": simple_damage(attr="Physical Damage", dmg_type="physical"),
    "E": simple_damage(attr="Physical Damage", dmg_type="physical"),
    "R": lambda ctx: no_damage(
        ctx,
        name="Void Assault",
        reason=(
            "Invisibility, evolution and movement speed are state; the recast "
            "does not deal enemy damage."
        ),
    ),
}
OPTIONS = [
    {
        "key": "p_ready",
        "type": "bool",
        "default": True,
        "label": "Unseen Threat armed",
    },
    {
        "key": "q_isolated",
        "type": "bool",
        "default": True,
        "label": "Isolated target",
    },
]
ASSUMPTIONS = list(REVIEWED_MODULE_ASSUMPTIONS)
SOURCES = load_champion_sources("Kha'Zix")
parse_abilities = build_parser(SLOTS, "Kha'Zix")

MODULE_COVERAGE = {
    slot: ("modeled" if slot != "R" else "no_damage") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"

from .. import healing_helpers as _healing  # pylint: disable=wrong-import-position


# pylint: disable=protected-access,too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument,wrong-import-position
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Resolve Kha'Zix self-healing events from its authored packet."""
    healing = []
    w = _healing._ability(champion_data, "W")
    w_rank = _healing._rank(ability_damages, "W")
    w_heal = _healing.extract_named(w, "Heal", w_rank, champion_stats)
    for event in _healing._attributed_events(
        damage_events, lambda source, _event: source == "W"
    ):
        _healing._heal_from_damage(
            healing, event, w_heal, "Void Spike", link_to_damage=False
        )
    return sorted(healing, key=lambda event: (event["time"], event["source"]))


from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Kha'Zix", derive_self_healing)
