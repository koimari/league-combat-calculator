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
from dataclasses import dataclass
from typing import Any

from ..ability_spec import DamagePart
from ..cast_dependency import CastDependency, validate_cast_dependencies
from .engine import SlotCtx, build_parser
from .module_helpers import no_damage_parser
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
    "Rank arrays, typed target-health terms, and packet variants remain "
    "sourced from the local reviewed-packet asset; the cooldown of each "
    "cast is read from the champion cache at the rank being cast.",
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
    """Resolved slot parsers plus the evidence declaration they compile.

    ``cast_dependencies`` rides here rather than in the digest: the module
    that accepts this evidence also declares the ordering rules it implies,
    and ``contract_from_module`` reads them off this carrier (P5-a).  It is
    keyword-only, so the positional signature is the ``(packet_spec,
    packet_sha256)`` pair it has always been and a third positional
    argument stays a ``TypeError`` rather than silently becoming a
    declaration.
    """

    def __init__(
        self,
        packet_spec: dict[str, Any],
        packet_sha256: str,
        *,
        cast_dependencies: tuple[CastDependency, ...] = (),
    ):
        super().__init__()
        self.packet_spec = packet_spec
        self.packet_sha256 = packet_sha256
        self.cast_dependencies = cast_dependencies


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
        per_tick = extract_named(
            ability, attr, rank, ctx.stats, ctx.target, level=ctx.level
        )
        entry = damage_entry(
            name or ability.get("name", f"Ability {ctx.slot}"),
            rank,
            extract_cooldown(ability, rank, level=ctx.level),
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
        initial = extract_named(
            ability, initial_attr, rank, ctx.stats, ctx.target, level=ctx.level
        )
        per_tick = extract_named(
            ability, tick_attr, rank, ctx.stats, ctx.target, level=ctx.level
        )
        entry = damage_entry(
            name or ability.get("name", f"Ability {ctx.slot}"),
            rank,
            extract_cooldown(ability, rank, level=ctx.level),
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
        full = extract_named(
            ability, full_attr, rank, ctx.stats, ctx.target, level=ctx.level
        )
        reduced = extract_named(
            ability, reduced_attr, rank, ctx.stats, ctx.target, level=ctx.level
        )
        entry = damage_entry(
            name or ability.get("name", f"Ability {ctx.slot}"),
            rank,
            extract_cooldown(ability, rank, level=ctx.level),
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


def _packet_cooldown(ctx: SlotCtx, spec: dict[str, Any], slot: str, rank: int) -> float:
    """The cast's cooldown from ``data/champions.json``: the packet holds rank 1."""
    source = tuple(spec["source"]) if spec.get("source") else (slot, 0)
    ability = ctx.ability(*source)
    return extract_cooldown(ability, rank, level=ctx.level) if ability else 0.0


def _one_hit(spec: dict[str, Any]) -> bool:
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
            static += value * float(ctx.stat(stat_key))
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


def _apply_slot_overrides(
    champion_name: str,
    slots: PacketSlotMap,
    slot_parsers: dict[str, Any] | None,
    slot_wrappers: dict[str, Any] | None,
    slot_order: tuple[str, ...] | None,
) -> None:
    """Apply a module's slot overrides to the compiled map, in place.

    Raises:
        KeyError: ``slot_wrappers`` or ``slot_order`` names a slot that
            neither the packet nor ``slot_parsers`` compiled.
    """
    for slot, custom in (slot_parsers or {}).items():
        slots[slot] = custom
    for slot, wrap in (slot_wrappers or {}).items():
        if slot not in slots:
            raise KeyError(
                f"{champion_name} slot_wrappers names {slot!r}, which neither the "
                f"packet nor slot_parsers compiled (slots are {sorted(slots)})"
            )
        slots[slot] = wrap(slots[slot])
    if slot_order is not None:
        unknown = [slot for slot in slot_order if slot not in slots]
        if unknown:
            raise KeyError(
                f"{champion_name} slot_order names {unknown}, which neither the "
                f"packet nor slot_parsers compiled (slots are {sorted(slots)})"
            )
        ordered = {slot: slots[slot] for slot in slot_order}
        slots.clear()
        slots.update(ordered)


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
    spec: dict[str, Any], slot: str, overrides: SlotOverrides
) -> tuple[Any, dict[str, Any]]:
    """A variants slot: the parser that reads its option, and that option."""
    variants = spec["variants"]
    parsers = _variant_parsers(variants, slot, overrides)
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
    return select_variant, {
        "key": option_key,
        "type": "int",
        "default": int(spec.get("default", 0)),
        "label": f"{slot} packet variant",
        "min": 0,
        "max": len(variants) - 1,
    }


def _compiled_slot(
    spec: dict[str, Any], slot: str, overrides: SlotOverrides
) -> tuple[Any, dict[str, Any] | None]:
    """One declared slot's parser, and the option it publishes if it has one.

    Only a variants slot publishes an option; every other kind answers
    ``None``, so the caller appends without asking what kind it compiled.
    A spec whose ``kind`` this does not know compiles to a no-damage slot
    with the generic reason rather than to nothing.
    """
    single_hit = slot in overrides.single_hit_slots
    if spec.get("kind") == "variants" and spec.get("variants"):
        return _variant_slot(spec, slot, overrides)
    if spec.get("kind") == "wiki_attribute":
        tick_fix = overrides.wiki_attribute_tick_fixes.get(slot)
        if tick_fix is not None:
            return _ticked_wiki_attribute_parser(spec, tick_fix), None
        return (
            simple_damage(
                attr=str(spec["attribute"]),
                dmg_type=str(spec.get("damage_type", "auto")),
                ranks=str(spec.get("ranks", "rank")),
                source=tuple(spec["source"]) if spec.get("source") else None,
                event_order_certified="single_hit" if single_hit else None,
            ),
            None,
        )
    if spec.get("kind") == "packet":
        return (
            _packet_parser(
                spec,
                slot,
                single_hit_certified=single_hit,
                tick_fix=overrides.packet_tick_fixes.get(str(spec.get("name", ""))),
                part_timing=overrides.packet_part_timings.get(slot),
            ),
            None,
        )
    if spec.get("kind") == "no_damage":
        return (
            no_damage_parser(
                slot,
                reason=str(
                    spec.get("reason", "No enemy damage is listed for this ability.")
                ),
            ),
            None,
        )
    return no_damage_parser(slot), None


def build_packet_module(
    champion_name: str,
    packet_sha256: str,
    *,
    assumption_overrides: tuple[str, ...] = (),
    single_hit_slots: frozenset[str] = frozenset(),
    packet_tick_fixes: dict[str, dict[str, Any]] | None = None,
    wiki_attribute_tick_fixes: dict[str, dict[str, Any]] | None = None,
    slot_parsers: dict[str, Any] | None = None,
    slot_wrappers: dict[str, Any] | None = None,
    slot_order: tuple[str, ...] | None = None,
    variant_parsers: dict[tuple[str, int], Any] | None = None,
    packet_part_timings: dict[str, dict[str, Any]] | None = None,
    cast_dependencies: tuple[CastDependency, ...] = (),
    cc_kinds: dict[str, str] | None = None,
):
    """Compile one named module's reviewed packet declaration.

    Champion-specific timing, parser, and assumption choices are passed by
    the named champion module.  This compiler contains no champion switchboard,
    and it is the only place a packet module's ``parse_abilities`` is built:
    the module never rebinds the parser, the slot map, or the packet pin it
    gets back, because the contract reads the pin off what this returns.

    Three keyword arguments override the compiled slot map, applied in this
    order once the packet is compiled:

    * ``slot_parsers`` — ``{slot: parser}`` replaces the compiled slot,
      whatever kind the packet gave it; a slot the packet does not compile
      (Riven's ``R_buff``, Vladimir's ``hemoplague`` amp) is appended.
    * ``slot_wrappers`` — ``{slot: factory}`` where ``factory(compiled)``
      returns the parser to use; for a module that prices the packet's own
      row and then adds to it (a self-shield, a certification, item on-hit
      application).  Naming a slot nothing compiled is an error.
    * ``slot_order`` — the module's slot surface in the order it is
      evaluated (within a phase, evaluation order is insertion order); a
      compiled slot the tuple leaves out is withheld from the module.

    ``single_hit_slots`` certifies a one-hit ``packet`` or ``wiki_attribute``
    slot at the cast boundary (variants certify per one-hit packet variant).
    Naming any other slot — a ``no_damage`` slot, a multi-hit packet, a
    ticked ``wiki_attribute`` row, a typo — is an error, since the
    certification would otherwise reach nothing.

    ``cc_kinds`` is the module's ``MODULE_CC`` declaration, handed to the
    same ``build_parser`` application every hand-written module uses so a
    packet champion reviews its crowd control in one place and not in its
    packet evidence — the evidence is what the Wiki says, the review is
    what the module says about it.  It rides the compiled parser too, so
    ``contract_from_module`` can prove the declaration and the wiring are
    one dict; a module that declares ``MODULE_CC`` and forgets to pass it
    here fails registration rather than reviewing nothing.

    ``cast_dependencies`` are the module's declared ordering prerequisites
    (``src/calculator/cast_dependency.py``).  They are deliberately **not**
    folded into ``packet_spec_sha256`` (P5-a): the digest pins reviewed
    evidence, and a dependency is a module-authored rule *about* that
    evidence carrying its own source, so folding it in would make every
    dependency edit read as evidence drift.  They are validated against
    the compiled slot surface — the same gate as the digest check — and
    attached to both carriers, so ``contract_from_module`` finds them
    whether it looks at the parser or the slot map.
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
    overrides = SlotOverrides(
        single_hit_slots=single_hit_slots,
        variant_parsers=variant_parsers or {},
        packet_tick_fixes=packet_tick_fixes or {},
        wiki_attribute_tick_fixes=wiki_attribute_tick_fixes or {},
        packet_part_timings=packet_part_timings or {},
    )
    uncertifiable = sorted(
        slot
        for slot in single_hit_slots
        if not _single_hit_row(
            champion.get("slots", {}).get(slot),
            ticked=slot in overrides.wiki_attribute_tick_fixes,
        )
    )
    if uncertifiable:
        raise KeyError(
            f"{champion_name} single_hit_slots names {uncertifiable}, which the "
            "packet compiles as no one-hit packet or wiki_attribute row "
            f"(slots are {sorted(champion.get('slots', {}))})"
        )
    slots = PacketSlotMap(champion, packet_sha256, cast_dependencies=cast_dependencies)
    options: list[dict[str, Any]] = []
    for slot in ("Q", "W", "E", "R", "P"):
        spec = champion.get("slots", {}).get(slot)
        if not spec:
            continue
        parser, option = _compiled_slot(spec, slot, overrides)
        slots[slot] = parser
        if option is not None:
            options.append(option)

    _apply_slot_overrides(champion_name, slots, slot_parsers, slot_wrappers, slot_order)

    # The digest above proves the evidence is the reviewed one; this
    # proves the declarations are about slots that evidence compiled.  A
    # dependency naming a slot this packet never built is a rule with no
    # referent, and only a declaring module can reach the raise (D-85).
    if cast_dependencies:
        validate_cast_dependencies(
            cast_dependencies, slot_surface=set(slots), module=champion_name
        )

    parser = build_parser(slots, champion_name, cc_kinds=cc_kinds)

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
    parse_abilities.cast_dependencies = cast_dependencies
    if cc_kinds is not None:
        parse_abilities.cc_kinds = parser.cc_kinds
    return parse_abilities, slots, assumptions, sources, options
