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
- Q/E damage remain modeled; W bailout and R berserk stay documented
  out-of-scope rows.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .packet_module import build_packet_module
from .slotlib import attach_self_shield, extract_named, extract_value, proc_damage

PACKET_SHA256 = "384ce3a01847e53d1b8cdaaa0d444174ecfba6cfb31d913a020a45fab7d189fa"

_packet_parse, _packet_slots, _packet_assumptions, _packet_sources, _packet_options = (
    build_packet_module(
        "Renata Glasc",
        PACKET_SHA256,
        # The hook deals its damage to the first enemy it hits, once — the
        # boundary claim that carries MODULE_CC's reviewed answer for Q
        # into the event ledger.  E authors its own cast-boundary offset
        # below, beside the shield that rides its events.
        single_hit_slots=frozenset({"Q"}),
    )
)
PACKET_SPEC = _packet_slots.packet_spec

# HARDCODED: verify on patch updates — wiki prose on P: the on-hit bonus
# is "+ 2% per 100 AP" of the target's maximum health; the per-level base
# is the cached Per-Level Scaling row (1% : 2%).
_P_AP_RATIO_PER_100 = 2.0
# E shield duration (cached E description: "granted a shield for 3
# seconds").
_E_SHIELD_DURATION = 3.0


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


def _loyalty_program(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: magic damage row plus Renata's own 3s shield from the rockets."""
    entry = _packet_slots["E"](ctx)
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


SLOTS = dict(_packet_slots)
SLOTS["P"] = _leverage
SLOTS["E"] = _loyalty_program

# Cached kit review.  Q's hook "deals magic damage to the first enemy hit
# and roots them for 1 second"; the recast's throw and its 0.5-second stun
# land on the enemies the thrown target passes through, not on the hooked
# target this row prices.  E's rockets are the kit's other damaging cast:
# "enemies struck are dealt magic damage and slowed by 30% for 2 seconds".
# W (Bailout) and R (Hostile Takeover) deal no damage — R's berserk is
# real control with no damage row to carry it — and P is an on-hit mark on
# the auto stream, so none of the three can carry an answer of its own.
MODULE_CC = {"Q": "root", "E": "slow"}

parse_abilities = build_parser(SLOTS, "Renata Glasc", cc_kinds=MODULE_CC)

OPTIONS: list[dict[str, Any]] = list(_packet_options) + [
    {
        "key": "p_leverage_procs",
        "type": "int",
        "default": 1,
        "min": 0,
        "max": 10,
        "label": (
            "Leverage on-hit procs (unmarked first-hits; the mark lasts 6s "
            "and refreshes, so a 1v1 prices one per target)"
        ),
        "rotation": {
            "role": "self_state",
            "slot": "P",
            "note": (
                "P Leverage is an on-hit mark applied/refreshed by the auto "
                "stream — self-state, no cross-slot cast edge."
            ),
        },
    },
]

ASSUMPTIONS = list(_packet_assumptions) + [
    "P (Leverage) is an on-hit mark: the first basic attack on an "
    "unmarked target deals bonus magic damage equal to 1% : 2% (based on "
    "level) (+ 2% per 100 AP) of the target's maximum health — the "
    "cached Per-Level Scaling row; the mark refreshes on subsequent hits "
    "and expires on a new target, so the 1v1 prices the p_leverage_procs "
    "option (default 1)",
    "E (Loyalty Program) grants Renata herself a 3s shield for the "
    "sourced Shield Strength (50-110 + 50% AP) — the rockets strike "
    "'Renata and allies'; the ally half needs a roster teammate and is "
    "not priced in the 1v1",
    "W (Bailout) revival and R (Hostile Takeover) berserk are "
    "documented out-of-scope rows (no enemy damage).",
]

SOURCES = list(_packet_sources)
MODULE_COVERAGE = {
    "P": "modeled",
    "Q": "modeled",
    "W": "out_of_scope",
    "E": "modeled",
    "R": "out_of_scope",
}
