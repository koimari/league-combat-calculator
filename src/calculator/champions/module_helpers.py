"""Small, typed helpers shared by named champion modules.

The helpers deliberately accept the cached ability JSON instead of carrying a
second table of values.  That keeps rank, level, resource and cooldown values
on the revision-pinned Wiki packet and makes a missing source field fail
closed in the same place as the other reviewed modules.  This module owns no
champion membership or champion-specific formulas.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from typing import Any

from ..ability_spec import DamagePart
from .engine import AMP, DAMAGE, SlotCtx, SlotParser
from .slotlib import (
    MODULE_FORMULA_ZERO,
    ProcDamageResolver,
    ability_name,
    damage_entry,
    extract_cooldown,
    extract_named,
    find_named_leveling,
    simple_damage,
)

REVIEWED_MODULE_ASSUMPTIONS = (
    "Every passive/Q/W/E/R slot was reviewed against the complete parent Wiki "
    "entry and its five namespace-10 template receipts.",
    "Only the explicit one-rotation target/variant options are priced; utility, "
    "control, movement, healing and defensive state remain named rather than "
    "guessed.",
    "All numeric rank/level values are read from the cached source JSON through typed extractors.",
)


def typed_damage(
    ctx: SlotCtx,
    attribute: str,
    damage_type: str,
    *,
    count: int = 1,
    time_offset: float | None = None,
    hit_interval: float | None = None,
    rank_override: int | None = None,
    source_slot: str | None = None,
) -> dict[str, Any] | None:
    """Build one explicitly named typed packet from cached champion data."""

    slot = source_slot or ctx.slot
    ability = ctx.ability(slot)
    if ability is None:
        return None
    selected = rank_override if rank_override is not None else ctx.rank_for(slot)
    if slot == "P" and rank_override is None:
        selected = ctx.level
    if selected < 1:
        return None
    value = extract_named(ability, attribute, selected, ctx.stats, ctx.target)
    entry = damage_entry(
        str(ability.get("name", slot)),
        selected,
        extract_cooldown(ability, selected),
        value * max(1, count),
        damage_type,
    )
    entry["parts"] = (
        DamagePart(
            damage_type,
            value,
            count=max(1, count),
            time_offset=time_offset,
            hit_interval=hit_interval,
        ),
    )
    return entry


def ranked_slot(
    body: Callable[[SlotCtx, dict[str, Any], int], dict[str, Any] | None],
) -> SlotParser:
    """A slot that prices nothing until learned; *body* gets its ``(ability, rank)``."""

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        ranked = ctx.ranked()
        if ranked is None:
            return None
        return body(ctx, *ranked)

    # Not functools.wraps: a ``__wrapped__`` would make pylint read a direct
    # ``slot(ctx)`` call against the body's three-parameter signature.
    parse.__name__, parse.__qualname__ = body.__name__, body.__qualname__
    parse.__doc__, parse.__module__ = body.__doc__, body.__module__
    return parse


def delayed(parser: SlotParser, *, delay: float) -> SlotParser:
    """Wrap a slot so every part it emits lands *delay* seconds after the cast start.

    ``DamagePart.time_offset`` is seconds from the cast start, so an ability
    the cache places on a post-cast delay authors that number here rather
    than certifying a cast-boundary hit it does not have.  Where the cached
    entry says the delay excludes the cast time, the caller adds the cached
    ``castTime`` and passes the sum, because the champion module is what
    knows its source's convention.
    """

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        entry = parser(ctx)
        if entry is None:
            return None
        entry["parts"] = tuple(
            replace(part, time_offset=delay) for part in entry.get("parts", ())
        )
        return entry

    parse.phase = getattr(parser, "phase", DAMAGE)
    return parse


def delayed_damage(*, delay: float, **simple_damage_kwargs: Any) -> SlotParser:
    """A :func:`slotlib.simple_damage` slot, :func:`delayed`."""
    return delayed(simple_damage(**simple_damage_kwargs), delay=delay)


def named_damage(  # pylint: disable=too-many-arguments
    attr: str,
    dmg_type: str,
    *,
    ticks: int | None = None,
    time_offset: float | None = None,
    hit_interval: float | None = None,
    crit_effectiveness: float = 0.0,
    basic_damage: bool = False,
    **entry_keys: Any,
) -> SlotParser:
    """A slot pricing one named row of its cached entry at the slot's rank.

    The row is one cast's whole damage; ``ticks`` delivers it as that many
    even hits (the Cassiopeia rule).  The part keywords author the hit, and
    every other keyword lands on the entry as-is (``detail``,
    ``event_order_certified``, ``empowers_next_auto``, ...), in the order
    written; the engine's entry-key check refuses a misspelling.
    """

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        ranked = ctx.ranked()
        if ranked is None:
            return None
        ability, selected = ranked
        value = extract_named(ability, attr, selected, ctx.stats, ctx.target)
        entry = damage_entry(
            ability_name(ability),
            selected,
            extract_cooldown(ability, selected),
            value,
            dmg_type,
        )
        entry["parts"] = (
            DamagePart(
                dmg_type,
                value / ticks if ticks else value,
                count=ticks or 1,
                time_offset=time_offset,
                hit_interval=hit_interval,
                crit_effectiveness=crit_effectiveness,
                basic_damage=basic_damage,
                zero_policy=MODULE_FORMULA_ZERO,
            ),
        )
        entry.update(entry_keys)
        return entry

    parse.phase = DAMAGE
    return parse


def with_detail(detail: str) -> Callable[[SlotParser], SlotParser]:
    """Wrap a slot so the row it emits carries *detail*."""

    def wrap(parser: SlotParser) -> SlotParser:
        def parse(ctx: SlotCtx) -> dict[str, Any] | None:
            entry = parser(ctx)
            if entry is None:
                return None
            entry["detail"] = detail
            return entry

        return parse

    return wrap


def amp_slot(option: str, apply: Callable[[dict[str, Any]], None]) -> SlotParser:
    """An AMP pseudo-slot: with *option* on, *apply* rewrites every Q/W/E/R entry."""

    def parse(ctx: SlotCtx) -> None:
        if not ctx.option(option):
            return
        for key in ("Q", "W", "E", "R"):
            entry = ctx.results.get(key)
            if entry is not None:
                apply(entry)

    parse.phase = AMP
    return parse


def with_item_on_hit_specs(
    parse_abilities: Callable[..., dict[str, Any]],
    specs: Mapping[str, Mapping[str, Any]],
) -> Callable[..., dict[str, Any]]:
    """Wrap a parser so each listed slot's row declares its wiki-sourced item on-hits."""

    def parse(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = parse_abilities(*args, **kwargs)
        for slot, spec in specs.items():
            entry = result.get(slot) or (result.get("passive") if slot == "P" else None)
            if entry is not None:
                entry["applies_item_on_hits"] = dict(spec)
        return result

    # The wrapper is the module's published parser, so it republishes the
    # wiring the inner parser holds — the contract proves declaration and
    # wiring are one dict off whichever function the module exports.
    parse.cc_kinds = parse_abilities.cc_kinds
    return parse


def mixed_damage(
    _ctx: SlotCtx,
    name: str,
    rank_value: int,
    cooldown: float,
    magic: float,
    true_damage: float,
    *,
    detail: str,
) -> dict[str, Any]:
    """Build an explicitly split magic/true damage receipt."""

    parts = (DamagePart("magic", magic), DamagePart("true", true_damage))
    return {
        "name": name,
        "rank": rank_value,
        "cooldown": cooldown,
        "damage_type": "mixed",
        "total_raw": magic + true_damage,
        "parts": parts,
        "detail": detail,
    }


def rank(ctx: SlotCtx) -> int:
    """Return the selected skill rank, or zero when the slot is unlearned."""

    return ctx.rank_for() if ctx.slot != "P" else ctx.level


def clamp(value: float, lower: float, upper: float) -> float:
    """Clamp *value* into ``[lower, upper]``."""

    return min(upper, max(lower, value))


def missing_hp_fraction(ctx: SlotCtx) -> float:
    """The shared ``target_missing_hp_pct`` option as a 0..1 fraction."""

    return clamp(float(ctx.option("target_missing_hp_pct")), 0.0, 100.0) / 100.0


def buff_window_share(ctx: SlotCtx, duration: float) -> float:
    """Share of the fight window a self-buff lasting *duration* covers.

    ``fight_duration_seconds`` is zero in one-rotation mode and in a direct
    parse call, so with no window the whole bonus lands."""

    window = float(ctx.option("fight_duration_seconds"))
    if window <= duration:
        return 1.0
    return duration / window


def ability_cast_times(
    ctx: SlotCtx, duration: float, slots: Sequence[str]
) -> list[tuple[float, str]]:
    """``(time, slot)`` for each ability cast a timed fight schedules.

    A stack walk that counts *casts* needs the schedule before the fight
    runs it, so it mirrors the rotation the way Braum's passive does: each
    learned slot casts at t=0 and again every hasted cooldown, giving the
    ``1 + duration // cd`` count the rotation computes.  One set of hands,
    cast times, item cooldown refunds and resource exhaustion are not
    mirrored — the same approximation the Braum-pattern walks declare —
    and ties break on ``slots`` order.  An ``auto_attacks_only`` window
    schedules no casts at all, so the stream is empty.
    """
    if ctx.option("auto_attacks_only"):
        return []
    # Deferred: damage.py imports champion modules that import this one.
    # pylint: disable-next=import-outside-toplevel,cyclic-import
    from ..damage import effective_cooldown

    casts: list[tuple[float, int]] = []
    for index, slot in enumerate(slots):
        ability = ctx.ability(slot)
        slot_rank = ctx.rank_for(slot)
        if ability is None or slot_rank < 1:
            continue
        haste = ctx.stat("ability_haste")
        if slot != "R":
            haste += ctx.stat("basic_ability_haste")
        cooldown = effective_cooldown(extract_cooldown(ability, slot_rank), haste)
        count = 1 + int(duration / cooldown) if cooldown > 0 else 1
        casts.extend((step * cooldown, index) for step in range(count))
    casts.sort()
    return [(time, slots[index]) for time, index in casts]


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


def no_damage_parser(
    slot: str, reason: str = "No enemy damage is listed for this ability."
):
    """Build a slot parser emitting an explicit zero-damage entry.

    Unlike ``no_damage`` this is not rank-gated and carries no cooldown: a
    state/utility slot keeps its named row even at rank 0 so the reason stays
    user-visible.
    """

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


def rank_gated_no_damage_parser(
    slot: str, reason: str = "No enemy damage is listed for this ability."
):
    """A :func:`no_damage_parser` row that is ABSENT while unlearned.

    The engine rotates every slot at every rank, so a heal/cleanse-only
    ultimate (Milio R, Olaf R) would otherwise book a cast at rank 0 and
    let its heal rule fire off the clamped last row.
    """
    inner = no_damage_parser(slot, reason=reason)

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        if ctx.rank_for() < 1:
            return None
        return inner(ctx)

    parse.phase = "damage"
    return parse


def no_damage_slot(reason: str) -> SlotParser:
    """A slot whose cached row prices no enemy damage: its named, rank-gated zero row."""

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        ability = ctx.ability()
        if ability is None:
            return None
        return no_damage(ctx, name=ability_name(ability), reason=reason)

    parse.phase = DAMAGE
    return parse


def level_row(attr: str) -> ProcDamageResolver:
    """A proc resolver reading *attr* at the champion's level: an innate's per-level row."""

    def resolve(ctx: SlotCtx, ability: dict[str, Any]) -> float:
        return extract_named(ability, attr, ctx.level, ctx.stats, ctx.target)

    return resolve


def require_named_leveling(
    champion: str, ability: dict[str, Any], attribute: str
) -> None:
    """Fail loud when the named leveling row is absent (cache corruption)."""
    if find_named_leveling(ability, attribute) is None:
        raise KeyError(
            f"{champion} {ability_name(ability)} has no {attribute!r} leveling row"
        )


def at_level(brackets: Sequence[tuple[int, Any]], level: int) -> Any:
    """The value of the highest bracket *level* has reached; *brackets* descend by level."""
    for min_level, value in brackets:
        if level >= min_level:
            return value
    return brackets[-1][1]
