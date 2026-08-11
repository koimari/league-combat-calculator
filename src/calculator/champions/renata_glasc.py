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
- Q/E damage remain modeled. W Bailout stays fail-closed because the local
  Wiki cache and game binary disagree on the burn cadence and damage class.
  R berserk stays documented as an out-of-scope row.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .packet_module import build_packet_module
from .slotlib import attach_self_shield, extract_named, extract_value, proc_damage

PACKET_SHA256 = "384ce3a01847e53d1b8cdaaa0d444174ecfba6cfb31d913a020a45fab7d189fa"

_packet_parse, _packet_slots, _packet_assumptions, _packet_sources, _packet_options = (
    build_packet_module("Renata Glasc", PACKET_SHA256)
)
PACKET_SPEC = _packet_slots.packet_spec

# HARDCODED: verify on patch updates — wiki prose on P: the on-hit bonus
# is "+ 2% per 100 AP" of the target's maximum health; the per-level base
# is the cached Per-Level Scaling row (1% : 2%).
_P_AP_RATIO_PER_100 = 2.0
# E shield duration (cached E description: "granted a shield for 3
# seconds").
_E_SHIELD_DURATION = 3.0

# Bailout cannot enter the survival kernel until its burn has one exact local
# authority. The Wiki cache says one 10%-maximum-health tick every 0.264s and
# describes true damage. Its notes call the same health loss raw damage. The
# local 16.15 game binary instead carries TicksPerSecond=4 (0.25s). Publishing
# either interpretation would overstate or understate survival, so this
# source-status receipt is descriptive only and runtime availability is false.
BAILOUT_AUTHORITY = {
    "runtime_available": False,
    "reason": "burn_authority_conflict",
    "wiki_burn_interval_seconds": 0.264,
    "gamefile_ticks_per_second": 4.0,
    "wiki_description_damage_class": "true",
    "wiki_notes_damage_class": "raw",
    "gamefile_path": "data/bin/characters/renata.bin.json",
    "gamefile_sha256": (
        "9f6ffc8c07f63734978479b3f56c2b364d07cd2bcb46f061936c0bebd03d5000"
    ),
}


def _leverage_per_proc(ctx: SlotCtx, ability: dict[str, Any]) -> float:
    """One Leverage proc: per-level % + 2% per 100 AP of target max health."""
    percent = extract_value(ability, "Per-Level Scaling", ctx.level, 0)
    ap = float(ctx.stats.get("ability_power", 0.0) or 0.0)
    percent += _P_AP_RATIO_PER_100 * ap / 100.0
    target_max = float(ctx.target.get("target_max_health", 0.0) or 0.0)
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


SLOTS = dict(_packet_slots)
SLOTS["P"] = _leverage
SLOTS["E"] = _loyalty_program
parse_abilities = build_parser(SLOTS, "Renata Glasc")

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
    "'Renata and allies struck'; the ally half is a scanner packet with "
    "scope all_teammates (every selected teammate the rockets pass "
    "through), so a roster fight shields each selected ally and the 1v1 "
    "prices only the module-authored self shield",
    "W (Bailout) revival and R (Hostile Takeover) berserk are "
    "documented out-of-scope rows (no enemy damage).",
    "W (Bailout) is documented-only for ally support. The Wiki cache "
    "describes a fatal-damage restore to 100% maximum health followed by "
    "10% maximum-health burn ticks every 0.264s. The local game binary "
    "carries TicksPerSecond=4, while the Wiki description calls the loss "
    "true damage and its notes call it raw damage. The survival result "
    "fails closed until one source resolves both conflicts. The ramping "
    "attack-speed and movement-speed buff has no survival impact on the "
    "recipient in this model.",
]

SOURCES = list(_packet_sources)
MODULE_COVERAGE = {
    "P": "modeled",
    "Q": "modeled",
    "W": "out_of_scope",
    "E": "modeled",
    "R": "out_of_scope",
}
REVIEW_STATUS = "reviewed_module"
