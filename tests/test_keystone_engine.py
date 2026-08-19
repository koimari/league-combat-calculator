"""Fight-engine tests for all seventeen keystone runes.

Each keystone declares which of the fight's event streams it watches and
what it books; the engine owns the streams. The five that book damage on a
stream are asserted here against the numbers the cache states, and the
eight that book none are asserted to leave the total bit-identical while
publishing the receipt that says why.

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

Arcane Comet: every damaging ability cast hurls a comet when the rune
is off its leveled cooldown (20s at 1 → 8s at 18). Basic attacks never
trigger it, and DoT ticks are not cast instances — damage over time
neither triggers nor extends anything, unlike the Liandry's burn
family. Damage is priced at the assumed 375-unit flight (+50%), landing
0.8s after the cast.
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


def _comet_row(result):
    return result["breakdown"].get("keystone_Arcane Comet")


# 100 base at 18, ×1.5 for the assumed 375-unit flight, into 100 MR.
COMET_AMPED_AT_18 = 150.0
COMET_MITIGATED_AT_18 = apply_resistance(COMET_AMPED_AT_18, 100.0)


class TestArcaneCometProcs:
    def test_single_cast_procs_one_comet_after_the_landing_delay(
        self, fight, attacker_stats
    ):
        result = fight(attacker_stats(), _spell("Q"), keystone="Arcane Comet")
        row = _comet_row(result)
        assert row is not None
        assert row["count"] == 1
        assert row["damage_type"] == "magic"
        assert row["total_damage"] == pytest.approx(COMET_MITIGATED_AT_18)
        cast_time = result["cast_timeline"][0]["time"]
        assert row["damage_events"][0]["time"] == pytest.approx(cast_time + 0.8)

    def test_casts_inside_the_cooldown_are_gated(self, fight, attacker_stats):
        # Three casts land within ~3s of each other; the level-18 comet
        # cooldown is 8s, so only the first cast hurls a comet.
        abilities = {**_spell("Q"), **_spell("W"), **_spell("E")}
        result = fight(attacker_stats(), abilities, keystone="Arcane Comet")
        assert _comet_row(result)["count"] == 1

    def test_every_cast_procs_when_ability_cooldown_exceeds_the_runes(
        self, fight, attacker_stats
    ):
        # Q recasts every 10s; the 8s comet cooldown is always ready.
        result = fight(
            attacker_stats(),
            _spell("Q", cooldown=10.0),
            keystone="Arcane Comet",
            one_rotation=False,
            fight_duration_seconds=25.0,
        )
        casts = len(result["cast_timeline"])
        assert casts >= 2
        assert _comet_row(result)["count"] == casts

    def test_cooldown_scales_with_level(self, fight, attacker_stats):
        # The same fight at level 1 runs a 20s comet cooldown: of the
        # casts at ~0, 10, 20, the middle one is gated.
        result = fight(
            attacker_stats(level=1),
            _spell("Q", cooldown=10.0),
            keystone="Arcane Comet",
            one_rotation=False,
            fight_duration_seconds=25.0,
        )
        assert len(result["cast_timeline"]) == 3
        assert _comet_row(result)["count"] == 2

    def test_autos_never_trigger_and_the_note_says_so(self, fight, attacker_stats):
        result = fight(
            attacker_stats(),
            {},
            keystone="Arcane Comet",
            one_rotation=False,
            fight_duration_seconds=10.0,
            auto_attack_uptime=1.0,
            auto_attacks_only=True,
        )
        assert _comet_row(result) is None
        assert any(
            "Arcane Comet" in note and "never procced" in note
            for note in result["notes"]
        )

    def test_zero_damage_casts_never_trigger(self, fight, attacker_stats):
        buff = {
            "W": {
                "name": "Test buff",
                "rank": 1,
                "cooldown": 60.0,
                "damage_type": "magic",
                "total_raw": 0.0,
                "parts": (),
            }
        }
        result = fight(attacker_stats(), buff, keystone="Arcane Comet")
        assert _comet_row(result) is None

    def test_dot_ticks_are_not_cast_instances(self, fight, attacker_stats):
        # A DoT deals damage across 4s, but only its cast hurls a comet:
        # ticks neither trigger nor extend anything (unlike Liandry's).
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
            keystone="Arcane Comet",
            fight_duration_seconds=10.0,
        )
        assert _comet_row(result)["count"] == 1

    def test_adaptive_type_uses_physical_when_bonus_ad_dominates(
        self, fight, attacker_stats
    ):
        result = fight(
            attacker_stats(bonus_attack_damage=200.0, attack_damage=300.0),
            _spell("Q"),
            keystone="Arcane Comet",
            target_armor=100.0,
        )
        row = _comet_row(result)
        assert row["damage_type"] == "physical"
        # (100 base + 10% × 200 bonus AD) × 1.5 distance amp, into armor.
        assert row["total_damage"] == pytest.approx(
            apply_resistance((100.0 + 0.10 * 200.0) * 1.5, 100.0)
        )

    def test_assumed_flight_distance_is_disclosed(self, fight, attacker_stats):
        result = fight(attacker_stats(), _spell("Q"), keystone="Arcane Comet")
        assert any("Arcane Comet" in note and "375" in note for note in result["notes"])


def _row(result, keystone):
    return result["breakdown"].get(f"keystone_{keystone}")


def _notes(result, keystone):
    return [note for note in result["notes"] if note.startswith(keystone)]


def _autos(fight, attacker_stats, keystone, seconds=10.0, **overrides):
    """A pure auto-attack fight: swings at t = 0, 1, 2, ... at 1.0 AS."""
    return fight(
        attacker_stats(**overrides.pop("stats", {})),
        overrides.pop("abilities", {}),
        keystone=keystone,
        one_rotation=False,
        fight_duration_seconds=seconds,
        auto_attack_uptime=1.0,
        auto_attacks_only=not overrides.pop("with_abilities", False),
        **overrides,
    )


class TestSummonAery:
    """Aery watches the same instance stream Electrocute does, gated by flight.

    Ten swings at t = 0..9 with a 3.45s round trip send her at t = 0, 4 and
    8; each pounce lands 0.45s later.
    """

    def test_the_round_trip_gates_the_pounces(self, fight, attacker_stats):
        result = _autos(fight, attacker_stats, "Summon Aery")
        row = _row(result, "Summon Aery")
        assert row["count"] == 3
        times = [event["time"] for event in row["damage_events"]]
        assert times == [pytest.approx(0.45), pytest.approx(4.45), pytest.approx(8.45)]

    def test_damage_is_the_leveled_adaptive_pounce(self, fight, attacker_stats):
        result = _autos(fight, attacker_stats, "Summon Aery")
        row = _row(result, "Summon Aery")
        assert row["damage_type"] == "magic"
        assert row["total_damage"] == pytest.approx(3 * apply_resistance(50.0, 100.0))

    def test_ability_casts_send_her_out_too(self, fight, attacker_stats):
        result = fight(attacker_stats(), _spell("Q"), keystone="Summon Aery")
        assert _row(result, "Summon Aery")["count"] == 1

    def test_the_assumption_and_the_withheld_shield_reach_the_notes(
        self, fight, attacker_stats
    ):
        result = _autos(fight, attacker_stats, "Summon Aery")
        notes = _notes(result, "Summon Aery")
        assert any("3.45s" in note for note in notes)
        assert any("shield is withheld" in note for note in notes)

    def test_a_fight_with_no_instances_says_she_never_procced(
        self, fight, attacker_stats
    ):
        result = fight(attacker_stats(), {}, keystone="Summon Aery")
        assert _row(result, "Summon Aery") is None
        assert any("never procced" in note for note in _notes(result, "Summon Aery"))


class TestHailOfBlades:
    def test_one_empowered_swing_per_cached_cooldown(self, fight, attacker_stats):
        ten = _autos(fight, attacker_stats, "Hail of Blades", seconds=10.0)
        twenty = _autos(fight, attacker_stats, "Hail of Blades", seconds=20.0)
        assert _row(ten, "Hail of Blades")["count"] == 1
        assert _row(twenty, "Hail of Blades")["count"] == 2
        assert [
            event["time"] for event in _row(twenty, "Hail of Blades")["damage_events"]
        ] == [pytest.approx(0.0), pytest.approx(10.0)]

    def test_the_bonus_damage_is_true_and_unmitigated(self, fight, attacker_stats):
        result = _autos(fight, attacker_stats, "Hail of Blades")
        row = _row(result, "Hail of Blades")
        assert row["damage_type"] == "true"
        assert row["total_damage"] == pytest.approx(20.0)  # 4 + (20-4)/17 × 17

    def test_abilities_never_trigger_it(self, fight, attacker_stats):
        result = fight(attacker_stats(), _spell("Q"), keystone="Hail of Blades")
        assert _row(result, "Hail of Blades") is None
        assert any("never procced" in note for note in _notes(result, "Hail of Blades"))

    def test_the_withheld_attack_speed_is_disclosed_either_way(
        self, fight, attacker_stats
    ):
        result = fight(attacker_stats(), _spell("Q"), keystone="Hail of Blades")
        assert any(
            "attack speed" in note and "withheld" in note
            for note in _notes(result, "Hail of Blades")
        )


class TestGraspOfTheUndying:
    def test_exactly_one_proc_for_a_share_of_the_holders_maximum_health(
        self, fight, attacker_stats
    ):
        result = _autos(fight, attacker_stats, "Grasp of the Undying", seconds=20.0)
        row = _row(result, "Grasp of the Undying")
        assert row["count"] == 1
        assert row["damage_events"][0]["time"] == pytest.approx(0.0)
        # 3.5% of the melee holder's 2000 maximum health, into 100 MR.
        assert row["total_damage"] == pytest.approx(apply_resistance(70.0, 100.0))

    def test_a_ranged_holder_uses_the_ranged_share(self, fight, attacker_stats):
        result = _autos(
            fight,
            attacker_stats,
            "Grasp of the Undying",
            stats={"is_melee": False},
        )
        assert _row(result, "Grasp of the Undying")["total_damage"] == pytest.approx(
            apply_resistance(0.014 * 2000.0, 100.0)
        )

    def test_the_withheld_re_procs_heal_and_health_are_disclosed(
        self, fight, attacker_stats
    ):
        result = _autos(fight, attacker_stats, "Grasp of the Undying")
        notes = _notes(result, "Grasp of the Undying")
        assert any("floor of one" in note for note in notes)
        assert any("heal" in note and "withheld" in note for note in notes)


class TestLethalTempo:
    def test_swings_past_maximum_stacks_fire_a_bolt(self, fight, attacker_stats):
        # Ten swings at t = 0..9: the first six build stacks, the swings at
        # t = 6, 7, 8, 9 are empowered.
        result = _autos(fight, attacker_stats, "Lethal Tempo")
        row = _row(result, "Lethal Tempo")
        assert row["count"] == 4
        assert [event["time"] for event in row["damage_events"]] == [
            pytest.approx(t) for t in (6.0, 7.0, 8.0, 9.0)
        ]
        # 9 + (30-9)/17 × 17 = 30 melee adaptive at level 18, into 100 MR.
        assert row["total_damage"] == pytest.approx(4 * apply_resistance(30.0, 100.0))

    def test_the_bolt_grows_with_the_builds_bonus_attack_speed(
        self, fight, attacker_stats
    ):
        # The keystone's own attack speed is withheld, so the multiplier
        # reads the build's: 1% more damage per 1% bonus attack speed.
        result = _autos(
            fight,
            attacker_stats,
            "Lethal Tempo",
            stats={"bonus_attack_speed": 50.0},
        )
        row = _row(result, "Lethal Tempo")
        assert row["total_damage"] == pytest.approx(
            row["count"] * apply_resistance(30.0 * 1.5, 100.0)
        )

    def test_six_swings_never_reach_the_empowered_stream(self, fight, attacker_stats):
        result = _autos(fight, attacker_stats, "Lethal Tempo", seconds=6.0)
        assert _row(result, "Lethal Tempo") is None
        assert any("never procced" in note for note in _notes(result, "Lethal Tempo"))


class TestDeathfireTouch:
    def test_one_burn_tick_per_damaging_cast(self, fight, attacker_stats):
        result = fight(attacker_stats(), _spell("Q"), keystone="Deathfire Touch")
        row = _row(result, "Deathfire Touch")
        assert row["count"] == 1
        assert row["damage_type"] == "magic"
        # 3/2 + ((12/2)-(3/2))/17 × 17 = 6 magic per tick at level 18.
        assert row["total_damage"] == pytest.approx(apply_resistance(6.0, 100.0))
        cast_time = result["cast_timeline"][0]["time"]
        assert row["damage_events"][0]["time"] == pytest.approx(cast_time + 0.5)

    def test_every_damaging_cast_burns_again(self, fight, attacker_stats):
        abilities = {**_spell("Q"), **_spell("W"), **_spell("E")}
        result = fight(attacker_stats(), abilities, keystone="Deathfire Touch")
        assert _row(result, "Deathfire Touch")["count"] == 3

    def test_autos_never_burn_and_the_floor_is_disclosed(self, fight, attacker_stats):
        result = _autos(fight, attacker_stats, "Deathfire Touch")
        assert _row(result, "Deathfire Touch") is None
        notes = _notes(result, "Deathfire Touch")
        assert any("never procced" in note for note in notes)
        assert any("floor of one per cast" in note for note in notes)


class TestKeystonesThatBookNoDamage:
    """Eight keystones contribute nothing and each says so in its own words."""

    @pytest.mark.parametrize(
        "keystone,phrase",
        [
            ("Unsealed Spellbook", "deals no damage in any fight"),
            ("Glacial Augment", "deals no damage in any fight"),
            ("Stormraider's Surge", "deals no damage in any fight"),
            ("Conqueror", "is not priced"),
            ("Fleet Footwork", "is not priced"),
            ("Aftershock", "is not priced"),
            ("Guardian", "is not priced"),
            ("Dark Harvest", "is not priced"),
        ],
    )
    def test_the_total_is_unmoved_and_the_receipt_is_published(
        self, fight, attacker_stats, keystone, phrase
    ):
        baseline = _autos(fight, attacker_stats, "")
        result = _autos(fight, attacker_stats, keystone)
        assert result["total_damage"] == pytest.approx(baseline["total_damage"])
        assert not [key for key in result["breakdown"] if key.startswith("keystone")]
        assert any(phrase in note for note in _notes(result, keystone))

    def test_stormraiders_discloses_its_swiftmarch_caveat(self, fight, attacker_stats):
        result = _autos(fight, attacker_stats, "Stormraider's Surge")
        assert any(
            "Swiftmarch" in note for note in _notes(result, "Stormraider's Surge")
        )


def test_a_keystone_that_never_procs_says_so(fight, attacker_stats):
    """Electrocute's silent zero is closed with the rest of them."""
    result = _autos(fight, attacker_stats, "Electrocute", stats={"attack_speed": 0.5})
    assert _keystone_row(result) is None
    assert any("never procced" in note for note in _notes(result, "Electrocute"))
