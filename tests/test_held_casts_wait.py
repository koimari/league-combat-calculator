"""A cast an action-blocking control holds waits for its caster, never dropped.

The coupled walk judges a cast when it is made (``survival/transitions.py``):
one made while its caster can act lands whatever holds the caster later, one
made while a stun or charm holds the caster moves to the moment the caster
is free, and every cast one hold blocks moves by the same shift.
"""

import pytest

from src.calculator.calculate import calculate_payload

_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}


def _versus_ahri(champion):
    return calculate_payload(
        {
            "champion": champion,
            "level": 13,
            "items": [],
            "role": "mid",
            "fight_mode": "time_based",
            "fight_duration": 10,
            "enemies": [{"champion": "Ahri", "level": 13, "items": [], "role": "mid"}],
        },
        deterministic=True,
    )


def _lux_versus_amumu(items=(), item_options=None):
    return calculate_payload(
        {
            "champion": "Lux",
            "level": 18,
            "items": list(items),
            "item_options": item_options or {},
            "fight_mode": "time_based",
            "fight_duration": 8,
            "ability_ranks": dict(_RANKS),
            "enemies": [
                {
                    "champion": "Amumu",
                    "level": 18,
                    "items": [],
                    "ability_ranks": dict(_RANKS),
                }
            ],
        },
        deterministic=True,
    )


def _main_casts(payload, *slots):
    return [
        (event["time"], event["source"])
        for event in payload["combat"]["events"]
        if event["attacker"] == "main" and event["source"] in slots
    ]


def test_a_cast_planned_inside_a_charm_lands_when_the_charm_ends():
    """Taric's E, his only damage, is planned at 0.5 s inside Ahri's 0-1.2 s
    charm; it lands at 1.2 s rather than vanishing."""
    payload = _versus_ahri("Taric")
    assert _main_casts(payload, "E")[:1] == [(1.2, "E")]
    assert payload["headline_total"] == pytest.approx(62.5, abs=0.1)


def test_a_hold_another_stun_extends_moves_the_rotation_once_with_its_spacing():
    """Amumu's Q stuns Lux 0-1.0 s and his R 0.5-2.0 s.  Her Q and R, planned
    0.25 s apart inside the hold, land at 2.0 and 2.25 s: the extension moves
    them once more, by the extension alone, and they keep their spacing."""
    assert _main_casts(_lux_versus_amumu(), "Q", "R")[:2] == [(2.0, "Q"), (2.25, "R")]


def test_a_cleanse_that_ends_the_hold_brings_the_rotation_back():
    """Quicksilver Sash at 0.5 s frees Lux, so the casts the hold had moved
    land from 0.5 s, not from where the hold would have ended."""
    payload = _lux_versus_amumu(
        items=("Quicksilver Sash",),
        item_options={"Quicksilver Sash": {"active_seconds": 0.5}},
    )
    assert _main_casts(payload, "Q", "R")[:2] == [(0.5, "Q"), (0.75, "R")]


@pytest.mark.parametrize("champion", ["Brand", "Taric"])
def test_published_events_stay_in_time_order_after_a_cast_moves(champion):
    events = _versus_ahri(champion)["combat"]["events"]
    times = [event["time"] for event in events]
    assert times == sorted(times)


def test_a_cast_made_at_the_holds_own_instant_still_lands_inside_it():
    """Fiddlesticks casts Q at 0.0 s, the instant Ahri's charm lands, so the
    cast goes off and its fear reaches her at 0.35 s while he is still
    charmed: a control at the cast's own instant does not hold it, which is
    what keeps the walk's three adapters from deciding it by read order."""
    combat = _versus_ahri("Fiddlesticks")["combat"]
    mine, theirs = (row["survival"] for row in combat["participants"][:2])
    assert [(row["start"], row["end"]) for row in mine["action_downtime_intervals"]][
        :1
    ] == [(0.0, 1.2)]
    fear = next(
        row for row in theirs["crowd_control_intervals"] if row["source"] == "Q"
    )
    assert fear["kind"] == "fear"
    assert fear["start"] == pytest.approx(0.35)
