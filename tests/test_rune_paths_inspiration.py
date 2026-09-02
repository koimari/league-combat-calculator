"""Inspiration's minor runes: one stat grant and eight receipted refusals.

Inspiration buys biscuits, boots, elixirs, summoner-spell swaps and gold
back. Three of its runes have no combat number in any source and are exact
zeros; five have one this engine cannot reach and are withheld. The ninth is
Jack Of All Trades, whose stacks are the build's own item stat types and
whose two channels are granted together.
"""

import pytest

from src.calculator import rune_effects
from src.calculator.calculate import calculate_payload
from src.calculator.stats import item_stat_type_count

#: Every Inspiration rune, its disposition, and the words its receipt must
#: carry. A structural zero is "nothing to price"; a withheld rune is a real
#: number this engine has no channel for.
DISPOSITIONS = {
    "Hextech Flashtraption": ("STRUCTURAL_ZERO", "no source states a combat number"),
    "Magical Footwear": ("WITHHELD", "buys no item on a clock"),
    "Cash Back": ("STRUCTURAL_ZERO", "gold never joins the fight's damage total"),
    "Triple Tonic": ("WITHHELD", "prices no consumable"),
    "Time Warp Tonic": ("WITHHELD", "the fight model consumes no potions"),
    "Biscuit Delivery": ("WITHHELD", "the fight model consumes none"),
    "Cosmic Insight": ("WITHHELD", "summoner-spell haste and item haste"),
    "Approach Velocity": ("WITHHELD", "no damage row reads movement speed"),
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
    @pytest.mark.parametrize(("name", "declaration"), sorted(DISPOSITIONS.items()))
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


class TestJackOfAllTrades:
    """The path's one priced rune: two channels off the build's own stat count."""

    def test_it_declares_both_channels_and_computes_them_from_one_count(self):
        """1 ability haste per stack; 8 adaptive at 5 stacks, 20 at 10."""
        effect = rune_effects.resolve_rune("Jack Of All Trades")
        assert isinstance(effect, rune_effects.RuneMultiStatGrantEffect)
        assert effect.stats == (
            rune_effects.RuneStat.ABILITY_HASTE,
            rune_effects.RuneStat.ADAPTIVE_FORCE,
        )
        haste = rune_effects.RuneStat.ABILITY_HASTE
        force = rune_effects.RuneStat.ADAPTIVE_FORCE
        assert effect.declared_amounts(_stat_context(4)) == {haste: 4.0, force: 0.0}
        assert effect.declared_amounts(_stat_context(5)) == {haste: 5.0, force: 8.0}
        assert effect.declared_amounts(_stat_context(10)) == {haste: 10.0, force: 20.0}

    def test_the_stacks_are_the_build_s_own_stat_types(self):
        """Counted off the item stat totals, and two engine keys for one
        game stat count once — a build wearing boots earns one stack for
        movement speed rather than two."""
        assert item_stat_type_count({}) == 0
        assert item_stat_type_count({"attack_damage": 40.0, "health": 300.0}) == 2
        assert (
            item_stat_type_count({"move_speed_flat": 45.0, "move_speed_percent": 5.0})
            == 1
        )
        assert item_stat_type_count({"attack_damage": 0.0}) == 0

    def test_biscuit_delivery_withholds_health_that_is_unknown_as_well(self):
        """Unearned *and* uncached: the receipt says both, not one."""
        effect = rune_effects.resolve_rune("Biscuit Delivery")
        assert "over a game one fight does not simulate" in effect.zero_policy.reason
        assert any(
            "the cache carries the biscuit's sale price and not the health" in receipt
            for receipt in effect.receipts
        )

    def test_the_cache_carries_the_step_and_both_gates(self):
        """Every number the compiler reads, checked against the cache.

        The three adaptive figures parse without conflict: the gates are
        claimed as gates and the total certifies them instead of
        conflicting with them.
        """
        jack = rune_effects.RUNE_EFFECTS["Jack Of All Trades"]
        assert jack["effects"] == {
            "ability_haste_per_stack": 1.0,
            "adaptive_force_stack_gates": [[5, 8.0], [10, 12.0]],
        }
        assert "parse_warnings" not in jack
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
        assert {entry["name"] for entry in catalog} == set(DISPOSITIONS) | {
            "Jack Of All Trades"
        }

    def test_no_inspiration_rune_declares_an_option(self):
        """Nothing here reads a number, so nothing here needs one asked for."""
        catalog = {entry["name"]: entry for entry in rune_effects.rune_catalog()}
        assert all(catalog[name]["options"] == [] for name in DISPOSITIONS)


def _stat_context(item_stat_types):
    """A stat context at level 18 carrying a count of item stat types."""
    return rune_effects.RuneStatContext(
        level=18,
        is_melee=False,
        bonus_attack_damage=0.0,
        ability_power=0.0,
        options={},
        item_stat_types=item_stat_types,
    )
