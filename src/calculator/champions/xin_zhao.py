"""Xin Zhao — CP10.10 full-entry-reviewed packet module.

Row-selection fix.  The generated packet picked, for both Q and W, a
single-instance row where the cached entry also carries the Total the
wiki computes for one cast, so this module reads the Total instead:

- Q (Three Talon Strike) "empowers his next three basic attacks ... to
  each have an uncancellable windup, deal bonus physical damage".  The
  packet priced "Bonus Physical Damage" (15/30/45/60/75 + 40% bonus AD),
  one of the three; the cache's "Total Bonus Physical Damage" row is
  45/90/135/180/225 + 120% bonus AD — exactly three of them.
- W (Wind Becomes Lightning) "unleashes 4 slashes ... each dealing
  physical damage ... he then thrusts his spear in a line ... dealing
  physical damage".  The packet priced "Physical Damage per Slash"
  (7.5/10/12.5/15/17.5 + 7.5% AD), one slash of four and no thrust; the
  cache's "Total Physical Damage" row is 80/125/170/215/260 + 120% AD
  + 65% AP == "Slash Total Physical Damage" + "Thrust Physical Damage".

Each row is now several hits, so neither certifies a cast-boundary single
hit.  W declares its one aggregate hit at the cast so its reviewed slow
still reaches the event ledger; the slashes' sourced cadence ("over the
first 0.15 seconds of the cast time") and the thrust's offset behind the
remaining cast time are left for the timing wave.

Both rows carry a sourced crit clause, and they are different axes — see
``_Q_CRIT_EFFECTIVENESS`` and ``_W_THRUST_CRIT_CHANCE_AMP``.

Coverage-frontier rider: P (Determination) is the every-third-attack
bonus — "Xin Zhao's basic attacks on-hit ... generate a stack of
Determination, stacking up to 3 times.  The third stack consumes them
all to deal 15% / 30% / 45% / 60% (based on level) AD (+ 5% / 10% / 15%
/ 20% (based on level) AP) bonus physical damage and heal Xin Zhao for
2% / 3.5% / 5% (based on level) of his maximum health (+ 40% / 50% / 70%
(based on level) AP)."  The cached P entry carries no leveling row at
all, so the bands are module constants.  W's first slash hit and thrust
each generate a stack too; the kit-wide ability-hit counter would count E
and R as well, so the row names its stack source per slot instead
(``ability_stack_slots``: ``{"W": 2}``).  The heal is paid by the Xin Zhao
healing rule off the same on-hit events.
"""

from typing import Any

from ..ability_atoms import ability_field, ability_payload
from .. import healing_helpers as _healing
from ..ability_spec import DamagePart
from ..binary_roots import data_value, spell_object
from .inputs import champion_stat
from .engine import ONHIT, SlotCtx
from .healing_contract import self_healing_rule
from .packet_module import build_packet_module
from .slotlib import (
    ability_name,
    ability_on_hit_entry,
    damage_entry,
    extract_cooldown,
    extract_named,
    simple_damage,
)

PACKET_SHA256 = "c39efd0eac006d4b59799a0b3c5de44ef6ec31f9f9a23bea7ab8a25d2f4ccf64"

# HARDCODED: verify on patch updates — the cached Determination entry
# has no leveling rows; every number is wiki prose, and the level
# breakpoints come from Template:Data Xin Zhao/Determination
# ("15 to 60 for 4|1 to 16" and "5 to 20 for 4|1;6;11;16" — levels
# 1/6/11/16 for both damage terms).  The heal's bands live in the
# healing rule that pays it (this module's ``derive_self_healing``).
DETERMINATION_STACKS = 3
# "Xin Zhao's basic attacks on-hit AND Wind Becomes Lightning's first
# slash hit and thrust ... each generate a stack of Determination"
# (cached P effect 0).  W's row is one aggregate hit at the cast, so that
# hit carries both stacks; no other slot feeds the counter, which is why
# this is a per-slot source and not the kit-wide ``count_ability_hits``
# (E and R would count too, and they generate none).
W_DETERMINATION_STACKS = {"W": 2}
_DAMAGE_BANDS: tuple[tuple[int, float, float], ...] = (
    (16, 0.60, 0.20),
    (11, 0.45, 0.15),
    (6, 0.30, 0.10),
    (1, 0.15, 0.05),
)


def _determination_ratios(level: int) -> tuple[float, float]:
    """The third-stack AD and AP ratios at a champion level."""
    for min_level, ad_ratio, ap_ratio in _DAMAGE_BANDS:
        if level >= min_level:
            return ad_ratio, ap_ratio
    return _DAMAGE_BANDS[-1][1], _DAMAGE_BANDS[-1][2]


def _determination(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: the third-stack bonus, as a per-attack share of the proc."""
    ability = ctx.ability()
    if ability is None:
        return None
    ad_ratio, ap_ratio = _determination_ratios(ctx.level)
    per_proc = ad_ratio * ctx.stat("attack_damage") + ap_ratio * ctx.stat(
        "ability_power"
    )
    if per_proc <= 0:
        return None

    name = ability_name(ability)
    entry = ability_on_hit_entry(
        name,
        ctx.level,
        "physical",
        {
            "name": name,
            # The engine multiplies the per-hit share by every attack and
            # displays procs, so partial stacks are priced smoothly (the
            # Vayne W / Aurora P shape).
            "damage_per_hit": per_proc / DETERMINATION_STACKS,
            "damage_type": "physical",
            "stacks_required": DETERMINATION_STACKS,
            "ability_stack_slots": W_DETERMINATION_STACKS,
        },
    )
    entry["detail"] = (
        f"every {DETERMINATION_STACKS}rd basic attack consumes the stacks "
        f"for {per_proc:.2f} bonus physical damage ({ad_ratio:.0%} AD + "
        f"{ap_ratio:.0%} AP at level {ctx.level}) and the sourced "
        "maximum-health heal; Wind Becomes Lightning's first slash and "
        "thrust each feed the counter one stack"
    )
    return entry


_determination.phase = ONHIT


# Q's bonus damage "is affected by critical strike modifiers" (cached Q
# effect 2), which is the crit-PROBABILITY axis ``crit_effectiveness``
# names: the row crits at the fight's own chance and multiplier.
_Q_CRIT_EFFECTIVENESS = 1.0

# W's thrust: "dealing physical damage to enemies hit, increased by
# 0% : 33.3% (based on critical strike chance)"; the binary CritChanceAmp
# DataValue carries the endpoint.  A deterministic
# amplifier, not a crit roll — it reaches +33.3% whatever the crit
# multiplier is, so ``crit_effectiveness`` (which routes through
# ``state.crit_multiplier``) would misprice an Infinity Edge build.  The
# repo's key for this axis is the parser-level linear scale between the
# sourced endpoints (Nilah Q, Smolder Q, Zeri E), on the thrust term
# alone: the four slashes take no amplifier.
_XIN_ZHAO_W_SPELL = spell_object("Xin Zhao", "XinZhaoW")
_W_THRUST_CRIT_CHANCE_AMP = data_value(_XIN_ZHAO_W_SPELL, "CritChanceAmp")


def _wind_becomes_lightning(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: the whole cast — four slashes plus the crit-scaled thrust."""
    ability = ctx.ability("W")
    if ability is None:
        return None
    rank = ctx.rank_for("W")
    if rank < 1:
        return None
    total = extract_named(ability, "Total Physical Damage", rank, ctx.stats, ctx.target)
    thrust = extract_named(
        ability, "Thrust Physical Damage", rank, ctx.stats, ctx.target
    )
    crit_chance = min(
        1.0, max(0.0, float(ctx.stat("critical_strike_chance") or 0.0) / 100.0)
    )
    amplified = thrust * _W_THRUST_CRIT_CHANCE_AMP * crit_chance
    total += amplified
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        total,
        "physical",
    )
    entry["parts"] = (DamagePart("physical", total, time_offset=0.0),)
    entry["detail"] = (
        "four slashes plus the thrust as one hit at the cast; the thrust's "
        f"sourced 0% : {_W_THRUST_CRIT_CHANCE_AMP:.1%} crit-chance amplifier "
        f"adds {amplified:.2f} at {crit_chance:.0%} crit chance"
    )
    return entry


# Wind Becomes Lightning ends in a thrust "dealing physical damage to
# enemies hit ... and slowing them by 50%" — the cast slows the target it
# damages, and now that W prices the whole cast (four slashes plus that
# thrust) the reviewed kind covers every hit the row contains.  Audacious
# Charge "slow[s] all targets hit by 30% for 0.5 seconds".  Crescent
# Guard's knockback and stun reach only "targets hit that are not
# Challenged", and its own passive marks the duel target — "Xin Zhao's
# basic attacks and Audacious Charge apply the Challenged mark to enemy
# champions hit" — so the one enemy this module prices is never displaced
# by it.
#
# Q stays UNREVIEWED, so this kit keeps the coarse control-armed scan.
# Its row is now all three empowered attacks, but only "the third attack
# knocks up the target" — one of three, and no slot-wide answer covers a
# row whose hits differ (the Annie Pyromania rule).
MODULE_CC = {"W": "slow", "E": "slow", "R": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Xin Zhao",
    PACKET_SHA256,
    # E's arrival and R's sweep are one hit each at the cast.  W is no
    # longer among them: its row is four slashes plus a thrust, declared
    # at the cast boundary by ``_wind_becomes_lightning``.
    single_hit_slots=frozenset({"E", "R"}),
    slot_parsers={
        "P": _determination,
        "Q": simple_damage(
            attr="Total Bonus Physical Damage",
            dmg_type="physical",
            crit_effectiveness=_Q_CRIT_EFFECTIVENESS,
        ),
        "W": _wind_becomes_lightning,
    },
    assumption_overrides=(
        "Q (Three Talon Strike) prices all three empowered attacks — the "
        "cached Total Bonus Physical Damage row (45/90/135/180/225 + 120% "
        "bonus AD), three times the per-attack Bonus Physical Damage row "
        "the generated packet selected.  Their spacing across the "
        "5-second window is not authored.  The row declares "
        "crit_effectiveness=1.0 — 'Three Talon Strike's bonus damage is "
        "affected by critical strike modifiers' (cached Q effect 2) — so "
        "it crits at the fight's own chance and multiplier.",
        "W (Wind Becomes Lightning) prices the whole cast — the cached "
        "Total Physical Damage row (80/125/170/215/260 + 120% AD + 65% "
        "AP), which is the four slashes plus the thrust.  The generated "
        "packet priced Physical Damage per Slash, one slash of four with "
        "no thrust.  The row is declared as one aggregate hit at the cast "
        "boundary; the slash cadence remains unpriced.",
        "W's thrust is 'increased by 0% : 33.3% (based on critical strike "
        "chance)' (cached W effect 0) — a deterministic amplifier, not a "
        "crit roll, so it is NOT crit_effectiveness (that key would route "
        "through the crit multiplier and misprice an Infinity Edge "
        "build).  The module scales the cached Thrust Physical Damage row "
        "alone by 1 + 0.333 x crit chance, exact at both sourced "
        "endpoints and linear between them (the Nilah Q / Smolder Q / "
        "Zeri E precedent); the four slashes take no amplifier.",
        "P (Determination) prices the third-stack bonus at the wiki's "
        "15% / 30% / 45% / 60% (based on level) AD + 5% / 10% / 15% / "
        "20% AP (level breakpoints 1/6/11/16) — module constants, "
        "because the cached P entry carries no leveling row.  Stacks "
        "come from basic attacks and from Wind Becomes Lightning's "
        "first slash hit and thrust, one each — declared per slot "
        "(ability_stack_slots {'W': 2}) rather than through the "
        "kit-wide ability-hit counter, which would also count E and R, "
        "and they generate none.  The Challenged mark is state.",
    ),
    cc_kinds=MODULE_CC,
)


# HARDCODED: verify on patch updates — Determination's heal is cached
# PROSE, not a leveling row: the third stack "heal[s] Xin Zhao for
# 2% / 3.5% / 5% (based on level) of his maximum health (+ 40% / 50% /
# 70% (based on level) AP)".  The level breakpoints 1/6/11 are the wiki
# template's.
_HEAL_BANDS: tuple[tuple[int, float, float], ...] = (
    (11, 0.05, 0.70),
    (6, 0.035, 0.50),
    (1, 0.02, 0.40),
)


def _determination_heal_ratios(level: int) -> tuple[float, float]:
    """The third-stack maximum-health and AP heal ratios at a level."""
    for min_level, health_share, ap_ratio in _HEAL_BANDS:
        if level >= min_level:
            return health_share, ap_ratio
    return _HEAL_BANDS[-1][1], _HEAL_BANDS[-1][2]


# pylint: disable=too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Resolve Xin Zhao self-healing events from its authored packet."""
    healing = []
    lifesteal = champion_stat(champion_stats, "lifesteal_percent")
    if lifesteal > 0.0:
        for event in _healing.attributed_events(
            damage_events, lambda source, _event: source == "W"
        ):
            amount = (
                0.333 * max(0.0, float(event.get("damage", 0.0))) * lifesteal / 100.0
            )
            _healing.heal_from_damage(healing, event, amount, "Wind Becomes Lightning")
    # Determination (P): the third stack "consume[s] them all to deal ...
    # bonus physical damage and heal Xin Zhao for 2% / 3.5% / 5% (based on
    # level) of his maximum health (+ 40% / 50% / 70% (based on level) AP)".
    # ``_determination`` prices the proc as a per-attack share (partial
    # stacks included), so the heal pays the same share on the same on-hit
    # events — three of them are one proc's heal.
    determination = ability_field(ability_payload(ability_damages, "passive"), "on_hit")
    if determination:
        xin_level = max(1, int(champion_stat(champion_stats, "level")))
        health_share, heal_ap_ratio = _determination_heal_ratios(xin_level)
        per_proc_heal = health_share * float(
            champion_stat(champion_stats, "health")
        ) + heal_ap_ratio * champion_stat(champion_stats, "ability_power")
        # The module declares the cadence; dividing by it here is what keeps
        # the heal and the damage on one grouping.
        stacks = max(1, int(determination.get("stacks_required") or 1))
        for event in _healing.attributed_events(
            damage_events, lambda source, _event: source == "on_hit_ability_passive"
        ):
            _healing.heal_from_damage(
                healing, event, per_proc_heal / stacks, "Determination"
            )
    return healing


SELF_HEALING_RULE = self_healing_rule("Xin Zhao")(derive_self_healing)
