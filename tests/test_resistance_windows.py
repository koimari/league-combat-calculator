"""A timed packet meets the shred live when it lands, and only then."""

import pytest

from src.calculator.calculate import calculate_payload
from src.calculator.resistance import apply_resistance, rescale_mitigated


def _fight(champion: str, seconds: float, *, trace: bool = False) -> dict:
    return calculate_payload(
        {
            "champion": champion,
            "level": 18,
            "items": [],
            "fight_mode": "timed",
            "fight_duration": seconds,
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
            "target_armor": 150.0,
            "target_mr": 90.0,
            "count_damage_after_fight_end": False,
        },
        deterministic=True,
        trace=trace,
    )


def test_rescaling_is_the_ratio_of_the_two_mitigations() -> None:
    mitigated = apply_resistance(300.0, 80.0) * 1.2
    assert rescale_mitigated(mitigated, 80.0, 50.0) == pytest.approx(
        apply_resistance(300.0, 50.0) * 1.2
    )


@pytest.mark.parametrize("champion", ["Sion", "Vi", "Karthus"])
def test_a_longer_fight_never_deals_less(champion: str) -> None:
    """The three the property sweep caught: a shred weighted by its share of
    the fight shrank for packets inside its window as the fight grew."""
    totals = [
        _fight(champion, float(seconds))["total_damage"] for seconds in range(2, 15)
    ]
    assert totals == sorted(totals)


def test_kogmaws_q_shreds_magic_resistance_only_inside_its_window() -> None:
    lines = _fight("Kog'Maw", 8.0, trace=True)["trace"]["lines"]
    q_casts = sorted(line["time"] for line in lines if line["source"] == "Q")
    magic = [
        line
        for line in lines
        if line["damage_class"] == "magic" and line["source"] != "Q"
    ]
    inside = [line for line in magic if q_casts[0] <= line["time"] <= q_casts[0] + 4.0]
    outside = [line for line in magic if q_casts[0] + 4.0 < line["time"] < q_casts[1]]
    assert inside and outside
    # Caustic Spittle's rank-5 cut is 32% for 4 seconds; Kog'Maw carries no
    # magic penetration here.
    assert {round(line["resistance_met"], 6) for line in inside} == {61.2}
    assert {round(line["resistance_met"], 6) for line in outside} == {90.0}


def test_garens_judgment_shreds_from_its_sixth_spin_not_from_the_fight_start() -> None:
    lines = [
        line
        for line in _fight("Garen", 8.0, trace=True)["trace"]["lines"]
        if line["damage_class"] == "physical" and line["resistance_met"] is not None
    ]
    spins = sorted(line["time"] for line in lines if line["source"] == "E")
    sixth = spins[5]
    opening = [
        line for line in lines if line["source"] != "E" and line["time"] <= sixth
    ]
    after = [
        line
        for line in lines
        if line["source"] != "E" and sixth < line["time"] <= sixth + 6.0
    ]
    assert opening and after
    assert {round(line["resistance_met"], 6) for line in opening} == {150.0}
    assert {round(line["resistance_met"], 6) for line in after} == {112.5}
