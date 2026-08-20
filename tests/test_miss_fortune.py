"""Miss Fortune — the reviewed crowd control its kit declares (MODULE_CC).

The declaration is not decoration: a control-armed holder shield
(Fimbulwinter's Everlasting) reads a control marker off ability damage
events, and one unreviewed ability packet makes the whole timed fight
fall back to coarse ordering.  These tests hold the declaration to the
cached text it was read from, and prove it reaches the event ledger.
"""

import pytest

from src.calculator.calculate import calculate_payload
from src.calculator.champions import get_champion_module_contract, miss_fortune
from src.calculator.data_fetcher import get_champion
from tests import rider_probe, row_review

# Every control word the Wiki uses for the classes an item passive keys on.
CONTROL_WORDS = (
    "stun",
    "root",
    "snare",
    "charm",
    "fear",
    "flee",
    "taunt",
    "sleep",
    "suppress",
    "knock",
    "airborne",
    "pull",
    "slow",
    "immobiliz",
    "stasis",
    "drowsy",
    "cripple",
    "polymorph",
    "disarm",
    "silence",
)

# The phrase each declared kind was read from, in that slot's cached text.
QUOTED = {"E": "slowing them by 40%"}

# No reviewed-absent slot's cached text carries a control word at all.
UNCONTROLLED_MENTIONS: dict[str, list[str]] = {}


@pytest.fixture(scope="module")
def cached():
    return get_champion("Miss Fortune")


def slot_text(cached, slot):
    """Every cached description of one slot, lowercased."""
    return " ".join(
        effect.get("description") or ""
        for ability in cached["abilities"][slot]
        for effect in ability.get("effects", [])
    ).lower()


class TestReviewedCrowdControl:
    def test_declared_kinds_quote_the_cached_text(self, cached):
        assert miss_fortune.MODULE_CC == {"Q": "none", "E": "slow", "R": "none"}
        for slot, phrase in QUOTED.items():
            assert phrase in slot_text(cached, slot), slot

    def test_reviewed_absences_read_the_whole_slot(self, cached):
        """A "none" is a slot that was read, not a slot that was skipped."""
        for slot, kind in miss_fortune.MODULE_CC.items():
            if kind != "none":
                continue
            hits = [word for word in CONTROL_WORDS if word in slot_text(cached, slot)]
            assert hits == UNCONTROLLED_MENTIONS.get(slot, []), slot

    def test_every_ability_event_carries_the_review(self, cached):
        """Reviewing a kit only counts where the ledger can see it."""
        parsed = miss_fortune.parse_abilities(cached, 18, 100.0)
        for slot, kind in miss_fortune.MODULE_CC.items():
            parts = parsed[slot]["parts"]
            assert parts, slot
            assert {part.cc_kind for part in parts} == {kind}, slot

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        """The campaign's control-token probe, through the public entry."""
        coverage = calculate_payload(
            {
                "champion": "Miss Fortune",
                "level": 18,
                "items": ["Fimbulwinter"],
                "fight_mode": "timed",
                "include_auto_attacks": True,
            }
        )["timeline_coverage"]

        assert coverage["complete"] is True
        assert coverage["certification"] == "event_order_certified"
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
        assert coverage["coarse_sources"] == []


class TestLoveTap:
    """P: the AD-scaled bonus on an attack that tags a NEW enemy."""

    def test_the_ratio_is_the_cached_six_band_row(self, cached):
        """The champion row is 50 : 100; the minion half-row is not read."""
        champion_band, minion_band = [
            leveling["modifiers"][0]["values"]
            for effect in cached["abilities"]["P"][0]["effects"]
            for leveling in effect["leveling"]
        ]
        assert champion_band == [50, 60, 70, 80, 90, 100]
        assert minion_band == [25, 30, 35, 40, 45, 50]
        # Level 18 is past the last breakpoint (13), so the ratio is 100%
        # of the 200 total AD row_review fixes.
        on_hit = row_review.entry("Miss Fortune", "passive")["on_hit"]
        assert on_hit["damage_type"] == "physical"
        assert on_hit["damage_per_hit"] == pytest.approx(200.0)
        assert on_hit["max_procs"] == 1

    def test_one_tap_reaches_the_fight_total_by_default(self):
        result = rider_probe.fight("Miss Fortune")
        row = result["breakdown"][rider_probe.RIDER_ROW]
        assert row["name"] == "Love Tap (on-hit)"
        assert row["count"] == 1
        assert result["breakdown"]["auto_attacks"]["count"] == 10
        assert row["total_damage"] == pytest.approx(48.0, abs=0.05)

    def test_tagging_more_targets_prices_more_taps(self):
        result = rider_probe.fight("Miss Fortune", champion_options={"p_procs": 3})
        row = result["breakdown"][rider_probe.RIDER_ROW]
        assert row["count"] == 3
        assert row["total_damage"] == pytest.approx(144.0, abs=0.05)

    def test_no_tap_prices_nothing(self):
        result = rider_probe.fight("Miss Fortune", champion_options={"p_procs": 0})
        assert rider_probe.RIDER_ROW not in result["breakdown"]


class TestStrut:
    """W: the sourced attack-speed active, through stat_buff."""

    def test_the_buff_is_the_cached_bonus_attack_speed_row(self, cached):
        rows = {
            leveling["attribute"]: leveling["modifiers"][0]["values"]
            for effect in cached["abilities"]["W"][0]["effects"]
            for leveling in effect.get("leveling") or []
        }
        assert rows["Bonus Attack Speed"] == [40, 55, 70, 85, 100]
        entry = row_review.entry("Miss Fortune", "W")
        assert entry["stat_buff"] == {"bonus_attack_speed": 100.0}
        assert entry["total_raw"] == 0.0

    def test_every_slot_now_prices_something(self):
        assert get_champion_module_contract("Miss Fortune").coverage == {
            slot: "modeled" for slot in "PQWER"
        }
