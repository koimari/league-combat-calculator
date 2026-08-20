"""Darius — slot map for the archetype engine.

Why each slot is non-generic:
- P (Hemorrhage) is a hit-driven stacking bleed plus the steroid it
  triggers. Every damaging basic attack AND damaging ability applies one
  stack for 5s (max 5, refreshing); unlike Briar's, every stack ticks at
  FULL rate. Landing the 5th stack on a champion grants Noxian Might —
  bonus AD for 5s, refreshing while the target is held at max. Both ride
  the fight engine's shared stack timeline (damage.py Case 4 and 5), so
  "when does a stack land" has exactly one home. The JSON parse is
  degraded in two ways the generic path cannot survive: all four bleed
  arrays share attribute ``"Per-Level Scaling"`` (indexed positionally
  below) and every bonus-AD ratio in the passive lives only in the
  description prose (hardcoded below).
- Q (Decimate) reads the outer BLADE attribute — the inner handle is a
  misplay and is not modeled — applies a bleed stack, and overrides its
  cast time: the JSON says ``"none"`` but Decimate hefts the axe for
  0.75s, during which Darius cannot attack or cast (the Cassiopeia
  cast-time rule).
- W (Crippling Strike) empowers the NEXT basic attack once per cast (the
  Alistar rule) and its bonus crits at FULL effectiveness alongside the
  base swing.
- E (Apprehend) deals ZERO damage — so it applies NO bleed stack, a real
  mechanic rather than an oversight. Its always-on armor-penetration
  passive is the whole point, emitted as a BUFF-phase ``stat_buff`` (the
  Ambessa R precedent) so every physical slot is priced after it.
- R (Noxian Guillotine) is TRUE damage that grows with the Hemorrhage
  stacks ON THE TARGET when it lands. The JSON's "Maximum True Damage"
  is a trap for the primary-damage classifier — it is only correct at 5
  stacks — so R is built as base + one per-stack instance, with the
  stack count derived from the fight timeline (or forced by option).
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import BUFF, SlotCtx, build_parser
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    stat_buff,
    sum_modifiers,
)

# HARDCODED: verify on patch updates — the passive's bonus-AD ratios
# exist ONLY in the description prose; its modifier ``units`` are all
# empty strings, so nothing in the JSON carries them. The per-level
# VALUE arrays below ARE in the JSON and are read from it.
# https://wiki.leagueoflegends.com/en-us/Darius
P_BLEED_BONUS_AD_RATIO = 0.30  # per stack, over the full 5s
P_BLEED_DURATION = 5.0  # seconds per (refreshing) stack window
# The bleed ticks every 1.25s — the JSON's own per-tick arrays are exactly
# quarters of the 5s totals (test-locked in test_darius.py), so the cadence
# is sourced; the engine authors bleed tick events from it.
P_BLEED_TICK_INTERVAL = 1.25
P_BLEED_MAX_STACKS = 5
P_BLEED_EXTRA_STACK_EFFECTIVENESS = 1.0  # every stack ticks at full rate
NOXIAN_MIGHT_DURATION = 5.0
NOXIAN_MIGHT_TRIGGER_STACKS = 5

# HARDCODED cast lockouts: the wiki's ``castTime`` field understates how
# long these casts occupy Darius' hands, and a too-short cast lets an
# ability both overcount its own throughput and avoid displacing others
# on the shared timed-mode timeline (the Cassiopeia cast-time bug).
Q_CAST_TIME = 0.75  # JSON says "none"; Decimate winds up for 0.75s
E_CAST_TIME = 0.65  # 0.25 cast + 0.4 pull
R_CAST_TIME = 0.6167  # 0.3667 cast + 0.25 recovery

# The passive's four bleed arrays ALL share attribute="Per-Level
# Scaling", so ``extract_named`` cannot tell them apart — index them
# positionally instead. effects[1].leveling[], values at level 18 / 20:
#   [0] one stack over 5s .......... 30 / 32   <- the only one we read
#   [1] one stack per 1.25s tick ... 7.5 / 8   ([0] / 4)
#   [2] five stacks over 5s ........ 150 / 160 ([0] x 5)
#   [3] five stacks per tick ....... 37.5 / 40 ([2] / 4)
# (tests/test_darius.py asserts those relationships still hold.)
_P_BLEED_EFFECT = 1
_P_PER_STACK_TOTAL = 0
_P_MIGHT_EFFECT = 3
_P_MIGHT_BONUS_AD = 0  # 230 / 280 — non-linear, read by level index


def _per_level(
    ability: dict[str, Any],
    effect_index: int,
    leveling_index: int,
    level: int,
) -> float:
    """One positionally-addressed per-level array's value at *level*.

    The passive's arrays are 40 entries long and indistinguishable by
    attribute name. Noxian Might's ramp is deliberately non-linear
    (+5/level to 10, +10 to 13, then +25), so the value is READ at the
    level index — never interpolated between the wiki's endpoints.
    """
    effects = ability.get("effects", [])
    if effect_index >= len(effects):
        return 0.0
    leveling = effects[effect_index].get("leveling", [])
    if leveling_index >= len(leveling):
        return 0.0
    return sum_modifiers(leveling[leveling_index], level)


def _ad_ratio(
    ability: dict[str, Any],
    attribute: str,
    rank: int,
    modifier_index: int = 1,
) -> float:
    """An attribute's AD-scaling modifier at *rank*, as a 0..n fraction.

    The engine needs each part's derivative in bonus AD so Noxian Might
    can re-price it mid-fight. Reading the ratio from the SAME JSON
    modifier that produced the damage keeps the two in step on patch
    updates (a total-AD scaling has the same derivative in bonus AD).
    Modifier 1 is the AD term wherever a flat base precedes it; W's only
    modifier IS the AD term, so it passes ``modifier_index=0``.
    """
    return extract_value(ability, attribute, rank, modifier_index) / 100.0


def _starting_stacks(ctx: SlotCtx) -> int:
    """Hemorrhage stacks already on the target when the fight opens.

    One number for the whole fight state. Because reaching 5 stacks IS
    what grants Noxian Might, seeding the timeline is the only way R's
    stack count, the bleed's rate and the steroid can agree: asking for
    5 stacks without the buff describes a state the game cannot reach.
    """
    stacks = int(ctx.option("starting_hemorrhage_stacks"))
    return min(max(stacks, 0), P_BLEED_MAX_STACKS)


def _hemorrhage(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: the stacking bleed and the Noxian Might window it triggers.

    One stack = 13-32 by level (+30% bonus AD) physical over 5s, four
    ticks of a quarter each. The fight engine walks the hit timeline and
    owns the stack/tick accounting; reaching 5 stacks opens a 5s
    +30-280 bonus AD window that re-prices casts, autos and the bleed
    itself.
    """
    ability = ctx.ability()
    if ability is None:
        return None

    bonus_ad = ctx.stat("bonus_attack_damage")
    single_stack = (
        _per_level(ability, _P_BLEED_EFFECT, _P_PER_STACK_TOTAL, ctx.level)
        + P_BLEED_BONUS_AD_RATIO * bonus_ad
    )
    name = ability.get("name", "Hemorrhage")
    return {
        "name": name,
        "damage_type": "physical",
        "total_raw": single_stack,
        "parts": (),
        # Item burns (Liandry's, Blackfire) stay refreshed through the
        # bleed's tail, not just to the last cast (the Cassiopeia rule).
        "dot_duration": P_BLEED_DURATION,
        "stacking_dot": {
            "name": f"{name} (bleed)",
            "damage_type": "physical",
            "single_stack_raw": single_stack,
            "single_stack_bonus_ad_ratio": P_BLEED_BONUS_AD_RATIO,
            "duration": P_BLEED_DURATION,
            "tick_interval": P_BLEED_TICK_INTERVAL,
            "max_stacks": P_BLEED_MAX_STACKS,
            "extra_stack_effectiveness": P_BLEED_EXTRA_STACK_EFFECTIVENESS,
            "applied_by_autos": True,
            "starting_stacks": _starting_stacks(ctx),
        },
        "stack_triggered_buff": {
            "name": "Noxian Might",
            "trigger_stacks": NOXIAN_MIGHT_TRIGGER_STACKS,
            "duration": NOXIAN_MIGHT_DURATION,
            "bonus_attack_damage": _per_level(
                ability, _P_MIGHT_EFFECT, _P_MIGHT_BONUS_AD, ctx.level
            ),
        },
    }


def _decimate(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: the outer blade's physical damage; applies a bleed stack."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    attribute = "Physical Damage (Blade)"
    total = extract_named(ability, attribute, rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Decimate"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "physical",
    )
    entry["parts"] = (
        DamagePart(
            "physical", total, bonus_ad_ratio=_ad_ratio(ability, attribute, rank)
        ),
    )
    entry["applies_dot_stack"] = True
    entry["cast_time"] = Q_CAST_TIME
    # One swing on one target ("swinging it around himself to deal physical
    # damage to nearby enemies") — the certification that carries the row's
    # reviewed control answer into the event ledger.
    entry["event_order_certified"] = "single_hit"
    return entry


def _crippling_strike(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: bonus physical damage on the next basic attack, crits fully.

    The bonus is 40-60% total AD and the wiki states it is affected by
    critical strike modifiers, so it crits at 100% effectiveness beside
    the base swing. With an auto stream the swing rides it; with none
    (one-rotation, or timed at zero uptime) the engine appends the
    expected-crit base swing to this row — the Blitzcrank/Caitlyn rule.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    attribute = "Bonus Physical Damage"
    bonus = extract_named(ability, attribute, rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Crippling Strike"),
        rank,
        extract_cooldown(ability, rank),
        bonus,
        "physical",
    )
    entry["parts"] = (
        DamagePart(
            "physical",
            bonus,
            crit_effectiveness=1.0,
            bonus_ad_ratio=_ad_ratio(ability, attribute, rank, modifier_index=0),
        ),
    )
    entry["empowers_next_auto"] = True
    entry["applies_dot_stack"] = True
    # "empowers his next basic attack" — one empowered swing per cast, so
    # one part and one hit, which is what carries W's reviewed slow into
    # the event ledger.
    entry["event_order_certified"] = "single_hit"
    return entry


_armor_pen_buff = stat_buff("Armor Penetration", "armor_penetration_percent")


def _apprehend(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: a zero-damage pull whose armor-pen passive is always on.

    Deliberately carries NO ``applies_dot_stack``: Apprehend deals no
    damage, so in-game it applies no Hemorrhage stack.
    """
    entry = _armor_pen_buff(ctx)
    if entry is not None:
        entry["cast_time"] = E_CAST_TIME
    return entry


_apprehend.phase = BUFF


def _noxian_guillotine(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: true damage plus one bonus instance per Hemorrhage stack.

    Damage is "True Damage" + N x "Bonus Damage Per Stack", where N is
    the stacks on the target when R lands — NOT the JSON's "Maximum
    True Damage", which is only correct at N=5. N always comes from the
    fight's stack timeline (the engine resolves ``dot_stack_scaled``),
    which the ``starting_hemorrhage_stacks`` option seeds. R never reads
    that option directly: a stack count R believed but the timeline did
    not would let R hit for 5 stacks while Noxian Might — granted by
    those very stacks — stayed off.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    base = extract_named(ability, "True Damage", rank, ctx.stats, ctx.target)
    per_stack = extract_named(
        ability, "Bonus Damage Per Stack", rank, ctx.stats, ctx.target
    )
    per_stack_ratio = _ad_ratio(ability, "Bonus Damage Per Stack", rank)

    # Parse-level view of the opening state; the engine re-resolves the
    # count against the timeline at R's cast time.
    stacks = _starting_stacks(ctx)

    entry = damage_entry(
        ability.get("name", "Noxian Guillotine"),
        rank,
        extract_cooldown(ability, rank),
        base + per_stack * stacks,
        "true",
    )
    entry["parts"] = (
        DamagePart(
            "true", base, bonus_ad_ratio=_ad_ratio(ability, "True Damage", rank)
        ),
        DamagePart(
            "true",
            per_stack,
            count=stacks,
            bonus_ad_ratio=per_stack_ratio,
            dot_stack_scaled=True,
        ),
    )
    entry["applies_dot_stack"] = True
    entry["cast_time"] = R_CAST_TIME
    return entry


OPTIONS: list[dict[str, Any]] = [
    {
        "key": "starting_hemorrhage_stacks",
        "type": "int",
        "default": 5,
        "min": 0,
        "max": 5,
        "label": (
            "Hemorrhage stacks on the target when the fight opens "
            "(5 = already stacked, so Noxian Might is up)"
        ),
    },
]

ASSUMPTIONS = [
    "Noxian Might is derived from the fight's hit timeline: each auto "
    "and each damaging ability application (Q, W's swing, R) adds a "
    "Hemorrhage stack, and reaching 5 stacks grants +30-280 bonus AD "
    "(by level) for 5s, refreshing while the target is held at 5 "
    "stacks. Casts, autos and bleed ticks inside a window are priced "
    "with the buffed AD",
    "Noxian Might's 'instantly applies 5 stacks' is modeled as the "
    "stack count already being at max when the window opens; Might "
    "triggered by an R execute kill is not modeled (the target never "
    "dies here)",
    "The target starts the fight with 5 Hemorrhage stacks by default, so "
    "Noxian Might is already up when the first cast lands — the state "
    "you are in after stacking a target up, and the only way to reach 5 "
    "stacks in game. Set the option to 0 to model a combo opened on an "
    "unstacked target, where Might never triggers in one-rotation mode "
    "(3 applications: Q, W's swing, R)",
    "R's Hemorrhage stack count always comes from the fight timeline at "
    "its cast time, never from the option directly: the stacks that "
    "scale R are the same ones that grant Noxian Might, so the two can "
    "never disagree",
    "Pre-fight stacks tick during the fight and their bleed is counted, "
    "though the autos that applied them are not — a stacked opener "
    "includes bleed that was already running",
    "E applies NO Hemorrhage stack — Apprehend deals no damage; only "
    "its always-on armor-penetration passive is modeled",
    "Q models the outer blade only; the inner radius (handle, 35% "
    "damage, applies no stack) is a misplay and is not modeled",
    "R is cast once — the free recast on execute is not modeled, since "
    "the target does not die in this calculator",
    "Bleed uses committed accounting: every stack applied during the "
    "fight counts its full 5s of ticks, including past the fight "
    "cutoff; the bleed cannot crit",
    "Hemorrhage's 250% damage against monsters is not modeled — the "
    "target is a champion",
    "Q's self-heal (17-51% of missing health by targets hit) is modeled in "
    "the ordered participant ledger; R's execute reset restores nothing here",
    "W's kill-triggered cooldown reduction and mana refund are not modeled",
    "CC is not modeled: Q's slow, E's pull/rebound/slow, W's 90% slow, and R's fear",
]

SLOTS = {
    "E": _apprehend,
    "P": _hemorrhage,
    "Q": _decimate,
    "W": _crippling_strike,
    "R": _noxian_guillotine,
}

# Reviewed crowd control, read from the cached kit.  Q (Decimate) swings
# "to deal physical damage to nearby enemies" with no control clause.  W
# (Crippling Strike) empowers the next attack to "deal bonus physical
# damage and slow the target by 90% for 1 second".  R (Noxian Guillotine)
# is the pull/airborne/slow row, but it deals no damage of its own; P is
# the Hemorrhage bleed.
#
# R stays UNREVIEWED, so this kit keeps the coarse control-armed scan.
# Noxian Guillotine is control-free against the champion it damages — it
# "attempts to execute the target enemy champion ... to deal true damage",
# and fears only on a kill and only "nearby minions and monsters".  Its
# row being two parts is no longer the obstacle (a shared instant is
# certifiable since the engine's wave-6 rule); the per-Hemorrhage-stack
# term is, because it hits once per stack and a repeated part is a
# schedule, which ``single_hit`` refuses and which has no cadence to
# author — the stacks land together, not in sequence.  Stating that would
# take a "scale the amount by stacks" part the spec does not have.
MODULE_CC = {"Q": "none", "W": "slow"}

parse_abilities = build_parser(SLOTS, "Darius", cc_kinds=MODULE_CC)


SOURCES = [
    {
        "label": "Local League Wiki cache",
        "url": "https://wiki.leagueoflegends.com/en-us/Darius",
        "revision_id": 4022598,
        "revision_timestamp": "2026-05-27T00:45:14Z",
    }
]

from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Darius")
