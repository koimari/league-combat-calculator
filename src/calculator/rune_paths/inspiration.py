"""Inspiration's minor runes.

Inspiration is the path most of whose runes buy things the fight model has no
axis for — biscuits, boots, summoner-spell swaps. Cosmic Insight is the first
of them and shows the shape: compiled, selectable, and receipted as a
refusal rather than a silent zero. Its siblings land in the same table.
"""

from typing import Any, Callable, Mapping

from ..ability_spec import Disposition
from ..rune_effects import RuneEffect, RuneOption, no_damage_compiler

#: The Inspiration runes that book no damage: disposition, the reason that
#: becomes the receipt, and any further half this engine refuses.
_NO_DAMAGE: dict[str, tuple[Disposition, str, tuple[str, ...]]] = {
    # Cosmic Insight's haste is real and reaches nothing this engine reads.
    # Summoner spells are outside the damage model entirely, and an item
    # active is priced once per fight (``damage._add_item_active_damage``)
    # whatever its cooldown, so item haste changes no number either. That
    # makes it withheld — the number exists and is refused — rather than a
    # structural zero, and it is *not* a stat grant: ability haste, the one
    # haste the engine reads, is not what this rune grants.
    "Cosmic Insight": (
        Disposition.WITHHELD,
        "it grants summoner-spell haste and item haste, and the engine "
        "reads neither — summoner spells are outside the damage model, "
        "and an item active is priced once per fight whatever its cooldown",
        (
            "Cosmic Insight grants no ability haste, so nothing in the "
            "fight's cooldowns is understated by withholding it.",
        ),
    ),
}

COMPILERS: dict[str, Callable[[Mapping[str, Any]], RuneEffect]] = {
    name: no_damage_compiler(name, *declaration)
    for name, declaration in _NO_DAMAGE.items()
}

OPTIONS: dict[str, tuple[RuneOption, ...]] = {}
