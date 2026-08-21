"""Shen — sourced empowered-attack and energy timeline.

Twilight Assault is not cast damage: it modifies up to three subsequent
basic attacks with level-, rank-, AP-, and target-max-health-scaled magic
damage. The module therefore emits the bonus as a three-hit typed part and
declares the consumed basic attacks through ``empowers_next_auto``. In a
one-rotation calculation, those attacks are forced and timestamped exactly.
When a timed ambient auto stream is present, the damage remains included but
the result is explicitly partial until the shared auto schedule can couple the
same physical and magic instances.

Shadow Dash is authored at the selected travel distance. Its cooldown begins
after the dash, so travel time is added to the data's post-effect cooldown.

Roadmap session (2026-08-20): closes 2 of Shen's 3 out_of_scope slots (P, W);
R stays open with a named receipt.

  - P (Ki Barrier): sourced self-shield (``data/champions.json`` Shen P
    "Shield" leveling row: 47 : 128.59 based on LEVEL, flat, + 13% bonus
    health) granted "after completing an ability's effects", on an 11s flat
    cooldown NOT affected by ability haste (P's own cached cooldown row).
    Ki Barrier has no cast of its own — it rides whichever ability
    completes — so it cannot carry ``self_shield_events`` on a standalone
    "P" entry: that payload requires a host with its own nonzero damage
    events (``attach_self_shield``'s own contract; Ki Barrier deals none).
    The cached notes name Shadow Dash's own dash-end as one of Ki Barrier's
    triggers ("Shadow Dash will grant the shield when the dash ends"), and
    this module's certified order is E before Q ("The standard damage order
    is E, then Q empowered attacks"), so E is the FIRST ability to complete
    in a one-rotation fight — the shield is attached there. Ki Barrier's
    11-second flat cooldown is far longer than any one-rotation fight's
    total elapsed time, so at most one grant is possible regardless of how
    many abilities complete afterward; Q's own later completion (also a
    named trigger) is accordingly not double-counted. Reclassified from
    out_of_scope to modeled.
  - W (Spirit's Refuge): the cached ability carries `"leveling": []` for
    its only effect row (``data/champions.json`` Shen W) — no damage, heal,
    or shield numeric attribute of any kind; only its cost and cooldown
    scale by rank. The ability is a pure attack-block ZONE: "blocking all
    non-turret basic attacks that hit Shen or allied champions in the
    area" for 1.75s. This engine does carry a modeled "blocks basic
    attacks" defense convention (``interaction_effects.py``'s
    ``ProjectileDefense.blocks_basic_attacks``, used by Jax's Counter
    Strike and Fiora's Riposte) — so the underlying mechanic is not an
    unbuilt kernel — but that convention lives entirely on the DEFENDER
    side of a champion-vs-champion interaction (applied when the shielded
    champion is the one being attacked), not in a named champion's own
    outgoing SLOTS map, and wiring Shen into it means editing
    ``interaction_effects.py``, a file this session's scope is Shen-only
    and does not include. Reclassified from out_of_scope to no_damage (an
    atoms-confirmed zero-HP-number effect), not left silently absent.
  - R (Stand United): stays out_of_scope. The shield IS sourced
    (``data/champions.json`` Shen R "Minimum Shield Strength" 120/220/320
    + 135% AP + 15% of Shen's bonus health; "Maximum Shield Strength"
    192/352/512 + 216% AP + 24% of Shen's bonus health; description:
    "increased by 0% : 60% (based on target's missing health)" — Maximum
    is uniformly 1.6x Minimum at every rank, matching a linear ramp from
    the Minimum endpoint at 0% missing health to the Maximum endpoint at
    100%). Every number needed is cached, but wiring it is structurally
    blocked on three independent points, each named so a later session
    with a wider file scope can close it without re-deriving the audit:
    (1) It shields an ALLY, not Shen, so it does not fit
    ``attach_self_shield``'s self-shield contract, and Stand United has no
    outgoing damage of its own to host the payload on regardless (it is a
    channel + teleport, zero cast damage) — the module-authored-shield
    path used for P is unavailable here for the opposite reason.
    (2) The generic ally-support scanner (``support_effects.py``) only
    recognizes the attribute names "Shield Strength" / "Shield" / "Magic
    Shield Strength" (``_SUPPORT_ATTRIBUTES``); Stand United's "Minimum
    Shield Strength" / "Maximum Shield Strength" pair is not in that set,
    and the scanner's two typed formula helpers
    (``_target_max_health_shield_metadata``,
    ``_target_missing_health_heal_metadata``) each resolve ONE ratio
    against ONE health term — neither performs the two-endpoint linear
    interpolation Stand United's shield needs. Both are new scanner
    capability, not a one-line ``_CHAMPION_SHIELD_ATTR`` override, and
    ``support_effects.py`` is outside this session's Shen-only scope.
    (3) Even the source ratio's own unit string is a live blocker,
    verified directly: ``resolve_scaling("% of his bonus health", 15.0,
    {"bonus_health": 1000.0}, {})`` returns ``0.0`` — the phrasing "% of
    his bonus health" (not the "% bonus health" string P's row uses) is
    unmapped in ``scaling.py``'s unit table and silently resolves to zero
    rather than raising, so any shortcut reuse of the existing scaling
    helper would silently drop the bonus-health term. Stand United's
    teleport has no numeric representation in this engine at all (it is a
    position change, not a combat number) and is not priced by any slot.
"""

from dataclasses import replace
from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .module_helpers import no_damage
from .scaling import is_flat_unit, resolve_scaling
from .slotlib import (
    attach_self_shield,
    damage_entry,
    extract_cooldown,
    extract_named,
    find_named_leveling,
)

_Q_ATTACKS = 3
_Q_ENHANCED_BONUS_ATTACK_SPEED = 50.0
_E_BASE_SPEED = 800.0
_P_SHIELD_DURATION_SECONDS = 2.5


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
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    hits = min(
        _Q_ATTACKS,
        max(0, int(ctx.options.get("q_attacks_landed", _Q_ATTACKS))),
    )
    enhanced = bool(ctx.options.get("q_spirit_blade_hit", True))
    attribute = "Increased Bonus Damage" if enhanced else "Bonus Magic Damage"
    per_hit = _named_level_rank_damage(ctx, ability, attribute, rank)
    baseline_target_health = float(ctx.target.get("target_max_health", 0.0))
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
        ability.get("name", "Twilight Assault"),
        rank,
        cooldown,
        per_hit * hits,
        "magic",
    )
    entry["parts"] = (
        (
            DamagePart(
                "magic",
                per_hit,
                count=hits,
                hp_scaled_damage=target_health_damage,
            ),
        )
        if hits
        else ()
    )
    entry["target_max_health_sensitive"] = True
    entry["resource_restore"] = _energy_restore(ctx.level) * hits
    entry["detail"] = (
        f"{hits} {'enhanced' if enhanced else 'normal'} empowered attack"
        f"{'' if hits == 1 else 's'}"
    )
    if hits:
        attack_speed = ctx.stats.get("attack_speed", 0.0)
        if enhanced:
            attack_speed += ctx.stats.get("attack_speed_ratio", 0.0) * (
                _Q_ENHANCED_BONUS_ATTACK_SPEED / 100.0
            )
        first_delay = float(ctx.options.get("q_first_attack_delay", 0.5))
        interval = 1.0 / attack_speed if attack_speed > 0 else 0.0
        entry["empowers_next_auto"] = {
            "hits": hits,
            "authored_timing": {
                "first_attack_delay": first_delay,
                "attack_interval": interval,
            },
        }
        entry["requires_auto_timeline_coupling"] = True
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
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    distance = min(600.0, max(300.0, float(ctx.options.get("e_dash_distance", 600))))
    speed = _E_BASE_SPEED + ctx.stats.get("move_speed", 0.0)
    travel = distance / speed if speed > 0 else 0.0
    total = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Shadow Dash"),
        rank,
        extract_cooldown(ability, rank) + travel,
        total,
        "physical",
    )
    entry["parts"] = (DamagePart("physical", total, time_offset=travel),)
    entry["resource_restore"] = _energy_restore(ctx.level)
    shield = _ki_barrier_shield_amount(ctx)
    return attach_self_shield(
        entry,
        amount=shield,
        duration=_P_SHIELD_DURATION_SECONDS,
        source="Ki Barrier",
        detail=(
            f"champion hit after {travel:.2f}s dash; Ki Barrier (P) also "
            f"shields Shen for {shield:g} for {_P_SHIELD_DURATION_SECONDS:g}s "
            "once the dash ends (sourced per-level base + 13% bonus health; "
            "11s flat cooldown caps this at one grant per one-rotation fight)"
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
        name=ability.get("name", "Spirit's Refuge"),
        reason=(
            "Spirit's Refuge primes a protective zone that blocks all "
            "non-turret basic attacks (and basic-damage abilities) hitting "
            "Shen or allied champions inside it for 1.75s; the cached W "
            "entry carries no damage/heal/shield leveling row at all "
            "(data/champions.json Shen W). This engine's attack-block "
            "defense convention (interaction_effects.py's "
            "ProjectileDefense.blocks_basic_attacks, used by Jax's Counter "
            "Strike and Fiora's Riposte) lives on the defender side of a "
            "champion-vs-champion interaction, outside this Shen-only "
            "session's file scope, so the zone is priced as an explicit "
            "zero-HP-number state rather than left silently absent."
        ),
    )


OPTIONS = [
    {
        "key": "q_spirit_blade_hit",
        "type": "bool",
        "default": True,
        "label": "Q blade passes through a champion",
    },
    {
        "key": "q_attacks_landed",
        "type": "int",
        "default": 3,
        "label": "Q empowered attacks landed",
        "min": 0,
        "max": 3,
    },
    {
        "key": "q_first_attack_delay",
        "type": "float",
        "default": 0.5,
        "label": "Delay to first Q attack (seconds)",
        "min": 0.0,
        "max": 2.0,
        "step": 0.1,
    },
    {
        "key": "e_dash_distance",
        "type": "float",
        "default": 600.0,
        "label": "E dash distance",
        "min": 300.0,
        "max": 600.0,
        "step": 50.0,
    },
]

ASSUMPTIONS = [
    "The standard damage order is E, then Q empowered attacks.",
    "Q attack count and first-attack delay are selected explicitly; enhanced "
    "Q uses its sourced 50% bonus attack speed for spacing.",
    "Each landed Q attack and E champion hit restores the sourced level-based "
    "energy amount.",
    "Timed fights with ambient autos include Q damage but remain partial until "
    "the physical and magic instances share one coupled auto timeline.",
    "Ki Barrier (P) has no cast of its own; its sourced self-shield (per-level "
    "base + 13% bonus health) is attached to Shadow Dash (E), the first "
    "ability to complete in the certified E-then-Q order, since its 11s flat "
    "cooldown allows only one grant per one-rotation fight.",
    "Spirit's Refuge (W) is a pure attack-block zone with no damage, heal, or "
    "shield attribute in the cached data; it emits an explicit zero-damage "
    "state row (no_damage) rather than staying silently absent.",
    "Stand United (R)'s ally shield is sourced (Minimum/Maximum Shield "
    "Strength, base + AP + bonus health, ramped by the target's missing "
    "health) but is not yet wired: it shields an ally rather than Shen, the "
    "generic ally-support scanner does not recognize its attribute names or "
    "two-endpoint ramp, and its bonus-health unit string is unmapped in "
    "scaling.py — so it stays out_of_scope.",
]

SOURCES = [
    {
        "label": "Shen — Ki Barrier",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Shen/Ki_Barrier",
        "revision_id": 3985839,
        "revision_timestamp": "2026-01-21T19:55:43Z",
    },
    {
        "label": "Shen — Twilight Assault",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Shen/Twilight_Assault",
        "revision_id": 4008038,
        "revision_timestamp": "2026-04-13T04:23:20Z",
    },
    {
        "label": "Shen — Spirit's Refuge",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Shen/Spirit's_Refuge",
        "revision_id": 3977238,
        "revision_timestamp": "2025-12-18T16:34:14Z",
    },
    {
        "label": "Shen — Shadow Dash",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Shen/Shadow_Dash",
        "revision_id": 4007754,
        "revision_timestamp": "2026-04-12T14:09:29Z",
    },
    {
        "label": "Shen — Stand United",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Shen/Stand_United",
        "revision_id": 4004939,
        "revision_timestamp": "2026-04-02T19:26:56Z",
    },
]

CAST_ORDER = ["E", "Q"]
SLOTS = {"E": _shadow_dash, "Q": _twilight_assault, "W": _spirits_refuge}

parse_abilities = build_parser(SLOTS, "Shen")


# Authoritative review metadata (issue #161).
MODULE_COVERAGE = {
    "P": "modeled",
    "Q": "modeled",
    "W": "no_damage",
    "E": "modeled",
    "R": "out_of_scope",
}
REVIEW_STATUS = "reviewed_module"
