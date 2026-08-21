"""Sylas — CP10.8 full-entry-reviewed packet module, plus the P1 E-shield note.

The CP-era "SylasEShield" atom (Abscond/Abduct shield, 80/115/150/185/220
+ 100% AP for 2s) is HISTORICAL: the wiki patch history records it as
removed — "Abscond Removed: ... No longer shields for 80 / 115 / 150 /
185 / 220 (+ 100% AP) against magic damage for 2 seconds upon dashing"
(V10.2 patch note).  The pinned cached data (patch 16.15) carries no
shield row on either E entry, matching the live kit, so the module's E
packet (Abduct magic damage) is complete — the shield atom is documented
as a stale receipt, not a missing mechanic.

E1-b2: Sylas is in HEALING_RULE_CHAMPIONS — W Kingslayer's
missing-health-scaled heal (Minimum/Maximum Heal rows) is authored by
``derive_self_healing`` (test_sylas_kingslayer_heals_scaled_by_missing).

Coverage-frontier rider: P (Petricite Burst) is the empowered attack
every cast stocks — "Whenever Sylas casts an ability, he generates a
stack of Unshackled ... stacking up to 3 times.  Unshackled: Sylas' next
basic attack ... consume[s] a stack to whirl his chains around him,
dealing 130% AD (+ 30% AP) magic damage to the primary target".  The
cached P entry carries no leveling row at all, so both ratios are module
constants read from that sentence.  ``p_procs`` is how many stocked
attacks the fight spends and defaults to the sourced 3-stack cap.

R (Hijack) stays ``out_of_scope``: it casts a copy of another champion's
ultimate, an axis the engine has no surface for — no second champion's
kit is in the request, and the "0.6% AP per 1% total AD" ratio
conversion has nothing to convert.
"""

from dataclasses import replace
from typing import Any

from .. import healing_helpers as _healing
from .engine import ONHIT, SlotCtx
from .healing_contract import declare_healing_rule
from .packet_module import build_packet_module
from .slotlib import on_hit_entry

PACKET_SHA256 = "2c402273f8fc3938c635dbebea26dc7e22901e8a0a07e00ef933ab0d12d77b98"

# HARDCODED: verify on patch updates — the cached Petricite Burst entry
# has no leveling rows whatsoever; every number is wiki prose:
# "dealing 130% AD (+ 30% AP) magic damage to the primary target",
# "stacking up to 3 times".
_PETRICITE_AD_RATIO = 1.30
_PETRICITE_AP_RATIO = 0.30
_UNSHACKLED_MAX_STACKS = 3


def _chain_lash(packet_q):
    """Q: the packet's Total Magic Damage row, declared at the cast.

    The row is the lash and the explosion "after a 0.6-second delay"
    summed into one lump, so it is not a single hit the ledger can
    certify.  Declaring the lump's own position — the cast boundary, where
    the lash lands — is the Xin Zhao W shape: it leaves the row's price
    and its aggregation alone and only says when the ledger sees it, which
    is what carries Q's reviewed slow to the control-armed readers.
    """

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        entry = packet_q(ctx)
        if entry is None:
            return None
        entry["parts"] = tuple(
            replace(part, time_offset=0.0) for part in entry.get("parts") or ()
        )
        return entry

    return parse


def _petricite_burst(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: the Unshackled empowered attack's chain whirl, once per stack."""
    ability = ctx.ability()
    if ability is None:
        return None
    per_hit = _PETRICITE_AD_RATIO * ctx.stat("attack_damage") + (
        _PETRICITE_AP_RATIO * ctx.stat("ability_power")
    )
    if per_hit <= 0:
        return None

    bursts = min(max(int(ctx.option("p_procs")), 0), _UNSHACKLED_MAX_STACKS)
    entry = on_hit_entry(ability.get("name", "Petricite Burst"), per_hit, "magic")
    entry["on_hit"]["max_procs"] = bursts
    entry["detail"] = (
        f"{bursts} Unshackled attack(s) of {per_hit:.2f} magic damage "
        f"({_PETRICITE_AD_RATIO:.0%} AD + {_PETRICITE_AP_RATIO:.0%} AP to "
        "the primary target); the empowered attack's 125% bonus attack "
        "speed, its 40% AD + 20% AP splash and its critical strike are "
        "not priced"
    )
    return entry


_petricite_burst.phase = ONHIT


# Reviewed crowd control, read from the cached kit.  W (Kingslayer)
# applies no control.  E (Abduct) deals its damage and "reveal[s] and
# stun[s] them for 0.5 seconds", then "knocks them up for 0.5 seconds upon
# arrival" — two immobilize kinds on the one target, so the reviewed
# answer is the un-narrowed one.  R (Hijack) deals no damage of its own.
#
# Q (Chain Lash) deals "magic damage to enemies hit and slow[s] them for
# 1.5 seconds"; its lumped row is declared at the cast boundary (see
# ``_chain_lash``) rather than split into the two cached rows, which was
# measured to move the row's ledger position.
MODULE_CC = {"W": "none", "E": "immobilize", "Q": "slow"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Sylas",
    PACKET_SHA256,
    # Kingslayer is one strike ("dashes to the front of the target enemy's
    # location then strikes them") and Abduct is one chain hit ("deal magic
    # damage to the first enemy hit"), so each packet is one part and one
    # hit the ledger can time — which is what carries their MODULE_CC
    # answer to the control-armed readers.
    single_hit_slots=frozenset({"W", "E"}),
    slot_parsers={
        "P": _petricite_burst,
    },
    slot_wrappers={
        "Q": _chain_lash,
    },
    cc_kinds=MODULE_CC,
)

OPTIONS.append(
    {
        "key": "p_procs",
        "type": "int",
        "default": _UNSHACKLED_MAX_STACKS,
        "min": 0,
        "max": _UNSHACKLED_MAX_STACKS,
        "label": "Petricite Burst attacks (Unshackled stacks spent)",
    }
)

MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"P", "Q", "W", "E"} else "out_of_scope")
    for slot in "PQWER"
}


# pylint: disable=protected-access,too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Resolve Sylas self-healing events from its authored packet."""
    healing = []
    w = _healing._ability(champion_data, "W")
    w_rank = _healing._rank(ability_damages, "W")
    min_heal = _healing.extract_named(w, "Minimum Heal", w_rank, champion_stats)
    max_heal = _healing.extract_named(w, "Maximum Heal", w_rank, champion_stats)
    for payment in _healing._payments(
        _healing.HealAnchor.CAST, "W", damage_events, cast_timeline
    ):
        event = payment.event
        if float(event.get("damage", 0.0)) <= 0.0:
            continue
        healing.append(
            {
                "time": float(event.get("time", 0.0)),
                "amount": 0.0,
                "amount_formula": _healing._missing_health_scaled_heal(
                    min_heal, max_heal
                ),
                "source": "Kingslayer",
                "kind": "champion_ability",
                **_healing._trigger_fields(event),
            }
        )
    return sorted(healing, key=lambda event: (event["time"], event["source"]))


SELF_HEALING_RULE = declare_healing_rule("Sylas", derive_self_healing)

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "E (Abscond/Abduct) carries no shield in the current kit: the CP-era "
    "SylasEShield atom (80/115/150/185/220 + 100% AP for 2s) was removed "
    "in V10.2 (wiki patch history: 'Abscond Removed: ... No longer "
    "shields ... for 2 seconds upon dashing'); the pinned cached data "
    "has no shield row on either E entry, so the E magic-damage packet "
    "is complete",
    "P (Petricite Burst) prices the Unshackled empowered attack at the "
    "wiki's 130% AD + 30% AP magic against the primary target — module "
    "constants, because the cached P entry carries no leveling row.  "
    "Each ability cast stocks one stack (cap 3) and each empowered "
    "attack spends one, so p_procs defaults to the 3-stack cap; the "
    "empowered attack's 125% bonus attack speed, the 40% AD + 20% AP "
    "secondary-target whirl, its minion execute and its (175% + 30%) "
    "critical strike are not priced.",
]
