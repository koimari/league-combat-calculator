"""Accumulation — the optimizer receipt's parallel-array sums (issue #137).

Ports the legacy score assembly exactly: per-attacker float-addition order
(pair fights in defender order, then thorns in strike order), the rounded
death-time cutoff on each attacker's outgoing total, and the support
value/healing-output sums over the compilers' support entries.  Nothing
here recomputes survival numbers — it only replays the ordered ``applied``
slots the score ledger recorded.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence


def accumulate_support_values(
    applied: Sequence[float],
    fresh_entries: Sequence[tuple[str, int, int, bool]],
    base_entries: Sequence[tuple[str, int, int, bool]],
    sig_entries: Sequence[tuple[str, int, int, bool]],
    count: int,
) -> tuple[list[float], list[float]]:
    """Per-attacker support value and healing output in legacy attach order.

    Legacy attach order — main (fresh), allies (base), enemies (sig) —
    decides both target-key insertion and per-target list order; the sums
    are order-independent, so this replays the same iteration the legacy
    assembly used.
    """
    support_value = [0.0] * count
    healing_output = [0.0] * count
    by_target: dict[str, list[tuple[int, int, bool]]] = {}
    for target_id, attacker_i, aidx, is_heal in fresh_entries:
        by_target.setdefault(target_id, []).append((attacker_i, aidx, is_heal))
    for target_id, attacker_i, aidx, is_heal in base_entries:
        by_target.setdefault(target_id, []).append((attacker_i, aidx, is_heal))
    for target_id, attacker_i, aidx, is_heal in sig_entries:
        by_target.setdefault(target_id, []).append((attacker_i, aidx, is_heal))
    for entries in by_target.values():
        for attacker_i, aidx, is_heal in entries:
            amount = applied[aidx]
            support_value[attacker_i] += amount
            if is_heal:
                healing_output[attacker_i] += amount
    return support_value, healing_output


def accumulate_damage_totals(
    survival_rows: Sequence[Mapping[str, Any]],
    applied: Sequence[float],
    *,
    sig_damage_order: Mapping[int, Sequence[tuple[int, float]]],
    base_damage_order: Mapping[int, Sequence[tuple[int, float]]],
    fresh_damage_order: Mapping[int, Sequence[tuple[int, float]]],
    fresh_thorns_order: Mapping[int, Sequence[tuple[int, float]]],
    base_thorns_order: Mapping[int, Sequence[tuple[int, float]]],
    count: int,
) -> list[float]:
    """Per-attacker outgoing totals in the legacy float-addition order.

    Pair fights in defender order (enemies hit the main first, then
    allies), then thorns in strike order (fresh strikes precede the
    roster's).  One running total over the ordered parts keeps the exact
    same addition sequence without building a concat list.  A dead
    attacker's total also replays the legacy cutoff against its ROUNDED
    death time: the walk applies an attacker's own event at the exact
    death instant, but the legacy sum excludes it whenever the true death
    time rounds down past it.
    """
    totals: list[float] = []
    for index in range(count):
        death_cutoff = survival_rows[index].get("death_time")
        running = 0.0
        for order in (
            sig_damage_order.get(index),
            base_damage_order.get(index),
            fresh_damage_order.get(index),
            fresh_thorns_order.get(index),
            base_thorns_order.get(index),
        ):
            if not order:
                continue
            if death_cutoff is None:
                for aidx, _event_time in order:
                    running += applied[aidx]
            else:
                for aidx, event_time in order:
                    if event_time <= death_cutoff:
                        running += applied[aidx]
        totals.append(round(running, 1))
    return totals


__all__ = ["accumulate_damage_totals", "accumulate_support_values"]
