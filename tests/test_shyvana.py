"""Shyvana's reviewed crowd control (``MODULE_CC``) and Scalemail.

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

import copy

import pytest

from src.calculator.calculate import calculate_payload
from src.calculator.champions import (
    get_champion_module_contract,
    parse_champion_abilities,
    shyvana,
)
from src.calculator.data_fetcher import get_champion
from tests import cc_review, row_review


class TestReviewedCrowdControl:
    """Shyvana's reviewed crowd control, and what declaring it clears."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Shyvana")
        assert shyvana.MODULE_CC == {
            "Q": "none",
            "W": "none",
            "E": "slow",
            "R": "fear",
            "P": "none",
        }
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == []
        assert "slowing them by 30% for 2 seconds" in cc_review.slot_text(data, "E")
        # R also slows by 99%; the fear is the immobilizing half, which is
        # the answer a control-armed reader needs.
        assert "fears them for 0.75 seconds" in cc_review.slot_text(data, "R")

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Shyvana") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Shyvana")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


class TestScalemail:
    """P prices the ``scalemail_stacks`` option the module declares.

    The per-stack resists live in the cached effect sentence and nowhere
    else — the entry carries no leveling row at all — so the parser reads
    the sentence rather than copying a number out of it.
    """

    def test_the_sentence_is_the_only_source_the_entry_has(self):
        passive = get_champion("Shyvana")["abilities"]["P"][0]
        assert [
            leveling for effect in passive["effects"] for leveling in effect["leveling"]
        ] == []
        assert (
            "For each stack, Shyvana gains 0.3 bonus armor and 0.3 bonus "
            "magic resistance" in passive["effects"][1]["description"]
        )
        assert shyvana._scalemail_per_stack(passive) == (0.3, 0.3)

    def test_the_option_moves_the_row_it_declares(self):
        empty = row_review.entry("Shyvana", "passive")
        stacked = row_review.entry("Shyvana", "passive", scalemail_stacks=12)
        assert empty["stat_buff"] == {"armor": 0.0, "magic_resistance": 0.0}
        assert stacked["stat_buff"] == {
            "armor": pytest.approx(3.6),
            "magic_resistance": pytest.approx(3.6),
        }
        assert "12 Scalemail stack(s)" in stacked["detail"]

    def test_the_grant_reaches_a_real_fight(self):
        """The published stat block carries the stacks the request set."""

        def armor(stacks):
            return calculate_payload(
                {
                    "champion": "Shyvana",
                    "level": 18,
                    "items": [],
                    "fight_mode": "timed",
                    "champion_options": {"scalemail_stacks": stacks},
                }
            )["champion_stats"]["armor"]

        assert armor(20) - armor(0) == pytest.approx(6.0)

    def test_the_passive_slot_no_longer_reads_out_of_scope(self):
        contract = get_champion_module_contract("Shyvana")
        assert contract.coverage["P"] == "no_damage"
        assert "out_of_scope" not in set(contract.coverage.values())

    def test_the_published_assumption_names_the_cached_passive(self):
        """The assumption's ability name is the cache's, not a stale one.

        The prose read "Fury of the Dragonborn" — a name that appears
        nowhere in ``data/champions.json`` — while the emitted row and
        the parser both name "Scalemail".  A published assumption naming
        a different ability than the row it describes is a second home
        that can disagree with the first, so the name is pinned here.
        """
        cached_name = get_champion("Shyvana")["abilities"]["P"][0]["name"]
        assert cached_name == "Scalemail"
        (stated,) = [
            text
            for text in get_champion_module_contract("Shyvana").assumptions
            if text.startswith("P (")
        ]
        assert stated.startswith(f"P ({cached_name})")

    def test_the_no_damage_verdict_is_what_the_passive_entry_holds(self):
        """``no_damage`` is the entry's own reading, not a convention.

        Both halves of the disposition are checked against the cache: the
        entry declares no damage type and self-only effects, and the row
        the parser emits carries a stat buff with zero damage in it.
        """
        passive = get_champion("Shyvana")["abilities"]["P"][0]
        assert passive["damageType"] is None
        assert passive["affects"] == "Self"
        entry = row_review.entry("Shyvana", "passive", scalemail_stacks=12)
        assert entry["stat_buff"] == {
            "armor": pytest.approx(3.6),
            "magic_resistance": pytest.approx(3.6),
        }
        # The row is a declared steroid zero (``STEROID_ZERO``), so it keeps
        # one zero-amount part rather than none — the disposition is that
        # nothing the enemy takes is priced, not that the row is absent.
        assert entry["total_raw"] == 0.0
        assert [part.amount for part in entry["parts"]] == [0.0]

    def test_prose_that_no_longer_states_the_resists_raises(self):
        stripped = copy.deepcopy(get_champion("Shyvana"))
        effect = stripped["abilities"]["P"][0]["effects"][1]
        effect["description"] = effect["description"].replace("0.3 bonus armor", "more")
        with pytest.raises(ValueError, match=r"Shyvana P .Scalemail."):
            parse_champion_abilities(stripped, 18, 0.0, row_review.RANKS)
