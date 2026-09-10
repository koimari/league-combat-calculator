"""The reviewed-packet asset, and the slot parser one of its rows compiles to."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx
from .module_helpers import no_damage_parser
from .slot_entries import damage_entry
from .slot_extract import extract_cooldown, extract_named
from .slotlib import simple_damage

_ROOT = Path(__file__).resolve().parents[3]


_PACKET_PATH = _ROOT / "static" / "reviewed-packets.json"


@lru_cache(maxsize=1)
def _packet_specs() -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(_PACKET_PATH.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Reviewed packet asset is unavailable: {_PACKET_PATH}"
        ) from exc
    champions = payload.get("champions") if isinstance(payload, dict) else None
    if not isinstance(champions, dict):
        raise RuntimeError("Reviewed packet asset has no champion map")
    return champions


def _ranked(values: list[float], rank: int) -> float:
    if not values:
        return 0.0
    return float(values[min(max(rank, 1) - 1, len(values) - 1)])


def _packet_cooldown(
    ctx: SlotCtx, spec: Mapping[str, Any], slot: str, rank: int
) -> float:
    """The cast's cooldown from ``data/champions.json``: the packet holds rank 1."""
    source = tuple(spec["source"]) if spec.get("source") else (slot, 0)
    ability = ctx.ability(*source)
    return extract_cooldown(ability, rank, level=ctx.level) if ability else 0.0


def _one_hit(spec: Mapping[str, Any]) -> bool:
    """Whether a packet row is exactly one hit (a packet without ``count`` is)."""
    return int(spec.get("count", 1)) == 1


def _packet_parser(
    spec: dict[str, Any],
    slot: str,
    *,
    single_hit_certified: bool = False,
    tick_fix: dict[str, Any] | None = None,
    part_timing: dict[str, Any] | None = None,
):
    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        ability = ctx.ability()
        if ability is None:
            return None
        rank = ctx.level if spec.get("ranks") == "level" else ctx.rank_for()
        if rank < 1:
            return None

        base = _ranked(spec.get("base", []), rank)
        static = base
        target_terms: list[tuple[str, float]] = []
        for ratio in spec.get("ratios", []):
            stat = str(ratio.get("stat", ""))
            value = _ranked(ratio.get("values", []), rank)
            if stat in {"targetMaxHp", "targetCurrentHp", "targetMissingHp"}:
                target_terms.append((stat, value))
                continue
            stat_key = {
                "ap": "ability_power",
                "ad": "attack_damage",
                "bonusAd": "bonus_attack_damage",
                "health": "health",
                "bonusHealth": "bonus_health",
                "armor": "armor",
                "magicResistance": "magic_resistance",
            }.get(stat)
            if stat_key:
                static += value * float(ctx.stat(stat_key))

        damage_type = str(spec.get("damage_type", "magic"))
        if target_terms:
            target_max = float(ctx.target_stat("target_max_health"))

            def hp_scaled(missing_ratio: float) -> float:
                current_ratio = max(0.0, 1.0 - missing_ratio)
                total = static
                for kind, value in target_terms:
                    if kind == "targetMaxHp":
                        total += value * target_max
                    elif kind == "targetCurrentHp":
                        total += value * target_max * current_ratio
                    else:
                        total += value * target_max * missing_ratio
                return total

            parts = (DamagePart(damage_type, hp_scaled_damage=hp_scaled),)
            total_raw = static
        else:
            parts = (DamagePart(damage_type, amount=static),)
            total_raw = static

        entry = damage_entry(
            ability.get("name", spec.get("name", f"Ability {slot}")),
            rank,
            _packet_cooldown(ctx, spec, slot, rank),
            total_raw,
            damage_type,
        )
        entry["parts"] = parts
        entry["total_raw"] = total_raw
        if part_timing is not None:
            entry["parts"] = tuple(
                DamagePart(
                    part.damage_type,
                    amount=part.amount,
                    count=int(part_timing.get("count", part.count)),
                    hp_scaled_damage=part.hp_scaled_damage,
                    time_offset=part_timing.get("time_offset", part.time_offset),
                    hit_interval=part_timing.get("hit_interval", part.hit_interval),
                )
                for part in entry["parts"]
            )
            entry["total_raw"] = total_raw * float(
                part_timing.get("total_multiplier", 1.0)
            )
        # A packet can certify a dynamic-health cast when the authored
        # packet is exactly one hit.  The damage engine still evaluates the
        # current target health at the cast boundary; there is no hidden
        # intra-cast ordering left to guess.  Multi-hit packets deliberately
        # keep the conservative cast-boundary marker until their hit timing
        # is sourced separately.
        if single_hit_certified and _one_hit(spec):
            entry["event_order_certified"] = "single_hit"
        if spec.get("cast_time") is not None:
            entry["cast_time"] = float(spec["cast_time"])
        if not _one_hit(spec):
            entry["parts"] = tuple(
                DamagePart(
                    part.damage_type,
                    amount=part.amount,
                    count=int(spec["count"]),
                    hp_scaled_damage=part.hp_scaled_damage,
                )
                for part in parts
            )
        if tick_fix is not None:
            entry = _apply_packet_tick_fix(ctx, entry, spec, tick_fix)
        return entry

    parse.phase = "damage"
    return parse


def _override_packet_static(ctx: SlotCtx, fix: Mapping[str, Any], rank: int) -> float:
    """Re-resolve a packet's per-hit base from an override (Nunu E).

    The pinned packet priced the wrong leveling row, so the fix carries the
    per-tick base and ratios from the same ability entry.  Returns the
    per-tick static damage the override prices.
    """
    base = _ranked(list(fix.get("base", [])), rank)
    static = base
    for ratio in fix.get("ratios", []):
        stat = str(ratio.get("stat", ""))
        value = _ranked(ratio.get("values", []), rank)
        stat_key = {
            "ap": "ability_power",
            "ad": "attack_damage",
            "bonusAd": "bonus_attack_damage",
            "health": "health",
            "bonusHealth": "bonus_health",
            "armor": "armor",
            "magicResistance": "magic_resistance",
        }.get(stat)
        if stat_key:
            static += value * float(ctx.stat(stat_key))
    return static


def _apply_packet_tick_fix(
    ctx: SlotCtx, entry: dict[str, Any], spec: Mapping[str, Any], fix: dict[str, Any]
) -> dict[str, Any]:
    """Price one full multi-tick cast instead of a single tick.

    The packet's ``base``/``ratios`` are per-tick values; the fix supplies
    the sourced count (and cadence) so per-tick damage x ticks == the wiki
    Total row at every rank.  Abilities with an initial hit keep that hit as
    a separate single part and append the ticked part from its own leveling
    attribute.
    """
    rank = ctx.level if spec.get("ranks") == "level" else ctx.rank_for()
    if "base" in fix:
        per_tick = _override_packet_static(ctx, fix, rank)
    else:
        per_tick = float(entry.get("total_raw", 0.0) or 0.0)

    extra = fix.get("extra_part")
    if extra is not None:
        ability = ctx.ability()
        extra_per_tick = (
            extract_named(
                ability,
                str(extra["attribute"]),
                rank,
                ctx.stats,
                ctx.target,
                level=ctx.level,
            )
            if ability is not None
            else 0.0
        )
        parts = (
            DamagePart(
                str(entry.get("damage_type", "magic")),
                amount=per_tick,
                time_offset=fix.get("initial_tick"),
            ),
            DamagePart(
                str(extra.get("damage_type", "magic")),
                amount=extra_per_tick,
                count=int(extra["count"]),
                time_offset=extra.get("first_tick"),
                hit_interval=extra.get("tick_interval"),
            ),
        )
        total = per_tick + extra_per_tick * int(extra["count"])
        entry["detail"] = (
            f"initial hit + {int(extra['count'])} sourced "
            f"{extra.get('tick_interval', '?')}s-interval ticks "
            f"({extra['attribute']} x{int(extra['count'])} = "
            f"{entry.get('name', '')} total)"
        )
        if extra.get("dot_duration") is not None:
            entry["dot_duration"] = float(extra["dot_duration"])
    else:
        count = int(fix.get("count", 1))
        first_tick = fix.get("first_tick")
        tick_interval = fix.get("tick_interval")
        parts = (
            DamagePart(
                str(entry.get("damage_type", "magic")),
                amount=per_tick,
                count=count,
                time_offset=first_tick,
                hit_interval=tick_interval,
            ),
        )
        total = per_tick * count
        entry["detail"] = (
            f"{count} sourced {tick_interval or '?'}s-interval "
            f"tick{'s' if count != 1 else ''} (per-tick x{count} = "
            f"{entry.get('name', '')} total)"
        )
        if fix.get("dot_duration") is not None:
            entry["dot_duration"] = float(fix["dot_duration"])

    entry["parts"] = parts
    entry["total_raw"] = total
    return entry


def _ticked_wiki_attribute_parser(spec: Mapping[str, Any], fix: Mapping[str, Any]):
    """A ``wiki_attribute`` slot whose value is per-tick (Nasus R).

    Reads the named per-tick attribute and multiplies by the sourced tick
    count so the entry prices the ability's full Total row with one event
    per tick.
    """

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        source = tuple(spec["source"]) if spec.get("source") else (ctx.slot, 0)
        ability = ctx.ability(*source)
        if ability is None:
            return None
        rank = ctx.level if spec.get("ranks") == "level" else ctx.rank_for(source[0])
        if rank < 1:
            return None
        per_tick = extract_named(
            ability,
            str(spec["attribute"]),
            rank,
            ctx.stats,
            ctx.target,
            level=ctx.level,
        )
        count = int(fix.get("count", 1))
        total = per_tick * count
        dmg_type = str(spec.get("damage_type", "auto"))
        if dmg_type == "auto":
            dmg_type = "magic"
        entry = damage_entry(
            ability.get("name", spec.get("name", f"Ability {ctx.slot}")),
            rank,
            extract_cooldown(ability, rank, level=ctx.level),
            total,
            dmg_type,
        )
        entry["parts"] = (
            DamagePart(
                dmg_type,
                amount=per_tick,
                count=count,
                time_offset=fix.get("first_tick"),
                hit_interval=fix.get("tick_interval"),
            ),
        )
        entry["total_raw"] = total
        entry["detail"] = (
            f"{count} sourced {fix.get('tick_interval', '?')}s-interval "
            f"tick{'s' if count != 1 else ''} ({spec['attribute']} x{count} "
            f"= {entry['name']} total)"
        )
        if fix.get("dot_duration") is not None:
            entry["dot_duration"] = float(fix["dot_duration"])
        return entry

    parse.phase = "damage"
    return parse


def _single_hit_row(spec: dict[str, Any] | None, *, ticked: bool) -> bool:
    """Whether ``single_hit_slots`` reaches a row this slot compiles.

    A one-hit ``packet`` row certifies, a ``wiki_attribute`` row certifies
    unless a tick fix rebuilt it, and a ``variants`` slot certifies through
    its one-hit packet variants.  A ``no_damage`` slot, a multi-hit packet,
    or a slot the packet never compiled has no row to certify, so naming it
    would certify nothing in silence.
    """
    if not spec:
        return False
    kind = spec.get("kind")
    if kind == "variants":
        return any(
            _single_hit_row(variant, ticked=False)
            for variant in spec.get("variants", ())
            if variant.get("kind") == "packet"
        )
    if kind == "wiki_attribute":
        return not ticked
    return kind == "packet" and _one_hit(spec)


@dataclass(frozen=True, slots=True)
class SlotOverrides:
    """The module-supplied tables one slot's compilation reads.

    One carrier rather than five parameters, because every step of the
    compile — the slot, its variants, a variant's own packet — reads the
    same five tables and threading them apart is how a step comes to read
    four of them.
    """

    single_hit_slots: frozenset[str]
    variant_parsers: dict[tuple[str, int], Any]
    packet_tick_fixes: dict[str, dict[str, Any]]
    wiki_attribute_tick_fixes: dict[str, dict[str, Any]]
    packet_part_timings: dict[str, dict[str, Any]]


def _variant_parsers(
    variants: list[dict[str, Any]], slot: str, overrides: SlotOverrides
) -> list[Any]:
    """One parser per declared variant of *slot*, in declaration order.

    A module-supplied override replaces the variant whatever kind it is;
    the rest compile from the variant's own ``kind`` exactly as a
    single-kind slot does.
    """
    parsers: list[Any] = []
    for variant_index, variant in enumerate(variants):
        custom = overrides.variant_parsers.get((slot, variant_index))
        if custom is not None:
            parsers.append(custom)
        elif variant.get("kind") == "wiki_attribute":
            parsers.append(
                simple_damage(
                    attr=str(variant["attribute"]),
                    dmg_type=str(variant.get("damage_type", "auto")),
                    ranks=str(variant.get("ranks", "rank")),
                    source=(
                        tuple(variant["source"]) if variant.get("source") else None
                    ),
                )
            )
        elif variant.get("kind") == "packet":
            parsers.append(
                _packet_parser(
                    variant,
                    slot,
                    single_hit_certified=slot in overrides.single_hit_slots,
                    tick_fix=overrides.packet_tick_fixes.get(
                        str(variant.get("name", ""))
                    ),
                    part_timing=overrides.packet_part_timings.get(slot),
                )
            )
        else:
            parsers.append(
                no_damage_parser(
                    slot,
                    reason=str(
                        variant.get(
                            "reason",
                            "No enemy damage is listed for this variant.",
                        )
                    ),
                )
            )
    return parsers


def _variant_slot(
    spec: Mapping[str, Any], slot: str, overrides: SlotOverrides
) -> tuple[Any, dict[str, Any]]:
    """A variants slot: the parser that reads its option, and that option."""
    variants = spec["variants"]
    parsers = _variant_parsers(variants, slot, overrides)
    option_key = f"{slot.lower()}_variant"

    def select_variant(
        ctx: SlotCtx,
        parsers=tuple(parsers),
        key=option_key,
        default=spec.get("default", 0),  # noqa: B008 - bound at definition
    ):
        try:
            index = int(ctx.options.get(key, default))
        except (TypeError, ValueError):
            index = int(default)
        index = max(0, min(index, len(parsers) - 1))
        return parsers[index](ctx)

    select_variant.phase = getattr(parsers[0], "phase", "damage")
    return select_variant, {
        "key": option_key,
        "type": "int",
        "default": int(spec.get("default", 0)),
        "label": f"{slot} packet variant",
        "min": 0,
        "max": len(variants) - 1,
    }
