"""Nasus — slot map for the archetype engine (E3 stack systems).

Why each slot is non-generic:
- Q (Siphoning Strike) is the permanent-scaling stack: every kill grants
  Nasus 3 permanent stacks (12 for champions/large minions/monsters),
  and each stack adds 1 bonus damage to Q ("Bonus Physical Damage" =
  flat 40-120 by rank + 100% of Siphoning Strike stacks). The current
  stack total comes from the ``q_stacks`` option (default 0 = a fresh
  Nasus); the kill-gain itself is not modeled (the target never dies in
  this calculator). Q empowers the next basic attack, so it carries
  ``empowers_next_auto`` (Vayne Q precedent).
- E (Spirit Fire) prices the initial hit plus 10 sourced 0.5s zone
  ticks (E2 fix: "Magic Damage" + 10 x "Magic Damage Per Tick" ==
  "Total Magic Damage"), with the burn tail keeping item burns
  refreshed.
- R (Fury of the Sands) prices all 30 sourced 0.5s ticks ("Magic
  Damage Per Tick" x30 == "Total Magic Damage"); the bonus health /
  resistances are self-stats and the Siphoning Strike cooldown halving
  is not modeled.
- P (Soul Eater) and W (Wither) both emit rows that deal no enemy
  damage, but they are not the same claim. P is modeled: the Soul Eater
  heal rule prices its lifesteal off every physical hit (declared
  through ``COVERAGE_CHANNELS``). W is a no_damage row.

W (Wither) is already a cast slot in this module (SLOTS["W"] =
_wither) emitting the pinned packet's sourced zero-damage row; the
pinned packet (reviewed-packets.json) declares W in no_damage_slots
alongside P. MODULE_COVERAGE was simply stale, still reading
"out_of_scope" for an already-covered slot. Roadmap session 4 batch D
(2026-08-21) reclassifies W to "no_damage" (the Cassiopeia/Cho'Gath/
Jarvan precedent) — a documentation-only fix with zero
fight-computation change.  Wither's slow/cripple magnitude is still
unpriced; its kind rides ``MODULE_CC``.
"""

from typing import Any

from ..ability_spec import DamagePart
from ..healing_helpers import HealAnchor, heal_from_damage, payments
from .inputs import bool_option, champion_stat, int_option
from .engine import SlotCtx, build_parser
from .healing_contract import self_healing_rule
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
)
from .source_receipts import load_champion_sources
from .module_contract import coverage

# E2-sourced tick cadences (data/worklists/e2-dot-ticks.json and the
# ability descriptions): Spirit Fire's zone ticks every 0.5s over 5s
# (first tick 0.5s after the initial hit's 0.264s delay); Fury of the
# Sands ticks every 0.5s over 15s.
#
# HARDCODED: verify on patch updates — wiki prose, not a leveling row:
# the cached R description states "Siphoning Strike's cooldown is
# halved" while Fury of the Sands is active (eff[1] prose).
_R_Q_COOLDOWN_MULTIPLIER = 0.5
_E_INITIAL_DELAY = 0.264
_E_TICKS = 10
_E_TICK_INTERVAL = 0.5
_E_DOT_DURATION = 5.0
_R_TICKS = 30
_R_TICK_INTERVAL = 0.5
_R_DOT_DURATION = 15.0


def _siphoning_strike(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: bonus damage (flat + permanent stacks) riding the next auto."""
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked

    stacks = max(0, int(ctx.option("q_stacks")))
    bonus = (
        extract_named(ability, "Bonus Physical Damage", rank, ctx.stats, ctx.target)
        + stacks
    )
    entry = damage_entry(
        ability.get("name", "Siphoning Strike"),
        rank,
        extract_cooldown(ability, rank),
        bonus,
        "physical",
        # The bonus rides one empowered basic attack — one hit, at the cast
        # boundary — which is the claim that carries MODULE_CC's reviewed
        # answer for Q into the event ledger.
        event_order_certified="single_hit",
    )
    # Fury of the Sands halves Siphoning Strike's cooldown while active
    # (cached R prose).  The module prices all 30 sourced R ticks, i.e.
    # the fight sits inside R's 15s window, so the halving applies to
    # the whole fight's Q schedule; the option turns it off to price an
    # un-empowered rotation.
    if ctx.rank_for("R") >= 1 and ctx.option("r_q_cooldown_halved"):
        entry["cooldown"] *= _R_Q_COOLDOWN_MULTIPLIER
    entry["parts"] = (DamagePart("physical", bonus),)
    entry["empowers_next_auto"] = True
    entry["detail"] = (
        f"flat {bonus - stacks:.2f} + {stacks} permanent Siphoning Strike "
        f"stack(s); Q cooldown halved during Fury of the Sands"
    )
    return entry


def _spirit_fire(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: initial hit + 10 sourced 0.5s zone ticks (E2 fix)."""
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked

    initial = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    per_tick = extract_named(
        ability, "Magic Damage Per Tick", rank, ctx.stats, ctx.target
    )
    total = initial + per_tick * _E_TICKS
    entry = damage_entry(
        ability.get("name", "Spirit Fire"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    entry["parts"] = (
        DamagePart("magic", initial, time_offset=_E_INITIAL_DELAY),
        DamagePart(
            "magic",
            per_tick,
            count=_E_TICKS,
            time_offset=_E_INITIAL_DELAY + _E_TICK_INTERVAL,
            hit_interval=_E_TICK_INTERVAL,
        ),
    )
    entry["dot_duration"] = _E_DOT_DURATION
    entry["detail"] = (
        f"initial hit + {_E_TICKS} sourced {_E_TICK_INTERVAL:g}s-interval "
        f"ticks (Magic Damage Per Tick x{_E_TICKS} = Spirit Fire total)"
    )
    return entry


def _fury_of_the_sands(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: all 30 sourced 0.5s ticks (E2 fix)."""
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked

    per_tick = extract_named(
        ability, "Magic Damage Per Tick", rank, ctx.stats, ctx.target
    )
    total = per_tick * _R_TICKS
    entry = damage_entry(
        ability.get("name", "Fury of the Sands"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    entry["parts"] = (
        DamagePart(
            "magic",
            per_tick,
            count=_R_TICKS,
            time_offset=_R_TICK_INTERVAL,
            hit_interval=_R_TICK_INTERVAL,
        ),
    )
    entry["dot_duration"] = _R_DOT_DURATION
    entry["detail"] = (
        f"{_R_TICKS} sourced {_R_TICK_INTERVAL:g}s-interval ticks "
        f"(Magic Damage Per Tick x{_R_TICKS} = Fury of the Sands total)"
    )
    return entry


def _soul_eater(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: innate lifesteal — no enemy damage, self-heal via healing.py."""
    ability = ctx.ability()
    if ability is None:
        return None
    return {
        "name": ability.get("name", "Soul Eater"),
        "rank": ctx.level,
        "cooldown": 0.0,
        "damage_type": "physical",
        "total_raw": 0.0,
        "parts": (),
        "detail": (
            "Innate lifesteal: heals for 12% / 18% / 24% (based on level; "
            "game-file breakpoints 7/13) of the post-mitigation physical "
            "basic-attack/on-hit damage dealt — authored by the Soul Eater "
            "heal rule (HEALING_RULE_CHAMPIONS), no enemy damage."
        ),
    }


def _wither(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: slow/cripple — no enemy damage."""
    ability = ctx.ability()
    if ability is None:
        return None
    return {
        "name": ability.get("name", "Wither"),
        "rank": ctx.rank_for(),
        "cooldown": extract_cooldown(ability, ctx.rank_for()),
        "damage_type": "magic",
        "total_raw": 0.0,
        "parts": (),
        "detail": "Slow and attack-speed cripple: CC only, no damage.",
    }


OPTIONS: list[dict[str, Any]] = [
    bool_option(
        "r_q_cooldown_halved",
        True,
        label="Fury of the Sands halves Siphoning Strike's cooldown "
        "(effective while R is ranked)",
        rotation={"role": "irrelevant", "slot": "Q"},
    ),
    int_option(
        "q_stacks",
        0,
        minimum=0,
        maximum=5000,
        label="Permanent Siphoning Strike stacks (each adds 1 bonus damage "
        "to Q; 3 per minion kill, 12 per champion kill)",
    ),
]

ASSUMPTIONS = [
    "Q (Siphoning Strike) bonus damage = the rank flat (40-120) + the "
    "q_stacks option total (100% of Siphoning Strike stacks); the "
    "permanent gain (+3 per kill, +12 for champions) is not modeled — "
    "the target never dies here, so the option IS the current stack "
    "state",
    "Q empowers the next basic attack (empowers_next_auto), so its "
    "casts are capped by the fight's auto count; with no auto stream it "
    "forces its own swing",
    "E (Spirit Fire) prices the initial hit + 10 sourced 0.5s zone "
    "ticks (E2 fix, unchanged from the reviewed packet)",
    "R (Fury of the Sands) prices all 30 sourced 0.5s ticks (E2 fix, "
    "unchanged); its bonus health/resistances are self-stats.  While "
    "R is active (ranked and r_q_cooldown_halved on, the default) "
    "Siphoning Strike's cooldown is halved — the cached R prose "
    "('Siphoning Strike's cooldown is halved') — and the module prices "
    "the whole fight inside R's 15s window, consistent with pricing "
    "all 30 ticks",
    "P (Soul Eater) lifesteal is a self-heal rule (HEALING_RULE_CHAMPIONS): "
    "12% / 18% / 24% (based on level; game-file breakpoints at 7/13) of the "
    "post-mitigation physical basic-attack/on-hit damage dealt; W (Wither) "
    "slow/cripple is a zero-damage row",
    "W (Wither) is CC-only (slow + attack-speed cripple) with no enemy "
    "damage formula in the pinned packet; it emits the sourced "
    "zero-damage row (MODULE_COVERAGE: no_damage, not out_of_scope). W "
    'is already a cast slot in this module (SLOTS["W"] = _wither).',
]

SLOTS = {
    "Q": _siphoning_strike,
    "W": _wither,
    "E": _spirit_fire,
    "R": _fury_of_the_sands,
    "P": _soul_eater,
}

# Cached kit review.  Nothing Nasus damages with applies control: Q only
# empowers a basic attack to "deal bonus physical damage", E's fire deals
# magic damage and "inflict[s] them with armor reduction" (a resistance
# shred, not a control class), and R "deals magic damage every 0.5 seconds
# to nearby enemies" while buffing his own stats.  W is absent rather than
# "none" — Wither is the kit's one control ("slowing them by 35% and
# crippling them"), but it deals no damage, so no event of its own could
# carry an answer.  P (lifesteal) likewise damages nothing.
MODULE_CC = {"Q": "none", "E": "none", "R": "none"}

parse_abilities = build_parser(SLOTS, "Nasus", cc_kinds=MODULE_CC)

# P emits a row that prices no enemy damage; what the engine prices for
# the slot is Soul Eater's lifesteal, authored by the healing rule below
# (48.6 over a level-18 itemless timed fight with autos).  W is a cast
# slot emitting the pinned packet's sourced zero-damage row: no_damage,
# not a gap — only its slow/cripple magnitude stays unpriced.
MODULE_COVERAGE = coverage(no_damage="W")
COVERAGE_CHANNELS = {"P": ("self_healing_rule",)}


# Soul Eater is level-gated lifesteal, not an ability packet: "Nasus has
# 12% / 18% / 24% (based on level) life steal" against the physical
# damage his attacks and on-hits deal, so the rule pays per damaging hit
# rather than per cast.
_SOUL_EATER_BREAKPOINTS = ((13, 0.24), (7, 0.18), (1, 0.12))


# pylint: disable=too-many-arguments,too-many-positional-arguments
def derive_self_healing(
    champion_data: dict[str, Any],
    champion_stats: dict[str, float],
    ability_damages: dict[str, dict[str, Any]],
    damage_events: list[dict[str, Any]],
    cast_timeline: list[dict[str, Any]] | None = None,
    fight_duration_seconds: float | None = None,
) -> list[dict[str, Any]]:
    """Price Soul Eater's lifesteal off every physical basic-attack hit.

    The empowered swing counts.  Siphoning Strike does not replace a basic
    attack, it rides one ("Nasus's next basic attack ... deals bonus
    physical damage"), so the engine reattributes that swing to the Q row
    and publishes no ``auto_attacks`` row for it.  A rule reading only
    ``auto_attacks`` therefore pays nothing at all once R halves Q's
    cooldown and every swing is empowered.  Q rows and ``auto_attacks``
    rows partition the swings, so reading both is exactly one payment per
    swing, never two.
    """
    del champion_data, cast_timeline, fight_duration_seconds
    healing: list[dict[str, Any]] = []
    level = max(1, int(champion_stat(champion_stats, "level")))
    ratio = next(
        share for breakpoint, share in _SOUL_EATER_BREAKPOINTS if level >= breakpoint
    )
    empowered = bool(ability_damages.get("Q", {}).get("empowers_next_auto"))

    def is_swing(source: str) -> bool:
        if source == "auto_attacks" or source.startswith("on_hit_"):
            return True
        return empowered and source == "Q"

    for payment in payments(HealAnchor.DAMAGING_HIT, is_swing, damage_events):
        event = payment.event
        if event.get("damage_type") != "physical":
            continue
        amount = max(0.0, float(event.get("damage", 0.0))) * ratio
        heal_from_damage(healing, event, amount, "Soul Eater")
    return healing


SELF_HEALING_RULE = self_healing_rule("Nasus")(derive_self_healing)

SOURCES = load_champion_sources("Nasus")
