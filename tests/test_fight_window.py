"""``count_damage_after_fight_end`` decides what a fight's end does to damage.

On (the default), the fight is the window in which the champions act: a hit a
cast lights inside it still lands after it (a fused Time Bomb, Requiem's
payload, a DoT's remaining ticks, a burn's tail), the reading a user measured
in game for a 3 s Cassiopeia and Blackfire Torch fight. Off, every landing is
clipped at the fight's end, so a 1 s fight shows nothing of a bomb that goes
off at 3 s (muri's report, issue #323). One-rotation fights never clip: that
mode is "cast everything once and let it land".
"""

from __future__ import annotations

import pytest

from src.calculator.calculate import calculate_payload

_ZILEAN_FUSE = 3.0
_KLED_PULL = 1.75
_NOTE = "Damage timed past the fight's end is not counted"


def _fight(
    champion: str,
    duration: float,
    *,
    count: bool,
    mode: str = "time_based",
    level: int = 6,
    items: tuple[str, ...] = (),
    ranks: dict[str, int] | None = None,
) -> dict:
    return calculate_payload(
        {
            "champion": champion,
            "level": level,
            "items": list(items),
            "ability_ranks": ranks or {"Q": 1, "W": 1, "E": 1, "R": 1},
            "fight_mode": mode,
            "fight_duration": duration,
            "include_auto_attacks": False,
            "count_damage_after_fight_end": count,
            "target_health": 1000,
            "target_armor": 100,
            "target_mr": 100,
        },
        deterministic=True,
    )


def _events(payload: dict, source: str) -> list[dict]:
    return [event for event in payload["damage_events"] if event["source"] == source]


class TestTheDefaultCountsWhatTheWindowLit:
    def test_a_fused_bomb_counts_and_the_result_says_nothing_special(self) -> None:
        payload = _fight("Zilean", 1.0, count=True)
        assert [event["time"] for event in _events(payload, "Q")] == [_ZILEAN_FUSE]
        assert payload["breakdown"]["Q"]["total_damage"] > 0
        assert not any(_NOTE in note for note in payload["notes"])

    def test_the_request_defaults_to_counting(self) -> None:
        payload = calculate_payload(
            {
                "champion": "Zilean",
                "level": 6,
                "items": [],
                "ability_ranks": {"Q": 1, "W": 1, "E": 1, "R": 1},
                "fight_mode": "time_based",
                "fight_duration": 1.0,
                "include_auto_attacks": False,
                "target_health": 1000,
            },
            deterministic=True,
        )
        assert payload["breakdown"]["Q"]["total_damage"] > 0


class TestClippingToTheWindow:
    @pytest.mark.parametrize("duration", [1.0, 2.5, _ZILEAN_FUSE - 0.1])
    def test_a_bomb_still_fused_at_the_fight_end_deals_nothing(
        self, duration: float
    ) -> None:
        payload = _fight("Zilean", duration, count=False)
        assert _events(payload, "Q") == []
        assert payload["breakdown"].get("Q", {}).get("total_damage", 0.0) == 0.0
        assert any(_NOTE in note for note in payload["notes"])

    def test_the_bomb_lands_once_the_fight_reaches_its_fuse(self) -> None:
        short = _fight("Zilean", _ZILEAN_FUSE, count=False)
        long = _fight("Zilean", 8.0, count=False)
        assert [event["time"] for event in _events(short, "Q")] == [_ZILEAN_FUSE]
        assert short["breakdown"]["Q"]["total_damage"] == pytest.approx(
            long["breakdown"]["Q"]["total_damage"]
        )

    def test_a_one_rotation_fight_never_clips(self) -> None:
        payload = _fight("Zilean", 1.0, count=False, mode="one_rotation")
        assert [event["time"] for event in _events(payload, "Q")] == [_ZILEAN_FUSE]
        assert payload["breakdown"]["Q"]["total_damage"] > 0

    def test_a_two_hit_part_keeps_only_the_hits_inside_the_window(self) -> None:
        """Bear Trap: the throw lands at the cast, the pull 1.75 s later."""
        before_pull = _fight("Kled", _KLED_PULL - 0.25, count=False)
        after_pull = _fight("Kled", _KLED_PULL + 0.25, count=False)
        assert [event["time"] for event in _events(before_pull, "Q")] == [0.0]
        assert [event["time"] for event in _events(after_pull, "Q")] == [
            0.0,
            _KLED_PULL,
        ]

    @pytest.mark.parametrize(
        ("champion", "slot"),
        [("Karthus", "R"), ("Vladimir", "R")],
        ids=["requiem-channel", "hemoplague-infection"],
    )
    def test_a_channel_or_infection_still_running_deals_nothing(
        self, champion: str, slot: str
    ) -> None:
        short = _fight(champion, 2.0, count=False)
        long = _fight(champion, 8.0, count=False)
        assert _events(short, slot) == []
        assert short["breakdown"].get(slot, {}).get("total_damage", 0.0) == 0.0
        assert long["breakdown"][slot]["total_damage"] > 0

    def test_a_dot_tick_train_stops_at_the_fight_end(self) -> None:
        """Malefic Visions ticks past a 2 s window by default, not when clipped."""
        kwargs = {"level": 18, "ranks": {"Q": 5, "W": 5, "E": 5, "R": 3}}
        counted = _fight("Malzahar", 2.0, count=True, **kwargs)
        clipped = _fight("Malzahar", 2.0, count=False, **kwargs)
        late = [event for event in _events(counted, "E") if event["time"] > 2.0]
        assert late, "the default keeps ticks past the end"
        assert all(event["time"] <= 2.0 + 1e-9 for event in _events(clipped, "E"))
        assert (
            clipped["breakdown"]["E"]["total_damage"]
            < counted["breakdown"]["E"]["total_damage"]
        )

    def test_a_stacking_dot_stops_at_the_fight_end(self) -> None:
        kwargs = {"level": 18, "ranks": {"Q": 5, "W": 5, "E": 5, "R": 3}}
        counted = _fight("Briar", 3.0, count=True, **kwargs)
        clipped = _fight("Briar", 3.0, count=False, **kwargs)
        assert clipped["total_damage"] < counted["total_damage"]
        assert all(event["time"] <= 3.0 + 1e-9 for event in clipped["damage_events"])

    def test_an_item_burn_stops_at_the_fight_end(self) -> None:
        kwargs = {
            "level": 18,
            "ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
            "items": ("Blackfire Torch",),
        }
        counted = _fight("Cassiopeia", 3.0, count=True, **kwargs)
        clipped = _fight("Cassiopeia", 3.0, count=False, **kwargs)
        burn = next(key for key in counted["breakdown"] if "Blackfire" in key)
        assert (
            clipped["breakdown"][burn]["total_damage"]
            < counted["breakdown"][burn]["total_damage"]
        )
        assert all(
            event["time"] <= 3.0 + 1e-9
            for event in clipped["damage_events"]
            if event["source"] == burn
        )
