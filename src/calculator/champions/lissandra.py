"""Lissandra: revision-backed direct-damage slot map.

Q, W, E and R each deal one sourced magic-damage instance.  E's recast only
moves Lissandra, and R's ice field deals the same damage whether she targets
herself or an enemy.
P (Iceborn Subjugation) spawns a Frozen Thrall from a nearby enemy champion's
corpse, which chases for 4 seconds and then shatters for the cached per-level
magic damage plus a prose-only 50% AP rider.  The trigger is a kill this
deterministic duel never reaches, and the thrall is a summoned pet on its own
timeline, an axis this engine lacks, so the slot is a zero-damage boundary
receipt whose detail reports the would-be magnitude for traceability.
"""

from typing import Any

from .. import healing_helpers as _healing
from .engine import SlotCtx, build_parser
from .healing_contract import SelfHealCtx, self_healing_rule
from .shared_mechanics import unreachable_innate
from .slot_cc import CC_PER_PART
from .slot_control import with_control
from .slotlib import simple_damage
from .source_receipts import load_champion_sources

OPTIONS: list[dict[str, Any]] = []


def _iceborn_subjugation_detail(ctx: SlotCtx, would_be: float) -> str:
    """The published boundary text, quoting the thrall shatter this fight never sees."""

    return (
        "Kill-only trigger: whenever a nearby enemy champion dies, "
        "Lissandra spawns a Frozen Thrall that chases for 4 seconds "
        "then shatters for the sourced "
        f"{would_be:g} magic damage (cached 'Per-Level Scaling' at "
        f"champion level {ctx.level}) + 50% AP (prose-only, not "
        "modeled) to nearby enemies. The deterministic 1v1 fight's "
        "target never dies in the model; priced at zero damage as a "
        "documented boundary."
    )


def _iceborn_subjugation(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: the kill-only thrall shatter this fight never reaches (module docstring)."""

    return unreachable_innate(
        ctx,
        row="Per-Level Scaling",
        dmg_type="magic",
        detail=_iceborn_subjugation_detail,
    )


ASSUMPTIONS = [
    "Iceborn Subjugation (P) fires only on a nearby enemy champion's death, spawning "
    "a Frozen Thrall.",
    "The Thrall shatters for the sourced 120 to 520 by level magic; its 50% AP rider "
    "is prose-only.",
    "P's boundary prices zero: the 1v1 target never dies, and the magnitude is in the "
    "row's detail.",
    "Glacial Path counts its outward hit; the recast is movement only.",
    "Frozen Tomb counts one ice-field hit, whether cast on Lissandra or an enemy.",
]

SOURCES = load_champion_sources("Lissandra")

# Each slot deals its one sourced instance at the cast (the module
# docstring's own claim), so each certifies that boundary — which is what
# carries MODULE_CC's reviewed kinds into the event ledger.
SLOTS = {
    "P": _iceborn_subjugation,
    "Q": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
    # Ring of Frost carries its sourced root duration onto the hit.
    "W": with_control(
        simple_damage(
            attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
        ),
        duration_attr="Root Duration",
    ),
    "E": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
    "R": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
}

# Cached kit review: Q "slows enemies hit for 1.5 seconds", W deals damage
# "and root[s] them for a duration", E's claw only decelerates itself, and
# the R instance this module prices is the ice field, which deals damage
# "and slow[s] them for 0.5 seconds" on either cast — the enemy cast's
# 1.5-second stun is not the hit the module counts (ASSUMPTIONS above).
# P's kill-boundary row prices nothing and authors no part, so it
# declares no kind.
MODULE_CC = {"Q": "slow", "W": "root", "E": "none", "R": "slow", "P": CC_PER_PART}

parse_abilities = build_parser(SLOTS, "Lissandra", cc_kinds=MODULE_CC)


def derive_self_healing(ctx: SelfHealCtx) -> list[dict[str, Any]]:
    """Resolve Lissandra self-healing events from its authored packet."""
    healing = []
    min_tick, max_tick = ctx.ranked_rows(
        "R", "Minimum Heal per Tick", "Maximum Heal per Tick"
    )
    for payment in ctx.payments(_healing.HealAnchor.CAST_SCHEDULE, "R"):
        trigger = _healing.trigger_fields(payment.event)
        healing.extend(
            {
                "time": payment.cast_time + index * 0.25,
                "amount": 0.0,
                "amount_formula": _healing.missing_health_scaled_heal(
                    min_tick, max_tick
                ),
                "source": "Frozen Tomb",
                "kind": "champion_ability",
                **trigger,
            }
            for index in range(1, 11)
        )
    return healing


SELF_HEALING_RULE = self_healing_rule("Lissandra")(derive_self_healing)
