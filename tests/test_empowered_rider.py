"""A cast that empowers the next basic attack: which swing it takes, and its rider.

Jax W and Leona Q each empower "his/her next basic attack" to deal bonus
magic damage, so a timed fight moves one stream swing per cast onto the
ability's row and pays the rider on that swing alone.
"""

import pytest

from src.calculator.calculate import calculate_payload
from src.calculator.champions import parse_champion_abilities
from tests import cc_review

EMPOWERS = [("Jax", "W"), ("Leona", "Q")]


def _fight(champion, **request):
    return calculate_payload(
        {
            "champion": champion,
            "level": 18,
            "items": [],
            "fight_mode": "timed",
            "fight_duration": 8.0,
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
            **request,
        },
        deterministic=True,
        trace=True,
    )


def _lines(payload, source, damage_class):
    return [
        line
        for line in payload["trace"]["lines"]
        if line["source"] == source and line["damage_class"] == damage_class
    ]


def _times(payload, source, damage_class):
    return [line["time"] for line in _lines(payload, source, damage_class)]


@pytest.mark.parametrize(("champion", "slot"), EMPOWERS)
def test_each_cast_takes_the_first_swing_after_it(champion, slot):
    """The auto row keeps every other swing, through the fight's last one."""
    payload = _fight(champion)
    casts = [cast["time"] for cast in payload["cast_timeline"] if cast["slot"] == slot]
    empowered = _times(payload, slot, "physical")
    plain = _times(payload, "auto_attacks", "physical")
    stream = sorted(empowered + plain)
    assert len(casts) >= 2
    assert empowered == [min(time for time in stream if time > cast) for cast in casts]
    assert plain[-1] == stream[-1]


@pytest.mark.parametrize(("champion", "slot"), EMPOWERS)
def test_the_rider_lands_once_per_cast_on_its_swing(champion, slot):
    payload = _fight(champion)
    assert f"on_hit_ability_{slot}" not in payload["breakdown"]
    assert _times(payload, slot, "magic") == _times(payload, slot, "physical")


@pytest.mark.parametrize(("champion", "slot"), EMPOWERS)
def test_one_rotation_pays_the_rider_beside_the_swing_it_forces(champion, slot):
    payload = _fight(champion, fight_mode="one_rotation")
    rider = parse_champion_abilities(cc_review.kit(champion), 18, 0.0)[slot]
    (magic,) = _lines(payload, slot, "magic")
    magic_resistance = payload["trace"]["effective_mr"]
    assert magic["mitigated"] == pytest.approx(
        rider["total_raw"] * 100.0 / (100.0 + magic_resistance)
    )
    assert len(_lines(payload, slot, "physical")) == 1
