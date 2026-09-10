"""A hit the source times past the fight's end never lands (issue #323).

Time Bomb's damage is its detonation three seconds after the throw, Requiem's
is the end of a three-second channel, Hemoplague's the end of a four-second
infection, Bear Trap's pull 1.75 seconds after the throw. Each module declares
that instant as its part's ``time_offset``; the rotation used to price the
hit whatever the fight length, so a one-second fight showed the bomb's whole
damage before the bomb went off. A timed fight now keeps only the hits that
land inside its window; a one-rotation fight is "cast everything once and let
it land" and keeps every hit. A DoT's tick train (a part with a hit interval)
is not clipped: an applied DoT commits its ticks past the cutoff by the tick
ledger's own rule, and that rule is pinned by the DoT champions' tests.
"""

from __future__ import annotations

import pytest

from src.calculator.calculate import calculate_payload

_ZILEAN_FUSE = 3.0
_KLED_PULL = 1.75


def _fight(champion: str, duration: float, *, mode: str = "time_based") -> dict:
    return calculate_payload(
        {
            "champion": champion,
            "level": 6,
            "items": [],
            "ability_ranks": {"Q": 1, "W": 1, "E": 1, "R": 1},
            "fight_mode": mode,
            "fight_duration": duration,
            "include_auto_attacks": False,
            "target_health": 1000,
            "target_armor": 100,
            "target_mr": 100,
        },
        deterministic=True,
    )


def _events(payload: dict, source: str) -> list[dict]:
    return [event for event in payload["damage_events"] if event["source"] == source]


class TestDelayedHitsRespectTheFightWindow:
    @pytest.mark.parametrize("duration", [1.0, 2.5, _ZILEAN_FUSE - 0.1])
    def test_a_bomb_still_fused_at_the_fight_end_deals_nothing(
        self, duration: float
    ) -> None:
        payload = _fight("Zilean", duration)
        assert _events(payload, "Q") == []
        # A row that priced nothing is not published at all.
        assert payload["breakdown"].get("Q", {}).get("total_damage", 0.0) == 0.0

    def test_the_bomb_lands_once_the_fight_reaches_its_fuse(self) -> None:
        short = _fight("Zilean", _ZILEAN_FUSE)
        long = _fight("Zilean", 8.0)
        assert [event["time"] for event in _events(short, "Q")] == [_ZILEAN_FUSE]
        assert short["breakdown"]["Q"]["total_damage"] == pytest.approx(
            long["breakdown"]["Q"]["total_damage"]
        )

    def test_a_one_rotation_fight_lets_every_hit_land(self) -> None:
        payload = _fight("Zilean", 1.0, mode="one_rotation")
        assert [event["time"] for event in _events(payload, "Q")] == [_ZILEAN_FUSE]
        assert payload["breakdown"]["Q"]["total_damage"] > 0

    def test_a_two_hit_part_keeps_only_the_hits_inside_the_window(self) -> None:
        """Bear Trap: the throw lands at the cast, the pull 1.75 s later."""
        before_pull = _fight("Kled", _KLED_PULL - 0.25)
        after_pull = _fight("Kled", _KLED_PULL + 0.25)
        assert [event["time"] for event in _events(before_pull, "Q")] == [0.0]
        assert [event["time"] for event in _events(after_pull, "Q")] == [
            0.0,
            _KLED_PULL,
        ]
        assert (
            after_pull["breakdown"]["Q"]["total_damage"]
            > before_pull["breakdown"]["Q"]["total_damage"]
            > 0
        )

    @pytest.mark.parametrize(
        ("champion", "slot"),
        [("Karthus", "R"), ("Vladimir", "R")],
        ids=["requiem-channel", "hemoplague-infection"],
    )
    def test_a_channel_or_infection_still_running_deals_nothing(
        self, champion: str, slot: str
    ) -> None:
        short = _fight(champion, 2.0)
        long = _fight(champion, 8.0)
        assert _events(short, slot) == []
        assert short["breakdown"].get(slot, {}).get("total_damage", 0.0) == 0.0
        assert long["breakdown"][slot]["total_damage"] > 0
        assert [event["time"] for event in _events(long, slot)] and all(
            event["time"] <= 8.0 for event in _events(long, slot)
        ), "the landed ultimate is inside the window"
