"""Front-door tests for inventory, boots, and item legality rules."""

import pytest

from src.calculator.loadout_rules import (
    conflicts_with_groups,
    inventory_capacity,
    required_boots_tier,
    validate_resolved_loadout,
)


def test_role_state_controls_capacity_and_boot_tier() -> None:
    assert inventory_capacity("bottom", True) == 7
    assert required_boots_tier("mid", True) == 3


def test_exclusivity_and_duplicate_rules_fail_closed() -> None:
    assert conflicts_with_groups("Lich Bane", {"Spellblade"})
    with pytest.raises(ValueError, match="duplicate"):
        validate_resolved_loadout([{"name": "Ravenous Hydra"}] * 2)
