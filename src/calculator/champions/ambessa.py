"""Ambessa — slot map for the archetype engine.

Why each slot is non-generic:
- Q is TWO JSON entries under one slot: Q1 (Cunning Sweep, index 0)
  and Q2 (Sundering Slam, index 1). Both are ``by_option(sweetspot)``
  attr picks (default True = "Increased Physical Damage"); Q2 reads
  ``source=("Q", 1)`` with ``cooldown_from=("Q", 0)`` — the engine's
  slot keys map to themselves, so the synthetic "Q2" results key needs
  no engine support — and a thin wrapper stamps the ``recast_of: "Q"``
  marker damage.py uses to chain the recast after Q1.
- R (Public Execution) is a ``stat_buff`` (% armor penetration the
  fight engine applies — not a parse-time scaling stat, so no
  apply_to) that also carries its active "Physical Damage".
- W (Repudiation) always models the empowered hit — the "Increased
  Physical Damage" attribute the classifier would not pick.
- E (Lacerate) hits twice — the "Total Physical Damage" attribute.
- P (Drakehound's Step) is a custom fn: per-proc damage is a per-LEVEL
  base plus a bonus-AD ratio that lives only in the description text
  (regex-extracted, see ``_parse_passive_damage``), multiplied by the
  ``passive_procs`` option (default 4) — the shape proc_damage emits,
  but the extraction is not attribute-driven.

All numeric values are read from the champion JSON data (the passive's
AD ratio from its description text); nothing is hardcoded.
"""

import re
from typing import Any

from .. import healing_helpers as _healing
from ..ability_atoms import ability_field, ability_payload
from ..binary_roots import data_value, spell_object
from .engine import SlotCtx, SlotParser, build_parser
from .healing_contract import self_healing_rule
from .inputs import bool_option, champion_stat, int_option
from .module_helpers import delayed
from .slotlib import (
    attach_self_shield,
    by_option,
    find_named_leveling,
    proc_damage,
    simple_damage,
    stat_buff,
    sum_modifiers,
)
from .source_receipts import load_champion_sources

# Rooted in AmbessaW.Shield_Duration; the cached ability description
# corroborates the 1.5-second shield window. The shield base and 150%
# bonus-AD ratio remain cached leveling rows read live below.
_REPUDIATION_SHIELD_DURATION_SECONDS = data_value(
    spell_object("Ambessa", "AmbessaW"), "Shield_Duration"
)


def _repudiation_shield_amount(ctx: SlotCtx) -> float:
    """W's shield: a per-LEVEL base (40 cached values, 50 at level 1 and
    320 at level 18) plus 150% bonus AD; the long row reads at the level.
    """
    ability = ctx.ability()
    if ability is None:
        return 0.0
    leveling = find_named_leveling(ability, "Shield")
    if leveling is None:
        raise ValueError("Ambessa W Shield leveling row is unavailable")
    return sum_modifiers(
        leveling, ctx.rank_for(), ctx.stats, ctx.target, level=ctx.level
    )


def _repudiation(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: the empowered hit plus the sourced self-shield payload.

    The shield is granted at the cast (the damage event timestamp); the
    shared ledger converts the ``self_shield_events`` payload into a
    timed 1.5-second self-shield.  The generic ally-support scanner
    defers this slot (``support_effects._MODULE_AUTHORED_SHIELD_SLOTS``)
    because its rank-based derivation cannot read the level-indexed
    base.
    """
    entry = _packet_w(ctx)
    rank = int(entry.get("rank", 0) or 0) if entry is not None else 0
    if entry is None or rank < 1:
        return entry
    shield = _repudiation_shield_amount(ctx)
    entry["event_order_certified"] = "single_hit"
    return attach_self_shield(
        entry,
        amount=shield,
        duration=_REPUDIATION_SHIELD_DURATION_SECONDS,
        source=entry.get("name", "Repudiation"),
        detail=(
            f"W also shields Ambessa for {shield:g} for "
            f"{_REPUDIATION_SHIELD_DURATION_SECONDS:g}s (self)"
        ),
    )


def _parse_passive_damage(
    passive: dict[str, Any],
    level: int,
    champion_stats: dict[str, float] | None = None,
    total_ability_power: float = 0.0,
) -> float:
    """Parse Ambessa passive damage per proc from JSON leveling data.

    The passive has per-level base values (20 values for levels 1-20)
    extracted from the wiki's ``data-bot-values`` attribute, plus a
    bonus AD scaling ratio embedded in the effect description (not
    always present as a leveling modifier) — regex-extracted from
    ``"(+ N% bonus AD)"``. (Test seam: tests/test_ambessa.py validates
    the JSON values here.)

    Args:
        passive: Passive ability dict from champion JSON.
        level: Champion level (1-20).
        champion_stats: Champion stats for bonus AD scaling.
        total_ability_power: Total AP.

    Returns:
        Damage per passive proc before resistances.
    """
    stats_context = dict(champion_stats) if champion_stats else {}
    stats_context["ability_power"] = total_ability_power

    leveling = find_named_leveling(passive, "Per-Level Scaling")
    if leveling is None:
        return 0.0

    damage = sum_modifiers(leveling, level, stats_context)
    modifiers = leveling.get("modifiers", [])
    if len(modifiers) > 1:
        return damage

    # The bonus AD scaling is in prose when structured scaling is absent.
    for effect in passive.get("effects", []):
        desc = effect.get("description", "")
        ad_match = re.search(r"\(\+\s*(\d+(?:\.\d+)?)%\s+bonus\s+AD\)", desc)
        if ad_match:
            ratio = float(ad_match.group(1)) / 100.0
            return damage + ratio * champion_stat(stats_context, "bonus_attack_damage")

    return damage


def _drakehounds_step_damage(ctx: SlotCtx, ability: dict[str, Any]) -> float:
    """Resolve one Drakehound's Step proc from structured data/prose."""
    return _parse_passive_damage(
        ability, ctx.level, ctx.stats, ctx.stat("ability_power")
    )


def _drakehounds_step(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: damage plus the energy restored by each selected empowered attack."""
    entry = proc_damage(_drakehounds_step_damage, "physical")(ctx)
    if entry is None:
        return None
    # Medarda's Maxim is consumed by empowered basic attacks; its proc count
    # must be coupled to the authored auto timeline rather than treated as a
    # free fixed-count damage package.  The coupling flag is what clamps
    # procs to real swings in one-rotation mode; the ``auto_stack_proc``
    # certification (each proc consumed by exactly one attack) additionally
    # places each timed proc event on the fight's real swing schedule
    # instead of a synthetic cadence, so no item or config combination can
    # surface the row coarse.
    entry["requires_auto_timeline_coupling"] = True
    entry["event_order_certified"] = "auto_stack_proc"
    entry["auto_stack_every"] = 1
    # Wiki revision 4038211 supplies the 1/7/13 thresholds. The locally
    # ingested champion JSON carries the three values in the passive prose.
    description = " ".join(
        effect.get("description", "")
        for effect in (ctx.ability() or {}).get("effects", [])
    )
    match = re.search(
        r"restore\s+(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*/\s*"
        r"(\d+(?:\.\d+)?)\s*\(based on level\)\s*energy",
        description,
        flags=re.IGNORECASE,
    )
    if match is None:
        raise ValueError("Ambessa passive energy restoration is unavailable")
    values = tuple(float(value) for value in match.groups())
    index = 0 if ctx.level < 7 else 1 if ctx.level < 13 else 2
    entry["resource_restore_per_proc"] = values[index]
    return entry


def _q_cast(index: int) -> SlotParser:
    """Sweetspot-dispatched Q entry at *index* (0 = Q1, 1 = Q2)."""
    return by_option(
        "sweetspot",
        {
            True: simple_damage(
                attr="Increased Physical Damage",
                dmg_type="physical",
                source=("Q", index),
                cooldown_from=("Q", 0),
                event_order_certified="single_hit",
            ),
            False: simple_damage(
                attr="Physical Damage",
                dmg_type="physical",
                source=("Q", index),
                cooldown_from=("Q", 0),
                event_order_certified="single_hit",
            ),
        },
        default=True,
    )


_q2_damage = _q_cast(1)


def _sundering_slam(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q2: the Q recast entry, marked recast_of for the fight engine."""
    entry = _q2_damage(ctx)
    if entry is not None:
        entry["recast_of"] = "Q"
    return entry


OPTIONS = [
    bool_option("sweetspot", True, label="Q/Q2 Sweetspot (doubled damage)"),
    int_option("passive_procs", 4, minimum=0, maximum=20, label="Passive procs"),
]

ASSUMPTIONS = [
    "R passive (armor penetration) is always active when R is skilled",
    "W always uses increased (empowered) damage",
    "E always hits twice (both passes)",
    "Q2 (Sundering Slam) shown separately from Q1 (Cunning Sweep)",
]

# Public Execution's damage is the landing, and the landing is on the far
# side of the suppression: Ambessa "blinks behind the farthest enemy
# champion within the area and seizes them ... and suppresses them for 0.75
# seconds.  While the target is suppressed, they are revealed and Ambessa
# picks them up off the ground before crashing them back down, afterwards
# dealing physical damage and stunning them for 0.4 seconds" (data/
# champions.json Ambessa R).  The seize happens at the end of the cast
# ("Ambessa is displacement immune and unable to act during the cast time
# and while the target is suppressed" names the two as consecutive), so the
# offset from cast start is the cached castTime plus the cached suppression.
_R_CAST_TIME_S = 0.7
_R_SUPPRESSION_S = 0.75
_R_IMPACT_FROM_CAST_START_S = _R_CAST_TIME_S + _R_SUPPRESSION_S


_r_stat_buff = stat_buff(
    "Armor Penetration",
    "armor_penetration_percent",
    damage_attr="Physical Damage",
)
# R: the stat-buff row, with its strike timed to the cached landing.
_public_execution = delayed(_r_stat_buff, delay=_R_IMPACT_FROM_CAST_START_S)

SLOTS = {
    "R": _public_execution,
    "Q": _q_cast(0),
    "Q2": _sundering_slam,
    "W": simple_damage(attr="Increased Physical Damage", dmg_type="physical"),
    "E": simple_damage(attr="Total Physical Damage", dmg_type="physical"),
    "P": _drakehounds_step,
}

SLOTS = dict(SLOTS)
_packet_w = SLOTS["W"]
SLOTS["W"] = _repudiation
# Cached kit review.  Q ("slashes ... in a cone"), Q2 ("slams ... in a
# line") and W ("smashes the ground beneath her") each deal damage and
# apply nothing else — the outer-edge and first-enemy clauses only double
# the damage.  R's strike lands "afterwards" — after the cached 0.75-second
# suppression — "dealing physical damage and stunning them for 0.4
# seconds", so the stun is what the damaged target is taking as the damage
# arrives, and that landing is now authored (see ``_public_execution``).
#
# E stays UNREVIEWED, so this kit keeps the coarse control-armed scan: its
# row is the cached "Total Physical Damage" of both spins, each of which
# "slow[s] them by 99% decaying over 1 second", and the cache times the
# second spin only as "at the end of the dash" — a dash whose length it
# never gives.  P is an empowered-auto rider with no boundary of its own.
MODULE_CC = {"Q": "none", "Q2": "none", "W": "none", "R": "stun"}

parse_abilities = build_parser(SLOTS, "Ambessa", cc_kinds=MODULE_CC)

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "W (Repudiation) also shields Ambessa at the cast for the level-indexed "
    "base (50 : 320 by level) + 150% bonus AD for 1.5s; the shield absorbs "
    "incoming damage in the participant ledger.",
]


SOURCES = load_champion_sources("Ambessa")


# pylint: disable=too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Resolve Ambessa self-healing events from its authored packet."""
    healing = []
    r_rank = int(ability_field(ability_payload(ability_damages, "R"), "rank"))
    ratio = _healing.leveling_value(
        _healing.ability_json(champion_data, "R"), "Healing Percentage", r_rank
    )
    # Public Execution heals from post-mitigation active ability damage: a
    # share of each hit's own damage, so one payment per hit that dealt some.
    if ratio > 0:
        for payment in _healing.payments(
            _healing.HealAnchor.DAMAGING_HIT,
            lambda source: source in {"Q", "Q2", "W", "E", "R"},
            damage_events,
        ):
            event = payment.event
            amount = max(0.0, float(event.get("damage", 0.0))) * ratio / 100.0
            if amount > 0:
                healing.append(
                    {
                        "time": float(event.get("time", 0.0)),
                        "amount": amount,
                        "source": "Public Execution",
                        "kind": "champion_passive",
                        **_healing.trigger_fields(event),
                    }
                )
    return healing


SELF_HEALING_RULE = self_healing_rule("Ambessa")(derive_self_healing)
