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
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .scaling import is_flat_unit, resolve_scaling
from .slotlib import damage_entry, extract_cooldown, extract_named

_Q_ATTACKS = 3
_Q_ENHANCED_BONUS_ATTACK_SPEED = 50.0
_E_BASE_SPEED = 800.0


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
    cooldown = extract_cooldown(ability, rank)
    entry = damage_entry(
        ability.get("name", "Twilight Assault"),
        rank,
        cooldown,
        per_hit * hits,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", per_hit, count=hits),) if hits else ()
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
    """E: one champion hit at the selected dash travel time."""
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
    entry["detail"] = f"champion hit after {travel:.2f}s dash"
    return entry


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
    "Ki Barrier, Spirit's Refuge, and Stand United deal no damage and are "
    "excluded from outgoing TDD.",
]

SOURCES = [
    {
        "label": "Shen — Twilight Assault",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Shen/Twilight_Assault",
        "revision_id": 4008038,
        "revision_timestamp": "2026-04-13T04:23:20Z",
    },
    {
        "label": "Shen — Shadow Dash",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Shen/Shadow_Dash",
        "revision_id": 4007754,
        "revision_timestamp": "2026-04-12T14:09:29Z",
    },
]

CAST_ORDER = ["E", "Q"]
SLOTS = {"E": _shadow_dash, "Q": _twilight_assault}

parse_abilities = build_parser(SLOTS, "Shen")
