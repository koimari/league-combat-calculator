"""Kennen's crowd-control review: every slot withholds, and none for timing.

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.  Kennen has
no ``MODULE_CC`` because Mark of the Storm puts the stun on the target's
stack count rather than on any one ability — the third application stuns,
the first two do not, and every slot is capable of being either.  P's own
row carries the walk that says which applications those were.
"""

import copy

import pytest

from src.calculator.champions import kennen, parse_champion_abilities
from src.calculator.scenario import load_public_champion
from tests import cc_review, row_review

# The mark walk reads cooldowns, so every walk test parses at zero haste
# and with no auto stream: Q 4s, W 6s, E 6s and R 120s at maximum rank are
# then the cached numbers themselves and the stream is hand-checkable.
_NO_HASTE = {
    "ability_haste": 0.0,
    "basic_ability_haste": 0.0,
    "attack_speed": 0.0,
    "ability_power": 0.0,
}
_MAX_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}


def _walk(level=18, data=None, **options):
    """Kennen's Mark of the Storm row over a timed window at zero haste."""
    parsed = parse_champion_abilities(
        data if data is not None else load_public_champion("Kennen"),
        level,
        0.0,
        _MAX_RANKS,
        champion_stats=dict(_NO_HASTE),
        champion_options=options or None,
    )
    return parsed["passive"]


class TestMarkOfTheStormWalk:
    """P: the per-target consume, walked over this target's applications.

    At zero haste a 10s window applies marks from Q at 0/4/8, W at 0/6,
    E at 0/6 and Slicing Maelstrom's three permitted bolts at 0.5/1.0/1.5
    — so every third-mark stun is hand-countable.
    """

    def test_the_third_application_stuns_and_the_next_two_do_not(self):
        """Three marks at t=0, three more by t=1.5, three more by t=6."""
        detail = _walk(fight_duration_seconds=10.0)["detail"]
        assert "3 third-mark stun(s)" in detail
        assert "at 0.00s/1.25s, 1.50s/0.5s, 6.00s/0.5s" in detail

    def test_a_repeat_stun_inside_the_sourced_window_is_shortened(self):
        """1.25s the first time, 0.5s "on the same target again within 6"."""
        detail = _walk(fight_duration_seconds=10.0)["detail"]
        assert detail.count("/0.5s") == 2
        assert detail.count("/1.25s") == 1

    def test_opening_marks_move_the_first_stun_earlier(self):
        """Two marks already on the target: the very first cast detonates.

        Without them the same 1s window reaches only two marks and stuns
        nothing at all.
        """
        seeded = _walk(fight_duration_seconds=1.0, mark_stacks=2)["detail"]
        assert seeded.startswith("2 third-mark stun(s) at 0.00s/1.25s, 0.50s/0.5s")
        empty = _walk(fight_duration_seconds=0.0, mark_stacks=0)["detail"]
        assert "1 third-mark stun(s) at 0.00s/1.25s" in empty

    def test_the_storm_alone_can_reach_three_marks(self):
        """R applies "only up to 3 stacks on a target" — exactly one stun."""
        parsed = parse_champion_abilities(
            load_public_champion("Kennen"),
            18,
            0.0,
            {"Q": 0, "W": 0, "E": 0, "R": 3},
            champion_stats=dict(_NO_HASTE),
            champion_options={"fight_duration_seconds": 10.0},
        )
        assert "1 third-mark stun(s) at 1.50s/1.25s" in parsed["passive"]["detail"]

    def test_an_autos_only_window_applies_no_marks(self):
        detail = _walk(
            fight_duration_seconds=10.0, mark_stacks=1, auto_attacks_only=True
        )["detail"]
        assert "0 third-mark stun(s) (the walk ends at 1/3 marks)" in detail

    def test_the_empowered_surge_attack_applies_its_own_mark(self):
        """The four-stack attack marks on the first swing and every fifth."""
        parsed = parse_champion_abilities(
            load_public_champion("Kennen"),
            18,
            0.0,
            {"Q": 0, "W": 0, "E": 0, "R": 0},
            champion_stats={**_NO_HASTE, "attack_speed": 1.0},
            champion_options={
                "fight_duration_seconds": 20.0,
                "auto_attack_uptime": 1.0,
            },
        )
        # One swing per second: the empowered ones are at 0, 5, 10 and 15,
        # each inside the previous mark's 6s window, so the third lands at
        # 10s and the 15s swing only re-opens the count.
        assert "1 third-mark stun(s) at 10.00s/1.25s" in parsed["passive"]["detail"]

    def test_a_cache_that_stops_stating_the_repeat_rule_fails_closed(self):
        data = copy.deepcopy(load_public_champion("Kennen"))
        effect = data["abilities"]["P"][0]["effects"][1]
        effect["description"] = effect["description"].split(". The stun")[0] + "."
        with pytest.raises(ValueError, match="the repeat stun's reduced duration"):
            _walk(data=data, fight_duration_seconds=10.0)

    def test_a_cache_that_stops_limiting_the_storm_fails_closed(self):
        data = copy.deepcopy(load_public_champion("Kennen"))
        data["abilities"]["P"][0]["effects"][2]["description"] = ""
        with pytest.raises(ValueError, match="per-target stack limit"):
            _walk(data=data, fight_duration_seconds=10.0)


class TestReviewedCrowdControl:
    """Why Kennen withholds: the stun belongs to the mark, not the slot."""

    def test_the_kit_declares_nothing_because_the_mark_is_state(self):
        passive = cc_review.slot_text(cc_review.kit("Kennen"), "P")
        assert kennen.MODULE_CC == {}
        assert kennen.parse_abilities.cc_kinds == {}
        assert (
            "kennen's abilities apply a stack of mark of the storm to "
            "enemies hit for 6 seconds, refreshing on subsequent "
            "applications and stacking up to 3 times" in passive
        )
        assert (
            "the third stack against a target consumes them all to stun "
            "them for 1.25 seconds" in passive
        )

    def test_no_damaging_slot_states_a_control_of_its_own(self):
        """Q, W and E only damage; the storm's own entry never says stun."""
        data = cc_review.kit("Kennen")
        for slot in ("Q", "W", "E", "R"):
            assert cc_review.control_words(cc_review.slot_text(data, slot)) == [], slot

    def test_the_storm_already_strikes_on_its_sourced_cadence(self):
        """R's blocker is the kind alone: its bolts are authored hits.

        "Kennen summons a storm around himself for 3 seconds" and "the
        storm strikes lightning bolts down on nearby enemies every 0.5
        seconds" — six bolts on a half-second beat, which the module
        authors, so R reaches the event ledger and still cannot say what
        the bolt that lands the third mark did.
        """
        r_text = cc_review.slot_text(cc_review.kit("Kennen"), "R")
        assert "kennen summons a storm around himself for 3 seconds" in r_text
        assert (
            "the storm strikes lightning bolts down on nearby enemies "
            "every 0.5 seconds" in r_text
        )
        (bolts,) = row_review.parts("Kennen", "R")
        assert (bolts.time_offset, bolts.hit_interval, bolts.count) == (0.5, 0.5, 6)
        assert bolts.cc_kind is None

    def test_the_unreviewable_slots_keep_the_fight_coarse(self):
        assert cc_review.unreviewed_ability_slots("Kennen") == ["E", "Q", "R", "W"]
        coverage = cc_review.fimbulwinter_coverage("Kennen")
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]


def test_the_storm_certifies_nothing_it_is_not():
    """R carries no ``event_order_certified``, and needs none.

    The vocabulary is a string every reader compares against
    ("single_hit" / "auto_stack_proc"), so a ``True`` on this row could
    never match one; six bolts on a half-second beat are neither
    kind anyway, and the part's own cadence is what the ledger reads.
    """
    entry = row_review.entry("Kennen", "R", r_bolts=6)
    assert "event_order_certified" not in entry
    (bolts,) = entry["parts"]
    assert (bolts.time_offset, bolts.hit_interval, bolts.count) == (0.5, 0.5, 6)
