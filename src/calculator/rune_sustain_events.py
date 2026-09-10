"""The healing a rune page did, read back off a finished fight result."""

import math
from collections.abc import Iterable, Mapping
from typing import Any

from . import item_effects
from .fight_params import FightParams
from .interpreters import sustain
from .item_behavior import SustainStat
from .item_sustain_events import _timestamped_damage_events
from .rune_effects import (
    KeystoneConquerorEffect,
    KeystoneFleetEffect,
    RuneHealEffect,
    RuneHealTrigger,
    RunePage,
    resolve_rune,
    resolve_rune_page,
)
from .trigger_stream import applies_control


def _rune_heal_times(result: Mapping[str, Any], effect: RuneHealEffect) -> list[float]:
    """When one healing rune is paid, from the stream it declares.

    The rune names the stream and the engine owns what is in it — the same
    division the damage-side trigger streams keep. Neither stream invents an
    event: a fight that lands no damage pays no Taste of Blood, and a fight
    the target survives pays no Triumph.
    """
    rows = _timestamped_damage_events(result)
    if effect.trigger is RuneHealTrigger.IMPAIRING_INSTANCES:
        # Whether a row applies control is the bus's answer, never a
        # ``cc_kind`` compared against a string here — the same predicate
        # the damage side's impaired stream asks.
        rows = [row for row in rows if applies_control(row)]
    if not rows:
        return []
    if effect.trigger is RuneHealTrigger.TAKEDOWNS:
        # The fight scored a takedown exactly when the target ended at or
        # below zero health, dated at the window's last damage instance —
        # the rule the coupled walk's own takedown synthesis reads. That is
        # at or after the instance that crossed zero, so a heal placed there
        # arrives no earlier than it should.
        if float(result.get("target_ending_health", 1.0) or 0.0) > 0.0:
            return []
        return [float(rows[-1].get("time", 0.0)) + effect.delay_seconds]
    times: list[float] = []
    ready_at = 0.0
    for row in rows:
        time = float(row.get("time", 0.0))
        if time < ready_at:
            continue
        times.append(time + effect.delay_seconds)
        ready_at = time + effect.cooldown_seconds
    return times


def _rune_self_healing_events(
    result: Mapping[str, Any], rune_page: RunePage | None
) -> list[dict[str, Any]]:
    """Materialize the heal packets the page's healing runes earned.

    The sibling of :func:`_item_self_healing_events`, in the same shape and
    folded into the same ledger: a rune heal is not a different kind of
    heal, only a different owner.  Each rune declares the stream it is paid
    on and the fight supplies the timestamps, so no number here is the
    engine's and no timestamp there is the rune's.
    """
    if rune_page is None:
        return []
    effects = [
        effect
        for effect in resolve_rune_page(rune_page)
        if isinstance(effect, RuneHealEffect)
    ]
    if not effects:
        return []
    stats = result.get("champion_stats")
    stats = stats if isinstance(stats, Mapping) else {}
    inputs = item_effects.DamageInputs(
        champion_stats=stats,
        level=int(stats.get("level", 1) or 1),
        is_melee=bool(stats.get("is_melee", True)),
        target_max_health=float(result.get("target_effective_max_health", 0.0) or 0.0),
        target_current_health=float(result.get("target_ending_health", 0.0) or 0.0),
    )
    events: list[dict[str, Any]] = []
    for effect in effects:
        amount = effect.amount(inputs)
        if not math.isfinite(amount) or amount <= 0.0:
            continue
        for sequence, time in enumerate(_rune_heal_times(result, effect)):
            events.append(
                {
                    "time": time,
                    "amount": amount,
                    "source": effect.source,
                    "kind": "rune_proc",
                    "_trigger_time": time,
                    "_trigger_sequence": sequence,
                }
            )
    return events


def _keystone_self_healing_events(
    result: Mapping[str, Any], params: "FightParams"
) -> list[dict[str, Any]]:
    """Materialize timestamped self-heals emitted by a typed keystone row."""
    if params.keystone not in {"Fleet Footwork", "Conqueror"}:
        return []
    row = result.get("breakdown", {}).get(f"heal_{params.keystone}")
    if not isinstance(row, Mapping) or not isinstance(row.get("heal_events"), list):
        return []
    source = (
        "Fleet Footwork · Energized heal"
        if params.keystone == "Fleet Footwork"
        else "Conqueror · max-stack heal"
    )
    effect = resolve_rune(params.keystone)
    if params.keystone == "Fleet Footwork" and not isinstance(
        effect, KeystoneFleetEffect
    ):
        return []
    if params.keystone == "Conqueror" and not isinstance(
        effect, KeystoneConquerorEffect
    ):
        return []
    slug = "fleet-footwork" if params.keystone == "Fleet Footwork" else "conqueror"
    events: list[dict[str, Any]] = []
    for index, event in enumerate(row["heal_events"]):
        if not isinstance(event, Mapping):
            continue
        events.append(
            {
                **event,
                "source": source,
                "kind": "keystone",
                "healing_category": "direct",
                "actor_wide": True,
                "_event_id": event.get(
                    "_event_id",
                    f"main:{slug}:heal:{index}",
                ),
            }
        )
    return events


def _saturated_omnivamp_percent(
    items: Iterable[dict[str, Any]],
    fight_duration_seconds: float,
    *,
    is_melee: bool = True,
) -> float:
    """The omnivamp this fight's length arms that the stat block does not hold.

    A ramp-armed grant is a fight state, not a stat, so it decides both whether
    the light tuple ledger is adequate and what the published effective stats
    say.  Both read the declaration, so a second such item needs no predicate.
    """
    return sustain.saturating_stat_percent(
        [str(item.get("name", "")) for item in items],
        SustainStat.OMNIVAMP_PERCENT,
        fight_duration_seconds=fight_duration_seconds,
        holder_is_melee=is_melee,
    )
