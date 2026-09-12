"""A cast the fight cannot make until a counter fills.

Ashe's Ranger's Focus "can only be activated at 4 stacks", and her basic
attacks are what bank them. The rule answers one thing, the earliest instant
the count stands, and two readers use it: the cast scheduler seeds the
slot's readiness with it, and ``cast_slots.slot_cast_start`` opens the row's
attack-speed window there.
"""

from dataclasses import replace

import pytest

from src.calculator.champions.cast_arming import (
    CastArmingRule,
    banking_swings,
    declared_rules,
    ready_at,
)
from src.calculator.champions import parse_champion_abilities
from src.calculator.data_fetcher import get_champion
from src.calculator.pipeline import run_fight
from src.calculator.scenario import parse_scenario_request, resolve_scenario
from src.calculator.stats import calculate_total_stats

FOUR = CastArmingRule(stacks_required=4, stack_seconds=4.0, max_stacks=4)


def _fight(options: dict, duration: float) -> dict:
    request = parse_scenario_request(
        {
            "champion": "Ashe",
            "level": 13,
            "role": "bottom",
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


class TestWhenTheCountStands:
    def test_the_event_that_completes_the_count_is_the_instant(self):
        """Four attacks a second apart: the fourth is when the cast arms,
        not the moment after it."""
        assert ready_at(FOUR, (0.0, 1.0, 2.0, 3.0, 4.0)) == 3.0

    def test_a_stream_slower_than_the_decay_never_arrives(self):
        """Five seconds apart against a four-second stack: the count never
        passes one, so the cast is never available."""
        assert ready_at(FOUR, (0.0, 5.0, 10.0, 15.0, 20.0)) == float("inf")

    def test_a_stream_too_short_to_fill_it_never_arrives(self):
        assert ready_at(FOUR, (0.0, 0.5, 1.0)) == float("inf")

    def test_no_stream_at_all_never_arrives(self):
        assert ready_at(FOUR, ()) == float("inf")

    def test_the_cap_does_not_block_the_count_it_equals(self):
        """A rule whose threshold IS its cap still arms; the eviction that
        makes room happens only past the cap."""
        assert ready_at(FOUR, (0.0, 0.1, 0.2, 0.3)) == pytest.approx(0.3)


class TestTheBankingStream:
    def test_the_swings_are_even_at_the_fight_rate(self):
        assert banking_swings(1.0, 1.0, 3.5) == (0.0, 1.0, 2.0, 3.0)

    def test_uptime_stretches_the_gap(self):
        assert banking_swings(1.0, 0.5, 3.5) == (0.0, 2.0)

    @pytest.mark.parametrize(
        ("speed", "uptime", "duration"),
        [(0.0, 1.0, 5.0), (1.0, 0.0, 5.0), (1.0, 1.0, 0.0)],
    )
    def test_a_fight_with_no_swings_banks_nothing(self, speed, uptime, duration):
        assert banking_swings(speed, uptime, duration) == ()


class TestTheDeclarationFailsClosed:
    PAYLOAD = {"stacks_required": 4, "stack_seconds": 4.0, "max_stacks": 4}

    def test_a_complete_declaration_resolves(self):
        assert declared_rules({"Q": {"cast_requires_stacks": dict(self.PAYLOAD)}}) == {
            "Q": FOUR
        }

    @pytest.mark.parametrize(
        "field", ["stacks_required", "stack_seconds", "max_stacks"]
    )
    def test_a_missing_number_raises_and_names_the_slot(self, field):
        payload = dict(self.PAYLOAD)
        payload[field] = None
        with pytest.raises(ValueError, match=f"Q: .*{field}"):
            declared_rules({"Q": {"cast_requires_stacks": payload}})

    def test_a_gate_on_nothing_is_refused(self):
        with pytest.raises(ValueError, match="cast with no gate"):
            CastArmingRule(stacks_required=0, stack_seconds=4.0, max_stacks=4)

    def test_a_gate_past_the_cap_is_refused(self):
        with pytest.raises(ValueError, match="never arms"):
            CastArmingRule(stacks_required=5, stack_seconds=4.0, max_stacks=4)

    def test_a_stack_with_no_life_is_refused(self):
        with pytest.raises(ValueError, match="no positive stack_seconds"):
            CastArmingRule(stacks_required=4, stack_seconds=0.0, max_stacks=4)

    def test_no_declaring_slot_is_no_rule(self):
        assert declared_rules({"Q": {"name": "Something"}}) == {}


class TestAsheRangersFocus:
    """The one kit on it, end to end."""

    @staticmethod
    def _row(options: dict | None = None) -> dict:
        data = get_champion("Ashe")
        return parse_champion_abilities(
            data,
            18,
            0.0,
            ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
            champion_stats=calculate_total_stats(data, 18, []),
            champion_options=options or {},
        )["Q"]

    def test_unset_declares_the_gate_from_the_cached_stack_rule(self):
        gate = self._row()["cast_requires_stacks"]
        assert gate["stacks_required"] == 4
        assert gate["max_stacks"] == 4
        assert gate["stack_seconds"] > 0.0

    def test_a_stated_full_level_declares_no_gate(self):
        assert "cast_requires_stacks" not in self._row({"q_focus_stacks": 4})

    def test_a_stated_short_level_publishes_no_row_at_all(self):
        """The old reading, kept: three stacks cannot activate it."""
        data = get_champion("Ashe")
        rows = parse_champion_abilities(
            data,
            18,
            0.0,
            ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
            champion_stats=calculate_total_stats(data, 18, []),
            champion_options={"q_focus_stacks": 3},
        )
        assert "Q" not in rows

    def test_a_fight_too_short_to_bank_four_casts_nothing(self):
        """Three seconds: the derived reading matches the no-stacks one,
        because the fourth attack never lands inside the fight."""
        derived = _fight({}, 3.0)
        never = _fight({"q_focus_stacks": 0}, 3.0)
        assert derived["total_damage"] == pytest.approx(never["total_damage"])

    def test_a_fight_long_enough_banks_them_and_casts_late(self):
        """Five seconds: worth more than never casting and less than opening
        with Focus already full."""
        never = _fight({"q_focus_stacks": 0}, 5.0)
        derived = _fight({}, 5.0)
        ready = _fight({"q_focus_stacks": 4}, 5.0)
        assert never["total_damage"] < derived["total_damage"] < ready["total_damage"]
