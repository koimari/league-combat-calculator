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

Summon Aery: damaging ability casts signal one adaptive damage packet after
the sourced 0.45s flight. The sourced two-second linger gates the next
signal.

Dark Harvest: direct timestamped damage can trigger below 50% maximum health.
The proc lands after 1.75s, and each completed reap adds one Soul to later
procs.

Aftershock: an authored immobilize schedules one delayed shockwave, then
respects the sourced cooldown.

Grasp: four timed combat stacks empower the next basic attack, while the
same receipt carries its self-heal and permanent health gain.

Hail of Blades: the first basic attack activates a two-stack attack-speed
window, and the same shared swing schedule carries its true-damage rider.
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


def _aftershock_row(result):
    return result["breakdown"].get("keystone_Aftershock")


def _deathfire_row(result):
    return result["breakdown"].get("keystone_Deathfire Touch")


ELECTROCUTE_BASE_AT_18 = 240.0  # 60 + 10 × 18, from data/runes.json
ELECTROCUTE_BASE_AT_20 = 260.0


class TestDeathfireTouch:
    def test_typed_burn_ticks_and_amplified_tail(self, fight, attacker_stats):
        abilities = {
            "Q": {
                "name": "Deathfire test spell",
                "cooldown": 10.0,
                "damage_type": "magic",
                "total_raw": 100.0,
                "deathfire_category": "spell_damage",
                "parts": (DamagePart("magic", 100.0),),
            }
        }
        result = fight(
            attacker_stats(bonus_attack_damage=100.0, ability_power=100.0),
            abilities,
            keystone="Deathfire Touch",
            target_magic_resistance=0.0,
        )

        row = _deathfire_row(result)
        assert row is not None
        assert row["total_damage"] == pytest.approx(110.1875)
        assert len(row["trigger_events"]) == 1
        assert row["trigger_events"][0]["category"] == "spell_damage"
        assert row["count"] == 8
        assert row["amplified_tick_count"] == 3
        assert all(event["damage_type"] == "magic" for event in row["damage_events"])

    def test_persistent_damage_refreshes_each_authored_tick(
        self, fight, attacker_stats
    ):
        abilities = {
            "Q": {
                "name": "Persistent test spell",
                "cooldown": 10.0,
                "damage_type": "magic",
                "total_raw": 300.0,
                "deathfire_category": "persistent_damage",
                "parts": (
                    DamagePart(
                        "magic", 100.0, count=3, time_offset=0.0, hit_interval=0.5
                    ),
                ),
            }
        }
        result = fight(
            attacker_stats(),
            abilities,
            keystone="Deathfire Touch",
            target_magic_resistance=0.0,
        )

        row = _deathfire_row(result)
        assert row is not None
        assert len(row["trigger_events"]) == 3
        assert [event["time"] for event in row["trigger_events"]] == [0.0, 0.5, 1.0]
        assert row["trigger_events"][1]["new_chain"] is False
        assert row["damage_events"][-1]["time"] == pytest.approx(2.0)


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


class TestAftershock:
    def test_immobilize_schedules_levelled_shockwave(self, fight, attacker_stats):
        spell = {
            "Q": {
                "name": "Test stun",
                "rank": 1,
                "cooldown": 10.0,
                "damage_type": "magic",
                "total_raw": 300.0,
                "parts": (DamagePart("magic", 300.0, cc_kind="stun", cc_duration=1.0),),
            }
        }
        result = fight(
            attacker_stats(level=18, bonus_health=500.0),
            spell,
            keystone="Aftershock",
            target_magic_resistance=0.0,
            fight_duration_seconds=3.0,
        )
        row = _aftershock_row(result)
        assert row is not None
        assert row["count"] == 1
        assert row["damage_type"] == "magic"
        assert row["damage_events"][0]["time"] == pytest.approx(2.5)
        assert row["total_damage"] == pytest.approx(160.0)

    def test_non_immobilizing_damage_does_not_proc(self, fight, attacker_stats):
        result = fight(
            attacker_stats(),
            _spell(),
            keystone="Aftershock",
            target_magic_resistance=0.0,
        )
        assert _aftershock_row(result) is None


class TestGrasp:
    def test_four_combat_stacks_empower_basic_attacks(self, fight, attacker_stats):
        result = fight(
            attacker_stats(),
            {},
            keystone="Grasp of the Undying",
            target_magic_resistance=0.0,
            one_rotation=False,
            fight_duration_seconds=9.0,
            auto_attack_uptime=1.0,
            auto_attacks_only=True,
        )
        row = result["breakdown"]["keystone_Grasp of the Undying"]
        assert row["count"] == 2
        assert [event["time"] for event in row["damage_events"]] == [4.0, 8.0]
        assert row["total_damage"] == pytest.approx(0.035 * 2000 + 0.035 * 2005)
        heal = result["breakdown"]["heal_Grasp of the Undying"]
        assert heal["total_amount"] == pytest.approx(0.013 * 2000 + 0.013 * 2005)
        assert row["permanent_health_gained"] == pytest.approx(10.0)

    def test_ranged_ratios_are_sourced_separately(self, fight, attacker_stats):
        result = fight(
            attacker_stats(is_melee=False),
            {},
            keystone="Grasp of the Undying",
            target_magic_resistance=0.0,
            one_rotation=False,
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
            auto_attacks_only=True,
        )
        row = result["breakdown"]["keystone_Grasp of the Undying"]
        assert row["count"] == 1
        assert row["total_damage"] == pytest.approx(0.014 * 2000)

    def test_no_basic_attack_timeline_does_not_proc(self, fight, attacker_stats):
        result = fight(attacker_stats(), {}, keystone="Grasp of the Undying")
        assert "keystone_Grasp of the Undying" not in result["breakdown"]


class TestHailOfBlades:
    def test_temporary_attack_speed_changes_shared_swing_count(
        self, fight, attacker_stats
    ):
        result = fight(
            attacker_stats(),
            {},
            keystone="Hail of Blades",
            target_armor=0.0,
            target_magic_resistance=0.0,
            one_rotation=False,
            fight_duration_seconds=9.0,
            auto_attack_uptime=1.0,
            auto_attacks_only=True,
        )
        auto_row = result["breakdown"]["auto_attacks"]
        row = result["breakdown"]["keystone_Hail of Blades"]
        assert auto_row["count"] == 10
        assert row["count"] == 2
        assert [event["time"] for event in row["damage_events"]] == pytest.approx(
            [0.0, 0.64]
        )
        assert row["total_damage"] == pytest.approx(40.0)

    def test_cooldown_allows_a_later_two_attack_window(self, fight, attacker_stats):
        result = fight(
            attacker_stats(),
            {},
            keystone="Hail of Blades",
            target_armor=0.0,
            target_magic_resistance=0.0,
            one_rotation=False,
            fight_duration_seconds=12.0,
            auto_attack_uptime=1.0,
            auto_attacks_only=True,
        )
        row = result["breakdown"]["keystone_Hail of Blades"]
        assert row["count"] == 4
        assert len(row["activation_times"]) == 2
        assert row["activation_times"][1] >= 10.0

    def test_no_basic_attack_timeline_does_not_proc(self, fight, attacker_stats):
        result = fight(attacker_stats(), {}, keystone="Hail of Blades")
        assert "keystone_Hail of Blades" not in result["breakdown"]


class TestLethalTempo:
    def test_max_stack_bolts_use_the_shared_stack_sensitive_schedule(
        self, fight, attacker_stats
    ):
        result = fight(
            attacker_stats(),
            {},
            keystone="Lethal Tempo",
            target_armor=0.0,
            target_magic_resistance=0.0,
            one_rotation=False,
            fight_duration_seconds=10.0,
            auto_attack_uptime=1.0,
            auto_attacks_only=True,
        )
        auto_row = result["breakdown"]["auto_attacks"]
        row = result["breakdown"]["keystone_Lethal Tempo"]
        assert auto_row["count"] == len(row["stack_counts"])
        assert row["bolt_attack_indices"][0] == 5
        assert all(
            row["stack_counts"][index] == 6 for index in row["bolt_attack_indices"]
        )
        assert row["damage_type"] == "magic"
        assert row["count"] > 0

    def test_stacks_expire_after_the_sourced_window(self, fight, attacker_stats):
        result = fight(
            attacker_stats(attack_speed=0.1),
            {},
            keystone="Lethal Tempo",
            target_armor=0.0,
            target_magic_resistance=0.0,
            one_rotation=False,
            fight_duration_seconds=30.0,
            auto_attack_uptime=1.0,
            auto_attacks_only=True,
        )
        row = result["breakdown"].get("keystone_Lethal Tempo")
        assert row is None
        assert any("never reached" in note for note in result["notes"])

    def test_no_basic_attack_timeline_does_not_proc(self, fight, attacker_stats):
        result = fight(attacker_stats(), {}, keystone="Lethal Tempo")
        assert "keystone_Lethal Tempo" not in result["breakdown"]


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


def _aery_row(result):
    return result["breakdown"].get("keystone_Summon Aery")


def _dark_harvest_row(result):
    return result["breakdown"].get("keystone_Dark Harvest")


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


class TestTheOneKeystoneThatBooksNoDamage:
    """Unsealed Spellbook contributes nothing and says so in its own words.

    Every other keystone is modeled now, so this is the whole of the
    no-damage roster — and it is compiled and selectable rather than a
    refusal, which is what makes the receipt reachable at all.
    """

    def test_the_total_is_unmoved_and_the_receipt_is_published(
        self, fight, attacker_stats
    ):
        keystone = "Unsealed Spellbook"
        baseline = _autos(fight, attacker_stats, "")
        result = _autos(fight, attacker_stats, keystone)
        assert result["total_damage"] == pytest.approx(baseline["total_damage"])
        assert not [key for key in result["breakdown"] if key.startswith("keystone")]
        assert any(
            "deals no damage in any fight" in note for note in _notes(result, keystone)
        )


def test_a_keystone_that_never_procs_says_so(fight, attacker_stats):
    """Electrocute's silent zero is closed with the rest of them."""
    result = _autos(fight, attacker_stats, "Electrocute", stats={"attack_speed": 0.5})
    assert _keystone_row(result) is None
    assert any("never procced" in note for note in _notes(result, "Electrocute"))


class TestSummonAeryProcs:
    def test_damaging_cast_lands_after_the_sourced_flight(self, fight, attacker_stats):
        result = fight(attacker_stats(), _spell("Q"), keystone="Summon Aery")
        row = _aery_row(result)
        assert row is not None
        assert row["count"] == 1
        assert row["damage_type"] == "magic"
        assert row["total_damage"] == pytest.approx(25.0)
        cast_time = result["cast_timeline"][0]["time"]
        assert row["damage_events"][0]["time"] == pytest.approx(cast_time + 0.45)

    def test_sourced_linger_gates_following_signals(self, fight, attacker_stats):
        result = fight(
            attacker_stats(),
            _spell("Q", cooldown=10.0),
            keystone="Summon Aery",
            one_rotation=False,
            fight_duration_seconds=25.0,
        )
        assert len(result["cast_timeline"]) == 3
        assert _aery_row(result)["count"] == 3


class TestDarkHarvestProcs:
    def test_only_a_hit_after_the_threshold_triggers(self, fight, attacker_stats):
        abilities = {
            **_spell("Q", damage=600.0, cooldown=60.0),
            **_spell("W", damage=100.0, cooldown=60.0),
        }
        result = fight(
            attacker_stats(),
            abilities,
            keystone="Dark Harvest",
            target_health=1000.0,
            target_magic_resistance=0.0,
        )
        row = _dark_harvest_row(result)
        assert row is not None
        assert row["count"] == 1
        assert row["total_damage"] == pytest.approx(30.0)
        assert row["damage_events"][0]["time"] == pytest.approx(1.75)
        assert row["damage_events"][0]["trigger_time"] == pytest.approx(0.0)
        assert row["damage_events"][0]["souls"] == 0

    def test_cooldown_and_soul_reap_gate_later_procs(self, fight, attacker_stats):
        abilities = {
            **_spell("Q", damage=600.0, cooldown=60.0),
            **_spell("W", damage=100.0, cooldown=60.0),
            **_spell("E", damage=50.0, cooldown=10.0),
        }
        result = fight(
            attacker_stats(),
            abilities,
            keystone="Dark Harvest",
            one_rotation=False,
            fight_duration_seconds=45.0,
            target_health=1000.0,
            target_magic_resistance=0.0,
        )
        row = _dark_harvest_row(result)
        assert row is not None
        assert row["count"] == 2
        assert [event["trigger_time"] for event in row["damage_events"]] == [
            pytest.approx(0.0),
            pytest.approx(40.0),
        ]
        assert [event["souls"] for event in row["damage_events"]] == [0, 1]
        assert row["total_damage"] == pytest.approx(30.0 + 41.0)
        assert any("takedown reset" in note for note in result["notes"])
