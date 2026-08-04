"""Contracts for the role-quest combat rules."""

import pytest

from src.calculator.role_quests import (
    BOOT_UPGRADES,
    boot_upgrade_contract,
    level_cap,
    role_quest_meta,
    support_quest_item_contract,
)


class TestLevelCap:
    """Only a completed top-lane quest raises the level cap to 20."""

    def test_completed_top_quest_raises_cap_to_20(self) -> None:
        assert level_cap("top", True) == 20

    def test_incomplete_top_quest_keeps_cap_at_18(self) -> None:
        assert level_cap("top", False) == 18

    @pytest.mark.parametrize("role", ["", "jungle", "mid", "bottom", "support"])
    def test_other_roles_keep_cap_at_18_even_with_quest(self, role: str) -> None:
        assert level_cap(role, True) == 18

    def test_top_quest_meta_names_the_level_cap(self) -> None:
        assert "20" in role_quest_meta("top", True)["effect"]


def test_boot_upgrade_contract_covers_every_tier_two_pair() -> None:
    contract = boot_upgrade_contract()

    assert set(contract) == set(BOOT_UPGRADES)
    assert {pair["upgraded"] for pair in contract.values()} == set(
        BOOT_UPGRADES.values()
    )


def test_support_quest_contract_separates_progression_stages() -> None:
    contract = support_quest_item_contract()

    assert contract["incomplete_allowed_stages"] == ["intermediate", "starter"]
    assert contract["complete_allowed_stages"] == ["upgraded"]
    assert "Runic Compass" in contract["stages"]["intermediate"]
    assert "Bloodsong" in contract["stages"]["upgraded"]
