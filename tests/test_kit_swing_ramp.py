"""A ramp the CHAMPION declares over its own swing stream.

Jax's Relentless Assault and Jinx's Rev'd up are the record an item ramp
already is: a bonus per stack, a cap, and how long a stack lives, with one
stack landing per completed attack. The module publishes ``swing_ramp``,
``stat_buff_ultimates._kit_swing_ramp`` resolves it, and
``rearmed_swings.swing_times`` walks it beside a build's item ramp rather
than in place of it.

The end-to-end readings here are taken with Rageblade held, so the declared
and the derived reading are walked by the SAME exact walker: a declared
stack level with no item ramp is priced through the per-phase floor
instead, and comparing across the two paths measures the floor rather than
the ramp.
"""

from dataclasses import replace

import pytest

from src.calculator.champions import parse_champion_abilities
from src.calculator.data_fetcher import get_champion
from src.calculator.fight.setup import stat_buff_ultimates
from src.calculator.interpreters import rearmed_swings as rs
from src.calculator.pipeline import run_fight
from src.calculator.scenario import parse_scenario_request, resolve_scenario
from src.calculator.stats import calculate_total_stats

RAGEBLADE = "Guinsoo's Rageblade"
_FULL_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}


def _parse(champion: str, options: dict | None = None) -> dict:
    """The champion's compiled slot table at level 18 under *options*."""
    data = get_champion(champion)
    stats = calculate_total_stats(data, 18, [])
    return parse_champion_abilities(
        data,
        18,
        0.0,
        ability_ranks=dict(_FULL_RANKS),
        champion_stats=stats,
        target_stats={"armor": 100.0, "magic_resistance": 100.0, "max_health": 2000.0},
        champion_options=options or {},
    )


def _fight(champion: str, options: dict, duration: float, items: list[str]) -> dict:
    """One timed fight at full auto uptime, deterministic."""
    request = parse_scenario_request(
        {
            "champion": champion,
            "level": 13,
            "role": "bottom",
            "items": items,
            "champion_options": options,
        },
        deterministic=True,
    )
    resolved = resolve_scenario(request)
    params = replace(
        resolved.fight_params,
        fight_duration_seconds=duration,
        one_rotation=False,
        auto_attack_uptime=1.0,
    )
    return run_fight(
        resolved.champion_data, request.level, list(resolved.items), params
    )


def _autos(result: dict) -> int:
    return result["auto_attack_schedule"]["expected_autos_total"]


class TestTheRampRecord:
    """``DecayingStackRamp`` prices a stack level, and only what it holds."""

    def test_every_stack_is_worth_the_same_when_no_first_stack_is_declared(self):
        ramp = rs.DecayingStackRamp(per_stack=0.05, max_stacks=4, stack_duration=3.0)
        assert [ramp.bonus_percent(n) for n in range(6)] == [
            pytest.approx(value) for value in (0.0, 5.0, 10.0, 15.0, 20.0, 20.0)
        ]

    def test_a_declared_first_stack_prices_only_the_first_one(self):
        """Jinx: 15% on the first stack and 7.5% on each of the two after it."""
        ramp = rs.DecayingStackRamp(
            per_stack=0.075, max_stacks=3, stack_duration=2.5, first_stack=0.15
        )
        assert [ramp.bonus_percent(n) for n in range(5)] == [
            pytest.approx(value) for value in (0.0, 15.0, 22.5, 30.0, 30.0)
        ]
        # The cap is the cached "Maximum Attack Speed" row, reached at the
        # cached stack count and never passed.
        assert ramp.bonus_percent(99) == pytest.approx(30.0)


class TestTheWalkerMergesTwoRamps:
    """An item ramp and a kit ramp re-rate one stream; neither replaces one."""

    SCHEDULE = rs.SwingSchedule(ramp=None, window=None, schedules_single_rotation=False)
    RATE = {"attack_speed": 0.625, "attack_speed_ratio": 0.668}

    def _times(self, **kwargs) -> tuple[float, ...]:
        return rs.swing_times(
            self.SCHEDULE, duration_seconds=8.0, **self.RATE, **kwargs
        )

    def test_a_kit_ramp_shortens_the_gap_between_successive_swings(self):
        kit = rs.DecayingStackRamp(
            per_stack=0.075, max_stacks=3, stack_duration=2.5, first_stack=0.15
        )
        times = self._times(kit_ramp=kit)
        gaps = [after - before for before, after in zip(times, times[1:])]
        assert gaps == sorted(gaps, reverse=True)
        assert gaps[-1] < gaps[0]
        assert len(times) > len(self._times())

    def test_a_build_ramp_and_a_kit_ramp_add_rather_than_overwrite(self):
        """The trap the Jax slice was written around: one ramp winning.

        Each keeps its own stack clock, because their durations differ, and
        one attack lands a stack on each, so the pair beats either alone.
        """
        item = rs.DecayingStackRamp(per_stack=0.08, max_stacks=4, stack_duration=3.0)
        kit = rs.DecayingStackRamp(
            per_stack=0.075, max_stacks=3, stack_duration=2.5, first_stack=0.15
        )
        both = rs.SwingSchedule(ramp=item, window=None, schedules_single_rotation=False)
        kit_only = len(self._times(kit_ramp=kit))
        item_only = len(rs.swing_times(both, duration_seconds=8.0, **self.RATE))
        merged = len(
            rs.swing_times(both, duration_seconds=8.0, kit_ramp=kit, **self.RATE)
        )
        assert merged > kit_only
        assert merged > item_only


class TestAnAbilityStackedRamp:
    """A ramp whose stacks come from casts, not from the swings it rates."""

    RAMP = rs.DecayingStackRamp(per_stack=0.10, max_stacks=5, stack_duration=6.0)
    SCHEDULE = rs.SwingSchedule(ramp=None, window=None, schedules_single_rotation=False)
    RATE = {"attack_speed": 0.625, "attack_speed_ratio": 0.668}

    def _times(self, **kwargs) -> tuple[float, ...]:
        return rs.swing_times(
            self.SCHEDULE, duration_seconds=10.0, **self.RATE, **kwargs
        )

    def test_with_no_ability_stream_it_never_stacks(self):
        """The swings do not stack it, so an empty cast stream leaves it flat."""
        assert (
            self._times(kit_ramp=self.RAMP, kit_ramp_stacks_swings=False)
            == self._times()
        )

    def test_each_cast_admitted_at_its_instant_speeds_the_swings_after_it(self):
        ramped = self._times(
            kit_ramp=self.RAMP,
            kit_ramp_stacks_swings=False,
            kit_ability_stack_times=(0.0, 1.0, 2.0, 3.0, 4.0),
        )
        assert len(ramped) > len(self._times())

    def test_a_stack_expires_on_its_own_clock(self):
        """Five casts in the first second, then nothing: the ramp decays."""
        early = self._times(
            kit_ramp=self.RAMP,
            kit_ramp_stacks_swings=False,
            kit_ability_stack_times=(0.0, 0.2, 0.4, 0.6, 0.8),
        )
        spread = self._times(
            kit_ramp=self.RAMP,
            kit_ramp_stacks_swings=False,
            kit_ability_stack_times=(0.0, 2.0, 4.0, 6.0, 8.0),
        )
        gaps = [after - before for before, after in zip(early, early[1:])]
        # The last gap is wider than the first: by then the early stacks
        # have run out their six seconds and nothing replaced them.
        assert gaps[-1] > gaps[0]
        assert len(spread) != len(early)


class TestEzrealRisingSpellForce:
    """Ability casts stack it; the swings it rates never do."""

    def test_unset_publishes_a_cast_stacked_ramp(self):
        passive = _parse("Ezreal")["passive"]
        ramp = passive["swing_ramp"]
        assert ramp["stacks_from_swings"] is False
        assert ramp["stacks_from_ability_casts"] is True
        assert ramp["max_stacks"] == 5
        assert ramp["stack_duration"] == pytest.approx(6.0)
        assert "stat_buff" not in passive

    def test_the_ramp_sits_between_no_stacks_and_a_full_level(self):
        full = _fight("Ezreal", {"passive_stacks": 5}, 20.0, [RAGEBLADE])
        ramped = _fight("Ezreal", {}, 20.0, [RAGEBLADE])
        none = _fight("Ezreal", {"passive_stacks": 0}, 20.0, [RAGEBLADE])
        assert _autos(none) < _autos(ramped) < _autos(full)


class TestAStackLevelThatFeedsTwoMechanics:
    """One count re-rates the swings AND gates a rider (Volibear, Irelia).

    The ramp and the threshold read different streams by necessity: the
    ramp is resolved in setup and takes the CASTS the schedule places, the
    threshold is resolved after the rotation and takes its ability-hit
    ledger. Each is the best stream where it sits, and both are floors.
    """

    @pytest.mark.parametrize(
        ("champion", "slot", "stacks", "option"),
        [
            ("Volibear", "passive", 5, "relentless_storm_stacks"),
            ("Irelia", "passive", 4, "p_stacks"),
        ],
    )
    def test_unset_declares_a_ramp_and_a_retained_threshold(
        self, champion, slot, stacks, option
    ):
        row = _parse(champion)[slot]
        assert row["swing_ramp"]["max_stacks"] == stacks
        assert row["swing_ramp"]["stacks_from_swings"] is True
        assert row["swing_ramp"]["stacks_from_ability_casts"] is True
        assert row["armed_procs"]["hits_required"] == stacks
        assert row["armed_procs"]["retained_at_threshold"] is True
        # The rider is published whatever the count: which swings carry it
        # is the fight's answer now, not the parser's.
        assert row["on_hit"]["damage_per_hit"] > 0.0
        assert "stat_buff" not in row

    @pytest.mark.parametrize(
        ("champion", "stacks", "option"),
        [
            ("Volibear", 5, "relentless_storm_stacks"),
            ("Irelia", 4, "p_stacks"),
        ],
    )
    def test_a_stated_level_keeps_the_flat_grant_and_the_all_or_nothing_rider(
        self, champion, stacks, option
    ):
        full = _parse(champion, {option: stacks})["passive"]
        assert full["stat_buff"]["bonus_attack_speed"] > 0.0
        assert "swing_ramp" not in full
        assert "armed_procs" not in full
        assert full["on_hit"]["damage_per_hit"] > 0.0
        # One stack short, the rider is worth nothing: Volibear publishes no
        # on_hit at all and Irelia's row carries one priced at zero.
        one_short = _parse(champion, {option: stacks - 1})["passive"]
        assert one_short.get("on_hit", {}).get("damage_per_hit", 0.0) == 0.0

    @pytest.mark.parametrize(
        ("champion", "stacks", "option"),
        [
            ("Volibear", 5, "relentless_storm_stacks"),
            ("Irelia", 4, "p_stacks"),
        ],
    )
    def test_the_ramp_is_worth_less_than_a_declared_full_level(
        self, champion, stacks, option
    ):
        full = _fight(champion, {option: stacks}, 20.0, [RAGEBLADE])
        ramped = _fight(champion, {}, 20.0, [RAGEBLADE])
        none = _fight(champion, {option: 0}, 20.0, [RAGEBLADE])
        assert none["total_damage"] < ramped["total_damage"] < full["total_damage"]


class TestTheReaderFailsClosed:
    """Every number of a kit ramp is the module's; nothing is filled in."""

    RAMP = {"per_stack": 0.05, "max_stacks": 3, "stack_duration": 2.0}

    @staticmethod
    def _state(rows: dict) -> object:
        class _State:
            ability_damages = rows

        return _State()

    def test_a_slot_declaring_a_complete_ramp_resolves_it(self):
        kit = stat_buff_ultimates._kit_swing_ramp(
            self._state({"P": {"name": "Some Passive", "swing_ramp": dict(self.RAMP)}})
        )
        assert kit.ramp == rs.DecayingStackRamp(
            per_stack=0.05, max_stacks=3, stack_duration=2.0
        )
        # Silence means the swings the ramp re-rates, the shape that existed
        # before an ability stream reached here.
        assert kit.stacks_from_swings is True
        assert kit.stacks_from_ability_casts is False

    def test_a_ramp_that_stacks_on_neither_stream_raises(self):
        payload = {**self.RAMP, "stacks_from_swings": False}
        with pytest.raises(ValueError, match="stacks on neither"):
            stat_buff_ultimates._kit_swing_ramp(
                self._state({"P": {"name": "Some Passive", "swing_ramp": payload}})
            )

    def test_an_ability_stacked_ramp_says_so(self):
        payload = {
            **self.RAMP,
            "stacks_from_swings": False,
            "stacks_from_ability_casts": True,
        }
        kit = stat_buff_ultimates._kit_swing_ramp(
            self._state({"P": {"name": "Some Passive", "swing_ramp": payload}})
        )
        assert kit.stacks_from_swings is False
        assert kit.stacks_from_ability_casts is True

    @pytest.mark.parametrize("field", ["per_stack", "max_stacks", "stack_duration"])
    def test_a_missing_number_raises_and_names_the_slot(self, field):
        payload = dict(self.RAMP)
        payload[field] = None
        with pytest.raises(ValueError, match=f"Some Passive.*{field}"):
            stat_buff_ultimates._kit_swing_ramp(
                self._state({"P": {"name": "Some Passive", "swing_ramp": payload}})
            )

    def test_two_declaring_slots_raise_rather_than_pick_one(self):
        with pytest.raises(ValueError, match="one swing stream carries one kit ramp"):
            stat_buff_ultimates._kit_swing_ramp(
                self._state(
                    {
                        "P": {"name": "First", "swing_ramp": dict(self.RAMP)},
                        "Q": {"name": "Second", "swing_ramp": dict(self.RAMP)},
                    }
                )
            )

    def test_no_declaring_slot_is_no_ramp(self):
        assert stat_buff_ultimates._kit_swing_ramp(self._state({"P": {}})) is None


class TestJaxRelentlessAssault:
    """Unset derives the ramp; a stated level is still honoured."""

    def test_unset_publishes_the_ramp_and_no_flat_grant(self):
        passive = _parse("Jax")["passive"]
        assert passive["swing_ramp"]["max_stacks"] == 8
        assert passive["swing_ramp"]["stack_duration"] > 0.0
        assert passive["swing_ramp"]["per_stack"] > 0.0
        assert "stat_buff" not in passive

    def test_a_stated_level_is_a_flat_grant_and_no_ramp(self):
        passive = _parse("Jax", {"p_stacks": 8})["passive"]
        assert passive["stat_buff"]["bonus_attack_speed"] > 0.0
        assert "swing_ramp" not in passive

    def test_the_ramp_buys_fewer_swings_than_a_full_stack_level(self):
        options = {"p_stacks": 8}
        full = _fight("Jax", options, 5.0, [RAGEBLADE])
        ramped = _fight("Jax", {}, 5.0, [RAGEBLADE])
        assert _autos(ramped) < _autos(full)


class TestJinxRevdUp:
    """Pow-Pow's stacks ramp; Fishbones has none to ramp."""

    POW_POW = {"jinx_weapon": "minigun"}

    def test_unset_publishes_the_ramp_with_its_own_first_stack(self):
        row = _parse("Jinx", dict(self.POW_POW))["Q"]
        # Rank 5: 65% on the first stack, 32.5% on each of the two after it.
        assert row["swing_ramp"]["first_stack"] == pytest.approx(0.65)
        assert row["swing_ramp"]["per_stack"] == pytest.approx(0.325)
        assert row["swing_ramp"]["max_stacks"] == 3
        assert row["swing_ramp"]["stack_duration"] == pytest.approx(2.5)
        assert "stat_buff" not in row

    def test_a_stated_level_is_the_flat_grant_the_cache_caps(self):
        row = _parse("Jinx", {**self.POW_POW, "jinx_rev_up_stacks": 3})["Q"]
        assert row["stat_buff"]["bonus_attack_speed"] == pytest.approx(130.0)
        assert "swing_ramp" not in row

    def test_fishbones_carries_no_ramp(self):
        row = _parse("Jinx", {"jinx_weapon": "fishbones"})["Q"]
        assert "swing_ramp" not in row

    def test_the_ramp_buys_fewer_swings_than_a_full_stack_level(self):
        full = _fight(
            "Jinx", {**self.POW_POW, "jinx_rev_up_stacks": 3}, 5.0, [RAGEBLADE]
        )
        ramped = _fight("Jinx", dict(self.POW_POW), 5.0, [RAGEBLADE])
        assert _autos(ramped) == _autos(full) - 1
        assert ramped["total_damage"] < full["total_damage"]

    def test_the_stacks_leave_the_published_stat_sheet(self):
        """The bonus is a stack timeline now, so it is not a flat stat.

        A reader taking ``champion_stats.attack_speed`` for a ramping
        champion gets the unstacked sheet; the stacks live on the swing
        stream, which is where the fight prices them.
        """
        full = _fight("Jinx", {**self.POW_POW, "jinx_rev_up_stacks": 3}, 5.0, [])
        ramped = _fight("Jinx", dict(self.POW_POW), 5.0, [])
        assert (
            ramped["champion_stats"]["attack_speed"]
            < full["champion_stats"]["attack_speed"]
        )
