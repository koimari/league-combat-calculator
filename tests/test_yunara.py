"""Yunara: the kit rides the swing stream, and the reviewed crowd control.

Cultivation of Spirit's passive is an on-hit on every basic attack, Unleash
is a 5-second attack-speed window whose swings carry a second on-hit, Vow of
the First Lands rides each critical strike, and Arc of Judgment slows in
both its base and Transcendent forms.
"""

import math
from itertools import pairwise

import pytest

from src.calculator.calculate import calculate_payload
from src.calculator.champions import yunara
from src.calculator.damage import calculate_fight_damage
from src.calculator.data_fetcher import get_champion
from src.calculator.fight.config import FightConfig
from tests import cc_review

_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_UNLEASH_WINDOW = 5.0
_FIGHT_SECONDS = 10.0


def _fight(items: list[str] | None = None, **overrides) -> dict:
    """A deterministic level-18 timed fight, autos included, against 0 resists."""
    request = {
        "champion": "Yunara",
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


def _swing_times(result: dict) -> list[float]:
    return [
        event["time"]
        for event in result["damage_events"]
        if event["source"] == "auto_attacks"
    ]


class TestCultivationOfSpiritRidesTheSwingStream:
    """Q is two on-hits and a window, never a cast that deals damage."""

    def test_the_passive_on_hit_lands_on_every_swing(self):
        result = _fight()
        passive = result["breakdown"]["on_hit_ability_Q_passive"]
        assert passive["count"] == result["breakdown"]["auto_attacks"]["count"]
        assert passive["damage_per_hit"] == pytest.approx(25.0)  # rank 5, 0 AP
        assert {
            event["damage_type"]
            for event in result["damage_events"]
            if event["source"] == "on_hit_ability_Q_passive"
        } == {"magic"}

    def test_the_passive_scales_with_ability_power(self):
        result = _fight(["Rabadon's Deathcap"])
        ap = result["champion_stats"]["ability_power"]
        assert ap > 0
        per_hit = result["breakdown"]["on_hit_ability_Q_passive"]["damage_per_hit"]
        assert per_hit == pytest.approx(25.0 + 0.20 * ap)

    def test_q_is_a_steroid_row_with_no_direct_damage(self):
        result = _fight()
        assert result["breakdown"]["Q"]["total_damage"] == 0.0
        abilities = yunara.parse_abilities(get_champion("Yunara"), 18, 0.0, _RANKS)
        assert "applies_item_on_hits" not in abilities["Q"]
        assert abilities["Q"]["stat_buff"] == {"bonus_attack_speed": 60.0}
        assert abilities["Q"]["auto_attack_override"] == {
            "active_duration": _UNLEASH_WINDOW
        }

    def test_unleash_swings_carry_the_active_on_hit(self):
        result = _fight()
        in_window = sum(time < _UNLEASH_WINDOW for time in _swing_times(result))
        active = result["breakdown"]["on_hit_ability_Q"]
        assert active["count"] == in_window
        assert 0 < in_window < result["breakdown"]["auto_attacks"]["count"]
        assert active["damage_per_hit"] == pytest.approx(25.0)

    def test_the_window_counts_the_autos_per_phase(self):
        unranked = _fight(ability_ranks=dict(_RANKS, Q=0))
        base_as = unranked["champion_stats"]["attack_speed"]
        ratio = unranked["champion_stats"]["attack_speed_ratio"]
        buffed_as = base_as + ratio * 0.60

        expected = math.floor(buffed_as * _UNLEASH_WINDOW) + math.floor(
            base_as * (_FIGHT_SECONDS - _UNLEASH_WINDOW)
        )
        assert _fight()["breakdown"]["auto_attacks"]["count"] == expected
        assert "on_hit_ability_Q_passive" not in unranked["breakdown"]

    def test_transcendent_state_keeps_unleash_up_for_the_whole_fight(self):
        result = _fight(champion_options={"r_transcendent": True})
        unranked = _fight(ability_ranks=dict(_RANKS, Q=0))
        base_as = unranked["champion_stats"]["attack_speed"]
        ratio = unranked["champion_stats"]["attack_speed_ratio"]

        assert result["breakdown"]["auto_attacks"]["count"] == math.floor(
            (base_as + ratio * 0.60) * _FIGHT_SECONDS
        )
        passive = result["breakdown"]["on_hit_ability_Q_passive"]
        assert passive["damage_per_hit"] == pytest.approx(50.0)  # combined row
        assert passive["count"] == result["breakdown"]["auto_attacks"]["count"]
        assert "on_hit_ability_Q" not in result["breakdown"]

    def test_rageblade_stacks_keep_climbing_through_the_window(self):
        """The build's own ramp is walked through the window, not dropped."""
        plain = _fight()
        rageblade = _fight(["Guinsoo's Rageblade"])
        times = _swing_times(rageblade)
        in_window = [t for t in times if t < _UNLEASH_WINDOW]
        gaps = [b - a for a, b in pairwise(in_window)]

        assert rageblade["breakdown"]["auto_attacks"]["count"] > (
            plain["breakdown"]["auto_attacks"]["count"]
        )
        assert gaps[:4] == sorted(gaps[:4], reverse=True)  # a stack per swing
        assert gaps[0] > gaps[3]
        assert rageblade["breakdown"]["on_hit_ability_Q"]["count"] == len(in_window)

    def test_phantom_hits_apply_the_passive_again(self):
        result = _fight(["Guinsoo's Rageblade"])
        passive = result["breakdown"]["on_hit_ability_Q_passive"]
        autos = result["breakdown"]["auto_attacks"]["count"]
        assert passive["count"] > autos


class TestVowOfTheFirstLands:
    """Each critical strike deals a share of its raw damage again as magic."""

    # Round stats so the wiki arithmetic is checkable by eye.
    _STATS = {
        "armor_penetration_bonus_percent": 0.0,
        "lethality": 0.0,
        "move_speed": 0.0,
        "omnivamp_percent": 0.0,
        "resource_regen_per_second": 0.0,
        "ultimate_haste": 0.0,
        "attack_damage": 200.0,
        "base_attack_damage": 100.0,
        "bonus_attack_damage": 100.0,
        "ability_power": 100.0,
        "attack_speed": 1.0,
        "attack_speed_ratio": 0.65,
        "critical_strike_chance": 50.0,
        "ability_haste": 0.0,
        "basic_ability_haste": 0.0,
        "magic_penetration_flat": 0.0,
        "magic_penetration_percent": 0.0,
        "flat_armor_penetration": 0.0,
        "armor_penetration_percent": 0.0,
        "max_mana": 500.0,
        "bonus_mana": 0.0,
        "health": 2000.0,
        "bonus_health": 0.0,
        "is_melee": False,
        "level": 18,
    }

    def _rider_fight(self, *, crit_chance: float, deterministic: bool) -> dict:
        stats = dict(self._STATS, critical_strike_chance=crit_chance)
        abilities = yunara.parse_abilities(
            get_champion("Yunara"),
            18,
            stats["ability_power"],
            _RANKS,
            champion_stats=stats,
        )
        return calculate_fight_damage(
            stats,
            {"passive": abilities["passive"]},
            [],
            FightConfig(
                target_health=10_000.0,
                target_armor=0.0,
                target_magic_resistance=0.0,
                fight_duration_seconds=8.0,
                auto_attack_uptime=1.0,
                one_rotation=False,
                deterministic=deterministic,
            ),
        )

    def test_the_binary_ratio_agrees_with_the_wiki_text(self):
        """ "10% (+ 10% per 100 AP)": 0.10 + 0.001 x AP."""
        base, per_ap = yunara._P_CRIT_MAGIC_BASE, yunara._P_CRIT_MAGIC_PER_AP
        assert (base, per_ap) == pytest.approx((0.10, 0.001))
        passive = yunara.parse_abilities(
            get_champion("Yunara"), 18, 100.0, _RANKS, champion_stats=self._STATS
        )["passive"]
        assert passive["critical_strike_magic_ratio"] == pytest.approx(0.20)
        assert passive["total_raw"] == 0.0

    def test_the_expected_share_of_each_crit_is_paid_as_magic(self):
        """8 autos at 200 AD, 50% crit, x2.0: 8 x 0.5 x 400 x 20% = 320."""
        row = self._rider_fight(crit_chance=50.0, deterministic=True)["breakdown"][
            "auto_attacks_critical_magic"
        ]
        assert row["damage_type"] == "magic"
        assert row["count"] == 8
        assert row["total_damage"] == pytest.approx(320.0)

    def test_a_rolled_fight_pays_on_the_crits_it_rolled(self):
        result = self._rider_fight(crit_chance=100.0, deterministic=False)
        row = result["breakdown"]["auto_attacks_critical_magic"]
        assert row["count"] == result["breakdown"]["auto_attacks"]["num_crits"] == 8
        assert row["total_damage"] == pytest.approx(8 * 400.0 * 0.20)

    def test_no_critical_strike_chance_pays_nothing(self):
        breakdown = self._rider_fight(crit_chance=0.0, deterministic=True)["breakdown"]
        assert "auto_attacks_critical_magic" not in breakdown


class TestReviewedCrowdControl:
    """Yunara's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Yunara")
        assert yunara.MODULE_CC == {
            "Q": "none",
            "W": "slow",
            "P": "none",
            "E": "none",
            "R": "none",
        }
        assert yunara.parse_abilities.cc_kinds == yunara.MODULE_CC
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        # Both W forms slow, so one slot-wide kind covers r_transcendent.
        w_text = cc_review.slot_text(data, "W")
        assert "slows them by 99% decaying over 1.5 seconds" in w_text
        assert "slows them by 99% decaying over 1 second" in w_text

    def test_the_non_damaging_slots_stay_absent(self):
        """E is a dash, R is the Transcendent State buff shell."""
        assert yunara.MODULE_CC["E"] == "none"
        assert yunara.MODULE_CC["R"] == "none"
        assert (
            cc_review.control_words(cc_review.slot_text(cc_review.kit("Yunara"), "E"))
            == []
        )

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Yunara") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Yunara")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
