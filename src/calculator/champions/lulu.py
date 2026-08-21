"""Lulu — CP10.4 full-entry-reviewed packet module.

E8d: E (Help, Pix!) Shield Strength is emitted as an ally-support event
by the support scanner.

P1-2 fix — P (Pix, Faerie Companion) becomes a modeled ONHIT slot: Pix
fires a barrage of ``lulu_pix_bolts`` (default 3, wiki prose) magic
bolts at the target whenever Lulu basic-attacks on-attack; each bolt
deals the per-level "Per-Level Scaling" row (5 : 39 by level) + 5% AP
(the AP ratio is prose in the cached P description; the second
Per-Level Scaling row is the 3-bolt total 15 : 117 + 15% AP).  The
on-hit entry prices bolts x per-bolt so reducing the barrage keeps the
sourced per-bolt row exact.

W (Whimsy) and R (Wild Growth) are both "herself or an ally" casts, so
each one declares who it lands on.  Neither carries a damage attribute
anywhere in the cache — W's leveling rows are "Disable Duration",
"Bonus Attack Speed" and "Effect Duration"; R's are "Bonus Health" and
"Slow" (data/champions.json Lulu W/R, cross-checked against
data/atoms/lulu.atoms.json where every LuluW*/LuluR* atom carries
``damage_type: null``).  What each one DOES carry is priced: only the
**self** branch reaches this fighter's stats — that is the buff the
main champion's own fight holds — and it takes the cached row through
``stat_buff``: W's Bonus Attack Speed (20-30%) for its Effect Duration
row, R's Bonus Health (275-575 + 55% AP) for 7 seconds.  An ally cast
reaches the roster through the ally-support scanner, not this slot.
W's enemy cast is the OTHER branch of the same active — the cache
states them as "Self / Ally Cast" and "Enemy Cast" — so it prices the
sourced "Disable Duration" polymorph as a control event and grants no
attack speed at all; R's 1-second knock-up has no duration row in the
cache, so it stays named rather than authored.
"""

from typing import Any

from .engine import BUFF, ONHIT, SlotCtx
from .module_helpers import buff_window_share
from .packet_module import build_packet_module
from .slotlib import (
    STEROID_ZERO,
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    on_hit_entry,
    with_control_event,
)

# HARDCODED: verify on patch updates — the 3-bolt barrage and each bolt's
# 5% AP ratio are wiki P prose; the JSON carries the per-bolt and
# 3-bolt-total flat per-level rows.
_PIX_BOLTS_DEFAULT = 3
_PIX_BOLT_AP_RATIO = 0.05
# Wild Growth's window is cached R prose ("For the next 7 seconds, the
# target gains bonus health"); W's is the JSON's Effect Duration row.
_R_DURATION_SECONDS = 7.0
# The two "herself or an ally" casts name their target the same way.
_SELF_CAST = "self"
_ALLY_CAST = "ally"
_ENEMY_CAST = "enemy"

PACKET_SHA256 = "2dcdd74eafe747d8fbd7233f3202b76fca9be9d6250a336ce0fe7f8ef2f2f1e1"


def _pix_bolts(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: Pix's 3-bolt barrage on basic attacks (per-bolt row x count)."""
    ability = ctx.ability("P", 0)
    if ability is None:
        return None
    bolts = min(max(int(ctx.options.get("lulu_pix_bolts", _PIX_BOLTS_DEFAULT)), 0), 3)
    if bolts <= 0:
        return None
    per_bolt_flat = extract_named(
        ability, "Per-Level Scaling", ctx.level, ctx.stats, ctx.target
    )
    ap = float(ctx.stat("ability_power"))
    per_bolt = per_bolt_flat + _PIX_BOLT_AP_RATIO * ap
    return on_hit_entry(
        ability.get("name", "Pix, Faerie Companion"),
        per_bolt * bolts,
        "magic",
    )


_pix_bolts.phase = ONHIT


def _whimsy(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: one cast, one branch — the self/ally buff OR the enemy polymorph.

    The cache states them as two mutually exclusive halves of one active:
    "Self / Ally Cast ... granting the target bonus attack speed" (the
    Bonus Attack Speed / Effect Duration rows) and "Enemy Cast ...
    polymorphs them into a harmless critter for a duration" (the Disable
    Duration row).  ``lulu_whimsy_target`` picks which one this cast was,
    and the branch it picks is the only one priced: a self cast that also
    polymorphed would be one cast modelled twice, and it would broadcast
    a control nobody cast onto every enemy on the board.
    """
    ability = ctx.ability("W")
    if ability is None:
        return None
    rank = ctx.rank_for("W")
    if rank < 1:
        return None

    target = str(ctx.option("lulu_whimsy_target"))
    granted = extract_value(ability, "Bonus Attack Speed", rank)
    duration = extract_value(ability, "Effect Duration", rank)
    share = buff_window_share(ctx, duration) if target == _SELF_CAST else 0.0
    bonus_as = granted * share
    entry = damage_entry(
        ability.get("name", "Whimsy"),
        rank,
        extract_cooldown(ability, rank),
        0.0,
        "physical",
        zero_policy=STEROID_ZERO,
    )
    entry["stat_buff"] = {"bonus_attack_speed": bonus_as}
    entry["detail"] = _cast_detail(
        target,
        self_text=(
            f"+{granted:g}% bonus attack speed for {duration:g}s "
            f"({bonus_as:g}% over the fight window); the cast's 25% "
            "(+5% per 100 AP) movement speed has no stat_buff key"
        ),
        ally_text=(
            f"cast on an ally: the same +{granted:g}% for {duration:g}s "
            "reaches the roster through the ally-support scanner, not "
            "this slot"
        ),
        enemy_text=(
            "cast on an enemy: the sourced Disable Duration polymorph "
            "(1.2-2s) and its disarm; the branch grants no attack speed"
        ),
    )
    if target == _ENEMY_CAST:
        # Only the enemy branch authors control, and it reads its own
        # sourced row rather than restating one here.
        entry = with_control_event(
            lambda _ctx, built=entry: built,
            kind="polymorph",
            duration_attr="Disable Duration",
        )(ctx)
    return entry


_whimsy.phase = BUFF


def _wild_growth(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: the self cast's 275-575 (+55% AP) bonus health for 7 seconds."""
    ability = ctx.ability("R")
    if ability is None:
        return None
    rank = ctx.rank_for("R")
    if rank < 1:
        return None

    target = str(ctx.option("lulu_wild_growth_target"))
    granted = extract_named(ability, "Bonus Health", rank, ctx.stats, ctx.target)
    on_self = target == _SELF_CAST
    bonus_health = granted if on_self else 0.0
    if on_self:
        ctx.stats["bonus_health"] = ctx.stat("bonus_health") + bonus_health
        ctx.stats["health"] = ctx.stat("health") + bonus_health
    entry = damage_entry(
        ability.get("name", "Wild Growth"),
        rank,
        extract_cooldown(ability, rank),
        0.0,
        "physical",
        zero_policy=STEROID_ZERO,
    )
    entry["stat_buff"] = {"bonus_health": bonus_health}
    entry["detail"] = _cast_detail(
        target,
        self_text=(
            f"+{granted:g} bonus health for {_R_DURATION_SECONDS:g}s; the "
            "knock-up and the lingering slow are control the engine "
            "records as kinds, not magnitudes"
        ),
        ally_text=(
            f"cast on an ally: the same +{granted:g} bonus health is the "
            "roster's, not this fighter's"
        ),
        enemy_text="",
    )
    return entry


_wild_growth.phase = BUFF


def _cast_detail(
    target: str, *, self_text: str, ally_text: str, enemy_text: str
) -> str:
    """The row's detail for whichever target the cast option names."""
    if target == _SELF_CAST:
        return self_text
    if target == _ENEMY_CAST and enemy_text:
        return enemy_text
    return ally_text


# Cached kit review: Q's bolts deal damage "and slow[] them by 80%
# decaying over 2 seconds"; E's enemy cast only damages and reveals.  W's
# polymorph and R's knock-up are real control on abilities that deal no
# damage, so neither can ride a damage part: W's rides its own control
# event off the sourced "Disable Duration" row, authored by ``_whimsy``
# on the enemy branch alone because the kind is a property of the cast
# and not of the slot, and R's has no duration row in the cache to
# author at all.
MODULE_CC = {"Q": "slow", "E": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Lulu",
    PACKET_SHA256,
    # Glitterlance prices one bolt and Help, Pix! one landing: each deals
    # its packet once, at the cast — the boundary claim that carries
    # MODULE_CC's reviewed answers into the event ledger.
    single_hit_slots=frozenset({"Q", "E"}),
    slot_parsers={
        "P": _pix_bolts,
        "W": _whimsy,
        "R": _wild_growth,
    },
    cc_kinds=MODULE_CC,
)

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "P (Pix, Faerie Companion) fires lulu_pix_bolts (default 3) magic "
    "bolts on each basic attack; each bolt deals the per-level row "
    "(5 : 39 by level) + 5% AP (module constants; the AP ratio is wiki "
    "prose). The second Per-Level Scaling row is the full 3-bolt total "
    "(15 : 117 + 15% AP).",
    "W (Whimsy) and R (Wild Growth) carry no damage attribute at all; "
    "each prices its SELF cast only — the cached Bonus Attack Speed row "
    "(20-30%) for its Effect Duration row and the Bonus Health row "
    "(275-575 + 55% AP) for the sourced 7 seconds.  "
    "lulu_whimsy_target / lulu_wild_growth_target name who the cast "
    "lands on; an ally cast is the roster's and reaches it through the "
    "ally-support scanner.",
    "W's two cached branches are mutually exclusive and only the one "
    "lulu_whimsy_target names is priced: a self/ally cast grants the "
    "Bonus Attack Speed row and authors no control, and an enemy cast "
    "authors the sourced Disable Duration polymorph and grants no "
    "attack speed.  The polymorph reaches every enemy in the fight "
    "because a control event carries no target of its own; the cached "
    "cast is single-target, so a multi-enemy roster overstates who it "
    "holds.",
    "R's 1-second knock-up is real control the cache gives no duration "
    "row for, so it is named rather than authored as an event.",
    "R's bonus health is held for the whole fight rather than for its "
    "sourced 7 seconds: a health pool is not a rate, so the stat_buff "
    "channel can only grant or withhold it.",
]
OPTIONS.extend(
    [
        {
            "key": "lulu_pix_bolts",
            "type": "int",
            "default": _PIX_BOLTS_DEFAULT,
            "min": 0,
            "max": 3,
            "label": "Pix bolts per basic attack",
        },
        {
            "key": "lulu_whimsy_target",
            "type": "select",
            "default": _SELF_CAST,
            "label": "Whimsy (W) cast on",
            "rotation": {
                "role": "self_state",
                "slot": "W",
                "note": (
                    "Names who W lands on; only the self branch reaches "
                    "this fighter's stats."
                ),
            },
            "choices": [
                {"value": _SELF_CAST, "label": "Lulu herself"},
                {"value": _ALLY_CAST, "label": "An allied champion"},
                {"value": _ENEMY_CAST, "label": "An enemy (polymorph)"},
            ],
        },
        {
            "key": "lulu_wild_growth_target",
            "type": "select",
            "default": _SELF_CAST,
            "label": "Wild Growth (R) cast on",
            "rotation": {
                "role": "self_state",
                "slot": "R",
                "note": (
                    "Names who R lands on; only the self branch reaches "
                    "this fighter's stats."
                ),
            },
            "choices": [
                {"value": _SELF_CAST, "label": "Lulu herself"},
                {"value": _ALLY_CAST, "label": "An allied champion"},
            ],
        },
    ]
)

# No MODULE_COVERAGE: every one of the five slots emits a priced row now.
