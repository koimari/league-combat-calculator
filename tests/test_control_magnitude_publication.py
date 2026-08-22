"""A sourced control magnitude publishes on the fight row that carries it.

CF8 gave ``ControlEvent`` a magnitude and nine cc-only slots declared one, but
the roster receipt published only ``cc_kind`` and ``cc_duration``: a reader
wanting the slow's strength had to re-derive it from the ranked values in
``control_source_atoms``.  ``program/views/receipt`` now publishes the leaf the
engine already carried, so the four magnitude carriers state their strength
where they state their duration.
"""

from __future__ import annotations

import pytest

from src.calculator.calculate import calculate_payload
from src.calculator.program import precision

# Champion, slot, and the level-18 max-rank control the cached rows source.
MAGNITUDE_CARRIERS = [
    ("Nasus", "W", "slow", 5.0, 95.0),
    ("Trundle", "E", "slow", 6.0, 50.0),
    ("Viktor", "W", "slow", 1.0, 45.0),
    ("Zilean", "E", "slow", 2.5, 99.0),
]


def _fight(champion: str) -> dict:
    """One published roster fight against a plain enemy."""
    return calculate_payload(
        {
            "champion": champion,
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 10.0,
            "enemies": [{"champion": "Garen", "level": 18, "items": []}],
        },
        deterministic=True,
    )


def _control_rows(payload: dict, slot: str) -> list[dict]:
    """The published zero-damage control rows this slot's casts landed."""
    return [
        event
        for event in payload["combat"]["events"]
        if event.get("source") == slot and event.get("cc_duration") is not None
    ]


@pytest.mark.parametrize(
    ("champion", "slot", "kind", "duration", "magnitude"),
    MAGNITUDE_CARRIERS,
    ids=[case[0] for case in MAGNITUDE_CARRIERS],
)
def test_a_magnitude_carrier_publishes_its_duration_and_its_strength(
    champion: str, slot: str, kind: str, duration: float, magnitude: float
) -> None:
    rows = _control_rows(_fight(champion), slot)
    assert rows, f"{champion} {slot} published no control row"
    for row in rows:
        assert row["cc_kind"] == kind
        assert row["cc_duration"] == pytest.approx(duration)
        assert row["cc_magnitude"] == pytest.approx(magnitude)
        assert row["damage"] == 0.0


def test_a_control_kind_with_no_magnitude_publishes_no_leaf_rather_than_a_zero() -> (
    None
):
    """Rammus' taunt has a sourced duration and no strength to state."""
    rows = _control_rows(_fight("Rammus"), "E")
    assert rows, "Rammus E published no control row"
    for row in rows:
        assert row["cc_kind"] == "taunt"
        assert row["cc_duration"] == pytest.approx(2.0)
        assert "cc_magnitude" not in row


def test_the_published_magnitude_leaf_declares_its_own_precision() -> None:
    """The registry is what makes the leaf publishable at all."""
    assert precision.digits_for("events.cc_magnitude") == 3
