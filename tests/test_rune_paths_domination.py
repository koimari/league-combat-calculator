"""Domination's minor runes: what each one prices, and what each one declines.

Three of the nine reach the fight — Cheap Shot's bonus true damage on the
impaired trigger stream, Sudden Impact's on a declared dash, and Ultimate
Hunter's ultimate haste — and all three are pinned here against the cache and
through the real pipeline. The other six are compiled refusals, so the test
that matters for them is not "does it price" but "does it decline for the
right reason, with the number it declined to price named".

The distinction is the disposition: ``WITHHELD`` is a real number this engine
holds no channel for, ``STRUCTURAL_ZERO`` is a rune whose answer is zero.
"""

import pytest

from src.calculator import rune_effects
from src.calculator.calculate import calculate_payload
from src.calculator.item_effects import DamageInputs
from src.calculator.rune_paths import domination
from src.calculator.trigger_stream import applies_control

_PROBE = {
    "champion": "Ashe",
    "level": 18,
    "items": [],
    "fight_mode": "one_rotation",
    "target_health": 2000.0,
    "target_armor": 100.0,
    "target_mr": 100.0,
}
#: A twenty-second window with Cheap Shot on the page, long enough for a
#: kit's control casts to come off the rune's four-second cooldown.
_TIMED = {
    "level": 18,
    "items": [],
    "fight_mode": "time_based",
    "fight_duration": 20.0,
    "target_health": 10000.0,
    "target_armor": 100.0,
    "target_mr": 100.0,
    "minor_runes": ["Cheap Shot"],
}


def _inputs(*, level):
    return DamageInputs(
        champion_stats={},
        level=level,
        is_melee=False,
        target_max_health=1000.0,
        target_current_health=1000.0,
    )


class TestCheapShot:
    """Row 1: bonus true damage on the impaired trigger stream."""

    def test_it_prices_its_cached_table_as_true_damage_on_a_4s_cooldown(self):
        """10 true damage at level 1 rising to 45 at 18, on a 4s cooldown."""
        effect = rune_effects.resolve_rune("Cheap Shot")
        assert isinstance(effect, rune_effects.RuneProcEffect)
        assert effect.trigger is rune_effects.RuneTrigger.IMPAIRED_INSTANCES
        assert effect.cooldown_seconds == 4.0
        assert effect.damage_type({}) == "true"
        assert effect.raw_damage(_inputs(level=1)) == pytest.approx(10.0)
        assert effect.raw_damage(_inputs(level=18)) == pytest.approx(45.0)
        assert rune_effects.RUNE_EFFECTS["Cheap Shot"]["cooldown"] == 4.0

    def test_the_stream_is_every_control_class_not_the_immobilizing_subset(self):
        """The rune names slows and blinds beside its immobilizes.

        Which is why the stream's predicate is the bus's wider one: an
        immobilize-only reader would refuse damage the rune really empowers.
        """
        assert applies_control({"cc_kind": "slow"})
        assert applies_control({"cc_kind": "charm"})
        assert not applies_control({"cc_kind": "none"})
        assert not applies_control({})

    def test_a_charming_kit_procs_and_an_unreviewed_kit_does_not(self):
        """Ahri's charm and Ashe's slow proc it; Annie's kit reviews nothing.

        Ahri's E is ``immobilize`` and Ashe's W a ``slow``, both reviewed in
        their modules' ``MODULE_CC``; Annie declares none, so her fight books
        no proc and says so rather than assuming she impairs.
        """
        charmer = calculate_payload({**_TIMED, "champion": "Ahri"})
        slower = calculate_payload({**_TIMED, "champion": "Ashe"})
        unreviewed = calculate_payload({**_TIMED, "champion": "Annie"})
        rows = [
            result["breakdown"].get("rune_Cheap Shot") for result in (charmer, slower)
        ]
        assert [(row["count"], row["total_damage"]) for row in rows] == [
            (2, pytest.approx(90.0)),
            (5, pytest.approx(225.0)),
        ]
        assert "rune_Cheap Shot" not in unreviewed["breakdown"]
        assert any("Cheap Shot never procced" in note for note in unreviewed["notes"])

    def test_the_procs_are_the_fight_s_own_control_casts(self):
        """45 true damage each, and the total moves by exactly that."""
        bare = calculate_payload(
            {key: value for key, value in _TIMED.items() if key != "minor_runes"}
            | {"champion": "Ashe"}
        )
        procced = calculate_payload({**_TIMED, "champion": "Ashe"})
        assert bare["total_damage"] == pytest.approx(800.0, abs=0.05)
        assert procced["total_damage"] == pytest.approx(1025.0, abs=0.05)
        assert procced["damage_by_type"]["true"] - bare["damage_by_type"]["true"] == (
            pytest.approx(225.0)
        )


class TestSuddenImpact:
    """Row 1: a proc whose whole trigger is a declared option."""

    def test_it_prices_its_cached_table_and_reads_the_dash_switch(self):
        """20 true damage at level 1 rising to 80 at 18, armed by the option."""
        effect = rune_effects.resolve_rune("Sudden Impact")
        assert isinstance(effect, rune_effects.RuneProcEffect)
        assert effect.damage_type({}) == "true"
        assert effect.raw_damage(_inputs(level=1)) == pytest.approx(20.0)
        assert effect.raw_damage(_inputs(level=18)) == pytest.approx(80.0)
        assert not effect.armed({})
        assert not effect.armed({"Sudden Impact": {"dashed": 0}})
        assert effect.armed({"Sudden Impact": {"dashed": 1}})

    def test_its_option_is_a_switch_defaulting_to_no_dash(self):
        option = domination.OPTIONS["Sudden Impact"][0]
        assert option.key == "dashed"
        assert option.kind is rune_effects.RuneOptionKind.SWITCH
        assert (option.default, option.bounds) == (0.0, (0.0, 1.0))

    def test_the_arming_window_and_cooldown_are_read_not_written(self):
        cached = rune_effects.RUNE_EFFECTS["Sudden Impact"]
        assert cached["effects"]["arming_window_seconds"] == 4.0
        assert cached["cooldown"] == 10.0
        effect = rune_effects.resolve_rune("Sudden Impact")
        assert "inside the 4s window" in effect.disclosures[1]
        assert "its 10s cooldown gates nothing here" in effect.disclosures[1]

    def test_the_switch_is_the_whole_difference_in_the_fight(self):
        """1542.0 without the dash, 1622.0 with it — one 80-damage proc."""
        request = {
            "champion": "Ahri",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 20.0,
            "target_health": 10000.0,
            "target_armor": 100.0,
            "target_mr": 100.0,
        }
        bare = calculate_payload(dict(request))
        selected = calculate_payload({**request, "minor_runes": ["Sudden Impact"]})
        dashed = calculate_payload(
            {
                **request,
                "minor_runes": ["Sudden Impact"],
                "rune_options": {"Sudden Impact": {"dashed": 1}},
            }
        )
        assert bare["total_damage"] == pytest.approx(1542.0, abs=0.05)
        assert selected["total_damage"] == pytest.approx(bare["total_damage"])
        assert "rune_Sudden Impact" not in selected["breakdown"]
        assert any(
            "the rune page's options do not arm it" in note
            for note in selected["notes"]
        )
        row = dashed["breakdown"]["rune_Sudden Impact"]
        assert (row["count"], row["total_damage"]) == (1, pytest.approx(80.0))
        assert dashed["total_damage"] == pytest.approx(1622.0, abs=0.05)


class TestTasteOfBloodStillWaits:
    """Row 1's third: a heal the self-healing ledger has no rune entry for."""

    def test_taste_of_blood_names_the_heal_and_the_missing_destination(self):
        """16 rising to 40, plus 10% bonus AD and 5% AP."""
        effect = rune_effects.resolve_rune("Taste of Blood")
        assert effect.zero_policy.disposition.name == "WITHHELD"
        assert "self-healing ledger" in effect.zero_policy.reason
        assert "heal 16 at level 1 rising to 40 at level 18" in effect.disclosures[0]
        assert "10% bonus AD and 5% AP" in effect.disclosures[0]

    def test_the_quoted_span_is_the_cached_table_at_levels_1_and_18(self):
        """The receipt's numbers are read, not written: prove it off the cache."""
        table = rune_effects.RUNE_EFFECTS["Taste of Blood"]["effects"]["leveling"][0]
        assert (rune_effects.at_level(table, 1), rune_effects.at_level(table, 18)) == (
            pytest.approx(16.0),
            pytest.approx(40.0),
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
        names = ["Taste of Blood", "Grisly Mementos", "Treasure Hunter"]
        bare = calculate_payload(dict(_PROBE))
        with_runes = calculate_payload({**_PROBE, "minor_runes": names})
        assert with_runes["total_damage"] == pytest.approx(bare["total_damage"])
        assert with_runes["champion_stats"] == bare["champion_stats"]
        assert not [key for key in with_runes["breakdown"] if key.startswith("rune_")]
        for name in names:
            assert any(
                f"{name} is not priced" in note for note in with_runes["notes"]
            ), name

    def test_the_withheld_heal_reaches_the_notes_with_its_numbers(self):
        result = calculate_payload({**_PROBE, "minor_runes": ["Taste of Blood"]})
        assert any(
            "heal 16 at level 1 rising to 40 at level 18" in note
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

    def test_the_two_runes_with_a_declared_input_are_the_two_with_options(self):
        assert set(domination.OPTIONS) == {"Sudden Impact", "Ultimate Hunter"}


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
