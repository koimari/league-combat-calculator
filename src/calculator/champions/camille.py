"""Camille — slot map for the archetype engine.

Why each slot is non-generic:
- Q (Precision Protocol) is TWO empowered basic attacks per cycle under
  one JSON entry (damageType OTHER_DAMAGE — the classifier cannot type
  it). Q1 rides the next auto (+20-40% total AD physical); Q2 is always
  modeled as the DELAYED recast: doubled bonus ("Increased Mixed
  Damage") with (36% + 4% per level, 100% from level 16) of the WHOLE
  attack — base swing, bonus, and the spellblade proc it consumes —
  converted to true damage. Neither Q attack can crit, so both entries
  author their own non-crit forced swing via ``empowers_next_auto
  {"swing_parts"}`` instead of the engine's default expected-crit swing.
- W (Tactical Sweep) adds the outer-cone sweet spot: (6-8% + 2.5% per
  100 bonus AD) of target MAX health — the "% per 100 bonus AD" unit
  means percent-of-max-health, which generic scaling would misread as
  flat damage. W's effect[2] holds monster-only values (excluded).
- E (Hookshot/Wall Dive) splits across two JSON entries: damage and the
  40-60% bonus-AS steroid live on E[1] (Wall Dive, cooldown None), the
  cooldown on E[0] (Hookshot). BUFF phase: the AS is modeled as active
  for the whole fight.
- R (The Hextech Ultimatum) deals NO upfront damage — each basic attack
  on the trapped target deals 4/6/8% of its CURRENT health as bonus
  magic damage while the zone lasts. Emitted as an ``on_hit`` payload
  with ``proc_window`` (zone duration): the fight engine procs it on
  the autos landing inside the window against decaying current health,
  and shows zero with no autos (one-rotation / autos off).
- P (Adaptive Defenses) is a defensive shield — absent from the map.

All numeric values are read from the champion JSON data.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import BUFF, SlotCtx, build_parser
from .slotlib import (
    attach_self_shield,
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
)


def _true_split_parts(
    amount: float,
    true_ratio: float,
    basic_damage: bool = False,
) -> tuple[DamagePart, ...]:
    """Split *amount* into a true part and a physical remainder.

    Q attacks cannot crit, so every part stays at the default
    ``crit_effectiveness=0``. Zero-sized portions are dropped.
    """
    parts = []
    if true_ratio > 0:
        parts.append(DamagePart("true", amount * true_ratio, basic_damage=basic_damage))
    if true_ratio < 1:
        parts.append(
            DamagePart(
                "physical", amount * (1.0 - true_ratio), basic_damage=basic_damage
            )
        )
    return tuple(parts)


def _q_true_ratio(ability: dict[str, Any], level: int) -> float:
    """Q2's true-damage conversion at a champion level (0..1).

    The JSON "Bonus True Damage" table has 16 per-level entries
    (36% + 4% x level, hitting 100% at level 16); levels 17-20 read the
    capped last entry.
    """
    return min(extract_value(ability, "Bonus True Damage", level), 100.0) / 100.0


def _precision_protocol(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q1: next basic attack deals +20-40% total AD physical, no crit."""
    ability = ctx.ability("Q")
    if ability is None:
        return None
    rank = ctx.rank_for("Q")
    if rank < 1:
        return None

    bonus = extract_named(ability, "Bonus Physical Damage", rank, ctx.stats, ctx.target)
    total_ad = ctx.stat("attack_damage")
    return {
        "name": ability.get("name", "Precision Protocol"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "physical",
        "total_raw": bonus,
        "parts": (DamagePart("physical", bonus),),
        # Rides the auto stream when one exists; with no autos the fight
        # engine appends these module-authored swing parts instead of
        # its default expected-crit swing (Q attacks cannot crit).
        "empowers_next_auto": {
            "swing_parts": (DamagePart("physical", total_ad, basic_damage=True),)
        },
    }


def _precision_protocol_recast(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q2 (always delayed): doubled bonus, whole attack true-converted."""
    ability = ctx.ability("Q")
    if ability is None:
        return None
    rank = ctx.rank_for("Q")
    if rank < 1:
        return None

    bonus = extract_named(
        ability, "Increased Mixed Damage", rank, ctx.stats, ctx.target
    )
    ratio = _q_true_ratio(ability, ctx.level)
    total_ad = ctx.stat("attack_damage")
    return {
        "name": f"{ability.get('name', 'Precision Protocol')} (Q2)",
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "true" if ratio >= 1.0 else "mixed",
        "total_raw": bonus,
        "parts": _true_split_parts(bonus, ratio),
        "empowers_next_auto": {
            "swing_parts": _true_split_parts(total_ad, ratio, basic_damage=True)
        },
        "recast_of": "Q",
        # The spellblade proc Q2 consumes is part of the attack and
        # converts with it (game-verified); other on-hit effects keep
        # their own damage types.
        "spellblade_true_ratio": ratio,
    }


def _tactical_sweep(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: inner cone physical + optional outer-cone % max HP sweet spot."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    total = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    if ctx.options.get("w_outer_cone", True):
        # Modifier 0: base % of target max health; modifier 1: extra %
        # per 100 bonus AD (of max health too — not a flat scaling).
        percent = extract_value(ability, "Outer Cone Additional Damage", rank, 0)
        percent += (
            extract_value(ability, "Outer Cone Additional Damage", rank, 1)
            * ctx.stat("bonus_attack_damage")
            / 100.0
        )
        total += percent / 100.0 * ctx.target_stat("target_max_health")

    return damage_entry(
        ability.get("name", "Tactical Sweep"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "physical",
    )


def _hookshot(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: Wall Dive damage + always-on bonus-AS steroid (cooldown on E[0])."""
    hookshot = ctx.ability("E", 0)
    wall_dive = ctx.ability("E", 1)
    if hookshot is None or wall_dive is None:
        return None
    rank = ctx.rank_for("E")
    if rank < 1:
        return None

    damage = extract_named(wall_dive, "Physical Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        hookshot.get("name", "Hookshot"),
        rank,
        extract_cooldown(hookshot, rank),
        damage,
        "physical",
    )
    bonus_as = extract_value(wall_dive, "Bonus Attack Speed", rank)
    if bonus_as > 0:
        entry["stat_buff"] = {"bonus_attack_speed": bonus_as}
    return entry


_hookshot.phase = BUFF


def _hextech_ultimatum(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: zero upfront damage; current-health magic rider on zone autos."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    percent = extract_value(ability, "Bonus Magic Damage", rank)
    window = extract_value(ability, "Zone Duration", rank)
    name = ability.get("name", "The Hextech Ultimatum")
    return {
        "name": name,
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "magic",
        "total_raw": 0.0,
        "parts": (),
        "detail": (
            f"No upfront damage — rider requires basic attacks: each auto on "
            f"the trapped target deals {percent:g}% of current health as "
            f"bonus magic damage for {window:g}s"
        ),
        "on_hit": {
            "name": f"{name} (rider)",
            "damage_type": "magic",
            "current_health_percent": percent,
            "proc_window": window,
        },
    }


OPTIONS: list[dict[str, Any]] = [
    {
        "key": "w_outer_cone",
        "type": "bool",
        "default": True,
        "label": "W Outer cone (sweet spot)",
    },
]

# HARDCODED: verify on patch updates — Adaptive Defenses' shield amount,
# duration, and damage-type adaptation are prose-only in the cached
# passive description (data/champions.json, Camille P): "grants her a
# shield equal to 20% of her maximum health, lasting for 2 seconds and
# absorbing damage from either exclusively physical damage or magic
# damage, based on which type the target has previously dealt most of".
ADAPTIVE_DEFENSES_MAX_HP_RATIO = 0.20  # 20% of maximum health
ADAPTIVE_DEFENSES_DURATION_SECONDS = 2.0


def _tactical_sweep_with_shield(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: Tactical Sweep carrying Adaptive Defenses' pre-fight shield.

    Adaptive Defenses triggers on Camille's next auto against a champion
    — a passive with no cast.  The shield (20% max HP for 2s) rides the
    first W damage event as a ``self_shield_events`` payload so the
    ledger grants it before incoming damage; the damage-type adaptation
    (physical OR magic, by the last damage type dealt to Camille) is a
    documented boundary — the ledger's payload grants a general shield
    that absorbs both types.
    """
    entry = _packet_w(ctx)
    rank = int(entry.get("rank", 0) or 0) if entry is not None else 0
    if entry is None or rank < 1:
        return entry
    shield = ADAPTIVE_DEFENSES_MAX_HP_RATIO * ctx.stat("health")
    entry["event_order_certified"] = "single_hit"
    return attach_self_shield(
        entry,
        amount=shield,
        duration=ADAPTIVE_DEFENSES_DURATION_SECONDS,
        source="Adaptive Defenses",
        detail=(
            f"W carries Adaptive Defenses' pre-fight shield: {shield:g} "
            f"({ADAPTIVE_DEFENSES_MAX_HP_RATIO * 100:g}% of max HP) for "
            f"{ADAPTIVE_DEFENSES_DURATION_SECONDS:g}s; the physical/magic "
            "adaptation boundary is documented in ASSUMPTIONS"
        ),
    )


ASSUMPTIONS = [
    "Q2 is always the delayed recast: doubled bonus damage and the "
    "level-based true conversion (36% + 4% per level, 100% from level 16)",
    "Both Q attacks cannot critically strike; in timed fights with autos "
    "the consumed auto is modeled inside the regular auto stream",
    "Spellblade procs on both Q casts; Q2's spellblade proc is converted "
    "to true damage with the attack (game-verified). Other on-hit "
    "effects keep their own damage types",
    "W models the outer-cone sweet spot by default; W's self-heal and "
    "slow are not modeled",
    "E's 40-60% attack speed is applied for the whole fight (in-game: 5s "
    "per cast); E's stun is not modeled",
    "P (Adaptive Defenses) is modeled as a pre-fight granted shield: 20% "
    "of max HP for 2s riding the first W cast. The in-game trigger (the "
    "next auto against a champion) and the physical/magic adaptation "
    "are documented boundaries — the model grants a general shield that "
    "absorbs both damage types",
    "R deals damage only through basic attacks on the trapped target: "
    "with autos disabled (or one-rotation mode) its row is 0. Rider "
    "procs are capped by the zone duration and use decaying current "
    "health starting from max HP",
]

SLOTS = {
    "E": _hookshot,
    "Q": _precision_protocol,
    "Q2": _precision_protocol_recast,
    "W": _tactical_sweep,
    "R": _hextech_ultimatum,
}

SLOTS = dict(SLOTS)
_packet_w = SLOTS["W"]
SLOTS["W"] = _tactical_sweep_with_shield
parse_abilities = build_parser(SLOTS, "Camille")


# Authoritative review metadata (issue #161).
SOURCES = [
    {
        "label": "Local League Wiki cache",
        "url": "https://wiki.leagueoflegends.com/en-us/Camille",
        "revision_id": 4002624,
        "revision_timestamp": "2026-03-27T01:51:45Z",
    }
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in SLOTS else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"

from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Camille")
