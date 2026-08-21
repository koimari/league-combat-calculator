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


class TestTheFiveUtilityRunes:
    @pytest.mark.parametrize(
        "name,disposition,phrase",
        [
            ("Sixth Sense", "STRUCTURAL_ZERO", "no source prices as damage"),
            ("Deep Ward", "STRUCTURAL_ZERO", "belongs to the champion the fight"),
            ("Relentless Hunter", "STRUCTURAL_ZERO", "only while out of combat"),
            ("Grisly Mementos", "WITHHELD", "the engine reads no trinket"),
            ("Treasure Hunter", "WITHHELD", "gold is not damage"),
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
        """Trinket haste is refused; ultimate haste has a channel of its own.

        Ultimate haste is a stat the engine's stat block carries, so the rune
        grants into it; trinket haste is a stat the engine does not read at
        all, so the rune states what it would have granted and stops.
        """
        trinket = rune_effects.resolve_rune("Grisly Mementos")
        ultimate = rune_effects.resolve_rune("Ultimate Hunter")
        assert "grants no ability haste" in trinket.disclosures[0]
        assert ultimate.stat is rune_effects.RuneStat.ULTIMATE_HASTE


class TestUltimateHunter:
    """Row 3: ultimate haste, a cached base plus a cached per-stack step."""

    def test_the_base_and_the_step_come_out_of_the_cache(self):
        """6 flat, 5 per Bounty Hunter stack, 31 at the five-stack maximum."""
        effect = rune_effects.resolve_rune("Ultimate Hunter")
        assert isinstance(effect, rune_effects.RuneStatGrantEffect)
        assert effect.amount(_stat_context()) == pytest.approx(6.0)
        assert effect.amount(_stat_context(stacks=1)) == pytest.approx(11.0)
        assert effect.amount(_stat_context(stacks=5)) == pytest.approx(31.0)

    def test_its_option_is_a_count_bounded_by_the_cached_ceiling(self):
        option = domination.OPTIONS["Ultimate Hunter"][0]
        assert option.key == "hunter_stacks"
        assert option.kind is rune_effects.RuneOptionKind.COUNT
        assert (option.default, option.bounds) == (0.0, (0.0, 5.0))
        with pytest.raises(ValueError, match="between 0 and 5"):
            option.validated(6)

    def test_the_grant_reaches_the_stat_card_and_says_the_scheduler_caps_it(self):
        """0 -> 6 -> 31 ultimate haste, and no damage row moves.

        The timed scheduler casts the ultimate exactly once whatever its
        cooldown is (``damage._schedule_shared_casts``), which is a floor
        every ultimate-haste source in the engine shares. The rune says so
        rather than letting the reader read a zero as "no haste".
        """
        request = {**_PROBE, "fight_mode": "time_based", "fight_duration": 30.0}
        bare = calculate_payload(dict(request))
        unstacked = calculate_payload({**request, "minor_runes": ["Ultimate Hunter"]})
        stacked = calculate_payload(
            {
                **request,
                "minor_runes": ["Ultimate Hunter"],
                "rune_options": {"Ultimate Hunter": {"hunter_stacks": 5}},
            }
        )
        hastes = [
            result["champion_stats"]["ultimate_haste"]
            for result in (bare, unstacked, stacked)
        ]
        assert hastes == [0, pytest.approx(6.0), pytest.approx(31.0)]
        assert stacked["total_damage"] == pytest.approx(bare["total_damage"])
        assert any(
            "casts the ultimate exactly once" in note for note in stacked["notes"]
        )

    def test_a_build_with_no_haste_item_still_publishes_an_integer_zero(self):
        """A published zero's *type* is load-bearing (CLAUDE.md).

        ``views.publish`` gives a float leaf a disposition entry and an int
        leaf none, and the item side of this stat sums no terms for a build
        holding no registry item. The rune channel joins as a term, so a page
        that grants nothing must not turn that int into a float.
        """
        bare = calculate_payload(dict(_PROBE))
        assert isinstance(bare["champion_stats"]["ultimate_haste"], int)
        other = calculate_payload({**_PROBE, "minor_runes": ["Cheap Shot"]})
        assert isinstance(other["champion_stats"]["ultimate_haste"], int)


class TestThePathThroughTheRealPipeline:
    def test_a_full_domination_row_prices_nothing_and_receipts_everything(self):
        names = ["Cheap Shot", "Grisly Mementos", "Treasure Hunter"]
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

    def test_only_the_rune_with_a_stack_count_declares_an_option(self):
        assert set(domination.OPTIONS) == {"Ultimate Hunter"}


def _stat_context(*, stacks=None):
    """A stat context at level 18, optionally carrying a Hunter stack count."""
    return rune_effects.RuneStatContext(
        level=18,
        is_melee=False,
        bonus_attack_damage=0.0,
        ability_power=0.0,
        options=(
            {} if stacks is None else {"Ultimate Hunter": {"hunter_stacks": stacks}}
        ),
    )
