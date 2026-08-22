"""Ekko's three-hit passive, two-pass Q and target-health state."""

from __future__ import annotations

from typing import Any

from .. import healing_helpers as _healing
from ..ability_spec import DamagePart
from .engine import ONHIT, SlotCtx, build_parser
from .healing_contract import self_healing_rule
from .module_helpers import no_damage
from .slotlib import damage_entry, extract_cooldown, extract_named, proc_damage
from .source_receipts import load_champion_sources
from .inputs import bool_option, float_option, int_option


def _resonance(ctx: SlotCtx, ability: dict[str, Any]) -> float:
    """One Z-Drive Resonance detonation: the third stack consumes all
    three to deal the sourced bonus magic damage (30 : 150 by level,
    + 80% AP).  The detonation is priced per completed 3-stack cycle."""
    return extract_named(
        ability, "Bonus Magic Damage", ctx.level, ctx.stats, ctx.target
    )


_resonance_proc = proc_damage(
    _resonance,
    "magic",
    count_option="p_procs",
    default_count=0,
    name="Z-Drive Resonance",
    phase_order_events=True,
)


def _timewinder(ctx: SlotCtx) -> dict[str, Any] | None:
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    initial = extract_named(
        ability, "Initial Magic Damage", rank, ctx.stats, ctx.target
    )
    returned = extract_named(
        ability, "Return Magic Damage", rank, ctx.stats, ctx.target
    )
    return_entry = damage_entry(
        ability.get("name", "Timewinder"),
        rank,
        extract_cooldown(ability, rank),
        initial + returned,
        "magic",
    )
    return_entry["parts"] = (
        DamagePart("magic", initial, time_offset=0.25),
        DamagePart("magic", returned, time_offset=2.0),
    )
    return_entry["detail"] = (
        "Initial grenade and authored return pass; each pass hits a target once."
    )
    return return_entry


def _parallel_convergence(ctx: SlotCtx) -> dict[str, Any] | None:
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    ready = bool(ctx.options.get("w_passive_ready", False))
    entry = no_damage(
        ctx,
        name=ability.get("name", "Parallel Convergence"),
        reason="Active W creates a sourced shield/stun zone; its passive on-hit is opt-in below 30% target health.",
    )
    if entry is None:
        return None
    if ready:
        target_max = float(ctx.target_stat("target_max_health") or 0.0)
        missing_ratio = float(ctx.option("w_target_missing_health"))
        missing_ratio = min(max(missing_ratio, 0.0), 1.0)
        base = max(
            15.0,
            target_max
            * (0.03 + 0.03 * ctx.stat("ability_power") / 100.0)
            * missing_ratio,
        )
        entry["on_hit"] = {
            "name": "Parallel Convergence passive",
            "damage_per_hit": base,
            "damage_type": "magic",
        }
        entry["detail"] = "Passive on-hit enabled: target is below 30% max health."
    return entry


_parallel_convergence.phase = ONHIT


def _phase_dive(ctx: SlotCtx) -> dict[str, Any] | None:
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    bonus = extract_named(ability, "Bonus Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Phase Dive"),
        rank,
        extract_cooldown(ability, rank),
        bonus,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", bonus),)
    entry["empowers_next_auto"] = True
    # One empowered swing, landing with that swing.
    entry["event_order_certified"] = "single_hit"
    entry["detail"] = (
        "Empowers one basic attack; the blink and attack reset are state-only."
    )
    return entry


def _chronobreak(ctx: SlotCtx) -> dict[str, Any] | None:
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    damage = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Chronobreak"),
        rank,
        extract_cooldown(ability, rank),
        damage,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", damage, time_offset=0.5),)
    entry["event_order_certified"] = "single arrival explosion"
    entry["detail"] = (
        "Explosion at the afterimage; the sourced self-heal/stasis is not outgoing damage."
    )
    return entry


SLOTS = {
    "P": _resonance_proc,
    "Q": _timewinder,
    "W": _parallel_convergence,
    "E": _phase_dive,
    "R": _chronobreak,
}
# Cached kit review.  Q's grenade "expand[s] into a Temporal Sickness field
# that slows nearby enemies" around the champion it hits; E's empowered
# attack and R's arrival explosion add damage and nothing else.  W is
# absent because it emits no damage row — its chronosphere slow and its
# entry-triggered stun ride a zone the damage model does not price.
MODULE_CC = {"Q": "slow", "E": "none", "R": "none"}

parse_abilities = build_parser(SLOTS, "Ekko", cc_kinds=MODULE_CC)

OPTIONS = [
    int_option(
        "p_procs",
        0,
        minimum=0,
        maximum=10,
        label="Z-Drive Resonance detonations (3 stacks each)",
    ),
    bool_option("w_passive_ready", False, label="Parallel Convergence passive ready"),
    float_option(
        "w_target_missing_health",
        0.5,
        minimum=0.0,
        maximum=1.0,
        label="W target missing-health ratio",
        step=0.05,
    ),
]

ASSUMPTIONS = [
    "Resonance stacks up to 3 (cap) and the third stack consumes all three to detonate; each p_procs entry is one completed 3-stack detonation (30 : 150 by level + 80% AP), priced because the rotation does not imply three prior applications.",
    "Resonance's per-target 4-second stack window and monster 270% multiplier are boundary state; the detonation value is the champion-target sourced value.",
    "Q's return is a separate authored event and W's passive is disabled unless the target-health gate is selected.",
    "Chronobreak's heal, stasis and movement are recorded as non-TDD state; only the arrival explosion enters damage.",
]

SOURCES = load_champion_sources("Ekko")


# pylint: disable=too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Resolve Ekko self-healing events from its authored packet."""
    healing = []
    r_rank = _healing.parsed_rank(ability_damages, "R")
    r_heal = _healing.extract_named(
        _healing.ability_json(champion_data, "R"),
        "Minimum Heal",
        r_rank,
        champion_stats,
    )
    for payment in _healing.payments(
        _healing.HealAnchor.CAST, "R", damage_events, cast_timeline
    ):
        event = payment.event
        _healing.heal_from_damage(
            healing, event, r_heal, "Chronobreak", link_to_damage=False
        )
    return healing


SELF_HEALING_RULE = self_healing_rule("Ekko")(derive_self_healing)
