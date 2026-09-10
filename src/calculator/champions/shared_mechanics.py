"""One home for each kit mechanic more than one champion repeats.

A shape several kits publish (a widened bolt's reduced secondary hits, a
ticked channel, a cast that rides the next basic attack, a self-shield with
no cast of its own) is modelled once here and configured by the champion
module, which keeps its own domain constants and its own published detail
string.  Every number is read from the cached ability JSON, so a missing
source row fails closed where the other reviewed helpers fail closed.

Downstream of :mod:`slotlib` and :mod:`module_helpers`, upstream of every
champion module: nothing here imports a champion.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from typing import Any

from ..ability_atoms import (
    AbilityAtomQuery,
    ranked_ability_atom_value,
    required_ability_atom,
    required_ranked_attribute_atom,
)
from ..ability_spec import AttackClass, DamageClass, DamagePart
from ..survival.phases import TransitionRank
from .module_helpers import buff_window_share, no_damage, ranked_slot, steroid_entry
from .slot_context import DAMAGE, SlotCtx, SlotParser
from .slot_control import atom_receipt
from .slot_entries import (
    ability_on_hit_entry,
    attach_self_shield,
    damage_entry,
    on_hit_entry,
)
from .slot_extract import (
    ability_name,
    extract_cooldown,
    extract_named,
    extract_value,
    find_named_leveling,
    sum_modifiers,
)

#: How many extra targets a widened or returning projectile may be told it hit.
SECONDARY_TARGET_CAP = 5

#: Seconds from a cast to the basic attack its payload rides.
_EMPOWERED_SWING_OFFSET = 0.1

_ATTACK_SPEED_ROW = "Bonus Attack Speed"
_DAMAGE_REDUCTION_ROW = "Damage Reduction"
_PER_LEVEL_ROW = "Per-Level Scaling"


def capped_option(ctx: SlotCtx, key: str, cap: int) -> int:
    """One declared count option, clamped to its cap."""

    return min(max(int(ctx.option(key)), 0), cap)


def prose_numbers(
    ctx: SlotCtx, slot: str, pattern: re.Pattern[str]
) -> tuple[float | None, ...] | None:
    """Every number *pattern* captures in a slot's cached effect prose, or ``None``.

    ``None`` is the one answer for both ways the read fails: no such entry
    cached, and no match.
    """

    ability = ctx.ability(slot)
    if ability is None:
        return None
    prose = " ".join(effect["description"] for effect in ability["effects"])
    match = pattern.search(prose)
    if match is None:
        return None
    return tuple(None if group is None else float(group) for group in match.groups())


def per_level_row(
    ctx: SlotCtx, attribute: str, *, champion: str, stop: str | None = None
) -> float:
    """A long per-level row read at the champion's level; a missing row is a stop."""

    ability = ctx.ability()
    if ability is None:
        return 0.0
    leveling = find_named_leveling(ability, attribute)
    if leveling is None:
        raise ValueError(
            stop or f"{champion} {ctx.slot} {attribute} leveling row is unavailable"
        )
    return sum_modifiers(
        leveling, ctx.rank_for(), ctx.stats, ctx.target, level=ctx.level
    )


def reduced_secondary_hits(  # pylint: disable=too-many-arguments
    ctx: SlotCtx,
    ability: dict[str, Any],
    rank_value: int,
    *,
    dmg_type: str,
    primary_row: str,
    reduced_row: str,
    option: str,
    lead: str,
    noun: str,
    certify_single_hit: bool = True,
) -> dict[str, Any]:
    """One primary hit plus the targets an option counts, each at the sourced reduced row.

    The whole row lands in one instant, so its parts author a zero offset
    and a zero interval rather than claiming a cast-boundary single hit.  A
    slot that reaches exactly one enemy makes that claim instead, unless
    the kit strikes on arrival and the claim was never its answer.
    """

    primary = extract_named(ability, primary_row, rank_value, ctx.stats, ctx.target)
    reduced = extract_named(ability, reduced_row, rank_value, ctx.stats, ctx.target)
    secondary = capped_option(ctx, option, SECONDARY_TARGET_CAP)
    entry = damage_entry(
        ability_name(ability),
        rank_value,
        extract_cooldown(ability, rank_value),
        primary + reduced * secondary,
        dmg_type,
    )
    together = bool(secondary) or not certify_single_hit
    parts = [DamagePart(dmg_type, primary, time_offset=0.0 if together else None)]
    if secondary:
        parts.append(
            DamagePart(
                dmg_type, reduced, count=secondary, time_offset=0.0, hit_interval=0.0
            )
        )
        entry["detail"] = (
            f"{lead} + {secondary} {noun} at the sourced "
            f"{reduced / primary * 100:g}% {reduced_row} row each"
        )
    elif certify_single_hit:
        entry["event_order_certified"] = "single_hit"
    entry["parts"] = tuple(parts)
    return entry


def ticked_channel(  # pylint: disable=too-many-arguments
    ctx: SlotCtx,
    ability: dict[str, Any],
    rank_value: int,
    *,
    attr: str,
    dmg_type: str,
    ticks: int,
    interval: float,
    dot_duration: float,
    detail: str | Callable[[float, float], str],
) -> dict[str, Any]:
    """A channel priced as N even sourced ticks.

    A *detail* that quotes the computed numbers is a callable over
    per-tick and total; a sentence that quotes neither is the string.
    """

    per_tick = extract_named(ability, attr, rank_value, ctx.stats, ctx.target)
    total = per_tick * ticks
    entry = damage_entry(
        ability_name(ability),
        rank_value,
        extract_cooldown(ability, rank_value),
        total,
        dmg_type,
    )
    entry["parts"] = (
        DamagePart(
            dmg_type, per_tick, count=ticks, time_offset=interval, hit_interval=interval
        ),
    )
    entry["dot_duration"] = dot_duration
    entry["detail"] = detail(per_tick, total) if callable(detail) else detail
    return entry


def multi_pass_damage(
    dmg_type: str, *, passes: Sequence[tuple[str, float]], detail: str
) -> SlotParser:
    """A slot delivering one cast as several sourced rows, each at its own offset.

    ``passes`` pairs a cached row name with the seconds from the cast start
    at which that pass lands, in the order the kit lands them.
    """

    def body(ctx: SlotCtx, ability: dict[str, Any], rank_value: int) -> dict[str, Any]:
        rows = [
            (extract_named(ability, attr, rank_value, ctx.stats, ctx.target), offset)
            for attr, offset in passes
        ]
        entry = damage_entry(
            ability_name(ability),
            rank_value,
            extract_cooldown(ability, rank_value),
            sum(value for value, _ in rows),
            dmg_type,
        )
        entry["parts"] = tuple(
            DamagePart(dmg_type, value, time_offset=offset) for value, offset in rows
        )
        entry["detail"] = detail
        return entry

    return ranked_slot(body)


def empowered_auto_entry(  # pylint: disable=too-many-arguments
    ability: dict[str, Any],
    rank_value: int,
    dmg_type: str,
    proc: dict[str, Any],
    *,
    cooldown: float,
    detail: str,
    empowered_damage: float | None = None,
    **entry_keys: Any,
) -> dict[str, Any]:
    """A cast whose payload rides the next basic attack.

    A rider on the empowered swing is the row's one basic-damage part,
    landing on the swing that follows the cast.
    """

    entry = ability_on_hit_entry(
        ability_name(ability), rank_value, dmg_type, proc, cooldown=cooldown
    )
    if empowered_damage is not None:
        entry["parts"] = (
            DamagePart(
                dmg_type,
                empowered_damage,
                basic_damage=True,
                time_offset=_EMPOWERED_SWING_OFFSET,
            ),
        )
        entry["total_raw"] = empowered_damage
    entry["empowers_next_auto"] = True
    entry.update(entry_keys)
    entry["detail"] = detail
    return entry


def attack_speed_steroid(
    ctx: SlotCtx,
    ability: dict[str, Any],
    rank_value: int,
    *,
    duration: float,
    aside: str,
) -> dict[str, Any]:
    """The cached bonus attack speed, weighted by the share of the fight it covers.

    ``aside`` is the kit's own closing clause, the one sentence the two
    numbers and the window do not say.
    """

    granted = extract_value(ability, _ATTACK_SPEED_ROW, rank_value)
    published = granted * buff_window_share(ctx, duration)
    return steroid_entry(
        ability,
        rank_value,
        {"bonus_attack_speed": published},
        f"+{granted:g}% bonus attack speed for {duration:g}s "
        f"({published:g}% over the fight window); {aside}",
    )


def move_speed_grant(
    ctx: SlotCtx,
    entry: dict[str, Any],
    *,
    granted: float,
    duration: float,
    detail: Callable[[float], str],
) -> dict[str, Any]:
    """A cast's own movement grant, time weighted, published on the shared fold."""

    published = granted * buff_window_share(ctx, duration)
    entry["stat_buff"] = {"move_speed_percent": published}
    entry["detail"] = detail(published)
    return entry


def per_level_on_hit(
    ctx: SlotCtx,
    *,
    ap_ratio: float,
    count_option: str,
    detail: Callable[[float, int], str],
) -> dict[str, Any] | None:
    """P: an on-hit from the per-level row plus an AP share, capped by a declared count."""

    ability = ctx.ability("P")
    if ability is None:
        return None
    per_hit = extract_named(
        ability, _PER_LEVEL_ROW, ctx.level, ctx.stats, ctx.target, level=ctx.level
    ) + ap_ratio * float(ctx.stat("ability_power") or 0.0)
    if per_hit <= 0:
        return None
    count = max(0, int(ctx.option(count_option)))
    entry = on_hit_entry(ability_name(ability), per_hit, "magic")
    entry["on_hit"]["max_procs"] = count
    entry["detail"] = detail(per_hit, count)
    return entry


def innate_zero_row(
    ctx: SlotCtx, *, detail: str, dmg_type: str = "magic"
) -> dict[str, Any] | None:
    """P: a named zero row at the champion's level, for an innate authored elsewhere."""

    ability = ctx.ability("P")
    if ability is None:
        return None
    return no_damage(
        ctx,
        name=ability_name(ability),
        reason=detail,
        slot="P",
        dmg_type=dmg_type,
        cooldown=0.0,
    )


def unreachable_innate(
    ctx: SlotCtx,
    *,
    row: str,
    dmg_type: str,
    detail: Callable[[SlotCtx, float], str],
) -> dict[str, Any] | None:
    """P: a trigger this fight never reaches, priced at zero, quoting its magnitude."""

    ability = ctx.ability("P")
    if ability is None:
        return None
    would_be = extract_named(ability, row, ctx.level, ctx.stats, ctx.target)
    return no_damage(
        ctx,
        name=ability_name(ability),
        reason=detail(ctx, would_be),
        slot="P",
        dmg_type=dmg_type,
        cooldown=0.0,
    )


def damage_reduction_window(
    ctx: SlotCtx,
    ability: dict[str, Any],
    rank_value: int,
    *,
    duration_source: str,
    damage_classes: frozenset[DamageClass],
    detail: Callable[[float, float], str],
) -> dict[str, Any]:
    """A cast's sourced incoming-damage-reduction window, as a zero-damage self-state row.

    The percentage is the slot's ranked ``Damage Reduction`` atom and the
    window is the prose active-duration atom of *duration_source*; both are
    unit checked, because a row reading anything but percent and seconds
    would publish a multiplier nothing sources.  ``damage_classes`` is the
    kit's own declaration: a cache that carves a type out narrows it, and
    one that carves none passes the full enum.
    """

    champion_data = {"name": ctx.champion_name, "abilities": ctx.abilities}
    percent, reduction_atom = required_ranked_attribute_atom(
        ctx.champion_name, champion_data, ctx.slot, _DAMAGE_REDUCTION_ROW, rank_value
    )
    units = {str(unit).strip().lower() for unit in reduction_atom["units"]}
    if not units or units != {"%"}:
        raise ValueError(
            f"{ctx.champion_name} {ctx.slot} damage-reduction atom must use percent"
        )
    duration_atom = required_ability_atom(
        ctx.champion_name,
        champion_data,
        ctx.slot,
        query=AbilityAtomQuery(
            source=duration_source,
            behavior="timing",
            evidence_prefix="active duration@",
        ),
    )
    if [str(unit).strip().lower() for unit in duration_atom["units"]] != ["s"]:
        raise ValueError(
            f"{ctx.champion_name} {ctx.slot} active-duration atom must use seconds"
        )
    duration = ranked_ability_atom_value(duration_atom, 1, source=duration_source)
    name = ability_name(ability)
    entry = damage_entry(
        name, rank_value, extract_cooldown(ability, rank_value), 0.0, "magic"
    )
    entry["parts"] = ()
    entry["self_state_events"] = [
        {
            "kind": "damage_modifier",
            "multiplier": 1.0 - percent / 100.0,
            "duration": duration,
            "source": f"{name} · damage reduction",
            "source_atoms": [atom_receipt(reduction_atom), atom_receipt(duration_atom)],
            # The cached prose reduces incoming damage with no attack or
            # spell-only carve-out, so the modifier gates no source kind
            # (the Briar-E / Glacial-Augment convention).
            "all_sources": True,
            "damage_classes": damage_classes,
            "attack_classes": frozenset(AttackClass),
            # An amplification already in force at its own timestamp must
            # price the hit landing at that timestamp.
            "_rank": TransitionRank.AURA_ARM,
        }
    ]
    entry["detail"] = detail(percent, duration)
    return entry


def ranked_packet_slot(
    packet: SlotParser,
    body: Callable[[SlotCtx, dict[str, Any], dict[str, Any], int], dict[str, Any]],
) -> SlotParser:
    """A compiled packet row, re-detailed by *body* once the slot is learned.

    An unlearned slot keeps the packet's generic stub; a learned one is
    handed its cached entry and rank to quote numbers back out of.
    """

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        entry = packet(ctx)
        if entry is None:
            return None
        ability = ctx.ability()
        slot_rank = ctx.rank_for()
        if ability is None or slot_rank < 1:
            return entry
        return body(ctx, entry, ability, slot_rank)

    return parse


def with_self_shield(
    parser: SlotParser,
    *,
    shield: Callable[[SlotCtx], float],
    window: float,
    source: str,
    detail: Callable[[SlotCtx, float], str],
) -> SlotParser:
    """A slot that also grants its caster the timed self shield its module prices.

    A defensive passive with no cast of its own rides a damaging slot's
    first event as a ``self_shield_events`` payload, and ``shield`` reads
    the amount off the build: every one of these is a share of a stat.
    The shielded cast is one hit, so the row certifies its own ordering.
    """

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        entry = parser(ctx)
        if entry is None:
            return None
        rank_value = entry.get("rank")
        if not rank_value or int(rank_value) < 1:
            return entry
        granted = shield(ctx)
        entry["event_order_certified"] = "single_hit"
        return attach_self_shield(
            entry,
            amount=granted,
            duration=window,
            source=source,
            detail=detail(ctx, granted),
        )

    parse.phase = getattr(parser, "phase", DAMAGE)
    return parse
