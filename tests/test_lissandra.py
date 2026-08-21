"""Revision-backed tests for Lissandra's direct-damage slot map."""

import pytest

from tests.ability_math import parts_raw_total
from src.calculator.calculate import calculate_payload
from src.calculator.champions import lissandra


def test_lissandra_full_rotation_uses_each_direct_hit(lissandra_data, parse_at):
    _, abilities = parse_at(
        lissandra_data,
        18,
        ap=200,
        ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
    )

    expected = {"Q": 370.0, "W": 350.0, "E": 330.0, "R": 500.0}
    assert set(abilities) == set(expected) | {"passive"}
    for slot, raw in expected.items():
        assert parts_raw_total(abilities[slot]["parts"], "magic") == pytest.approx(raw)


class TestPassive:
    """P (Iceborn Subjugation) emits a zero-damage boundary receipt."""

    def test_passive_emits_zero_damage_row(self, lissandra_data, parse_at) -> None:
        _, abilities = parse_at(
            lissandra_data,
            18,
            ap=200,
            ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
        )
        assert abilities["passive"]["name"] == "Iceborn Subjugation"
        assert abilities["passive"]["total_raw"] == pytest.approx(0.0)
        assert abilities["passive"]["parts"] == ()
        assert abilities["passive"]["damage_type"] == "magic"
        # Sourced would-be shatter magnitude at level 18 ("Per-Level
        # Scaling" cached leveling row), reported for traceability only.
        assert "520" in abilities["passive"]["detail"]


def test_lissandra_rotation_is_mitigated_and_resource_ordered(
    lissandra_data, parse_at, fight
):
    stats, abilities = parse_at(
        lissandra_data,
        18,
        ap=200,
        ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
    )
    result = fight(stats, abilities, target_magic_resistance=100)

    assert result["total_damage"] == pytest.approx(775.0)
    assert [event["slot"] for event in result["cast_timeline"]] == [
        "Q",
        "W",
        "E",
        "R",
    ]
    assert sum(ability["resource_cost"] for ability in abilities.values()) == 315.0
    assert stats["max_mana"] >= 315.0


# ---------------------------------------------------------------------------
# Reviewed crowd control (MODULE_CC)
# ---------------------------------------------------------------------------


def _slot_text(cached, slot):
    """Every cached description of one slot, lowercased."""
    return " ".join(
        effect.get("description") or ""
        for ability in cached["abilities"][slot]
        for effect in ability.get("effects", [])
    ).lower()


class TestReviewedCrowdControl:
    """Lissandra's kit facts, held to the cached text and to the ledger.

    A control-armed holder shield (Fimbulwinter's Everlasting) reads a
    control marker off ability damage events; one unreviewed ability
    packet makes the whole timed fight fall back to coarse ordering.
    """

    def test_declared_kinds_quote_the_cached_text(self, lissandra_data):
        assert lissandra.MODULE_CC == {
            "Q": "slow",
            "W": "root",
            "E": "none",
            "R": "slow",
        }
        assert "slows enemies hit for 1.5 seconds" in _slot_text(lissandra_data, "Q")
        assert "rooting them for a duration" in _slot_text(lissandra_data, "W")
        # R's priced instance is the ice field, which slows on either cast;
        # the enemy cast's stun is not the hit the module counts.
        assert "slowing them for 0.5 seconds" in _slot_text(lissandra_data, "R")

    def test_the_reviewed_absence_read_the_whole_slot(self, lissandra_data):
        """E's claw only decelerates itself — no control word at all."""
        text = _slot_text(lissandra_data, "E")
        assert "slow" not in text
        assert "root" not in text
        assert "stun" not in text

    def test_every_ability_event_carries_the_review(self, lissandra_data):
        """Reviewing a kit only counts where the ledger can see it."""
        parsed = lissandra.parse_abilities(lissandra_data, 18, 100.0)
        for slot, kind in lissandra.MODULE_CC.items():
            parts = parsed[slot]["parts"]
            assert parts, slot
            assert {part.cc_kind for part in parts} == {kind}, slot

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        """The campaign's control-token probe, through the public entry."""
        coverage = calculate_payload(
            {
                "champion": "Lissandra",
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
