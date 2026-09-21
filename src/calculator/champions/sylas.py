"""Sylas: full-entry-reviewed packet module.

P replaces the basic attack rather than adding to it, so it rides
``auto_attack_conversion`` and the module supplies only the non-AD
remainder, ``bonus_raw = 1.30 x AD + 0.30 x AP - AD``; the engine's
swing path owns the AD term, crits and mid-fight AD changes.  The ratios
are module constants because the cached entry's ``leveling`` arrays are
empty and the numbers live in description prose, so the tests re-derive
both from the binary.  TRAPS.md carries the shape for the next champion.
W (Kingslayer) heals on a missing-health scale through
``derive_self_healing``; E (Abscond/Abduct) prices the Abduct magic
damage and nothing else.
P's nonstandard critical strike is documented, not approximated: the
wiki records 175% + 30% where this kernel's ``crit_effectiveness``
scales the crit probability and ``state.crit_multiplier`` is global, and
at an ordinary Sylas build's zero crit chance both readings agree.
R (Hijack) stays ``out_of_scope``: its damage is another champion's ultimate.
Every attacker resolves to one validated contract, so modelling it needs a
cross-champion ultimate-import kernel.
"""

import re
from dataclasses import replace
from typing import Any

from .. import healing_helpers as _healing
from ..ability_prose import CachedSentence
from ..binary_roots import calculation_coefficients, spell_object
from ..damage_event_row import event_damage as _row_damage
from ..damage_event_row import event_time as _row_time
from .contract_vocabulary import coverage
from .engine import SlotCtx
from .healing_contract import SelfHealCtx, self_healing_rule
from .inputs import int_option
from .packet_module import build_packet_module
from .shared_option_keys import PASSIVE_PROCS_OPTION
from .slot_extract import ability_name

PACKET_SHA256 = "2c402273f8fc3938c635dbebea26dc7e22901e8a0a07e00ef933ab0d12d77b98"

_SYLAS_PASSIVE_SPELL = spell_object("Sylas", "SylasPassive")
_PRIMARY_COEFFICIENTS = calculation_coefficients(_SYLAS_PASSIVE_SPELL, "PassiveDamage")
_SECONDARY_COEFFICIENTS = calculation_coefficients(
    _SYLAS_PASSIVE_SPELL, "PassiveAoEDamage"
)
_PRIMARY_TOTAL_AD_RATIO = _PRIMARY_COEFFICIENTS[0]
_PRIMARY_AP_RATIO = _PRIMARY_COEFFICIENTS[1]
_SECONDARY_TOTAL_AD_RATIO = _SECONDARY_COEFFICIENTS[0]
_SECONDARY_AP_RATIO = _SECONDARY_COEFFICIENTS[1]
# Sourced cap on held Unshackled stacks: "stacking up to 3 times"
# (cached P effect 0). The binary's ``PassiveCharges=2`` is not the gameplay
# cap itself, so it remains a documented non-rooted boundary.
_MAX_UNSHACKLED_STACKS = 3
# The same sentence's other half: "generates a stack of Unshackled for 4
# seconds, refreshing on subsequent casts". The stack's own clock, which
# the walk needs to know when a banked stack is gone.
_UNSHACKLED_STACK = CachedSentence(
    re.compile(r"generates a stack of Unshackled for (?P<value>\d+(?:\.\d+)?) seconds"),
    missing=(
        "Sylas P: the cached innate no longer states the Unshackled stack "
        "duration ('generates a stack of Unshackled for N seconds')"
    ),
)


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


def _petricite_burst(packet_passive):
    """P: convert the first N swings into empowered magic attacks.

    ``auto_attack_conversion`` wants the NON-AD remainder only: the
    engine adds the swing's own AD (and crits it) before mitigating the
    whole instance as magic.  The empowered attack's total is
    ``1.30 x total AD + 0.30 x AP``, so the remainder this module owns is
    ``0.30 x total AD + 0.30 x AP`` (the Galio Colossal Smash contract,
    which subtracts total AD from the modified total for the same
    reason).  It is a CONVERSION, not bonus on-hit damage: the empowered
    swing replaces its own physical damage and is mitigated as magic, so
    an on-hit reading would invent roughly one whole auto per stack spent.

    The packet's own zero row is decorated rather than replaced, so the
    slot keeps its ``parts`` empty: it books no ability damage of its
    own, and nothing here may be summed a second time alongside the
    converted swing.
    """

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        entry = packet_passive(ctx)
        if entry is None:
            return None
        ability = ctx.ability("P")
        if ability is None:
            return None
        name = ability_name(ability)
        attacks = min(
            max(int(ctx.option(PASSIVE_PROCS_OPTION)), 0),
            _MAX_UNSHACKLED_STACKS,
        )
        total_ad = ctx.stat("attack_damage")
        ability_power = ctx.stat("ability_power")
        modified_total = (
            _PRIMARY_TOTAL_AD_RATIO * total_ad + _PRIMARY_AP_RATIO * ability_power
        )
        entry = dict(entry)
        entry["name"] = name
        entry["armed_procs"] = {
            "arming_slots": ("Q", "W", "E", "R"),
            "max_stacks": _MAX_UNSHACKLED_STACKS,
            "per_cast": 1,
            "stack_seconds": _UNSHACKLED_STACK.value(ability),
            "armed_at_start": False,
            "requested": ctx.options.get(PASSIVE_PROCS_OPTION) is not None,
        }
        entry["auto_attack_conversion"] = {
            "name": name,
            "count": attacks,
            "bonus_raw": max(0.0, modified_total - total_ad),
            "damage_type": "magic",
        }
        entry["detail"] = (
            f"{attacks} empowered basic attack(s) REPLACE their ordinary "
            f"swing with {modified_total:.2f} magic damage (130% total AD "
            "+ 30% AP), not bonus damage on top of it; the secondary-target "
            "whirl (40% AD + 20% AP), the nonstandard (175% + 30%) critical "
            "strike, the monster multiplier and the 125% bonus attack speed "
            "are all unmodeled"
        )
        return entry

    return parse


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
MODULE_CC = {"W": "none", "E": "immobilize", "Q": "slow", "P": "none", "R": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Sylas",
    PACKET_SHA256,
    # Kingslayer is one strike ("dashes to the front of the target enemy's
    # location then strikes them") and Abduct is one chain hit ("deal magic
    # damage to the first enemy hit"), so each packet is one part and one
    # hit the ledger can time — which is what carries their MODULE_CC
    # answer to the control-armed readers.
    single_hit_slots=frozenset({"W", "E"}),
    slot_wrappers={
        "P": _petricite_burst,
        "Q": _chain_lash,
    },
    cc_kinds=MODULE_CC,
)

OPTIONS = [
    *list(OPTIONS),
    int_option(
        PASSIVE_PROCS_OPTION,
        0,
        minimum=0,
        maximum=_MAX_UNSHACKLED_STACKS,
        label=(
            "Unshackled attacks spent; unset derives them from the casts "
            "that bank a stack and the swings that spend one"
        ),
        rotation={"role": "self_state", "slot": "P"},
        derives=True,
    ),
]

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "P (Petricite Burst) prices the empowered attack as a CONVERSION, not as bonus "
    "on-hit damage.",
    "Each Unshackled stack spent REPLACES one physical swing with 130% total AD + 30% "
    "AP magic.",
    "The game file's SylasPassive PassiveDamage is mStat 2 at 1.3 total AD plus a 0.3 "
    "AP coefficient, and nothing else.",
    "The module supplies only the non-AD remainder, 0.30 total AD + 0.30 AP, via "
    "auto_attack_conversion.",
    "The engine's own swing path keeps the AD term, so nothing is double counted.",
    "Pricing it as an added magic row would invent about one auto per swing and meet "
    "armor, not MR.",
    "The ratios are module constants: every leveling array on the cached P entry is "
    "empty.",
    "The numbers exist only in description prose, so the tests re-derive them from "
    "the game file.",
    "Attacks default to 0, fail-closed: stacks come from casts over a 4s window the "
    "engine cannot walk.",
    "The count is user-set caster state, capped at the sourced 3 stacks.",
    "P withholds four sourced riders rather than approximating them.",
    "The secondary-target whirl, 40% AD + 20% AP, needs nearby enemies the 1v1 "
    "surface lacks.",
    "The nonstandard critical strike, 175% + 30% rather than 200% + 30%, has no "
    "channel.",
    "DamagePart.crit_effectiveness scales crit PROBABILITY, not the multiplier, so "
    "encoding overstates.",
    "auto_attack_conversion crits the AD component at the standard multiplier and "
    "never the remainder.",
    "That coincides with the sourced reading at the zero crit chance of an ordinary "
    "Sylas build.",
    "The 115% monster multiplier cannot bind: target_class has no monster value.",
    "The secondary-target minion execute below 25 health is secondary-target only.",
    "The 125% bonus attack speed has no derivable uptime from a static build, and the "
    "windup no channel.",
    "R (Hijack) stays out_of_scope, NOT no_damage, by the Olaf-R rule.",
    "Its damage is another champion's ultimate, arriving through the free recast on "
    "Hijack's rank.",
    "The binary SylasR record carries only PerTargetCooldown and no damage formula.",
    "The blocker is a named kernel gap: every attacker resolves to one contract and "
    "others fail closed.",
    "No surface lets one champion's parse instantiate another champion's R at a rank "
    "of its own.",
    "The sourced conversion rule, 0.6% AP per 1% total AD and 0.4% per 1% bonus AD, "
    "has no channel.",
    "Nothing in the kernel rewrites a foreign ability's scaling terms.",
    "Modelling R needs a cross-champion ultimate-import kernel, a project rather than "
    "a slot.",
]
MODULE_COVERAGE = coverage(out_of_scope="R")


def derive_self_healing(ctx: SelfHealCtx) -> list[dict[str, Any]]:
    """Resolve Sylas self-healing events from its authored packet."""
    healing = []
    min_heal, max_heal = ctx.ranked_rows("W", "Minimum Heal", "Maximum Heal")
    for payment in ctx.payments(_healing.HealAnchor.CAST, "W"):
        event = payment.event
        if _row_damage(event) <= 0.0:
            continue
        healing.append(
            {
                "time": _row_time(event),
                "amount": 0.0,
                "amount_formula": _healing.missing_health_scaled_heal(
                    min_heal, max_heal
                ),
                "source": "Kingslayer",
                "kind": "champion_ability",
                **_healing.trigger_fields(event),
            }
        )
    return healing


SELF_HEALING_RULE = self_healing_rule("Sylas")(derive_self_healing)

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "E (Abscond/Abduct) carries no shield in the current kit.",
    "The pinned cached data has no shield row on either E entry, so the magic-damage "
    "packet is complete.",
]
