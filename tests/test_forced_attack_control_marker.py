"""A forced attack carries its slot's reviewed control marker in every window.

An ``empowers_next_auto`` ability is delivered by the basic attack it forces.
With an auto stream the engine lands the slot's declared ``cc_kind`` on the
consumed swing; without one (one rotation, autos off) the same attack is the
row's own lump or its engine-appended swing part, and it carries the same
marker.  A reviewed slot therefore certifies a control-armed holder shield
(Fimbulwinter's Everlasting) with the stream on and off alike, and an
undeclared slot stays unreviewed in both.
"""

import pytest

from src.calculator.trigger_stream import is_immobilizing_event
from tests import cc_review

NO_STREAM = (
    pytest.param({"fight_mode": "one_rotation"}, id="one_rotation"),
    pytest.param(
        {"fight_mode": "timed", "include_auto_attacks": False}, id="timed_autos_off"
    ),
)


@pytest.mark.parametrize("window", NO_STREAM)
@pytest.mark.parametrize(
    "champion",
    ["Jax", "Vayne", "Leona", "Fizz", "Vi", "Shen", "Camille", "Jayce", "Kayle"],
)
def test_a_reviewed_kit_certifies_without_an_auto_stream(champion, window):
    assert cc_review.unreviewed_ability_slots(champion, **window) == []
    coverage = cc_review.fimbulwinter_coverage(champion, **window)
    assert coverage["complete"] is True
    assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


def test_the_forced_attack_lump_carries_the_declared_kind():
    """Jax W (declared none) authors no events of its own in one rotation;
    the ledger's lump for it is the attack the cast forced."""
    lumps = [
        event
        for event in cc_review.damage_events("Jax", fight_mode="one_rotation")
        if event["source_key"] == "W"
    ]

    assert lumps
    assert all(event.get("basic_attack") for event in lumps)
    assert {(event["cc_kind"], event["cc_reviewed"]) for event in lumps} == {
        ("none", True)
    }


def test_a_forced_stun_is_an_immobilize_event_at_its_cast():
    """Leona Q's stun rides the swing it forces; with no stream that swing
    is the Q lump at Q's cast, and Command / Everlasting read it there."""
    events = cc_review.damage_events("Leona", fight_mode="one_rotation")
    q_events = [event for event in events if event["source_key"] == "Q"]

    assert q_events
    assert all(is_immobilizing_event(event) for event in q_events)
    assert {event["cc_kind"] for event in q_events} == {"stun"}


def test_an_engine_appended_swing_part_carries_the_kind():
    """Fizz W authors its own events; the forced swing the engine appends
    to the cast's parts is stamped with the slot's declared kind too."""
    swings = [
        event
        for event in cc_review.damage_events("Fizz", fight_mode="one_rotation")
        if event["source_key"] == "W" and event.get("basic_attack")
    ]

    assert swings
    assert {event.get("cc_kind") for event in swings} == {"none"}


@pytest.mark.parametrize("window", NO_STREAM)
def test_a_reviewed_absence_carries_no_marker_and_still_certifies(window):
    """Control: the marker is the module's declaration, never invented —
    Sett Q reviews its way to no control, so its events say ``"none"`` and
    the scan has nothing left to withhold on."""
    from src.calculator.champions import sett

    assert sett.MODULE_CC["Q"] == "none"
    assert cc_review.unreviewed_ability_slots("Sett", **window) == []
    coverage = cc_review.fimbulwinter_coverage("Sett", **window)
    assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
