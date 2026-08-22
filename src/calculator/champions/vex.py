"""Vex — CP10.9 full-entry-reviewed packet module, plus the E8c W shield and
the P1 Gloom detonation.

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

from typing import Any

from .engine import ONHIT, SlotCtx
from .packet_module import build_packet_module
from .slotlib import attach_self_shield, extract_named, on_hit_entry
from .inputs import int_option

PACKET_SHA256 = "02fdfcd1fd65f629f446626879f993ab3308ec7eefb4e974ab8f4a026f43dd15"


# HARDCODED: verify on patch updates — Personal Space's shield duration is
# prose in the cached ability description ("granting herself a shield for
# 2.5 seconds"); the leveling row (data/champions.json, W "Shield
# Strength": 50/75/100/125/150 + 75% AP) is read live below.
_PERSONAL_SPACE_SHIELD_DURATION_SECONDS = 2.5


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
# Q, E and R are read and left undeclared: their packet rows carry neither a
# sourced hit time nor a single-landing certification, so the ledger cannot
# carry a kind for them and refuses one rather than accept a no-op.
MODULE_CC = {"P": "none", "W": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Vex",
    PACKET_SHA256,
    single_hit_slots=frozenset({"W"}),
    slot_parsers={
        "P": _gloom_detonation,
    },
    slot_wrappers={
        "W": _personal_space,
    },
    cc_kinds=MODULE_CC,
)

OPTIONS = list(OPTIONS) + [
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

ASSUMPTIONS = list(ASSUMPTIONS) + [
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
