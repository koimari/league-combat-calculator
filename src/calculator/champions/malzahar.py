"""Malzahar — CP10.4 full-entry-reviewed packet module.

E (Malefic Visions) and R (Nether Grasp) override the batch packet with
full-total DoT pricing: the packets carried the PER-TICK rows, so the
fight priced one tick of each multi-tick ability.  Both totals are
sourced:

- E: "Total Magic Damage" 80/115/150/185/220 is exactly 16x the "Magic
  Damage Per Tick" row (5/7.1875/9.375/11.5625/13.75); the wiki text
  ("dealing magic damage every 0.25 seconds over 4 seconds") confirms
  the 16-tick cadence.
- R: "Total Magic Damage" 125/200/275 is exactly 10x the "Magic Damage
  Per Tick" row (12.5/20/27.5); the wiki text ("channels for up to 2.5
  seconds ... every 0.25 seconds") confirms the 10-tick cadence.

W (Void Swarm) overrides the batch packet's single-attack price with
the sourced voidling swarm: the W cast itself deals no direct damage
(the packet's 39 was one voidling attack priced as the whole ability),
and the voidling attacks ride a separate ``voidling_attacks`` proc row.
The per-attack formula and the attack-speed growth are sourced from the
wiki's Malzahar pets entry and the ability JSON:
- Per attack: level-based 5-64.5 (the 18-value per-level array) + rank
  base 12-20 + 40% bonus AD + 20% AP magic.
- Attack speed: 0.665*(1 + 0.02*(level-1)*(0.7025+0.0175*(level-1))),
  so ~0.891 AS at level 18 (~1.12s per attack).
- Summoning: the first Voidling appears after a 0.5s delay, each extra
  Voidling 0.5s later (the ability description); voidlings attack the
  target from their summon time.

P (Void Shift) is a periodic 90% damage reduction with crowd-control
immunity until it breaks — pure defensive self-state, no enemy damage.
The pinned packet already declares it ``kind: "no_damage"`` (a sourced
zero-damage row), so it was never a gap in enemy-damage coverage;
MODULE_COVERAGE was simply stale, still reading "out_of_scope" for a
slot that already emits its state row. Roadmap session 4 batch D
(2026-08-21) reclassifies P to "no_damage" (the Cassiopeia/Cho'Gath/
Jarvan precedent) rather than leaving an already-covered passive
misreported as a gap. P is not a cast slot (``rotation_resolver`` only
schedules Q/Q2/W/E/R), so this is a documentation-only fix with zero
fight-computation change.  (Damage *taken* remains an axis the engine
does not have.)
"""

from __future__ import annotations

from functools import partial
from typing import Any

from ..binary_roots import data_value, spell_object
from ..stats import growth_multiplier
from .engine import SlotCtx
from .inputs import champion_stat, int_option
from .module_contract import coverage
from .module_helpers import named_damage, ranked_slot
from .packet_module import build_packet_module
from .slotlib import (
    ability_name,
    extract_cooldown,
    extract_value,
    find_named_leveling,
    fixed_count_pet_row,
    with_control,
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
    Relative growth reuses ``stats.growth_multiplier``, so one place holds
    the level 1-20 contract."""
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

    return {
        "name": ability_name(ability),
        "rank": w_rank,
        "cooldown": extract_cooldown(ability, w_rank),
        "damage_type": "magic",
        "total_raw": 0.0,  # the summon itself deals no direct damage
        "parts": (),
        "detail": (
            f"Summons {count} Voidling(s); their attacks are priced on the "
            "voidling_attacks row."
        ),
    }


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


PACKET_SHA256 = "914a2a28fdee65829d311570f62107c1b9c39d397b2782c147e5bdbe894a4f8f"

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
MODULE_CC = {"Q": "silence", "E": "none", "R": "suppression"}

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
    ),
    int_option(
        "voidling_attacks",
        8,
        minimum=0,
        maximum=40,
        label="Attacks per Voidling (0 = none; defaults to the sourced "
        "attack-speed cadence over the fight window)",
    ),
]

ASSUMPTIONS = [
    *ASSUMPTIONS,
    "W is a summon: the cast row carries no direct damage; voidling "
    "attacks ride the sourced 'Magic Damage' leveling formula "
    "(per-level flat + per-rank base + 40% bonus AD + 20% AP) on a "
    "separate voidling_attacks proc row",
    "Voidling attack cadence is the wiki pets attack speed "
    "(0.665 + 2% growth per level, ~0.891 AS at 18) with the 0.5s "
    "summon delay and 0.5s stagger; the default attack count truncates "
    "that cadence to the fight window",
    "One summon wave per fight window; re-casting W refreshes the swarm "
    "in-game, modeled by the voidling_count option (up to 4) instead of "
    "multiplying the proc row by W casts",
    "An autos-only fight summons no swarm at all (the pipeline states "
    "this with the auto_attacks_only reserved option): the cached W text "
    "sources the Zz'Rot stacks to 'when he casts another ability' and the "
    "Voidlings to 'Active: Malzahar consumes all Zz'Rot Swarm stacks "
    "and... summons a Voidling', so a basic attack produces neither",
    "P (Void Shift) is periodic defensive self-state (damage reduction "
    "with crowd-control immunity) with no enemy damage, so it emits the "
    "packet's sourced zero-damage row (MODULE_COVERAGE: no_damage, not "
    "out_of_scope). P is not a cast slot in this engine's rotation.",
]

MODULE_COVERAGE = coverage(no_damage="P")
