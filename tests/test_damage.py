"""Tests for the fight-damage engine core (src.calculator.damage).

Covers calculate_fight_damage behavior (cast order), the private simulation
helpers (_simulate_bork_damage, _calculate_phantom_hits, _navori_effective_cd),
and the auto-vs-ability breakdown split. Per-item fight-damage tests live in
test_item_damage.py; resistance/pen primitives in test_resistance.py; ability
primitives in test_champion_primitives.py.
"""

import pytest
from types import SimpleNamespace

from src.calculator.ability_spec import DamagePart
from src.calculator.resistance import apply_resistance
from src.calculator.champions import (
    parse_champion_abilities as parse_ahri_abilities,
)
from src.calculator.damage import (
    FightConfig,
    calculate_fight_damage,
    split_auto_vs_ability,
    split_by_damage_type,
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
    """Keep cadence tables readable while production consumes typed rules.

    Returns (count, autos) for the auto-only case these tables cover;
    production also receives leading ability-attack phantom positions.
    """
    effects = resolve_damage_effects([{"name": name} for name in item_names])
    ability_phantoms, autos = _calculate_phantom_hits_compiled(
        num_auto_attacks, effects.phantom_hit
    )
    assert ability_phantoms == []  # no leading ability attacks here
    return len(autos), autos


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
            items,
            FightConfig(
                target_health=1000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=5.0,
                auto_attack_uptime=0.8,
                one_rotation=True,
            ),
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
            items,
            FightConfig(
                target_health=2000,
                target_armor=50,
                target_magic_resistance=50,
                fight_duration_seconds=5.0,
                auto_attack_uptime=0.0,
                one_rotation=True,
            ),
        )
        fight_explicit = calculate_fight_damage(
            stats,
            abilities,
            items,
            FightConfig(
                target_health=2000,
                target_armor=50,
                target_magic_resistance=50,
                fight_duration_seconds=5.0,
                auto_attack_uptime=0.0,
                one_rotation=True,
                cast_order=["Q", "W", "E", "R"],
            ),
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
            items,
            FightConfig(
                target_health=2000,
                target_armor=50,
                target_magic_resistance=100,
                fight_duration_seconds=5.0,
                auto_attack_uptime=0.0,
                one_rotation=True,
                cast_order=["Q", "W", "E", "R"],
            ),
        )
        fight_rwqe = calculate_fight_damage(
            stats,
            abilities,
            items,
            FightConfig(
                target_health=2000,
                target_armor=50,
                target_magic_resistance=100,
                fight_duration_seconds=5.0,
                auto_attack_uptime=0.0,
                one_rotation=True,
                cast_order=["R", "W", "Q", "E"],
            ),
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
            items,
            FightConfig(
                target_health=1500,
                target_armor=50,
                target_magic_resistance=50,
                fight_duration_seconds=5.0,
                auto_attack_uptime=0.0,
                one_rotation=True,
                cast_order=["Q", "W", "E", "R"],
            ),
        )
        fight_rqwe = calculate_fight_damage(
            stats,
            abilities,
            items,
            FightConfig(
                target_health=1500,
                target_armor=50,
                target_magic_resistance=50,
                fight_duration_seconds=5.0,
                auto_attack_uptime=0.0,
                one_rotation=True,
                cast_order=["R", "Q", "W", "E"],
            ),
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

    def test_informational_entries_skipped(self) -> None:
        # Entries marked informational (e.g. Actualizer's amp summary)
        # have damage already counted in other rows — never double-count.
        breakdown = {
            "Q": {"name": "Q", "total_damage": 100.0},
            "ability_amp_Actualizer": {
                "name": "Damage Amplification (Actualizer)",
                "total_damage": 15.0,
                "detail": "included in ability/proc totals above",
                "informational": True,
            },
        }
        auto, ability = split_auto_vs_ability(breakdown)
        assert auto == 0.0
        assert ability == 100.0

    def test_amp_split_proportionally_and_execute_skipped(self) -> None:
        # auto 100 / ability 300 -> auto ratio 0.25; amp 40 redistributes
        # as 10 auto / 30 ability. Amp rows use the damage_amp_<source>
        # keys the engine actually emits; the execute-threshold row is
        # informational (always zero engine-side) and contributes nothing.
        breakdown = {
            "auto_attacks": {"name": "Auto Attacks", "total_damage": 100.0},
            "Q": {"name": "Q", "total_damage": 300.0},
            "damage_amp_Lord Dominik's Regards": {
                "name": "Damage Amplification (Lord Dominik's Regards)",
                "total_damage": 40.0,
            },
            "execute": {
                "name": "Execute",
                "total_damage": 0.0,
                "informational": True,
            },
        }
        auto, ability = split_auto_vs_ability(breakdown)
        assert auto == pytest.approx(110.0)
        assert ability == pytest.approx(330.0)

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
        # The Sundered Sky row is display-only (marked informational by
        # the engine): excluded from both buckets, never redistributed.
        breakdown = {
            "Q": {"name": "Q", "total_damage": 200.0},
            "sundered_sky": {
                "name": "Sundered Sky",
                "total_damage": 50.0,
                "informational": True,
            },
        }
        auto, ability = split_auto_vs_ability(breakdown)
        assert auto == 0.0
        assert ability == 200.0

    def test_zero_total_drops_amp(self) -> None:
        # With no attributable damage there is no ratio to split by;
        # amp damage is dropped entirely.
        breakdown = {
            "damage_amp_Lord Dominik's Regards": {
                "name": "Damage Amplification (Lord Dominik's Regards)",
                "total_damage": 40.0,
            },
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


class TestSplitByDamageType:
    """Tests for split_by_damage_type — physical/magic/true attribution.

    Every non-informational breakdown row carries a ``damage_type``;
    mixed rows built from typed parts additionally carry their exact
    ``damage_by_type`` composition. Untyped rows (amp rows) and mixed
    rows without a composition redistribute proportionally, mirroring
    split_auto_vs_ability's amp rule.
    """

    def test_typed_rows_land_in_their_buckets(self) -> None:
        breakdown = {
            "auto_attacks": {
                "name": "Auto Attacks",
                "total_damage": 400.0,
                "damage_type": "physical",
            },
            "Q": {"name": "Q", "total_damage": 100.0, "damage_type": "magic"},
            "fiendhunter_true_damage": {
                "name": "Fiendhunter",
                "total_damage": 50.0,
                "damage_type": "true",
            },
        }
        split = split_by_damage_type(breakdown)
        assert split == {"physical": 400.0, "magic": 100.0, "true": 50.0}

    def test_mixed_row_uses_exact_composition(self) -> None:
        # Mixed abilities (e.g. Ahri Q: magic outgoing + true return)
        # carry damage_by_type — the exact per-type mitigated totals.
        breakdown = {
            "Q": {
                "name": "Orb of Deception",
                "total_damage": 300.0,
                "damage_type": "mixed",
                "damage_by_type": {"magic": 200.0, "true": 100.0},
            },
        }
        split = split_by_damage_type(breakdown)
        assert split == {"physical": 0.0, "magic": 200.0, "true": 100.0}

    def test_mixed_without_composition_redistributes_proportionally(self) -> None:
        # physical 300 / magic 100 -> mixed 40 splits 30 physical, 10 magic.
        breakdown = {
            "auto_attacks": {
                "name": "Auto Attacks",
                "total_damage": 300.0,
                "damage_type": "physical",
            },
            "Q": {"name": "Q", "total_damage": 100.0, "damage_type": "magic"},
            "double_on_hit_Dusk and Dawn": {
                "name": "Dusk and Dawn (Double On-Hit)",
                "total_damage": 40.0,
                "damage_type": "mixed",
            },
        }
        split = split_by_damage_type(breakdown)
        assert split["physical"] == pytest.approx(330.0)
        assert split["magic"] == pytest.approx(110.0)
        assert split["true"] == 0.0

    def test_amp_rows_redistribute_proportionally(self) -> None:
        # damage_amp_<source> rows amplify every damage type equally.
        breakdown = {
            "auto_attacks": {
                "name": "Auto Attacks",
                "total_damage": 100.0,
                "damage_type": "physical",
            },
            "Q": {"name": "Q", "total_damage": 300.0, "damage_type": "magic"},
            "damage_amp_Lord Dominik's Regards": {
                "name": "Damage Amplification (Lord Dominik's Regards)",
                "total_damage": 40.0,
            },
        }
        split = split_by_damage_type(breakdown)
        assert split["physical"] == pytest.approx(110.0)
        assert split["magic"] == pytest.approx(330.0)
        assert split["true"] == 0.0

    def test_informational_rows_skipped(self) -> None:
        breakdown = {
            "Q": {"name": "Q", "total_damage": 100.0, "damage_type": "magic"},
            "execute": {
                "name": "The Collector (Execute)",
                "total_damage": 0.0,
                "damage_type": "true",
                "informational": True,
            },
            "ability_amp_Actualizer": {
                "name": "Damage Amplification (Actualizer)",
                "total_damage": 15.0,
                "informational": True,
            },
        }
        split = split_by_damage_type(breakdown)
        assert split == {"physical": 0.0, "magic": 100.0, "true": 0.0}

    def test_zero_typed_total_drops_untyped_damage(self) -> None:
        # No typed damage -> no ratio to split by; amp damage is dropped.
        breakdown = {
            "damage_amp_Lord Dominik's Regards": {
                "name": "Damage Amplification (Lord Dominik's Regards)",
                "total_damage": 40.0,
            },
        }
        split = split_by_damage_type(breakdown)
        assert split == {"physical": 0.0, "magic": 0.0, "true": 0.0}

    def test_empty_breakdown(self) -> None:
        assert split_by_damage_type({}) == {
            "physical": 0.0,
            "magic": 0.0,
            "true": 0.0,
        }

    def test_missing_total_damage_treated_as_zero(self) -> None:
        breakdown = {
            "Q": {"name": "Q", "damage_type": "magic"},
            "auto_attacks": {
                "name": "Auto Attacks",
                "total_damage": 50.0,
                "damage_type": "physical",
            },
        }
        split = split_by_damage_type(breakdown)
        assert split == {"physical": 50.0, "magic": 0.0, "true": 0.0}


# ---------------------------------------------------------------------------
# Hit-timeline stacking DoT (Briar's Crimson Curse)
# ---------------------------------------------------------------------------


def _stacking_dot_passive(single_stack_raw=100.0, applied_by_autos=True):
    """Passive entry declaring a hit-driven stacking DoT (Briar P shape)."""
    return {
        "name": "Bleed",
        "damage_type": "physical",
        "total_raw": single_stack_raw,
        "parts": (),
        "stacking_dot": {
            "name": "Bleed",
            "damage_type": "physical",
            "single_stack_raw": single_stack_raw,
            "duration": 5.0,
            "max_stacks": 5,
            "extra_stack_effectiveness": 0.25,
            "applied_by_autos": applied_by_autos,
        },
    }


def _stack_applier(cooldown=20.0, empowers_next_auto=False):
    """Zero-damage castable whose applications add one DoT stack each."""
    from src.calculator.ability_spec import DamagePart

    entry = {
        "name": "Applier",
        "cooldown": cooldown,
        "damage_type": "physical",
        "parts": (DamagePart("physical", 0.0),),
        "applies_dot_stack": True,
    }
    if empowers_next_auto:
        entry["empowers_next_auto"] = True
    return entry


class TestStackingDot:
    """Hit-timeline stacking DoT: rate = single_dps x (1 + 0.25 x (n-1)),
    stacks from the fight's real hit timeline (autos at attack-speed
    intervals, ability applications at cast times), shared duration
    refreshed by every application, committed 5s tail past the last hit.

    Single stack = 100 raw over 5s -> 20 dps; rates by stack count:
    20 / 25 / 30 / 35 / 40 (5-stack rate = 2x single = 200 per 5s window).
    """

    def test_auto_ramp_reduced_stacks_and_committed_tail(
        self, attacker_stats, fight
    ) -> None:
        """10 autos at 1/s over a 10s fight: ramp 20+25+30+35+40 over the
        first 5s, 4s at the 5-stack rate 40, then the full committed 5s
        tail (200) past fight end -> 510 raw."""
        result = fight(
            attacker_stats(),
            {"passive": _stacking_dot_passive()},
            target_armor=0.0,
            one_rotation=False,
            fight_duration_seconds=10.0,
            auto_attack_uptime=1.0,
        )
        row = result["breakdown"]["stacking_dot_passive"]
        assert row["total_damage"] == pytest.approx(510.0)
        assert row["count"] == 10
        assert row["unit"] == "stacks"
        assert row["damage_per_hit"] == pytest.approx(51.0)
        assert row["damage_type"] == "physical"

    def test_one_rotation_marginal_sum_is_175_percent(
        self, attacker_stats, fight
    ) -> None:
        """Q+W+E+R applications land together in one-rotation mode: the
        first stack commits 100%, the other three 25% each -> 1.75x."""
        abilities = {
            "passive": _stacking_dot_passive(),
            "Q": _stack_applier(),
            "W": _stack_applier(),
            "E": _stack_applier(),
            "R": _stack_applier(),
        }
        result = fight(attacker_stats(), abilities, target_armor=0.0)
        row = result["breakdown"]["stacking_dot_passive"]
        assert row["total_damage"] == pytest.approx(175.0)
        assert row["count"] == 4

    def test_single_application_commits_full_duration(
        self, attacker_stats, fight
    ) -> None:
        """One application = the full single-stack total, fight end or not."""
        abilities = {
            "passive": _stacking_dot_passive(),
            "Q": _stack_applier(),
        }
        result = fight(attacker_stats(), abilities, target_armor=0.0)
        row = result["breakdown"]["stacking_dot_passive"]
        assert row["total_damage"] == pytest.approx(100.0)

    def test_reapplication_refreshes_shared_duration(
        self, attacker_stats, fight
    ) -> None:
        """Autos at t=0 and t=4 (0.25 AS): the second hit refreshes before
        expiry -> 4s at 1 stack (80) + committed 5s at 2 stacks (125)."""
        result = fight(
            attacker_stats(attack_speed=0.25),
            {"passive": _stacking_dot_passive()},
            target_armor=0.0,
            one_rotation=False,
            fight_duration_seconds=9.0,
            auto_attack_uptime=1.0,
        )
        row = result["breakdown"]["stacking_dot_passive"]
        assert row["total_damage"] == pytest.approx(205.0)

    def test_stacks_expire_after_duration_gap(self, attacker_stats, fight) -> None:
        """Autos at t=0 and t=6 (gap > 5s): the first stack runs its full
        5s and expires; the second starts a fresh chain -> 100 + 100."""
        result = fight(
            attacker_stats(attack_speed=1.0 / 6.0),
            {"passive": _stacking_dot_passive()},
            target_armor=0.0,
            one_rotation=False,
            fight_duration_seconds=12.0,
            auto_attack_uptime=1.0,
        )
        row = result["breakdown"]["stacking_dot_passive"]
        assert row["total_damage"] == pytest.approx(200.0)
        assert row["count"] == 2

    def test_timed_casts_apply_stacks_on_cooldown(self, attacker_stats, fight) -> None:
        """No autos; a 4s-cooldown applier casts at t=0/4/8 over 10s:
        4s at 1 stack (80) + 4s at 2 (100) + committed 5s at 3 (150)."""
        abilities = {
            "passive": _stacking_dot_passive(),
            "Q": _stack_applier(cooldown=4.0),
        }
        result = fight(
            attacker_stats(),
            abilities,
            target_armor=0.0,
            one_rotation=False,
            fight_duration_seconds=10.0,
            auto_attack_uptime=0.0,
        )
        row = result["breakdown"]["stacking_dot_passive"]
        assert row["total_damage"] == pytest.approx(330.0)
        assert row["count"] == 3

    def test_bleed_is_mitigated_by_armor(self, attacker_stats, fight) -> None:
        """The DoT is physical damage: 100 armor halves it."""
        abilities = {
            "passive": _stacking_dot_passive(),
            "Q": _stack_applier(),
        }
        result = fight(attacker_stats(), abilities, target_armor=100.0)
        row = result["breakdown"]["stacking_dot_passive"]
        assert row["total_damage"] == pytest.approx(50.0)

    def test_empowered_auto_stack_rides_the_auto_stream(
        self, attacker_stats, fight
    ) -> None:
        """An empowers_next_auto applier's swing IS one of the fight's
        autos - its stack must not be counted twice on the timeline."""
        abilities = {
            "passive": _stacking_dot_passive(),
            "W": _stack_applier(cooldown=20.0, empowers_next_auto=True),
        }
        result = fight(
            attacker_stats(),
            abilities,
            target_armor=0.0,
            one_rotation=False,
            fight_duration_seconds=10.0,
            auto_attack_uptime=1.0,
        )
        row = result["breakdown"]["stacking_dot_passive"]
        # Identical to the autos-only timeline: 10 hits -> 510 raw.
        assert row["total_damage"] == pytest.approx(510.0)
        assert row["count"] == 10

    def test_empowered_auto_applies_stack_without_auto_stream(
        self, attacker_stats, fight
    ) -> None:
        """One-rotation mode (no autos): the forced swing carries the
        stack, so the applier still commits one full stack."""
        abilities = {
            "passive": _stacking_dot_passive(),
            "W": _stack_applier(cooldown=20.0, empowers_next_auto=True),
        }
        result = fight(attacker_stats(), abilities, target_armor=0.0)
        row = result["breakdown"]["stacking_dot_passive"]
        assert row["total_damage"] == pytest.approx(100.0)
        assert row["count"] == 1

    def test_no_applications_no_row(self, attacker_stats, fight) -> None:
        """A declared DoT with no hits in the fight emits nothing."""
        result = fight(
            attacker_stats(),
            {"passive": _stacking_dot_passive()},
            target_armor=0.0,
        )
        assert "stacking_dot_passive" not in result["breakdown"]


# ---------------------------------------------------------------------------
# Empowered-auto forced swings: zero-uptime timed fights and Hexoptics amp
# ---------------------------------------------------------------------------


def _empowered_bonus_ability(cooldown: float = 4.0) -> dict:
    """Vayne-Q-shaped entry: bonus physical riding the next basic attack."""
    from src.calculator.ability_spec import DamagePart

    return {
        "name": "Empowered Strike",
        "damage_type": "physical",
        "cooldown": cooldown,
        "parts": (DamagePart("physical", 50.0),),
        "empowers_next_auto": True,
    }


class TestEmpoweredAutoZeroUptimeTimed:
    """A timed fight with zero auto uptime still forces the empowered
    attack per cast — each cast carries bonus + base swing (was 0)."""

    def test_timed_zero_uptime_carries_swings(self, attacker_stats, fight) -> None:
        """cd 4 over 10s = 3 casts x (50 bonus + 100 swing) = 450."""
        result = fight(
            attacker_stats(),
            {"Q": _empowered_bonus_ability(cooldown=4.0)},
            one_rotation=False,
            fight_duration_seconds=10.0,
            auto_attack_uptime=0.0,
            target_armor=0.0,
        )
        assert result["breakdown"]["Q"]["total_damage"] == pytest.approx(450.0)

    def test_timed_with_auto_stream_unchanged(self, attacker_stats, fight) -> None:
        """With autos on, the auto stream hosts the swings: bonus only."""
        result = fight(
            attacker_stats(),
            {"Q": _empowered_bonus_ability(cooldown=4.0)},
            one_rotation=False,
            fight_duration_seconds=10.0,
            auto_attack_uptime=1.0,
            target_armor=0.0,
        )
        assert result["breakdown"]["Q"]["total_damage"] == pytest.approx(150.0)


class TestForcedSwingBasicAmp:
    """Hexoptics C44 amplifies forced basic-attack swings on ability rows
    (they ARE basic attacks), and the info row reports that bonus."""

    def test_one_rotation_swing_amped(self, attacker_stats, fight) -> None:
        """Ranged amp 1.10: 50 bonus (unamped) + 100 swing x 1.10 = 160."""
        result = fight(
            attacker_stats(is_melee=False),
            {"Q": _empowered_bonus_ability()},
            items=[{"name": "Hexoptics C44"}],
            target_armor=0.0,
        )
        assert result["breakdown"]["Q"]["total_damage"] == pytest.approx(160.0)
        amp_row = result["breakdown"]["basic_amp_Hexoptics C44"]
        assert amp_row["total_damage"] == pytest.approx(10.0)


def _timeline_entry(name, cooldown, cast_time=None, damage=100.0):
    """Minimal castable ability entry for cast-timeline tests."""
    entry = {
        "name": name,
        "rank": 5,
        "cooldown": cooldown,
        "damage_type": "magic",
        "total_raw": damage,
        "parts": (DamagePart("magic", damage),),
    }
    if cast_time is not None:
        entry["cast_time"] = cast_time
    return entry


class TestSharedCastTimeline:
    """Timed-mode casts share ONE timeline: each cast occupies its
    cast_time (cooldown runs from cast end), and no ability can start
    while another is mid-cast. Cassiopeia's E-spam exposed the old
    per-ability `1 + T/cd` formula overcounting (5 casts vs ~3 in-game
    over 3s)."""

    @staticmethod
    def _timed(fight, attacker_stats, abilities, duration=3.0):
        return fight(
            attacker_stats(),
            abilities,
            one_rotation=False,
            fight_duration_seconds=duration,
        )

    def test_cast_time_stretches_own_cycle(self, fight, attacker_stats) -> None:
        """cd 0.75 + cast 0.125 = 0.875s cycle: starts at 0/.875/1.75/2.625
        -> 4 casts in 3s (the old cd-only formula said 5)."""
        result = self._timed(
            fight, attacker_stats, {"E": _timeline_entry("Spam", 0.75, 0.125)}
        )
        assert result["breakdown"]["E"]["casts"] == 4

    def test_other_casts_displace_the_spam_spell(self, fight, attacker_stats) -> None:
        """Q (0.5s cast) and R (0.5s) occupy the timeline's first ~1.1s,
        so E only starts at 0.5/1.375/2.25 -> 3 casts, not 4."""
        result = self._timed(
            fight,
            attacker_stats,
            {
                "Q": _timeline_entry("Opener", 10.0, 0.5),
                "E": _timeline_entry("Spam", 0.75, 0.125),
                "R": _timeline_entry("Ult", 60.0, 0.5),
            },
        )
        breakdown = result["breakdown"]
        assert breakdown["Q"]["casts"] == 1
        assert breakdown["E"]["casts"] == 3
        assert breakdown["R"]["casts"] == 1

    def test_zero_cast_time_preserves_legacy_counts(
        self, fight, attacker_stats
    ) -> None:
        """Entries without cast_time are instant: cd 1.0 over 3s casts at
        0/1/2/3 = 4, exactly the old `1 + int(T/cd)`."""
        result = self._timed(fight, attacker_stats, {"Q": _timeline_entry("Bolt", 1.0)})
        assert result["breakdown"]["Q"]["casts"] == 4

    def test_r_still_casts_once_in_timed_mode(self, fight, attacker_stats) -> None:
        """R never recasts on cooldown in timed mode (unchanged rule)."""
        result = self._timed(
            fight,
            attacker_stats,
            {"R": _timeline_entry("Ult", 2.0, 0.5)},
            duration=10.0,
        )
        assert result["breakdown"]["R"]["casts"] == 1
