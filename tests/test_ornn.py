"""Tests for the Ornn champion module."""

import copy

import pytest

from src.calculator.calculate import calculate_payload
from src.calculator.champions import (
    get_champion_module_contract,
    ornn,
    parse_champion_abilities,
)
from src.calculator.data_fetcher import get_champion
from tests import cc_review, row_review
from src.calculator.champions.engine import CC_PER_PART


def _r_row(level, **options):
    """Ornn's parsed R row against a 2000-health dummy at one level."""
    return parse_champion_abilities(
        get_champion("Ornn"),
        level,
        0.0,
        ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
        target_stats={"target_max_health": 2000.0},
        champion_options=options or None,
    )["R"]


def _w_total(target_max_health):
    """Ornn's priced Bellows Breath total against one dummy's maximum health."""
    return parse_champion_abilities(
        get_champion("Ornn"),
        18,
        0.0,
        ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
        target_stats={"target_max_health": target_max_health},
    )["W"]["total_raw"]


class TestReviewedCrowdControl:
    """Ornn's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Ornn")
        assert ornn.MODULE_CC == {
            "Q": "slow",
            "W": "none",
            "E": "none",
            "R": CC_PER_PART,
        }
        assert "slows them by 40% for 2 seconds" in cc_review.slot_text(data, "Q")
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == []
        # E's priced row is the charge's pass-through damage; the knock-up
        # and stun belong to the terrain-collision shockwave, whose own
        # damage lands only on enemies the charge did not already hit.
        e_text = cc_review.slot_text(data, "E")
        assert "if ornn collides with terrain during the charge" in e_text
        assert "deals the same damage if they were not already hit" in e_text

    def test_r_answers_per_pass_because_the_two_passes_differ(self):
        data = cc_review.kit("Ornn")
        r_text = cc_review.slot_text(data, "R")
        assert "slows them for 2 seconds" in r_text
        assert "knocks them up and stuns them for 1 second" in r_text
        assert ornn.MODULE_CC["R"] == CC_PER_PART
        abilities = parse_champion_abilities(
            get_champion("Ornn"), 18, 0.0, ability_ranks={"R": 3}
        )
        assert [part.cc_kind for part in abilities["R"]["parts"]] == [
            "slow",
            "immobilize",
        ]

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Ornn") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Ornn")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


class TestTemperBrittleConsume:
    """CF4: Temper's Brittle consume, and the two sources that pin it.

    The cached passive carries no leveling row at all, so the consume's
    ramp is read out of the Temper prose and cross-checked against the
    game file's own interpolation.
    """

    def test_the_ramp_spans_the_prose_endpoints_over_the_level_cap(self):
        """9% at level 1, 17.94% at the cap — and 17% at level 18.

        The game file interpolates 9% -> 17% across levels 1-18 with a bare
        ``ByCharLevelInterpolationCalculationPart``; that slope carried out
        to today's cap of 20 is where the wiki's 17.94% comes from, so the
        prose endpoints have to reproduce the game file in the middle.
        """
        text = cc_review.slot_text(cc_review.kit("Ornn"), "P")
        assert "9% : 17.94% (based on ornn's level) of the target's maximum" in text
        for level, expected in ((1, 180.0), (18, 339.9789473684211), (20, 358.8)):
            (part,) = _r_row(level)["post_hit_proc"]["parts"]
            assert part.amount == pytest.approx(expected)
            assert part.damage_type == "magic"
        # 2000 x 17% = 340, the game file's own level-18 value.
        assert _r_row(18)["post_hit_proc"]["parts"][0].amount == pytest.approx(
            340.0, abs=0.03
        )

    def test_the_consume_rides_the_recast_pass_that_immobilises(self):
        row = _r_row(18)
        proc = row["post_hit_proc"]
        assert proc["name"] == "Living Forge (Temper)"
        assert proc["breakdown_key"] == "passive_temper_brittle"
        # The immobilising pass is R's second, 1.25s after the first — the
        # pass that applied the debuff, inside its sourced 3s window.
        assert [part.cc_kind for part in row["parts"]] == ["slow", "immobilize"]
        assert proc["parts"][0].time_offset == ornn._R_RECAST_DELAY
        assert row["parts"][1].time_offset == ornn._R_RECAST_DELAY
        assert row["target_max_health_sensitive"] is True
        assert "applies brittle to targets for 3 seconds" in cc_review.slot_text(
            cc_review.kit("Ornn"), "R"
        )

    def test_a_single_pass_consumes_nothing(self):
        """One pass only slows, and a slow is not an immobilise."""
        assert "post_hit_proc" not in _r_row(18, r_passes=1)

    def test_prose_that_no_longer_states_the_ramp_raises(self, monkeypatch):
        stripped = copy.deepcopy(get_champion("Ornn"))
        temper = stripped["abilities"]["P"][0]["effects"][2]
        temper["description"] = temper["description"].replace("9% : 17.94%", "lots")
        monkeypatch.setattr(
            "src.calculator.data_fetcher.get_champion", lambda *a, **k: stripped
        )
        with pytest.raises(ValueError, match="Ornn P .Temper."):
            parse_champion_abilities(
                stripped,
                18,
                0.0,
                ability_ranks={"R": 3},
                target_stats={"target_max_health": 2000.0},
            )

    def test_prose_that_disagrees_with_the_game_file_raises(self, monkeypatch):
        drifted = copy.deepcopy(get_champion("Ornn"))
        temper = drifted["abilities"]["P"][0]["effects"][2]
        temper["description"] = temper["description"].replace(
            "9% : 17.94%", "12% : 17.94%"
        )
        monkeypatch.setattr(
            "src.calculator.data_fetcher.get_champion", lambda *a, **k: drifted
        )
        with pytest.raises(ValueError, match="BrittlePercentMaxHPCalc|game file"):
            parse_champion_abilities(
                drifted,
                18,
                0.0,
                ability_ranks={"R": 3},
                target_stats={"target_max_health": 2000.0},
            )

    def test_the_passive_publishes_its_own_row_through_the_whole_pipeline(self):
        """A real request pays the consume as the passive's breakdown row."""
        payload = calculate_payload(
            {
                "champion": "Ornn",
                "level": 18,
                "items": [],
                "fight_mode": "one_rotation",
                "deterministic": True,
            }
        )
        row = payload["breakdown"]["passive_temper_brittle"]
        # The default dummy is 1000 maximum health behind 100 magic
        # resistance: 17% of 1000 = 170 raw, halved to 85.0.
        assert payload["target_effective_max_health"] == pytest.approx(1000.0)
        assert payload["effective_mr"] == pytest.approx(100.0)
        assert row["name"] == "Living Forge (Temper)"
        assert row["total_damage"] == pytest.approx(85.0)
        assert row["count"] == 1

    def test_the_passive_slot_reads_modeled_through_that_channel(self):
        contract = get_champion_module_contract("Ornn")
        assert contract.coverage["P"] == "modeled"
        assert contract.coverage_channels["P"] == ("post_hit_proc",)
        assert "out_of_scope" not in set(contract.coverage.values())

    def test_bellows_breath_only_refreshes_the_debuff_it_applies(self):
        """W applies Brittle and prices no consume of its own."""
        w_row = row_review.entry("Ornn", "W")
        assert "post_hit_proc" not in w_row
        assert "final gout applies Brittle" in w_row["detail"]

    def test_bellows_breath_stamps_the_maximum_health_row_it_prices(self):
        """Both W damage rows are % of the target's maximum health.

        The stamp is the row's own statement that its number moves with
        the target's maximum health — R carries it for Temper's consume,
        and W's ticks are the same kind of number.
        """
        w_ability = get_champion("Ornn")["abilities"]["W"][0]
        units = {
            unit
            for effect in w_ability["effects"]
            for leveling in effect.get("leveling") or []
            if leveling["attribute"] in ("Total Magic Damage", "Magic Damage Per Tick")
            for modifier in leveling["modifiers"]
            for unit in modifier["units"]
        }
        assert units == {"% of target's maximum health"}
        assert row_review.entry("Ornn", "W")["target_max_health_sensitive"] is True
        # The priced total tracks the target: 12% of maximum health per
        # rank-1 cast, so a 4000-health dummy takes twice a 2000's.
        assert _w_total(2000.0) == pytest.approx(0.5 * _w_total(4000.0))
