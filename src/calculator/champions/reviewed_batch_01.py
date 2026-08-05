"""Small, typed helpers shared by the first exact champion batch.

The helpers deliberately accept the cached ability JSON instead of carrying a
second table of values.  That keeps rank, level, resource and cooldown values
on the revision-pinned Wiki packet and makes a missing source field fail
closed in the same place as the other reviewed modules.
"""

from __future__ import annotations

from typing import Any, Callable

from ..ability_spec import DamagePart
from .engine import DAMAGE, SlotCtx
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
)


def rank(ctx: SlotCtx) -> int:
    """Return the selected skill rank, or zero when the slot is unlearned."""

    return ctx.rank_for() if ctx.slot != "P" else ctx.level


def level_value(ctx: SlotCtx, ability: dict[str, Any], attribute: str) -> float:
    """Read a per-level attribute from a passive."""

    return extract_value(ability, attribute, ctx.level)


def named_damage(
    ctx: SlotCtx,
    *,
    attribute: str,
    damage_type: str,
    source_slot: str | None = None,
    source_index: int = 0,
    rank_override: int | None = None,
    cooldown_from: tuple[str, int] | None = None,
    count: int = 1,
    time_offset: float | None = None,
    hit_interval: float | None = None,
) -> dict[str, Any] | None:
    """Build a typed packet from one named Wiki leveling attribute."""

    slot = source_slot or ctx.slot
    ability = ctx.ability(slot, source_index)
    if ability is None:
        return None
    selected_rank = rank_override if rank_override is not None else ctx.rank_for(slot)
    if slot == "P" and rank_override is None:
        selected_rank = ctx.level
    if selected_rank < 1:
        return None
    total = extract_named(
        ability,
        attribute,
        selected_rank,
        ctx.stats,
        ctx.target,
    )
    part = DamagePart(
        damage_type,
        amount=total,
        count=max(1, count),
        time_offset=time_offset,
        hit_interval=hit_interval,
    )
    entry = damage_entry(
        str(ability.get("name", f"Ability {slot}")),
        selected_rank,
        extract_cooldown(
            ctx.ability(*cooldown_from) if cooldown_from else ability,
            selected_rank,
        ),
        total * max(1, count),
        damage_type,
    )
    entry["parts"] = (part,)
    return entry


def target_health_part(
    ctx: SlotCtx,
    *,
    ability: dict[str, Any],
    attribute: str,
    flat_attribute: str | None,
    damage_type: str,
    rank: int,
    count: int = 1,
    time_offset: float | None = None,
    hit_interval: float | None = None,
) -> tuple[DamagePart, float]:
    """Split a source formula into flat and target-max-health components."""

    target_max = float(ctx.target.get("target_max_health", 0.0) or 0.0)
    total = extract_named(ability, attribute, rank, ctx.stats, ctx.target)
    flat = (
        extract_named(ability, flat_attribute, rank, ctx.stats, ctx.target)
        if flat_attribute
        else 0.0
    )
    ratio = (total - flat) / target_max if target_max > 0.0 else 0.0

    def scaled(_missing_ratio: float) -> float:
        return flat + ratio * target_max

    return (
        DamagePart(
            damage_type,
            amount=flat,
            count=max(1, count),
            hp_scaled_damage=scaled if target_max > 0.0 and ratio else None,
            time_offset=time_offset,
            hit_interval=hit_interval,
        ),
        total * max(1, count),
    )


def no_damage(
    ctx: SlotCtx,
    *,
    name: str,
    reason: str,
    slot: str | None = None,
    cooldown: float | None = None,
) -> dict[str, Any] | None:
    """Emit an explicit, user-visible state/utility row."""

    ability = ctx.ability(slot or ctx.slot)
    if ability is None:
        return None
    selected_rank = ctx.rank_for(slot or ctx.slot)
    if (slot or ctx.slot) == "P":
        selected_rank = ctx.level
    if selected_rank < 1:
        return None
    entry: dict[str, Any] = {
        "name": name,
        "rank": selected_rank,
        "cooldown": (
            float(cooldown)
            if cooldown is not None
            else extract_cooldown(ability, selected_rank)
        ),
        "damage_type": "magic",
        "total_raw": 0.0,
        "parts": (),
        "detail": reason,
    }
    return entry


def stamp_review_metadata(
    *,
    sources: list[dict[str, Any]],
    coverage: dict[str, str],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Keep source/coverage declarations immutable at module import time."""

    return list(sources), dict(coverage)


def source_row(
    label: str,
    url: str,
    revision_id: int,
    revision_timestamp: str,
) -> dict[str, Any]:
    """Create the canonical revision receipt shape used by /api/config."""

    return {
        "label": label,
        "url": url,
        "revision_id": revision_id,
        "revision_timestamp": revision_timestamp,
    }


def mark_damage(parser: Callable[[SlotCtx], dict[str, Any] | None]):
    """Annotate a local parser as a normal DAMAGE-phase slot."""

    parser.phase = DAMAGE
    return parser
