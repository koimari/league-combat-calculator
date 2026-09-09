"""Kha'Zix — full-entry reviewed CP10.3 module.

Option keys consumed by the shared parser: "p_ready", "q_isolated".

Void Spike's heal pays once per cast whether or not the explosion damaged
anyone, so ``SELF_HEALING_RULE`` is the slot, the sourced row and the source
name it is published under.
"""

from typing import Any

from .. import healing_helpers as _healing
from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .healing_contract import self_healing_rule
from .inputs import bool_option
from .module_contract import coverage
from .module_helpers import (
    REVIEWED_MODULE_ASSUMPTIONS,
    innate_on_hit,
    no_damage,
    ranked_slot,
)
from .slotlib import ability_name, extract_cooldown, extract_named, simple_damage
from .source_receipts import load_champion_sources

_unseen_threat_hit = innate_on_hit(
    "Bonus Magic Damage",
    "magic",
    name="Unseen Threat",
    detail=(
        "One empowered next basic attack after Kha'Zix leaves enemy vision; "
        "isolation is a target-state option."
    ),
)


def _unseen_threat(ctx: SlotCtx) -> dict[str, Any] | None:
    if not bool(ctx.option("p_ready")):
        return no_damage(
            ctx,
            name="Unseen Threat",
            reason="The isolated-stealth empowered attack is not armed in this scenario.",
        )
    return _unseen_threat_hit(ctx)


@ranked_slot
def _taste_their_fear(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    isolated = bool(ctx.option("q_isolated"))
    attribute = "Isolated Target Physical Damage" if isolated else "Physical Damage"
    value = extract_named(ability, attribute, rank, ctx.stats, ctx.target)
    return {
        "name": ability_name(ability),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "physical",
        "total_raw": value,
        "parts": (DamagePart("physical", value),),
        "detail": (
            "Isolated target branch is explicit; nearby-allies state disables "
            "the 210% branch."
        ),
        "event_order_certified": "single_hit",
    }


SLOTS = {
    "P": _unseen_threat,
    "Q": _taste_their_fear,
    # Each of Q/W/E deals its packet once, at the cast: the boundary claim
    # that carries MODULE_CC's reviewed answers into the event ledger.
    "W": simple_damage(
        attr="Physical Damage", dmg_type="physical", event_order_certified="single_hit"
    ),
    "E": simple_damage(
        attr="Physical Damage", dmg_type="physical", event_order_certified="single_hit"
    ),
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
    bool_option("p_ready", True, label="Unseen Threat armed"),
    bool_option("q_isolated", True, label="Isolated target"),
]
ASSUMPTIONS = list(REVIEWED_MODULE_ASSUMPTIONS)
SOURCES = load_champion_sources("Kha'Zix")

# Cached kit review: the damaging slots this module prices are the
# UNevolved abilities — Taste Their Fear slashes, Void Spike explodes and
# Leap lands, none of them applying control.  The kit's two slows are the
# evolution bonus (Evolved Spike Racks) and the Unseen Threat empowered
# attack, neither of which is a slot packet this module emits.
MODULE_CC = {"Q": "none", "W": "none", "E": "none", "P": "slow", "R": "none"}

parse_abilities = build_parser(SLOTS, "Kha'Zix", cc_kinds=MODULE_CC)

MODULE_COVERAGE = coverage(no_damage="R")


SELF_HEALING_RULE = self_healing_rule("Kha'Zix")(
    lambda data, stats, damages, events, casts=None, *_: _healing.cast_heals(
        "W",
        "Void Spike",
        events,
        casts,
        amount=_healing.ranked_rows(data, damages, stats, "W", "Heal")[0],
        link_to_damage=False,
    )
)
