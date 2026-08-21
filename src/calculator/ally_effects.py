"""Opt-in outgoing ally effects with explicit sourced formulas."""

from collections.abc import Mapping
from dataclasses import dataclass
import math
import re
from typing import Any

from .interpreters.ally_packet import AllyPacketSlot, resolve_slots
from .item_behavior import AllyProducer
from .item_source import effect_text

# The one producer whose packet this opt-in path can apply to the calculated
# champion's own stat block: a timed ability-power and ability-haste buff the
# ally hands over before the fight.  Every other declared producer reaches
# its own reader instead of being spent here.
_PRODUCER = AllyProducer.RAPIDS

# Which cached passive stat each declared number is the reviewed reading of.
# The pair-side stat bonus and the walk's ``stat_buff`` packet now read one
# registry, so this pairing is what keeps the *cached* record — the half
# patch day actually refreshes — from diverging from it in silence.
_CACHED_STATS: tuple[tuple[str, str], ...] = (
    ("abilityPower", "bonus_ability_power"),
    ("abilityHaste", "bonus_ability_haste"),
)


@dataclass(frozen=True, slots=True)
class AllyStatEffect:
    """One ally effect applied to the champion being calculated."""

    source: str
    ability_power: float = 0.0
    ability_haste: float = 0.0
    duration: float = 0.0
    assumption: str = ""


def _required_flat_stat(
    passive: Mapping[str, Any], *, item_name: str, stat_name: str
) -> float:
    """Read one cached passive stat without silently converting omissions to zero."""
    stats = passive.get("stats")
    if not isinstance(stats, Mapping):
        raise ValueError(f"{item_name} Rapids is missing its cached stats mapping")
    stat = stats.get(stat_name)
    if not isinstance(stat, Mapping) or "flat" not in stat:
        raise ValueError(f"{item_name} Rapids is missing numeric {stat_name}.flat")
    value = stat["flat"]
    if isinstance(value, bool):
        raise ValueError(f"{item_name} Rapids {stat_name}.flat must be numeric")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{item_name} Rapids {stat_name}.flat must be numeric"
        ) from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{item_name} Rapids {stat_name}.flat must be finite")
    return parsed


def _required_cached_duration(passive: Mapping[str, Any], *, item_name: str) -> float:
    """Read the window the cached effect text states, or refuse."""
    duration_match = re.search(
        r"for\s+(\d+(?:\.\d+)?)\s+seconds?",
        effect_text(passive),
        flags=re.IGNORECASE,
    )
    if duration_match is None:
        raise ValueError(f"{item_name} Rapids is missing numeric duration")
    try:
        duration = float(duration_match.group(1))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{item_name} Rapids duration must be numeric") from exc
    if not math.isfinite(duration):
        raise ValueError(f"{item_name} Rapids duration must be finite")
    return duration


def _agree(*, item_name: str, key: str, declared: float, cached: float) -> None:
    """Stop when a declared number and the record it was read from disagree."""
    if declared != cached:
        raise ValueError(
            f"{item_name} Rapids declares {key}={declared} and its cached "
            f"record now reads {cached}; the declaration is the number both "
            "engines price, so a refreshed source that disagrees is a review, "
            "not a silent second answer"
        )


def _cached_producer_passive(
    item: Mapping[str, Any], *, item_name: str
) -> Mapping[str, Any] | None:
    """The cached passive this producer was read from, if the record still has it.

    Matched on the producer's own declared spelling rather than on the item's
    name, so the question asked is "does the source still describe this
    mechanic?" — the question the declaration is an answer to.
    """
    for passive in item.get("passives", []):
        if not isinstance(passive, Mapping):
            raise ValueError(f"{item_name} Rapids passive must be a mapping")
        if str(passive.get("name", "")).lower() == _PRODUCER.value:
            return passive
    return None


def _stat_effect(passive: Mapping[str, Any], slot: AllyPacketSlot) -> AllyStatEffect:
    """One declared producer, checked against the record it cites.

    Every number comes from the declaration — the same three references the
    walk's ``stat_buff`` emitter reads — so the two surfaces that price this
    buff can no longer hold different numbers.  The cached passive is still
    parsed, and now for the reason it is worth parsing: it is the half that
    moves on patch day, and a move it does not share with the declaration is
    a named stop rather than a number only one engine sees.
    """
    owner = slot.owner
    for stat_name, key in _CACHED_STATS:
        _agree(
            item_name=owner,
            key=key,
            declared=slot.value(key),
            cached=_required_flat_stat(passive, item_name=owner, stat_name=stat_name),
        )
    _agree(
        item_name=owner,
        key="duration",
        declared=slot.value("duration"),
        cached=_required_cached_duration(passive, item_name=owner),
    )
    return AllyStatEffect(
        source=f"{owner} — Rapids",
        ability_power=slot.value("bonus_ability_power"),
        ability_haste=slot.value("bonus_ability_haste"),
        duration=slot.value("duration"),
        assumption="The ally healed or shielded the attacker immediately before combat.",
    )


def resolve_ally_stat_effects(
    items: tuple[dict[str, Any], ...],
) -> tuple[AllyStatEffect, ...]:
    """Compile every supported outgoing effect in an enabled ally build.

    The build's declarations decide, not a name: a producer reaches this
    opt-in stat path because it declares the shape this path can apply to the
    calculated champion's block, and a producer declaring a different shape
    reaches its own reader instead.

    Declaration and cached record are required to agree on *presence* as well
    as on numbers.  Either one alone is a stop, because a source that grew
    the mechanic nothing declares and a declaration whose source no longer
    describes it are both the ally buff quietly costing zero.
    """
    by_name = {str(item.get("name", "")): item for item in items}
    declared: dict[str, AllyPacketSlot] = {
        slot.owner: slot for slot in resolve_slots(by_name).get(_PRODUCER, ())
    }
    effects: list[AllyStatEffect] = []
    for item_name, item in by_name.items():
        passive = _cached_producer_passive(item, item_name=item_name)
        slot = declared.get(item_name)
        if slot is None:
            if passive is not None:
                raise ValueError(
                    f"{item_name}'s cached record carries a Rapids passive and "
                    f"no {_PRODUCER.value} producer is declared for it; an "
                    "undeclared ally buff is a review, not a zero"
                )
            continue
        if passive is None:
            raise ValueError(f"{item_name} is missing its Rapids passive")
        effects.append(_stat_effect(passive, slot))
    return tuple(effects)


def combine_ally_stat_effects(
    effects: tuple[AllyStatEffect, ...],
) -> dict[str, float]:
    """Combine active external stats into the pipeline input shape."""
    return {
        "ability_power": sum(effect.ability_power for effect in effects),
        "ability_haste": sum(effect.ability_haste for effect in effects),
    }
