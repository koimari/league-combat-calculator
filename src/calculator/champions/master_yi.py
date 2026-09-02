"""Master Yi — reviewed packet slots plus the E3 Double Strike passive.

E3 addition over the CP10.4 packet module:
- P (Double Strike) becomes an ONHIT stack slot: basic attacks on-hit
  generate a stack (up to 3); at 3 stacks the next basic attack strikes
  twice, the second strike dealing 50% AD physical damage. The fight
  engine's every-Nth-hit on-hit machinery prices it exactly like Vayne
  W (``stacks_required`` 3, autos-only): the per-proc 50%-AD strike is
  spread across the 3 stacking hits. Alpha Strike explicitly does NOT
  grant Double Strike stacks (wiki note), so ability hits never count —
  only the simulated auto stream.

P1-2 addition — W (Meditate): the module now declares W in SLOTS so the
fight rotation casts the channel; the channel's self-heal is authored
by the healing rule (``healing.derive_self_healing`` "Master Yi"
branch): 8 ticks at the sourced 0.5-second cadence over the 4-second
channel, each tick interpolated between the Minimum Heal Per Tick and
Maximum Heal Per Tick rows by the fighter's live missing health.  W's
damage-reduction window is a defensive state the damage model does not
stage.

R (Highlander) is the attack-speed steroid: the cached "Bonus Attack
Speed" row (25/45/65%) over the sourced 7-second window, emitted as a
BUFF-phase ``stat_buff`` so the fight engine's auto count scales with
it.  R's movement speed, its slow/cripple immunity and its takedown
cooldown refund have no channel and stay named.
"""

from typing import Any

from .. import healing_helpers as _healing
from ..binary_roots import calculation_coefficient, data_value, spell_object
from .engine import BUFF, ONHIT, SlotCtx
from .healing_contract import self_healing_rule
from .module_helpers import buff_window_share, ranked_slot
from .packet_module import build_packet_module
from .slotlib import (
    STEROID_ZERO,
    ability_name,
    ability_on_hit_entry,
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
)

PACKET_SHA256 = "a6d43d11733ede3c9a2f3daa2d2f6afb754fc83e580b27dff8e8ffeb76783164"

# Alpha Strike's priced hit is its primary damage, and the cached entry
# puts that after the whole vanish: Master Yi "reappears ... and then
# becomes able to act again[ after 0.165 seconds. ][ 1.087 seconds total
# after the start of the cast with 4 bounces. ]" with the note "Alpha
# Strike's primary damage applies after Master Yi reappears."  The cached
# number is already measured from the cast start, which is where
# ``time_offset`` starts.  The lesser marks that "detonate instantly upon
# application to deal 25% damage" are a multi-target branch this
# single-target packet does not price.
_Q_REAPPEAR_SECONDS = 1.087


# HARDCODED: verify on patch updates — Double Strike's 3-hit cadence is wiki
# prose.  The second-strike ratio is rooted in the passive calculation.
# DOCUMENTED CONFLICT: the binary's MasterYiPassive.AttackCount reads 4 — kept
# on the wiki root until a patch settles it, pinned by test_binary_roots.
_DOUBLE_STRIKE_STACKS = 3
_MASTER_YI_PASSIVE_SPELL = spell_object("Master Yi", "MasterYiPassive")
_SECOND_STRIKE_AD_RATIO = calculation_coefficient(
    _MASTER_YI_PASSIVE_SPELL, "TotalDamage"
)
# "The second strike ... is affected by critical strike modifiers"
# (cached P effect 1), and the entry's notes add that it "separately
# rolls a critical strike" — full crit probability on its own roll,
# which is the axis this key scales.
_SECOND_STRIKE_CRIT_EFFECTIVENESS = 1.0

# Highlander's window is the binary Highlander.RDuration DataValue; the
# cached R prose ("For the next 7 seconds ...") corroborates it.  The
# percentage rides the JSON's "Bonus Attack Speed" row.
_R_DURATION_SECONDS = data_value(spell_object("Master Yi", "Highlander"), "RDuration")


def _double_strike(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: every 3rd auto strikes twice — second strike 50% AD physical."""
    ability = ctx.ability()
    if ability is None:
        return None
    ad = ctx.stat("attack_damage")
    per_proc = _SECOND_STRIKE_AD_RATIO * ad
    return ability_on_hit_entry(
        ability_name(ability),
        ctx.level,
        "physical",
        {
            "name": "Double Strike (second strike)",
            "damage_per_hit": per_proc / _DOUBLE_STRIKE_STACKS,
            "damage_type": "physical",
            "stacks_required": _DOUBLE_STRIKE_STACKS,
            "crit_effectiveness": _SECOND_STRIKE_CRIT_EFFECTIVENESS,
        },
    )


_double_strike.phase = ONHIT


@ranked_slot
def _meditate(
    _ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """W: a zero-damage channel receipt (the heal lives in healing.py)."""
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        0.0,
        "physical",
    )
    entry["parts"] = ()
    entry["detail"] = (
        "4-second channel: the self-heal (Minimum/Maximum Heal Per Tick, "
        "missing-health scaled) is authored by healing.py; the damage-"
        "reduction window is a defensive state not staged by the damage "
        "model"
    )
    return entry


def _highlander(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: the 25/45/65% attack-speed steroid, priced onto the auto count."""
    ranked = ctx.ranked("R")
    if ranked is None:
        return None
    ability, rank = ranked

    granted = extract_value(ability, "Bonus Attack Speed", rank)
    movement = extract_value(ability, "Bonus Movement Speed", rank)
    bonus_as = granted * buff_window_share(ctx, _R_DURATION_SECONDS)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        0.0,
        "physical",
        zero_policy=STEROID_ZERO,
    )
    entry["stat_buff"] = {"bonus_attack_speed": bonus_as}
    entry["detail"] = (
        f"+{granted:g}% bonus attack speed for {_R_DURATION_SECONDS:g}s "
        f"({bonus_as:g}% over the fight window); the row's "
        f"+{movement:g}% movement speed, the crowd-control immunities and "
        "the takedown cooldown refund have no channel"
    )
    return entry


_highlander.phase = BUFF


# Reviewed crowd control, read from the cached kit.  Alpha Strike marks
# and detonates for damage and on-hit effects only — nothing in the entry
# controls the enemies it strikes (Master Yi is the one made unable to
# act).  P is an on-hit rider, W a self-channel, R a self-buff.
#
# E stays UNREVIEWED, so this kit keeps the coarse control-armed scan,
# and the reason is not timing: Wuju Style "empowers his basic attacks
# within the next 5 seconds to deal bonus true damage on-hit", but the
# reviewed packet prices it as one direct hit on the E row.  Certifying
# that hit at the cast boundary would state an instant the ability does
# not have — the rider lands on a later basic attack — so the row needs
# to move onto the on-hit stream before it can carry any marker.
MODULE_CC = {"Q": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Master Yi",
    PACKET_SHA256,
    packet_part_timings={"Q": {"time_offset": _Q_REAPPEAR_SECONDS}},
    slot_parsers={
        "P": _double_strike,
        "W": _meditate,
        "R": _highlander,
    },
    cc_kinds=MODULE_CC,
)

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "Double Strike procs on every 3rd basic attack; the second strike "
    "deals 50% AD physical damage — wiki prose (module constants)",
    "The second strike 'is affected by critical strike modifiers' and "
    "'separately rolls a critical strike' (cached P effect 1 and notes), "
    "so the on-hit row declares crit_effectiveness=1.0 and the engine "
    "prices it at the fight's own crit chance and multiplier.",
    "Only basic attacks generate stacks (Alpha Strike explicitly does "
    "not; Meditate's channel stacks are not simulated)",
    "The engine prices the proc spread across the 3 stacking hits "
    "(Vayne W convention); the 4-second stack window is assumed not to "
    "expire during sustained combat",
    "W (Meditate) heals for 8 ticks at 0.5-second intervals over the "
    "4-second channel, interpolated between Minimum Heal Per Tick and "
    "Maximum Heal Per Tick by the fighter's live missing health "
    "(healing.py 'Master Yi' rule); the channel's damage reduction is "
    "a defensive state not staged by the damage model.",
    "R (Highlander) grants the cached Bonus Attack Speed row "
    "(25/45/65%) for the sourced 7 seconds; the fight engine applies it "
    "to the auto count, time-weighted by the share of the fight window "
    "the buff covers.  R's bonus movement speed, slow/cripple immunity "
    "and takedown cooldown refund are named rather than priced.",
]

# No MODULE_COVERAGE: all five slots carry a priced row now — W's is the
# healing rule's self-heal ledger, R's the attack-speed stat_buff — which
# is exactly what the contract derives from SLOTS.


# Meditate channels for up to 4 seconds, healing Master Yi every 0.5
# seconds, increased by 0% : 100% (based on missing health) between the
# sourced Minimum Heal Per Tick and Maximum Heal Per Tick rows (8 ticks;
# Minimum/Maximum Total Heal == 8 x per-tick at every rank).  W deals no
# enemy damage, so the W cast timeline is the sourced trigger — the heal
# is paid on the channel's own tick schedule, not inferred from hits.
# pylint: disable=too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Resolve Master Yi self-healing events from its authored packet."""
    healing = []
    w_rank = _healing.parsed_rank(ability_damages, "W")
    w_ability = _healing.ability_json(champion_data, "W")
    min_tick = extract_named(w_ability, "Minimum Heal Per Tick", w_rank, champion_stats)
    max_tick = extract_named(w_ability, "Maximum Heal Per Tick", w_rank, champion_stats)
    if min_tick > 0.0:
        for cast_time in _healing.cast_slot_times(cast_timeline, "W"):
            start = float(cast_time)
            healing.extend(
                {
                    "time": start + index * 0.5,
                    "amount": 0.0,
                    "amount_formula": _healing.missing_health_scaled_heal(
                        min_tick, max_tick
                    ),
                    "source": "Meditate",
                    "kind": "champion_ability",
                    "actor_wide": True,
                }
                for index in range(1, 9)
            )
    return healing


SELF_HEALING_RULE = self_healing_rule("Master Yi")(derive_self_healing)
