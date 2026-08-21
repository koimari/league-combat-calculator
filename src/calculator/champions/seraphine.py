"""Seraphine — CP10.7 full-entry-reviewed packet module.

E8d ally-support: W (Surround Sound) shields the caster and every selected
teammate (Shield Strength 60-140 + 20% AP; scope self_and_all_teammates).
The event is authored by the engine's ally-support scanner from cached
leveling at the W cast time; the module declares W in SLOTS so the fight
rotation casts it.  W's conditional pulse heal ("% of target's missing
health") uses a live missing-health formula and the caster's shield state.

P1 addition over the reviewed packet:
- Q (High Note) prices the missing-health amplifier: "Against champions
  and monsters, the damage is increased by 0% : 75% (based on target's
  missing health)" (cached Q description, second effect).  The base row
  "Magic Damage" (60-160 + 40% AP) is the flat part; a second
  hp-scaled part adds 0.75 x base x missing-health-ratio, so at full
  missing health the total equals the cached "Maximum Enhanced Damage"
  row (105-280 + 70% AP = 1.75 x base).  The engine evaluates the
  hp-scaled part at the cast with the target's live missing health —
  deterministic given the fight's health walk (Akshan R precedent).
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import ONHIT, SlotCtx
from .packet_module import build_packet_module
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    on_hit_entry,
    with_control,
)

PACKET_SHA256 = "4814ec27868dfc6c584834af7a9e7e17d4febc980aa3532143466c34cf7b995b"


# HARDCODED: verify on patch updates — the 0%:75% missing-health amplifier
# is prose in the cached Q second effect ("Against champions and monsters,
# the damage is increased by 0% : 75% (based on target's missing health)");
# it is cross-checked by the cached "Maximum Enhanced Damage" row
# (105-280 + 70% AP == 1.75 x the base row at every rank).
_Q_MISSING_HEALTH_MAX_BONUS = 0.75

# Notes "stack up to 4 times on each unit" and every ability cast grants
# one, so a full Q/W/E/R rotation puts the cap on Seraphine — the default.
_NOTE_CAP = 4


def _stage_presence(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: the empowered attack fires every active Note at the target."""
    ability = ctx.ability()
    if ability is None:
        return None
    per_note = extract_named(
        ability, "Bonus Magic Damage", ctx.level, ctx.stats, ctx.target, level=ctx.level
    )
    if per_note <= 0:
        return None
    notes = min(max(0, int(ctx.option("p_notes"))), _NOTE_CAP)
    entry = on_hit_entry(
        ability.get("name", "Stage Presence"), per_note * notes, "magic"
    )
    # One empowered attack fires every Note it holds; the next attack has
    # none until her abilities grant more.
    entry["on_hit"]["max_procs"] = 1 if notes else 0
    entry["detail"] = (
        f"{notes} Note(s) of {per_note:.2f} bonus magic damage each "
        "(4 : 27.47 based on level + 4% AP) on one empowered attack; Notes "
        "from allies (reduced by 75%) and Echo's free recast are unpriced"
    )
    return entry


_stage_presence.phase = ONHIT


def _high_note(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: flat base + 0%:75% missing-health amplifier (hp-scaled part)."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    base = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    maximum = extract_named(
        ability, "Maximum Enhanced Damage", rank, ctx.stats, ctx.target
    )
    entry = damage_entry(
        ability.get("name", "High Note"),
        rank,
        extract_cooldown(ability, rank),
        base,
        "magic",
    )
    entry["parts"] = (
        # Both the flat base and the missing-health amplifier land at the
        # cast boundary: authored time_offset 0.0 upgrades their events from
        # cast_boundary to hit precision so the coverage classifier certifies
        # the row instead of downgrading it coarse (Viego R pattern).
        DamagePart("magic", base, time_offset=0.0),
        DamagePart(
            "magic",
            hp_scaled_damage=lambda missing, base=base: base
            * _Q_MISSING_HEALTH_MAX_BONUS
            * max(0.0, min(1.0, missing)),
            time_offset=0.0,
        ),
    )
    entry["detail"] = (
        f"flat {base:g} + up to {_Q_MISSING_HEALTH_MAX_BONUS * 100:g}% of "
        f"base ({maximum:g} at full missing health, the cached Maximum "
        "Enhanced Damage row) scaled by the target's live missing-health "
        "ratio"
    )
    entry["event_order_certified"] = "single_hit"
    return entry


# Reviewed crowd control, read from the cached kit: Q (High Note) "deals
# magic damage to enemies within the area" and applies nothing else; E
# (Beat Drop) "slows them by 99%" (its root and stun are conditional on
# the target already being slowed / immobilized, which the duel model
# does not establish); R (Encore) "deals magic damage to enemies hit,
# charms them ... and slows them by 40%" — the charm is the control the
# damaged target takes.  W and P emit no damage event, so they carry no
# reviewable control.
MODULE_CC = {"Q": "none", "E": "slow", "R": "charm"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Seraphine",
    PACKET_SHA256,
    single_hit_slots=frozenset({"E", "R"}),
    slot_parsers={
        "Q": _high_note,
        "P": _stage_presence,
    },
    # The kinds above are the reviewed answer; these wrappers read each
    # one's sourced duration off the packet ("Disable Duration" is the
    # window E's 99% slow and R's charm both last).
    slot_wrappers={
        "E": lambda parser: with_control(
            parser, kind="slow", duration_attr="Disable Duration"
        ),
        "R": lambda parser: with_control(
            parser, kind="charm", duration_attr="Disable Duration"
        ),
    },
    cc_kinds=MODULE_CC,
)

OPTIONS = list(OPTIONS) + [
    {
        "key": "p_notes",
        "type": "int",
        "default": _NOTE_CAP,
        "min": 0,
        "max": _NOTE_CAP,
        "label": "Notes on the empowered attack",
    },
    {
        "key": "w_already_shielded",
        "type": "bool",
        "default": False,
        "label": "W caster already has a shield for the first pulse",
    },
]

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "W (Surround Sound) pulses its sourced missing-health heal after 2.5 "
    "seconds when Seraphine has a shield at cast time; the first cast can "
    "use the explicit w_already_shielded option",
    "Q (High Note) prices the missing-health amplifier: base (60-160 + "
    "40% AP) plus 0.75 x base x the target's live missing-health ratio "
    "(0%:75% based on missing health; equals the cached Maximum Enhanced "
    "Damage row at full missing health)",
    "P (Stage Presence) prices the empowered attack's Notes: the sourced "
    "per-Note row (4 : 27.47 based on level + 4% AP) times the selected "
    "Note count (default 4, the cap a full rotation reaches); Notes granted "
    "by allies (reduced by 75%) and Echo's free recast are not priced.",
]
