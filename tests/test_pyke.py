"""Tests for the Pyke champion module."""

import pytest

from src.calculator.calculate import calculate_payload
from src.calculator.champions import (
    get_champion_module_contract,
    get_champion_stat_conversion,
    pyke,
)
from src.calculator.champions.module_contract import (
    ChampionModuleContractError,
    contract_from_module,
)
from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.stat_conversion import BonusHealthConversion
from src.calculator.stats import calculate_total_stats
from tests import cc_review


class TestReviewedCrowdControl:
    """Pyke's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Pyke")
        assert pyke.MODULE_CC == {"Q": "pull", "E": "stun", "R": "none"}
        q_text = cc_review.slot_text(data, "Q")
        assert "dealing physical damage to the first enemy hit and pulling" in q_text
        assert "then slowing them by 90% for 1 second" in q_text
        assert "the phantom homes back to pyke to stun enemies" in cc_review.slot_text(
            data, "E"
        )
        assert cc_review.control_words(cc_review.slot_text(data, "R")) == []
        # W (camouflage) and P (grey health) damage nothing, so no event of
        # theirs could carry an answer.
        assert "W" not in pyke.MODULE_CC
        assert "P" not in pyke.MODULE_CC

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Pyke") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Pyke")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


class TestGiftOfTheDrownedOnesStatConversion:
    """P denies Pyke bonus health and returns it as bonus attack damage."""

    def test_the_ratio_is_the_one_the_cached_passive_states(self):
        text = " ".join(
            effect["description"]
            for effect in get_champion("Pyke")["abilities"]["P"][0]["effects"]
        )
        assert "maximum health cannot increase except through growth" in text
        assert "1 bonus attack damage per 14 bonus health" in text
        assert "7.143% of bonus health" in text
        ratio = pyke.MODULE_STAT_CONVERSION.attack_damage_ratio
        assert ratio == 1.0 / 14.0
        assert round(ratio * 100.0, 3) == 7.143

    def test_the_contract_carries_the_declaration(self):
        contract = get_champion_module_contract("Pyke")
        assert contract.stat_conversion is pyke.MODULE_STAT_CONVERSION
        assert isinstance(contract.stat_conversion, BonusHealthConversion)
        assert contract.stat_conversion.source == "Gift of the Drowned Ones"

    @pytest.mark.parametrize(
        "declared",
        [
            "1 per 14",
            BonusHealthConversion(source=" ", attack_damage_ratio=1.0 / 14.0),
            BonusHealthConversion(source="Gift", attack_damage_ratio=0.0),
            BonusHealthConversion(source="Gift", attack_damage_ratio=1.5),
        ],
    )
    def test_an_unusable_declaration_fails_the_import_gate(self, monkeypatch, declared):
        monkeypatch.setattr(pyke, "MODULE_STAT_CONVERSION", declared, raising=True)
        with pytest.raises(ChampionModuleContractError):
            contract_from_module("Pyke", "pyke", pyke)

    def test_a_champion_with_no_declaration_keeps_its_item_health(self):
        assert get_champion_stat_conversion("Ahri") is None
        ahri = calculate_total_stats(
            get_champion("Ahri"), 18, [get_item_by_name("Warmog's Armor")]
        )
        assert ahri["bonus_health"] == 1120

    @pytest.mark.parametrize(
        ("item_name", "denied_health", "expected_bonus_ad"),
        [
            # Warmog's own 1000-health stat block, raised to 1120 by
            # Vitality before the conversion reads it.
            ("Warmog's Armor", 1120, 80),
            ("Heartsteel", 900, 64),
            ("Riftmaker", 350, 25),
        ],
    )
    def test_bonus_health_becomes_bonus_attack_damage(
        self, item_name: str, denied_health: int, expected_bonus_ad: int
    ):
        item = [get_item_by_name(item_name)]
        bare = calculate_total_stats(get_champion("Pyke"), 18, [])
        stats = calculate_total_stats(get_champion("Pyke"), 18, item)
        assert calculate_total_stats(get_champion("Ahri"), 18, item)[
            "bonus_health"
        ] == (denied_health)
        assert stats["health"] == bare["health"]
        assert stats["bonus_health"] == 0
        assert stats["bonus_attack_damage"] == expected_bonus_ad

    def test_the_published_fight_sees_the_converted_attack_damage(self):
        payload = calculate_payload(
            {
                "champion": "Pyke",
                "level": 18,
                "items": ["Warmog's Armor"],
                "fight_mode": "timed",
                "fight_duration": 12,
                "include_auto_attacks": True,
            },
            deterministic=True,
        )
        assert payload["champion_stats"]["health"] == 2540
        assert payload["champion_stats"]["attack_damage"] == 176
