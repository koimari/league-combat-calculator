"""Mordekaiser: full-entry-reviewed packet module.

P (Darkness Rise) rides the swing stream as two rows: ``passive`` is the 40% AP
bonus magic damage on every basic attack, and ``passive_darkness_rise`` is the
aura, walked from the third stacking hit, basic attacks and Q casts and E claws,
to the fight end at one tick per second.
W (Indestructible) is a non-damaging state slot whose grey-health receipts live
in the shared participant-timeline primitive: it stores a share of damage dealt
and damage taken as Potential Shield under a maximum-health cap, and pays the
recast heal at the earliest recast time, half a second after the W cast.  The
engine's cast timeline still schedules the W cast that arms it.
R (Realm of Death) deals no damage either, but it heals Mordekaiser for 10% of
the TARGET's maximum health.  A share of another unit's maximum health is the
one number the self-heal rule cannot read, the rule never seeing target stats,
so the slot prices it here against this pair fight's target and the rule places
it at the R cast.  The stat theft in the same sentence has no engine axis.
"""

import math
import re
from typing import Any

from .. import healing_helpers as _healing
from ..ability_atoms import ability_field, ability_payload
from ..ability_prose import CachedSentence
from ..ability_spec import DamagePart
from ..binary_roots import (
    calculation_coefficient,
    calculation_constant,
    calculation_interpolation,
    data_value,
    spell_object,
)
from .engine import ONHIT, SlotCtx
from .healing_contract import SelfHealCtx, self_healing_rule
from .module_helpers import ability_cast_times, ability_slot
from .packet_module import build_packet_module
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
_R_DRAIN = CachedSentence(
    re.compile(
        r"healing himself for\s+(?P<value>\d+(?:\.\d+)?)%\s+of their maximum health",
        re.IGNORECASE,
    ),
    missing=(
        "Mordekaiser R (Realm of Death): the cached active no longer states "
        "the soul drain ('healing himself for N% of their maximum health')"
    ),
)


@ability_slot("P")
def _darkness_rise_on_hit(
    ctx: SlotCtx, ability: dict[str, Any]
) -> dict[str, Any] | None:
    """P: the bonus magic damage every basic attack carries (40% AP)."""
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
        percent = _R_DRAIN.value(ctx.ability("R") or {})
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
    "P (Darkness Rise) adds 40% AP magic on every basic attack (binary "
    "PercentAPAddedToAutos).",
    "Rageblade phantom hits apply that on-hit again.",
    "The aura ticks 5 + 30% AP + 1 to 5% by level of target maximum health each "
    "second from the 3rd hit.",
    "P's stacks are assumed to refresh, the hits being swings, Q at each mirrored "
    "cast and E at each claw.",
    "The walk uses one set of hands and no resource exhaustion.",
    "The 4s tail past the fight end, the 3/6/9% movement speed and the monster cap "
    "are not priced.",
    "W (Indestructible) stores 45% of post-mitigation damage dealt and 7.5% of damage "
    "taken.",
    "The Potential Shield caps at 30% of maximum health.",
    "The recast, modeled at W cast + 0.5s, heals 35/37.5/40/42.5/45% by rank of the "
    "stored shield.",
    "The grey-health primitive authors it from both ledgers; conversion and decay "
    "curves are state.",
    "W (Indestructible) deals no enemy damage in any channel.",
    "The cached entry lists only the Potential Shield store, the shield active and "
    "the recast heal.",
    "The binary's MordekaiserW has no damage field and the v2 atoms tag it heal and "
    "shield only.",
    "Its shield and recast heal are priced by the grey-health primitive, so the slot "
    "is no_damage.",
    "R (Realm of Death) heals 10% of the banished champion's maximum health at the "
    "cast (cached R prose).",
    "Only the primary defender's pair fight authors it: one banishment, one heal.",
    "R itself deals no enemy damage; its binary carries SpiritRealmDuration, "
    "ZoneRadius, GhostAPRatio and the steal scalar.",
    "The 7s stat theft of 10% of the target's stats and the Death Realm are not "
    "modeled.",
    "The attacker-only stat_buff channel has no defender input, so pricing the steal "
    "would invent stats.",
]

# No MODULE_COVERAGE any more: W's Potential Shield recast heal is
# authored by the grey-health primitive and R's soul drain by the
# self-heal rule, so every slot in SLOTS now prices a row the engine
# consumes — which is what the contract derives.


def derive_self_healing(ctx: SelfHealCtx) -> list[dict[str, Any]]:
    """Price Realm of Death's soul drain: one banishment, one heal.

    Mordekaiser "consumes the target's soul ..., healing himself for 10%
    of their maximum health" at the cast.  Only R can price a share of the
    *target's* health, so it carries the amount on its row for the primary
    defender; the heal is paid at the cast and is actor-wide so a roster
    does not pay it once per enemy.  W's Potential Shield recast heal is
    the grey-health primitive's, not this rule's.
    """
    healing: list[dict[str, Any]] = []
    realm = ability_payload(ctx.ability_damages, "R").get("self_heal_state")
    if isinstance(realm, dict):
        amount = float(ability_field(realm, "amount", form="self_heal_state"))
        healing.extend(
            {
                "time": cast_time,
                "amount": amount,
                "source": "Realm of Death",
                "kind": "champion_ability",
                "actor_wide": True,
            }
            for cast_time in _healing.cast_slot_times(ctx.cast_timeline, "R")
        )
    return healing


SELF_HEALING_RULE = self_healing_rule("Mordekaiser")(derive_self_healing)
