"""The swing-stream gate holds the scan to its pinned frontier (issue #329).

A cached slot that puts damage on every basic attack, or carries a Bonus
Attack Speed row, publishes a swing key or sits on the frontier with its
reason; a new hit and a stale frontier row both fail here.
"""

import pytest

from scripts import swing_stream_audit as audit


def test_every_flagged_slot_rides_the_swings_or_is_on_the_frontier() -> None:
    new, stale = audit.drift()
    assert new == {}, f"slots priced once per cast with no stated boundary: {new}"
    assert stale == [], f"frontier rows the scan no longer flags: {stale}"


def test_the_frontier_names_its_reasons() -> None:
    assert all(reason.strip() for reason in audit.FRONTIER.values())
    assert all(slot in audit.SLOTS for _, slot in audit.FRONTIER)


@pytest.mark.parametrize(
    "text",
    [
        "Passive: Teemo's basic attacks are empowered to deal bonus magic damage "
        "on-hit and inflict poison.",
        "Innate: Mordekaiser's basic attacks are empowered to deal 40% AP bonus "
        "magic damage on-hit.",
        "Active: Master Yi empowers his basic attacks within the next 5 seconds "
        "to deal bonus true damage on-hit.",
        "Innate: Ashe's basic attacks deal bonus physical damage equal to 0% : "
        "100% of her critical strike chance.",
    ],
)
def test_per_attack_rider_text_is_a_rider(text: str) -> None:
    assert audit._per_attack_rider(text)


@pytest.mark.parametrize(
    "text",
    [
        "The stab deals physical damage and applies on-hit effects.",
        "Active: Fizz empowers his next basic attack within 4 seconds to deal "
        "bonus magic damage.",
        "Udyr empowers his next two basic attacks on-hit to deal magic damage.",
        "Innate: Renekton's basic attacks generate 5 Fury on-hit.",
    ],
)
def test_one_shot_and_carrier_text_is_not_a_rider(text: str) -> None:
    assert not audit._per_attack_rider(text)


def test_a_swing_key_or_an_attack_speed_grant_rides_the_swings() -> None:
    assert audit._rides_the_swings([{"on_hit": {}}], attack_speed=False)
    assert audit._rides_the_swings([{"stacking_dot": {}}], attack_speed=False)
    assert audit._rides_the_swings(
        [{"stat_buff": {"bonus_attack_speed": 40.0}}], attack_speed=True
    )
    # An attack-speed grant answers only an attack-speed row, and a plain
    # cast row answers neither.
    assert not audit._rides_the_swings(
        [{"stat_buff": {"bonus_attack_speed": 40.0}}], attack_speed=False
    )
    assert not audit._rides_the_swings(
        [{"parts": (), "total_raw": 165.0}], attack_speed=True
    )


def test_a_slots_secondary_rows_answer_for_it() -> None:
    results = {
        "passive": {"parts": (), "total_raw": 0.0},
        "passive_darkness_rise": {"on_hit": {}},
        "E": {"parts": ()},
        "E_passive": {"stacking_dot": {}},
    }
    assert audit._rides_the_swings(audit._entries_for(results, "P"), attack_speed=False)
    assert audit._rides_the_swings(audit._entries_for(results, "E"), attack_speed=False)
    assert not audit._rides_the_swings(
        audit._entries_for(results, "Q"), attack_speed=False
    )
