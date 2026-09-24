"""The one cadence rule: impacts land at windup, counted from the attack command."""

import random

import pytest

from src.calculator.attack_cadence import (
    champion_windup,
    counted_impacts,
    impact_count,
    impact_times,
    opener_spans,
    stream_impacts,
)
from src.calculator.calculate import calculate_payload
from src.calculator.data_fetcher import get_champion

# The League Wiki's base-statistics Windup% for each champion, read 2026-09-23:
# Jinx and Ahri state it one way (castTime/totalTime, 0.3 + offset), Jax and
# Corki the other, so both readings of the cached row are pinned.
WIKI_WINDUP_PERCENT = {"Jax": 0.20811, "Jinx": 0.16875, "Corki": 0.27, "Ahri": 0.2}


@pytest.mark.parametrize("champion,percent", sorted(WIKI_WINDUP_PERCENT.items()))
def test_the_cached_windup_is_the_wikis(champion: str, percent: float) -> None:
    windup = champion_windup(get_champion(champion))
    assert windup.percent == pytest.approx(percent, abs=1e-5)


def test_a_windup_modifier_keeps_part_of_the_windup_off_bonus_attack_speed() -> None:
    darius = champion_windup(get_champion("Darius"))
    assert darius.modifier == 0.5
    assert darius.phase(darius.base_attack_speed) == pytest.approx(darius.percent)
    assert darius.phase(2 * darius.base_attack_speed) > darius.percent


def test_a_one_rate_stream_lands_at_windup_then_every_cycle() -> None:
    assert stream_impacts(1.0, 3.0, 0.2) == pytest.approx((0.2, 1.2, 2.2))
    assert impact_count(1.0, 3.0, 0.2) == 3
    assert counted_impacts(2, 1.0, 0.2, start=5.0) == pytest.approx([5.2, 6.2])
    # A zero phase is an attacker with no windup: it lands at the command.
    assert stream_impacts(1.0, 3.0, 0.0) == pytest.approx((0.0, 1.0, 2.0))


def test_the_count_and_the_walk_are_one_rule() -> None:
    draws = random.Random(7)
    for _ in range(5000):
        rate, seconds, phase = (
            draws.uniform(0.2, 3.0),
            draws.uniform(0.1, 20.0),
            draws.uniform(0.0, 0.6),
        )
        walked = stream_impacts(rate, seconds, phase)
        assert impact_count(rate, seconds, phase) == len(walked)
        assert all(time < seconds for time in walked)


def test_one_attack_timer_runs_through_a_rate_change() -> None:
    # 1.5 cycles at 1/s, then 2/s: impact k lands at k + 0.25 cycles, so the
    # third lands 0.75 cycles into the faster span, 0.375s after it opens.
    times = impact_times(((0.0, 1.5, 1.0), (1.5, 3.0, 2.0)), 0.25)
    assert times == pytest.approx((0.25, 1.25, 1.875, 2.375, 2.875))


def test_an_opener_runs_its_impacts_at_its_own_rate_then_hands_the_timer_on() -> None:
    spans = opener_spans(2.0, 3, 1.0, 5.0)
    assert spans == ((0.0, 1.5, 2.0), (1.5, 5.0, 1.0))
    assert impact_times(spans, 0.2) == pytest.approx(
        (0.1, 0.6, 1.1, 1.7, 2.7, 3.7, 4.7)
    )


def test_a_fight_lands_its_first_swing_at_the_champions_windup() -> None:
    payload = calculate_payload(
        {
            "champion": "Rumble",
            "level": 18,
            "items": [],
            "fight_mode": "timed",
            "fight_duration": 8.0,
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
        },
        deterministic=True,
        trace=True,
    )
    swings = [
        line["time"]
        for line in payload["trace"]["lines"]
        if line["source"] == "auto_attacks"
    ]
    rate = payload["champion_stats"]["attack_speed"]
    phase = champion_windup(get_champion("Rumble")).phase(rate)
    assert swings == pytest.approx(stream_impacts(rate, 8.0, phase))
    # floor(8 x 0.8465) counted six and left 2.1s idle after the sixth.
    assert len(swings) == 7
