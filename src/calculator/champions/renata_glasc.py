"""Renata Glasc — CP10.6 full-entry-reviewed packet module (E9-2 fixes).

E9-2 gap fixes:
- P (Leverage) is modeled as an on-hit mark: the first basic attack on an
  unmarked target deals bonus magic damage equal to 1% : 2% (based on
  level) (+ 2% per 100 AP) of the target's maximum health (cached P
  Per-Level Scaling row; the AP per-100 ratio is wiki prose).  The mark
  lasts 6 seconds and refreshes on subsequent hits, so a sustained 1v1
  prices ONE unmarked first-hit per target — the ``p_leverage_procs``
  option (default 1).
- E (Loyalty Program) grants Renata herself a shield: "Renata and allies
  struck are granted a shield for 3 seconds".  The shield strength is the
  cached "Shield Strength" row (50-110 + 50% AP) and rides the E damage
  entry as a module-authored self-shield (E8c payload), so the 1v1 ledger
  grants it without needing a teammate.
- Q/E damage remain modeled.

W (Bailout) grants "the target bonus attack speed and bonus movement
speed ... with both of the bonuses increasing in effectiveness by
0% : 100% (based on seconds elapsed)" across its 5 seconds, and the
cache carries both ends of that ramp: "Bonus Attack Speed" (10-30% + 1%
per 100 AP) at the start and "Maximum Bonus Attack Speed" (20-60% + 2%
per 100 AP) at the end.  The self cast's mean of the two rides a
BUFF-phase ``stat_buff``; an ally cast is the roster's and reaches it
through the ally-support scanner.  The movement-speed rows have no
engine channel, and R (Hostile Takeover) berserks its targets — control
the engine records as a kind without a magnitude.

Bailout's LETHAL half (the 100%-health restore paid for with a
maximum-health burn) stays fail-closed, and the conflict behind that
refusal is adjudicated field by field in ``BAILOUT_AUTHORITY``: the burn
CADENCE is settled in favour of the game binary on the repo's Gnar
precedent (0.25s, ten ticks, a 2.5s window), while the burn's damage
CLASS remains unresolved — the cached description calls it true damage,
the same entry's notes call it raw damage, and the binary defines no
damage class for it at all.  A class that cannot be resolved cannot
decide whether a shield or a damage-reduction window absorbs a tick, so
the survival result is unpublishable and the named denial receipts stand.
"""

from typing import Any

from ..ability_spec import DamagePart
from ..binary_roots import data_value, spell_object
from .contract_vocabulary import coverage
from .engine import BUFF, SlotCtx
from .inputs import int_option
from .module_helpers import buff_window_share, ranked_slot
from .packet_module import build_packet_module
from .slot_control import with_control_event
from .slot_entries import STEROID_ZERO, attach_self_shield, damage_entry
from .slot_extract import ability_name, extract_cooldown, extract_named, extract_value
from .slotlib import proc_damage

PACKET_SHA256 = "384ce3a01847e53d1b8cdaaa0d444174ecfba6cfb31d913a020a45fab7d189fa"


# Rooted in RenataPassive.APToPercentRatio, converted from the binary's
# fraction-per-AP representation to the module's percentage-per-100-AP unit.
# The cached P prose corroborates the resulting 2% per 100 AP.
# HARDCODED: verify on patch updates — wiki prose on P: the on-hit bonus
# is "+ 2% per 100 AP" of the target's maximum health; the per-level base
# is the cached Per-Level Scaling row (1% : 2%).
_RENATA_P_SPELL = spell_object("Renata", "RenataPassive")
_P_AP_RATIO_PER_100 = data_value(_RENATA_P_SPELL, "APToPercentRatio") * 10000.0
# E shield duration (cached E description: "granted a shield for 3
# seconds").
_E_SHIELD_DURATION = data_value(spell_object("Renata", "RenataE"), "ShieldDuration")
# Bailout's window is cached W prose ("infuses ... for 5 seconds"); both
# ends of its ramp are JSON leveling rows.
_W_DURATION_SECONDS = data_value(spell_object("Renata", "RenataW"), "Duration")
_W_SELF_CAST = "self"
_W_ALLY_CAST = "ally"


def _leverage_per_proc(ctx: SlotCtx, ability: dict[str, Any]) -> float:
    """One Leverage proc: per-level % + 2% per 100 AP of target max health."""
    percent = extract_value(ability, "Per-Level Scaling", ctx.level, 0)
    ap = float(ctx.stat("ability_power") or 0.0)
    percent += _P_AP_RATIO_PER_100 * ap / 100.0
    target_max = float(ctx.target_stat("target_max_health") or 0.0)
    return percent / 100.0 * target_max


_leverage = proc_damage(
    _leverage_per_proc,
    "magic",
    count_option="p_leverage_procs",
    default_count=1,
    name="Leverage",
    phase_order_events=True,
)


@ranked_slot
def _bailout(ctx: SlotCtx, ability: dict[str, Any], rank: int) -> dict[str, Any] | None:
    """W: the self cast's ramping attack speed, at the ramp's mean."""

    on_self = str(ctx.option("w_bailout_target")) == _W_SELF_CAST
    start = extract_named(ability, "Bonus Attack Speed", rank, ctx.stats, {})
    end = extract_named(ability, "Maximum Bonus Attack Speed", rank, ctx.stats, {})
    ramp_mean = (start + end) / 2.0
    share = buff_window_share(ctx, _W_DURATION_SECONDS) if on_self else 0.0
    bonus_as = ramp_mean * share
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        0.0,
        "physical",
        zero_policy=STEROID_ZERO,
    )
    entry["stat_buff"] = {"bonus_attack_speed": bonus_as}
    entry["detail"] = (
        f"+{start:g}% ramping to +{end:g}% bonus attack speed over "
        f"{_W_DURATION_SECONDS:g}s — mean {ramp_mean:g}%, "
        f"{bonus_as:g}% applied"
        if on_self
        else (
            f"cast on an ally: the same +{start:g}% to +{end:g}% ramp is "
            "the roster's and reaches it through the ally-support scanner"
        )
    )
    return entry


_bailout.phase = BUFF


def _loyalty_program(packet_e):
    """E: magic damage row plus Renata's own 3s shield from the rockets."""

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        entry = packet_e(ctx)
        if entry is None:
            return None
        # The self-shield payload rides the ability's damage-event rows, so the
        # packet part gets an authored cast-boundary offset (the rockets strike
        # targets around Renata on launch).
        entry["parts"] = tuple(
            DamagePart(
                part.damage_type,
                amount=part.amount,
                count=part.count,
                hp_scaled_damage=part.hp_scaled_damage,
                crit_effectiveness=part.crit_effectiveness,
                basic_damage=part.basic_damage,
                bonus_ad_ratio=part.bonus_ad_ratio,
                dot_stack_scaled=part.dot_stack_scaled,
                time_offset=0.0,
                hit_interval=part.hit_interval,
                cc_kind=part.cc_kind,
                cc_duration=part.cc_duration,
                skillshot=part.skillshot,
            )
            for part in entry["parts"]
        )
        ability = ctx.ability("E", 0)
        rank = ctx.rank_for("E")
        shield = (
            extract_named(ability, "Shield Strength", rank, ctx.stats, {})
            if ability is not None
            else 0.0
        )
        if shield > 0.0:
            return attach_self_shield(
                entry,
                amount=shield,
                duration=_E_SHIELD_DURATION,
                source="Loyalty Program",
                detail=(
                    "Magic damage row plus the sourced Shield Strength "
                    "(50-110 + 50% AP) granted to Renata herself for 3s — "
                    "'Renata and allies struck are granted a shield'."
                ),
            )
        return entry

    return parse


# Cached kit review.  Q's hook "deals magic damage to the first enemy hit
# and roots them for 1 second"; the recast's throw and its 0.5-second stun
# land on the enemies the thrown target passes through, not on the hooked
# target this row prices.  E's rockets are the kit's other damaging cast:
# "enemies struck are dealt magic damage and slowed by 30% for 2 seconds".
# W (Bailout) and R (Hostile Takeover) deal no damage — R's berserk is
# real control with no damage row to carry it — and P is an on-hit mark on
# the auto stream, so none of the three can carry an answer of its own.
# R (Hostile Takeover) prices no damage; berserk is a forced action, not
# an immobilize, so it arms no immobilize-gated item.
MODULE_CC = {"Q": "root", "E": "slow", "R": "berserk", "P": "none", "W": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Renata Glasc",
    PACKET_SHA256,
    # The hook deals its damage to the first enemy it hits, once — the
    # boundary claim that carries MODULE_CC's reviewed answer for Q
    # into the event ledger.  E authors its own cast-boundary offset
    # below, beside the shield that rides its events.
    single_hit_slots=frozenset({"Q"}),
    slot_parsers={
        "P": _leverage,
        "W": _bailout,
    },
    slot_wrappers={
        "E": _loyalty_program,
        # Hostile Takeover prices no damage; the berserk it applies is
        # the cached "Berserk Duration" row (1.25/1.75/2.25s).
        "R": lambda parser: with_control_event(
            parser,
            duration_attr="Berserk Duration",
        ),
    },
    cc_kinds=MODULE_CC,
)

OPTIONS: list[dict[str, Any]] = [
    *list(OPTIONS),
    int_option(
        "p_leverage_procs",
        1,
        minimum=0,
        maximum=10,
        label="Leverage on-hit procs (unmarked first-hits; the mark lasts 6s "
        "and refreshes, so a 1v1 prices one per target)",
        rotation={
            "role": "self_state",
            "slot": "P",
            "note": "P Leverage is an on-hit mark applied/refreshed by the auto "
            "stream — self-state, no cross-slot cast edge.",
        },
    ),
]

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "P (Leverage) is an on-hit mark: the first basic attack on an "
    "unmarked target deals bonus magic damage equal to 1% : 2% (based on "
    "level) (+ 2% per 100 AP) of the target's maximum health — the "
    "cached Per-Level Scaling row; the mark refreshes on subsequent hits "
    "and expires on a new target, so the 1v1 prices the p_leverage_procs "
    "option (default 1)",
    "E (Loyalty Program) grants Renata herself a 3s shield for the "
    "sourced Shield Strength (50-110 + 50% AP) — the rockets strike "
    "'Renata and allies struck'; the ally half is a scanner packet with "
    "scope all_teammates (every selected teammate the rockets pass "
    "through), so a roster fight shields each selected ally and the 1v1 "
    "prices only the module-authored self shield",
    "W (Bailout) prices its SELF cast: the mean of the two cached "
    "attack-speed rows (Bonus Attack Speed 10-30% + 1% per 100 AP and "
    "Maximum Bonus Attack Speed 20-60% + 2% per 100 AP), which is what "
    "the sourced 0%-to-100% linear ramp averages to over its 5 seconds, "
    "time-weighted by the share of the fight window the buff covers.  "
    "w_bailout_target names who the cast lands on; an ally cast is the "
    "roster's and reaches it through the ally-support scanner.",
    "W's movement-speed rows have no engine channel, and R (Hostile "
    "Takeover) berserks its targets — control the engine records as a "
    "kind without a magnitude.",
    "W (Bailout)'s LETHAL half is documented-only. The Wiki cache "
    "describes a fatal-damage restore to 100% maximum health followed by "
    "10% maximum-health burn ticks that kill the target anyway unless a "
    "takedown lands within 6s. The burn CADENCE is adjudicated to the game "
    "binary (TicksPerSecond 4 -> 0.25s, TicksBeforeDeath 10 -> a 2.5s "
    "window) over the Wiki's 0.264s, on the repo's Gnar game-file "
    "precedent. The burn's DAMAGE CLASS is not adjudicated: the Wiki "
    "description calls it true damage, the same entry's notes call it raw "
    "damage, and the binary defines no damage class for it. That field "
    "decides whether a shield absorbs a tick, and Renata's own E shields "
    "the covered participant, so the survival result fails closed until a "
    "source resolves it — see BAILOUT_AUTHORITY for the per-field record. "
    "The ramping attack-speed and movement-speed buff has no survival "
    "impact on the recipient in this model.",
]

OPTIONS = [
    *list(OPTIONS),
    {
        "key": "w_bailout_target",
        "type": "select",
        "default": _W_SELF_CAST,
        "label": "Bailout (W) cast on",
        "rotation": {
            "role": "self_state",
            "slot": "W",
            "note": "Names who W lands on; only the self branch reaches this "
            "fighter's stats.",
        },
        "choices": [
            {"value": _W_SELF_CAST, "label": "Renata herself"},
            {"value": _W_ALLY_CAST, "label": "An allied champion"},
        ],
    },
]

# R is emitted and grants nothing the engine prices: berserk is a
# crowd-control kind, and the engine has no magnitude field for it.
MODULE_COVERAGE = coverage(no_damage="R")
