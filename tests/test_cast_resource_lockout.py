"""The self-silencing bar a kit's own casts fill, walked over the cast plan.

Rumble is the one kit that declares it, but nothing in the walk knows a
champion: the rule arrives on an ability entry with every number sourced,
and the plan decides the rest. See
``src/calculator/fight/rotation/cast_resource_lockout.py``.
"""

import pytest

from src.calculator.calculate import calculate_payload
from src.calculator.fight.rotation.cast_resource_lockout import (
    LockoutRule,
    LockoutWalk,
    declared_rule,
    lockout_empowered_swings,
    lockout_seconds_within,
)

_RULE = LockoutRule(
    slots=frozenset({"Q", "W", "E"}),
    per_cast=20.0,
    ceiling=150.0,
    seconds=4.0,
    decay_per_second=10.0,
    decay_delay_seconds=4.0,
    ultimate_slot="R",
    ultimate_delay_seconds=2.0,
    name="a bar under test",
)


class TestTheWalkIsTheGames:
    def test_the_bar_fills_and_the_ceiling_silences_the_kit(self) -> None:
        walk = LockoutWalk(_RULE)
        for index in range(7):
            assert walk.cast("Q", float(index) * 0.1, float(index) * 0.1) == 0.0
        # The eighth generating cast is the one that reaches 150.
        assert walk.cast("Q", 0.7, 0.7) == pytest.approx(4.7)
        assert walk.windows == [(0.7, 4.7)]
        assert walk.level == 0.0

    def test_the_ultimate_fills_nothing_and_only_delays_the_decay(self) -> None:
        walk = LockoutWalk(_RULE)
        walk.cast("Q", 0.0, 0.0)
        walk.cast("R", 0.1, 0.1)
        assert walk.level == pytest.approx(20.0)
        assert walk.windows == []

    def test_the_bar_decays_once_both_delays_have_passed(self) -> None:
        """Ten per second from the later of the two cached deadlines."""
        walk = LockoutWalk(_RULE)
        walk.cast("Q", 0.0, 0.0)
        walk.cast("Q", 0.5, 0.5)
        # Decay starts at 4.5 (the basic deadline), so 6.0 has lost 15.
        walk.cast("Q", 6.0, 6.0)
        assert walk.level == pytest.approx(45.0)

    def test_partial_progress_is_kept_rather_than_reset(self) -> None:
        walk = LockoutWalk(_RULE)
        walk.cast("Q", 0.0, 0.0)
        # Decay opens at 4.0 and runs 0.6s at 10/s, so 20 becomes 14 before
        # the second cast adds its 20.
        walk.cast("Q", 4.6, 4.6)
        assert walk.level == pytest.approx(34.0)

    def test_a_kit_declaring_nothing_has_no_bar(self) -> None:
        assert declared_rule({"Q": {"name": "Q"}}) is None

    def test_two_declarations_are_refused(self) -> None:
        payload = {
            "slots": ("Q",),
            "per_cast": 1.0,
            "ceiling": 2.0,
            "seconds": 1.0,
            "decay_per_second": 0.0,
            "decay_delay_seconds": 0.0,
            "ultimate_slot": "R",
            "ultimate_delay_seconds": 0.0,
        }
        with pytest.raises(ValueError, match="one set of hands has one bar"):
            declared_rule(
                {
                    "P": {"name": "one", "cast_resource_lockout": payload},
                    "Q": {"name": "two", "cast_resource_lockout": dict(payload)},
                }
            )

    def test_a_rule_missing_a_number_is_refused(self) -> None:
        with pytest.raises(ValueError, match="declares no 'ceiling'"):
            declared_rule(
                {
                    "P": {
                        "name": "half a rule",
                        "cast_resource_lockout": {
                            "slots": ("Q",),
                            "per_cast": 1.0,
                            "seconds": 1.0,
                            "decay_per_second": 0.0,
                            "decay_delay_seconds": 0.0,
                            "ultimate_slot": "R",
                            "ultimate_delay_seconds": 0.0,
                        },
                    }
                }
            )


class TestWhatTheWindowsCover:
    def test_only_the_seconds_inside_the_fight_count(self) -> None:
        assert lockout_seconds_within(((8.0, 12.0),), 10.0) == pytest.approx(2.0)
        assert lockout_seconds_within(((2.0, 6.0),), 10.0) == pytest.approx(4.0)
        assert lockout_seconds_within(((12.0, 16.0),), 10.0) == pytest.approx(0.0)

    def test_a_swing_is_empowered_when_a_window_holds_it(self) -> None:
        class _State:
            lockout_windows = ((2.0, 4.0),)

        swings = (1.0, 2.0, 3.5, 4.0, 5.0)
        # End-exclusive, the convention every window in this engine uses.
        assert lockout_empowered_swings(_State(), swings) == 2


class TestTheOneKitThatDeclaresIt:
    """Rumble, end to end through the real pipeline."""

    @staticmethod
    def _fight(duration: float, items: list[str]) -> dict:
        return calculate_payload(
            {
                "champion": "Rumble",
                "level": 18,
                "items": items,
                "fight_mode": "timed",
                "fight_duration": duration,
                "include_auto_attacks": True,
                "auto_attack_uptime": 1.0,
            }
        )

    def test_a_faster_plan_fills_the_bar_more_often(self) -> None:
        """Ability haste buys Overheats, which is the mechanic working."""
        slow = self._fight(30.0, [])
        fast = self._fight(30.0, ["Malignance", "Cosmic Drive", "Horizon Focus"])
        assert slow["breakdown"]["on_hit_ability_passive"]["count"] == 4
        assert fast["breakdown"]["on_hit_ability_passive"]["count"] == 8

    def test_the_lockout_costs_the_casts_it_eats(self) -> None:
        """The silence sits where it happens, so it removes real casts."""
        fast = self._fight(30.0, ["Malignance", "Cosmic Drive", "Horizon Focus"])
        times = sorted(event["time"] for event in fast["cast_timeline"])
        for start in (7.772727, 22.681818):
            assert not [
                time for time in times if start + 1e-3 < time < start + 4.0
            ], f"a cast landed inside the {start:.2f}s lockout"
