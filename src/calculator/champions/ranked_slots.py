"""The cross-slot rank guard, stated once: ``@ranked_at("Q")``.

A module function that prices one slot's cached entry opens with the same
three statements: ask ``ctx.ranked`` for the slot's ``(ability, rank)``,
return ``None`` when it has none, then unpack it. The decorator is those
three statements, so the body receives the pair and a guard cannot drift.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from .slot_context import SlotCtx

_Result = TypeVar("_Result")


def ranked_at(slot: str, index: int = 0) -> Callable[
    [Callable[[SlotCtx, dict[str, Any], int], _Result | None]],
    Callable[[SlotCtx], _Result | None],
]:
    """Call the body with *slot*'s ``(ability, rank)``, or answer ``None``.

    ``None`` is either reason ``ctx.ranked`` gives: no such cached entry, or
    no point in the slot yet.
    """

    def decorate(
        body: Callable[[SlotCtx, dict[str, Any], int], _Result | None],
    ) -> Callable[[SlotCtx], _Result | None]:
        @wraps(body)
        def guarded(ctx: SlotCtx) -> _Result | None:
            ranked = ctx.ranked(slot, index)
            if ranked is None:
                return None
            ability, rank = ranked
            return body(ctx, ability, rank)

        return guarded

    return decorate
