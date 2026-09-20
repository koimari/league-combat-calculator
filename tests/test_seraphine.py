"""Seraphine's reviewed crowd control (``MODULE_CC``).

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
``MODULE_CC`` is where this kit answers, read from the cached text, and the
probe below is the reason it exists.
"""

import pytest

from src.calculator.champions import get_champion_module_contract, seraphine
from tests import cc_review, rider_probe
from functools import partial
from tests import champion_closure as closure
from src.calculator.champions.slot_extract import extract_named


class TestReviewedCrowdControl:
    """Seraphine's reviewed crowd control, and what declaring it clears."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Seraphine")
        assert seraphine.MODULE_CC == {
            "Q": "none",
            "E": "slow",
            "R": "charm",
            "P": "none",
            "W": "none",
        }
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert "slows them by 99%" in cc_review.slot_text(data, "E")
        assert "charms them" in cc_review.slot_text(data, "R")

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Seraphine") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Seraphine")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


class TestStagePresenceRider:
    """Seraphine P fires her Notes on the empowered attack (census slice 6)."""

    def test_four_notes_reach_the_total(self):
        """Level 18, no items, the 4-Note cap: 4 x 25.0 raw magic.

        Cached P "Bonus Magic Damage" 4 : 27.47 (based on level) + 4% AP per
        Note; the probe target halves magic damage, so 50.0 lands.
        """
        result = rider_probe.fight("Seraphine")
        row = result["breakdown"][rider_probe.RIDER_ROW]

        assert row["name"] == "Stage Presence (on-hit)"
        assert row["count"] == 1
        assert row["total_damage"] == pytest.approx(50.0, abs=0.05)
        assert row["total_damage"] < result["total_damage"]

    def test_one_note_prices_a_quarter_of_the_cap(self):
        row = rider_probe.rider_row("Seraphine", champion_options={"p_notes": 1})
        assert row["total_damage"] == pytest.approx(12.5, abs=0.05)

    def test_no_notes_prices_nothing(self):
        result = rider_probe.fight("Seraphine", champion_options={"p_notes": 0})
        assert rider_probe.RIDER_ROW not in result["breakdown"]

    def test_every_slot_now_prices_something(self):
        assert get_champion_module_contract("Seraphine").coverage == dict.fromkeys(
            "PQWER", "modeled"
        )


# Level 18, ranks Q5/W5/E5/R3, no items, six seconds of autos at full uptime
# into a 3000-HP Aatrox whose own resistances mitigate.
_closure_fight = partial(
    closure.combat,
    mode="time_based",
    duration=6.0,
    include_autos=True,
    auto_uptime=1.0,
    target_health=3000.0,
    enemy=closure.AATROX,
)
_closure_parse = partial(closure.parse, target=closure.TARGET_3000)


# ---------------------------------------------------------------------------
# Seraphine — Q missing-health amplifier
# ---------------------------------------------------------------------------


def test_seraphine_q_hp_scaled_part_equals_maximum_enhanced_damage():
    data, stats, abilities = _closure_parse("Seraphine")
    q = data["abilities"]["Q"][0]
    base = extract_named(q, "Magic Damage", 5, stats, {})
    maximum = extract_named(q, "Maximum Enhanced Damage", 5, stats, {})
    assert base == pytest.approx(160.0)
    assert maximum == pytest.approx(280.0)  # 1.75 x base
    flat_part, enhanced_part = abilities["Q"]["parts"]
    assert flat_part.amount == pytest.approx(base)
    assert enhanced_part.hp_scaled_damage(0.0) == pytest.approx(0.0)
    assert enhanced_part.hp_scaled_damage(1.0) == pytest.approx(maximum - base)


def test_seraphine_api_q_always_at_least_the_flat_base():
    # The pair ledger re-prices the hp-scaled part at the defender's live
    # missing-health ratio, so the API total is >= the flat base mitigated
    # against the defender's own magic resistance (the fight's own stats)
    # and <= the Maximum Enhanced Damage row mitigated the same way.
    # The assertion covers High Note's missing-health amplifier. Disable
    # other damaging and control casts so their state does not change the
    # target before Q lands.
    combat = _closure_fight(
        "Seraphine",
        ranks={"Q": 5, "W": 0, "E": 0, "R": 0},
    )
    enemy_stats = closure.enemy_stats(combat)
    base_mitigated = 160.0 * 100.0 / (100.0 + enemy_stats["magic_resistance"])
    max_mitigated = 280.0 * 100.0 / (100.0 + enemy_stats["magic_resistance"])
    row = closure.main_breakdown(combat)
    q = next(s for s in row["sources"] if s["name"] == "High Note")
    assert q["total_damage"] >= base_mitigated - 0.05
    assert q["total_damage"] <= max_mitigated + 0.05
    assert q["total_damage"] > base_mitigated + 0.5  # the amp is live
