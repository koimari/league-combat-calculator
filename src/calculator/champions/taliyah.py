"""Taliyah — sourced E -> W -> Q event model with a timed terrain walk.

The certified one-rotation package casts Unraveled Earth, knocks the selected
target across its stones with Seismic Shove, then fires Threaded Volley.
Every damaging hit has an authored time; Worked Ground and the number of
stones detonated are explicit scenario inputs there.

Timed fights derive the terrain state instead: the first Threaded Volley on
fresh ground throws the full 5-shard volley and creates Worked Ground
(sourced: a 400-unit area lasting 30s — at least the public fight window),
and every later cast is made from inside it, consuming and re-creating the
area, so it uses the empowered boulder row, the 10-mana cost, and the halved
(min 0.75s) cooldown. The walk is module-owned on the engine's
cast-exactly-once idiom (the ability entry declares cooldown 0.0 and authors
every hit itself, like Aurelion Sol's continuous Q channel), with ability
haste applied to both cooldowns; E and W recast on their own cooldowns
through the shared scheduler, each E window detonating the selected stones.

Coverage: P (Rock Surfing) grants movement speed near terrain and R
(Weaver's Wall) raises a wall Taliyah can ride. Neither slot carries a
damage instance anywhere in the cached entry, so both are emitted as
sourced zero-damage rows (``no_damage``) rather than withheld — the
settled shape for a self movement state or a terrain utility with
nothing damage-relevant left unmodeled (Sivir P, Akshan W, Aurora W,
Nilah W, Zilean E).
"""

import math
from typing import Any

from ..ability_spec import DamagePart
from ..binary_roots import data_value, spell_object
from ..stats import effective_cooldown
from .engine import CC_PER_PART, SlotCtx, build_parser
from .inputs import float_option, int_option
from .module_contract import coverage
from .module_helpers import clamp, no_damage_slot, ranked_slot
from .slotlib import (
    ability_name,
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_resource_cost,
)
from .source_receipts import load_champion_sources

_E_CAST_START = 0.0
_W_CAST_START = 0.25
_Q_CAST_START = 0.5
_W_ERUPTION_DELAY = 0.792
_TALIYAH_E_SPELL = spell_object("Taliyah", "TaliyahE")
_E_ROW_INTERVAL = data_value(_TALIYAH_E_SPELL, "DelayBetweenRows")
_E_DETONATION_MULTIPLIERS = (1.0, 0.75, 0.5, 0.25)
_Q_CAST_TIME = 0.25
_Q_NORMAL_LAUNCH_OFFSETS = (0.25, 0.75, 1.25, 1.5, 1.75)
_Q_NORMAL_INITIAL_SPEED = 3600.0
_Q_NORMAL_DECELERATION = 5000.0
_Q_WORKED_SPEED = 2000.0
_Q_ORIGIN_OFFSET = 50.0
_Q_MAX_RANGE = 1000.0
_TALIYAH_Q_SPELL = spell_object("Taliyah", "TaliyahQ")
_Q_WORKED_COST = data_value(_TALIYAH_Q_SPELL, "BigRockManaCost")
_Q_WORKED_COOLDOWN_MULTIPLIER = data_value(_TALIYAH_Q_SPELL, "WorkedGroundCDR")
_Q_WORKED_MINIMUM_COOLDOWN = data_value(_TALIYAH_Q_SPELL, "MinimumWorkedGroundCD")


def _normal_projectile_time(distance: float) -> float:
    """Travel time for a shard's sourced decelerating projectile."""
    travel = max(0.0, distance - _Q_ORIGIN_OFFSET)
    discriminant = max(
        0.0,
        _Q_NORMAL_INITIAL_SPEED**2 - 2.0 * _Q_NORMAL_DECELERATION * travel,
    )
    return (_Q_NORMAL_INITIAL_SPEED - math.sqrt(discriminant)) / _Q_NORMAL_DECELERATION


def _worked_travel_time(distance: float) -> float:
    """Travel time for the Worked Ground boulder's sourced flat speed."""
    return max(0.0, distance - _Q_ORIGIN_OFFSET) / _Q_WORKED_SPEED


def _boulder_damage(ctx: SlotCtx, ability: dict, rank: int) -> tuple[float, bool]:
    """Worked Ground boulder damage and whether this is the primary target."""
    primary = int(ctx.target_stat("roster_target_index")) == 0
    attribute = "Empowered Damage" if primary else "Secondary Target Damage"
    return extract_named(ability, attribute, rank, ctx.stats, ctx.target), primary


def _volley_parts(
    ctx: SlotCtx, ability: dict, rank: int, distance: float, *, start: float
) -> tuple[DamagePart, ...]:
    """One full fresh-ground volley: 5 shards from a cast starting at ``start``.

    The shards carry the reviewed no-control answer: a fresh-ground Stone
    Shard is "dealing magic damage to nearby enemies and revealing them",
    with no control clause — only the Worked Ground boulder slows.  Q's
    two terrain states can share one entry (the timed walk authors both),
    so the answer rides the part rather than MODULE_CC.
    """
    first = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    reduced = extract_named(ability, "Reduced Damage", rank, ctx.stats, ctx.target)
    travel = _normal_projectile_time(distance)
    return tuple(
        DamagePart(
            "magic",
            first if index == 0 else reduced,
            time_offset=start + launch + travel,
            cc_kind="none",
        )
        for index, launch in enumerate(_Q_NORMAL_LAUNCH_OFFSETS)
    )


def _timed_cast_starts(
    duration: float, fresh_cd: float, worked_cd: float
) -> list[float]:
    """Q cast start times over the fight window, from the terrain state.

    The fresh cast at t=0 pays the full cooldown, since it CREATES Worked Ground
    rather than being cast from it; later casts are empowered and pay the halved
    one.  Each occupies its 0.25s cast time before its cooldown runs.
    """
    starts = [0.0]
    start = _Q_CAST_TIME + fresh_cd
    while start <= duration:
        starts.append(start)
        start += _Q_CAST_TIME + worked_cd
    return starts


def _timed_threaded_volley(
    ctx: SlotCtx, ability: dict, rank: int, distance: float, *, duration: float
) -> dict[str, Any]:
    """Timed Q: the module-owned Worked Ground walk, cast exactly once.

    The entry declares cooldown 0.0 (the engine's cast-exactly-once idiom)
    and authors every hit of every cast itself, so the terrain state — full
    volley first, boulders after — persists across the whole window. Both
    cooldowns take ability haste plus basic-ability haste, the same haste
    the engine would apply to a scheduled Q/W/E entry.
    """
    haste = ctx.stat("ability_haste") + ctx.stat("basic_ability_haste")
    base_cd = extract_cooldown(ability, rank)
    starts = _timed_cast_starts(
        duration,
        effective_cooldown(base_cd, haste),
        effective_cooldown(
            max(
                _Q_WORKED_MINIMUM_COOLDOWN,
                base_cd * _Q_WORKED_COOLDOWN_MULTIPLIER,
            ),
            haste,
        ),
    )
    boulder, primary = _boulder_damage(ctx, ability, rank)
    boulder_travel = _worked_travel_time(distance)
    parts = _volley_parts(ctx, ability, rank, distance, start=starts[0]) + tuple(
        # The empowered cast is the one that controls: "dealing 180% damage
        # to them and normal damage to nearby enemies, slowing all targets
        # hit for 1.5 seconds".
        DamagePart(
            "magic",
            boulder,
            time_offset=start + _Q_CAST_TIME + boulder_travel,
            cc_kind="slow",
        )
        for start in starts[1:]
    )
    boulders = len(starts) - 1
    entry = damage_entry(
        ability_name(ability),
        rank,
        0.0,
        sum(part.amount for part in parts),
        "magic",
    )
    entry["parts"] = parts
    entry["cast_instances"] = len(starts)
    entry["resource_type"] = "MANA"
    entry["resource_cost"] = (
        extract_resource_cost(ability, rank, ctx.level) + _Q_WORKED_COST * boulders
    )
    entry["detail"] = (
        f"Fresh volley then {boulders} Worked Ground boulder"
        f"{'' if boulders == 1 else 's'} on the "
        f"{'primary' if primary else 'secondary'} target over {duration:g}s"
    )
    return entry


@ranked_slot
def _threaded_volley(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:

    ground = str(ctx.option("q_ground"))
    if ground not in {"normal", "worked"}:
        raise ValueError("Taliyah q_ground must be normal or worked")
    distance = clamp(float(ctx.option("q_target_distance")), 0.0, _Q_MAX_RANGE)

    # A timed fight window derives the terrain sequence itself; the
    # q_ground select prices the two states in one-rotation mode only.
    duration = ctx.options.get("fight_duration_seconds")
    if duration is not None:
        return _timed_threaded_volley(
            ctx, ability, rank, distance, duration=float(duration)
        )

    if ground == "worked":
        raw, primary = _boulder_damage(ctx, ability, rank)
        hit_time = _Q_CAST_START + _Q_CAST_TIME + _worked_travel_time(distance)
        entry = damage_entry(
            ability_name(ability),
            rank,
            max(
                _Q_WORKED_MINIMUM_COOLDOWN,
                extract_cooldown(ability, rank) * _Q_WORKED_COOLDOWN_MULTIPLIER,
            ),
            raw,
            "magic",
        )
        entry["parts"] = (
            DamagePart("magic", raw, time_offset=hit_time, cc_kind="slow"),
        )
        entry["resource_type"] = "MANA"
        entry["resource_cost"] = _Q_WORKED_COST
        target_label = "primary" if primary else "secondary"
        entry["detail"] = (
            f"Worked Ground boulder on the {target_label} target at {distance:g} range"
        )
        return entry

    parts = _volley_parts(ctx, ability, rank, distance, start=_Q_CAST_START)
    total = parts[0].amount + 4.0 * parts[1].amount
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    entry["parts"] = parts
    entry["detail"] = (
        f"5 shards on one target at {distance:g} range; later shards deal 40%"
    )
    return entry


@ranked_slot
def _seismic_shove(
    _ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    """W deals no damage but spends its sourced cast and mana cost."""
    return {
        "name": ability_name(ability),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "magic",
        "total_raw": 0.0,
        "parts": (),
        "detail": "Knockback used to trigger the selected E stones",
    }


@ranked_slot
def _unraveled_earth(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:

    requested = int(ctx.option("e_detonations"))
    detonations = int(clamp(float(requested), 0.0, 4.0))
    initial = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    detonation = extract_named(
        ability, "Detonation Magic Damage", rank, ctx.stats, ctx.target
    )
    first_detonation = _W_CAST_START + _W_ERUPTION_DELAY
    # E's two hits control differently, so each part carries its own answer:
    # the eruption leaves a field that "slow[s] enemies within the area by
    # 20%", while a stone the target is knocked over detonates "taking
    # magic damage and becoming stunned for 0.75 seconds".
    parts = [DamagePart("magic", initial, time_offset=_E_CAST_START, cc_kind="slow")]
    parts.extend(
        DamagePart(
            "magic",
            detonation * multiplier,
            time_offset=first_detonation + index * _E_ROW_INTERVAL,
            cc_kind="stun",
        )
        for index, multiplier in enumerate(_E_DETONATION_MULTIPLIERS[:detonations])
    )
    total = sum(part.amount for part in parts)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    entry["parts"] = tuple(parts)
    entry["detail"] = (
        f"initial eruption + {detonations} stone detonation"
        f"{'' if detonations == 1 else 's'}"
    )
    return entry


CAST_ORDER = ("E", "W", "Q")
CUSTOM_CAST_ORDER_UNAVAILABLE_REASON = (
    "Taliyah uses the certified E -> W -> Q sequence so Seismic Shove can "
    "detonate the selected number of stones."
)

OPTIONS = [
    {
        "key": "q_ground",
        "type": "select",
        "default": "normal",
        "label": "Threaded Volley terrain",
        "choices": [
            {"value": "normal", "label": "Fresh ground · 5 shards"},
            {"value": "worked", "label": "Worked Ground · boulder"},
        ],
    },
    int_option(
        "e_detonations",
        4,
        minimum=0,
        maximum=4,
        label="E stones detonated by the target",
        step=1,
    ),
    float_option(
        "q_target_distance",
        800.0,
        minimum=0.0,
        maximum=1000.0,
        label="Threaded Volley target distance",
        step=50.0,
    ),
]

ASSUMPTIONS = [
    "One-rotation mode is the certified E -> W -> Q sequence; timed fights "
    "repeat E and W on their cooldowns and walk Q through the Worked "
    "Ground terrain state.",
    "The target is displaced through exactly the selected number of E stones "
    "(each E window in a timed fight, with a W available per window); "
    "successive detonations deal 100%, 75%, 50%, then 25% damage.",
    "Normal Q places all five shards on one target; later shards deal 40%. "
    "Worked Ground instead uses the primary-target 180% boulder hit.",
    "Timed Q: the first cast on fresh ground throws the full volley and "
    "creates Worked Ground (a 400-unit area lasting 30s, at least the fight "
    "window); Taliyah stays inside it, so every later cast is the empowered "
    "boulder at 10 mana on the halved (min 0.75s) cooldown. The q_ground "
    "select applies to one-rotation mode only.",
    "Target distance prices Q projectile travel while Taliyah remains at that "
    "distance for the volley.",
    "P (Rock Surfing) and R (Weaver's Wall) deal no enemy damage; both are "
    "emitted as sourced zero-damage rows (MODULE_COVERAGE: no_damage) "
    "rather than withheld. P is a self movement state and R is terrain "
    "plus a knockback that carries no sourced duration attribute, so "
    "neither leaves a damage channel unmodeled.",
]


# P: bonus move speed, a sourced zero-enemy-damage row.
#
# No effect row carries a damage instance (empty ``leveling``, ``affects``
# Self), and percent move speed reaches damage only through Swiftmarch's
# build-time read of total speed — the settled ``no_damage`` shape (Sivir
# P, Akshan W, Aurora W), not an ``out_of_scope`` receipt.
_rock_surfing = no_damage_slot(
    "Innate: 10% / 15% / 25% / 40% (based on level) bonus movement "
    "speed near terrain — self movement state with no damage "
    "instance, and it is suppressed while casting or in champion "
    "combat."
)


# R: terrain + knockback — a sourced zero-enemy-damage row.
#
# Every one of Weaver's Wall's four cached effect rows has an empty
# ``leveling`` array and the entry's ``damageType`` is ``None``: the
# ultimate summons terrain, knocks champions aside and lets Taliyah
# surf it.  The slot's atom catalog holds only ``timing.active_duration``
# (4.0s, the cast channel) and the cooldown row.  The knockback carries
# no sourced duration attribute anywhere in the slot, so no control
# event is authored — an invented duration is exactly what this module
# refuses to do (contrast Udyr E in the same batch, whose 0.75s stun IS
# a validated ``timing.control_duration`` atom).
_weavers_wall = no_damage_slot(
    "Terrain wall plus a knockback on champions hit: no damage row "
    "exists in the slot, and the knockback has no sourced duration "
    "attribute to author a control event from."
)


SOURCES = load_champion_sources("Taliyah")

SLOTS = {
    "E": _unraveled_earth,
    "W": _seismic_shove,
    "Q": _threaded_volley,
    "P": _rock_surfing,
    "R": _weavers_wall,
}

# Reviewed crowd control, read from the cached kit.  Q and E each land two
# different answers from one cast, so the parts carry them: Q's fresh-ground
# shards only "deal[] magic damage ... and reveal[]" while the Worked Ground
# boulder is "slowing all targets hit for 1.5 seconds"; E's eruption
# "slow[s] enemies within the area by 20%" while a detonated stone leaves
# them "stunned for 0.75 seconds".  W's ledge "knocks enemies hit 400 units
# in the target direction" and prices no damage of its own.
MODULE_CC = {
    "Q": CC_PER_PART,
    "W": "knockback",
    "E": CC_PER_PART,
    "P": "none",
    "R": "knockback",
}

parse_abilities = build_parser(SLOTS, "Taliyah", cc_kinds=MODULE_CC)

# P and R are emitted but carry no damage instance, so the derived
# "modeled" would overstate them.  Neither is out_of_scope either (the
# Olaf-R rule reserves that for a real sourced mechanic that WOULD change
# damage): P's payload is percent move speed and R's is terrain plus an
# undurationed knockback, so nothing damage-relevant is withheld.
MODULE_COVERAGE = coverage(no_damage="PR")
