"""Issue #329: per-attack riders ride the swings, and a non-Q window is placed.

The engine places a kit's attack-speed window at the first cast of the slot
that grants it, anchors a ``proc_window`` on-hit at that same cast, and
applies a bare ``ad_ratio`` to the swings inside the window.  The kits the
issue named are probed through the real pipeline: a deterministic level-18
timed fight, autos on, zero resists.
"""

import math
from types import SimpleNamespace

import pytest

from src.calculator.calculate import calculate_payload
from src.calculator.fight.cast_slots import slot_cast_start
from src.calculator.fight.setup.stat_buff_ultimates import _rate_attack_speed_grant

_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_FIGHT_SECONDS = 10.0


def _fight(champion: str, items: list[str] | None = None, **overrides) -> dict:
    request = {
        "champion": champion,
        "level": 18,
        "items": items or [],
        "ability_ranks": dict(_RANKS),
        "fight_mode": "timed",
        "fight_duration": _FIGHT_SECONDS,
        "include_auto_attacks": True,
        "auto_attack_uptime": 1.0,
        "target_health": 10_000,
        "target_armor": 0,
        "target_mr": 0,
    }
    request.update(overrides)
    return calculate_payload(request, deterministic=True)


def _swings(result: dict) -> list[dict]:
    return [e for e in result["damage_events"] if e.get("source") == "auto_attacks"]


def _window_start(result: dict, slot: str) -> float:
    """When the slot's first cast lands in the published timeline."""
    return next(float(e["time"]) for e in result["cast_timeline"] if e["slot"] == slot)


class TestTheWindowOpensAtTheGrantingSlotsCast:
    """Pattern B: the cast-start lookup is the slot's, not Q's."""

    def test_slot_cast_start_sums_the_cast_times_ordered_before_the_slot(self):
        state = SimpleNamespace(
            cast_order=["Q", "Q2", "W", "E", "R"],
            ability_damages={
                "Q": {"name": "Q", "cast_time": 0.25},
                "W": {"name": "W", "cast_time": 0.5},
                "E": {"name": "E", "cast_time": 0.0},
            },
        )
        assert slot_cast_start(state, "Q") == 0.0
        assert slot_cast_start(state, "E") == pytest.approx(0.75)
        assert slot_cast_start(state, "E_passive") == pytest.approx(0.75)
        # A row outside the cast order (a passive) is live from the open.
        assert slot_cast_start(state, "passive") == 0.0

    def test_a_second_windowed_grant_raises_instead_of_overwriting(self):
        state = SimpleNamespace(
            cast_order=["Q", "W", "E", "R"],
            ability_damages={},
            attack_speed=0.7,
            attack_speed_ratio=0.7,
            as_window_slot="",
            as_window_start=0.0,
            as_window_end=0.0,
            as_window_base_rate=0.0,
            as_window_pre_autos=0,
            as_window_autos=0,
            num_auto_attacks=0,
            fight_duration_seconds=10.0,
            auto_attack_uptime=1.0,
            one_rotation=False,
            declared=SimpleNamespace(
                charged_strikes=SimpleNamespace(swing_schedule=None)
            ),
        )
        _rate_attack_speed_grant(state, "E", 40.0, 5.0)
        assert state.as_window_slot == "E"
        with pytest.raises(ValueError, match="W places a second attack-speed window"):
            _rate_attack_speed_grant(state, "W", 40.0, 5.0)

    @pytest.mark.parametrize(
        ("champion", "slot", "duration", "granted"),
        [
            ("Kennen", "E", 4.0, 80.0),
            ("Xin Zhao", "E", 5.0, 70.0),
            ("Samira", "E", 5.0, 40.0),
            ("Wukong", "E", 5.0, 60.0),
            ("Xayah", "W", 4.0, 55.0),
            ("Nidalee", "E", 7.0, 70.0),
            ("Yuumi", "E", 3.0, 35.0),
            ("Sivir", "W", 4.0, 40.0),
        ],
    )
    def test_the_non_q_window_rates_the_swings_inside_it(
        self, champion, slot, duration, granted
    ):
        result = _fight(champion)
        unbuffed = _fight(champion, ability_ranks=dict(_RANKS, **{slot: 0}))
        base_as = unbuffed["champion_stats"]["attack_speed"]
        ratio = unbuffed["champion_stats"]["attack_speed_ratio"]
        # The published stat is the grant on top of the build's own.
        assert result["champion_stats"]["bonus_attack_speed"] == pytest.approx(
            unbuffed["champion_stats"]["bonus_attack_speed"] + granted, abs=1e-6
        )
        start = _window_start(result, slot)
        times = [float(e["time"]) for e in _swings(result)]
        inside = [t for t in times if start <= t < start + duration]
        after = [t for t in times if t >= start + duration]
        assert len(inside) == math.floor((base_as + ratio * granted / 100.0) * duration)
        assert inside[0] == pytest.approx(start)
        if len(after) > 1:  # published times are rounded to the millisecond
            assert after[1] - after[0] == pytest.approx(1.0 / base_as, abs=2e-3)


class TestTwistedFate:
    """E is an innate attack-speed grant and an every-4th-attack on-hit."""

    def test_stacked_deck_procs_every_fourth_swing(self):
        result = _fight("Twisted Fate")
        swings = result["breakdown"]["auto_attacks"]["count"]
        row = result["breakdown"]["on_hit_ability_E"]
        assert row["count"] == swings // 4 == 3
        assert row["damage_per_hit"] == pytest.approx(165.0)
        assert result["breakdown"]["E"]["total_damage"] == 0.0

    def test_the_attack_speed_is_innate_so_autos_only_keeps_it(self):
        result = _fight("Twisted Fate", fight_mode="auto_only")
        unranked = _fight("Twisted Fate", ability_ranks=dict(_RANKS, E=0))
        assert result["champion_stats"]["bonus_attack_speed"] == pytest.approx(
            unranked["champion_stats"]["bonus_attack_speed"] + 55.0
        )
        assert result["breakdown"]["on_hit_ability_E"]["count"] == 3

    def test_rageblade_phantoms_stack_the_deck(self):
        result = _fight("Twisted Fate", ["Guinsoo's Rageblade"])
        applications = result["breakdown"]["on_hit_Guinsoo's Rageblade"]["count"]
        assert result["breakdown"]["on_hit_ability_E"]["count"] == applications // 4


class TestMasterYi:
    """E is a true-damage on-hit on the swings inside its 5-second window."""

    def test_wuju_style_rides_every_swing_inside_the_window(self):
        result = _fight("Master Yi")
        start = _window_start(result, "E")
        inside = [e for e in _swings(result) if start <= float(e["time"]) < start + 5.0]
        row = result["breakdown"]["on_hit_ability_E"]
        assert row["count"] == len(inside) == 7
        assert row["damage_per_hit"] == pytest.approx(40.0)
        assert result["breakdown"]["E"]["total_damage"] == 0.0


class TestTeemo:
    """E is an on-hit on every swing plus the poison every swing refreshes."""

    def test_toxic_shot_rides_every_swing(self):
        result = _fight("Teemo")
        swings = result["breakdown"]["auto_attacks"]["count"]
        assert result["breakdown"]["on_hit_ability_E"]["count"] == swings == 10
        assert result["breakdown"]["on_hit_ability_E"]["damage_per_hit"] == 65.0
        poison = result["breakdown"]["stacking_dot_E"]
        assert poison["count"] == swings
        # The committed accounting: from the first swing through the last
        # swing's full 4 seconds, at the Total Poison Damage rate.
        last = max(float(e["time"]) for e in _swings(result))
        assert poison["total_damage"] == pytest.approx(
            (last + 4.0) * 120.0 / 4.0, abs=0.1
        )


class TestMordekaiser:
    """P is a 40% AP on-hit and the Darkness Rise aura from the third hit."""

    def test_the_on_hit_rides_every_swing(self):
        result = _fight("Mordekaiser", ["Rabadon's Deathcap"])
        row = result["breakdown"]["on_hit_ability_passive"]
        assert row["count"] == result["breakdown"]["auto_attacks"]["count"]
        assert row["damage_per_hit"] == pytest.approx(
            0.4 * result["champion_stats"]["ability_power"]
        )

    def test_the_aura_ticks_from_the_third_hit_to_the_fight_end(self):
        result = _fight("Mordekaiser")
        aura = result["breakdown"]["passive_darkness_rise"]
        ticks = [
            float(e["time"])
            for e in result["damage_events"]
            if e.get("source") == "passive_darkness_rise"
        ]
        # Q at 0, an auto at 0, E's claw at 0.5: the third hit is the claw.
        assert ticks == pytest.approx([0.5 + step for step in range(1, 10)])
        assert aura["total_damage"] == pytest.approx(9 * (5.0 + 0.05 * 10_000))

    def test_no_fight_window_means_no_aura(self):
        assert (
            "passive_darkness_rise"
            not in _fight("Mordekaiser", fight_mode="one_rotation")["breakdown"]
        )


class TestXayah:
    """W's frenzy: the swings inside the window are priced at 125% AD."""

    def test_the_feather_scales_the_swings_inside_the_window_only(self):
        result = _fight("Xayah")
        start = _window_start(result, "W")
        attack_damage = result["champion_stats"]["attack_damage"]
        for swing in _swings(result):
            inside = start <= float(swing["time"]) < start + 4.0
            assert swing["damage"] == pytest.approx(
                attack_damage * (1.25 if inside else 1.0)
            )
        assert result["breakdown"]["W"]["total_damage"] == 0.0


class TestThresh:
    """Flay's passive rides every swing; the charged opener rides the first."""

    def test_flay_rides_the_swings(self):
        result = _fight("Thresh")
        swings = result["breakdown"]["auto_attacks"]["count"]
        assert result["breakdown"]["on_hit_ability_E_passive"]["count"] == swings
        assert result["breakdown"]["on_hit_ability_E_passive"]["damage_per_hit"] == (
            pytest.approx(40 * 1.7)
        )
        opener = result["breakdown"]["on_hit_ability_E_opener"]
        assert opener["count"] == 1
        assert opener["damage_per_hit"] == pytest.approx(
            2.1 * result["champion_stats"]["attack_damage"]
        )


class TestPermanentAndWeightedGrants:
    """Qiyana W is innate; Skarner Q is weighted by its mirrored casts."""

    def test_terrashape_holds_in_autos_only(self):
        result = _fight("Qiyana", fight_mode="auto_only")
        unranked = _fight("Qiyana", ability_ranks=dict(_RANKS, W=0))
        assert result["champion_stats"]["bonus_attack_speed"] == pytest.approx(
            unranked["champion_stats"]["bonus_attack_speed"] + 35.0
        )

    def test_shattered_earth_covers_the_fight_when_cast_on_cooldown(self):
        result = _fight("Skarner")
        unranked = _fight("Skarner", ability_ranks=dict(_RANKS, Q=0))
        assert result["champion_stats"]["bonus_attack_speed"] == pytest.approx(
            unranked["champion_stats"]["bonus_attack_speed"] + 40.0
        )
        upheaval = _fight("Skarner", champion_options={"q_variant": 1})
        assert "stat_buff" not in upheaval["breakdown"]["Q"]
        assert upheaval["champion_stats"]["bonus_attack_speed"] == pytest.approx(
            unranked["champion_stats"]["bonus_attack_speed"]
        )
