"""A cast's own stat grant, in the three shapes the fight engine prices.

A grant the engine can place is published as a window at the row's cast
(``attack_speed_window``): the swings inside it ride the full magnitude.
A grant it cannot place is weighted by the share of the fight it covers
(``attack_speed_steroid``, ``move_speed_grant``), one scalar for the whole
fight.  Downstream of :mod:`module_helpers`, upstream of every champion
module.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .module_helpers import buff_window_share, steroid_entry
from .shared_mechanics import ranked_packet_slot
from .slot_context import SlotCtx, SlotParser
from .slot_extract import extract_named, extract_value

ATTACK_SPEED_ROW = "Bonus Attack Speed"


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

    granted = extract_value(ability, ATTACK_SPEED_ROW, rank_value)
    published = granted * buff_window_share(ctx, duration)
    return steroid_entry(
        ability,
        rank_value,
        {"bonus_attack_speed": published},
        f"+{granted:g}% bonus attack speed for {duration:g}s "
        f"({published:g}% over the fight window); {aside}",
    )


def attack_speed_window(
    ctx: SlotCtx,
    entry: dict[str, Any],
    ability: dict[str, Any],
    rank_value: int,
    *,
    duration: float,
) -> float:
    """Place the cached bonus attack speed as a window at *entry*'s cast; return the grant.

    The row keeps whatever damage it prices (Wukong E's dash hit), and the
    row's scalings (Xin Zhao E's AP term) resolve against the parse stats.
    """

    granted = extract_named(
        ability, ATTACK_SPEED_ROW, rank_value, ctx.stats, ctx.target
    )
    # The engine rates the swings inside [cast, cast + duration) at the full
    # grant and the rest at the base rate, one window per kit.
    entry.setdefault("stat_buff", {})["bonus_attack_speed"] = granted
    entry.setdefault("auto_attack_override", {})["active_duration"] = duration
    return granted


def with_attack_speed_window(
    parser: SlotParser, *, duration: float, aside: str
) -> SlotParser:
    """Wrap a slot so the row it emits also places its attack-speed window.

    ``aside`` is the kit's own closing clause; the row's inherited detail
    (a rider, a hit count) follows it.
    """

    def body(
        ctx: SlotCtx, entry: dict[str, Any], ability: dict[str, Any], rank_value: int
    ) -> dict[str, Any]:
        granted = attack_speed_window(
            ctx, entry, ability, rank_value, duration=duration
        )
        inherited = str(entry["detail"]).strip() if "detail" in entry else ""
        entry["detail"] = (
            f"+{granted:g}% bonus attack speed for {duration:g}s from the cast "
            f"(one window per fight); {aside}" + (f" {inherited}" if inherited else "")
        )
        return entry

    return ranked_packet_slot(parser, body)


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
