"""An empowered basic attack the fight arms, counted from the two schedules.

The rule is the module's and every number of it is cached; the count is the
fight's. See ``src/calculator/champions/armed_procs.py``.
"""

import pytest

from src.calculator.calculate import calculate_payload
from src.calculator.champions.armed_procs import (
    ArmedProcRule,
    armed_swing_count,
    armed_swing_times,
    cached_stack_terms,
    counted_hit_times,
    declared_rule,
)
from src.calculator.data_fetcher import get_champion

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


#: Akshan's and Ekko's shape: both streams stack, the third application procs.
_BOTH_STREAMS = ArmedProcRule(
    arming_slots=frozenset(),
    max_stacks=3,
    hits_required=3,
    stacks_from_swings=True,
    stacks_from_ability_hits=True,
    stack_seconds=4.0,
)
#: Talon's shape: abilities stack, a basic attack spends three.
_ABILITY_STACKS = ArmedProcRule(
    arming_slots=frozenset(),
    max_stacks=3,
    hits_required=3,
    stacks_from_ability_hits=True,
    consumed_by_swing=True,
    stack_seconds=6.0,
)


class TestTheHitCounterShape:
    def test_every_third_hit_across_both_streams_procs(self) -> None:
        swings = (0.0, 1.0, 2.0, 3.0, 4.0, 5.0)
        assert counted_hit_times(_BOTH_STREAMS, swings, (0.5,)) == (1.0, 4.0)

    def test_a_cycle_that_never_completes_procs_nothing(self) -> None:
        assert counted_hit_times(_BOTH_STREAMS, (0.0, 1.0), ()) == ()

    def test_a_stack_expires_on_its_own_clock(self) -> None:
        """Two hits, then a gap longer than the stack's life, then a third:
        the counter is back at one, not at three."""
        assert counted_hit_times(_BOTH_STREAMS, (0.0, 1.0, 9.0), ()) == ()

    def test_abilities_stack_and_a_swing_spends_them(self) -> None:
        assert counted_hit_times(_ABILITY_STACKS, (0.4,), (0.0, 0.1, 0.2)) == (0.4,)

    def test_a_swing_with_too_few_stacks_spends_nothing(self) -> None:
        assert counted_hit_times(_ABILITY_STACKS, (0.4,), (0.0, 0.1)) == ()

    def test_a_swing_refreshes_what_is_banked_without_adding_to_it(self) -> None:
        """Talon's basic attacks refresh Wound; if they also stacked it, two
        abilities and two swings would proc, and they must not."""
        assert counted_hit_times(_ABILITY_STACKS, (0.3, 0.4), (0.0, 0.1)) == ()

    def test_a_counter_that_names_no_stream_is_refused(self) -> None:
        with pytest.raises(ValueError, match="names no stream"):
            ArmedProcRule(arming_slots=frozenset(), max_stacks=3, hits_required=3)

    def test_a_counter_that_can_never_reach_its_threshold_is_refused(self) -> None:
        with pytest.raises(ValueError, match="never procs"):
            ArmedProcRule(
                arming_slots=frozenset(),
                max_stacks=2,
                hits_required=3,
                stacks_from_swings=True,
            )


# Volibear's shape: a stack per attack or ability, five held for six
# seconds each, and the empowerment STANDS at five rather than being spent.
_THRESHOLD = ArmedProcRule(
    arming_slots=frozenset(),
    max_stacks=5,
    hits_required=5,
    stacks_from_swings=True,
    stacks_from_ability_hits=True,
    stack_seconds=6.0,
    retained_at_threshold=True,
    armed_at_start=False,
)


class TestTheRetainedThresholdShape:
    """A count the swing READS rather than spends (Volibear's Claws)."""

    SWINGS = (0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0)

    def test_every_swing_after_the_threshold_lands_empowered(self) -> None:
        """The fifth attack banks the fifth stack; the sixth is the first
        empowered one, and none after it costs a stack."""
        assert armed_swing_times(_THRESHOLD, (), self.SWINGS) == (5.0, 6.0, 7.0, 8.0)

    def test_ability_hits_bring_the_threshold_forward(self) -> None:
        assert armed_swing_times(_THRESHOLD, (), self.SWINGS, (0.5, 1.5)) == (
            3.0,
            4.0,
            5.0,
            6.0,
            7.0,
            8.0,
        )

    def test_a_stream_too_slow_to_fill_it_empowers_nothing(self) -> None:
        assert armed_swing_times(_THRESHOLD, (), (0.0, 7.0, 14.0)) == ()

    def test_the_state_lapses_when_the_stacks_run_out(self) -> None:
        """Five fast attacks, then a long gap: the last swing is past the
        six seconds the fifth stack lived, so it is not empowered."""
        assert armed_swing_times(_THRESHOLD, (), (0.0, 0.1, 0.2, 0.3, 0.4, 9.0)) == ()

    def test_a_retained_rule_with_no_threshold_is_refused(self) -> None:
        with pytest.raises(ValueError, match="no threshold to stand at"):
            ArmedProcRule(
                arming_slots=frozenset(),
                max_stacks=5,
                per_cast=1,
                retained_at_threshold=True,
            )


class TestTheStackTermsComeFromTheCache:
    """One cached sentence shape, read for every kit that writes it."""

    @pytest.mark.parametrize(
        ("champion", "expected"),
        [("Akshan", (5.0, 3)), ("Ekko", (4.0, 3)), ("Talon", (6.0, 3))],
    )
    def test_the_cached_sentence_states_the_life_and_the_cap(
        self, champion: str, expected: tuple[float, int]
    ) -> None:
        ability = get_champion(champion)["abilities"]["P"][0]
        assert cached_stack_terms(ability, owner=f"{champion} P") == expected

    def test_a_cache_that_stops_saying_it_raises(self) -> None:
        with pytest.raises(ValueError, match="stack life and cap"):
            cached_stack_terms(
                {"effects": [{"description": "Innate: nothing."}]},
                owner="a kit under test",
            )


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


class TestTheKitsThatDeclareIt:
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
        """The empowered-swing count, whichever row this kit publishes it on."""
        row = payload["breakdown"].get("on_hit_ability_passive") or payload[
            "breakdown"
        ].get("passive")
        return 0 if row is None else int(row["count"])

    def test_galio_smashes_more_often_in_a_longer_fight(self) -> None:
        assert self._procs(self._fight("Galio", 5.0)) == 2
        assert self._procs(self._fight("Galio", 20.0)) == 7

    def test_sylas_spends_the_stacks_his_casts_banked(self) -> None:
        assert self._procs(self._fight("Sylas", 5.0)) == 4
        assert self._procs(self._fight("Sylas", 20.0)) == 8

    def test_ziggs_short_fuse_is_no_longer_capped_at_its_packet_count(self) -> None:
        """The engine held a champion-named walk of its own, capped by the
        declared two; the shared walk runs to the fight's end instead."""
        assert self._procs(self._fight("Ziggs", 5.0)) == 2
        assert self._procs(self._fight("Ziggs", 30.0)) == 6

    def test_gangplank_arms_on_the_timer_alone(self) -> None:
        """His keg reset is not modelled, so the derived count is a floor."""
        assert self._procs(self._fight("Gangplank", 5.0)) == 1
        assert self._procs(self._fight("Gangplank", 20.0)) == 2

    @pytest.mark.parametrize(
        ("champion", "short", "long"),
        [
            ("Ambessa", 4, 8),
            ("Akshan", 1, 6),
            ("Ekko", 3, 10),
            ("Talon", 1, 2),
        ],
    )
    def test_each_counting_kit_scales_with_the_fight(
        self, champion: str, short: int, long: int
    ) -> None:
        assert self._procs(self._fight(champion, 5.0)) == short
        assert self._procs(self._fight(champion, 20.0)) == long

    def test_a_request_that_names_the_count_keeps_it(self) -> None:
        """The override: the reader saw the swing miss, and says so."""
        named = self._fight("Galio", 20.0, {"passive_procs": 1})
        assert self._procs(named) == 1
