"""Fight-engine tests for keystone runes (Electrocute, First Strike, PTA).

Electrocute: the engine counts damage instances on the real fight
timeline — one per accepted ability cast plus one per simulated auto
swing — applies the sourced stack window, and gates re-procs behind the
keystone cooldown.

First Strike: the engine sums the post-mitigation damage that sources
with certified event times deal inside the opening buff window and adds
the sourced ratio as bonus true damage, reporting the gold generated.
Uncertified (coarse-timed) sources are excluded and disclosed — the
bonus is a floor, never an estimate.

Press the Attack: only simulated auto swings build stacks; the third
consumes them for leveled adaptive damage and turns on a lasting 8%
amplifier of every certified non-true damage event for the rest of the
fight (the buff only drops out of combat). The triggering swing and the
first proc itself predate the buff and are never amplified.
"""

import pytest

from src.calculator.ability_spec import DamagePart
from src.calculator.resistance import apply_resistance


def _spell(slot="Q", damage=300.0, cooldown=10.0):
    return {
        slot: {
            "name": f"Test {slot}",
            "rank": 1,
            "cooldown": cooldown,
            "damage_type": "magic",
            "total_raw": damage,
            "parts": (DamagePart("magic", damage),),
        }
    }


def _keystone_row(result):
    return result["breakdown"].get("keystone_Electrocute")


ELECTROCUTE_BASE_AT_18 = 240.0  # 60 + 10 × 18, from data/runes.json
ELECTROCUTE_BASE_AT_20 = 260.0


class TestElectrocuteProcs:
    def test_no_keystone_produces_no_row(self, fight, attacker_stats):
        result = fight(attacker_stats(), _spell())
        assert _keystone_row(result) is None

    def test_one_rotation_three_casts_proc_once(self, fight, attacker_stats):
        abilities = {**_spell("Q"), **_spell("W"), **_spell("E")}
        result = fight(
            attacker_stats(),
            abilities,
            keystone="Electrocute",
            target_magic_resistance=100.0,
        )
        row = _keystone_row(result)
        assert row is not None
        assert row["count"] == 1
        assert row["damage_type"] == "magic"
        expected = apply_resistance(ELECTROCUTE_BASE_AT_18, 100.0)
        assert row["total_damage"] == pytest.approx(expected)
        assert result["total_damage"] >= expected

    def test_cooldown_blocks_reproc_within_twenty_seconds(self, fight, attacker_stats):
        # 1.0 attack speed at full uptime: ten instances in ten seconds,
        # but the 20s cooldown allows exactly one proc.
        result = fight(
            attacker_stats(),
            {},
            keystone="Electrocute",
            one_rotation=False,
            fight_duration_seconds=10.0,
            auto_attack_uptime=1.0,
            auto_attacks_only=True,
        )
        row = _keystone_row(result)
        assert row["count"] == 1

    def test_second_proc_after_cooldown_expires(self, fight, attacker_stats):
        # Autos at 0,1,2,... — proc at t=2, cooldown ready at t=22,
        # stacks rebuild on the autos at 22,23,24 → second proc.
        result = fight(
            attacker_stats(),
            {},
            keystone="Electrocute",
            one_rotation=False,
            fight_duration_seconds=30.0,
            auto_attack_uptime=1.0,
            auto_attacks_only=True,
        )
        row = _keystone_row(result)
        assert row["count"] == 2

    def test_slow_instances_never_satisfy_the_window(self, fight, attacker_stats):
        # 0.5 attack speed: instances every 2s — at most two stacks alive
        # inside any 3-second window, so Electrocute never procs.
        result = fight(
            attacker_stats(attack_speed=0.5),
            {},
            keystone="Electrocute",
            one_rotation=False,
            fight_duration_seconds=10.0,
            auto_attack_uptime=1.0,
            auto_attacks_only=True,
        )
        assert _keystone_row(result) is None

    def test_proc_time_recorded_with_strike_delay(self, fight, attacker_stats):
        result = fight(
            attacker_stats(),
            {},
            keystone="Electrocute",
            one_rotation=False,
            fight_duration_seconds=10.0,
            auto_attack_uptime=1.0,
            auto_attacks_only=True,
        )
        events = _keystone_row(result)["damage_events"]
        assert len(events) == 1
        # Third auto lands at t=2; the lightning strikes 0.25s later.
        assert events[0]["time"] == pytest.approx(2.25)

    def test_adaptive_type_uses_physical_when_bonus_ad_dominates(
        self, fight, attacker_stats
    ):
        stats = attacker_stats(bonus_attack_damage=200.0, attack_damage=300.0)
        result = fight(
            stats,
            {},
            keystone="Electrocute",
            one_rotation=False,
            fight_duration_seconds=10.0,
            auto_attack_uptime=1.0,
            auto_attacks_only=True,
            target_armor=100.0,
        )
        row = _keystone_row(result)
        assert row["damage_type"] == "physical"
        expected = apply_resistance(ELECTROCUTE_BASE_AT_18 + 0.10 * 200.0, 100.0)
        assert row["total_damage"] == pytest.approx(expected)

    def test_level_twenty_uses_extended_wiki_leveling(self, fight, attacker_stats):
        result = fight(
            attacker_stats(level=20),
            {},
            keystone="Electrocute",
            one_rotation=False,
            fight_duration_seconds=10.0,
            auto_attack_uptime=1.0,
            auto_attacks_only=True,
            target_magic_resistance=0.0,
        )
        row = _keystone_row(result)
        assert row["total_damage"] == pytest.approx(ELECTROCUTE_BASE_AT_20)

    def test_casts_and_autos_share_one_stack_counter(self, fight, attacker_stats):
        # One cast plus the first two auto swings inside 3s → proc, even
        # though neither source alone reaches three instances quickly.
        result = fight(
            attacker_stats(attack_speed=0.8),
            _spell("Q"),
            keystone="Electrocute",
            one_rotation=False,
            fight_duration_seconds=4.0,
            auto_attack_uptime=1.0,
        )
        row = _keystone_row(result)
        assert row is not None
        assert row["count"] == 1

    def test_zero_damage_casts_never_stack(self, fight, attacker_stats):
        # Two damaging casts plus a zero-damage utility cast: in game the
        # utility cast applies no stack, so Electrocute must not proc.
        buff_ult = {
            "W": {
                "name": "Test buff",
                "rank": 1,
                "cooldown": 60.0,
                "damage_type": "magic",
                "total_raw": 0.0,
                "parts": (),
            }
        }
        abilities = {**_spell("Q"), **buff_ult, **_spell("E")}
        result = fight(attacker_stats(), abilities, keystone="Electrocute")
        assert _keystone_row(result) is None

    def test_unknown_keystone_raises(self, fight, attacker_stats):
        with pytest.raises(ValueError, match="Fake Rune"):
            fight(attacker_stats(), _spell(), keystone="Fake Rune")


def _first_strike_row(result):
    return result["breakdown"].get("keystone_First Strike")


class TestFirstStrike:
    def test_whole_fight_inside_window_amps_all_damage(self, fight, attacker_stats):
        # A 3-second fight sits entirely inside the 3-second buff: every
        # certified point of post-mitigation damage earns the 7% bonus.
        result = fight(
            attacker_stats(),
            _spell("Q", damage=300.0),
            keystone="First Strike",
            fight_duration_seconds=3.0,
        )
        row = _first_strike_row(result)
        assert row is not None
        mitigated_q = 300.0 * 100.0 / (100.0 + 100.0)
        expected_bonus = 0.07 * mitigated_q
        assert row["total_damage"] == pytest.approx(expected_bonus)
        assert row["damage_type"] == "true"
        assert result["total_damage"] == pytest.approx(mitigated_q + expected_bonus)

    def test_gold_reported_with_melee_conversion(self, fight, attacker_stats):
        result = fight(
            attacker_stats(),
            _spell("Q", damage=300.0),
            keystone="First Strike",
            fight_duration_seconds=3.0,
        )
        row = _first_strike_row(result)
        expected_bonus = 0.07 * 150.0
        assert row["gold_generated"] == pytest.approx(10.0 + 0.50 * expected_bonus)

    def test_long_fight_counts_only_damage_inside_the_window(
        self, fight, attacker_stats
    ):
        # Autos land at t = 0, 1, 2, ... — only the swings before the
        # 3-second buff expires (t = 0, 1, 2) earn the 7% bonus.
        result = fight(
            attacker_stats(),
            {},
            keystone="First Strike",
            one_rotation=False,
            fight_duration_seconds=10.0,
            auto_attack_uptime=1.0,
            auto_attacks_only=True,
        )
        row = _first_strike_row(result)
        assert row is not None
        auto_mitigated = 100.0 * 100.0 / (100.0 + 100.0)
        assert row["total_damage"] == pytest.approx(0.07 * 3 * auto_mitigated)
        # Every contributing point of damage came from auto attacks, and
        # the row says so for the auto-vs-ability split.
        assert row["auto_attack_fraction"] == pytest.approx(1.0)

    def test_coarse_timed_sources_are_excluded_and_disclosed(
        self, fight, attacker_stats
    ):
        # W is a DoT: its damage has no certified event times inside the
        # window, so it must not inflate the bonus — excluded, with a
        # note, never prorated.
        dot = {
            "W": {
                "name": "Test DoT",
                "rank": 1,
                "cooldown": 10.0,
                "damage_type": "magic",
                "total_raw": 300.0,
                "parts": (DamagePart("magic", 300.0),),
                "dot_duration": 4.0,
            }
        }
        result = fight(
            attacker_stats(),
            {**_spell("Q", damage=300.0), **dot},
            keystone="First Strike",
            fight_duration_seconds=10.0,
        )
        row = _first_strike_row(result)
        mitigated_q = 300.0 * 100.0 / (100.0 + 100.0)
        assert row["total_damage"] == pytest.approx(0.07 * mitigated_q)
        assert any("First Strike" in note and "W" in note for note in result["notes"])

    def test_all_coarse_fight_still_discloses_the_exclusion(
        self, fight, attacker_stats
    ):
        # Every damage source is a DoT: nothing is certified in-window,
        # so there is no bonus row — but silence would be dishonest. The
        # exclusion note (and the activation itself) must still surface.
        dot = {
            "W": {
                "name": "Test DoT",
                "rank": 1,
                "cooldown": 10.0,
                "damage_type": "magic",
                "total_raw": 300.0,
                "parts": (DamagePart("magic", 300.0),),
                "dot_duration": 4.0,
            }
        }
        result = fight(
            attacker_stats(),
            dot,
            keystone="First Strike",
            fight_duration_seconds=3.0,
        )
        assert _first_strike_row(result) is None
        assert any("First Strike" in note and "W" in note for note in result["notes"])

    def test_coupled_auto_stream_sources_are_not_certified_in_window(
        self, fight, attacker_stats
    ):
        # Shen-class abilities place their row damage at cast time but
        # actually deal it across later auto swings — the engine cannot
        # certify how much lands inside the window, so the source is
        # excluded, matching what timeline_coverage reports for it.
        coupled = {
            "Q": {
                "name": "Test empowered swings",
                "rank": 1,
                "cooldown": 10.0,
                "damage_type": "magic",
                "total_raw": 300.0,
                "parts": (DamagePart("magic", 300.0),),
                "requires_auto_timeline_coupling": True,
            }
        }
        result = fight(
            attacker_stats(),
            coupled,
            keystone="First Strike",
            one_rotation=False,
            fight_duration_seconds=10.0,
            auto_attack_uptime=1.0,
        )
        row = _first_strike_row(result)
        assert row is not None
        # Only the certified auto swings at t = 0, 1, 2 contribute.
        auto_mitigated = 100.0 * 100.0 / (100.0 + 100.0)
        assert row["total_damage"] == pytest.approx(0.07 * 3 * auto_mitigated)
        assert any("First Strike" in note and "Q" in note for note in result["notes"])

    def test_gold_uses_ranged_conversion_for_ranged_attackers(
        self, fight, attacker_stats
    ):
        result = fight(
            attacker_stats(is_melee=False),
            _spell("Q", damage=300.0),
            keystone="First Strike",
            fight_duration_seconds=3.0,
        )
        row = _first_strike_row(result)
        expected_bonus = 0.07 * 150.0
        assert row["gold_generated"] == pytest.approx(10.0 + 0.35 * expected_bonus)


def _pta_row(result):
    return result["breakdown"].get("keystone_Press the Attack")


def _pta_amp_row(result):
    return result["breakdown"].get("keystone_Press the Attack amp")


PTA_BASE_AT_18 = 160.0  # from data/runes.json leveling
AUTO_MITIGATED = 100.0 * 100.0 / (100.0 + 100.0)  # 100 AD into 100 armor


class TestPressTheAttackProcs:
    def test_third_auto_procs_the_leveled_adaptive_damage(self, fight, attacker_stats):
        # Autos at t = 0, 1, 2: the third swing consumes the stacks. The
        # 6s cooldown leaves only two stacks (t = 8, 9) before fight end.
        result = fight(
            attacker_stats(),
            {},
            keystone="Press the Attack",
            one_rotation=False,
            fight_duration_seconds=10.0,
            auto_attack_uptime=1.0,
            auto_attacks_only=True,
        )
        row = _pta_row(result)
        assert row is not None
        assert row["count"] == 1
        assert row["damage_type"] == "magic"  # no bonus AD, no AP → tie
        expected = apply_resistance(PTA_BASE_AT_18, 100.0)
        assert row["total_damage"] == pytest.approx(expected)
        events = row["damage_events"]
        assert len(events) == 1
        assert events[0]["time"] == pytest.approx(2.0)

    def test_reprocs_after_each_cooldown(self, fight, attacker_stats):
        # Procs at t = 2, then stacks rebuild at 8, 9, 10 → proc at 10,
        # then 16, 17, 18 → proc at 18.
        result = fight(
            attacker_stats(),
            {},
            keystone="Press the Attack",
            one_rotation=False,
            fight_duration_seconds=20.0,
            auto_attack_uptime=1.0,
            auto_attacks_only=True,
        )
        row = _pta_row(result)
        assert row["count"] == 3
        times = [event["time"] for event in row["damage_events"]]
        assert times == [pytest.approx(2.0), pytest.approx(10.0), pytest.approx(18.0)]
        # Whether stacks build during the 6s per-target cooldown is
        # undocumented on the wiki; the engine assumes they do not,
        # which can only delay re-procs — and says so.
        assert any(
            "Press the Attack" in note and "cooldown" in note
            for note in result["notes"]
        )

    def test_stacks_expire_between_slow_swings(self, fight, attacker_stats):
        # 0.25 attack speed: swings every 4s — each stack expires exactly
        # as the next swing lands, so three never coexist.
        result = fight(
            attacker_stats(attack_speed=0.25),
            {},
            keystone="Press the Attack",
            one_rotation=False,
            fight_duration_seconds=20.0,
            auto_attack_uptime=1.0,
            auto_attacks_only=True,
        )
        assert _pta_row(result) is None
        assert _pta_amp_row(result) is None

    def test_ability_casts_never_stack(self, fight, attacker_stats):
        # Three damaging casts proc Electrocute but not Press the Attack:
        # only basic attacks apply its stacks. A selected keystone that
        # never fires must say so instead of silently contributing zero.
        abilities = {**_spell("Q"), **_spell("W"), **_spell("E")}
        result = fight(attacker_stats(), abilities, keystone="Press the Attack")
        assert _pta_row(result) is None
        assert _pta_amp_row(result) is None
        assert any(
            "Press the Attack" in note and "never procced" in note
            for note in result["notes"]
        )

    def test_adaptive_type_uses_physical_when_bonus_ad_dominates(
        self, fight, attacker_stats
    ):
        result = fight(
            attacker_stats(bonus_attack_damage=200.0, attack_damage=300.0),
            {},
            keystone="Press the Attack",
            one_rotation=False,
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
            auto_attacks_only=True,
            target_armor=100.0,
        )
        row = _pta_row(result)
        assert row["damage_type"] == "physical"
        # Pure leveled adaptive damage: stats pick the type, not the amount.
        assert row["total_damage"] == pytest.approx(
            apply_resistance(PTA_BASE_AT_18, 100.0)
        )


class TestPressTheAttackAmp:
    def test_amp_covers_swings_after_the_trigger_until_fight_end(
        self, fight, attacker_stats
    ):
        # Proc at t = 2: the triggering swing and the swings before it
        # earn nothing; the swings at t = 3..9 each gain 8%.
        result = fight(
            attacker_stats(),
            {},
            keystone="Press the Attack",
            one_rotation=False,
            fight_duration_seconds=10.0,
            auto_attack_uptime=1.0,
            auto_attacks_only=True,
        )
        row = _pta_amp_row(result)
        assert row is not None
        expected_amp = 0.08 * 7 * AUTO_MITIGATED
        assert row["total_damage"] == pytest.approx(expected_amp)
        assert row["damage_by_type"] == {"physical": pytest.approx(expected_amp)}
        proc_mitigated = apply_resistance(PTA_BASE_AT_18, 100.0)
        assert result["total_damage"] == pytest.approx(
            10 * AUTO_MITIGATED + proc_mitigated + expected_amp
        )

    def test_later_procs_are_amplified_but_the_first_is_not(
        self, fight, attacker_stats
    ):
        # Procs at t = 2, 10, 18: the buff from the first proc amplifies
        # the later two procs' adaptive damage alongside the autos.
        result = fight(
            attacker_stats(),
            {},
            keystone="Press the Attack",
            one_rotation=False,
            fight_duration_seconds=20.0,
            auto_attack_uptime=1.0,
            auto_attacks_only=True,
        )
        row = _pta_amp_row(result)
        proc_mitigated = apply_resistance(PTA_BASE_AT_18, 100.0)
        expected_physical = 0.08 * 17 * AUTO_MITIGATED  # swings at t = 3..19
        expected_magic = 0.08 * 2 * proc_mitigated  # procs at t = 10, 18
        assert row["damage_by_type"]["physical"] == pytest.approx(expected_physical)
        assert row["damage_by_type"]["magic"] == pytest.approx(expected_magic)
        assert row["total_damage"] == pytest.approx(expected_physical + expected_magic)

    def test_true_damage_is_never_amplified(self, fight, attacker_stats):
        # A true-damage cast lands after the proc; the buff amplifies
        # everything except true damage, so only the autos contribute.
        true_spell = {
            "Q": {
                "name": "Test true nuke",
                "rank": 1,
                "cooldown": 5.0,
                "damage_type": "true",
                "total_raw": 300.0,
                "parts": (DamagePart("true", 300.0),),
            }
        }
        result = fight(
            attacker_stats(),
            true_spell,
            keystone="Press the Attack",
            one_rotation=False,
            fight_duration_seconds=10.0,
            auto_attack_uptime=1.0,
        )
        row = _pta_amp_row(result)
        assert "true" not in row["damage_by_type"]
        assert row["total_damage"] == pytest.approx(0.08 * 7 * AUTO_MITIGATED)

    def test_coarse_timed_sources_are_excluded_and_disclosed(
        self, fight, attacker_stats
    ):
        # A DoT's damage has no certified event times, so it must not
        # inflate the amp — excluded, with a note, never prorated.
        dot = {
            "W": {
                "name": "Test DoT",
                "rank": 1,
                "cooldown": 10.0,
                "damage_type": "magic",
                "total_raw": 300.0,
                "parts": (DamagePart("magic", 300.0),),
                "dot_duration": 4.0,
            }
        }
        result = fight(
            attacker_stats(),
            dot,
            keystone="Press the Attack",
            one_rotation=False,
            fight_duration_seconds=10.0,
            auto_attack_uptime=1.0,
        )
        row = _pta_amp_row(result)
        assert row["total_damage"] == pytest.approx(0.08 * 7 * AUTO_MITIGATED)
        assert any(
            "Press the Attack" in note and "W" in note for note in result["notes"]
        )
