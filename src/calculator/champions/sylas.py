"""Sylas — CP10.8 full-entry-reviewed packet module, plus the P1 E-shield note.

The CP-era "SylasEShield" atom (Abscond/Abduct shield, 80/115/150/185/220
+ 100% AP for 2s) is not part of the live kit: the wiki patch history
records its removal in V10.2, and the pinned cached data (patch 16.15)
carries no shield row on either E entry.  The module's E packet (Abduct
magic damage) is therefore complete, and the shield atom is a stale
receipt rather than a missing mechanic.

E1-b2: Sylas is in HEALING_RULE_CHAMPIONS — W Kingslayer's
missing-health-scaled heal (Minimum/Maximum Heal rows) is authored by
``derive_self_healing`` (test_sylas_kingslayer_heals_scaled_by_missing).

Roadmap session (2026-08-21): adjudicates Sylas' two remaining
out_of_scope slots.  P closes as ``modeled``; R stays open.

  - P (Petricite Burst) carries a real sourced damage formula, so the
    packet's implicit no-damage reading was INCOMPLETE: "Sylas' next
    basic attack ... is empowered to have an uncancellable windup and
    consume a stack to whirl his chains around him, dealing 130% AD
    (+ 30% AP) magic damage to the primary target and 40% AD (+ 20% AP)
    magic damage to nearby enemies".  The game binary agrees term for
    term (``SylasPassive``: ``PassiveDamage`` = 1.3 x total AD + 0.3 AP,
    ``PassiveAoEDamage`` = 0.4 x total AD + 0.2 AP, each with exactly two
    ``StatByCoefficientCalculationPart`` formula parts and no third
    term).

    **It is NOT bonus on-hit damage, and getting that wrong would have
    inflated Sylas.**  The empowered attack REPLACES the swing's own
    damage and converts it to magic; it does not stack on top.  Three
    independent reads agree: the ratio is 130% AD, which no bonus row
    could be (a bonus row cannot exceed a whole auto and still be
    called the attack's damage); the cached note "Spellblade damage does
    not get CONVERTED to magic damage" only parses if the attack's own
    damage *is* converted; and the wiki states the 130% AD (+ 30% AP) is
    the empowered attack's total, magic instead of physical, with
    on-hit effects and life steal still applying to the primary target.
    Pricing it as an added magic row would have invented roughly one
    full auto of damage per empowered swing AND mitigated the real swing
    against armor instead of magic resistance.

    So P rides ``auto_attack_conversion``, the kernel channel that
    already exists for exactly this shape — "a bounded set of attacks
    may replace their normal physical swing with one modified
    basic-damage instance" (the Galio Colossal Smash precedent).  The
    module supplies only the non-AD remainder,
    ``bonus_raw = 1.30 x AD + 0.30 x AP - AD``, and the engine's own
    swing path continues to own the AD term, crits and mid-fight AD
    changes.  The ratios are module constants because the cached entry's
    ``leveling`` arrays are ALL empty — the numbers live only in
    description prose (the Darius-P precedent for prose-only ratios),
    which is why the tests re-derive both from the binary rather than
    trusting the constants.

    Four sourced riders are deliberately NOT modeled:
      * the secondary/AoE whirl (40% AD + 20% AP).  It needs nearby
        enemies, which the 1v1 damage surface does not have;
      * the nonstandard critical strike.  The wiki records Petricite
        Burst critting for (175% + 30%) rather than the standard
        (200% + 30%), and this kernel cannot express that:
        ``DamagePart.crit_effectiveness`` scales the crit PROBABILITY,
        not the multiplier, and ``state.crit_multiplier`` is the global
        200%-plus-bonus figure, so the only available encoding would
        overstate the crit bonus.  ``auto_attack_conversion`` crits the
        AD component at the standard multiplier and never crits
        ``bonus_raw``; with the zero crit chance of an ordinary Sylas
        build the two readings coincide exactly.  Fail-closed: the
        divergence is documented, not approximated;
      * ``MonsterDamageMulti`` (115%) and the secondary-target minion
        execute below ``CheatingThreshold`` (25 health).  This engine's
        ``target_class`` has no monster value and the execute is
        secondary-target-only, so neither can bind;
      * the 125% bonus attack speed (binary ``PassiveAttackSpeed``
        1.25) and the uncancellable windup.  The steroid lasts only
        until the stack is spent, so its uptime is not derivable from a
        static build, and there is no windup channel.

  - R (Hijack) stays OPEN ``out_of_scope``.  The Olaf-R rule applies in
    its strongest form: this is not a slot whose damage is zero, it is a
    slot whose damage is *another champion's ultimate*.  Hijack's own
    binary record has one calculation, ``PerTargetCooldown``, and no
    damage formula — the damage arrives entirely through "Recast: Sylas
    casts his hijacked ultimate ability at no cost, scaling based on
    Hijack's rank and his own statistics".  Calling that ``no_damage``
    would be flatly false.

    The blocker is a named kernel gap, not an evidence gap.  Every
    attacker resolves to exactly one validated champion contract and
    unknown names fail closed (the named-module rule), so there is no
    surface on which one champion's parse can instantiate another
    champion's R at a rank of its own.  The sourced conversion rule that
    would make such an import correct — "abilities that do not scale
    with ability power have their attack damage ratios converted to
    ability power ratios, scaling with 0.6% AP per 1% total AD, and 0.4%
    AP per 1% bonus AD" — has no channel either: nothing in the kernel
    re-writes a foreign ability's scaling terms.  Modelling R therefore
    needs a cross-champion ultimate-import kernel, which is a project,
    not a slot.
"""

from dataclasses import replace
from typing import Any

from .. import healing_helpers as _healing
from ..binary_roots import calculation_coefficients, spell_object
from .engine import SlotCtx
from .healing_contract import self_healing_rule
from .inputs import int_option
from .module_contract import coverage
from .packet_module import build_packet_module
from .slotlib import ability_name, extract_named

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
            max(int(ctx.option("passive_procs")), 0),
            _MAX_UNSHACKLED_STACKS,
        )
        total_ad = ctx.stat("attack_damage")
        ability_power = ctx.stat("ability_power")
        modified_total = (
            _PRIMARY_TOTAL_AD_RATIO * total_ad + _PRIMARY_AP_RATIO * ability_power
        )
        entry = dict(entry)
        entry["name"] = name
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
    slot_wrappers={
        "P": _petricite_burst,
        "Q": _chain_lash,
    },
    cc_kinds=MODULE_CC,
)

OPTIONS = [
    *list(OPTIONS),
    int_option(
        "passive_procs",
        0,
        minimum=0,
        maximum=_MAX_UNSHACKLED_STACKS,
        label="Unshackled attacks spent (each replaces one swing)",
        rotation={"role": "self_state", "slot": "P"},
    ),
]

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "P (Petricite Burst) prices the empowered basic attack as a CONVERSION, "
    "not as bonus on-hit damage: each Unshackled stack spent REPLACES one "
    "ordinary physical swing with a single 130% total AD (+ 30% AP) magic "
    "instance (game file SylasPassive PassiveDamage: StatByCoefficient "
    "mStat 2 with no mStatFormula at 1.3 = total AD, plus a 0.3 ability "
    "power coefficient, and exactly those two formula parts). The module "
    "supplies only the non-AD remainder (0.30 total AD + 0.30 AP) through "
    "auto_attack_conversion and the engine's own swing path keeps the AD "
    "term, so nothing is double counted; pricing it as an added magic row "
    "would have invented roughly one whole auto per empowered swing and "
    "mitigated the real swing against armor instead of magic resistance. "
    "The ratios are module constants because every leveling array on the "
    "cached P entry is empty - the numbers exist only in description prose "
    "- so the tests re-derive them from the game file rather than trusting "
    "the constants. Attacks default to 0 (fail-closed): Unshackled stacks "
    "are generated by Sylas' own ability casts over a 4 second refreshing "
    "window the fight engine does not simulate, so the count is user-set "
    "caster state, capped at the sourced 3 stacks.",
    "P withholds four sourced riders rather than approximating them: the "
    "secondary-target whirl (40% AD + 20% AP) needs nearby enemies the 1v1 "
    "damage surface does not have; the nonstandard critical strike (the "
    "wiki records Petricite Burst critting for 175% + 30% rather than the "
    "standard 200% + 30%) has no channel, since DamagePart.crit_"
    "effectiveness scales crit PROBABILITY and not the multiplier, so the "
    "only available encoding would overstate the crit bonus - "
    "auto_attack_conversion crits the AD component at the standard "
    "multiplier and never crits the converted remainder, which coincides "
    "exactly with the sourced reading at the zero crit chance of an "
    "ordinary Sylas build; the 115% monster multiplier and the "
    "secondary-target minion execute below 25 health cannot bind because "
    "target_class has no monster value and the execute is "
    "secondary-target-only; and the 125% bonus attack speed plus the "
    "uncancellable windup have no derivable uptime from a static build and "
    "no windup channel.",
    "R (Hijack) stays out_of_scope, NOT no_damage (the Olaf-R rule). This "
    "is not a slot whose damage is zero, it is a slot whose damage is "
    "ANOTHER CHAMPION'S ULTIMATE: the binary SylasR record carries one "
    "calculation, PerTargetCooldown, and no damage formula, because the "
    "damage arrives entirely through the recast that casts the hijacked "
    "ultimate at no cost, scaling on Hijack's rank and Sylas' own stats. "
    "The blocker is a named kernel gap, not an evidence gap: every "
    "attacker resolves to exactly one validated champion contract and "
    "unknown names fail closed, so no surface exists on which one "
    "champion's parse can instantiate another champion's R at a rank of "
    "its own, and the sourced conversion rule that would make such an "
    "import correct (abilities that do not scale with ability power have "
    "their attack damage ratios converted at 0.6% AP per 1% total AD and "
    "0.4% AP per 1% bonus AD) has no channel either - nothing in the "
    "kernel rewrites a foreign ability's scaling terms. Modelling R needs "
    "a cross-champion ultimate-import kernel, which is a project rather "
    "than a slot.",
]
MODULE_COVERAGE = coverage(out_of_scope="R")


# pylint: disable=too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument
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
    w = _healing.ability_json(champion_data, "W")
    w_rank = _healing.parsed_rank(ability_damages, "W")
    min_heal = extract_named(w, "Minimum Heal", w_rank, champion_stats)
    max_heal = extract_named(w, "Maximum Heal", w_rank, champion_stats)
    for payment in _healing.payments(
        _healing.HealAnchor.CAST, "W", damage_events, cast_timeline
    ):
        event = payment.event
        if float(event.get("damage", 0.0)) <= 0.0:
            continue
        healing.append(
            {
                "time": float(event.get("time", 0.0)),
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
    "E (Abscond/Abduct) carries no shield in the current kit: the CP-era "
    "SylasEShield atom (80/115/150/185/220 + 100% AP for 2s) was removed "
    "in V10.2 (wiki patch history: 'Abscond Removed: ... No longer "
    "shields ... for 2 seconds upon dashing'); the pinned cached data "
    "has no shield row on either E entry, so the E magic-damage packet "
    "is complete",
]
