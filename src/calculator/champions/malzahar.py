"""Malzahar: full-entry-reviewed packet module.

E (Malefic Visions) and R (Nether Grasp) price the full-total DoT rows, never
the per-tick ones: E's "Total Magic Damage" is exactly 16 ticks at 0.25s over
4 seconds, and R's is 10 ticks over its 2.5-second channel.
W (Void Swarm) deals no direct damage on the cast.  The voidlings ride a
separate ``voidling_attacks`` proc row, each attack being the 18-value
per-level array plus the ranked base, 40% bonus AD and 20% AP as magic.  Their
attack speed is 0.665 grown by 2% per level on the standard growth curve, and
the first appears 0.5s after the cast with each further one 0.5s later.
P (Void Shift) is a ``no_damage`` row: its periodic 90% damage reduction and
crowd-control immunity are self-state, and damage taken is an axis this engine
does not carry.
"""

from __future__ import annotations

from functools import partial
from typing import Any

from ..binary_roots import data_value, spell_object
from ..stat_formulas import growth_multiplier
from .contract_vocabulary import coverage
from .engine import SlotCtx
from .inputs import champion_stat, int_option
from .module_helpers import named_damage, ranked_slot
from .packet_module import build_packet_module
from .slot_control import with_control
from .slot_entries import damage_entry, fixed_count_pet_row
from .slot_extract import (
    ability_name,
    extract_cooldown,
    extract_value,
    find_named_leveling,
)

_MALZAHAR_E_SPELL = spell_object("Malzahar", "MalzaharE")
_MALZAHAR_R_SPELL = spell_object("Malzahar", "MalzaharR")
# E: 16 ticks over 4s; R: 10 ticks over 2.5s.  The binary carries the
# durations and E's explicit cadence; the remaining counts/cadence are
# derived from those rooted fields.
_E_DURATION = data_value(_MALZAHAR_E_SPELL, "Duration")
_E_TICK_INTERVAL = data_value(_MALZAHAR_E_SPELL, "SecondsPerTick")
_E_TICKS = int(_E_DURATION / _E_TICK_INTERVAL)
_R_DURATION = data_value(_MALZAHAR_R_SPELL, "SuppressDuration")
_R_TICKS = int(data_value(_MALZAHAR_R_SPELL, "BeamDamageTicks"))
_R_TICK_INTERVAL = _R_DURATION / _R_TICKS

# HARDCODED: verify on patch updates — pet attack-speed growth is not in
# the champion JSON (the wiki's Malzahar#Pets entry):
# https://wiki.leagueoflegends.com/en-us/Malzahar
# Voidling attack speed = 0.665*(1 + 0.02*(level-1)*(0.7025+0.0175*(level-1))).
# Summon cadence: first Voidling after 0.5s, each extra 0.5s later
# (the W description).  The per-attack damage rows themselves are read
# from the champion JSON ("Magic Damage" leveling entry).
_VOIDLING_AS_BASE = 0.665
_VOIDLING_AS_GROWTH = 0.02
_VOIDLING_SUMMON_DELAY = data_value(
    spell_object("Malzahar", "MalzaharW"), "SummonDelay"
)
_VOIDLING_SUMMON_STAGGER = 0.5
_VOIDLING_DEFAULT_WINDOW = 5.0  # one rotation; timed fights pass the real window
_VOIDLING_MAX_ATTACKS_PER_UNIT = 40
_VOIDLING_ATTACK_ATTR = "Magic Damage"


def _voidling_attack_speed(level: int) -> float:
    """One Voidling's attacks per second at champion level (wiki pets).
    Relative growth reuses ``stat_formulas.growth_multiplier``, so one
    place holds the level 1-20 contract."""
    return _VOIDLING_AS_BASE * (
        1.0 + _VOIDLING_AS_GROWTH * (level - 1) * growth_multiplier(level)
    )


def _voidling_attack_damage(
    ability: dict[str, Any],
    level: int,
    w_rank: int,
    stats: dict[str, float],
) -> float:
    """One Voidling attack: per-level flat + per-rank base + 40% bAD + 20% AP.

    The four modifiers of the single "Magic Damage" leveling entry are,
    in order: the 18-value per-level flat, the 5-value per-rank flat,
    the 40% bonus-AD ratio, and the 20% AP ratio.
    """
    leveling = find_named_leveling(ability, _VOIDLING_ATTACK_ATTR)
    if leveling is None:
        raise ValueError(
            "Malzahar W: 'Magic Damage' leveling entry is missing from "
            "the ability JSON — cannot compute voidling attack damage"
        )
    flat_level = extract_value(ability, _VOIDLING_ATTACK_ATTR, level, 0)
    flat_rank = extract_value(ability, _VOIDLING_ATTACK_ATTR, w_rank, 1)
    bad_ratio = extract_value(ability, _VOIDLING_ATTACK_ATTR, w_rank, 2)
    ap_ratio = extract_value(ability, _VOIDLING_ATTACK_ATTR, w_rank, 3)
    return (
        flat_level
        + flat_rank
        + bad_ratio / 100.0 * champion_stat(stats, "bonus_attack_damage")
        + ap_ratio / 100.0 * champion_stat(stats, "ability_power")
    )


@ranked_slot
def _void_swarm(
    ctx: SlotCtx, ability: dict[str, Any], w_rank: int
) -> dict[str, Any] | None:
    """W: zero-damage summon cast + the voidling-attack proc row.

    One summon wave per fight window: ``voidling_count`` Voidlings (2-4,
    default 3 — the sourced per-cast cap of 1 + 2 Zz'Rot stacks) attack
    from their staggered summon times at the sourced attack speed.
    ``voidling_attacks`` overrides the per-Voidling attack count; the
    default is the sourced cadence truncated to the fight window.  The
    proc row is fixed-count — re-casting W refreshes the swarm in-game,
    which the option models instead of multiplying by W casts.

    An ``auto_attacks_only`` window casts nothing, so there is no swarm:
    the Zz'Rot stacks come from casting another ability and the Voidlings
    from W's Active, neither of which a basic attack does.
    """
    if ctx.option("auto_attacks_only"):
        return None

    count = min(max(int(ctx.option("voidling_count")), 2), 4)
    per_attack = _voidling_attack_damage(ability, ctx.level, w_rank, ctx.stats)
    interval = 1.0 / _voidling_attack_speed(ctx.level)
    window = float(ctx.options.get("fight_duration_seconds", _VOIDLING_DEFAULT_WINDOW))
    requested = ctx.options.get("voidling_attacks")
    attack_times: list[float] = []
    for index in range(count):
        summon_time = _VOIDLING_SUMMON_DELAY + _VOIDLING_SUMMON_STAGGER * index
        if requested is None:
            per_unit = int((window - summon_time) // interval)
            per_unit = max(0, per_unit)
        else:
            per_unit = min(max(int(requested), 0), _VOIDLING_MAX_ATTACKS_PER_UNIT)
        attack_times.extend(summon_time + (n + 1) * interval for n in range(per_unit))
    total_attacks = len(attack_times)
    if total_attacks > 0:
        ctx.results["voidling_attacks"] = fixed_count_pet_row(
            "Voidling Attacks",
            "magic",
            per_attack,
            attack_times,
            detail=(
                f"{count} Voidling(s), {total_attacks} attack(s) total at "
                f"{per_attack:.2f} magic each ({interval:.2f}s cadence)"
            ),
        )

    return damage_entry(
        ability_name(ability),
        w_rank,
        extract_cooldown(ability, w_rank),
        0.0,  # the summon itself deals no direct damage
        "magic",
        parts=(),
        detail=(
            f"Summons {count} Voidling(s); their attacks are priced on the "
            "voidling_attacks row."
        ),
    )


# E: the full 4-second Total Magic Damage across 16 sourced ticks.  Item
# burns (Liandry's, Blackfire Torch) stay refreshed through the whole
# infection (the Cassiopeia rule).
_malefic_visions = named_damage(
    "Total Magic Damage",
    "magic",
    ticks=_E_TICKS,
    time_offset=_E_TICK_INTERVAL,
    hit_interval=_E_TICK_INTERVAL,
    dot_duration=_E_DURATION,
)

# R: the full 2.5-second Total Magic Damage across 10 sourced ticks.  Only
# the flat "Total Magic Damage" row (effect 0) is read; the Null Zone's
# separate max-health row stays out of scope, as in the reviewed packet.
_nether_grasp = named_damage(
    "Total Magic Damage",
    "magic",
    ticks=_R_TICKS,
    time_offset=_R_TICK_INTERVAL,
    hit_interval=_R_TICK_INTERVAL,
    dot_duration=_R_DURATION,
)


PACKET_SHA256 = "e1c6fe3b8c168990c3791edc8d20ed60157d8670ebf0d4ad1be01494bab33e8b"

# Call of the Void lands on its own delay: Malzahar "opens two portals to
# the void centered at the target location ... After 0.4 seconds, enemies
# between the portals are dealt magic damage and silenced for a duration"
# (data/champions.json Malzahar Q).  The cached entry attaches no
# cast-time qualifier to the number, so it is read from the cast start as
# written.
_Q_PORTAL_SECONDS = data_value(spell_object("Malzahar", "MalzaharQ"), "DelayPostCast")


# Reviewed crowd control, read from the cached kit.  Call of the Void's
# delayed hit leaves the enemies it damages "silenced for a duration".
# Malefic Visions only deals "magic damage every 0.25 seconds over 4
# seconds" and spreads on death.  Nether Grasp's channel is
# "suppressing and revealing the target and dealing them magic damage
# every 0.25 seconds" — the suppression is what the damaged target takes.
# W's cast authors no damage part (the swarm rides its own pet row, which
# is not an ability event) and P is a self-buff.
MODULE_CC = {"Q": "silence", "E": "none", "R": "suppression", "P": "none", "W": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Malzahar",
    PACKET_SHA256,
    packet_part_timings={"Q": {"time_offset": _Q_PORTAL_SECONDS}},
    # Override the packet DoT rows with the full-total tick pricing above,
    # and the packet's single-attack W with the sourced voidling swarm.
    slot_parsers={
        "W": _void_swarm,
        "E": _malefic_visions,
        "R": _nether_grasp,
    },
    # The portals' sourced Silence Duration row carries MODULE_CC's reviewed
    # kind and its control atom onto the packet's Q entry.
    slot_wrappers={
        "Q": partial(with_control, duration_attr="Silence Duration"),
    },
    cc_kinds=MODULE_CC,
)
OPTIONS = [
    *OPTIONS,
    int_option(
        "voidling_count",
        3,
        minimum=2,
        maximum=4,
        label="Active Voidlings (3 = one full W cast at 2 Zz'Rot stacks; "
        "4 models an overlapping second wave in a sustained window)",
        rotation={"role": "self_state", "slot": "R"},
    ),
    int_option(
        "voidling_attacks",
        8,
        minimum=0,
        maximum=40,
        label="Attacks per Voidling (0 = none; defaults to the sourced "
        "attack-speed cadence over the fight window)",
        derives=True,
        rotation={"role": "self_state", "slot": "R"},
    ),
]

ASSUMPTIONS = [
    *ASSUMPTIONS,
    "W is a summon: its cast row carries no direct damage.",
    "Voidling attacks ride the sourced Magic Damage row, flat + base + 40% bonus AD + "
    "20% AP, on their own row.",
    "Voidling cadence is the wiki pets attack speed, 0.665 + 2% per level, about "
    "0.891 at 18.",
    "The 0.5s summon delay and 0.5s stagger apply, and the default count truncates to "
    "the fight window.",
    "One summon wave per fight window: voidling_count (up to 4) stands in for W "
    "recasts refreshing it.",
    "An autos-only fight summons no swarm (auto_attacks_only): stacks need 'another "
    "ability' cast.",
    "The cached W Active consumes those stacks, so a basic attack produces neither "
    "stack nor Voidling.",
    "P (Void Shift) is periodic defensive self-state, damage reduction with "
    "crowd-control immunity.",
    "It carries no enemy damage, emits the sourced zero-damage row, and is not a cast "
    "slot here.",
]

MODULE_COVERAGE = coverage(no_damage="P")
