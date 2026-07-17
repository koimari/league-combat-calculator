"""Tests for the fight-damage engine core (src.calculator.damage).

Covers calculate_fight_damage behavior (cast order), the private simulation
helpers (_simulate_bork_damage, _calculate_phantom_hits, _navori_effective_cd),
and the auto-vs-ability breakdown split. Per-item fight-damage tests live in
test_item_damage.py; resistance/pen primitives in test_resistance.py; ability
primitives in test_champion_primitives.py.
"""

import pytest
from types import SimpleNamespace

from src.calculator.resistance import apply_resistance
from src.calculator.champions import (
    parse_champion_abilities as parse_ahri_abilities,
)
from src.calculator.damage import (
    calculate_fight_damage,
    split_auto_vs_ability,
    _simulate_current_health_on_hit,
    _calculate_phantom_hits as _calculate_phantom_hits_compiled,
    _navori_effective_cd,
    _mitigate,
)
from src.calculator.item_effects import DamageInputs, resolve_damage_effects


def _simulate_bork_damage(
    *,
    target_health,
    num_auto_attacks,
    auto_damage_per_hit,
    other_on_hit_per_hit,
    effective_armor,
    is_melee,
    phantom_hit_autos=None,
    double_hit_all=False,
):
    """Readable test adapter around the generic current-health simulation."""
    effect = resolve_damage_effects([{"name": "Blade of the Ruined King"}])
    return _simulate_current_health_on_hit(
        effect.per_hits[0],
        DamageInputs({}, 1, is_melee, target_health, target_health),
        target_health,
        num_auto_attacks,
        auto_damage_per_hit,
        other_on_hit_per_hit,
        SimpleNamespace(effective_armor=effective_armor, effective_mr=0.0),
        1.0,
        phantom_hit_autos,
        double_hit_all,
    )


def _calculate_phantom_hits(num_auto_attacks, item_names):
    """Keep cadence tables readable while production consumes typed rules."""
    effects = resolve_damage_effects([{"name": name} for name in item_names])
    return _calculate_phantom_hits_compiled(num_auto_attacks, effects.phantom_hit)


class TestMitigate:
    """One resistance path shared by every damage source."""

    @pytest.fixture
    def resists(self):
        return SimpleNamespace(effective_armor=100.0, effective_mr=50.0)

    def test_physical_uses_effective_armor(self, resists) -> None:
        assert _mitigate(300.0, "physical", resists, 1.2) == 150.0

    def test_magic_uses_effective_mr_and_magic_amp(self, resists) -> None:
        assert _mitigate(300.0, "magic", resists, 1.2) == pytest.approx(240.0)

    def test_true_damage_ignores_resists_and_magic_amp(self, resists) -> None:
        assert _mitigate(300.0, "true", resists, 1.2) == 300.0


class TestBorkCurrentHpSimulation:
    """Tests for Blade of the Ruined King current-HP iterative simulation."""

    def test_single_hit_equals_full_hp_calculation(self) -> None:
        """With 1 auto attack, BoRK damage should equal ratio * full HP."""
        # Ranged, 0 armor, 1000 HP => 6% * 1000 = 60
        result, hits = _simulate_bork_damage(
            target_health=1000.0,
            num_auto_attacks=1,
            auto_damage_per_hit=0.0,
            other_on_hit_per_hit=0.0,
            effective_armor=0.0,
            is_melee=False,
        )
        assert abs(result - 60.0) < 0.01
        assert hits == 1

    def test_second_hit_less_than_first(self) -> None:
        """Second BoRK hit should deal less because target HP dropped."""
        # 2 hits, ranged, 0 armor, 1000 HP, auto does 100 damage
        result, hits = _simulate_bork_damage(
            target_health=1000.0,
            num_auto_attacks=2,
            auto_damage_per_hit=100.0,
            other_on_hit_per_hit=0.0,
            effective_armor=0.0,
            is_melee=False,
        )
        # Hit 1: 6% * 1000 = 60, target HP drops to 1000 - 100 - 60 = 840
        # Hit 2: 6% * 840 = 50.4, target HP drops to 840 - 100 - 50.4 = 689.6
        # Total: 110.4
        assert abs(result - 110.4) < 0.01
        assert hits == 2

    def test_less_than_flat_multiplication(self) -> None:
        """Iterative BoRK should always deal less than naive per_hit * hits."""
        naive_total = 0.06 * 1000.0 * 5  # 300
        result, _ = _simulate_bork_damage(
            target_health=1000.0,
            num_auto_attacks=5,
            auto_damage_per_hit=80.0,
            other_on_hit_per_hit=0.0,
            effective_armor=0.0,
            is_melee=False,
        )
        assert result < naive_total

    def test_min_damage_when_target_hp_zero(self) -> None:
        """BoRK should deal 5 flat damage once target HP hits 0."""
        # High auto damage to quickly deplete HP
        result, hits = _simulate_bork_damage(
            target_health=100.0,
            num_auto_attacks=3,
            auto_damage_per_hit=200.0,
            other_on_hit_per_hit=0.0,
            effective_armor=0.0,
            is_melee=False,
        )
        # Hit 1: 6% * 100 = 6, HP -> max(0, 100 - 200 - 6) = 0
        # Hit 2: min 5, HP stays 0
        # Hit 3: min 5, HP stays 0
        # Total: 6 + 5 + 5 = 16
        assert abs(result - 16.0) < 0.01
        assert hits == 3

    def test_melee_uses_9_percent(self) -> None:
        """Melee champions should use the 9% ratio."""
        result, _ = _simulate_bork_damage(
            target_health=1000.0,
            num_auto_attacks=1,
            auto_damage_per_hit=0.0,
            other_on_hit_per_hit=0.0,
            effective_armor=0.0,
            is_melee=True,
        )
        assert abs(result - 90.0) < 0.01

    def test_armor_mitigates_bork_damage(self) -> None:
        """BoRK physical damage should be reduced by armor."""
        # 100 armor => 100/200 = 50% mitigation
        result, _ = _simulate_bork_damage(
            target_health=1000.0,
            num_auto_attacks=1,
            auto_damage_per_hit=0.0,
            other_on_hit_per_hit=0.0,
            effective_armor=100.0,
            is_melee=False,
        )
        # Raw: 60, mitigated: 30
        assert abs(result - 30.0) < 0.01

    def test_zero_auto_attacks_returns_zero(self) -> None:
        """No autos means no BoRK damage."""
        result, hits = _simulate_bork_damage(
            target_health=1000.0,
            num_auto_attacks=0,
            auto_damage_per_hit=0.0,
            other_on_hit_per_hit=0.0,
            effective_armor=0.0,
            is_melee=False,
        )
        assert result == 0.0
        assert hits == 0

    def test_other_on_hit_reduces_target_hp(self) -> None:
        """Other on-hit damage should also reduce target HP for BoRK calc."""
        # Without other on-hit
        result_no_extra, _ = _simulate_bork_damage(
            target_health=1000.0,
            num_auto_attacks=3,
            auto_damage_per_hit=50.0,
            other_on_hit_per_hit=0.0,
            effective_armor=0.0,
            is_melee=False,
        )
        # With other on-hit (target HP drops faster => less BoRK damage)
        result_with_extra, _ = _simulate_bork_damage(
            target_health=1000.0,
            num_auto_attacks=3,
            auto_damage_per_hit=50.0,
            other_on_hit_per_hit=30.0,
            effective_armor=0.0,
            is_melee=False,
        )
        assert result_with_extra < result_no_extra

    def test_full_fight_with_bork(self) -> None:
        """Integration test: Ahri level 18 with BoRK vs 1000 HP target."""
        from src.calculator.data_fetcher import get_champion, get_item_by_name
        from src.calculator.stats import calculate_total_stats

        ahri_data = get_champion("Ahri")
        bork = get_item_by_name("Blade of the Ruined King")
        items = [bork]
        stats = calculate_total_stats(ahri_data, 18, items)
        abilities = parse_ahri_abilities(ahri_data, 18, stats["ability_power"])

        fight = calculate_fight_damage(
            stats,
            abilities,
            target_health=1000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=5.0,
            auto_attack_uptime=0.8,
            ability_haste=0.0,
            items=items,
            one_rotation=True,
        )
        bork_entry = fight["breakdown"].get("on_hit_Blade of the Ruined King")
        assert bork_entry is not None, "BoRK should appear in breakdown"
        assert bork_entry["total_damage"] > 0

        # Verify it's less than the naive flat calculation
        naive_per_hit = 0.06 * 1000  # 60 raw
        naive_mitigated = apply_resistance(naive_per_hit, fight["effective_armor"])
        naive_total = naive_mitigated * bork_entry["count"]
        assert bork_entry["total_damage"] < naive_total, (
            f"Iterative BoRK {bork_entry['total_damage']:.1f} should be less "
            f"than naive {naive_total:.1f}"
        )


class TestCastOrder:
    """Tests that cast_order parameter affects damage calculations."""

    def test_default_cast_order_unchanged(self) -> None:
        """None cast_order should produce the same result as explicit Q,W,E,R."""
        from src.calculator.data_fetcher import get_champion, get_item_by_name
        from src.calculator.stats import calculate_total_stats

        ahri_data = get_champion("Ahri")
        items = [get_item_by_name("Rabadon's Deathcap")]
        stats = calculate_total_stats(ahri_data, 18, items)
        abilities = parse_ahri_abilities(ahri_data, 18, stats["ability_power"])

        fight_default = calculate_fight_damage(
            stats,
            abilities,
            target_health=2000,
            target_armor=50,
            target_magic_resistance=50,
            fight_duration_seconds=5.0,
            auto_attack_uptime=0.0,
            ability_haste=0.0,
            items=items,
            one_rotation=True,
        )
        fight_explicit = calculate_fight_damage(
            stats,
            abilities,
            target_health=2000,
            target_armor=50,
            target_magic_resistance=50,
            fight_duration_seconds=5.0,
            auto_attack_uptime=0.0,
            ability_haste=0.0,
            items=items,
            one_rotation=True,
            cast_order=["Q", "W", "E", "R"],
        )
        assert fight_default["total_damage"] == fight_explicit["total_damage"]

    def test_cast_order_affects_bloodletter_stacking(self) -> None:
        """Different cast orders should produce different damage with Bloodletter's Curse."""
        from src.calculator.data_fetcher import get_champion, get_item_by_name
        from src.calculator.stats import calculate_total_stats

        ahri_data = get_champion("Ahri")
        items = [
            get_item_by_name("Rabadon's Deathcap"),
            get_item_by_name("Bloodletter's Curse"),
        ]
        stats = calculate_total_stats(ahri_data, 18, items)
        abilities = parse_ahri_abilities(ahri_data, 18, stats["ability_power"])

        fight_qwer = calculate_fight_damage(
            stats,
            abilities,
            target_health=2000,
            target_armor=50,
            target_magic_resistance=100,
            fight_duration_seconds=5.0,
            auto_attack_uptime=0.0,
            ability_haste=0.0,
            items=items,
            one_rotation=True,
            cast_order=["Q", "W", "E", "R"],
        )
        fight_rwqe = calculate_fight_damage(
            stats,
            abilities,
            target_health=2000,
            target_armor=50,
            target_magic_resistance=100,
            fight_duration_seconds=5.0,
            auto_attack_uptime=0.0,
            ability_haste=0.0,
            items=items,
            one_rotation=True,
            cast_order=["R", "W", "Q", "E"],
        )
        # Different order should produce different total damage
        assert fight_qwer["total_damage"] != fight_rwqe["total_damage"]

    def test_cast_order_affects_shadowflame_bonus(self) -> None:
        """Different cast orders should change Shadowflame bonus amounts."""
        from src.calculator.data_fetcher import get_champion, get_item_by_name
        from src.calculator.stats import calculate_total_stats

        ahri_data = get_champion("Ahri")
        items = [
            get_item_by_name("Rabadon's Deathcap"),
            get_item_by_name("Shadowflame"),
        ]
        stats = calculate_total_stats(ahri_data, 18, items)
        abilities = parse_ahri_abilities(ahri_data, 18, stats["ability_power"])

        fight_qwer = calculate_fight_damage(
            stats,
            abilities,
            target_health=1500,
            target_armor=50,
            target_magic_resistance=50,
            fight_duration_seconds=5.0,
            auto_attack_uptime=0.0,
            ability_haste=0.0,
            items=items,
            one_rotation=True,
            cast_order=["Q", "W", "E", "R"],
        )
        fight_rqwe = calculate_fight_damage(
            stats,
            abilities,
            target_health=1500,
            target_armor=50,
            target_magic_resistance=50,
            fight_duration_seconds=5.0,
            auto_attack_uptime=0.0,
            ability_haste=0.0,
            items=items,
            one_rotation=True,
            cast_order=["R", "Q", "W", "E"],
        )
        # With different cast orders, the Shadowflame bonus should differ
        qwer_sf = (
            fight_qwer["breakdown"]
            .get("shadowflame_Shadowflame", {})
            .get("total_damage", 0)
        )
        rqwe_sf = (
            fight_rqwe["breakdown"]
            .get("shadowflame_Shadowflame", {})
            .get("total_damage", 0)
        )
        assert qwer_sf != rqwe_sf


class TestPhantomHitCalculation:
    """Tests for Guinsoo's Rageblade phantom hit timing."""

    def test_no_rageblade_no_phantom_hits(self) -> None:
        """Without Rageblade, no phantom hits should occur."""
        count, autos = _calculate_phantom_hits(20, ["Nashor's Tooth"])
        assert count == 0
        assert len(autos) == 0

    def test_fewer_than_6_autos_no_phantom(self) -> None:
        """With fewer than 6 autos, no phantom hit triggers."""
        count, autos = _calculate_phantom_hits(5, ["Guinsoo's Rageblade"])
        assert count == 0
        assert len(autos) == 0

    def test_exactly_6_autos_one_phantom(self) -> None:
        """6th auto should be the first phantom hit."""
        count, autos = _calculate_phantom_hits(6, ["Guinsoo's Rageblade"])
        assert count == 1
        assert autos == {5}  # 0-indexed: auto #6 is index 5

    def test_10_autos_two_phantoms(self) -> None:
        """6th and 9th autos should trigger phantom hits."""
        count, autos = _calculate_phantom_hits(10, ["Guinsoo's Rageblade"])
        assert count == 2
        assert autos == {5, 8}  # 0-indexed: autos #6 and #9

    def test_13_autos_three_phantoms(self) -> None:
        """6th, 9th, and 12th autos should trigger phantom hits."""
        count, autos = _calculate_phantom_hits(13, ["Guinsoo's Rageblade"])
        assert count == 3
        assert autos == {5, 8, 11}

    def test_20_autos_correct_phantom_count(self) -> None:
        """With 20 autos, phantoms at 6,9,12,15,18 = 5 phantom hits."""
        count, autos = _calculate_phantom_hits(20, ["Guinsoo's Rageblade"])
        assert count == 5
        assert autos == {5, 8, 11, 14, 17}


class TestNavoriEffectiveCd:
    """Tests for Navori Flickerblade CD refund helper."""

    def test_no_autos_returns_base_cd(self) -> None:
        """With 0 autos per second, CD is unchanged."""
        assert _navori_effective_cd(7.0, 0.0, 0.15) == 7.0

    def test_no_refund_returns_base_cd(self) -> None:
        """With 0% refund, CD is unchanged."""
        assert _navori_effective_cd(7.0, 1.5, 0.0) == 7.0

    def test_cd_is_reduced(self) -> None:
        """With autos during the window, CD should be shorter than base."""
        reduced = _navori_effective_cd(7.0, 1.0, 0.15)
        assert reduced < 7.0
        assert reduced > 0.0

    def test_higher_attack_speed_more_reduction(self) -> None:
        """Higher attack speed should reduce CD more."""
        slow = _navori_effective_cd(7.0, 0.5, 0.15)
        fast = _navori_effective_cd(7.0, 2.0, 0.15)
        assert fast < slow

    def test_known_value(self) -> None:
        """Verify a specific scenario: 7s CD, 1 auto/sec, 15% refund.

        t=0: cast, 7s remaining
        t=1: auto → (7-1)*0.85 = 5.10
        t=2: auto → (5.10-1)*0.85 = 3.485
        t=3: auto → (3.485-1)*0.85 = 2.112
        t=4: auto → (2.112-1)*0.85 = 0.945
        t=4.945: CD expires. Effective CD ≈ 4.945s
        """
        reduced = _navori_effective_cd(7.0, 1.0, 0.15)
        assert abs(reduced - 4.945) < 0.01


class TestSplitAutoVsAbility:
    """Tests for split_auto_vs_ability — auto vs ability damage attribution.

    Expected values replicate the attribution rules that previously lived
    in app.py's /api/calculate route.
    """

    def test_pure_ability_damage(self) -> None:
        breakdown = {
            "Q": {"name": "Q", "total_damage": 100.0},
            "R": {"name": "R", "total_damage": 250.0},
        }
        auto, ability = split_auto_vs_ability(breakdown)
        assert auto == 0.0
        assert ability == 350.0

    def test_pure_auto_damage(self) -> None:
        breakdown = {
            "auto_attacks": {"name": "Auto Attacks", "total_damage": 400.0},
        }
        auto, ability = split_auto_vs_ability(breakdown)
        assert auto == 400.0
        assert ability == 0.0

    def test_on_hit_prefix_counts_as_auto(self) -> None:
        breakdown = {
            "auto_attacks": {"name": "Auto Attacks", "total_damage": 300.0},
            "on_hit_Kraken Slayer": {"name": "Kraken", "total_damage": 90.0},
        }
        auto, ability = split_auto_vs_ability(breakdown)
        assert auto == 390.0
        assert ability == 0.0

    def test_spellblade_prefix_counts_as_auto(self) -> None:
        breakdown = {
            "Q": {"name": "Q", "total_damage": 100.0},
            "spellblade_Lich Bane": {"name": "Lich Bane", "total_damage": 60.0},
        }
        auto, ability = split_auto_vs_ability(breakdown)
        assert auto == 60.0
        assert ability == 100.0

    def test_fiendhunter_true_damage_counts_as_auto(self) -> None:
        breakdown = {
            "fiendhunter_true_damage": {"name": "Fiendhunter", "total_damage": 75.0},
            "W": {"name": "W", "total_damage": 25.0},
        }
        auto, ability = split_auto_vs_ability(breakdown)
        assert auto == 75.0
        assert ability == 25.0

    def test_included_in_note_entries_skipped(self) -> None:
        # Informational entries (e.g. Actualizer) whose damage is already
        # counted in other rows must not be double-counted.
        breakdown = {
            "Q": {"name": "Q", "total_damage": 100.0},
            "ability_amp_Actualizer": {
                "name": "Damage Amplification (Actualizer)",
                "total_damage": 15.0,
                "note": "included in ability/proc totals above",
            },
        }
        auto, ability = split_auto_vs_ability(breakdown)
        assert auto == 0.0
        assert ability == 100.0

    def test_amp_and_execute_split_proportionally(self) -> None:
        # auto 100 / ability 300 -> auto ratio 0.25; amp 40 + execute 20
        # redistribute 60 as 15 auto / 45 ability. Amp rows use the
        # damage_amp_<source> keys the engine actually emits.
        breakdown = {
            "auto_attacks": {"name": "Auto Attacks", "total_damage": 100.0},
            "Q": {"name": "Q", "total_damage": 300.0},
            "damage_amp_Lord Dominik's Regards": {
                "name": "Damage Amplification (Lord Dominik's Regards)",
                "total_damage": 40.0,
            },
            "execute": {"name": "Execute", "total_damage": 20.0},
        }
        auto, ability = split_auto_vs_ability(breakdown)
        assert auto == pytest.approx(115.0)
        assert ability == pytest.approx(345.0)

    def test_multiple_damage_amp_sources_redistribute(self) -> None:
        # Several damage_amp_<source> rows (e.g. LDR + Horizon Focus) all
        # redistribute proportionally — amps scale both buckets.
        breakdown = {
            "auto_attacks": {"name": "Auto Attacks", "total_damage": 150.0},
            "W": {"name": "W", "total_damage": 50.0},
            "damage_amp_Lord Dominik's Regards": {
                "name": "Damage Amplification (Lord Dominik's Regards)",
                "total_damage": 30.0,
            },
            "damage_amp_Horizon Focus": {
                "name": "Damage Amplification (Horizon Focus)",
                "total_damage": 10.0,
            },
        }
        auto, ability = split_auto_vs_ability(breakdown)
        # auto ratio 0.75: 150 + 40*0.75 = 180; ability 50 + 40*0.25 = 60
        assert auto == pytest.approx(180.0)
        assert ability == pytest.approx(60.0)

    def test_sundered_sky_excluded_and_not_redistributed(self) -> None:
        # sundered_sky is a display-only row: excluded from both buckets
        # and (unlike amp/execute) never redistributed.
        breakdown = {
            "Q": {"name": "Q", "total_damage": 200.0},
            "sundered_sky": {"name": "Sundered Sky", "total_damage": 50.0},
        }
        auto, ability = split_auto_vs_ability(breakdown)
        assert auto == 0.0
        assert ability == 200.0

    def test_zero_total_drops_amp(self) -> None:
        # With no attributable damage there is no ratio to split by;
        # amp/execute damage is dropped entirely.
        breakdown = {
            "damage_amp_Lord Dominik's Regards": {
                "name": "Damage Amplification (Lord Dominik's Regards)",
                "total_damage": 40.0,
            },
            "execute": {"name": "Execute", "total_damage": 20.0},
        }
        auto, ability = split_auto_vs_ability(breakdown)
        assert auto == 0.0
        assert ability == 0.0

    def test_empty_breakdown(self) -> None:
        auto, ability = split_auto_vs_ability({})
        assert auto == 0.0
        assert ability == 0.0

    def test_missing_total_damage_treated_as_zero(self) -> None:
        breakdown = {
            "Q": {"name": "Q"},
            "auto_attacks": {"name": "Auto Attacks", "total_damage": 50.0},
        }
        auto, ability = split_auto_vs_ability(breakdown)
        assert auto == 50.0
        assert ability == 0.0
