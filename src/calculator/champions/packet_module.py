"""Shared runtime for explicit, source-receipted Wiki/Axword champion packets.

Each champion module selects its own packet specification at build time.
This helper only evaluates those already-selected formulas; it does not
inspect attributes or choose an archetype at runtime.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .source_receipts import load_champion_sources
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    simple_damage,
)

_ROOT = Path(__file__).resolve().parents[3]
_PACKET_PATH = _ROOT / "static" / "reviewed-packets.json"

_FULL_ENTRY_ASSUMPTIONS = (
    "The complete parent Wiki entry was read before certifying this module.",
    "Passive plus Q/W/E/R entries are represented by explicit packet or "
    "no-damage slot declarations.",
    "Rank arrays, cooldowns, typed target-health terms, and packet variants "
    "remain sourced from the local reviewed-packet asset.",
    "Non-damaging shields, buffs, movement, and utility branches remain "
    "explicit state/out-of-scope rows rather than invented damage.",
)


def packet_spec_sha256(packet_spec: dict[str, Any]) -> str:
    """Canonical digest pinned by the named module that accepts this evidence."""

    payload = json.dumps(
        packet_spec, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class PacketSlotMap(dict[str, Any]):
    """Resolved slot parsers plus the evidence declaration they compile."""

    def __init__(self, packet_spec: dict[str, Any], packet_sha256: str):
        super().__init__()
        self.packet_spec = packet_spec
        self.packet_sha256 = packet_sha256


def repeat_damage_parser(
    *,
    attr: str,
    dmg_type: str,
    count: int,
    time_offset: float = 0.0,
    hit_interval: float = 0.0,
    dot_duration: float | None = None,
    name: str | None = None,
):
    """One per-tick attribute priced ``count`` times (E2-3 repeat fix).

    ``per_tick * count`` equals the wiki's "Total ..." row at every rank;
    the parts keep the per-tick amount and emit one event per tick.
    """

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        ability = ctx.ability()
        if ability is None:
            return None
        rank = ctx.rank_for()
        if rank < 1:
            return None
        per_tick = extract_named(ability, attr, rank, ctx.stats, ctx.target)
        entry = damage_entry(
            name or ability.get("name", f"Ability {ctx.slot}"),
            rank,
            extract_cooldown(ability, rank),
            per_tick * count,
            dmg_type,
        )
        entry["parts"] = (
            DamagePart(
                dmg_type,
                amount=per_tick,
                count=count,
                time_offset=time_offset,
                hit_interval=hit_interval,
            ),
        )
        if dot_duration is not None:
            # Ability damage continues past the cast (poison/zone ticks):
            # item burns stay refreshed for the tail (the Cassiopeia rule).
            entry["dot_duration"] = dot_duration
        return entry

    parse.phase = "damage"
    return parse


def initial_plus_ticks_parser(
    *,
    initial_attr: str,
    tick_attr: str,
    dmg_type: str,
    tick_count: int,
    time_offset: float,
    hit_interval: float,
    dot_duration: float | None = None,
    name: str | None = None,
):
    """One impact hit plus ``tick_count`` channel ticks (Viktor R).

    ``initial + tick_count * per_tick`` equals the wiki's "Total Magic
    Damage" row at every rank (impact + 6 storm bolts for Arcane Storm).
    """

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        ability = ctx.ability()
        if ability is None:
            return None
        rank = ctx.rank_for()
        if rank < 1:
            return None
        initial = extract_named(ability, initial_attr, rank, ctx.stats, ctx.target)
        per_tick = extract_named(ability, tick_attr, rank, ctx.stats, ctx.target)
        entry = damage_entry(
            name or ability.get("name", f"Ability {ctx.slot}"),
            rank,
            extract_cooldown(ability, rank),
            initial + per_tick * tick_count,
            dmg_type,
        )
        entry["parts"] = (
            DamagePart(dmg_type, amount=initial, time_offset=0.0),
            DamagePart(
                dmg_type,
                amount=per_tick,
                count=tick_count,
                time_offset=time_offset,
                hit_interval=hit_interval,
            ),
        )
        if dot_duration is not None:
            entry["dot_duration"] = dot_duration
        return entry

    parse.phase = "damage"
    return parse


def full_plus_reduced_parser(
    *,
    full_attr: str,
    reduced_attr: str,
    dmg_type: str,
    reduced_count: int,
    time_offset: float,
    hit_interval: float,
    dot_duration: float | None = None,
    name: str | None = None,
):
    """One full-strength hit plus ``reduced_count`` reduced hits.

    The wiki's "Total ..." row equals ``full + reduced_count * reduced``
    at every rank (Zac's initial bounce + 3 half bounces; Yuumi's first
    wave + 4 waves at 25% damage).
    """

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        ability = ctx.ability()
        if ability is None:
            return None
        rank = ctx.rank_for()
        if rank < 1:
            return None
        full = extract_named(ability, full_attr, rank, ctx.stats, ctx.target)
        reduced = extract_named(ability, reduced_attr, rank, ctx.stats, ctx.target)
        entry = damage_entry(
            name or ability.get("name", f"Ability {ctx.slot}"),
            rank,
            extract_cooldown(ability, rank),
            full + reduced * reduced_count,
            dmg_type,
        )
        entry["parts"] = (
            DamagePart(dmg_type, amount=full, time_offset=0.0),
            DamagePart(
                dmg_type,
                amount=reduced,
                count=reduced_count,
                time_offset=time_offset,
                hit_interval=hit_interval,
            ),
        )
        if dot_duration is not None:
            entry["dot_duration"] = dot_duration
        return entry

    parse.phase = "damage"
    return parse


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
                static += value * float(ctx.stats.get(stat_key, 0.0))

        damage_type = str(spec.get("damage_type", "magic"))
        if target_terms:
            target_max = float(ctx.target.get("target_max_health", 0.0))

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
            float(spec.get("cooldown", 0.0)),
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
        if single_hit_certified and int(spec.get("count", 1)) == 1:
            entry["event_order_certified"] = "single_hit"
        if spec.get("cast_time") is not None:
            entry["cast_time"] = float(spec["cast_time"])
        if spec.get("count", 1) != 1:
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


def _override_packet_static(ctx: SlotCtx, fix: dict[str, Any], rank: int) -> float:
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
            static += value * float(ctx.stats.get(stat_key, 0.0))
    return static


def _apply_packet_tick_fix(
    ctx: SlotCtx, entry: dict[str, Any], spec: dict[str, Any], fix: dict[str, Any]
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


def _ticked_wiki_attribute_parser(spec: dict[str, Any], fix: dict[str, Any]):
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
        )
        count = int(fix.get("count", 1))
        total = per_tick * count
        dmg_type = str(spec.get("damage_type", "auto"))
        if dmg_type == "auto":
            dmg_type = "magic"
        entry = damage_entry(
            ability.get("name", spec.get("name", f"Ability {ctx.slot}")),
            rank,
            extract_cooldown(ability, rank),
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


def _no_formula_parser(
    slot: str, *, reason: str = "No enemy damage is listed for this ability."
):
    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        ability = ctx.ability()
        if ability is None:
            return None
        return {
            "name": ability.get("name", f"Ability {slot}"),
            "rank": ctx.rank_for(),
            "cooldown": 0.0,
            "damage_type": "magic",
            "total_raw": 0.0,
            "parts": (),
            "detail": reason,
        }

    parse.phase = "damage"
    return parse


def build_packet_module(
    champion_name: str,
    packet_sha256: str,
    *,
    assumption_overrides: tuple[str, ...] = (),
    single_hit_slots: frozenset[str] = frozenset(),
    packet_tick_fixes: dict[str, dict[str, Any]] | None = None,
    wiki_attribute_tick_fixes: dict[str, dict[str, Any]] | None = None,
    slot_parsers: dict[str, Any] | None = None,
    variant_parsers: dict[tuple[str, int], Any] | None = None,
    packet_part_timings: dict[str, dict[str, Any]] | None = None,
):
    """Compile one named module's reviewed packet declaration.

    Champion-specific timing, parser, and assumption choices are passed by
    the named champion module.  This compiler contains no champion switchboard.
    """
    champion = _packet_specs().get(champion_name)
    if champion is None:
        raise KeyError(f"No reviewed packet specification for {champion_name!r}")
    actual_sha256 = packet_spec_sha256(champion)
    if actual_sha256 != packet_sha256:
        raise RuntimeError(
            f"{champion_name} packet evidence drifted: named module pins "
            f"{packet_sha256}, manifest provides {actual_sha256}"
        )
    packet_tick_fixes = packet_tick_fixes or {}
    wiki_attribute_tick_fixes = wiki_attribute_tick_fixes or {}
    slot_parsers = slot_parsers or {}
    variant_parser_overrides = variant_parsers or {}
    packet_part_timings = packet_part_timings or {}
    slots = PacketSlotMap(champion, packet_sha256)
    options: list[dict[str, Any]] = []
    for slot in ("Q", "W", "E", "R", "P"):
        spec = champion.get("slots", {}).get(slot)
        if not spec:
            continue
        variants = spec.get("variants") if spec.get("kind") == "variants" else None
        if variants:
            parsers = []
            for variant_index, variant in enumerate(variants):
                custom = variant_parser_overrides.get((slot, variant_index))
                if custom is not None:
                    parsers.append(custom)
                elif variant.get("kind") == "wiki_attribute":
                    parsers.append(
                        simple_damage(
                            attr=str(variant["attribute"]),
                            dmg_type=str(variant.get("damage_type", "auto")),
                            ranks=str(variant.get("ranks", "rank")),
                            source=(
                                tuple(variant["source"])
                                if variant.get("source")
                                else None
                            ),
                        )
                    )
                elif variant.get("kind") == "packet":
                    parsers.append(
                        _packet_parser(
                            variant,
                            slot,
                            single_hit_certified=slot in single_hit_slots,
                            tick_fix=packet_tick_fixes.get(
                                str(variant.get("name", ""))
                            ),
                            part_timing=packet_part_timings.get(slot),
                        )
                    )
                else:
                    parsers.append(
                        _no_formula_parser(
                            slot,
                            reason=str(
                                variant.get(
                                    "reason",
                                    "No enemy damage is listed for this variant.",
                                )
                            ),
                        )
                    )
            option_key = f"{slot.lower()}_variant"

            def select_variant(
                ctx: SlotCtx,
                parsers=tuple(parsers),
                key=option_key,
                default=spec.get("default", 0),
            ):
                try:
                    index = int(ctx.options.get(key, default))
                except (TypeError, ValueError):
                    index = int(default)
                index = max(0, min(index, len(parsers) - 1))
                return parsers[index](ctx)

            select_variant.phase = getattr(parsers[0], "phase", "damage")
            slots[slot] = select_variant
            options.append(
                {
                    "key": option_key,
                    "type": "int",
                    "default": int(spec.get("default", 0)),
                    "label": f"{slot} packet variant",
                    "min": 0,
                    "max": len(variants) - 1,
                }
            )
        elif spec.get("kind") == "wiki_attribute":
            tick_fix = wiki_attribute_tick_fixes.get(slot)
            custom = slot_parsers.get(slot)
            if tick_fix is not None:
                slots[slot] = _ticked_wiki_attribute_parser(spec, tick_fix)
            elif custom is not None:
                slots[slot] = custom
            else:
                slots[slot] = simple_damage(
                    attr=str(spec["attribute"]),
                    dmg_type=str(spec.get("damage_type", "auto")),
                    ranks=str(spec.get("ranks", "rank")),
                    source=tuple(spec["source"]) if spec.get("source") else None,
                )
        elif spec.get("kind") == "packet":
            custom = slot_parsers.get(slot)
            slots[slot] = (
                custom
                if custom is not None
                else _packet_parser(
                    spec,
                    slot,
                    single_hit_certified=slot in single_hit_slots,
                    tick_fix=packet_tick_fixes.get(str(spec.get("name", ""))),
                    part_timing=packet_part_timings.get(slot),
                )
            )
        elif spec.get("kind") == "no_damage":
            slots[slot] = _no_formula_parser(
                slot,
                reason=str(
                    spec.get("reason", "No enemy damage is listed for this ability.")
                ),
            )
        else:
            slots[slot] = _no_formula_parser(slot)
    parser = build_parser(slots, champion_name)

    def parse_abilities(*args, **kwargs):
        result = parser(*args, **kwargs)
        for entry in result.values():
            if "parts" in entry:
                continue
            entry["parts"] = ()
            entry.setdefault("total_raw", 0.0)
            on_hit = entry.get("on_hit") or {}
            entry.setdefault("damage_type", on_hit.get("damage_type", "physical"))
        return result

    assumptions = list(champion.get("assumptions", []))
    assumptions.extend(assumption_overrides)
    assumptions.extend(_FULL_ENTRY_ASSUMPTIONS)
    sources = load_champion_sources(champion_name)
    parse_abilities.packet_spec = champion
    parse_abilities.packet_sha256 = packet_sha256
    return parse_abilities, slots, assumptions, sources, options
