"""Tests for champion-layer primitives shared by all champion modules.

Covers calculate_ability_damage (champions.common), effective_cooldown
(damage.py), castTime extraction (champions.slotlib), and skill-order
rank resolution (champions.skill_orders).
"""

import pytest

from src.calculator.champions import parse_champion_abilities
from src.calculator.champions.common import calculate_ability_damage
from src.calculator.champions.skill_orders import get_ability_rank
from src.calculator.champions.slotlib import extract_cast_time
from src.calculator.damage import effective_cooldown
from src.calculator.data_fetcher import get_champion


class TestCalculateAbilityDamage:
    """Tests for raw ability damage calculation."""

    def test_base_only(self) -> None:
        assert calculate_ability_damage(100, 0.5, 0) == 100.0

    def test_with_scaling(self) -> None:
        result = calculate_ability_damage(100, 0.5, 200)
        assert result == 200.0

    def test_zero_base_with_scaling(self) -> None:
        result = calculate_ability_damage(0, 0.5, 200)
        assert result == 100.0


class TestGetAbilityRank:
    """Tests for skill order (Q > W > E, R at 6/11/16)."""

    def test_level_1_q_rank_1(self) -> None:
        assert get_ability_rank("Q", 1) == 1

    def test_level_6_q_rank_3(self) -> None:
        assert get_ability_rank("Q", 6) == 3

    def test_level_6_w_rank_1(self) -> None:
        assert get_ability_rank("W", 6) == 1

    def test_level_6_e_rank_1(self) -> None:
        assert get_ability_rank("E", 6) == 1

    def test_level_6_r_rank_1(self) -> None:
        assert get_ability_rank("R", 6) == 1

    def test_level_11_q_rank_5(self) -> None:
        assert get_ability_rank("Q", 11) == 5

    def test_level_11_w_rank_3(self) -> None:
        assert get_ability_rank("W", 11) == 3

    def test_level_11_e_rank_1(self) -> None:
        assert get_ability_rank("E", 11) == 1

    def test_level_11_r_rank_2(self) -> None:
        assert get_ability_rank("R", 11) == 2

    def test_level_16_r_rank_3(self) -> None:
        assert get_ability_rank("R", 16) == 3

    def test_level_18_all_maxed(self) -> None:
        assert get_ability_rank("Q", 18) == 5
        assert get_ability_rank("W", 18) == 5
        assert get_ability_rank("E", 18) == 5
        assert get_ability_rank("R", 18) == 3


class TestGetEffectiveCooldown:
    """Tests for cooldown reduction from ability haste."""

    def test_no_haste(self) -> None:
        assert effective_cooldown(7.0, 0.0) == 7.0

    def test_with_haste(self) -> None:
        result = effective_cooldown(7.0, 15.0)
        expected = 7.0 * 100 / 115
        assert abs(result - expected) < 0.01


class TestExtractCastTime:
    """Wiki castTime free text -> seconds of cast lockout."""

    def test_missing_and_none_strings_are_instant(self) -> None:
        assert extract_cast_time({}) == 0.0
        assert extract_cast_time({"castTime": None}) == 0.0
        assert extract_cast_time({"castTime": "none"}) == 0.0
        assert extract_cast_time({"castTime": "None"}) == 0.0
        assert extract_cast_time({"castTime": "false"}) == 0.0

    def test_plain_numbers(self) -> None:
        assert extract_cast_time({"castTime": "0.25"}) == pytest.approx(0.25)
        assert extract_cast_time({"castTime": "1"}) == pytest.approx(1.0)
        assert extract_cast_time({"castTime": 0.5}) == pytest.approx(0.5)

    def test_first_cast_segment_wins_over_recast(self) -> None:
        """'cast • recast': only the first segment locks out the caster."""
        assert extract_cast_time({"castTime": "0.25 • None"}) == pytest.approx(0.25)
        assert extract_cast_time({"castTime": "None • 0.25"}) == 0.0
        assert extract_cast_time({"castTime": "1 • 1.25"}) == pytest.approx(1.0)

    def test_scaling_text_takes_base_value(self) -> None:
        """Level/AS-scaled cast times read the first (slowest) value."""
        assert extract_cast_time(
            {"castTime": "0.25 / 0.225 / 0.2 / 0.175 (based on level)"}
        ) == pytest.approx(0.25)
        assert extract_cast_time(
            {"castTime": "0.25 : 0.1 (based on bonus attack speed)"}
        ) == pytest.approx(0.25)

    def test_windup_percentage_reads_at_base_seconds(self) -> None:
        """'80% of X's windup time (0.4 at base...)': 80 is not seconds."""
        assert extract_cast_time(
            {"castTime": "80% of Senna's windup time (0.4 at base attack speed)"}
        ) == pytest.approx(0.4)

    def test_pure_windup_text_is_instant(self) -> None:
        assert extract_cast_time({"castTime": "Attack Windup Time"}) == 0.0
        assert extract_cast_time({"castTime": "Basic attack timer"}) == 0.0


class TestTargetDebuffDurations:
    """Every resistance shred in the game expires — none is permanent.

    An undeclared duration means "rest of the fight", which over-shreds
    any timed fight longer than the debuff. These are the real in-game
    durations, read from each ability's own wiki description.
    """

    # (champion, slot, level, expected duration in seconds)
    _SHREDS = [
        ("Kog'Maw", "Q", 18, 4.0),  # "for 4 seconds"
        ("Briar", "Q", 18, 5.0),  # "for 5 seconds"
        ("Jarvan IV", "Q", 18, 3.0),  # "for 3 seconds"
        ("Jayce", "R", 18, 5.0),  # "for 5 seconds"
        # Corki's stacks last 2s but REFRESH through his 4s channel, so
        # the shred is up from the cast until 2s after the last tick.
        ("Corki", "E", 18, 6.0),
    ]

    @pytest.mark.parametrize(("champion", "slot", "level", "duration"), _SHREDS)
    def test_shred_declares_its_duration(self, champion, slot, level, duration) -> None:
        abilities = parse_champion_abilities(
            get_champion(champion), level, 100.0, champion_stats={}
        )
        debuff = abilities[slot]["target_debuff"]
        assert debuff["duration"] == pytest.approx(duration)
