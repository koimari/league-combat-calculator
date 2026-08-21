"""Inspiration's minor runes: nine runes, nine receipted refusals.

Inspiration buys biscuits, boots, elixirs, summoner-spell swaps and gold
back. Three of its runes have no combat number in any source and are exact
zeros; six have one this engine cannot reach and are withheld. The pair the
engine could reach if it were wider — Jack Of All Trades and Biscuit
Delivery — say exactly what is missing, so the refusal is a specification
rather than a shrug.
"""

import pytest

from src.calculator import rune_effects
from src.calculator.calculate import calculate_payload

#: Every Inspiration rune, its disposition, and the words its receipt must
#: carry. A structural zero is "nothing to price"; a withheld rune is a real
#: number this engine has no channel for.
DISPOSITIONS = {
    "Hextech Flashtraption": ("STRUCTURAL_ZERO", "no source states a combat number"),
    "Magical Footwear": ("WITHHELD", "buys no item on a clock"),
    "Cash Back": ("STRUCTURAL_ZERO", "gold never joins the fight's damage total"),
    "Triple Tonic": ("WITHHELD", "prices no consumable"),
    "Time Warp Tonic": ("WITHHELD", "no rune healing channel"),
    "Biscuit Delivery": ("WITHHELD", "raises maximum health permanently"),
    "Cosmic Insight": ("WITHHELD", "summoner-spell haste and item haste"),
    "Approach Velocity": ("WITHHELD", "no damage row reads movement speed"),
    "Jack Of All Trades": ("WITHHELD", "carries no item stats"),
}


def _request(**overrides):
    payload = {
        "champion": "Ahri",
        "level": 11,
        "items": ["Rabadon's Deathcap"],
        "fight_mode": "time_based",
        "fight_duration": 20.0,
    }
    payload.update(overrides)
    return payload


class TestEveryInspirationRuneIsCompiledAndReceipted:
    @pytest.mark.parametrize("name,declaration", sorted(DISPOSITIONS.items()))
    def test_it_books_no_damage_and_says_why(self, name, declaration):
        disposition, reason = declaration
        effect = rune_effects.resolve_rune(name)
        assert isinstance(effect, rune_effects.RuneNoDamageEffect), name
        assert effect.zero_policy.disposition.name == disposition, name
        assert reason in effect.zero_policy.reason, name

    def test_a_structural_zero_and_a_withheld_rune_read_differently(self):
        """The verdict is the disposition's, and the two are not the same claim."""
        exact = rune_effects.resolve_rune("Cash Back")
        refused = rune_effects.resolve_rune("Triple Tonic")
        assert exact.receipts[0].startswith("Cash Back deals no damage in any fight:")
        assert refused.receipts[0].startswith("Triple Tonic is not priced:")


class TestTheTwoRunesTheEngineCouldReach:
    """Jack Of All Trades and Biscuit Delivery name what a wider engine needs."""

    def test_jack_of_all_trades_names_both_of_its_blockers(self):
        """Its stacks are a fact about the build; its grant is two channels."""
        effect = rune_effects.resolve_rune("Jack Of All Trades")
        reason = effect.zero_policy.reason
        assert "distinct stat types the build's items grant" in reason
        assert "rune stat context carries no item stats" in reason
        assert "two stat channels where a rune stat grant names one" in reason
        assert any("adaptive figures" in receipt for receipt in effect.receipts)

    def test_biscuit_delivery_withholds_health_earned_over_a_game(self):
        effect = rune_effects.resolve_rune("Biscuit Delivery")
        assert any(
            "over a game this one fight does not simulate" in receipt
            for receipt in effect.receipts
        )

    def test_the_cache_still_carries_only_what_the_parse_reached(self):
        """The receipts' claims about the cache, checked against the cache."""
        jack = rune_effects.RUNE_EFFECTS["Jack Of All Trades"]
        assert jack["effects"] == {"ability_haste": 1.0}
        assert any("adaptive_force" in warning for warning in jack["parse_warnings"])
        biscuit = rune_effects.RUNE_EFFECTS["Biscuit Delivery"]
        assert biscuit["effects"] == {"flat_gold": 5.0}


class TestInspirationOverTheWholePipeline:
    def test_a_selected_inspiration_rune_publishes_its_receipt_and_moves_nothing(
        self,
    ):
        bare = calculate_payload(_request())
        with_rune = calculate_payload(_request(minor_runes=["Magical Footwear"]))
        assert any(
            "Magical Footwear is not priced" in note for note in with_rune["notes"]
        )
        assert with_rune["champion_stats"] == bare["champion_stats"]
        assert with_rune["total_damage"] == pytest.approx(bare["total_damage"])

    def test_a_full_inspiration_secondary_pair_is_legal_and_prices_nothing(self):
        """Two rows of one path is what a secondary path may hold."""
        bare = calculate_payload(_request())
        paired = calculate_payload(
            _request(minor_runes=["Cash Back", "Cosmic Insight"])
        )
        assert paired["total_damage"] == pytest.approx(bare["total_damage"])
        assert sum("is not priced" in note for note in paired["notes"]) >= 1


class TestInspirationCoverage:
    def test_every_inspiration_minor_compiles(self):
        catalog = [
            entry
            for entry in rune_effects.rune_catalog()
            if entry["path"] == "Inspiration" and entry["row"]
        ]
        assert len(catalog) == 9
        assert all(entry["implemented"] is True for entry in catalog)
        assert {entry["name"] for entry in catalog} == set(DISPOSITIONS)

    def test_no_inspiration_rune_declares_an_option(self):
        """Nothing here reads a number, so nothing here needs one asked for."""
        catalog = {entry["name"]: entry for entry in rune_effects.rune_catalog()}
        assert all(catalog[name]["options"] == [] for name in DISPOSITIONS)
