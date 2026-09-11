"""Shared runtime for explicit, source-receipted Wiki/Axword champion packets.

Each champion module selects its own packet specification at build time.
This helper only evaluates those already-selected formulas; it does not
inspect attributes or choose an archetype at runtime.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

from ..ability_spec import DamagePart
from ..cast_dependency import CastDependency, validate_cast_dependencies
from .charge_cadence import ChargeRule
from .engine import SlotCtx, SlotParser, build_parser
from .module_helpers import no_damage_parser
from .packet_parsers import (
    SlotOverrides,
    _packet_parser,
    _packet_specs,
    _single_hit_row,
    _ticked_wiki_attribute_parser,
    _variant_slot,
)
from .slot_entries import damage_entry
from .slot_extract import extract_cooldown, extract_named
from .slotlib import simple_damage
from .source_receipts import load_champion_sources

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
) -> SlotParser:
    """One per-tick attribute priced ``count`` times (E2-3 repeat fix).

    ``per_tick * count`` equals the wiki's "Total ..." row at every rank;
    the parts keep the per-tick amount and emit one event per tick.
    """

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        ranked = ctx.ranked()
        if ranked is None:
            return None
        ability, rank = ranked
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


def first_plus_repeats_parser(
    *,
    first_attr: str,
    repeat_attr: str,
    repeats: int,
    time_offset: float,
    hit_interval: float,
    dot_duration: float | None = None,
) -> SlotParser:
    """One hit at the cast plus ``repeats`` hits of a second row.

    ``first + repeats * repeat`` equals the wiki's "Total ..." row at every
    rank: an impact plus channel ticks (Viktor R's impact + 6 storm bolts),
    or a full-strength hit plus reduced ones (Zac's initial bounce + 3 half
    bounces; Yuumi's first wave + 4 waves at 25% damage).
    """

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        ranked = ctx.ranked()
        if ranked is None:
            return None
        ability, rank = ranked
        first = extract_named(
            ability, first_attr, rank, ctx.stats, ctx.target, level=ctx.level
        )
        repeat = extract_named(
            ability, repeat_attr, rank, ctx.stats, ctx.target, level=ctx.level
        )
        entry = damage_entry(
            ability.get("name", f"Ability {ctx.slot}"),
            rank,
            extract_cooldown(ability, rank, level=ctx.level),
            first + repeat * repeats,
            "magic",
        )
        entry["parts"] = (
            DamagePart("magic", amount=first, time_offset=0.0),
            DamagePart(
                "magic",
                amount=repeat,
                count=repeats,
                time_offset=time_offset,
                hit_interval=hit_interval,
            ),
        )
        if dot_duration is not None:
            entry["dot_duration"] = dot_duration
        return entry

    parse.phase = "damage"
    return parse


def _apply_slot_overrides(
    champion_name: str,
    slots: PacketSlotMap,
    slot_parsers: dict[str, Any] | None,
    slot_wrappers: dict[str, Any] | None,
    *,
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
    charge_rules: dict[str, ChargeRule] | None = None,
) -> tuple[
    Callable[..., dict[str, dict[str, Any]]],
    PacketSlotMap,
    list[str],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
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

    ``charge_rules`` is ``{slot: ChargeRule}``, the module's reviewed answer
    for each of its charge slots (``champions/charge_cadence.py``): a slot
    whose cached ability carries a ``rechargeRate`` prices that recharge as
    its cadence, and its compiled packet cannot, because the packet carries
    the short inter-cast timer the cache calls ``cooldown``.

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

    _apply_slot_overrides(
        champion_name, slots, slot_parsers, slot_wrappers, slot_order=slot_order
    )

    # The digest above proves the evidence is the reviewed one; this
    # proves the declarations are about slots that evidence compiled.  A
    # dependency naming a slot this packet never built is a rule with no
    # referent, and only a declaring module can reach the raise (D-85).
    if cast_dependencies:
        validate_cast_dependencies(
            cast_dependencies, slot_surface=set(slots), module=champion_name
        )

    parser = build_parser(
        slots, champion_name, cc_kinds=cc_kinds, charge_rules=charge_rules
    )

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


def _compiled_slot(
    spec: dict[str, Any], slot: str, overrides: SlotOverrides
) -> tuple[Any, dict[str, Any] | None]:
    """One declared slot's parser, and the option it publishes if it has one.

    Only a variants slot publishes an option; every other kind answers
    ``None``, so the caller appends without asking what kind it compiled.
    A spec whose ``kind`` this does not know compiles to a no-damage slot
    with the generic reason rather than to nothing.
    """
    if spec.get("kind") == "named_module":
        raise ValueError(f"{spec['name']} requires its named module: {spec['owner']}")
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
