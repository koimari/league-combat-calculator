"""Precision's minor runes.

Precision's third row is the conditional-damage row: three runes that all
amplify by a share of damage while a health gate holds. Two of them gate on
the *target's* health and are the same shape read off the same three cached
keys — Coup de Grace below a share, Cut Down above one. The third, Last
Stand, gates on the *holder's* health, which the pair engine does not track;
it is a flat amplifier whose gate is a declared option instead.
"""

from typing import Any, Mapping, NamedTuple

from ..rune_effects import (
    AmpCondition,
    RuneAmpContext,
    RuneConditionalAmpEffect,
    RuneFlatAmpEffect,
    RuneOption,
    RuneOptionKind,
    RuneValues,
    breakdown_key,
    display_name,
)


def _target_health_amp(
    name: str, entry: Mapping[str, Any], condition: AmpCondition
) -> RuneConditionalAmpEffect:
    """Compile one target-health-gated amplifier from its three cached keys.

    The gate is the target's *current* health against its maximum, so the
    engine decides per damage instance, walking its ordered ledger with the
    target's health falling by everything already dealt. Nothing about the
    gate is assumed here: the share, the amplifier, and which side of the
    threshold arms it all come out of the cached description, and a
    description stating the other side is refused rather than priced as the
    one the rune is known for.
    """
    effects = RuneValues(name, entry.get("effects", {}))
    stated = AmpCondition(str(effects.value("damage_amp_health_gate")))
    if stated is not condition:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] states a {stated.value!r} gate and this "
            f"compiler prices the {condition.value!r} one — wiki description "
            "reordered"
        )
    health_ratio = effects.number("damage_amp_health_ratio")
    side = "below" if condition is AmpCondition.TARGET_BELOW else "above"
    return RuneConditionalAmpEffect(
        rune_name=name,
        breakdown_key=breakdown_key(name),
        display_name=display_name(name),
        condition=condition,
        health_ratio=health_ratio,
        amp_ratio=effects.number("damage_amp_ratio"),
        disclosures=(
            f"{name} amplifies exactly the instances that land while the "
            f"target is {side} {health_ratio * 100:g}% of its maximum health, "
            "read off the fight's own ordered ledger; damage the ledger "
            "cannot timestamp is never amplified, so the row is a floor.",
        ),
    )


def _compile_coup_de_grace(entry: Mapping[str, Any]) -> RuneConditionalAmpEffect:
    """Compile Coup de Grace: more damage to a champion below a health share."""
    return _target_health_amp("Coup de Grace", entry, AmpCondition.TARGET_BELOW)


def _compile_cut_down(entry: Mapping[str, Any]) -> RuneConditionalAmpEffect:
    """Compile Cut Down: more damage to a champion above a health share.

    Coup de Grace's mirror, and the cached description is why it needs no
    kind of its own: the rune once compared the target's *maximum* health
    with the holder's, and now reads the target's current health like its
    row-mates do.
    """
    return _target_health_amp("Cut Down", entry, AmpCondition.TARGET_ABOVE)


#: Last Stand's gate is the holder's own health, and the pair engine prices
#: outgoing damage without tracking it — so the health it reads is an option
#: with a disclosed default (decision 5). The default is full health, which
#: is the un-triggered state: at 100 the rune amplifies nothing, so a fight
#: with it selected is the fight priced without it.
_SELF_HEALTH_PERCENT = "self_health_percent"


class _RampEnd(NamedTuple):
    """One end of a ramping amplifier: its gate, and what it pays there."""

    health: float
    ratio: float


def _ramp_end(name: str, effects: RuneValues, prefix: str) -> _RampEnd:
    """Read one end of a self-health-gated amplifier out of the cache."""
    gate = str(effects.value(f"{prefix}damage_amp_health_gate"))
    if gate != "self_below":
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] states a {gate!r} gate for its "
            f"{prefix or 'first'} end and this compiler prices the one that "
            "arms below a share of the holder's own health — wiki "
            "description reordered"
        )
    return _RampEnd(
        health=effects.number(f"{prefix}damage_amp_health_ratio"),
        ratio=effects.number(f"{prefix}damage_amp_ratio"),
    )


def _compile_last_stand(entry: Mapping[str, Any]) -> RuneFlatAmpEffect:
    """Compile Last Stand: more damage the lower the holder's own health.

    The wiki states the two ends and the direction between them — 5% on
    arming below 60% health, rising with missing health to 11% below 30% —
    and nothing about the shape of the rise. It is read as linear in the
    holder's remaining health, the one reading its two endpoints determine,
    and the rune discloses that.
    """
    name = "Last Stand"
    effects = RuneValues(name, entry.get("effects", {}))
    armed = _ramp_end(name, effects, "")
    peak = _ramp_end(name, effects, "escalated_")
    if peak.ratio <= armed.ratio or peak.health >= armed.health:
        raise KeyError(
            f"RUNE_EFFECTS[{name!r}] states {peak.ratio:g} at {peak.health:g} "
            f"maximum health as the escalated end of {armed.ratio:g} at "
            f"{armed.health:g}, which is not a rise toward lower health — "
            "wiki description reordered"
        )
    span = armed.health - peak.health

    def amp_ratio(context: RuneAmpContext) -> float:
        health = context.option(name, _SELF_HEALTH_PERCENT, 100.0) / 100.0
        if health >= armed.health:
            return 0.0
        if health <= peak.health:
            return peak.ratio
        return armed.ratio + (peak.ratio - armed.ratio) * (armed.health - health) / span

    return RuneFlatAmpEffect(
        rune_name=name,
        breakdown_key=breakdown_key(name),
        display_name=display_name(name),
        amp_ratio=amp_ratio,
        disclosures=(
            f"{name} reads the holder's own health, which the pair engine "
            f"does not track: it is priced from the {_SELF_HEALTH_PERCENT!r} "
            "option, whose default of 100 is the un-triggered state.",
            f"{name} pays {armed.ratio * 100:g}% on arming below "
            f"{armed.health * 100:g}% maximum health and "
            f"{peak.ratio * 100:g}% at {peak.health * 100:g}%; between those "
            "two ends the wiki states only that it rises with missing "
            "health, so the rise is read as linear in the holder's health.",
        ),
    )


COMPILERS = {
    "Coup de Grace": _compile_coup_de_grace,
    "Cut Down": _compile_cut_down,
    "Last Stand": _compile_last_stand,
}

OPTIONS: dict[str, tuple[RuneOption, ...]] = {
    "Last Stand": (
        RuneOption(
            key=_SELF_HEALTH_PERCENT,
            label="Holder's health (% of maximum)",
            kind=RuneOptionKind.COUNT,
            default=100.0,
            bounds=(0.0, 100.0),
            disclosure=(
                "The share of maximum health Last Stand's holder is on for "
                "the fight it prices. 100 is full health, where the rune "
                "amplifies nothing; the amplifier arms and rises below the "
                "shares its description names."
            ),
        ),
    ),
}
