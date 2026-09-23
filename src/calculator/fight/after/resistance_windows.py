"""Every timed packet re-priced at the resistance the target has when it lands.

Two things change a target's resistance for a stretch of the fight: a row's
``target_debuff`` shred (Kog'Maw Q, Garen E's sixth spin, Vi's Denting Blows)
and an authored temporary lethality (Voltaic Cyclosword's Firmament).  The
steps that priced the packets met the one figure the fight served them; once
the whole ledger exists, each timestamped physical or magic packet is
re-priced at the resistance live at its own time, rebuilt through the engine's
own :class:`Resists` from the target's opening armour and MR.  A row with no
timed packets keeps the figure the rotation served it.
"""

import math
from collections.abc import Mapping
from dataclasses import replace
from typing import Any, NamedTuple

from ...ability_atoms import ability_field
from ...resistance import apply_armor_penetration, rescale_mitigated
from ...survival.pricing import AuthoredDeclaration, restate_declaration
from ..ledger.breakdown import source_event_phase, source_total_damage
from ..ledger.event_rows import _finite_numeric_receipt
from ..resists import Resists
from ..setup.target_debuffs import _apply_target_shred
from ..state import FightState

_TIME_EPSILON = 1e-9
# Two resistances this close are one figure: the served pipeline recomputed
# here and the one a packet stamped differ only by float order.
_MATCH_TOLERANCE = 1e-6


class _ShredWindow(NamedTuple):
    """One application of a shred: live from ``start`` to ``end`` at ``fraction``
    of the debuff's stated reduction."""

    start: float
    end: float
    fraction: float


class _Shred(NamedTuple):
    source_key: str
    debuff: Mapping[str, Any]
    windows: tuple[_ShredWindow, ...]

    def fraction_at(self, source_key: str, time: float) -> float:
        """The share of the reduction live for one packet: the hit that applies
        a window meets the target before it, any other packet at that instant
        after it."""
        return max(
            (
                window.fraction
                for window in self.windows
                if (
                    window.start < time
                    if source_key == self.source_key
                    else window.start <= time + _TIME_EPSILON
                )
                and time <= window.end + _TIME_EPSILON
            ),
            default=0.0,
        )


def _hit_times(row: Any) -> list[float]:
    events = row.get("damage_events") if isinstance(row, Mapping) else None
    if not isinstance(events, list):
        return []
    times = {
        _finite_numeric_receipt(event.get("time"))
        for event in events
        if isinstance(event, Mapping)
        and (_finite_numeric_receipt(event.get("damage")) or 0.0) > 0.0
    }
    return sorted(time for time in times if time is not None)


def _shred_windows(state: FightState) -> list[_Shred]:
    """Each declared shred's windows, opened by the hits of its own row.

    A cast's window opens at its first hit, a threshold shred's at the hit that
    reaches the threshold (Garen E), and a stacking shred lands one stack per
    hit up to its cap (Corki Q); a row with no timed hits opens at its casts.
    """
    shreds: dict[str, _Shred] = {}
    for declaration in state.shred_declarations:
        debuff = declaration.debuff
        duration = float(ability_field(debuff, "duration", form="target_debuff"))
        span = duration if duration > 0.0 else math.inf
        threshold = int(ability_field(debuff, "threshold_hits", form="target_debuff"))
        stacks = int(ability_field(debuff, "stacks", form="target_debuff"))
        hits = _hit_times(state.breakdown.get(declaration.source_key))
        openings = sorted(declaration.opening_times)
        windows: list[_ShredWindow] = []
        for index, opening in enumerate(openings):
            following = openings[index + 1] if index + 1 < len(openings) else math.inf
            cast_hits = [
                hit
                for hit in hits
                if opening - _TIME_EPSILON <= hit < following - _TIME_EPSILON
            ] or [opening]
            if threshold > 0:
                if len(cast_hits) >= threshold:
                    applied = cast_hits[threshold - 1]
                    windows.append(_ShredWindow(applied, applied + span, 1.0))
            elif stacks > 0:
                windows.extend(
                    _ShredWindow(hit, hit + span, count / stacks)
                    for count, hit in enumerate(cast_hits[:stacks], 1)
                )
            else:
                windows.append(_ShredWindow(cast_hits[0], cast_hits[0] + span, 1.0))
        shreds[declaration.source_key] = _Shred(
            declaration.source_key, debuff, tuple(windows)
        )
    return [shred for shred in shreds.values() if shred.windows]


def _lethality_windows(state: FightState) -> list[dict[str, Any]]:
    """Firmament's authored temporary lethality, one window per holder row."""
    windows: list[dict[str, Any]] = []
    for source_key, row in state.breakdown.items():
        if not isinstance(row, dict):
            continue
        temporary = row.get("temporary_lethality")
        events = row.get("damage_events")
        if not isinstance(temporary, Mapping) or not isinstance(events, list):
            continue
        amount = _finite_numeric_receipt(temporary.get("amount"))
        duration = _finite_numeric_receipt(temporary.get("duration"))
        if amount is None or amount <= 0.0 or duration is None or duration <= 0.0:
            continue
        trigger_times = [
            _finite_numeric_receipt(event.get("time"))
            for event in events
            if isinstance(event, Mapping)
        ]
        trigger_times = [time for time in trigger_times if time is not None]
        if not trigger_times:
            continue
        windows.append(
            {
                "source_key": str(source_key),
                "trigger_time": min(trigger_times),
                "end_time": min(trigger_times) + duration,
                "amount": amount,
                "applies_to_triggering_event": bool(
                    ability_field(
                        temporary, "applied_to_triggering_event", form="temporary_buff"
                    )
                    or ability_field(
                        temporary, "applies_before_event", form="temporary_buff"
                    )
                ),
                "applied_count": 0,
            }
        )
    return windows


def _lethality_at(
    windows: list[dict[str, Any]], source_key: str, row: Mapping[str, Any], time: float
) -> tuple[float, list[dict[str, Any]]]:
    """The extra lethality one physical packet meets, and the windows granting it.

    Firmament is an ordered pre-packet effect: its extra lethality applies to its
    own damage and to the triggering attack or ability, and later events use the
    strict after-trigger boundary.  Ability events at the same timestamp are
    excluded unless they are the named Galvanize row; the sourced trigger is
    still the packet before them.
    """
    extra = 0.0
    active: list[dict[str, Any]] = []
    for window in windows:
        same_time_trigger = (
            window["applies_to_triggering_event"]
            and abs(time - window["trigger_time"]) <= _TIME_EPSILON
            and (
                source_key == window["source_key"]
                or source_event_phase(row) != "ability"
            )
        )
        later_event = (
            time > window["trigger_time"] and time <= window["end_time"] + _TIME_EPSILON
        )
        if same_time_trigger or later_event:
            extra += float(window["amount"])
            active.append(window)
    return extra, active


class _LiveResistance:
    """What a packet met and what it would meet, both through the engine's own
    :class:`Resists` with the fight's final penetration, memoised.

    A packet is re-priced only when the resistance it states is the served
    pipeline at one of the target states the fight passed through (its opening
    armour and MR, then each shred's).  A packet that met a resistance of its
    own (a per-hit MR state, penetration changed mid-fight) keeps it.
    """

    def __init__(self, resists: Resists) -> None:
        self.final = resists
        self.targets = (
            (resists.opening_armor, resists.opening_mr),
            *resists.shredded_targets,
        )
        self.memo: dict[tuple[Any, ...], float] = {}

    def _served(
        self,
        damage_class: str,
        target: tuple[float, float],
        shreds: tuple[tuple[int, Mapping[str, Any], float], ...] = (),
        extra_lethality: float = 0.0,
    ) -> float:
        key = (
            damage_class,
            target,
            tuple((index, fraction) for index, _, fraction in shreds),
            extra_lethality,
        )
        known = self.memo.get(key)
        if known is not None:
            return known
        resists = replace(self.final, target_armor=target[0], base_mr=target[1])
        resists.resolve()
        for _, debuff, fraction in shreds:
            _apply_target_shred(resists, debuff, fraction)
        if damage_class != "physical":
            served = resists.effective_mr
        elif extra_lethality > 0.0:
            served = apply_armor_penetration(
                resists.reduced_armor,
                resists.flat_armor_pen + extra_lethality,
                resists.effective_armor_pen_percent,
                resists.armor_pen_bonus_percent,
                bonus_armor=resists.target_bonus_armor,
            )
        else:
            served = resists.effective_armor
        self.memo[key] = served
        return served

    def met_served_pipeline(self, damage_class: str, met: float) -> bool:
        """Whether *met* is what the fight served at one of its target states."""
        return any(
            abs(self._served(damage_class, target) - met) <= _MATCH_TOLERANCE
            for target in self.targets
        )

    def at(
        self,
        damage_class: str,
        shreds: tuple[tuple[int, Mapping[str, Any], float], ...],
        extra_lethality: float,
    ) -> float:
        """The resistance a packet meets under *shreds* and *extra_lethality*."""
        return self._served(damage_class, self.targets[0], shreds, extra_lethality)


def _met_resistance(event: Mapping[str, Any]) -> float | None:
    """The resistance an event states it met, off the event or its declaration."""
    met = _finite_numeric_receipt(event.get("resistance_met"))
    if met is None and event.get("declared") is not None:
        met = AuthoredDeclaration(*event["declared"]).effective_resistance
    return None if met is None else float(met)


def _apply_resistance_windows(state: FightState) -> None:
    """Re-price every timed physical and magic packet at its live resistance."""
    shreds = _shred_windows(state)
    lethality = _lethality_windows(state)
    if not shreds and not lethality:
        return
    live = _LiveResistance(state.resists)
    kept = 0

    for source_key, row in state.breakdown.items():
        if not isinstance(row, dict):
            continue
        events = row.get("damage_events")
        if not isinstance(events, list):
            continue
        row_delta = 0.0
        for event in events:
            if not isinstance(event, dict):
                continue
            damage_class = event.get("damage_type")
            if damage_class not in ("physical", "magic"):
                continue
            time = _finite_numeric_receipt(event.get("time"))
            damage = _finite_numeric_receipt(event.get("damage"))
            if time is None or damage is None or damage <= 0.0:
                continue
            resistance = "armor" if damage_class == "physical" else "mr"
            active = tuple(
                (index, shred.debuff, fraction)
                for index, shred in enumerate(shreds)
                if _reduces(shred.debuff, resistance)
                and (fraction := shred.fraction_at(str(source_key), time)) > 0.0
            )
            extra, granting = (
                _lethality_at(lethality, str(source_key), row, time)
                if damage_class == "physical"
                else (0.0, [])
            )
            if (
                not active
                and extra <= 0.0
                and not any(_reduces(shred.debuff, resistance) for shred in shreds)
            ):
                continue
            met = _met_resistance(event)
            if met is None or not live.met_served_pipeline(damage_class, met):
                kept += 1
                continue
            meets = live.at(damage_class, active, extra)
            if abs(meets - met) <= _MATCH_TOLERANCE:
                continue
            repriced = rescale_mitigated(damage, met, meets)
            if not math.isfinite(repriced):
                continue
            event["damage"] = repriced
            event["resistance_met"] = meets
            restate_declaration(event, resistance=meets)
            row_delta += repriced - damage
            by_type = row.get("damage_by_type")
            if isinstance(by_type, dict) and damage_class in by_type:
                by_type[damage_class] = float(by_type[damage_class]) + (
                    repriced - damage
                )
            for window in granting:
                window["applied_count"] += 1
        if row_delta:
            priced = source_total_damage(row)
            row["total_damage"] = row_delta if priced is None else priced + row_delta
            if "damage_per_hit" in row and row.get("count"):
                row["damage_per_hit"] = float(row["total_damage"]) / float(row["count"])
            state.total_damage += row_delta

    if kept:
        state.notes.append(
            f"{kept} timed packet(s) kept the resistance the fight served them: "
            "each met a resistance of its own (a per-hit MR state or a "
            "mid-fight penetration change) the resistance windows do not replay."
        )
    _publish_lethality_receipts(state, lethality)


def _reduces(debuff: Mapping[str, Any], resistance: str) -> bool:
    """Whether a debuff states any reduction of *resistance* (``armor``/``mr``)."""
    return bool(
        ability_field(debuff, f"{resistance}_reduction_percent", form="target_debuff")
        or ability_field(debuff, f"{resistance}_reduction_flat", form="target_debuff")
    )


def _publish_lethality_receipts(
    state: FightState, windows: list[dict[str, Any]]
) -> None:
    """What each Firmament window applied to, on its holder's row."""
    for window in windows:
        row = state.breakdown.get(window["source_key"])
        if not isinstance(row, dict):
            continue
        temporary = row.get("temporary_lethality")
        if not isinstance(temporary, dict):
            continue
        applied = int(window["applied_count"])
        temporary["applied_to_triggering_event"] = bool(
            ability_field(
                temporary, "applied_to_triggering_event", form="temporary_buff"
            )
            and applied > 0
        )
        temporary["applied_to_later_events"] = applied > 0
        temporary["applied_event_count"] = applied
        temporary["note"] = (
            "Applied before the triggering Firmament packet and to later "
            "timestamped physical events within the sourced window."
            if applied > 0
            else "No timestamped physical events fell within the window."
        )
