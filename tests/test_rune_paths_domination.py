"""Domination's minor runes: nine compiled refusals, and why each one is one.

Domination is the path this engine covers by declining, so the test that
matters is not "does it price" but "does it decline for the right reason,
with the number it declined to price named". Three of the nine carry a cached
damage or heal table and are missing only a trigger or a destination; six buy
things — vision, trinket haste, gold, out-of-combat movement — that are not
damage in any source.

The distinction is the disposition: ``WITHHELD`` is a real number this engine
holds no channel for, ``STRUCTURAL_ZERO`` is a rune whose answer is zero.
"""

import pytest

from src.calculator import rune_effects
from src.calculator.calculate import calculate_payload
from src.calculator.rune_paths import domination

_PROBE = {
    "champion": "Ashe",
    "level": 18,
    "items": [],
    "fight_mode": "one_rotation",
    "target_health": 2000.0,
    "target_armor": 100.0,
    "target_mr": 100.0,
}


class TestTheThreeCombatRunes:
    """Row 1: damage and healing the cache holds and the fight cannot reach."""

    def test_cheap_shot_names_the_true_damage_and_the_missing_trigger(self):
        """10 true damage at level 1 rising to 45 at 18, on a 4s cooldown."""
        effect = rune_effects.resolve_rune("Cheap Shot")
        assert isinstance(effect, rune_effects.RuneNoDamageEffect)
        assert effect.zero_policy.disposition.name == "WITHHELD"
        assert "no rune trigger stream reads the crowd-control marker" in (
            effect.zero_policy.reason
        )
        assert "10 bonus true damage at level 1 rising to 45 at level 18" in (
            effect.disclosures[0]
        )
        assert rune_effects.RUNE_EFFECTS["Cheap Shot"]["cooldown"] == 4.0

    def test_taste_of_blood_names_the_heal_and_the_missing_destination(self):
        """16 rising to 40, plus 10% bonus AD and 5% AP."""
        effect = rune_effects.resolve_rune("Taste of Blood")
        assert effect.zero_policy.disposition.name == "WITHHELD"
        assert "self-healing ledger" in effect.zero_policy.reason
        assert "heal 16 at level 1 rising to 40 at level 18" in effect.disclosures[0]
        assert "10% bonus AD and 5% AP" in effect.disclosures[0]

    def test_sudden_impact_names_the_true_damage_and_the_missing_event(self):
        """20 rising to 80 — armed by a dash the fight's timeline never records."""
        effect = rune_effects.resolve_rune("Sudden Impact")
        assert effect.zero_policy.disposition.name == "WITHHELD"
        assert "carries no movement or stealth event" in effect.zero_policy.reason
        assert "20 bonus true damage at level 1 rising to 80 at level 18" in (
            effect.disclosures[0]
        )

    @pytest.mark.parametrize(
        "name,levels",
        [
            ("Cheap Shot", (10.0, 45.0)),
            ("Taste of Blood", (16.0, 40.0)),
            ("Sudden Impact", (20.0, 80.0)),
        ],
    )
    def test_the_quoted_span_is_the_cached_table_at_levels_1_and_18(self, name, levels):
        """The receipt's numbers are read, not written: prove it off the cache."""
        table = rune_effects.RUNE_EFFECTS[name]["effects"]["leveling"][0]
        assert (rune_effects.at_level(table, 1), rune_effects.at_level(table, 18)) == (
            pytest.approx(levels[0]),
            pytest.approx(levels[1]),
        )


class TestTheSixUtilityRunes:
    @pytest.mark.parametrize(
        "name,disposition,phrase",
        [
            ("Sixth Sense", "STRUCTURAL_ZERO", "no source prices as damage"),
            ("Deep Ward", "STRUCTURAL_ZERO", "belongs to the champion the fight"),
            ("Relentless Hunter", "STRUCTURAL_ZERO", "only while out of combat"),
            ("Grisly Mementos", "WITHHELD", "the engine reads no trinket"),
            ("Treasure Hunter", "WITHHELD", "gold is not damage"),
            ("Ultimate Hunter", "WITHHELD", "no ultimate-haste field to grant into"),
        ],
    )
    def test_each_declares_its_disposition_and_its_reason(
        self, name, disposition, phrase
    ):
        effect = rune_effects.resolve_rune(name)
        assert isinstance(effect, rune_effects.RuneNoDamageEffect)
        assert effect.zero_policy.disposition.name == disposition
        assert phrase in effect.zero_policy.reason

    def test_deep_wards_cached_bonus_health_belongs_to_the_ward(self):
        """The cache reads 1 bonus health off the ward, not off the holder.

        Wiring that key into the bonus-health channel would hand the champion
        a stat the rune never grants, so the rune compiles to a zero and the
        key stays unread.
        """
        assert rune_effects.RUNE_EFFECTS["Deep Ward"]["effects"]["bonus_health"] == 1.0
        effect = rune_effects.resolve_rune("Deep Ward")
        assert not isinstance(effect, rune_effects.RuneStatGrantEffect)

    def test_the_two_hunter_hastes_are_told_apart(self):
        """Trinket haste and ultimate haste are refused for different reasons.

        Ultimate haste is a stat the engine reads and no rune can reach;
        trinket haste is a stat the engine does not read at all.
        """
        trinket = rune_effects.resolve_rune("Grisly Mementos")
        ultimate = rune_effects.resolve_rune("Ultimate Hunter")
        assert "grants no ability haste" in trinket.disclosures[0]
        assert "a stat the engine does read" in ultimate.zero_policy.reason


class TestThePathThroughTheRealPipeline:
    def test_a_full_domination_row_prices_nothing_and_receipts_everything(self):
        names = ["Cheap Shot", "Grisly Mementos", "Ultimate Hunter"]
        bare = calculate_payload(dict(_PROBE))
        with_runes = calculate_payload({**_PROBE, "minor_runes": names})
        assert with_runes["total_damage"] == pytest.approx(bare["total_damage"])
        assert with_runes["champion_stats"] == bare["champion_stats"]
        assert not [key for key in with_runes["breakdown"] if key.startswith("rune_")]
        for name in names:
            assert any(
                f"{name} is not priced" in note for note in with_runes["notes"]
            ), name

    def test_the_withheld_damage_reaches_the_notes_with_its_numbers(self):
        result = calculate_payload({**_PROBE, "minor_runes": ["Sudden Impact"]})
        assert any(
            "20 bonus true damage at level 1 rising to 80" in note
            for note in result["notes"]
        )


class TestThePathIsCovered:
    def test_every_domination_minor_rune_compiles(self):
        catalog = {
            entry["name"]: entry["implemented"]
            for entry in rune_effects.rune_catalog()
            if entry["path"] == "Domination" and entry["row"] > 0
        }
        assert len(catalog) == 9
        assert all(catalog.values())
        assert set(domination.COMPILERS) == set(catalog)

    def test_none_of_them_declares_an_option_because_none_prices_anything(self):
        assert domination.OPTIONS == {}
