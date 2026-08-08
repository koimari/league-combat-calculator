"""Blitzcrank — slot map for the archetype engine.

Why each slot is non-generic:
- W (Overdrive) is a TIMED attack-speed steroid: 30-70% bonus AS for
  the buff's 5-second duration only. ``stat_buff`` can only express a
  full-fight buff, so a custom BUFF-phase fn time-averages the bonus
  over the fight window read from the reserved
  ``fight_duration_seconds`` option (10s fight -> half the bonus; the
  fight engine's auto count then matches "buffed autos for 5s + base
  autos after"). Absent option (one-rotation / direct parse) -> the
  per-cast model: full bonus. Zero damage, like Aatrox R.
- E (Power Fist) has NO leveling data in the JSON at all — the
  100% total AD (+ 25% AP) bonus is hand-authored below. It rides the
  next basic attack (``empowers_next_auto``, the Vayne Q pattern: the
  empowered auto is one of the fight's autos, which already applies
  item on-hits and advances on-attack counters), and the bonus crits
  at full effectiveness per the wiki.
- R (Static Field) has two "Magic Damage" leveling entries: the
  passive lightning (skipped by design — casting R disables it, and
  realistic bolt counts are negligible) and the active burst.
  ``extract_named`` would return the passive first, so a custom fn
  selects the active by the ABSENCE of the passive's '% maximum mana'
  modifier (robust to effect reordering on data re-pulls).
- Q (Rocket Grab) is a clean generic read, kept explicit here.
- P (Mana Barrier) is a defensive shield only — absent from the map.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import BUFF, SlotCtx, build_parser
from .slotlib import (
    attach_self_shield,
    damage_entry,
    extract_cooldown,
    extract_value,
    simple_damage,
    sum_modifiers,
)

# HARDCODED: verify on patch updates — wiki prose, not in the JSON.
# https://wiki.leagueoflegends.com/en-us/Blitzcrank
# E (Power Fist) has zero leveling data: the next basic attack deals
# 100% total AD (+ 25% AP) bonus physical damage, rank-independent
# (only the cooldown scales). W's buff duration is prose too.
POWER_FIST_TOTAL_AD_RATIO = 1.0
POWER_FIST_AP_RATIO = 0.25
OVERDRIVE_DURATION_SECONDS = 5.0
# HARDCODED: verify on patch updates — Mana Barrier's shield amount and
# duration are prose-only in the cached passive description (data/
# champions.json, Blitzcrank P): "when damaged to 30% maximum health,
# Blitzcrank generates a shield equal to 35% of maximum mana, lasting
# for up to 10 seconds", on the cached 90-second cooldown.  The 35% is
# the cached wiki value at the last data pull (patch 25.22).
MANA_BARRIER_SHIELD_RATIO = 0.35  # 35% of maximum mana
MANA_BARRIER_DURATION_SECONDS = 10.0


def _overdrive(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: bonus AS for the fight's first 5s, time-averaged over the window."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    bonus_as = extract_value(ability, "Bonus Attack Speed", rank)
    duration = ctx.options.get("fight_duration_seconds")
    if duration and duration > OVERDRIVE_DURATION_SECONDS:
        bonus_as *= OVERDRIVE_DURATION_SECONDS / duration

    entry = damage_entry(
        ability.get("name", "Overdrive"),
        rank,
        extract_cooldown(ability, rank),
        0.0,
        "magic",
    )
    entry["stat_buff"] = {"bonus_attack_speed": bonus_as}
    return entry


_overdrive.phase = BUFF


def _power_fist(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: hand-authored 100% AD + 25% AP bonus riding the next auto."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    bonus = POWER_FIST_TOTAL_AD_RATIO * ctx.stats.get(
        "attack_damage", 0.0
    ) + POWER_FIST_AP_RATIO * ctx.stats.get("ability_power", 0.0)

    return {
        "name": ability.get("name", "Power Fist"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "physical",
        "total_raw": bonus,
        # "This damage is affected by critical strike modifiers" (wiki).
        "parts": (DamagePart("physical", bonus, crit_effectiveness=1.0),),
        # Damage lands only through the empowered basic attack: casts
        # are capped by the auto count; the attack reset costs no attack
        # time, so the auto stream (which already applies item on-hits
        # and readies/consumes spellblade) is unchanged.
        "empowers_next_auto": True,
    }


def _static_field(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: active burst only — the passive bolt entry is skipped by design."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    # Both R damage entries are named "Magic Damage"; only the skipped
    # passive carries a '% maximum mana' modifier.
    active = None
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute", "") != "Magic Damage":
                continue
            units = (
                unit
                for modifier in leveling.get("modifiers", [])
                for unit in modifier.get("units", [])
            )
            if any("maximum mana" in unit for unit in units):
                continue  # passive lightning — not modeled
            active = leveling
            break
        if active is not None:
            break

    total = (
        sum_modifiers(active, rank, ctx.stats, ctx.target)
        if active is not None
        else 0.0
    )
    return damage_entry(
        ability.get("name", "Static Field"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )


OPTIONS: list[dict[str, Any]] = []

ASSUMPTIONS = [
    "P (Mana Barrier) is modeled as a pre-fight granted shield: the "
    "cached passive (35% of maximum mana for up to 10s, 90s cooldown) "
    "rides the first Q cast's event so the ledger grants it before "
    "incoming damage. The in-game trigger (damage taken while below "
    "30% max health) is a documented boundary — the pre-fight grant "
    "approximates an always-ready barrier for the fight window",
    "W (Overdrive) attack speed (30-70%) is active for the first 5 "
    "seconds of the fight; fights of 5s or less have it up throughout. "
    "Movement speed and the post-buff slow are ignored",
    "E (Power Fist) fires once per cast on the next auto (attack "
    "reset), applies item on-hits, procs spellblade, and its "
    "100% AD + 25% AP bonus benefits from expected crit scaling",
    "R (Static Field) passive lightning is not modeled — casting R "
    "disables it and realistic bolt counts are small next to the "
    "active; only the active burst is counted",
]


def _rocket_grab(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: the clean magic hit carrying Mana Barrier's pre-fight shield.

    Mana Barrier is a defensive passive, so it has no cast of its own;
    the shield rides the first Q damage event (t=0 in one-rotation and
    timed fights) as a ``self_shield_events`` payload, which the shared
    ledger grants as a timed self-shield before incoming damage.
    """
    entry = _packet_q(ctx)
    rank = int(entry.get("rank", 0) or 0) if entry is not None else 0
    if entry is None or rank < 1:
        return entry
    shield = MANA_BARRIER_SHIELD_RATIO * ctx.stats.get("max_mana", 0.0)
    entry["event_order_certified"] = "single_hit"
    return attach_self_shield(
        entry,
        amount=shield,
        duration=MANA_BARRIER_DURATION_SECONDS,
        source="Mana Barrier",
        detail=(
            f"Q carries Mana Barrier's pre-fight shield: {shield:g} "
            f"({MANA_BARRIER_SHIELD_RATIO * 100:g}% of max mana) for up to "
            f"{MANA_BARRIER_DURATION_SECONDS:g}s; the 30%-health trigger "
            "boundary is documented in ASSUMPTIONS"
        ),
    )


SLOTS = {
    "W": _overdrive,
    "Q": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "E": _power_fist,
    "R": _static_field,
}

SLOTS = dict(SLOTS)
_packet_q = SLOTS["Q"]
SLOTS["Q"] = _rocket_grab
parse_abilities = build_parser(SLOTS, "Blitzcrank")


# Authoritative review metadata (issue #161).
SOURCES = [
    {
        "label": "Local League Wiki cache",
        "url": "https://wiki.leagueoflegends.com/en-us/Blitzcrank",
        "revision_id": 4047544,
        "revision_timestamp": "2026-07-29T20:05:52Z",
    }
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in SLOTS else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
