"""Mordekaiser — CP10.4 full-entry-reviewed packet module.

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

import re
from typing import Any

from .engine import SlotCtx
from .healing_contract import declare_healing_rule
from .packet_module import build_packet_module
from .slotlib import simple_damage
from .. import healing_helpers as _healing

PACKET_SHA256 = "62dd25de0191c8de67cec4f56eaebf7ad2bfa32cf704569b553e18049647d228"

# Death's Grasp lands on its own delay: Mordekaiser "summons a claw in the
# target direction that grants sight of the area. After 0.5 seconds, it
# deals magic damage to enemies within and pulls them over 250 units"
# (data/champions.json Mordekaiser E).  The cached entry attaches no
# cast-time qualifier to the number, so it is read from the cast start as
# written.
_E_CLAW_SECONDS = 0.5

# R carries no leveling row at all — the drain is one sentence of the
# cached R prose, so the percentage is read from there rather than pinned
# as a module constant.
_R_DRAIN_PROSE = re.compile(
    r"healing himself for\s+(\d+(?:\.\d+)?)%\s+of their maximum health",
    re.IGNORECASE,
)


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
        ability = ctx.ability("R")
        if ability is None:
            return entry
        match = _R_DRAIN_PROSE.search(
            " ".join(
                effect.get("description", "") for effect in ability.get("effects", [])
            )
        )
        if match is None:
            return entry
        percent = float(match.group(1))
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
# Rise) is a basic-attack/aura row, and W and R author no damage part.
MODULE_CC = {"Q": "none", "E": "pull"}

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
    },
    slot_wrappers={"R": _realm_of_death},
    cc_kinds=MODULE_CC,
)

ASSUMPTIONS = list(ASSUMPTIONS) + [
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


# pylint: disable=protected-access,too-many-arguments,too-many-positional-arguments,unused-argument
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Price Realm of Death's soul drain: one banishment, one heal.

    Mordekaiser "consumes the target's soul ..., healing himself for 10%
    of their maximum health" at the cast.  Only R can price a share of the
    *target's* health, so it carries the amount on its row for the primary
    defender; the heal is paid at the cast and is actor-wide so a roster
    does not pay it once per enemy.  W's Potential Shield recast heal is
    the grey-health primitive's, not this rule's.
    """
    healing: list[dict[str, Any]] = []
    realm = ability_damages.get("R", {}).get("self_heal_state")
    if isinstance(realm, dict):
        amount = float(realm.get("amount", 0.0) or 0.0)
        for cast_time in _healing._cast_slot_times(cast_timeline, "R"):
            healing.append(
                {
                    "time": cast_time,
                    "amount": amount,
                    "source": "Realm of Death",
                    "kind": "champion_ability",
                    "actor_wide": True,
                }
            )
    return sorted(healing, key=lambda event: (event["time"], event["source"]))


SELF_HEALING_RULE = declare_healing_rule("Mordekaiser", derive_self_healing)
