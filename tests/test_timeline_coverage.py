"""Contracts for combining fight-order precision receipts."""

from src.calculator.timeline_coverage import (
    combine_timeline_coverages,
    downgrade_timeline_sources,
)


def test_combined_receipt_stays_exact_when_every_target_is_exact():
    receipt = combine_timeline_coverages(
        [
            {
                "complete": True,
                "exact_sources": ["Q", "auto_attacks"],
                "coarse_sources": [],
            },
            {
                "complete": True,
                "exact_sources": ["Q", "burn_Liandry's Torment"],
                "coarse_sources": [],
            },
        ],
        target_count=2,
    )

    assert receipt["complete"] is True
    assert receipt["certification"] == "event_order_certified"
    assert receipt["exact_sources"] == [
        "Q",
        "auto_attacks",
        "burn_Liandry's Torment",
    ]


def test_any_coarse_target_keeps_the_roster_receipt_partial():
    receipt = combine_timeline_coverages(
        [
            {
                "complete": True,
                "exact_sources": ["Q", "proc_Luden's Echo"],
                "coarse_sources": [],
            },
            {
                "complete": False,
                "exact_sources": ["Q"],
                "coarse_sources": ["proc_Luden's Echo"],
            },
        ],
        target_count=2,
    )

    assert receipt["complete"] is False
    assert receipt["certification"] == "partial_event_order"
    assert receipt["exact_sources"] == ["Q"]
    assert receipt["coarse_sources"] == ["proc_Luden's Echo"]


def test_missing_target_receipt_fails_closed():
    receipt = combine_timeline_coverages([{}], target_count=1)

    assert receipt["complete"] is False
    assert receipt["coarse_sources"] == []
    assert "unavailable" in receipt["note"].lower()


def test_later_cross_target_allocation_can_downgrade_one_exact_source():
    receipt = downgrade_timeline_sources(
        {
            "complete": True,
            "certification": "event_order_certified",
            "exact_sources": ["Q", "proc_Luden's Echo"],
            "coarse_sources": [],
            "note": "Exact.",
        },
        ["proc_Luden's Echo"],
        note="Charged damage is allocated later.",
    )

    assert receipt["complete"] is False
    assert receipt["exact_sources"] == ["Q"]
    assert receipt["coarse_sources"] == ["proc_Luden's Echo"]
    assert receipt["note"] == "Charged damage is allocated later."
