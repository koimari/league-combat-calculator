"""Sett — Pit Grit right-punch combo system.

Stack mechanics modeled (E3):
- P (Pit Grit): Sett's basic attacks alternate between a Left Punch and
  a Right Punch on-attack.  The Right Punch is the combo's empowered
  hit: it gains 50 bonus range, attacks at 8x the Left Punch's attack
  speed, and deals bonus physical damage equal to 5 : 100 (based on
  level) (+ 55% bonus AD).  ``p_right_punches`` is the explicit count
  of Right Punches in the fight window (each auto stream alternates, so
  roughly half of the autos are Right Punches); 0 prices the state row.

Q (Knuckle Down), W (Haymaker), E (Facebreaker) and R (The Show
Stopper) keep the reviewed CP10.7 packet pricing. All numeric values
are read from the champion JSON data; the 55% bonus AD ratio is wiki
prose (the leveling array holds only the per-level flat value).
"""

from __future__ import annotations

from typing import Any

import re

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .module_helpers import no_damage
from .packet_module import build_packet_module
from .source_receipts import load_champion_sources
from .slotlib import (
    attach_self_shield,
    damage_entry,
    extract_cooldown,
    extract_named,
    find_named_leveling,
    simple_damage,
)

# HARDCODED: verify on patch updates — wiki prose, not in the JSON.
# Haymaker's shield equals the expended Grit ("grant himself a shield ...
# equal to the expended Grit for 3 seconds"); the center-line damage is
# true ("those hit in a line in the middle are dealt true damage
# instead"); the grit damage ratio is the cached "Damage" row's unit
# string ("% (+ 25% per 100 bonus AD) of expended Grit").
_W_SHIELD_DURATION_SECONDS = 3.0
_W_GRIT_OPTION = "w_grit"
_Q_TOTAL_ATTR = "Total Bonus Physical Damage"

PACKET_SHA256 = "122d6d40606b4b120f4fd94cc1ba7fa968cbda67af830338296f41fe94ca3820"

_BATCH_PARSE, _BATCH_SLOTS, _BATCH_ASSUMPTIONS, _BATCH_SOURCES, _BATCH_OPTIONS = (
    build_packet_module(
        "Sett",
        PACKET_SHA256,
        # Facebreaker and The Show Stopper each land one blow on a target
        # ("dealing physical damage and slowing them"; "Enemies within the
        # epicenter take physical damage"), so their single authored part
        # is a hit the ledger can time — which is what carries their
        # MODULE_CC answer to the control-armed readers.
        single_hit_slots=frozenset({"E"}),
        slot_parsers={
            "R": simple_damage(
                attr="Physical Damage",
                dmg_type="physical",
                ranks="rank",
                source=("R", 0),
                event_order_certified="single_hit",
            )
        },
    )
)
PACKET_SPEC = _BATCH_SLOTS.packet_spec

# HARDCODED: verify on patch updates — wiki prose, not in the JSON.
# Pit Grit's Right Punch: "deal 5 : 100 (based on level) (+ 55% bonus
# AD) bonus physical damage"; the leveling array holds the flat part.
_RIGHT_PUNCH_BONUS_AD_RATIO = 0.55


def _pit_grit(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: alternating-punch combo — Right Punch bonus physical damage."""
    ability = ctx.ability()
    if ability is None:
        return None
    punches = min(max(int(ctx.option("p_right_punches")), 0), 30)
    if punches <= 0:
        return no_damage(
            ctx,
            name=ability.get("name", "Pit Grit"),
            reason=(
                "Heavy Hands alternates Left and Right punches; the Right "
                "Punch deals the sourced bonus physical damage — set "
                "p_right_punches to price it (0 = no Right Punches)."
            ),
        )
    flat = extract_named(ability, "Per-Level Scaling", ctx.level)
    bonus_ad = float(ctx.stat("bonus_attack_damage"))
    per_punch = flat + _RIGHT_PUNCH_BONUS_AD_RATIO * bonus_ad
    total = per_punch * punches
    return {
        "name": ability.get("name", "Pit Grit"),
        "damage_type": "physical",
        "total_raw": total,
        "parts": (DamagePart("physical", per_punch, basic_damage=True),),
        "proc_count": punches,
        "detail": (
            f"{punches} Right Punch(es) x {per_punch:.2f} bonus physical "
            f"damage (5 : 100 by level + 55% bonus AD); the 8x Right "
            "Punch attack speed is state."
        ),
    }


def _knuckle_down(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: BOTH empowered basic attacks (the Total Bonus Physical Damage row).

    Knuckle Down empowers Sett's next two basic attacks; the reviewed
    packet read the single-attack "Bonus Physical Damage" row once.  The
    cached "Total Bonus Physical Damage" row (20-100 by rank) is exactly
    double.  The %max-HP term's unit ("% (+ 2 / 3 / 4 / 5 / 6% per 100
    AD) of target's maximum health") is not a generic scaling unit: the
    base percentage is the cached value (2% for the total row) and the
    per-100-AD percentage is the rank-scaled value embedded in the unit
    string (2/3/4/5/6% by rank), both priced against the target's max
    health and Sett's total AD.
    """
    ability = ctx.ability("Q")
    if ability is None:
        return None
    rank = ctx.rank_for("Q")
    if rank < 1:
        return None
    leveling = find_named_leveling(ability, _Q_TOTAL_ATTR)
    if leveling is None:
        raise ValueError("Sett Q Total Bonus Physical Damage row is unavailable")
    total = 0.0
    for modifier in leveling.get("modifiers", []):
        values = modifier.get("values", [])
        units = modifier.get("units", [])
        if not values:
            continue
        index = min(max(rank - 1, 0), len(values) - 1)
        value = float(values[index])
        unit = units[index] if index < len(units) else ""
        if not unit or not str(unit).strip():
            total += value
            continue
        # "% (+ 2 / 3 / 4 / 5 / 6% per 100 AD) of target's maximum health":
        # the base percentage is the cached value; the per-100-AD
        # percentage is the rank-scaled value embedded in the unit string
        # ("2 / 3 / 4 / 5 / 6" precedes the "per 100 AD" literal, so the
        # rank-1 index picks the rank's percentage).
        per_100_ad = 0.0
        if "per 100 AD" in str(unit):
            values_in_unit = re.findall(r"\d+(?:\.\d+)?", str(unit))
            if len(values_in_unit) >= 5:
                per_100_ad = float(values_in_unit[index])
        total += (
            value / 100.0 + per_100_ad / 100.0 * ctx.stat("attack_damage") / 100.0
        ) * float(ctx.target_stat("target_max_health"))
    entry = damage_entry(
        ability.get("name", "Knuckle Down"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "physical",
    )
    entry["parts"] = (DamagePart("physical", total),)
    entry["detail"] = (
        "both empowered attacks priced from the Total Bonus Physical "
        "Damage row (20-100 by rank + %max-HP + % per 100 AD of target "
        "max health)"
    )
    return entry


def _haymaker(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: the center-line TRUE damage plus the grit shield.

    Haymaker consumes all stored Grit: the blast deals the cached "Damage"
    row's flat base (80-160 by rank) plus 25% (+ 25% per 100 bonus AD) of
    the expended Grit, and those in the center line take TRUE damage
    (the row's damageType is OTHER — the center-line branch is the one
    priced, the outer physical ring is state).  The cast also grants Sett
    a shield equal to the expended Grit for 3 seconds (wiki prose), so
    ``w_grit`` is the explicit expended-Grit state that prices both the
    grit damage term and the self-shield.
    """
    ability = ctx.ability("W")
    if ability is None:
        return None
    rank = ctx.rank_for("W")
    if rank < 1:
        return None
    leveling = find_named_leveling(ability, "Damage")
    if leveling is None:
        raise ValueError("Sett W Damage leveling row is unavailable")
    flat = 0.0
    grit_ratio = 0.0
    for modifier in leveling.get("modifiers", []):
        values = modifier.get("values", [])
        units = modifier.get("units", [])
        if not values:
            continue
        index = min(max(rank - 1, 0), len(values) - 1)
        value = float(values[index])
        unit = units[index] if index < len(units) else ""
        if not unit or not str(unit).strip():
            flat += value
            continue
        # "% (+ 25% per 100 bonus AD) of expended Grit" — the value IS the
        # base percentage (25), and the unit embeds the per-100-bonus-AD
        # percentage (25).
        if "of expended Grit" in str(unit):
            grit_ratio = (
                value / 100.0 + 0.25 * float(ctx.stat("bonus_attack_damage")) / 100.0
            )
    grit = max(0.0, float(ctx.option(_W_GRIT_OPTION) or 0))
    entry = damage_entry(
        ability.get("name", "Haymaker"),
        rank,
        extract_cooldown(ability, rank),
        flat + grit_ratio * grit,
        "true",
    )
    entry["parts"] = (DamagePart("true", flat + grit_ratio * grit),)
    # One blast, one blow per target ("he unleashes a massive blast ...
    # dealing physical damage to enemies hit; those hit in a line in the
    # middle are dealt true damage instead"), so the single part is a hit
    # the ledger can time.
    entry["event_order_certified"] = "single_hit"
    if grit > 0.0:
        return attach_self_shield(
            entry,
            amount=grit,
            duration=_W_SHIELD_DURATION_SECONDS,
            source="Haymaker",
            detail=(
                f"center-line true damage {flat:g} + "
                f"{grit_ratio * 100:g}% of expended Grit ({grit:g}) = "
                f"{flat + grit_ratio * grit:g}; the expended Grit also "
                f"shields Sett for {grit:g} for "
                f"{_W_SHIELD_DURATION_SECONDS:g}s"
            ),
        )
    entry["detail"] = (
        f"center-line true damage {flat:g} (flat only); the grit term "
        "(25% + 25% per 100 bonus AD of expended Grit) and the equal-"
        "grit shield are priced via the w_grit option (0 = no Grit)"
    )
    return entry


SLOTS = {
    "P": _pit_grit,
    "Q": _knuckle_down,
    "W": _haymaker,
    "E": _BATCH_SLOTS["E"],
    "R": _BATCH_SLOTS["R"],
}

# Reviewed crowd control, read from the cached kit.  W (Haymaker) is a
# blast with no control clause.  E (Facebreaker) "pulls in enemies at his
# front and back ... dealing physical damage and slowing them by 70%" —
# the pull is the immobilizing half and the one a control-armed reader
# needs; the two-sided stun is conditional on hitting both sides.  R (The
# Show Stopper) "suppresses and reveals the target enemy champion" it
# then slams.  Q is deliberately absent: its row is BOTH empowered basic
# attacks summed at the cast, so no part of it is a hit the ledger can
# time, and an unreachable declaration reviews nothing.
MODULE_CC = {"W": "none", "E": "pull", "R": "suppression"}

parse_abilities = build_parser(SLOTS, "Sett", cc_kinds=MODULE_CC)

OPTIONS = [
    {
        "key": "p_right_punches",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 30,
        "label": "Right Punch count (Pit Grit combo)",
    },
    {
        "key": "w_grit",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 3000,
        "label": "Expended Grit (Haymaker damage + shield)",
    },
]

ASSUMPTIONS = [
    "Pit Grit's combo alternates Left and Right punches on-attack; the "
    "Right Punch deals the sourced bonus physical damage (5 : 100 by "
    "level + 55% bonus AD) and is priced per p_right_punches",
    "The fight model does not auto-derive Right Punch count from the "
    "auto stream (each attack alternates); p_right_punches is the "
    "explicit pre-stack state",
    "The Right Punch's 8x attack speed and 50 bonus range are state",
    "Q (Knuckle Down) prices BOTH empowered attacks from the cached "
    "'Total Bonus Physical Damage' row (20-100 by rank); the %max-HP "
    "term uses the cached base percentage plus the rank-scaled "
    "per-100-AD percentage embedded in the row's unit string",
    "W (Haymaker) prices the center-line TRUE damage: the cached "
    "'Damage' row flat (80-160 by rank) plus 25% (+ 25% per 100 bonus "
    "AD) of the expended Grit (w_grit option, 0 = flat only); the "
    "expended Grit also grants Sett an equal shield for 3s "
    "(self_shield_events). The outer physical ring is state",
    "E/R damage keep the reviewed CP10.7 packet pricing",
]

SOURCES = load_champion_sources("Sett")
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"P", "Q", "W", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}
