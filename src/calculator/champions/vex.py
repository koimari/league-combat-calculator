"""Vex — CP10.9 full-entry-reviewed packet module, plus the E8c W shield,
the P1 Gloom detonation, and the ER2 R split.

ER2 addition over the reviewed packet:
- R (Shadow Surge) is two hits, not one: the Shadow's own "Magic Damage"
  and the recast dash's, which the cached "Total Magic Damage" row sums
  exactly at every rank.  ``_shadow_surge`` reads both, checks the sum
  against that row, and lands them at their own instants.

E8c addition over the reviewed packet:
- W (Personal Space) deals its magic damage AND shields Vex herself for
  2.5 seconds.  The shield rides the W damage event as a
  ``self_shield_events`` payload (the Eclipse item shape): the shared
  ledger grants a timed self-shield at the event timestamp, so the W
  cast both deals damage and absorbs the sourced amount.  The generic
  ally-support scanner is told to defer this slot (see
  ``support_effects._MODULE_AUTHORED_SHIELD_SLOTS``) — its description
  marker misses "granting herself" and would mis-target the self-only
  shield at a teammate.

P1 addition over the reviewed packet:
- P (Doom 'n Gloom) Gloom detonation: "Nearby enemy champions and
  monsters that dash or blink will be marked with Gloom for 6 seconds.
  Vex's next basic attack ... against an enemy with Gloom will detonate
  the mark.  Gloom's detonation deals 40 : 162.94 (based on level)
  (+ 25% AP) bonus magic damage" (cached P description; the leveling row
  "Bonus Magic Damage" carries the per-level array and AP ratio).  The
  mark requires the ENEMY to dash/blink, so the fight is deterministic
  through the ``p_gloom_detonations`` option: each priced detonation
  rides one of the fight's basic attacks as an on-hit rider capped at
  the option's count (the engine's ``max_procs`` cap, Bard-meep
  pattern).  The Doom fear / knock-down (crowd control) and the
  non-champion reduced damage are state and out of scope.
"""

import math
from typing import Any

from ..ability_spec import DamagePart
from ..binary_roots import data_value, spell_object
from .engine import ONHIT, SlotCtx
from .inputs import int_option
from .packet_module import build_packet_module
from .slotlib import (
    attach_self_shield,
    extract_description_duration,
    extract_named,
    find_named_leveling,
    on_hit_entry,
    sum_modifiers,
)

PACKET_SHA256 = "02fdfcd1fd65f629f446626879f993ab3308ec7eefb4e974ab8f4a026f43dd15"


# HARDCODED: verify on patch updates — Personal Space's shield duration is
# prose in the cached ability description ("granting herself a shield for
# 2.5 seconds"); the leveling row (data/champions.json, W "Shield
# Strength": 50/75/100/125/150 + 75% AP) is read live below.
_PERSONAL_SPACE_SHIELD_DURATION_SECONDS = data_value(
    spell_object("Vex", "VexW"), "ShieldDuration"
)


def _personal_space(packet_w):
    """W: the reviewed magic hit plus the sourced self-shield payload."""

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        entry = packet_w(ctx)
        rank = int(entry.get("rank", 0) or 0) if entry is not None else 0
        if entry is None or rank < 1:
            return entry
        shield = extract_named(
            ctx.ability(), "Shield Strength", rank, ctx.stats, ctx.target
        )
        return attach_self_shield(
            entry,
            amount=shield,
            duration=_PERSONAL_SPACE_SHIELD_DURATION_SECONDS,
            source=entry.get("name", "Personal Space"),
            detail=(
                f"W also shields Vex for {shield:g} for "
                f"{_PERSONAL_SPACE_SHIELD_DURATION_SECONDS:g}s (self)"
            ),
        )

    return parse


# The cached R effect whose description times the mark the recast lives
# in ("mark them for 4 seconds"), read live by ``_shadow_surge``.
_R_MARK_EFFECT_INDEX = 1

# HARDCODED: verify on patch updates — the recast's instant is the
# player's, anywhere inside that mark, so the cache times the window and
# not the hit.  The authored cadence is Lee Sin Q's (``lee_sin.py``): the
# 0.25-second cast the game file gives VexR plus the recast reaction.
# VexR2 itself has spellCastTime 0.
_R_RECAST_DELAY_SECONDS = 0.5


def _shadow_surge(packet_r):
    """R: the Shadow's hit, then the recast consume it marked a target for.

    The reviewed packet prices the cached "Total Magic Damage" row, which
    is exactly the "Magic Damage" of the Shadow (effect 0) plus the
    "Magic Damage" of the recast (effect 2) at every rank.  One row cannot
    carry two landing times, so the two are read separately, checked
    against the total, and land at their own instants.
    """

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        entry = packet_r(ctx)
        ranked = ctx.ranked("R", 0)
        if entry is None or ranked is None:
            return entry
        ability, rank = ranked
        window = extract_description_duration(ability, _R_MARK_EFFECT_INDEX)
        if window is None or window < _R_RECAST_DELAY_SECONDS:
            raise ValueError(
                "Vex R: the cached Shadow Surge effect "
                f"{_R_MARK_EFFECT_INDEX} states no mark window holding the "
                f"{_R_RECAST_DELAY_SECONDS:g}s recast, so the consume has no "
                "sourced instant"
            )
        surge = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
        recast_row = find_named_leveling(ability, "Magic Damage", 1)
        recast = (
            sum_modifiers(recast_row, rank, ctx.stats, ctx.target)
            if recast_row is not None
            else 0.0
        )
        total = extract_named(
            ability, "Total Magic Damage", rank, ctx.stats, ctx.target
        )
        if not math.isclose(surge + recast, total, rel_tol=1e-9, abs_tol=1e-6):
            raise ValueError(
                f"Vex R: the Shadow's {surge:g} and the recast's {recast:g} "
                f"do not compose the cached Total Magic Damage {total:g}"
            )
        entry["parts"] = (
            DamagePart("magic", surge, time_offset=0.0),
            DamagePart("magic", recast, time_offset=_R_RECAST_DELAY_SECONDS),
        )
        entry["detail"] = (
            f"Shadow's hit {surge:g}, then the recast consume {recast:g} "
            f"{_R_RECAST_DELAY_SECONDS:g}s later, inside the cached "
            f"{window:g}s mark"
        )
        return entry

    return parse


def _gloom_detonation(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: Gloom mark detonation on the next basic attack (empowered auto).

    "Vex's next basic attack ... against an enemy with Gloom will detonate
    the mark ... deals 40 : 162.94 (based on level) (+ 25% AP) bonus magic
    damage" — the bonus rides one auto per detonation; the count is the
    user-controlled ``p_gloom_detonations`` (default 1: the fight opens
    with one dashing enemy whose mark Vex detonates).  The on-hit rider is
    capped by the engine's ``max_procs`` so autos beyond the count land
    plain (Bard-meep pattern).
    """
    ability = ctx.ability()
    if ability is None:
        return None
    detonations = max(0, int(ctx.option("p_gloom_detonations")))
    if detonations <= 0:
        return None
    per_hit = extract_named(
        ability, "Bonus Magic Damage", ctx.level, ctx.stats, ctx.target
    )
    if per_hit <= 0:
        return None
    entry = on_hit_entry(
        "Doom 'n Gloom (Gloom Detonation)",
        per_hit,
        "magic",
    )
    entry["on_hit"]["max_procs"] = detonations
    entry["detail"] = (
        f"{detonations} Gloom detonation(s) of {per_hit:g} bonus magic "
        "damage (40:162.94 by level + 25% AP), each riding one basic "
        "attack against the marked enemy"
    )
    return entry


_gloom_detonation.phase = ONHIT


# Reviewed crowd control, read from the cached kit.  E's shadow explodes
# "dealing magic damage to enemies hit and slowing them for 2 seconds".
# Nothing else controls: Q's wave "deals magic damage to enemies hit", W
# "deal[s] magic damage to nearby enemies and grant[s] herself a shield",
# R marks and reveals its target before the recast damage, and P's priced
# row is the Gloom detonation's "bonus magic damage".  Doom's fear and
# knock-down empower a basic ability on its own cooldown — fight state this
# module does not price (see ASSUMPTIONS), so it is not any slot's answer.
#
# Q and E each land once, at the cast, so they certify and answer.  Mistral
# Bolt "deals magic damage to enemies hit" and nothing else; Looming
# Darkness explodes "dealing magic damage to enemies hit and slowing them
# for 2 seconds".  The slow's magnitude is cached (the "Slow" row,
# 30-50%) but its 2-second window is prose only, so the marker carries the
# kind with no interval -- which is what a zero cc_duration states.
#
# R answers too, now that its row lands its two hits at their own instants
# rather than as one "Total Magic Damage" lump: the Shadow "deals magic
# damage to enemies hit", the mark only reveals, and the recast dash's
# displacement immunity is Vex's own.
MODULE_CC = {"P": "none", "Q": "none", "W": "none", "E": "slow", "R": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Vex",
    PACKET_SHA256,
    single_hit_slots=frozenset({"E", "Q", "W"}),
    slot_parsers={
        "P": _gloom_detonation,
    },
    slot_wrappers={
        "R": _shadow_surge,
        "W": _personal_space,
    },
    cc_kinds=MODULE_CC,
)

OPTIONS = [
    *list(OPTIONS),
    int_option(
        "p_gloom_detonations",
        1,
        minimum=0,
        maximum=20,
        label="Gloom mark detonations (each: next basic attack deals the "
        "sourced bonus magic damage; marks require the enemy to "
        "dash/blink)",
    ),
]

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "R (Shadow Surge) always lands both hits: the Shadow's cached Magic "
    "Damage at the cast and the recast consume 0.5s later. The player "
    "picks that instant anywhere inside the cached 4-second mark, so the "
    "0.5s cadence is authored (Lee Sin Q's) rather than cached; the two "
    "hits sum to the cached Total Magic Damage row exactly, and the "
    "parser refuses the slot if they ever stop doing so.",
    "W (Personal Space) grants Vex the sourced shield (flat + 75% AP) for "
    "2.5s at the cast; the shield absorbs damage before health in the "
    "participant ledger.",
    "P (Doom 'n Gloom) Gloom detonations are priced as on-hit riders: "
    "p_gloom_detonations basic attacks each deal the sourced bonus magic "
    "damage (40:162.94 by level + 25% AP, cached 'Bonus Magic Damage' "
    "row), capped by the engine's max_procs.  The mark requires a "
    "dashing/blinking enemy, so the count is the user-controlled fight "
    "state; the Doom fear/knock-down (CC) and the reduced non-champion "
    "damage are state/out of scope.",
]
