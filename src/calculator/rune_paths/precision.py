"""Precision's minor runes.

Precision's third row is the conditional-damage row: three runes that all
amplify by a share of damage while a health gate holds. Coup de Grace is the
one compiled here; Cut Down (the target above a share) and Last Stand (the
holder below one) are the same shape read off the same three cached keys.
"""

from typing import Any, Mapping

from ..rune_effects import (
    AmpCondition,
    RuneConditionalAmpEffect,
    RuneOption,
    RuneValues,
    breakdown_key,
    display_name,
)


def _compile_coup_de_grace(entry: Mapping[str, Any]) -> RuneConditionalAmpEffect:
    """Compile Coup de Grace: more damage to a champion below a health share.

    The gate is the target's *current* health against its maximum, so the
    engine decides per damage instance, walking its ordered ledger with the
    target's health falling by everything already dealt. Nothing about the
    gate is assumed here: the share, the amplifier, and which side of the
    threshold arms it all come out of the cached description.
    """
    name = "Coup de Grace"
    effects = RuneValues(name, entry.get("effects", {}))
    condition = AmpCondition(str(effects.value("damage_amp_health_gate")))
    health_ratio = effects.number("damage_amp_health_ratio")
    return RuneConditionalAmpEffect(
        rune_name=name,
        breakdown_key=breakdown_key(name),
        display_name=display_name(name),
        condition=condition,
        health_ratio=health_ratio,
        amp_ratio=effects.number("damage_amp_ratio"),
        disclosures=(
            f"{name} amplifies exactly the instances that land while the "
            f"target is below {health_ratio * 100:g}% of its maximum health, "
            "read off the fight's own ordered ledger; damage the ledger "
            "cannot timestamp is never amplified, so the row is a floor.",
        ),
    )


COMPILERS = {
    "Coup de Grace": _compile_coup_de_grace,
}

OPTIONS: dict[str, tuple[RuneOption, ...]] = {}
