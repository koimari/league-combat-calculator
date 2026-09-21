"""Master Yi: reviewed packet slots plus the Double Strike passive.

P (Double Strike) is an on-hit stack slot: basic attacks build three stacks and
the next attack strikes twice, the second for 50% AD physical.  The engine's
every-Nth-hit machinery prices it with ``stacks_required`` 3 on autos only,
spreading the per-proc strike across the three stacking hits.  Alpha Strike
grants no stack, so ability hits never count.
W (Meditate) is declared in SLOTS so the rotation casts the channel.  Its
self-heal is authored by the healing rule as eight ticks at the sourced 0.5s
cadence, each interpolated between the Minimum and Maximum Heal Per Tick rows by
live missing health.  Its damage-reduction window is a defensive state the
damage model does not stage.
E (Wuju Style) rides the swing stream: the cached "Bonus True Damage" row is an
on-hit on every basic attack inside the sourced 5-second window, placed once at
the E cast.  The engine keeps a schedule-gated rider out of phantom-hit
doubling, so Rageblade phantoms and Double Strike's second strike never
re-apply it.
R (Highlander) is the attack-speed steroid over its sourced 7-second window, a
BUFF-phase ``stat_buff``, so the auto count scales with it.
"""

from typing import Any

from .. import healing_helpers as _healing
from ..binary_roots import calculation_coefficient, data_value, spell_object
from .engine import BUFF, ONHIT, SlotCtx
from .healing_contract import SelfHealCtx, self_healing_rule
from .module_helpers import (
    ability_slot,
    buff_window_share,
    no_damage_slot,
    ranked_slot,
    steroid_entry,
)
from .packet_module import build_packet_module
from .slot_entries import ability_on_hit_entry
from .slot_extract import ability_name, extract_cooldown, extract_named, extract_value

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
# Wuju Style's window is the binary WujuStyle.Duration DataValue; the
# cached E prose ("within the next 5 seconds") corroborates it.
_E_DURATION_SECONDS = data_value(spell_object("Master Yi", "WujuStyle"), "Duration")


@ability_slot()
def _double_strike(ctx: SlotCtx, ability: dict[str, Any]) -> dict[str, Any] | None:
    """P: every 3rd auto strikes twice — second strike 50% AD physical."""
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


_meditate = no_damage_slot(
    "4-second channel: the self-heal (Minimum/Maximum Heal Per Tick, "
    "missing-health scaled) is authored by healing.py; the damage-"
    "reduction window is a defensive state not staged by the damage "
    "model",
    dmg_type="physical",
)


@ranked_slot
def _wuju_style(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """E: bonus true damage on every basic attack inside the 5-second window."""

    per_hit = extract_named(ability, "Bonus True Damage", rank, ctx.stats, ctx.target)
    entry = ability_on_hit_entry(
        ability_name(ability),
        rank,
        "true",
        {
            "name": "Wuju Style (on-hit)",
            "damage_per_hit": per_hit,
            "damage_type": "true",
            "proc_window": _E_DURATION_SECONDS,
        },
        cooldown=extract_cooldown(ability, rank),
    )
    entry["detail"] = (
        f"{per_hit:g} bonus true damage on-hit on every basic attack for "
        f"{_E_DURATION_SECONDS:g}s from the E cast (one window per fight)"
    )
    return entry


@ranked_slot
def _highlander(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """R: the 25/45/65% attack-speed steroid, priced onto the auto count."""

    granted = extract_value(ability, "Bonus Attack Speed", rank)
    movement = extract_value(ability, "Bonus Movement Speed", rank)
    bonus_as = granted * buff_window_share(ctx, _R_DURATION_SECONDS)
    return steroid_entry(
        ability,
        rank,
        {"bonus_attack_speed": bonus_as},
        (
            f"+{granted:g}% bonus attack speed for {_R_DURATION_SECONDS:g}s "
            f"({bonus_as:g}% over the fight window); the row's "
            f"+{movement:g}% movement speed, the crowd-control immunities and "
            "the takedown cooldown refund have no channel"
        ),
    )


_highlander.phase = BUFF


# Reviewed crowd control, read from the cached kit.  Alpha Strike marks
# and detonates for damage and on-hit effects only — nothing in the entry
# controls the enemies it strikes (Master Yi is the one made unable to
# act).  P is an on-hit rider, W a self-channel, R a self-buff.
#
# E reviews to no control: Wuju Style "empowers his basic attacks within
# the next 5 seconds to deal bonus true damage on-hit", a rider on the
# swing stream with no part of its own.
MODULE_CC = {"Q": "none", "P": "none", "W": "none", "E": "none", "R": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Master Yi",
    PACKET_SHA256,
    packet_part_timings={"Q": {"time_offset": _Q_REAPPEAR_SECONDS}},
    slot_parsers={
        "P": _double_strike,
        "W": _meditate,
        "E": _wuju_style,
        "R": _highlander,
    },
    cc_kinds=MODULE_CC,
)

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "Double Strike procs every 3rd basic attack for 50% AD physical, a wiki-prose "
    "module constant.",
    "The second strike is affected by crit modifiers and rolls its own crit (cached P "
    "effect 1 and notes).",
    "Its on-hit row declares crit_effectiveness 1.0, priced at the fight's crit "
    "chance and multiplier.",
    "Only basic attacks generate stacks (Alpha Strike explicitly does "
    "not; Meditate's channel stacks are not simulated)",
    "The proc is spread across the 3 stacking hits, its 4s window assumed not to "
    "expire in sustained combat.",
    "E (Wuju Style) is an on-hit on every basic attack inside the sourced 5s window "
    "from the E cast.",
    "One window per fight is placed; the recast a longer fight would earn is not.",
    "It is never a direct hit of the cast, and phantom hits and the second strike do "
    "not re-apply it.",
    "W (Meditate) heals 8 ticks at 0.5s over its 4s channel, between the Minimum and "
    "Maximum per-tick rows.",
    "The interpolation is live missing health; the channel's damage reduction is "
    "defensive state.",
    "R (Highlander) grants the cached 25/45/65% Bonus Attack Speed for the sourced "
    "7s, time-weighted.",
    "R's movement speed, slow immunity and takedown refund are named rather than "
    "priced.",
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
def derive_self_healing(ctx: SelfHealCtx) -> list[dict[str, Any]]:
    """Resolve Master Yi self-healing events from its authored packet."""
    healing = []
    w_rank = _healing.parsed_rank(ctx.ability_damages, "W")
    w_ability = _healing.ability_json(ctx.champion_data, "W")
    min_tick = extract_named(
        w_ability, "Minimum Heal Per Tick", w_rank, ctx.champion_stats
    )
    max_tick = extract_named(
        w_ability, "Maximum Heal Per Tick", w_rank, ctx.champion_stats
    )
    if min_tick > 0.0:
        for cast_time in _healing.cast_slot_times(ctx.cast_timeline, "W"):
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
