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
from src.calculator.data_fetcher import get_champion
from src.calculator.damage import _entry_control_scope

TWO_ENEMIES = [
    {"champion": "Garen", "level": 18, "items": []},
    {"champion": "Malphite", "level": 18, "items": []},
]


#: One row per targeted cast: the champion, the slot, the kind that slot
#: authors, the options that select the branch authoring it, and the cached
#: sentence that makes the cast one enemy's.
ONE_TARGET_CASTS = [
    ("Nasus", "W", "slow", {}, "ages the target enemy champion"),
    ("Rammus", "E", "taunt", {}, "taunts the target enemy champion or monster"),
    ("Vayne", "E", "stun", {"condemn_wall": True}, "at the target enemy"),
    ("Elise", "E", "stun", {}, "stunning the first enemy hit"),
    ("Zilean", "E", "slow", {}, "applies Time Warp to the target champion"),
    ("Udyr", "E", "stun", {}, "pounce on the target to stun them"),
    ("Nocturne", "E", "fear", {"e_tether_holds": True}, "torments the target"),
    (
        "Evelynn",
        "W",
        "charm",
        {"w_charmed": True, "w_charm_triggered": True},
        "curses the target enemy champion",
    ),
]


def _control_rows(payload: dict, kind: str) -> list[dict]:
    """The main champion's published control intervals of one kind.

    ``MODULE_CC`` stamps the slot's kind on every damage row of the cast
    too, so the authored interval is the row that also carries a duration.
    """
    return [
        event
        for event in payload["combat"]["events"]
        if event.get("attacker") == "main"
        and event.get("cc_kind") == kind
        and event.get("cc_duration") is not None
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


@pytest.mark.parametrize(
    ("champion", "slot", "kind", "options", "sentence"),
    ONE_TARGET_CASTS,
    ids=[f"{champion}-{slot}" for champion, slot, *_ in ONE_TARGET_CASTS],
)
def test_a_targeted_cast_holds_one_roster_enemy(
    champion: str, slot: str, kind: str, options: dict, sentence: str
) -> None:
    """Issue #232: each of these eight casts names one enemy in the cache.

    The sentence is asserted with the allocation, so a patch that widens the
    cast fails here instead of leaving a stale ``ONE_TARGET`` behind.
    """
    cached = " ".join(
        effect.get("description") or ""
        for ability in get_champion(champion)["abilities"][slot]
        for effect in ability.get("effects") or ()
    )
    assert sentence in cached
    payload = calculate_payload(
        {
            "champion": champion,
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 10.0,
            "champion_options": options,
            "enemies": TWO_ENEMIES,
        },
        deterministic=True,
    )
    rows = _control_rows(payload, kind)
    assert rows, f"{champion} {slot} published no {kind} interval"
    assert {row["target"] for row in rows} == {"enemy:Garen"}


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
    rows = [
        event
        for event in payload["combat"]["events"]
        if event.get("attacker") == "main" and event.get("cc_kind") == kind
    ]
    assert rows
    assert {row["target"] for row in rows} == {"enemy:Garen"}


@pytest.mark.parametrize("champion", ["Nocturne", "Vayne"])
def test_scoped_control_keeps_fimbulwinter_review_coverage(champion):
    payload = calculate_payload(
        {
            "champion": champion,
            "level": 18,
            "items": ["Fimbulwinter"],
            "fight_mode": "time_based",
            "fight_duration": 10.0,
            "enemies": TWO_ENEMIES,
        },
        deterministic=True,
    )
    assert payload["timeline_coverage"]["complete"], payload["timeline_coverage"]


@pytest.mark.parametrize("champion", ["Nocturne", "Vayne"])
def test_cheap_shot_only_procs_on_the_control_recipient(champion):
    payload = calculate_payload(
        {
            "champion": champion,
            "level": 18,
            "items": [],
            "minor_runes": ["Cheap Shot"],
            "fight_mode": "time_based",
            "fight_duration": 10.0,
            "enemies": TWO_ENEMIES,
        },
        deterministic=True,
    )
    procs = [
        event
        for event in payload["combat"]["events"]
        if event.get("attacker") == "main" and event.get("source") == "rune_Cheap Shot"
    ]
    assert procs
    assert {event["target"] for event in procs} == {"enemy:Garen"}
    assert all(event["damage"] > 0 for event in procs)


@pytest.mark.parametrize("condemn_wall", [False, True])
def test_vayne_condemn_scope_applies_with_and_without_a_wall(condemn_wall):
    payload = calculate_payload(
        {
            "champion": "Vayne",
            "level": 18,
            "items": ["Fimbulwinter"],
            "champion_options": {"condemn_wall": condemn_wall},
            "minor_runes": ["Cheap Shot"],
            "fight_mode": "time_based",
            "fight_duration": 10.0,
            "enemies": TWO_ENEMIES,
        },
        deterministic=True,
    )
    events = [
        event
        for event in payload["combat"]["events"]
        if event.get("attacker") == "main"
    ]
    procs = [event for event in events if event.get("source") == "rune_Cheap Shot"]
    assert procs
    assert {event["target"] for event in procs} == {"enemy:Garen"}
    knockbacks = [event for event in events if event.get("cc_kind") == "knockback"]
    assert knockbacks
    assert {event["target"] for event in knockbacks} == {"enemy:Garen"}
    stuns = [event for event in events if event.get("cc_kind") == "stun"]
    assert bool(stuns) is condemn_wall
    assert payload["timeline_coverage"]["complete"]


@pytest.mark.parametrize("invalid", ["one_target", 0, False, {}])
def test_authored_control_scope_rejects_untyped_values(invalid):
    with pytest.raises(TypeError, match="control_scope must be a ControlScope"):
        _entry_control_scope({"control_scope": invalid})


def test_absent_cast_scope_uses_event_scope_or_remains_unspecified():
    assert _entry_control_scope({}) is None
    assert (
        _entry_control_scope(
            {
                "control_events": (
                    ControlEvent("stun", 1.0, scope=ControlScope.ONE_TARGET),
                )
            }
        )
        is ControlScope.ONE_TARGET
    )
