"""Module-authored self state windows, expanded over the cast times that admit them.

The front door for :mod:`src.calculator.self_state_effects`: one packet per
authored atom per accepted cast, and a refusal for every shape a champion module
may not author.
"""

from typing import Any

import pytest

from src.calculator.self_state_effects import derive_self_state_effects
from src.calculator.survival.classify import SUPPORT_RANK_KEY
from src.calculator.survival.phases import TransitionRank

_CASTS = [
    {"slot": "W", "time": 3.0},
    {"slot": "W", "time": 1.0},
    {"slot": "Q", "time": 0.5},
]


def _entry(*events: dict[str, Any]) -> dict[str, Any]:
    return {"W": {"rank": 3, "self_state_events": list(events)}, "Q": {"rank": 1}}


def _events(*events: dict[str, Any]) -> list[dict[str, Any]]:
    return derive_self_state_effects(_entry(*events), _CASTS)


SHIELD = {"kind": "spell_shield", "duration": 1.5, "source": "Sivir E"}
REDUCTION = {
    "kind": "damage_modifier",
    "duration": 2.0,
    "time_offset": 0.25,
    "source": "Briar E",
    "multiplier": 0.7,
    "damage_reduction": True,
    "damage_classes": ["physical"],
    SUPPORT_RANK_KEY: TransitionRank.AURA_ARM,
    "source_atoms": [{"atom_id": "ability.duration", "hash": "abc"}],
}


def test_one_packet_per_authored_atom_per_accepted_cast() -> None:
    """Two atoms over two W casts is four packets, sorted by their own time."""
    events = _events(SHIELD, REDUCTION)
    assert [(event["time"], event["kind"]) for event in events] == [
        (1.0, "spell_shield"),
        (1.25, "damage_modifier"),
        (3.0, "spell_shield"),
        (3.25, "damage_modifier"),
    ]
    assert all(event["slot"] == "W" for event in events), "Q authors no state"


def test_an_event_id_indexes_the_cast_timeline_not_the_sorted_output() -> None:
    """The id names the cast the packet came from, so a resort cannot renumber it."""
    events = _events(SHIELD)
    assert [event["_event_id"] for event in events] == [
        "self_state:W:1:0",
        "self_state:W:0:0",
    ]


def test_a_packet_carries_the_typed_fields_the_kernel_reads() -> None:
    """Self-targeting, the authored rank, the numbers and the atom receipts."""
    packet = _events(REDUCTION)[0]
    assert packet["target_self"] is True
    assert packet["target_scope"] == "self"
    assert packet["source_key"] == "W"
    assert packet["rank"] == 3
    assert packet["multiplier"] == pytest.approx(0.7)
    assert packet["damage_reduction"] is True
    assert packet["damage_classes"] == ["physical"]
    assert packet[SUPPORT_RANK_KEY] is TransitionRank.AURA_ARM
    assert packet["source_atoms"] == [{"atom_id": "ability.duration", "hash": "abc"}]


def test_a_slot_with_no_cast_authors_nothing() -> None:
    """The cast timeline supplies the only valid time, so no cast is no packet."""
    assert derive_self_state_effects(_entry(SHIELD), [{"slot": "Q", "time": 0.5}]) == []


@pytest.mark.parametrize(
    ("event", "message"),
    [
        ({"kind": "nope", "duration": 1.0, "source": "x"}, "not supported"),
        ({"kind": "stasis", "duration": 0.0, "source": "x"}, "must be positive"),
        ({"kind": "stasis", "duration": 1.0}, "source is required"),
        (
            {"kind": "stasis", "duration": 1.0, "source": "x", SUPPORT_RANK_KEY: 999},
            "must be a TransitionRank member",
        ),
        (
            {"kind": "stasis", "duration": 1.0, "source": "x", "multiplier": "no"},
            "must be numeric",
        ),
        (
            {"kind": "stasis", "duration": 1.0, "source": "x", "source_atoms": {}},
            "must be a list",
        ),
    ],
)
def test_an_unauthorable_shape_fails_closed(
    event: dict[str, Any], message: str
) -> None:
    """Every refusal names the slot, so a champion module's typo is locatable."""
    with pytest.raises(ValueError, match=message) as refusal:
        _events(event)
    assert str(refusal.value).startswith("W ")


def test_self_state_events_must_be_a_list() -> None:
    """A mapping where a list belongs is an authoring error, not an empty schedule."""
    with pytest.raises(ValueError, match="must be a list"):
        derive_self_state_effects({"W": {"self_state_events": {}}}, _CASTS)
