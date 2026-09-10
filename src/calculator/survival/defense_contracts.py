"""The one place the four interaction resolvers are read into a participant state."""

from __future__ import annotations

from typing import Any

from ..defense_composition import initial_full_block_uses
from ..interaction_effects import (
    resolve_physical_damage_reduction,
    resolve_spell_shield,
)
from ..projectile_defense import (
    defense_composition,
    defense_eligibility,
    resolve_projectile_defense,
)


def _resolved_defence_contracts(combatant: Any) -> dict[str, Any]:
    """The eleven :data:`_PER_CALL_FIELDS` a defence resolver decides.

    One home for the resolution, so the prototype declares the slots and
    this fills them.  ``None`` throughout is "this combatant holds no such
    contract", which is what every reader of these fields already tests for.
    """
    projectile_defense = resolve_projectile_defense(combatant)
    composition = defense_composition(projectile_defense)
    spell_shield = resolve_spell_shield(combatant)
    return {
        "projectile_defense": projectile_defense,
        "projectile_defense_eligibility": defense_eligibility(projectile_defense),
        "projectile_defense_composition": composition,
        "projectile_defense_uses_remaining": (
            initial_full_block_uses(composition) if composition is not None else None
        ),
        "physical_damage_reduction": resolve_physical_damage_reduction(combatant),
        "spell_shield_eligibility": (
            spell_shield.eligibility if spell_shield is not None else None
        ),
        "spell_shield_composition": (
            spell_shield.composition if spell_shield is not None else None
        ),
        "spell_shield_uses_remaining": (1 if spell_shield is not None else None),
        "spell_shield_cooldown_seconds": (
            spell_shield.cooldown_seconds if spell_shield is not None else None
        ),
        "spell_shield_cooldown_atom": (
            dict(spell_shield.cooldown_atom)
            if spell_shield is not None and spell_shield.cooldown_atom is not None
            else None
        ),
        # The rearm clock rides the contract.  ``None`` is "this combatant
        # holds no shield at all"; a shield whose cooldown is not sourced
        # carries the default clock, which never rearms.
        "spell_shield_rearm": (
            spell_shield.rearm if spell_shield is not None else None
        ),
    }
