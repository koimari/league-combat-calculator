"""A control event names who it lands on, and the roster honours it.

Issue #209: ``ControlEvent`` carried kind, duration and timing but no
recipient, so a single-target cast broadcast its control to every enemy on
the board — Lulu's Whimsy polymorphed a whole roster off one cast.  The
scope is the answer, declared once beside the event, and an unscoped
control still reaches every enemy the cast hit.
"""

from __future__ import annotations

import pytest

from src.calculator.ability_spec import ControlEvent, ControlScope
from src.calculator.calculate import calculate_payload

TWO_ENEMIES = [
    {"champion": "Garen", "level": 18, "items": []},
    {"champion": "Malphite", "level": 18, "items": []},
]

TARGETED_CONTROL_CASES = [
    ("Nasus", {}, "slow"),
    ("Rammus", {}, "taunt"),
    ("Vayne", {}, "knockback"),
    ("Vayne", {}, "stun"),
    ("Elise", {}, "stun"),
    ("Zilean", {}, "slow"),
    ("Udyr", {}, "stun"),
    ("Nocturne", {}, "fear"),
    (
        "Evelynn",
        {"champion_options": {"w_charmed": True, "w_charm_triggered": True}},
        "charm",
    ),
]


def _control_rows(payload: dict, kind: str) -> list[dict]:
    """The main champion's published control rows of one kind."""
    return [
        event
        for event in payload["combat"]["events"]
        if event.get("attacker") == "main" and event.get("cc_kind") == kind
    ]


def test_an_unscoped_control_reaches_every_target() -> None:
    """The default is the reviewed answer every existing author authored."""
    assert ControlEvent("stun", 1.0).scope is ControlScope.EVERY_TARGET
    assert ControlScope.EVERY_TARGET.reaches(0)
    assert ControlScope.EVERY_TARGET.reaches(4)


def test_a_one_target_control_reaches_only_the_allocated_target() -> None:
    """One enemy holds a single-target cast, like a target-limited proc.

    The allocated index is exactly zero: the engine clamps the roster index
    with ``max(0, ...)`` before the fight state holds it, so a negative one
    is a caller bug rather than a second spelling of "the first enemy".
    """
    assert ControlScope.ONE_TARGET.reaches(0)
    assert not ControlScope.ONE_TARGET.reaches(1)
    assert not ControlScope.ONE_TARGET.reaches(-1)


def test_a_single_target_cast_polymorphs_one_enemy_not_the_roster() -> None:
    """Lulu W's enemy branch is cast on one target enemy champion."""
    payload = calculate_payload(
        {
            "champion": "Lulu",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 10.0,
            "champion_options": {"lulu_whimsy_target": "enemy"},
            "enemies": TWO_ENEMIES,
        },
        deterministic=True,
    )
    rows = _control_rows(payload, "polymorph")
    assert [row["target"] for row in rows] == ["enemy:Garen"]
    assert rows[0]["cc_duration"] == pytest.approx(2.0)


def test_an_area_cast_still_roots_every_enemy() -> None:
    """Xayah E's recalled feathers root everything they pass through."""
    payload = calculate_payload(
        {
            "champion": "Xayah",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 10.0,
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
            "enemies": TWO_ENEMIES,
        },
        deterministic=True,
    )
    rows = _control_rows(payload, "root")
    assert sorted({row["target"] for row in rows}) == [
        "enemy:Garen",
        "enemy:Malphite",
    ]
    assert len(rows) == 4


@pytest.mark.parametrize("champion, options, kind", TARGETED_CONTROL_CASES)
def test_targeted_control_casts_do_not_broadcast(
    champion: str, options: dict, kind: str
) -> None:
    """Targeted authored controls land on only the allocated enemy."""
    payload = calculate_payload(
        {
            "champion": champion,
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 10.0,
            "enemies": TWO_ENEMIES,
            **options,
        },
        deterministic=True,
    )
    rows = _control_rows(payload, kind)
    assert rows
    assert {row["target"] for row in rows} == {"enemy:Garen"}
