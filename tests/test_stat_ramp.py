"""A stack level granting a stat no swing walker can carry.

The ramp's own arithmetic is the time-weighted mean of the stack count over
the fight, and the fight serves it once. See
``src/calculator/champions/stat_ramp.py`` for why that is the reading and
what it approximates.
"""

from dataclasses import replace

import pytest

from src.calculator.champions import parse_champion_abilities
from src.calculator.champions.stat_ramp import (
    StatRampRule,
    declared_rule,
    mean_stack_level,
)
from src.calculator.data_fetcher import get_champion
from src.calculator.pipeline import run_fight
from src.calculator.scenario import parse_scenario_request, resolve_scenario
from src.calculator.stats import calculate_total_stats

_FULL_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}


def _parse(champion: str, options: dict | None = None) -> dict:
    """The champion's compiled slot table at level 18 under *options*."""
    data = get_champion(champion)
    return parse_champion_abilities(
        data,
        18,
        0.0,
        ability_ranks=dict(_FULL_RANKS),
        champion_stats=calculate_total_stats(data, 18, []),
        target_stats={"armor": 100.0, "magic_resistance": 100.0, "max_health": 2000.0},
        champion_options=options or {},
    )


def _fight(champion: str, role: str, options: dict, duration: float) -> dict:
    request = parse_scenario_request(
        {
            "champion": champion,
            "level": 13,
            "role": role,
            "items": [],
            "champion_options": options,
            "enemies": [{"champion": "Aatrox", "level": 13, "role": "top"}],
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


_SWINGS = StatRampRule(
    per_stack={"bonus_attack_damage": 2.0},
    max_stacks=5,
    stack_duration=6.0,
    stacks_from_swings=True,
)


class TestTheMean:
    """The level a fight held on average, integrated rather than counted."""

    def test_one_event_a_second_fills_and_then_holds_the_cap(self):
        """Ten swings a second apart, five held for six seconds each: the
        count climbs one a second to the cap and stays, so the mean is the
        area 1+2+3+4+5+5+5+5+5+5 over ten seconds."""
        swings = [float(second) for second in range(10)]
        assert mean_stack_level(_SWINGS, swings, (), 10.0) == pytest.approx(4.0)

    def test_a_fight_that_ends_before_the_ramp_fills_is_priced_lower(self):
        swings = [float(second) for second in range(10)]
        assert mean_stack_level(_SWINGS, swings, (), 3.0) == pytest.approx(2.0)

    def test_a_stream_the_rule_does_not_count_stacks_nothing(self):
        """The swing rule ignores casts, so a cast-only fight holds no level."""
        assert mean_stack_level(_SWINGS, (), (0.0, 1.0, 2.0), 10.0) == 0.0

    def test_a_fight_with_no_duration_has_no_mean(self):
        assert mean_stack_level(_SWINGS, (0.0, 1.0), (), 0.0) == 0.0

    def test_a_stack_lapses_on_its_own_clock(self):
        """Two swings, then nothing: the level is live for six seconds and
        zero for the rest, so the mean is well under two."""
        mean = mean_stack_level(_SWINGS, (0.0, 0.5), (), 20.0)
        assert 0.0 < mean < 1.0


class TestTheGrant:
    def test_a_level_prices_each_stat_it_names(self):
        rule = StatRampRule(
            per_stack={"armor": 3.0, "magic_resistance": 1.5},
            max_stacks=8,
            stack_duration=4.0,
            stacks_from_ability_casts=True,
        )
        assert rule.grant(4.0) == {"armor": 12.0, "magic_resistance": 6.0}

    def test_the_cap_is_never_passed(self):
        assert _SWINGS.grant(99.0) == {"bonus_attack_damage": 10.0}

    def test_the_fill_multiplier_applies_at_the_cap_and_nowhere_below_it(self):
        """Zaahen's shape: filled Determination doubles the whole bonus."""
        rule = replace(_SWINGS, filled_multiplier=2.0)
        assert rule.grant(5.0) == {"bonus_attack_damage": 20.0}
        assert rule.grant(4.999) == pytest.approx(
            {"bonus_attack_damage": 9.998}, rel=1e-9
        )


class TestTheDeclarationFailsClosed:
    PAYLOAD = {
        "per_stack": {"armor": 2.0},
        "max_stacks": 4,
        "stack_duration": 5.0,
        "stacks_from_swings": True,
    }

    def test_a_complete_declaration_resolves(self):
        owner, rule = declared_rule(
            {"P": {"name": "Some Passive", "stat_ramp": dict(self.PAYLOAD)}}
        )
        assert owner == "Some Passive"
        assert rule.per_stack == {"armor": 2.0}
        assert rule.arming_slots == frozenset()

    @pytest.mark.parametrize("field", ["per_stack", "max_stacks", "stack_duration"])
    def test_a_missing_number_raises_and_names_the_slot(self, field):
        payload = dict(self.PAYLOAD)
        payload[field] = None
        with pytest.raises(ValueError, match=f"Some Passive.*{field}"):
            declared_rule({"P": {"name": "Some Passive", "stat_ramp": payload}})

    def test_two_declaring_slots_raise_rather_than_pick_one(self):
        with pytest.raises(ValueError, match="one stack count carries one"):
            declared_rule(
                {
                    "P": {"name": "First", "stat_ramp": dict(self.PAYLOAD)},
                    "E": {"name": "Second", "stat_ramp": dict(self.PAYLOAD)},
                }
            )

    def test_a_ramp_that_names_no_stream_never_leaves_zero_and_is_refused(self):
        payload = {**self.PAYLOAD, "stacks_from_swings": False}
        with pytest.raises(ValueError, match="names no stream"):
            declared_rule({"P": {"name": "Some Passive", "stat_ramp": payload}})

    def test_a_stack_with_no_life_is_refused(self):
        payload = {**self.PAYLOAD, "stack_duration": 0.0}
        with pytest.raises(ValueError, match="no positive stack_duration"):
            declared_rule({"P": {"name": "Some Passive", "stat_ramp": payload}})

    def test_a_ramp_granting_nothing_is_refused(self):
        with pytest.raises(ValueError, match="grants nothing per stack"):
            StatRampRule(
                per_stack={},
                max_stacks=3,
                stack_duration=4.0,
                stacks_from_swings=True,
            )

    def test_no_declaring_slot_is_no_rule(self):
        assert declared_rule({"P": {"name": "Some Passive"}}) is None


class TestTheKitsOnIt:
    """Three champions, three streams, one reading."""

    @pytest.mark.parametrize(
        ("champion", "slot", "option", "stat", "swings", "casts"),
        [
            (
                "Zaahen",
                "passive",
                "p_determination_stacks",
                "bonus_attack_damage",
                True,
                True,
            ),
            ("Graves", "E", "e_true_grit_stacks", "armor", False, True),
            ("Wukong", "passive", "stone_skin_stacks", "armor", True, True),
        ],
    )
    def test_unset_declares_the_ramp_over_the_streams_its_cache_names(
        self, champion, slot, option, stat, swings, casts
    ):
        row = _parse(champion)[slot]
        ramp = row["stat_ramp"]
        assert stat in ramp["per_stack"]
        assert ramp["max_stacks"] >= 1
        assert ramp["stack_duration"] > 0.0
        assert bool(ramp.get("stacks_from_swings")) is swings
        assert bool(ramp.get("stacks_from_ability_casts")) is casts

    def test_only_quickdraw_stacks_graves(self):
        """Every other cast of his is not a True Grit stack."""
        assert _parse("Graves")["E"]["stat_ramp"]["arming_slots"] == ("E",)

    @pytest.mark.parametrize(
        ("champion", "role", "option", "full", "stat"),
        [
            ("Zaahen", "top", "p_determination_stacks", 12, "attack_damage"),
            ("Graves", "bottom", "e_true_grit_stacks", 8, "armor"),
            ("Wukong", "top", "stone_skin_stacks", 5, "armor"),
        ],
    )
    def test_the_mean_sits_between_no_stacks_and_a_full_level(
        self, champion, role, option, full, stat
    ):
        none = _fight(champion, role, {option: 0}, 20.0)
        ramped = _fight(champion, role, {}, 20.0)
        declared = _fight(champion, role, {option: full}, 20.0)
        assert (
            none["champion_stats"][stat]
            < ramped["champion_stats"][stat]
            < declared["champion_stats"][stat]
        )

    @pytest.mark.parametrize(
        ("champion", "role", "option", "full"),
        [
            ("Zaahen", "top", "p_determination_stacks", 12),
            ("Graves", "bottom", "e_true_grit_stacks", 8),
            ("Wukong", "top", "stone_skin_stacks", 5),
        ],
    )
    def test_a_stated_level_keeps_the_flat_grant_and_declares_no_ramp(
        self, champion, role, option, full
    ):
        rows = _parse(champion, {option: full})
        declaring = [
            row for row in rows.values() if isinstance(row, dict) and "stat_ramp" in row
        ]
        assert declaring == []
