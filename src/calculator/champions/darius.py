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
from .healing_contract import declare_healing_rule
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    stat_buff,
    sum_modifiers,
    with_control_event,
)
from .source_receipts import load_champion_sources
from .. import healing_helpers as _healing

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

# HARDCODED rule declaration — Crippling Strike's kill-triggered cooldown
# halving and mana refund.  The cached W effects[1] prose ("If this attack
# kills the target, half of Crippling Strike's cooldown is reduced and its
# mana cost is refunded.") has no leveling row, so the atom catalog holds
# no atom for it; the game binary corroborates the HALF via the W hit
# spell's PercentCDRefund [50.0 x7] (the magnitude is data, the kill check
# script-side) and the flat 40 via the cached cost row [40 x5] + the
# binary mana [40 x6].  The kill is ASSERTED by the w_kill_assertion
# option — the fight model's target never dies, so no input can prove it.
W_KILL_COOLDOWN_FACTOR = 0.5
W_KILL_REFUND_FLAT = 40.0


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


# Modifier 1 is the AD term on every row but W, whose only modifier IS the AD
# term, so W passes ``modifier_index=0``.
def _ad_ratio(
    ability: dict[str, Any],
    attribute: str,
    rank: int,
    modifier_index: int = 1,
) -> float:
    """An attribute's AD-scaling modifier at *rank*, as a 0..n fraction."""
    return extract_value(ability, attribute, rank, modifier_index) / 100.0


def _starting_stacks(ctx: SlotCtx) -> int:
    """Hemorrhage stacks already on the target when the fight opens; seeding
    them is what lets R's count, the bleed rate and Noxian Might agree."""
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
    if ctx.option("w_kill_assertion"):
        # P4-14: the kill is asserted (the model's target never dies, so
        # the input cannot prove it — the w_kill_assertion option is the
        # r_execute_recast precedent).  Every accepted W empowered attack
        # is assumed to kill: the cycle's cooldown is halved (the
        # PercentCDRefund 50.0) and the flat 40 (the sourced cost) is
        # refunded by the resource walk.  With the option off the entry
        # stays byte-identical (the rule is simply not modeled).
        entry["cooldown"] *= W_KILL_COOLDOWN_FACTOR
        entry["kill_refund"] = {
            "flat": W_KILL_REFUND_FLAT,
            "source": "Darius W (Crippling Strike) kill refund",
            "atoms": (),
        }
    return entry


_armor_pen_buff = stat_buff("Armor Penetration", "armor_penetration_percent")


def _apprehend(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: a zero-damage pull whose armor-pen passive is always on.
    Carries no ``applies_dot_stack``: dealing no damage applies no
    Hemorrhage stack."""
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

    With ``r_execute_recast`` (default off) the cast is assumed to
    EXECUTE the target, so the sourced free recast ("can also recast
    the ability within 20 seconds at no cost", cached R prose) fires
    once more against the same (max) stack count — the recast parts are
    a second base + per-stack pair offset past the kill check.
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
    base_ratio = _ad_ratio(ability, "True Damage", rank)
    per_stack_ratio = _ad_ratio(ability, "Bonus Damage Per Stack", rank)

    # Parse-level view of the opening state; the engine re-resolves the
    # count against the timeline at R's cast time.
    stacks = _starting_stacks(ctx)

    parts = [
        DamagePart("true", base, bonus_ad_ratio=base_ratio),
        DamagePart(
            "true",
            per_stack,
            count=stacks,
            bonus_ad_ratio=per_stack_ratio,
            dot_stack_scaled=True,
        ),
    ]
    total = base + per_stack * stacks
    execute_recast = bool(ctx.option("r_execute_recast"))
    if execute_recast:
        # The recast lands after the 0.15s death check and its own leap
        # (R cast time again), at the same stack count the first R left.
        recast_offset = R_CAST_TIME + 0.15 + R_CAST_TIME
        parts.extend(
            (
                DamagePart(
                    "true",
                    base,
                    bonus_ad_ratio=base_ratio,
                    time_offset=recast_offset,
                ),
                DamagePart(
                    "true",
                    per_stack,
                    count=stacks,
                    bonus_ad_ratio=per_stack_ratio,
                    dot_stack_scaled=True,
                    time_offset=recast_offset,
                ),
            )
        )
        total *= 2.0

    entry = damage_entry(
        ability.get("name", "Noxian Guillotine"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "true",
    )
    entry["parts"] = tuple(parts)
    if execute_recast:
        entry["detail"] = (
            f"execute recast: both casts at {stacks} Hemorrhage stack(s) "
            f"({base:g} + {stacks} x {per_stack:g} per cast)"
        )
    entry["applies_dot_stack"] = True
    entry["cast_time"] = R_CAST_TIME
    return entry


OPTIONS: list[dict[str, Any]] = [
    {
        "key": "r_execute_recast",
        "type": "bool",
        "default": False,
        "label": (
            "Assume R executes the target: the free recast fires once "
            "more within 20 seconds (same stack count)"
        ),
        "rotation": {
            "condition": "execute",
            "kind": "execute",
            "role": "execute",
            "slot": "R",
        },
    },
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
    {
        "key": "w_kill_assertion",
        "type": "bool",
        "default": False,
        "label": (
            "Assume every accepted W empowered attack kills the target: "
            "Crippling Strike's cooldown is halved (PercentCDRefund 50.0) "
            "and its mana cost (40) is refunded"
        ),
        # NO rotation metadata: the kill does not reorder the rotation (an
        # execute-role edge on the damage row would make the resolver
        # derive a different order — the r_execute_recast metadata is R's
        # own; W's kill is a resource/cooldown assertion, not a rotation
        # edge).
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
    "R is cast once by default; with r_execute_recast enabled the "
    "cast is assumed to execute the target, so the sourced free recast "
    "('recast the ability within 20 seconds at no cost', cached R "
    "prose) fires once more against the same stack count — both casts "
    "priced at 2 x (base + N x per-stack), the recast parts offset "
    "past the 0.15s kill check; the model's target never dies, so the "
    "execute is an assertion via the option, and the recast's mana "
    "cost is not separately zeroed (one cast's cost is the module's "
    "existing single-cast cost)",
    "Bleed uses committed accounting: every stack applied during the "
    "fight counts its full 5s of ticks, including past the fight "
    "cutoff; the bleed cannot crit",
    "Hemorrhage's 250% damage against monsters is not modeled — the "
    "target is a champion",
    "Q's self-heal (17-51% of missing health by targets hit) is modeled in "
    "the ordered participant ledger; R's execute reset restores nothing here",
    "W's kill-triggered cooldown reduction and mana refund are modeled as "
    "an ASSERTION: the w_kill_assertion option assumes every accepted W "
    "empowered attack kills (the model's target never dies, so no input "
    "can prove a kill — the r_execute_recast precedent).  With the option "
    "on, W's cooldown is halved (the binary PercentCDRefund 50.0; haste "
    "applies to the halved base) and the flat 40 (the sourced cost row) "
    "is refunded by the resource walk at the W cast time after the spend "
    "(cast, hit, refund — it can only enable later casts).  The cached "
    "notes' exclusion is jungle plants only ('The cooldown reduction and "
    "mana refund will not trigger when killing jungle plants.') — the "
    "modeled target is a champion, so the exclusion is trivially "
    "satisfied; no structure/monster exclusion is sourced and none is "
    "invented.  The in-game swing lands one auto interval after the cast "
    "and the 4s empower window is never enforced (the model's hit time "
    "is the cast time) — the coarse timing is documented, not modeled.",
    "Q, W, and R slow effects are utility; E's sourced 1-second "
    "airborne interval is counted as action downtime",
]

SLOTS = {
    "E": _apprehend,
    "P": _hemorrhage,
    "Q": _decimate,
    "W": _crippling_strike,
    "R": _noxian_guillotine,
}
SLOTS["E"] = with_control_event(
    SLOTS["E"],
    kind="airborne",
    duration_attr="Airborne Duration",
    effect_index=1,
)

# Reviewed crowd control, read from the cached kit.  Q (Decimate) swings
# "to deal physical damage to nearby enemies" with no control clause.  W
# (Crippling Strike) empowers the next attack to "deal bonus physical
# damage and slow the target by 90% for 1 second".  R (Noxian Guillotine)
# is the pull/airborne/slow row, but it deals no damage of its own; P is
# the Hemorrhage bleed.
#
# R stays UNREVIEWED, so this kit keeps the coarse control-armed scan.
# Noxian Guillotine is control-free against the champion it damages: it
# "attempts to execute the target enemy champion ... to deal true damage",
# and fears only on a kill and only "nearby minions and monsters".  The
# obstacle is the per-Hemorrhage-stack term, which hits once per stack.  A
# repeated part is a schedule, which ``single_hit`` refuses and which has no
# cadence to author, since the stacks land together rather than in sequence.
# Stating it would take a "scale the amount by stacks" part the spec lacks.
MODULE_CC = {"Q": "none", "W": "slow"}

parse_abilities = build_parser(SLOTS, "Darius", cc_kinds=MODULE_CC)


SOURCES = load_champion_sources("Darius")


# pylint: disable=protected-access,too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Resolve Darius self-healing events from its authored packet.

    Decimate's outer blade heals for 17% of missing health per enemy
    champion hit, capped at 51% for three or more champions.  The heal is
    paid on the CAST — one activation, however many hits the row authors —
    and pair packets mark the cast so the coupled timeline coalesces those
    per-target receipts before applying one live heal.
    """
    healing = []
    for payment in _healing._payments(
        _healing.HealAnchor.CAST, "Q", damage_events, cast_timeline
    ):
        event = payment.event
        trigger_time = float(event.get("time", 0.0))
        trigger_sequence = int(event.get("sequence", 0) or 0)

        def missing_health_heal(
            current_health: float,
            maximum_health: float,
            ratio: float = 0.17,
        ) -> float:
            return max(0.0, maximum_health - current_health) * ratio

        healing.append(
            {
                "time": trigger_time,
                "amount": 0.0,
                "amount_formula": missing_health_heal,
                "source": "Decimate",
                "kind": "champion_ability",
                "_darius_q_group": (trigger_time, trigger_sequence),
                **_healing._trigger_fields(event),
            }
        )
    return sorted(healing, key=lambda event: (event["time"], event["source"]))


SELF_HEALING_RULE = declare_healing_rule("Darius", derive_self_healing)
