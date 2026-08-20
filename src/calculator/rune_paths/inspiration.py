"""Inspiration's minor runes.

Inspiration is the path most of whose runes buy things the fight model has no
axis for — biscuits, boots, summoner-spell swaps. Cosmic Insight is the first
of them and shows the shape: compiled, selectable, and receipted as a
refusal rather than a silent zero.
"""

from typing import Any, Mapping

from ..ability_spec import Disposition, ZeroPolicy
from ..rune_effects import RuneNoDamageEffect, RuneOption


def _compile_cosmic_insight(entry: Mapping[str, Any]) -> RuneNoDamageEffect:
    """Compile Cosmic Insight: summoner-spell and item haste, neither modeled.

    Its haste is real and reaches nothing this engine reads. Summoner spells
    are outside the damage model entirely, and an item active is priced once
    per fight (``damage._add_item_active_damage``) regardless of its
    cooldown, so item haste changes no number either. That makes it a
    withheld effect — the number exists and is refused — rather than a
    structural zero, and it is *not* a stat grant: ability haste, the one
    haste the engine reads, is not what this rune grants.
    """
    del entry  # the declaration is the whole compilation
    name = "Cosmic Insight"
    return RuneNoDamageEffect(
        rune_name=name,
        zero_policy=ZeroPolicy(
            Disposition.WITHHELD,
            "it grants summoner-spell haste and item haste, and the engine "
            "reads neither: summoner spells are outside the damage model and "
            "an item active is priced once per fight whatever its cooldown",
        ),
        disclosures=(
            f"{name} grants no ability haste, so nothing in the fight's "
            "cooldowns is understated by withholding it.",
        ),
    )


COMPILERS = {
    "Cosmic Insight": _compile_cosmic_insight,
}

OPTIONS: dict[str, tuple[RuneOption, ...]] = {}
