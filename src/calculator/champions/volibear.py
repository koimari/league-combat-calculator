"""Volibear — reviewed packet slots plus the E3 stack mechanics.

E3 additions over the CP10.9 packet module:
- P (The Relentless Storm) becomes a BUFF-phase stack slot: each of up
  to 5 stacks grants 5% (+ 3% per 100 AP) bonus attack speed (25% + 15%
  per 100 AP fully stacked), and at 5 stacks basic attacks gain
  Lightning Claws on-hit bonus magic damage (level-scaled flat + 45%
  AP). The stack count is a user option (``relentless_storm_stacks``,
  default 5 = the sustained-fight state) — the model cannot simulate
  which specific damage events re-stack the 6-second window, so the
  pre-stacked count is priced instead, matching the module convention
  for stack passives (Ezreal P, Darius P).
- W (Frenzied Maul) prices the Wounded 2nd bite: the first cast marks
  the target Wounded for 8 seconds and the next cast on the same
  target deals 50% (+ 25% per 100 bonus AD) increased damage. The
  ``w_wounded`` option (default True) selects the already-marked bite —
  the one-rotation model casts W once, so this is the sourced
  empowered cast rather than a simulated apply-then-recast sequence.
"""

from typing import Any

from .. import healing_helpers as _healing
from ..ability_spec import DamagePart
from ..binary_roots import calculation_coefficient, data_value, spell_object
from .engine import BUFF, SlotCtx
from .healing_contract import self_healing_rule
from .inputs import bool_option, int_option
from .module_helpers import ranked_slot
from .packet_module import build_packet_module
from .slotlib import (
    ability_name,
    attach_self_shield,
    damage_entry,
    extract_cooldown,
    extract_named,
)

PACKET_SHA256 = "29b4dc9dac0b65fb99cbe14df3e85aebbb307f341cae112415f1b9504c9f3cce"

# Stormbringer's damage is its landing: "Volibear impacts after 1 second,
# slowing nearby enemies by 50% decaying over 1 second. Enemies within the
# epicenter are also dealt physical damage" (data/champions.json Volibear
# R), and he "leaps to the target location ... over 1 second" regardless of
# distance, so the offset is a constant, not a travel estimate.
_R_IMPACT_SECONDS = 1.0

# Frenzied Maul's strike is its cast time: the cached note says "Frenzied
# Maul deals bonus damage and heals if the target is still Wounded after
# the cast time.  If the mark wears off before the cast time completes, the
# ability's animation will appear as if the bite was applied but there is
# no bonus damage or heal" (data/champions.json Volibear W), and that cast
# time is the cached ``castTime`` of 0.25 seconds.  Both halves of the bite
# — the base slash and the Wounded surplus — are the one strike, so both
# land on that instant.
_W_BITE_SECONDS = 0.25


_VOLIBEAR_P_SPELL = spell_object("Volibear", "VolibearP")
# PAttackSpeed is a fractional per-stack grant; AttackSpeedCalc's coefficient
# is fractional per AP. Convert both into the module's percentage units.
_RELENTLESS_STORM_MAX_STACKS = int(data_value(_VOLIBEAR_P_SPELL, "BounceCounterMax"))
_STORM_AS_PER_STACK = data_value(_VOLIBEAR_P_SPELL, "PAttackSpeed") * 100.0
_STORM_AS_PER_100_AP = (
    calculation_coefficient(_VOLIBEAR_P_SPELL, "AttackSpeedCalc") * 10000.0
)
_VOLIBEAR_W_SPELL = spell_object("Volibear", "VolibearW")
# W2DamageMultiplier is a total multiplier; the module stores its additive
# bonus. W2BonusADDamageMultiplier is per bonus-AD point; convert it to the
# module's documented per-100-bonus-AD unit.
_WOUNDED_BONUS_BASE = data_value(_VOLIBEAR_W_SPELL, "W2DamageMultiplier") - 1.0
_WOUNDED_BONUS_PER_100_BONUS_AD = (
    data_value(_VOLIBEAR_W_SPELL, "W2BonusADDamageMultiplier") * 100.0
)
# Sky Splitter's self shield is the binary VolibearE DataValue trio
# (ShieldAmount 0.14 / ShieldAPRatio 0.75 / ShieldDuration 3.0); the
# cached description ("a shield equal to 14% of his maximum health
# (+ 75% AP) for 3 seconds") corroborates it.
_VOLIBEAR_E_SPELL = spell_object("Volibear", "VolibearE")
_SKY_SPLITTER_SHIELD_MAX_HP_RATIO = data_value(_VOLIBEAR_E_SPELL, "ShieldAmount")
_SKY_SPLITTER_SHIELD_AP_RATIO = data_value(_VOLIBEAR_E_SPELL, "ShieldAPRatio")
_SKY_SPLITTER_SHIELD_DURATION_SECONDS = data_value(_VOLIBEAR_E_SPELL, "ShieldDuration")


def _relentless_storm(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: per-stack bonus AS; at 5 stacks, Lightning Claws on-hit magic.

    BUFF phase: the bonus attack speed is published as a ``stat_buff``
    the fight engine applies before autos are counted, and the
    Lightning Claws on-hit rides the same entry so a fully-stacked
    Volibear's basic attacks carry the sourced magic damage.
    """
    ability = ctx.ability()
    if ability is None:
        return None

    stacks = int(
        ctx.options.get("relentless_storm_stacks", _RELENTLESS_STORM_MAX_STACKS)
    )
    stacks = min(max(stacks, 0), _RELENTLESS_STORM_MAX_STACKS)
    ap = ctx.stat("ability_power")
    per_stack = _STORM_AS_PER_STACK + _STORM_AS_PER_100_AP * ap / 100.0
    bonus_as = stacks * per_stack

    entry: dict[str, Any] = {
        "name": ability_name(ability),
        "rank": ctx.level,
        "damage_type": "magic",
        "total_raw": 0.0,
        "parts": (),
        "stat_buff": {"bonus_attack_speed": bonus_as},
        "detail": (
            f"{stacks}/{_RELENTLESS_STORM_MAX_STACKS} stack(s); "
            f"{bonus_as:g}% bonus attack speed ({per_stack:g}% per stack)"
        ),
    }

    if stacks >= _RELENTLESS_STORM_MAX_STACKS:
        per_hit = extract_named(
            ability, "Bonus Magic Damage", ctx.level, ctx.stats, ctx.target
        )
        if per_hit > 0:
            entry["on_hit"] = {
                "name": "Lightning Claws (on-hit)",
                "damage_per_hit": per_hit,
                "damage_type": "magic",
            }
    return entry


_relentless_storm.phase = BUFF


@ranked_slot
def _frenzied_maul(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """W: base physical damage; the Wounded 2nd bite adds the sourced
    increased-damage part (50% + 25% per 100 bonus AD of the base)."""

    base = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    cooldown = extract_cooldown(ability, rank)
    name = ability_name(ability)

    if not ctx.option("w_wounded"):
        entry = damage_entry(name, rank, cooldown, base, "physical")
        entry["parts"] = (DamagePart("physical", base, time_offset=_W_BITE_SECONDS),)
        return entry

    bonus_ad = ctx.stat("bonus_attack_damage")
    extra_ratio = (
        _WOUNDED_BONUS_BASE + _WOUNDED_BONUS_PER_100_BONUS_AD * bonus_ad / 100.0
    )
    extra = base * extra_ratio
    entry = damage_entry(name, rank, cooldown, base + extra, "physical")
    entry["parts"] = (
        DamagePart("physical", base, time_offset=_W_BITE_SECONDS),
        DamagePart("physical", extra, time_offset=_W_BITE_SECONDS),
    )
    entry["detail"] = (
        f"Wounded 2nd bite: +{extra_ratio * 100:g}% increased damage "
        f"(+{extra:g} over the {base:g} base)"
    )
    return entry


def _sky_splitter(packet_e):
    """E: the reviewed magic hit plus the sourced self-shield payload.

    The 14% max HP + 75% AP shield (cached description prose) rides the
    E damage event; the shared ledger grants it as a timed 3-second
    self-shield at the cast.
    """

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        entry = packet_e(ctx)
        rank = int(entry.get("rank", 0) or 0) if entry is not None else 0
        if entry is None or rank < 1:
            return entry
        shield = _SKY_SPLITTER_SHIELD_MAX_HP_RATIO * ctx.stat(
            "health"
        ) + _SKY_SPLITTER_SHIELD_AP_RATIO * ctx.stat("ability_power")
        return attach_self_shield(
            entry,
            amount=shield,
            duration=_SKY_SPLITTER_SHIELD_DURATION_SECONDS,
            source=entry.get("name", "Sky Splitter"),
            detail=(
                f"E also shields Volibear for {shield:g} for "
                f"{_SKY_SPLITTER_SHIELD_DURATION_SECONDS:g}s "
                f"(14% max HP + 75% AP)"
            ),
        )

    return parse


# Thundering Smash's empowered attack pounces "dealing bonus physical
# damage and stunning them for 1 second"; Sky Splitter's bolt "deals magic
# damage to enemies hit ... and slows them by 40% for 2 seconds".  P is the
# stack buff plus its Lightning Claws on-hit rider — a basic-attack row,
# not an ability event.
#
# Stormbringer's landing "slow[s] nearby enemies by 50% decaying over 1
# second" on the same impact that deals its damage, now authored at that
# impact.
#
# Frenzied Maul "slashes the target enemy with his claws to deal physical
# damage, apply on-hit effects, trigger on-attack effects, and mark the
# target Wounded", and the Wounded bite only deals "increased damage and
# heal[s] himself" — a mark and a heal, no control.  Both halves of the
# bite now land on the cached cast time, so that review reaches the event
# ledger; the self-heal rule pays per bite rather than per part
# (``HealAnchor.CAST``), so the second half is not a second heal.
MODULE_CC = {"Q": "stun", "W": "none", "E": "slow", "R": "slow"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Volibear",
    PACKET_SHA256,
    # Q's empowered attack is one pounce on one target; E is one bolt.
    single_hit_slots=frozenset({"Q", "E"}),
    packet_part_timings={"R": {"time_offset": _R_IMPACT_SECONDS}},
    slot_parsers={
        "P": _relentless_storm,
        "W": _frenzied_maul,
    },
    slot_wrappers={
        "E": _sky_splitter,
    },
    cc_kinds=MODULE_CC,
)

OPTIONS = [
    *list(OPTIONS),
    int_option(
        "relentless_storm_stacks",
        _RELENTLESS_STORM_MAX_STACKS,
        minimum=0,
        maximum=_RELENTLESS_STORM_MAX_STACKS,
        label="The Relentless Storm stacks",
    ),
    bool_option("w_wounded", True, label="W hits an already-Wounded target (2nd bite)"),
]

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "The Relentless Storm stack count is user-set (default 5 = fully "
    "stacked); the 6-second stack window and which damage events refresh "
    "it are not simulated",
    "Each stack grants 5% (+ 3% per 100 AP) bonus attack speed — wiki "
    "prose (module constant)",
    "Lightning Claws on-hit magic damage applies to every basic attack "
    "while at 5 stacks; the 450-range secondary-target chain is not "
    "modeled (single-target calc)",
    "Frenzied Maul's Wounded 2nd bite deals 50% (+ 25% per 100 bonus AD) "
    "increased damage — binary-rooted W2 values, corroborated by cached "
    "prose; the option picks "
    "the already-marked bite because the one-rotation model casts W once",
    "E (Sky Splitter) also shields Volibear for 14% max HP + 75% AP for "
    "3s at the cast (cached description prose, module constants); the "
    "shield absorbs incoming damage in the participant ledger",
    "Q's stun/MS, W's heal and R's bonus health remain utility/state " "only",
]


# pylint: disable=too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Resolve Volibear self-healing events from its authored packet."""
    healing = []
    w = _healing.ability_json(champion_data, "W")
    w_rank = _healing.parsed_rank(ability_damages, "W")
    w_flat = extract_named(w, "Heal", w_rank, champion_stats, {})
    w_missing_pct = _healing.leveling_modifier(w, "Heal", w_rank, 1)

    frenzied_maul_heal = _healing.flat_plus_missing_heal(w_flat, w_missing_pct)
    # One bite, one heal: the cached note is "Frenzied Maul deals bonus
    # damage and heals if the target is still Wounded after the cast time",
    # so the payment is the cast, not the parts this module prices that bite
    # with (base slash + Wounded surplus).  The first W applies the Wound;
    # the heal lands on every later W.
    for index, payment in enumerate(
        _healing.payments(_healing.HealAnchor.CAST, "W", damage_events, cast_timeline)
    ):
        if index < 1:
            continue
        healing.append(
            {
                "time": float(payment.event.get("time", 0.0)),
                "amount": 0.0,
                "amount_formula": frenzied_maul_heal,
                "source": "Frenzied Maul",
                "kind": "champion_ability",
                **_healing.trigger_fields(payment.event),
            }
        )
    return healing


SELF_HEALING_RULE = self_healing_rule("Volibear")(derive_self_healing)
