"""Mordekaiser — CP10.4 full-entry-reviewed packet module.

P (Darkness Rise) rides the swing stream as two rows: ``passive`` is the
40% AP bonus magic damage on every basic attack, and
``passive_darkness_rise`` is the aura, walked from the third stacking hit
(basic attacks, Q casts, E claws) to the fight end at one tick per
second; the reviewed packet had priced neither.

E8a: the W (Indestructible) grey-health receipts live in the shared
participant-timeline primitive, which stores 45% of post-mitigation
damage dealt + 7.5% of pre-mitigation damage taken as Potential Shield
(capped at 30% of maximum health) and pays the recast heal
("Shield to Healing" 35/37.5/40/42.5/45% by W rank) at the earliest
recast time (W cast + 0.5 s per the wiki).  The module keeps pricing W
as a non-damaging state-only slot; the engine's cast timeline still
schedules the W cast that arms the recast.

R (Realm of Death) deals no damage either, but it "consumes the target's
soul ..., healing himself for 10% of their maximum health".  That share
of *another unit's* maximum health is the one number the self-heal rule
cannot read — the rule never sees target stats — so the slot prices it
here, against the champion this pair fight targets, and the rule places
it at the R cast.  The stat theft in the same sentence (10% of the
target's AP, attack speed, maximum health, resistances and AD, granted
to Mordekaiser for 7 seconds) has no engine axis and stays documented.
"""

import math
import re
from typing import Any

from .. import healing_helpers as _healing
from ..ability_atoms import ability_payload
from ..ability_spec import DamagePart
from ..binary_roots import (
    calculation_coefficient,
    calculation_constant,
    calculation_interpolation,
    data_value,
    spell_object,
)
from .engine import ONHIT, SlotCtx
from .healing_contract import self_healing_rule
from .module_helpers import ability_cast_times
from .packet_module import build_packet_module
from .shared_mechanics import prose_numbers
from .slot_entries import damage_entry, on_hit_entry
from .slot_extract import ability_name
from .slotlib import simple_damage

PACKET_SHA256 = "62dd25de0191c8de67cec4f56eaebf7ad2bfa32cf704569b553e18049647d228"

# Darkness Rise, from the binary MordekaiserPassive: every basic attack
# carries PercentAPAddedToAutos as bonus magic damage; a basic attack or
# basic ability that damages a champion adds a stack (MaximumStacks), and
# at the cap the aura ticks AuraDamagePerStack (5 + 30% AP) plus
# PercentHealthForAura (1% to 5% by level) of the target's maximum health
# every second (the cached P prose: "magic damage every second").  The
# aura's 0.125-second sub-ticks sum to the same per-second amount.
_MORDEKAISER_P_SPELL = spell_object("Mordekaiser", "MordekaiserPassive")
_P_ON_HIT_AP_RATIO = data_value(_MORDEKAISER_P_SPELL, "PercentAPAddedToAutos")
_P_RISE_STACKS = int(data_value(_MORDEKAISER_P_SPELL, "MaximumStacks"))
_P_AURA_BASE = calculation_constant(_MORDEKAISER_P_SPELL, "AuraDamagePerStack")
_P_AURA_AP_RATIO = calculation_coefficient(_MORDEKAISER_P_SPELL, "AuraDamagePerStack")
_P_AURA_HEALTH_LEVEL_1, _P_AURA_HEALTH_LEVEL_18 = calculation_interpolation(
    _MORDEKAISER_P_SPELL, "PercentHealthForAura"
)
_P_AURA_TICK_SECONDS = 1.0

# Death's Grasp lands on its own delay: Mordekaiser "summons a claw in the
# target direction that grants sight of the area. After 0.5 seconds, it
# deals magic damage to enemies within and pulls them over 250 units"
# (data/champions.json Mordekaiser E).  The cached entry attaches no
# cast-time qualifier to the number, so it is read from the cast start as
# written.
_E_CLAW_SECONDS = data_value(
    spell_object("Mordekaiser", "MordekaiserE"), "DelayBeforeMovement"
)

# R carries no leveling row at all — the drain is one sentence of the
# cached R prose, so the percentage is read from there rather than pinned
# as a module constant.
_R_DRAIN_PROSE = re.compile(
    r"healing himself for\s+(\d+(?:\.\d+)?)%\s+of their maximum health",
    re.IGNORECASE,
)


def _darkness_rise_on_hit(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: the bonus magic damage every basic attack carries (40% AP)."""
    ability = ctx.ability("P")
    if ability is None:
        return None
    per_hit = _P_ON_HIT_AP_RATIO * float(ctx.stat("ability_power"))
    entry = on_hit_entry(ability_name(ability), per_hit, "magic")
    entry["detail"] = (
        f"{per_hit:g} bonus magic damage on-hit ({_P_ON_HIT_AP_RATIO * 100:g}% AP) "
        "on every basic attack; the aura is the passive_darkness_rise row"
    )
    return entry


_darkness_rise_on_hit.phase = ONHIT


def _stacking_hit_times(ctx: SlotCtx, duration: float) -> list[float]:
    """When the fight's stacking hits land: basic attacks, Q at the cast, E at the claw."""
    rate = float(ctx.stat("attack_speed")) * float(ctx.option("auto_attack_uptime"))
    hits = (
        [index / rate for index in range(math.floor(rate * duration))] if rate else []
    )
    hits.extend(
        time + (_E_CLAW_SECONDS if slot == "E" else 0.0)
        for time, slot in ability_cast_times(ctx, duration, ("Q", "E"))
    )
    return sorted(hits)


def _darkness_rise_aura(ctx: SlotCtx) -> dict[str, Any] | None:
    """Aura: per-second magic damage from the third stacking hit to the fight end.

    The stacks refresh on every later hit, so a fight that keeps hitting
    holds the aura for the rest of the window; the walk mirrors the
    rotation the way Braum's passive does (one set of hands, no resource
    exhaustion).  Nothing is priced past the fight end, and a fight with no
    window (one rotation) or fewer than three hits emits nothing.
    """
    ability = ctx.ability("P")
    duration = float(ctx.option("fight_duration_seconds"))
    if ability is None or duration <= 0.0:
        return None
    hits = _stacking_hit_times(ctx, duration)
    if len(hits) < _P_RISE_STACKS:
        return None
    rise_at = hits[_P_RISE_STACKS - 1]
    ticks = math.floor((duration - rise_at) / _P_AURA_TICK_SECONDS)
    if ticks <= 0:
        return None
    health_percent = (
        _P_AURA_HEALTH_LEVEL_1
        + (_P_AURA_HEALTH_LEVEL_18 - _P_AURA_HEALTH_LEVEL_1) * (ctx.level - 1) / 17.0
    )
    per_tick = (
        _P_AURA_BASE
        + _P_AURA_AP_RATIO * float(ctx.stat("ability_power"))
        + health_percent / 100.0 * float(ctx.target_stat("target_max_health"))
    )
    # A proc row, not a cast: no cooldown, priced once with its own walked
    # ledger (the Braum convention).
    entry = damage_entry(
        f"{ability_name(ability)} (aura)", ctx.level, 0.0, per_tick * ticks, "magic"
    )
    entry["parts"] = (DamagePart("magic", per_tick, count=ticks),)
    entry["proc_count"] = 1
    entry["timeline_event_model"] = "module_walk"
    entry["damage_events"] = [
        {
            "time": rise_at + index * _P_AURA_TICK_SECONDS,
            "damage_type": "magic",
            "damage": per_tick,
            "event_precision": "exact",
        }
        for index in range(1, ticks + 1)
    ]
    entry["event_phase"] = "effect"
    entry["detail"] = (
        f"Darkness Rise from the {_P_RISE_STACKS}rd stacking hit at "
        f"{rise_at:.2f}s: {ticks} tick(s) of {per_tick:.1f} magic damage "
        f"({_P_AURA_BASE:g} + {_P_AURA_AP_RATIO * 100:g}% AP + "
        f"{health_percent:.2f}% of the target's maximum health) per second"
    )
    return entry


def _realm_of_death(compiled):
    """R: carry the sourced soul-drain heal for the primary target."""

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        entry = compiled(ctx)
        if entry is None or ctx.rank_for("R") < 1:
            return entry
        # Realm of Death banishes exactly one champion, so only the pair
        # fight against the primary defender may author the drain; a
        # roster must not heal Mordekaiser once per enemy.
        if int(ctx.target_stat("roster_target_index")) != 0:
            return entry
        drain = prose_numbers(ctx, "R", _R_DRAIN_PROSE)
        if drain is None:
            return entry
        percent = drain[0]
        amount = percent / 100.0 * float(ctx.target_stat("target_max_health"))
        if amount <= 0.0:
            return entry
        entry["self_heal_state"] = {"percent": percent, "amount": amount}
        entry["detail"] = (
            f"{str(entry.get('detail', '')).strip()} Soul drain: {percent:g}% "
            f"of the target's maximum health ({amount:.1f})."
        ).strip()
        return entry

    return parse


# Reviewed crowd control, read from the cached kit.  Obliterate "deal[s]
# magic damage to enemies within, increased if only one enemy is hit" and
# applies nothing else.  Death's Grasp "deals magic damage to enemies
# within and pulls them over 250 units" — the pull lands with the damage
# on the same 0.5-second claw, which the slot now authors.  P (Darkness
# Rise) is the on-hit and its aura row only damages, and W and R author no
# damage part.
MODULE_CC = {
    "Q": "none",
    "E": "pull",
    "P": "none",
    "passive_darkness_rise": "none",
    "W": "none",
    "R": "slow",
}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Mordekaiser",
    PACKET_SHA256,
    packet_part_timings={"E": {"time_offset": _E_CLAW_SECONDS}},
    slot_parsers={
        # The reviewed packet folded Obliterate's per-level term into its per-rank
        # base, so one index served both and the level term was read at the rank —
        # at level 18 rank 5 the swing priced its level-5 scaling.  Reading the
        # cached row through the shared slot repairs the axis without changing
        # which row is read.
        "Q": simple_damage(
            attr="Magic Damage",
            dmg_type="magic",
            event_order_certified="single_hit",
        ),
        "P": _darkness_rise_on_hit,
        "passive_darkness_rise": _darkness_rise_aura,
    },
    slot_wrappers={"R": _realm_of_death},
    cc_kinds=MODULE_CC,
)

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "P (Darkness Rise) is two rows on the swing stream: the 40% AP bonus "
    "magic damage is an on-hit on every basic attack (binary "
    "PercentAPAddedToAutos; Rageblade phantom hits apply it again), and "
    "the aura (passive_darkness_rise) ticks 5 + 30% AP + 1% to 5% by level "
    "of the target's maximum health every second from the third stacking "
    "hit to the fight end. The stacking hits are the basic attacks at the "
    "fight's swing cadence, Q at each mirrored cast and E at each cast's "
    "claw (Braum-pattern walk: one set of hands, no resource exhaustion), "
    "and the stacks are assumed to refresh for the rest of the window; the "
    "4-second tail past the fight end, the 3/6/9% movement speed and the "
    "monster cap are not priced.",
    "W (Indestructible) stores 45% of post-mitigation damage dealt and "
    "7.5% of pre-mitigation damage taken as Potential Shield (capped at "
    "30% of maximum health); the recast (modeled at W cast + 0.5 s, the "
    "wiki's earliest available recast) heals the Shield-to-Healing % "
    "(35/37.5/40/42.5/45% by W rank) of the stored shield — the E8a "
    "grey-health primitive authors it from the incoming/outgoing "
    "ledgers. Shield conversion and both decay curves are state.",
    "W (Indestructible) deals no enemy damage in any channel: the "
    "cached wiki entry lists only the Potential Shield store, the "
    "shield active and the recast heal, the game binary's MordekaiserW "
    "spell object has no damage field (only Duration/DamageConversion/"
    "BaseShield/HealingPercent/MinionPenalty/DamageTakenConversion/"
    "MaxHealthCap/TimeBeforeDecay/DecayPerSecond), and the v2 atoms "
    "capture tags it Trait_ActiveHeal + Trait_Shield with no damage "
    "atom.  Its shield and recast heal are priced by the E8a "
    "grey-health primitive, so the slot is no_damage, not withheld.",
    "R (Realm of Death) heals 10% of the banished champion's maximum "
    "health at the cast (cached R prose). Only the primary defender's "
    "pair fight authors it — one banishment, one heal. R itself deals "
    "no enemy damage (binary MordekaiserR carries only "
    "SpiritRealmDuration/StatStealPercentScalar/ZoneRadius/"
    "GhostAPRatio; v2 atoms tag it Trait_ImmobilizingCCSpell + "
    "Trait_ActiveHeal). The 7-second stat theft (10% of the target's "
    "ability power, total attack speed, maximum health, armour, magic "
    "resistance and total AD, transferred to Mordekaiser) and the "
    "Death Realm itself are not modeled: the attacker-only stat_buff "
    "channel (_apply_stat_buff_ultimates) has no defender input, so "
    "pricing the steal would mean inventing the target's stats.",
]

# No MODULE_COVERAGE any more: W's Potential Shield recast heal is
# authored by the grey-health primitive and R's soul drain by the
# self-heal rule, so every slot in SLOTS now prices a row the engine
# consumes — which is what the contract derives.


# pylint: disable=too-many-arguments,too-many-positional-arguments,unused-argument
def derive_self_healing(
    champion_data: dict[str, Any],
    champion_stats: dict[str, float],
    ability_damages: dict[str, dict[str, Any]],
    damage_events: list[dict[str, Any]],
    cast_timeline: list[dict[str, Any]] | None = None,
    fight_duration_seconds: float | None = None,
) -> list[dict[str, Any]]:
    """Price Realm of Death's soul drain: one banishment, one heal.

    Mordekaiser "consumes the target's soul ..., healing himself for 10%
    of their maximum health" at the cast.  Only R can price a share of the
    *target's* health, so it carries the amount on its row for the primary
    defender; the heal is paid at the cast and is actor-wide so a roster
    does not pay it once per enemy.  W's Potential Shield recast heal is
    the grey-health primitive's, not this rule's.
    """
    healing: list[dict[str, Any]] = []
    realm = ability_payload(ability_damages, "R").get("self_heal_state")
    if isinstance(realm, dict):
        amount = float(realm.get("amount", 0.0) or 0.0)
        healing.extend(
            {
                "time": cast_time,
                "amount": amount,
                "source": "Realm of Death",
                "kind": "champion_ability",
                "actor_wide": True,
            }
            for cast_time in _healing.cast_slot_times(cast_timeline, "R")
        )
    return healing


SELF_HEALING_RULE = self_healing_rule("Mordekaiser")(derive_self_healing)
