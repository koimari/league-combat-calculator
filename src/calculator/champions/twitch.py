"""Twitch — slot map for the archetype engine (E3 stack systems).

Why each slot is non-generic:
- P (Deadly Venom) is the stack system: basic attacks apply stacks (max
  6, 6s, refreshing); each stack deals level-scaled TRUE damage over the
  duration. The wiki carries the per-stack totals only in prose
  ("6 / 12 / 18 / 24 / 30 (based on level) (+ 18% AP) total true damage
  over the duration"), so the breakpoints live here as module constants
  (the Akshan/Braum prose-value precedent). The DoT is priced once per
  fight from the ``poison_stacks`` option (default 6 = sourced max).
- E (Contaminate) is the DETONATION: base physical damage plus, for
  each Deadly Venom stack, "Physical Damage Per Stack" physical (+35%
  bonus AD) and 35%-AP magic damage (prose ratio). The reviewed packet
  priced only the base row, losing the entire per-stack scaling.
- R (Spray and Pray) is a BUFF, not a damage packet: it grants 30/45/60
  bonus attack damage for 6 seconds. The reviewed packet priced that AD
  as if it were direct damage; the stat_buff (Vayne R precedent) makes
  autos and E's %bonus-AD stack term parse against the buffed stat.
- Q (Ambush) deals no direct damage, but "upon breaking stealth, Twitch
  gains bonus attack speed for 6 seconds" — the "Bonus Attack Speed" row
  (40-60%), emitted as a second BUFF-phase ``stat_buff`` so the fight
  engine's auto count scales with it.  It is OPTION-GATED and DEFAULT
  OFF — see below.
- W (Venom Cask) is a slow zone that applies poison stacks (covered by
  the pre-stack option) and emits a zero-damage row.

Roadmap session 5 batch L (2026-08-21): Q's magnitude moves onto its
typed atom, the window is published to the engine instead of being
averaged into the magnitude, and the whole buff is gated behind an
explicit state assertion.

  The magnitude is a typed atom, ``ability.bonus _attack _speed``
  (40/45/50/55/60% by rank), and the binary agrees:
  ``TwitchHideInShadows`` ``AttackSpeedMod`` [.35 .40 .45 .50 .55 .60
  .65].  Riot spell DataValues are rank-0-indexed, and this file's
  ``StealthDuration`` row proves that indexing independently — its
  indices 1..5 are 10/11/12/13/14, exactly the wiki's
  ``ability.stealth _duration`` atom.  So indices 1..5 of
  ``AttackSpeedMod`` are the rank 1-5 values.

  The 6-second WINDOW has no ability atom (the wiki carries it as prose
  in the effect description, not a ``leveling`` row), so it lives here as
  a module constant with both receipts: the cached description ("Upon
  breaking stealth, Twitch gains bonus attack speed for 6 seconds") and
  ``AttackSpeedDuration`` 6.0 flat at every rank index.
  ``tests/test_twitch_ambush_and_cask.py`` re-derives it from both.

  Why DEFAULT OFF, unlike Tristana Q: Rapid Fire fires ON THE CAST, so
  "Q is cast at t=0" and "the buff starts at t=0" are the same
  statement.  Ambush does the opposite — casting it makes Twitch
  CAMOUFLAGED after a 1-second fade (binary ``MaxFadeTime`` 1.0), for
  10-14s, and the attack speed arrives only when he BREAKS that stealth.
  A Twitch who casts Q at t=0 is not attacking at t=0, so a buff that is
  live from t=0 by default is a phantom proc (the Rammus lesson).  The
  option ``q_ambush_break`` is the user ASSERTING the pre-fight state —
  Twitch walked in already stealthed and breaks Ambush as the fight
  opens — which is the same shape as ``poison_stacks`` asserting stacks
  already on the target.  Under that assertion the window [0, 6) is
  exact, because ``damage.py`` resolves the window start by walking
  ``state.cast_order`` and breaking on ``"Q"``.

  That exactness is why the window is published rather than folded into
  the magnitude by ``module_helpers.buff_window_share``: the share helper
  weights the MAGNITUDE by the fraction of the fight the buff covers,
  which is the right answer only when the engine cannot place the window.
  Here it can, so the engine splits the auto count at full magnitude.

  The override carries ``active_duration`` and NOTHING else on purpose.
  ``ad_ratio`` defaults to 1.0 and the per-swing ``swing_window_ratio``
  that consumes it is read only inside the ``crit_as_bonus`` branch
  (Ashe's flurry), so a bare window changes the auto COUNT and never the
  per-swing formula.

  W (Venom Cask) closes as ``no_damage``.  ``damageType`` is ``None`` and
  the slot's whole atom catalog is the slow (30/35/40/45/50%, plus 6% per
  100 AP) and the cooldown.  The one damage-relevant thing it does —
  applying Deadly Venom stacks in the zone — is already priced by
  ``poison_stacks``, so nothing damaging is left unmodeled and the Olaf-R
  rule does not force an ``out_of_scope`` receipt.  The slow carries no
  sourced DURATION anywhere in the cache (the zone's 3 seconds is prose
  with no ``leveling`` row), so it is named rather than published as a
  control event.
"""

from typing import Any

from ..ability_atoms import required_ranked_attribute_atom
from ..ability_spec import DamagePart
from .engine import BUFF, SlotCtx, build_parser
from .slotlib import (
    STEROID_ZERO,
    damage_entry,
    extract_cooldown,
    extract_named,
    stat_buff,
)
from .source_receipts import load_champion_sources
from .inputs import bool_option, int_option
from .module_contract import coverage

# HARDCODED: verify on patch updates — wiki prose, not in the JSON.
# Deadly Venom per-stack total true damage over 6 seconds by level
# breakpoint (1/6/11/16) and its AP ratio; Contaminate's per-stack 35%
# AP magic damage; the sourced stack cap.
_POISON_MAX_STACKS = 6
_POISON_TOTAL_BREAKPOINTS = (6.0, 12.0, 18.0, 24.0, 30.0)
_POISON_BREAKPOINT_LEVELS = (1, 6, 11, 16, 18)
_POISON_AP_RATIO = 0.18  # (+ 18% AP) total per stack
_E_MAGIC_AP_RATIO = 0.35  # "and 35% AP magic damage for each stack"
# HARDCODED: verify on patch updates — the Element of Surprise window is
# wiki PROSE ("Upon breaking stealth, Twitch gains bonus attack speed for
# 6 seconds"), with no leveling row and therefore no ability atom.  The
# game binary corroborates it: TwitchHideInShadows AttackSpeedDuration is
# 6.0 at every rank index.  Both receipts are re-derived in
# tests/test_twitch_ambush_and_cask.py, which is what fails closed if a
# patch moves the number.  (The magnitude, unlike the window, IS a typed
# atom and is read as one.)
_Q_ATTACK_SPEED_WINDOW = 6.0


def _poison_stacks(options: dict[str, Any]) -> int:
    return min(
        _POISON_MAX_STACKS,
        max(0, int(options.get("poison_stacks", _POISON_MAX_STACKS))),
    )


def _poison_total_per_stack(level: int, ap: float) -> float:
    """One stack's full 6s true damage at a champion level."""
    base = _POISON_TOTAL_BREAKPOINTS[-1]
    for min_level, value in zip(_POISON_BREAKPOINT_LEVELS, _POISON_TOTAL_BREAKPOINTS):
        if level >= min_level:
            base = value
    return base + _POISON_AP_RATIO * ap


def _deadly_venom(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: the poison DoT priced once per fight at the stack option."""
    ability = ctx.ability()
    if ability is None:
        return None
    stacks = _poison_stacks(ctx.options)
    if stacks <= 0:
        return None
    per_stack = _poison_total_per_stack(ctx.level, ctx.stat("ability_power"))
    total = per_stack * stacks
    return {
        "name": ability.get("name", "Deadly Venom"),
        "rank": ctx.level,
        "cooldown": 0.0,
        "damage_type": "true",
        "total_raw": total,
        "parts": (DamagePart("true", per_stack, count=stacks),),
        "proc_count": 1,
        # Every tick is ability damage for 6s past the last application,
        # so item burns stay refreshed through the poison tail.
        "dot_duration": 6.0,
        "dot_tick_interval": 1.0,
        # One sourced event per fight: the poison packet is priced once
        # from the poison_stacks option.  The declared event is placed at
        # the fight-window end — the engine's end-of-rotation fallback
        # this ledger replaces — so ordering-certifying the row does not
        # move its ledger position and cannot change window-order item
        # outcomes (e.g. Shadowflame's threshold).  damage.py re-prices
        # the declared event at the proc's mitigated total, keeping the
        # ledger sum exactly equal to the row's total.
        "event_phase": "effect",
        "damage_events": [
            {
                "time": float(ctx.option("fight_duration_seconds") or 0.0),
                "damage_type": "true",
                "damage": total,
                "event_precision": "phase_order",
            }
        ],
        "detail": (
            f"{stacks} Deadly Venom stack(s) x {per_stack:.2f} total true "
            "damage per stack over 6s"
        ),
    }


def _contaminate(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: base + per-stack physical (+35% bonus AD) + per-stack 35% AP magic."""
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked

    base = extract_named(ability, "Base Physical Damage", rank, ctx.stats, ctx.target)
    per_stack = extract_named(
        ability, "Physical Damage Per Stack", rank, ctx.stats, ctx.target
    )
    stacks = _poison_stacks(ctx.options)
    physical = base + per_stack * stacks
    magic = _E_MAGIC_AP_RATIO * ctx.stat("ability_power") * stacks

    entry = damage_entry(
        ability.get("name", "Contaminate"),
        rank,
        extract_cooldown(ability, rank),
        physical + magic,
        "mixed",
    )
    entry["parts"] = (
        # Both damage types land at the detonation boundary: the sourced
        # per-stack terms are consumed at the cast, so each part authors
        # its hit at time_offset 0.0 (the coverage classifier certifies
        # "hit"-precision events instead of downgrading the row coarse).
        DamagePart("physical", physical, time_offset=0.0),
        DamagePart("magic", magic, time_offset=0.0),
    )
    entry["event_order_certified"] = "single_hit"
    entry["detail"] = f"{stacks} Deadly Venom stack(s) consumed"
    return entry


def _ambush(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: stealth, and — when asserted — the 6s attack-speed window.

    Zero enemy damage either way.  The steroid is published only when
    ``q_ambush_break`` asserts that Twitch entered the fight already in
    Ambush and breaks it as the fight opens; otherwise the row names the
    mechanic and stays inert (no phantom proc).  The row itself is kept
    at rank 0 so the withheld mechanic stays user-visible.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    entry = damage_entry(
        ability.get("name", "Ambush"),
        rank,
        extract_cooldown(ability, rank),
        0.0,
        "physical",
        zero_policy=STEROID_ZERO,
    )
    if rank < 1 or not ctx.option("q_ambush_break"):
        entry["detail"] = (
            "Camouflage and post-stealth attack speed: self buffs only, no "
            "enemy damage. Element of Surprise (+40/45/50/55/60% bonus "
            f"attack speed for {_Q_ATTACK_SPEED_WINDOW:g}s) is NOT applied: "
            "it needs Twitch to break an existing Ambush, which the fight "
            "model does not otherwise enter. Enable the 'opens the fight by "
            "breaking Ambush' option to assert that state."
        )
        return entry

    champion_data = {"name": ctx.champion_name, "abilities": ctx.abilities}
    bonus_as_pct, _as_atom = required_ranked_attribute_atom(
        "Twitch", champion_data, "Q", "Bonus Attack Speed", rank
    )
    entry["stat_buff"] = {"bonus_attack_speed": bonus_as_pct}
    # A BARE window: no ad_ratio and no crit_as_bonus, so only the auto
    # COUNT moves (the per-swing ratio is crit_as_bonus-only).
    entry["auto_attack_override"] = {"active_duration": _Q_ATTACK_SPEED_WINDOW}
    entry["detail"] = (
        f"Element of Surprise: +{bonus_as_pct:g}% bonus attack speed for "
        f"{_Q_ATTACK_SPEED_WINDOW:g}s from the stealth break, asserted at the "
        "fight open. Self buff, no enemy damage: the autos ride the buffed "
        "rate inside the window and the base rate after it."
    )
    return entry


_ambush.phase = BUFF


def _venom_cask(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: slow zone that applies poison stacks — a sourced zero-damage row.

    The stack application is the only damage-relevant thing here and it
    is already priced by ``poison_stacks``, so this is ``no_damage``, not
    a receipted ``out_of_scope`` opening.  The slow's magnitude rides its
    typed atoms so the row names sourced numbers.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    entry: dict[str, Any] = {
        "name": ability.get("name", "Venom Cask"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "magic",
        "total_raw": 0.0,
        "parts": (),
    }
    if rank < 1:
        entry["detail"] = (
            "Contaminated zone applies Deadly Venom stacks and slows; "
            "stack applications are covered by the poison_stacks option."
        )
        return entry
    champion_data = {"name": ctx.champion_name, "abilities": ctx.abilities}
    slow_pct, _slow_atom = required_ranked_attribute_atom(
        "Twitch", champion_data, "W", "Slow", rank
    )
    slow_ap, _slow_ap_atom = required_ranked_attribute_atom(
        "Twitch", champion_data, "W", "Slow", rank, modifier_index=1
    )
    entry["detail"] = (
        f"Movement slow only: {slow_pct:g}% (+{slow_ap:g}% per 100 AP) in the "
        "contaminated zone, which also applies a Deadly Venom stack each "
        "second. No enemy-damage clause exists in the slot; the stack "
        "applications are already priced by the poison_stacks option, and "
        "the slow carries no sourced duration to publish as a control event."
    )
    return entry


OPTIONS: list[dict[str, Any]] = [
    int_option(
        "poison_stacks",
        _POISON_MAX_STACKS,
        minimum=0,
        maximum=_POISON_MAX_STACKS,
        label="Deadly Venom stacks on the target when the fight opens "
        "(6 = fully stacked)",
    ),
    bool_option(
        "q_ambush_break",
        False,
        label="Twitch opens the fight by breaking Ambush "
        "(Element of Surprise: bonus attack speed for 6s)",
        rotation={
            "role": "self_state",
            "slot": "Q",
            "note": (
                "Asserts the PRE-FIGHT state Q's post-stealth attack speed "
                "needs — Twitch walked in already camouflaged and breaks "
                "Ambush as the fight opens — so the window sits at [0, 6). "
                "Casting Q inside the fight instead makes him camouflaged, "
                "not faster, which is why this is off by default."
            ),
        },
    ),
]

ASSUMPTIONS = [
    "W (Venom Cask) stays out of MODULE_CC: its slow is sourced (the "
    "cached 'Slow' row, 30/35/40/45/50% + 6% per 100 AP) but its window "
    "is not. The contaminated area lasts 3 seconds by the second effect's "
    "description alone, and the slot carries no seconds atom at all, so "
    "there is no sourced interval for a control event to publish.",
    "Deadly Venom stacks come from the poison_stacks option (default 6 "
    "= the sourced max); each stack deals its full 6-second total of "
    "level-scaled true damage (6/12/18/24/30 by level + 18% AP — wiki "
    "prose, module constants) once per fight",
    "E (Contaminate) detonates all stacks: base physical + stacks x "
    "per-stack physical (+35% bonus AD) + stacks x 35% AP magic",
    "R (Spray and Pray) is a 6s bonus-AD buff (+30/45/60 by rank) that "
    "raises autos and E's %bonus-AD stack term — modeled as a BUFF-phase "
    "stat_buff, not direct damage",
    "The auto-attack rate that applies poison in a real fight is not "
    "modeled (stack rate is the option); the fight's own autos still "
    "deal their base AD damage",
    "Q (Ambush) deals no enemy damage. Element of Surprise — the sourced "
    "40/45/50/55/60% bonus attack speed for 6 seconds on breaking stealth "
    "(atom ability.bonus _attack _speed; binary TwitchHideInShadows "
    "AttackSpeedMod agrees, and its AttackSpeedDuration 6.0 plus the "
    "cached prose carry the window) — is published as a stat_buff with a "
    "bare 6-second auto_attack_override window ONLY when the "
    "q_ambush_break option is on. It defaults OFF because the buff needs "
    "Twitch to break an already-active Ambush: casting Q at the fight "
    "open makes him camouflaged, not faster, so an always-on window would "
    "be a phantom proc. With the option on, the Q-slot kernel places the "
    "window at [0, 6) exactly, and the override carries the window only — "
    "no ad_ratio and no crit conversion — so the per-swing formula is "
    "untouched and only the auto count moves. The 1-second entry delay, "
    "the camouflage and its movement speed are not modeled",
    "W (Venom Cask) is a movement slow only (30/35/40/45/50%, +6% per 100 "
    "AP): a sourced zero-damage row (MODULE_COVERAGE: no_damage). Its "
    "in-zone Deadly Venom applications are already priced by the "
    "poison_stacks option, so no damage channel is left unmodeled, and "
    "the slow has no sourced duration to publish as a control event",
]

SLOTS = {
    "R": stat_buff(
        "Bonus Attack Damage",
        "bonus_attack_damage",
        apply_to=("attack_damage", "bonus_attack_damage"),
    ),
    "Q": _ambush,
    "W": _venom_cask,
    "E": _contaminate,
    "P": _deadly_venom,
}

# Reviewed crowd control, read from the cached kit: E (Contaminate)
# "sends out a lethal toxin to each nearby enemy afflicted by Deadly
# Venom, dealing them physical damage" and applies no control.  It is the
# only slot whose cast reaches the ability ledger — P's venom rides the
# attack stream, Q is a stealth buff, R is an attack-range/AD steroid, and
# W (Venom Cask), where the kit's slow lives, deals no damage at all.
MODULE_CC = {"E": "none"}

parse_abilities = build_parser(SLOTS, "Twitch", cc_kinds=MODULE_CC)

# W is emitted and grants nothing the engine prices: its slow has no
# magnitude field, and the poison stacks it applies are the P option's.
MODULE_COVERAGE = coverage(no_damage="W")

SOURCES = load_champion_sources("Twitch")
