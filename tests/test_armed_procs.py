"""An empowered basic attack the fight arms, counted from the two schedules.

The rule is the module's and every number of it is cached; the count is the
fight's. See ``src/calculator/champions/armed_procs.py``.
"""

import pytest

from src.calculator.calculate import calculate_payload
from src.calculator.champions.armed_procs import (
    ArmedProcRule,
    armed_swing_count,
    declared_rule,
)

# Galio's shape: a timer, brought forward by every arming cast.
_TIMER = ArmedProcRule(
    arming_slots=frozenset({"Q", "W", "E", "R"}),
    max_stacks=1,
    cooldown=5.0,
    cooldown_reduction_per_cast=3.0,
)
# Sylas' shape: a stack per cast, three held, four seconds each.
_STACKS = ArmedProcRule(
    arming_slots=frozenset({"Q", "W", "E", "R"}),
    max_stacks=3,
    per_cast=1,
    stack_seconds=4.0,
    armed_at_start=False,
)


class TestTheTimerShape:
    def test_the_first_swing_is_armed_when_the_kit_starts_armed(self) -> None:
        assert armed_swing_count(_TIMER, (), (0.0, 1.0, 2.0)) == 1

    def test_the_timer_alone_arms_one_swing_per_cooldown(self) -> None:
        swings = tuple(float(second) for second in range(12))
        assert armed_swing_count(_TIMER, (), swings) == 3  # 0.0, 5.0, 10.0

    def test_an_arming_cast_brings_the_timer_forward(self) -> None:
        """Two casts take six seconds off a five-second timer, so the next
        swing after them is armed instead of the one five seconds later."""
        casts = (("Q", 0.5), ("W", 1.0))
        assert armed_swing_count(_TIMER, casts, (0.0, 2.0)) == 2

    def test_a_cast_cannot_bring_the_timer_behind_itself(self) -> None:
        """Otherwise a burst of casts would bank time the fight never spent."""
        casts = tuple(("Q", 0.1 * index) for index in range(10))
        assert armed_swing_count(_TIMER, casts, (0.0, 1.0)) == 2

    def test_a_slot_outside_the_arming_set_does_nothing(self) -> None:
        casts = (("P", 0.5), ("P", 1.0))
        assert armed_swing_count(_TIMER, casts, (0.0, 2.0)) == 1


class TestTheStackShape:
    def test_nothing_is_armed_before_the_first_cast(self) -> None:
        assert armed_swing_count(_STACKS, (), (0.0, 1.0, 2.0)) == 0

    def test_each_cast_banks_one_and_each_swing_spends_one(self) -> None:
        casts = (("Q", 0.0), ("W", 0.1))
        assert armed_swing_count(_STACKS, casts, (0.2, 0.3, 0.4)) == 2

    def test_the_bank_holds_no_more_than_the_cap(self) -> None:
        casts = tuple(("Q", 0.1 * index) for index in range(6))
        assert armed_swing_count(_STACKS, casts, (1.0, 1.1, 1.2, 1.3)) == 3

    def test_a_stack_expires_on_its_own_clock(self) -> None:
        casts = (("Q", 0.0),)
        assert armed_swing_count(_STACKS, casts, (3.9,)) == 1
        assert armed_swing_count(_STACKS, casts, (4.1,)) == 0


class TestTheDeclaration:
    def test_a_kit_declaring_nothing_has_no_rule(self) -> None:
        assert declared_rule({"P": {"name": "P"}}) is None

    def test_a_rule_that_arms_nothing_is_refused(self) -> None:
        with pytest.raises(ValueError, match="arms nothing"):
            ArmedProcRule(arming_slots=frozenset({"Q"}), max_stacks=1)

    def test_two_declarations_are_refused(self) -> None:
        payload = {
            "arming_slots": ("Q",),
            "max_stacks": 1,
            "cooldown": 5.0,
            "armed_at_start": True,
            "requested": False,
        }
        with pytest.raises(ValueError, match="one empowering innate"):
            declared_rule(
                {
                    "P": {"name": "one", "armed_procs": payload},
                    "Q": {"name": "two", "armed_procs": dict(payload)},
                }
            )

    def test_a_rule_missing_a_number_is_refused(self) -> None:
        with pytest.raises(ValueError, match="declares no 'max_stacks'"):
            declared_rule(
                {
                    "P": {
                        "name": "half a rule",
                        "armed_procs": {
                            "arming_slots": ("Q",),
                            "cooldown": 5.0,
                            "armed_at_start": True,
                            "requested": False,
                        },
                    }
                }
            )


class TestTheTwoKitsThatDeclareIt:
    @staticmethod
    def _fight(champion: str, duration: float, options: dict | None = None) -> dict:
        return calculate_payload(
            {
                "champion": champion,
                "level": 18,
                "items": [],
                "fight_mode": "timed",
                "fight_duration": duration,
                "include_auto_attacks": True,
                "auto_attack_uptime": 1.0,
                "champion_options": options or {},
            }
        )

    @staticmethod
    def _procs(payload: dict) -> int:
        row = payload["breakdown"].get("on_hit_ability_passive")
        return 0 if row is None else int(row["count"])

    def test_galio_smashes_more_often_in_a_longer_fight(self) -> None:
        assert self._procs(self._fight("Galio", 5.0)) == 2
        assert self._procs(self._fight("Galio", 20.0)) == 7

    def test_sylas_spends_the_stacks_his_casts_banked(self) -> None:
        assert self._procs(self._fight("Sylas", 5.0)) == 4
        assert self._procs(self._fight("Sylas", 20.0)) == 8

    def test_a_request_that_names_the_count_keeps_it(self) -> None:
        """The override: the reader saw the swing miss, and says so."""
        named = self._fight("Galio", 20.0, {"passive_procs": 1})
        assert self._procs(named) == 1
