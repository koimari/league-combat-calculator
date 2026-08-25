"""Shen — sourced empowered-attack and energy timeline.

Twilight Assault is not cast damage: it modifies up to three subsequent
basic attacks with level-, rank-, AP-, and target-max-health-scaled magic
damage. The module emits the bonus as a three-hit typed part carrying the
authored swing schedule (the selected first-attack delay, then the
enhanced-attack-speed cadence), and declares the consumed basic attacks
through ``empowers_next_auto``. In a one-rotation calculation those attacks
are forced on the same schedule and the row's ledger sums exactly. In a
timed fight the engine caps Q casts at the ambient swings that consume them
and shows those swings on the Q row at the auto row's per-hit value; the
authored events remain the magic bonus hits, so the row certifies by its
cast schedule while the ledger prices each bonus instance at its swing.

Shadow Dash is authored at the selected travel distance. Its cooldown begins
after the dash, so travel time is added to the data's post-effect cooldown.
It also carries P (Ki Barrier), which fires "after completing an ability's
effects": the sourced self-shield (``data/champions.json`` Shen P "Shield"
leveling row — a per-LEVEL flat base, 47 : 128.59, plus a flat 13% bonus
health modifier that is the same at every level) rides the E cast as a
``self_shield_events`` payload, because a shield-only slot has no channel of
its own and a passive is never cast.  The cached notes name Shadow Dash's own
dash-end as one of Ki Barrier's triggers ("Shadow Dash will grant the shield
when the dash ends") and this module's certified order is E before Q, so E is
the first ability to complete in a one-rotation fight.  Ki Barrier's 11-second
flat cooldown — its own cached row, not affected by ability haste — is longer
than any one-rotation fight, so Q's own later completion (also a named
trigger) is not double-counted.

R (Stand United) is a zero-damage cast so the ally-support scanner prices
the sourced ally shield at its floor (the cached "Minimum Shield Strength"
row, 120/220/320 + 135% AP + 15% of his bonus health, which
``support_effects._SHIELD_ATTRIBUTES`` reads floor-before-ceiling); the
"increased by 0% : 60% (based on target's missing health)" that separates it
from the "Maximum Shield Strength" row (uniformly 1.6x the minimum at every
rank) is a live-health condition the scan cannot establish, and the 3-second
channel's teleport has no numeric representation in this engine at all.

W (Spirit's Refuge) is a pure attack-block zone: the cached ability carries
``"leveling": []`` for its only effect row (``data/champions.json`` Shen W) —
no damage, heal or shield numeric attribute of any kind, only a rank-scaled
cost and cooldown — so the slot emits an explicit ``no_damage`` state row
rather than staying silently absent.  The engine does carry an attack-block
convention (``interaction_effects.ProjectileDefense.blocks_basic_attacks``,
used by Jax's Counter Strike and Fiora's Riposte), but it lives entirely on
the DEFENDER side of a champion-vs-champion interaction, not in a champion's
own outgoing ``SLOTS`` map.
"""

from dataclasses import replace
from typing import Any

from ..ability_spec import DamagePart
from ..binary_roots import data_value, spell_object
from .engine import SlotCtx, build_parser
from .module_helpers import no_damage
from .scaling import is_flat_unit, resolve_scaling
from .slotlib import (
    ability_name,
    attach_self_shield,
    damage_entry,
    extract_cooldown,
    extract_named,
    find_named_leveling,
    support_cast,
)
from .source_receipts import load_champion_sources
from .inputs import bool_option, float_option, int_option
from .module_contract import coverage
from ..stats import calculate_attack_speed

_SHEN_Q_SPELL = spell_object("Shen", "ShenQ")
_SHEN_E_SPELL = spell_object("Shen", "ShenE")
_Q_ATTACKS = int(data_value(_SHEN_Q_SPELL, "NumEnhancedAttacks"))
_Q_ENHANCED_BONUS_ATTACK_SPEED = data_value(_SHEN_Q_SPELL, "SteroidAS")
_E_BASE_SPEED = data_value(_SHEN_E_SPELL, "DashBonusSpeed")
# HARDCODED: verify on patch updates — Ki Barrier's duration is prose
# ("grants himself a shield for 47 : 128.59 (based on level) (+ 13% bonus
# health) for 2.5 seconds"); the amount itself is the cached P "Shield" row.
_P_SHIELD_DURATION_SECONDS = data_value(
    spell_object("Shen", "ShenPassive"), "ShieldDuration"
)


def _named_level_rank_damage(
    ctx: SlotCtx,
    ability: dict[str, Any],
    attribute: str,
    rank: int,
) -> float:
    """Resolve a leveling row mixing per-level flat and per-rank scaling.

    Twilight Assault stores its flat damage as 18 champion-level values in
    the same row as five rank values for the max-health ratio. The shared
    rank-only extractor cannot distinguish those axes, so this resolver makes
    the source's two dimensions explicit.
    """
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute") != attribute:
                continue
            total = 0.0
            for modifier in leveling.get("modifiers", []):
                values = modifier.get("values", [])
                units = modifier.get("units", [])
                if not values:
                    continue
                index = ctx.level - 1 if len(values) >= 18 else rank - 1
                index = min(max(index, 0), len(values) - 1)
                value = float(values[index])
                unit = units[index] if index < len(units) else ""
                total += (
                    value
                    if is_flat_unit(unit)
                    else resolve_scaling(unit, value, ctx.stats, ctx.target)
                )
            return total
    raise ValueError(f"Shen Q attribute {attribute!r} is unavailable")


def _ki_barrier_shield_amount(ctx: SlotCtx) -> float:
    """P: the sourced self-shield amount at the current champion level.

    Ki Barrier's cached "Shield" leveling row mixes a 20-value per-LEVEL
    flat base (level-indexed, matching Twilight Assault's own mixed rows)
    with a flat 13% bonus health modifier that is the same at every level
    (a length-1 values array). Ki Barrier has no rank of its own (Innate),
    so every modifier here is read by champion level only.
    """
    ability = ctx.ability("P")
    if ability is None:
        raise ValueError("Shen P (Ki Barrier) ability data is unavailable")
    leveling = find_named_leveling(ability, "Shield")
    if leveling is None:
        raise ValueError(
            "Shen P (Ki Barrier): the cached P entry has no 'Shield' "
            "leveling row for its self-shield amount"
        )
    total = 0.0
    for modifier in leveling.get("modifiers", []):
        values = modifier.get("values", [])
        units = modifier.get("units", [])
        if not values:
            continue
        index = min(max(ctx.level - 1, 0), len(values) - 1)
        value = float(values[index])
        unit = units[index] if index < len(units) else ""
        total += (
            value
            if is_flat_unit(unit)
            else resolve_scaling(unit, value, ctx.stats, ctx.target)
        )
    return total


def _energy_restore(level: int) -> float:
    """Current Shadow Dash passive thresholds: levels 1, 4, and 12."""
    if level >= 12:
        return 50.0
    if level >= 4:
        return 40.0
    return 30.0


def _twilight_assault(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: selected normal/enhanced attacks, including their base swings."""
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked

    hits = min(
        _Q_ATTACKS,
        max(0, int(ctx.options.get("q_attacks_landed", _Q_ATTACKS))),
    )
    enhanced = bool(ctx.option("q_spirit_blade_hit"))
    attribute = "Increased Bonus Damage" if enhanced else "Bonus Magic Damage"
    per_hit = _named_level_rank_damage(ctx, ability, attribute, rank)
    baseline_target_health = float(ctx.target_stat("target_max_health"))
    if baseline_target_health > 0.0:
        flat_ctx = replace(
            ctx,
            target={**ctx.target, "target_max_health": 0.0},
        )
        flat_component = _named_level_rank_damage(flat_ctx, ability, attribute, rank)
        target_health_ratio = max(
            0.0, (per_hit - flat_component) / baseline_target_health
        )
    else:
        flat_component = per_hit
        target_health_ratio = 0.0

    def target_health_damage(
        _missing_ratio: float,
        live_target_max_health: float | None = None,
    ) -> float:
        live_max = (
            baseline_target_health
            if live_target_max_health is None
            else live_target_max_health
        )
        return flat_component + live_max * target_health_ratio

    cooldown = extract_cooldown(ability, rank)
    entry = damage_entry(
        ability_name(ability),
        rank,
        cooldown,
        per_hit * hits,
        "magic",
    )
    entry["parts"] = ()
    entry["target_max_health_sensitive"] = True
    entry["resource_restore"] = _energy_restore(ctx.level) * hits
    entry["detail"] = (
        f"{hits} {'enhanced' if enhanced else 'normal'} empowered attack"
        f"{'' if hits == 1 else 's'}"
    )
    if hits:
        attack_speed = ctx.stat("attack_speed")
        if enhanced:
            attack_speed = calculate_attack_speed(
                attack_speed,
                ctx.stat("attack_speed_ratio"),
                _Q_ENHANCED_BONUS_ATTACK_SPEED,
            )
        first_delay = float(ctx.option("q_first_attack_delay"))
        interval = 1.0 / attack_speed if attack_speed > 0 else 0.0
        # The bonus part carries the authored swing schedule, so every
        # bonus instance prices an exact event at its consuming swing
        # (first hit after the selected delay, then the enhanced cadence)
        # instead of an uncertified cast-boundary lump.  The engine caps
        # timed casts at the ambient swings that consume them and forces
        # the swings itself when no stream exists.
        entry["parts"] = (
            DamagePart(
                "magic",
                per_hit,
                count=hits,
                hp_scaled_damage=target_health_damage,
                time_offset=first_delay,
                hit_interval=interval if hits > 1 else None,
            ),
        )
        entry["empowers_next_auto"] = {
            "hits": hits,
            "authored_timing": {
                "first_attack_delay": first_delay,
                "attack_interval": interval,
            },
        }
    return entry


def _shadow_dash(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: one champion hit at the selected dash travel time, plus Ki
    Barrier's self-shield (P), which the cached notes name as one of the
    dash's own completion triggers.

    Ki Barrier deals no damage of its own, so it cannot host
    ``self_shield_events`` on a standalone entry (the payload requires a
    damage-emitting host). E is the first ability to complete in this
    module's certified E-then-Q order, and Ki Barrier's 11s flat cooldown
    outlasts a whole one-rotation fight, so attaching the shield here
    prices exactly the one grant a real fight would produce and Q's own
    later completion is not double-counted.
    """
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked

    distance = min(600.0, max(300.0, float(ctx.option("e_dash_distance"))))
    speed = _E_BASE_SPEED + ctx.stat("move_speed")
    travel = distance / speed if speed > 0 else 0.0
    total = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank) + travel,
        total,
        "physical",
    )
    entry["parts"] = (DamagePart("physical", total, time_offset=travel),)
    entry["resource_restore"] = _energy_restore(ctx.level)
    entry["detail"] = f"champion hit after {travel:.2f}s dash"
    # Ki Barrier fires "after completing an ability's effects", and E is the
    # module's first cast (CAST_ORDER), so the sourced self-shield rides it.
    # A shield-only slot has no channel of its own — ``attach_self_shield``
    # needs a damage event to ride (slotlib) and a passive is never cast.
    shield = _ki_barrier_shield_amount(ctx)
    return attach_self_shield(
        entry,
        amount=shield,
        duration=_P_SHIELD_DURATION_SECONDS,
        source="Ki Barrier",
        detail=(
            f"{entry['detail']}; Ki Barrier (P) also shields Shen for "
            f"{shield:g} for {_P_SHIELD_DURATION_SECONDS:g}s once the dash "
            "ends (sourced per-level base + 13% bonus health; the 11s flat "
            "cooldown caps this at one grant per one-rotation fight)"
        ),
    )


def _spirits_refuge(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: attack-block zone — documented zero-damage row (no_damage).

    The cached ability carries an empty ``leveling`` list — no damage,
    heal, or shield attribute at all, only a rank-scaled cost/cooldown.
    The zone blocks incoming basic attacks (and basic-damage abilities)
    rather than dealing or granting any HP number, so there is nothing for
    this champion's own outgoing SLOTS map to price.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    return no_damage(
        ctx,
        name=ability_name(ability),
        reason=(
            "Spirit's Refuge primes a protective zone that blocks all "
            "non-turret basic attacks (and basic-damage abilities) hitting "
            "Shen or allied champions inside it for 1.75s; the cached W "
            "entry carries no damage/heal/shield leveling row at all "
            "(data/champions.json Shen W). This engine's attack-block "
            "defense convention (interaction_effects.py's "
            "ProjectileDefense.blocks_basic_attacks, used by Jax's Counter "
            "Strike and Fiora's Riposte) lives on the defender side of a "
            "champion-vs-champion interaction, not in a champion's own "
            "outgoing SLOTS map, so the zone is priced as an explicit "
            "zero-HP-number state rather than left silently absent."
        ),
    )


OPTIONS = [
    bool_option("q_spirit_blade_hit", True, label="Q blade passes through a champion"),
    int_option(
        "q_attacks_landed", 3, minimum=0, maximum=3, label="Q empowered attacks landed"
    ),
    float_option(
        "q_first_attack_delay",
        0.5,
        minimum=0.0,
        maximum=2.0,
        label="Delay to first Q attack (seconds)",
        step=0.1,
    ),
    float_option(
        "e_dash_distance",
        600.0,
        minimum=300.0,
        maximum=600.0,
        label="E dash distance",
        step=50.0,
    ),
]

ASSUMPTIONS = [
    "The standard damage order is E, then Q empowered attacks.",
    "Q attack count and first-attack delay are selected explicitly; enhanced "
    "Q uses its sourced 50% bonus attack speed for spacing.",
    "Each landed Q attack and E champion hit restores the sourced level-based "
    "energy amount.",
    "Timed fights cap Q casts at the ambient swings that consume them; each "
    "bonus instance is an authored event on the module's swing schedule "
    "(selected first-attack delay, then the enhanced cadence), and the "
    "consumed swings themselves are shown on the Q row at the auto stream's "
    "per-hit damage.",
    "Ki Barrier (P) has no cast of its own; its sourced self-shield "
    "(per-level base + 13% bonus health) is attached to Shadow Dash (E), the "
    "first ability to complete in the certified E-then-Q order, since its 11s "
    "flat cooldown allows only one grant per one-rotation fight.",
    "Spirit's Refuge (W) is a pure attack-block zone with no damage, heal or "
    "shield attribute in the cached data; it emits an explicit zero-damage "
    "state row rather than staying silently absent, because the engine's "
    "attack-block convention lives on the defender side of an interaction.",
    "Stand United (R) deals no damage; the ally-support scanner prices its "
    "sourced shield floor (Minimum Shield Strength + 135% AP + 15% of his "
    "bonus health).  The 0-60% missing-health ramp to the Maximum row is a "
    "live-health condition the scan cannot establish, and the 3-second "
    "channel's teleport is not modeled.",
]

SOURCES = load_champion_sources("Shen")

CAST_ORDER = ["E", "Q", "R"]
SLOTS = {
    "E": _shadow_dash,
    "Q": _twilight_assault,
    "W": _spirits_refuge,
    # Stand United shields the target ally ("granting the target allied
    # champion a shield for 5 seconds at the time of cast").  The slot
    # exists so the rotation casts it and the support scanner can price the
    # shield; the sourced floor ("Minimum Shield Strength" 120/220/320 +
    # 135% AP + 15% of his bonus health) is what is priced, because the
    # "increased by 0% : 60% (based on target's missing health)" that
    # separates it from the maximum is a live-health condition.
    "R": support_cast(
        default_name="Stand United",
        detail="Ally shield (sourced by the support scanner) at its "
        "sourced floor; the 0-60% missing-health increase and the "
        "3-second channel's teleport are not modeled.",
    ),
}

# Reviewed crowd control, read from the cached kit.  Q (Twilight Assault):
# "Enemy champions hit by the Spirit Blade along its path are slowed for
# the next 2 seconds while moving away from Shen" — the blade recall
# applies the slow, and the empowered attacks this row prices land on that
# same target.  E (Shadow Dash): "dealing physical damage to enemy
# champions and monsters he passes through and taunting them for 1.5
# seconds".  Both rows already carry their authored swing/dash timing, so
# the declaration rides an event the ledger can see.
MODULE_CC = {"E": "taunt", "Q": "slow"}

parse_abilities = build_parser(SLOTS, "Shen", cc_kinds=MODULE_CC)

# P emits no cast row of its own; the Ki Barrier shield E carries is what
# the engine prices.  W emits an explicit zero-damage state row: its cached
# entry carries no HP number at all, and the attack block it does apply lives
# on the defender side of an interaction, not in this outgoing slot map.
MODULE_COVERAGE = coverage(no_damage="W")
COVERAGE_CHANNELS = {"P": ("self_shield_events",)}
