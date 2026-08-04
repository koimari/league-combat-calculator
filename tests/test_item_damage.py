"""Per-item damage effects exercised through calculate_fight_damage.

One test class per item passive/active, asserting the item's damage
contribution inside a full fight (most use Ahri or a minimal stats dict as
the vehicle). Split from test_item_effects.py by altitude, not by item:
that file unit-tests the ITEM_EFFECTS accessor functions against a patched
registry; this one asserts fight-engine behavior with live parsed item data.
"""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from src.calculator.ability_spec import DamagePart

from src.calculator.champions import (
    parse_champion_abilities as parse_ahri_abilities,
)
from src.calculator.damage import (
    FightConfig,
    calculate_fight_damage,
    _simulate_current_health_on_hit,
    _simulate_stacking_on_hit_damage,
    _calculate_phantom_hits as _calculate_phantom_hits_compiled,
    _calculate_stacking_procs,
)
from src.calculator.item_effects import DamageInputs, resolve_damage_effects


def _build(*names: str) -> list[dict[str, str]]:
    """Build the minimal item shape accepted by the typed resolver."""
    return [{"name": name} for name in names]


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
    total, hits, _per_hit_damages = _simulate_current_health_on_hit(
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
    return total, hits


def _calculate_phantom_hits(num_auto_attacks, item_names):
    """Keep cadence tables readable while production consumes typed rules."""
    effects = resolve_damage_effects([{"name": name} for name in item_names])
    return _calculate_phantom_hits_compiled(num_auto_attacks, effects.phantom_hit)


def _shadowflame_effect():
    """Return the live compiled low-health magic/true crit rule."""
    effect = resolve_damage_effects([{"name": "Shadowflame"}]).magic_true_crit
    assert effect is not None
    return effect


def _simulate_kraken_damage(
    *,
    target_health,
    num_auto_attacks,
    auto_damage_per_hit,
    other_on_hit_per_hit,
    effective_armor,
    is_melee,
    level,
    kraken_proc_autos,
):
    """Readable test adapter around the generic stacking-proc simulation."""
    effects = resolve_damage_effects([{"name": "Kraken Slayer"}])
    effect = effects.stacking_on_hits[0]
    return sum(
        _simulate_stacking_on_hit_damage(
            effect,
            DamageInputs({}, level, is_melee, target_health, target_health),
            target_health,
            num_auto_attacks,
            auto_damage_per_hit,
            other_on_hit_per_hit,
            SimpleNamespace(effective_armor=effective_armor, effective_mr=0.0),
            1.0,
            kraken_proc_autos,
        )
    )


class _FightHarness:
    """Install the shared attacker/fight factories on legacy-style classes."""

    @pytest.fixture(autouse=True)
    def _install_harness(self, attacker_stats, fight) -> None:
        self._make_stats = attacker_stats
        self.fight = fight


class TestBastionbreakerShapedCharge:
    """Tests for Bastionbreaker Shaped Charge passive."""

    @pytest.fixture
    def bastionbreaker(self) -> dict:
        from src.calculator.data_fetcher import get_item_by_name

        return get_item_by_name("Bastionbreaker")

    def test_shaped_charge_ranged_damage(self) -> None:
        """Ranged: 25 + 0.75 * 22 lethality = 41.5 true damage."""
        stats = {"lethality": 22.0}
        effect = resolve_damage_effects(_build("Bastionbreaker")).shaped_charges[0]
        damage = effect.source.raw_damage(
            DamageInputs(stats, 18, False, 1000.0, 1000.0)
        )
        assert abs(damage - 41.5) < 0.01

    def test_shaped_charge_melee_damage(self) -> None:
        """Melee: 50 + 1.5 * 22 lethality = 83 true damage."""
        stats = {"lethality": 22.0}
        effect = resolve_damage_effects(_build("Bastionbreaker")).shaped_charges[0]
        damage = effect.source.raw_damage(DamageInputs(stats, 18, True, 1000.0, 1000.0))
        assert abs(damage - 83.0) < 0.01

    def test_shaped_charge_multiple_procs(self) -> None:
        """20s cooldown: 50s fight = 3 procs."""
        stats = {"lethality": 22.0}
        effect = resolve_damage_effects(_build("Bastionbreaker")).shaped_charges[0]
        per_proc = effect.source.raw_damage(
            DamageInputs(stats, 18, False, 1000.0, 1000.0)
        )
        damage = per_proc * (1 + int(50.0 / effect.cooldown))
        expected = 41.5 * 3
        assert abs(damage - expected) < 0.01

    def test_ahri_full_fight_with_bastionbreaker(
        self,
        ahri_data: dict,
        bastionbreaker: dict,
    ) -> None:
        """Ahri level 18 with only Bastionbreaker, one rotation.

        Shaped Charge should add ~42 true damage.
        """
        from src.calculator.stats import calculate_total_stats

        items = [bastionbreaker]
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
                auto_attack_uptime=0.0,
                one_rotation=True,
            ),
        )
        sc = fight["breakdown"]["shaped_charge_Bastionbreaker"]
        assert (
            abs(sc["total_damage"] - 42) <= 1
        ), f"Shaped Charge {sc['total_damage']:.1f} expected ~42"


class TestRapidFirecannonSharpshooter:
    """Tests for Rapid Firecannon's Sharpshooter energized proc."""

    def test_parsed_values_match_expected(self) -> None:
        """Verify parser extracts 40 magic damage from JSON."""
        from src.calculator.passive_parser import parse_item_effect
        from src.calculator.data_fetcher import fetch_item_data

        items = fetch_item_data()
        parsed = parse_item_effect("Rapid Firecannon", items)
        assert parsed is not None
        assert parsed["base"] == 40.0
        assert parsed["damage_type"] == "magic"


class TestSpellbladeSiblingParsing:
    """Patch passive branches retain non-damage Spellblade effects."""

    def test_parser_extracts_lich_bane_attack_speed(self) -> None:
        from src.calculator.data_fetcher import fetch_item_data
        from src.calculator.passive_parser import parse_item_effect

        parsed = parse_item_effect("Lich Bane", fetch_item_data())
        assert parsed["bonus_attack_speed_percent"] == 50.0

    def test_parser_extracts_dusk_heal(self) -> None:
        from src.calculator.data_fetcher import fetch_item_data
        from src.calculator.passive_parser import parse_item_effect

        parsed = parse_item_effect("Dusk and Dawn", fetch_item_data())
        assert parsed["self_heal_ap_ratio"] == pytest.approx(0.10)
        assert parsed["self_heal_bonus_health_ratio"] == pytest.approx(0.03)

    @pytest.mark.parametrize("item_name", ["Fimbulwinter", "Winter's Approach"])
    def test_parser_extracts_awe_bonus_health_conversion(self, item_name: str) -> None:
        from src.calculator.data_fetcher import fetch_item_data
        from src.calculator.passive_parser import parse_item_effect

        parsed = parse_item_effect(item_name, fetch_item_data())
        assert parsed["bonus_mana_to_health_ratio"] == pytest.approx(0.15)

    def test_parser_extracts_guinsoo_stack_values(self) -> None:
        from src.calculator.data_fetcher import fetch_item_data
        from src.calculator.passive_parser import parse_item_effect

        parsed = parse_item_effect("Guinsoo's Rageblade", fetch_item_data())
        assert parsed["seething_attack_speed_per_stack"] == pytest.approx(0.08)
        assert parsed["seething_max_stacks"] == 4
        assert parsed["seething_duration"] == pytest.approx(3.0)

    def test_parser_extracts_runaan_bolt_scope(self) -> None:
        from src.calculator.data_fetcher import fetch_item_data
        from src.calculator.passive_parser import parse_item_effect

        parsed = parse_item_effect("Runaan's Hurricane", fetch_item_data())
        assert parsed["secondary_ad_ratio"] == pytest.approx(0.55)
        assert parsed["max_secondary_targets"] == 2
        assert parsed["applies_on_hit"] is True

    def test_single_proc_magic_damage(self) -> None:
        """One energized proc: 40 magic damage mitigated by MR."""
        from src.calculator.damage import calculate_fight_damage
        from src.calculator.resistance import apply_resistance

        stats = {
            "attack_damage": 100.0,
            "ability_power": 0.0,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0.0,
            "magic_penetration_percent": 0.0,
            "flat_armor_penetration": 0.0,
            "armor_penetration_percent": 0.0,
            "lethality": 0.0,
            "critical_strike_chance": 0.0,
            "is_melee": False,
            "level": 18,
        }
        import random

        random.seed(0)
        fight = calculate_fight_damage(
            stats,
            {},
            [{"name": "Rapid Firecannon"}],
            FightConfig(
                target_health=2000,
                target_armor=0,
                target_magic_resistance=100,
                fight_duration_seconds=5.0,
                auto_attack_uptime=1.0,
            ),
        )
        rfc = fight["breakdown"]["on_hit_once_Rapid Firecannon"]
        # 100 MR, no magic pen → effective MR = 100
        expected = apply_resistance(40.0, 100.0)
        assert abs(rfc["total_damage"] - expected) < 0.01
        assert rfc["damage_type"] == "magic"

    def test_no_proc_without_autos(self) -> None:
        """No auto attacks means no energized proc."""
        from src.calculator.damage import calculate_fight_damage

        stats = {
            "attack_damage": 100.0,
            "ability_power": 0.0,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0.0,
            "magic_penetration_percent": 0.0,
            "flat_armor_penetration": 0.0,
            "armor_penetration_percent": 0.0,
            "lethality": 0.0,
            "critical_strike_chance": 0.0,
            "is_melee": False,
            "level": 18,
        }
        fight = calculate_fight_damage(
            stats,
            {},
            [{"name": "Rapid Firecannon"}],
            FightConfig(
                target_health=2000,
                target_armor=0,
                target_magic_resistance=50,
                fight_duration_seconds=5.0,
                auto_attack_uptime=0.0,
            ),
        )
        assert "on_hit_once_Rapid Firecannon" not in fight["breakdown"]


class TestOverlordBloodmailTyranny:
    """Tests for Overlord's Bloodmail Tyranny passive parser."""

    def test_parsed_ratio_matches_expected(self) -> None:
        """Verify parser extracts the 2.5% bonus health to AD ratio."""
        from src.calculator.passive_parser import parse_item_effect
        from src.calculator.data_fetcher import fetch_item_data

        items = fetch_item_data()
        parsed = parse_item_effect("Overlord's Bloodmail", items)
        assert parsed is not None
        assert abs(parsed["bonus_health_to_ad_ratio"] - 0.025) < 0.001
        assert parsed["retribution_missing_health_min"] == pytest.approx(0.0)
        assert parsed["retribution_missing_health_max"] == pytest.approx(0.70)


def test_thornmail_parser_extracts_bonus_armor_thorns() -> None:
    from src.calculator.data_fetcher import fetch_item_data
    from src.calculator.passive_parser import parse_item_effect

    parsed = parse_item_effect("Thornmail", fetch_item_data())
    assert parsed["base"] == pytest.approx(20.0)
    assert parsed["bonus_armor_ratio"] == pytest.approx(0.10)
    assert parsed["grievous_duration"] == pytest.approx(3.0)


class TestBloodlettersCurseVileDecay:
    """Tests for Bloodletter's Curse stacking MR reduction passive."""

    @pytest.fixture
    def bloodletters(self) -> dict:
        from src.calculator.data_fetcher import get_item_by_name

        return get_item_by_name("Bloodletter's Curse")

    def test_stacking_mr_reduction_helper(self) -> None:
        """The build projection carries a typed stacking-reduction rule."""
        effect = resolve_damage_effects(
            [{"name": "Bloodletter's Curse"}]
        ).stacking_mr_reduction
        assert effect is not None
        assert effect.reduction_per_stack == 0.075
        assert effect.max_stacks == 4

    def test_no_stacking_mr_reduction_without_item(self) -> None:
        """Unrelated builds carry no stacking-reduction rule."""
        effects = resolve_damage_effects([{"name": "Liandry's Torment"}])
        assert effects.stacking_mr_reduction is None

    def test_effective_mr_decreases_per_ability(
        self,
        ahri_data: dict,
        bloodletters: dict,
    ) -> None:
        """Final effective MR should be lower than base when stacks apply."""
        from src.calculator.stats import calculate_total_stats

        items = [bloodletters]
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
                auto_attack_uptime=0.0,
                one_rotation=True,
            ),
        )
        # 4 stacks = 30% MR reduction: 100 * 0.70 = 70 effective MR
        assert fight["effective_mr"] == pytest.approx(70.0, abs=0.1)

    def test_ahri_level18_total_damage_within_tolerance(
        self,
        ahri_data: dict,
        bloodletters: dict,
    ) -> None:
        """Ahri level 18 with Bloodletter's Curse, one rotation.

        Target: 1000 HP, 100 MR, 100 Armor.
        Expected ~919 total damage (within ±5%).
        """
        from src.calculator.stats import calculate_total_stats

        items = [bloodletters]
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
                auto_attack_uptime=0.0,
                one_rotation=True,
            ),
        )
        expected = 919
        actual = fight["total_damage"]
        tolerance = expected * 0.05
        assert abs(actual - expected) <= tolerance, (
            f"Total damage {actual:.1f} not within 5% of {expected} "
            f"(diff: {abs(actual - expected) / expected * 100:.1f}%)"
        )

    def test_damage_higher_than_without_passive(
        self,
        ahri_data: dict,
        bloodletters: dict,
    ) -> None:
        """Damage with Bloodletter's Curse should exceed damage without MR reduction."""
        from src.calculator.stats import calculate_total_stats

        items = [bloodletters]
        stats = calculate_total_stats(ahri_data, 18, items)
        abilities = parse_ahri_abilities(ahri_data, 18, stats["ability_power"])

        fight_with = calculate_fight_damage(
            stats,
            abilities,
            items,
            FightConfig(
                target_health=1000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=5.0,
                auto_attack_uptime=0.0,
                one_rotation=True,
            ),
        )
        # Without item: no MR reduction passive
        fight_without = calculate_fight_damage(
            stats,
            abilities,
            [],
            FightConfig(
                target_health=1000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=5.0,
                auto_attack_uptime=0.0,
                one_rotation=True,
            ),
        )
        assert fight_with["total_damage"] > fight_without["total_damage"]

    def test_no_effect_on_physical_only_damage(self) -> None:
        """Stacking MR reduction should not affect physical-only abilities."""
        # Craft a minimal physical-only scenario
        stats = {
            "attack_damage": 100,
            "ability_power": 0,
            "attack_speed": 0.625,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 0,
            "is_melee": True,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test Physical",
                "rank": 1,
                "cooldown": 5.0,
                "physical_damage": 200,
                "parts": (DamagePart("physical", 200),),
                "total_raw": 200,
                "damage_type": "physical",
            },
        }
        items_with = [{"name": "Bloodletter's Curse"}]

        fight_with = calculate_fight_damage(
            stats,
            abilities,
            items_with,
            FightConfig(
                target_health=1000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=1.0,
                one_rotation=True,
            ),
        )
        fight_without = calculate_fight_damage(
            stats,
            abilities,
            [],
            FightConfig(
                target_health=1000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=1.0,
                one_rotation=True,
            ),
        )
        assert fight_with["breakdown"]["Q"]["total_damage"] == pytest.approx(
            fight_without["breakdown"]["Q"]["total_damage"], abs=0.01
        )


class TestShadowflameCinderbloom:
    """Tests for Shadowflame Cinderbloom passive (magic/true crit below 40% HP)."""

    @pytest.fixture
    def shadowflame(self) -> dict:
        from src.calculator.data_fetcher import get_item_by_name

        return get_item_by_name("Shadowflame")

    def test_shadowflame_item_effect_registered(self) -> None:
        """Shadowflame should be registered in ITEM_EFFECTS."""
        from src.calculator.item_effects import ITEM_EFFECTS

        effect = ITEM_EFFECTS.get("Shadowflame")
        assert effect is not None
        assert effect["type"] == "magic_true_crit"
        assert effect["crit_multiplier"] == 1.20
        assert effect["health_threshold"] == 0.40

    def test_no_bonus_when_target_above_threshold(self) -> None:
        """No Shadowflame bonus when all damage is dealt above 40% HP."""
        from src.calculator.damage import _calculate_shadowflame_bonus

        breakdown = {
            "Q": {
                "name": "Test",
                "casts": 1,
                "total_damage": 100.0,
                "damage_type": "magic",
            },
        }
        ability_damages = {
            "Q": {
                "damage_type": "magic",
                "magic_damage": 100,
                "total_raw": 100,
                "parts": (DamagePart("magic", 100),),
            },
        }
        # Target at 1000 HP, threshold 400 — 100 damage won't cross it
        bonus, _ = _calculate_shadowflame_bonus(
            _shadowflame_effect(), breakdown, ability_damages, 1000.0
        )
        assert bonus == 0.0

    def test_bonus_when_target_below_threshold(self) -> None:
        """Damage dealt when target is below 40% should get 20% bonus."""
        from src.calculator.damage import _calculate_shadowflame_bonus

        # Q does 700 damage (drops target from 1000 to 300, below 400)
        # W does 200 magic damage (target already below 40%)
        breakdown = {
            "Q": {
                "name": "Big Nuke",
                "casts": 1,
                "total_damage": 700.0,
                "damage_type": "magic",
            },
            "W": {
                "name": "Follow Up",
                "casts": 1,
                "total_damage": 200.0,
                "damage_type": "magic",
            },
            "auto_attacks": {
                "name": "Auto Attacks",
                "total_damage": 0.0,
                "damage_type": "physical",
            },
        }
        ability_damages = {
            "Q": {
                "damage_type": "magic",
                "magic_damage": 700,
                "total_raw": 700,
                "parts": (DamagePart("magic", 700),),
            },
            "W": {
                "damage_type": "magic",
                "magic_damage": 200,
                "total_raw": 200,
                "parts": (DamagePart("magic", 200),),
            },
        }
        bonus, _ = _calculate_shadowflame_bonus(
            _shadowflame_effect(), breakdown, ability_damages, 1000.0
        )
        # W (200) dealt below threshold, gets 20% bonus = 40
        assert abs(bonus - 40.0) < 0.01

    def test_magic_shield_delays_shadowflame_health_threshold(self) -> None:
        """A ready magic shield must absorb events before health falls."""
        from src.calculator.damage import _calculate_shadowflame_bonus

        breakdown = {
            slot: {
                "name": slot,
                "casts": 1,
                "total_damage": 400.0,
                "damage_type": "magic",
            }
            for slot in ("Q", "W", "E")
        }
        ability_damages = {
            slot: {
                "damage_type": "magic",
                "magic_damage": 400.0,
                "total_raw": 400.0,
                "parts": (DamagePart("magic", 400.0),),
            }
            for slot in ("Q", "W", "E")
        }

        no_shield, _ = _calculate_shadowflame_bonus(
            _shadowflame_effect(), breakdown, ability_damages, 1000.0
        )
        shielded, _ = _calculate_shadowflame_bonus(
            _shadowflame_effect(),
            breakdown,
            ability_damages,
            1000.0,
            target_magic_shield=300.0,
        )

        assert no_shield == pytest.approx(80.0)
        assert shielded == 0.0

    def test_timed_cast_timeline_controls_threshold_crossing(self) -> None:
        """Recasts must not be grouped ahead of intervening abilities."""
        from src.calculator.damage import _calculate_shadowflame_bonus

        breakdown = {
            "Q": {
                "name": "Repeat cast",
                "casts": 2,
                "total_damage": 1000.0,
                "damage_type": "magic",
            },
            "W": {
                "name": "Intervening cast",
                "casts": 1,
                "total_damage": 200.0,
                "damage_type": "magic",
            },
        }
        ability_damages = {
            "Q": {"damage_type": "magic", "parts": (DamagePart("magic", 500),)},
            "W": {"damage_type": "magic", "parts": (DamagePart("magic", 200),)},
        }

        bonus, _ = _calculate_shadowflame_bonus(
            _shadowflame_effect(),
            breakdown,
            ability_damages,
            1000.0,
            cast_order=["Q", "W"],
            cast_events=[
                {"time": 0.0, "slot": "Q", "ordinal": 1},
                {"time": 1.0, "slot": "W", "ordinal": 1},
                {"time": 2.0, "slot": "Q", "ordinal": 2},
            ],
        )

        # Q1 leaves 500 HP, W leaves 300 HP, so only Q2 lands below 40%.
        assert bonus == pytest.approx(100.0)

    def test_lifeline_shield_delays_shadowflame_health_threshold(self) -> None:
        from src.calculator.damage import _calculate_shadowflame_bonus

        breakdown = {
            slot: {
                "name": slot,
                "casts": 1,
                "total_damage": damage,
                "damage_type": "magic",
            }
            for slot, damage in (("Q", 600.0), ("W", 200.0), ("E", 200.0))
        }
        abilities = {
            slot: {"damage_type": "magic", "parts": (DamagePart("magic", damage),)}
            for slot, damage in (("Q", 600.0), ("W", 200.0), ("E", 200.0))
        }

        no_lifeline, _ = _calculate_shadowflame_bonus(
            _shadowflame_effect(), breakdown, abilities, 1000.0
        )
        lifeline, _ = _calculate_shadowflame_bonus(
            _shadowflame_effect(),
            breakdown,
            abilities,
            1000.0,
            target_threshold_shield_amount=400.0,
            target_threshold_shield_health_ratio=0.30,
            target_threshold_shield_duration=3.0,
        )

        assert no_lifeline == pytest.approx(40.0)
        assert lifeline == 0.0

    def test_physical_damage_not_affected(self) -> None:
        """Physical damage below threshold should not get Shadowflame bonus."""
        from src.calculator.damage import _calculate_shadowflame_bonus

        breakdown = {
            "Q": {
                "name": "Nuke",
                "casts": 1,
                "total_damage": 700.0,
                "damage_type": "magic",
            },
            "auto_attacks": {
                "name": "Auto Attacks",
                "total_damage": 200.0,
                "damage_type": "physical",
            },
        }
        ability_damages = {
            "Q": {
                "damage_type": "magic",
                "magic_damage": 700,
                "total_raw": 700,
                "parts": (DamagePart("magic", 700),),
            },
        }
        bonus, _ = _calculate_shadowflame_bonus(
            _shadowflame_effect(), breakdown, ability_damages, 1000.0
        )
        # Auto attacks are physical — no crit bonus
        assert bonus == 0.0

    def test_mixed_damage_splits_correctly(self) -> None:
        """Mixed abilities (like Ahri Q) should split into magic and true events."""
        from src.calculator.damage import _calculate_shadowflame_bonus

        # Q: 300 magic (mitigated) + 500 true = 800 total
        # Target at 1000 HP: after Q magic (300), HP = 700 (above 400)
        # After Q true (500), HP = 200 (Q true hit at 700, above 400)
        # W: 150 magic at HP 200 (below 400) → bonus = 150 * 0.2 = 30
        breakdown = {
            "Q": {
                "name": "Orb",
                "casts": 1,
                "total_damage": 800.0,
                "damage_type": "mixed",
                # The rotation attaches the exact mitigated composition
                # to every mixed row; Cinderbloom reads it directly.
                "damage_by_type": {"magic": 300.0, "true": 500.0},
            },
            "W": {
                "name": "Fire",
                "casts": 1,
                "total_damage": 150.0,
                "damage_type": "magic",
            },
            "auto_attacks": {
                "name": "Auto Attacks",
                "total_damage": 0.0,
                "damage_type": "physical",
            },
        }
        ability_damages = {
            "Q": {
                "damage_type": "mixed",
                "magic_damage": 500,
                "true_damage": 500,
                "parts": (
                    DamagePart("magic", 500),
                    DamagePart("true", 500),
                ),
                "total_raw": 1000,
            },
            "W": {
                "damage_type": "magic",
                "magic_damage": 150,
                "total_raw": 150,
                "parts": (DamagePart("magic", 150),),
            },
        }
        bonus, _ = _calculate_shadowflame_bonus(
            _shadowflame_effect(), breakdown, ability_damages, 1000.0
        )
        assert abs(bonus - 30.0) < 0.01

    def test_damage_higher_with_shadowflame(
        self,
        ahri_data: dict,
        shadowflame: dict,
    ) -> None:
        """Ahri's total damage should increase with Shadowflame passive."""
        from src.calculator.stats import calculate_total_stats

        items = [shadowflame]
        stats = calculate_total_stats(ahri_data, 18, items)
        abilities = parse_ahri_abilities(ahri_data, 18, stats["ability_power"])

        fight_with = calculate_fight_damage(
            stats,
            abilities,
            items,
            FightConfig(
                target_health=1000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=5.0,
                auto_attack_uptime=0.0,
                one_rotation=True,
            ),
        )
        fight_without = calculate_fight_damage(
            stats,
            abilities,
            [],
            FightConfig(
                target_health=1000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=5.0,
                auto_attack_uptime=0.0,
                one_rotation=True,
            ),
        )
        assert fight_with["total_damage"] > fight_without["total_damage"]
        assert "shadowflame_Shadowflame" in fight_with["breakdown"]

    def test_ahri_full_build_within_tolerance(self, ahri_data: dict) -> None:
        """Ahri level 18, 6 items vs 1000 HP / 100 Armor / 100 MR.

        Items: Rabadon's, Liandry's, Bloodletter's Curse, Malignance,
               Shadowflame, Blackfire Torch.
        Expected AP: 717, expected total damage ~3700 (within 5%).
        """
        from src.calculator.data_fetcher import get_item_by_name
        from src.calculator.stats import calculate_total_stats

        items = [
            get_item_by_name("Rabadon's Deathcap"),
            get_item_by_name("Liandry's Torment"),
            get_item_by_name("Bloodletter's Curse"),
            get_item_by_name("Malignance"),
            get_item_by_name("Shadowflame"),
            get_item_by_name("Blackfire Torch"),
        ]
        stats = calculate_total_stats(ahri_data, 18, items)
        assert stats["ability_power"] == 717

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
                auto_attack_uptime=0.0,
                one_rotation=True,
            ),
        )
        expected = 3700
        actual = fight["total_damage"]
        tolerance = expected * 0.05
        assert abs(actual - expected) <= tolerance, (
            f"Total damage {actual:.1f} not within 5% of {expected} "
            f"(diff: {abs(actual - expected) / expected * 100:.1f}%)"
        )

    def test_synthetic_recast_row_counted_once(self) -> None:
        """A synthetic recast row (e.g. Ambessa Q2) is one damage event, not two.

        Q (400) and Q2 (400) drop the target from 1000 to 200; W (300 magic)
        then lands below the 400 threshold -> bonus = 300 * 0.2 = 60.
        Counting the Q2 breakdown row AGAIN as an "item effect" event would
        add a bogus below-threshold event worth another 80.
        """
        from src.calculator.damage import _calculate_shadowflame_bonus

        breakdown = {
            "Q": {
                "name": "Cast",
                "casts": 1,
                "total_damage": 400.0,
                "damage_type": "magic",
            },
            "Q2": {
                "name": "Recast",
                "casts": 1,
                "total_damage": 400.0,
                "damage_type": "magic",
            },
            "W": {
                "name": "Follow Up",
                "casts": 1,
                "total_damage": 300.0,
                "damage_type": "magic",
            },
        }
        ability_damages = {
            "Q": {
                "damage_type": "magic",
                "magic_damage": 400,
                "total_raw": 400,
                "parts": (DamagePart("magic", 400),),
            },
            "Q2": {
                "damage_type": "magic",
                "magic_damage": 400,
                "parts": (DamagePart("magic", 400),),
                "total_raw": 400,
                "recast_of": "Q",
            },
            "W": {
                "damage_type": "magic",
                "magic_damage": 300,
                "total_raw": 300,
                "parts": (DamagePart("magic", 300),),
            },
        }
        # Default cast_order includes "Q2" — step 1 already consumes it.
        bonus, _ = _calculate_shadowflame_bonus(
            _shadowflame_effect(), breakdown, ability_damages, 1000.0
        )
        assert abs(bonus - 60.0) < 0.01

    def test_ambessa_q2_and_luden_have_one_ledger_position(
        self,
        ambessa_data: dict,
        shadowflame: dict,
        parse_at,
    ) -> None:
        """A real synthetic recast and a triggered proc each enter once."""
        from src.calculator.data_fetcher import get_item_by_name
        from src.calculator.damage import _ordered_damage_events

        items = [shadowflame, get_item_by_name("Luden's Echo")]
        stats, abilities = parse_at(ambessa_data, 18, items=items)

        fight = calculate_fight_damage(
            dict(stats),
            abilities,
            items,
            FightConfig(
                target_health=100000.0,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=5.0,
                auto_attack_uptime=0.0,
                one_rotation=True,
            ),
        )
        events = _ordered_damage_events(
            fight["breakdown"],
            abilities,
            ["Q", "Q2", "W", "E", "R"],
            cast_events=fight["cast_timeline"],
        )
        q2_events = [event for event in events if event["source_key"] == "Q2"]
        luden_events = [
            event for event in events if event["source_key"] == "proc_Luden's Echo"
        ]

        assert sum(event["damage"] for event in q2_events) == pytest.approx(
            fight["breakdown"]["Q2"]["total_damage"]
        )
        assert len(luden_events) == 1
        assert luden_events[0]["order"] == pytest.approx(0.5)


class TestActualizerAmpRow:
    """The informational Actualizer row must reflect only rows the amp touched.

    The ability amp is applied in exactly two places in the fight engine:
    rotation ability rows (cast_order keys, damage.py step 2) and
    ``is_ability_damage`` item procs (Stormsurge / Zaz'Zak's Realmspike,
    step 7).  The display-only ``ability_amp_*`` row's "amplified base"
    must mirror that exact set — not burns, on-hits, or other item rows.
    """

    @pytest.fixture
    def actualizer(self) -> dict:
        from src.calculator.data_fetcher import get_item_by_name

        return get_item_by_name("Actualizer")

    @staticmethod
    def _run(ahri_data: dict, items: list) -> dict:
        from src.calculator.stats import calculate_total_stats

        stats = calculate_total_stats(ahri_data, 18, items)
        abilities = parse_ahri_abilities(ahri_data, 18, stats["ability_power"])
        return calculate_fight_damage(
            stats,
            abilities,
            items,
            FightConfig(
                target_health=1000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=5.0,
                auto_attack_uptime=0.0,
                one_rotation=True,
                include_actives=True,
            ),
        )

    @staticmethod
    def _amp_row_and_expected(fight: dict, extra_keys: tuple = ()) -> tuple:
        """Return (amp row, hand-computed bonus over the rows the amp touched)."""
        breakdown = fight["breakdown"]
        row = breakdown["ability_amp_Actualizer"]
        amp = row["multiplier"]
        amped_keys = ("Q", "Q2", "W", "E", "R") + extra_keys
        base = sum(
            breakdown[key]["total_damage"] for key in amped_keys if key in breakdown
        )
        # base already includes the amp: contribution = base * (amp-1) / amp.
        return row, base * (amp - 1.0) / amp

    def test_amp_row_excludes_burn_rows(
        self,
        ahri_data: dict,
        liandrys: dict,
        actualizer: dict,
    ) -> None:
        """Liandry's burn is not ability-amped; it must not inflate the row."""
        fight = self._run(ahri_data, [actualizer, liandrys])
        assert any(key.startswith("burn_") for key in fight["breakdown"])
        row, expected = self._amp_row_and_expected(fight)
        assert row["total_damage"] == pytest.approx(expected, abs=0.01)

    def test_amp_row_includes_ability_damage_procs(
        self,
        ahri_data: dict,
        actualizer: dict,
    ) -> None:
        """Stormsurge's proc IS ability-amped and belongs in the row's base."""
        from src.calculator.data_fetcher import get_item_by_name

        fight = self._run(ahri_data, [actualizer, get_item_by_name("Stormsurge")])
        assert "proc_Stormsurge" in fight["breakdown"]
        row, expected = self._amp_row_and_expected(fight, ("proc_Stormsurge",))
        assert row["total_damage"] == pytest.approx(expected, abs=0.01)


class TestBurnRefreshWindow:
    """Burn windows stretch by the rotation cast spread.

    Only a multi-instance R (Ahri: cast_instances=3) adds dash spread;
    a plain single-instance R must not inherit Ahri's dash count.
    """

    _STATS = {
        "attack_damage": 60.0,
        "base_attack_damage": 60.0,
        "attack_speed": 0.7,
        "attack_speed_ratio": 0.625,
        "critical_strike_chance": 0.0,
        "magic_penetration_flat": 0.0,
        "magic_penetration_percent": 0.0,
        "armor_penetration_percent": 0.0,
        "lethality": 0.0,
        "ability_power": 100.0,
        "is_melee": False,
        "level": 18,
    }

    def _fight(self, abilities, item_names):
        from src.calculator.data_fetcher import get_item_by_name

        return calculate_fight_damage(
            dict(self._STATS),
            abilities,
            [get_item_by_name(n) for n in item_names],
            FightConfig(
                target_health=2000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=5.0,
                auto_attack_uptime=0.0,
                one_rotation=True,
                cast_order=[k for k in ("Q", "R") if k in abilities],
            ),
        )

    @staticmethod
    def _r_entry(cast_instances=None):
        entry = {
            "name": "Test R",
            "parts": (DamagePart("magic", 300.0),),
            "total_raw": 300.0,
            "damage_type": "magic",
            "cooldown": 60.0,
        }
        if cast_instances is not None:
            entry["cast_instances"] = cast_instances
        return entry

    _Q = {
        "name": "Test Q",
        "parts": (DamagePart("magic", 200.0),),
        "total_raw": 200.0,
        "damage_type": "magic",
        "cooldown": 6.0,
    }

    def test_single_instance_r_adds_no_dash_spread(self) -> None:
        """A plain R must not inherit Ahri's 3-dash burn-window stretch.

        Q + R one-rotation: base spread = (2 - 1) * 0.5s. With
        cast_instances=3 the window gains 2 dashes x 0.5s; the plain-R
        window must be exactly the base. Burn totals scale linearly with
        (spread + duration), so the ratio pins both windows.
        """
        (burn,) = resolve_damage_effects(_build("Liandry's Torment")).burns
        duration = burn.duration

        plain = self._fight(
            {"Q": dict(self._Q), "R": self._r_entry()},
            ["Liandry's Torment"],
        )
        dashes = self._fight(
            {"Q": dict(self._Q), "R": self._r_entry(cast_instances=3)},
            ["Liandry's Torment"],
        )
        burn_key = next(k for k in plain["breakdown"] if k.startswith("burn_"))
        plain_burn = plain["breakdown"][burn_key]["total_damage"]
        dash_burn = dashes["breakdown"][burn_key]["total_damage"]

        base_spread = 0.5  # (2 casts - 1) * 0.5s
        expected_ratio = (base_spread + 1.0 + duration) / (base_spread + duration)
        assert dash_burn / plain_burn == pytest.approx(expected_ratio)

    def test_champion_dot_extends_burn_refresh_window(self) -> None:
        """An entry's dot_duration (Brand's Blaze) stretches the burn.

        The champion DoT keeps dealing ability damage for its tail after
        the last cast, and every tick refreshes the burn: window =
        spread + tail + duration. Burn totals scale linearly with the
        window, so the ratio pins the semantics.
        """
        (burn,) = resolve_damage_effects(_build("Liandry's Torment")).burns
        duration = burn.duration

        plain = self._fight(
            {"Q": dict(self._Q), "R": self._r_entry()},
            ["Liandry's Torment"],
        )
        with_dot = self._fight(
            {
                "Q": dict(self._Q),
                "R": self._r_entry(),
                "P": {
                    "name": "Test Blaze",
                    "parts": (DamagePart("magic", 60.0, count=3),),
                    "total_raw": 180.0,
                    "damage_type": "magic",
                    "proc_count": 1,
                    "dot_duration": 4.0,
                },
            },
            ["Liandry's Torment"],
        )
        burn_key = next(k for k in plain["breakdown"] if k.startswith("burn_"))
        plain_burn = plain["breakdown"][burn_key]["total_damage"]
        dot_burn = with_dot["breakdown"][burn_key]["total_damage"]

        spread = 0.5  # (2 casts - 1) x 0.5s; the P proc entry is not a cast
        expected_ratio = (spread + 4.0 + duration) / (spread + duration)
        assert dot_burn / plain_burn == pytest.approx(expected_ratio)

    def test_hatefog_refresh_window_uses_seconds_not_dash_count(self) -> None:
        """Malignance's Hatefog starts at R1: cast_spread minus the dash
        spread in SECONDS (r_extra x 0.5s), not minus the dash count."""
        (burn,) = resolve_damage_effects(_build("Liandry's Torment")).burns
        (hatefog,) = resolve_damage_effects(_build("Malignance")).ultimate_procs
        duration = burn.duration

        fight = self._fight(
            {"R": self._r_entry(cast_instances=3)},
            ["Liandry's Torment", "Malignance"],
        )
        burn_key = next(k for k in fight["breakdown"] if k.startswith("burn_"))
        actual = fight["breakdown"][burn_key]["total_damage"]

        # One R cast, 3 instances: spread = 2 dashes x 0.5s = 1.0s;
        # R1 lands at spread - 2 x 0.5s = 0.0s; hatefog runs to its
        # duration; burn refreshes until hatefog ends.
        dot_refresh_end = max(1.0, 0.0 + hatefog.duration)
        inputs = DamageInputs(dict(self._STATS), 18, False, 2000.0, 2000.0)
        raw = burn.source.raw_damage(inputs)
        raw *= (dot_refresh_end + duration) / duration
        from src.calculator.resistance import apply_resistance

        expected = apply_resistance(raw, fight["effective_mr"])
        assert actual == pytest.approx(expected, rel=1e-6)


class TestBurnTimedModeUptime:
    """In time-based mode, recasting abilities keep refreshing the burn.

    The refresh window must run to the fight's LAST cast (spaced by
    cooldowns across the duration), not the 0.5s-per-cast combo spread —
    user bug: Liandry's in a 10s fight showed barely more than one
    3-second application (~240 raw) instead of near-continuous uptime
    (in-game measured ~2% max HP/s for the whole fight).
    """

    _STATS = {
        "attack_damage": 60.0,
        "base_attack_damage": 60.0,
        "attack_speed": 0.7,
        "attack_speed_ratio": 0.625,
        "critical_strike_chance": 0.0,
        "magic_penetration_flat": 0.0,
        "magic_penetration_percent": 0.0,
        "armor_penetration_percent": 0.0,
        "lethality": 0.0,
        "ability_power": 100.0,
        "is_melee": False,
        "level": 18,
    }

    def _fight(self, abilities, duration=10.0):
        from src.calculator.data_fetcher import get_item_by_name

        return calculate_fight_damage(
            dict(self._STATS),
            abilities,
            [get_item_by_name("Liandry's Torment")],
            FightConfig(
                target_health=4000,
                target_armor=50,
                target_magic_resistance=50,
                fight_duration_seconds=duration,
                auto_attack_uptime=0.0,
                one_rotation=False,
                cast_order=[k for k in ("Q", "R") if k in abilities],
            ),
        )

    def _expected_burn(self, fight, uptime_seconds):
        from src.calculator.resistance import apply_resistance

        (burn,) = resolve_damage_effects(_build("Liandry's Torment")).burns
        inputs = DamageInputs(dict(self._STATS), 18, False, 4000.0, 4000.0)
        raw = burn.source.raw_damage(inputs) * (uptime_seconds / burn.duration)
        return apply_resistance(raw, fight["effective_mr"])

    @staticmethod
    def _q_entry(cooldown):
        return {
            "name": "Test Q",
            "parts": (DamagePart("magic", 200.0),),
            "total_raw": 200.0,
            "damage_type": "magic",
            "cooldown": cooldown,
        }

    def test_recasting_ability_burn_resolves_past_fight_end(self) -> None:
        """Q on a 4s cooldown over 10s casts at t=0/4/8: the t=8 refresh
        ticks until the burn expires at t=11 — uptime 11s, NOT capped at
        the 10s fight. User bug (Cassiopeia + Blackfire, 3s fight): the
        cap priced the burn as rate x fight_duration (~30) while the
        in-game burn resolved its full window (~90)."""
        fight = self._fight({"Q": self._q_entry(4.0)})
        burn_key = next(k for k in fight["breakdown"] if k.startswith("burn_"))
        actual = fight["breakdown"][burn_key]["total_damage"]
        assert actual == pytest.approx(self._expected_burn(fight, 11.0), rel=1e-6)

    def test_single_cast_abilities_keep_combo_spread(self) -> None:
        """Nothing recasts (Q cd 100, R cd 60): the burn window stays
        the GCD combo spread + burn duration — a sparse caster must NOT
        get fight-long burn uptime."""
        fight = self._fight(
            {
                "Q": self._q_entry(100.0),
                "R": {
                    "name": "Test R",
                    "parts": (DamagePart("magic", 300.0),),
                    "total_raw": 300.0,
                    "damage_type": "magic",
                    "cooldown": 60.0,
                },
            }
        )
        burn_key = next(k for k in fight["breakdown"] if k.startswith("burn_"))
        actual = fight["breakdown"][burn_key]["total_damage"]
        # 2 casts, 0.5s apart -> last hit t=0.5, burn to t=3.5
        assert actual == pytest.approx(self._expected_burn(fight, 3.5), rel=1e-6)


class TestSheenSpellblade:
    """Sheen is the sourced component shared by the Spellblade family."""

    def test_parser_reads_cached_spellblade_values(self) -> None:
        from src.calculator.data_fetcher import fetch_item_data
        from src.calculator.passive_parser import parse_item_effect

        parsed = parse_item_effect("Sheen", fetch_item_data())
        assert parsed == {
            "damage_type": "physical",
            "base_ad_ratio": 1.0,
            "cooldown": 1.5,
            "weave_delay": 1.5,
        }

    def test_spellblade_compiles_and_scales_from_base_ad(self) -> None:
        effect = resolve_damage_effects(_build("Sheen")).spellblade
        assert effect is not None
        assert effect.source.item_name == "Sheen"
        assert effect.cooldown == pytest.approx(1.5)
        assert effect.weave_delay == pytest.approx(1.5)
        assert effect.source.raw_damage(
            DamageInputs({"base_attack_damage": 110.0}, 18, True, 1000.0, 1000.0)
        ) == pytest.approx(110.0)

    def test_spellblade_procs_in_the_existing_timed_event_pipeline(
        self,
        ahri_data: dict,
    ) -> None:
        from src.calculator.data_fetcher import get_item_by_name
        from src.calculator.stats import calculate_total_stats

        item = get_item_by_name("Sheen")
        items = [item]
        stats = calculate_total_stats(ahri_data, 18, items)
        abilities = parse_ahri_abilities(ahri_data, 18, stats["ability_power"])
        result = calculate_fight_damage(
            stats,
            abilities,
            items,
            FightConfig(
                target_health=3000.0,
                target_armor=0.0,
                target_magic_resistance=0.0,
                fight_duration_seconds=5.0,
                auto_attack_uptime=1.0,
            ),
        )
        row = result["breakdown"]["spellblade_Sheen"]
        assert row["count"] >= 1
        assert row["damage_type"] == "physical"


class TestBloodsongSpellbladeAndExposeWeakness:
    """Tests for Bloodsong's Spellblade and Expose Weakness passives."""

    @pytest.fixture
    def bloodsong(self) -> dict:
        from src.calculator.data_fetcher import get_item_by_name

        return get_item_by_name("Bloodsong")

    def test_bloodsong_registered_as_spellblade(self) -> None:
        """Bloodsong should be in ITEM_EFFECTS with type spellblade."""
        from src.calculator.item_effects import ITEM_EFFECTS

        effect = ITEM_EFFECTS.get("Bloodsong")
        assert effect is not None
        assert effect["type"] == "spellblade"
        assert effect["base_ad_ratio"] == 1.0
        assert effect["damage_type"] == "physical"

    def test_spellblade_damage_equals_base_ad(self) -> None:
        """Bloodsong spellblade should deal 100% base AD."""
        stats = {"base_attack_damage": 104.0}
        effect = resolve_damage_effects(_build("Bloodsong")).spellblade
        assert effect is not None
        damage = effect.source.raw_damage(DamageInputs(stats, 18, False, 1000, 1000))
        assert abs(damage - 104.0) < 0.01

    def test_two_procs_in_five_second_fight(
        self,
        ahri_data: dict,
        bloodsong: dict,
    ) -> None:
        """Bloodsong should proc twice in a 5-second fight (CD starts after attack)."""
        from src.calculator.stats import calculate_total_stats

        items = [bloodsong]
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
                auto_attack_uptime=1.0,
                one_rotation=False,
            ),
        )
        sb = fight["breakdown"]["spellblade_Bloodsong"]
        assert sb["count"] == 2

    def test_expose_weakness_present_in_breakdown(
        self,
        ahri_data: dict,
        bloodsong: dict,
    ) -> None:
        """Expose Weakness bonus should appear in the fight breakdown."""
        from src.calculator.stats import calculate_total_stats

        items = [bloodsong]
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
                auto_attack_uptime=1.0,
                one_rotation=False,
            ),
        )
        assert "expose_weakness_Bloodsong" in fight["breakdown"]
        ew = fight["breakdown"]["expose_weakness_Bloodsong"]
        assert ew["total_damage"] > 0

    def test_expose_weakness_uses_ranged_rate_for_ahri(
        self,
        ahri_data: dict,
        bloodsong: dict,
    ) -> None:
        """Ahri is ranged; Expose Weakness should use the 5% rate."""
        from src.calculator.stats import calculate_total_stats

        items = [bloodsong]
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
                auto_attack_uptime=1.0,
                one_rotation=False,
            ),
        )
        ew = fight["breakdown"]["expose_weakness_Bloodsong"]
        assert ew["amplifier"] == pytest.approx(1.05, abs=0.001)

    def test_ahri_level18_bloodsong_total_damage(
        self,
        ahri_data: dict,
        bloodsong: dict,
    ) -> None:
        """Ahri level 18 with Bloodsong vs 1000 HP / 100 Armor / 100 MR.

        5-second fight, 100% auto uptime. Expected ~1040 total damage
        (±5%). Was ~1161 before the shared cast timeline: W (5.0s cd)
        used to sneak a second cast at exactly t=5.0, but Q's 0.25s cast
        time delays W to t=0.25, putting its recast at 5.25 — past the
        fight's end, as in-game.
        """
        from src.calculator.stats import calculate_total_stats

        items = [bloodsong]
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
                auto_attack_uptime=1.0,
                one_rotation=False,
            ),
        )
        expected = 1040
        actual = fight["total_damage"]
        tolerance = expected * 0.05
        assert abs(actual - expected) <= tolerance, (
            f"Total damage {actual:.1f} not within 5% of {expected} "
            f"(diff: {abs(actual - expected) / expected * 100:.1f}%)"
        )

    def test_no_expose_weakness_without_auto_attacks(
        self,
        ahri_data: dict,
        bloodsong: dict,
    ) -> None:
        """No auto attacks means no spellblade procs, so no Expose Weakness."""
        from src.calculator.stats import calculate_total_stats

        items = [bloodsong]
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
                auto_attack_uptime=0.0,
                one_rotation=True,
            ),
        )
        assert "expose_weakness_Bloodsong" not in fight["breakdown"]

    def test_expose_weakness_melee_uses_eight_percent(self) -> None:
        """Melee champions should use the 8% Expose Weakness rate."""
        stats = {
            "attack_damage": 100,
            "ability_power": 0,
            "base_attack_damage": 100,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 0,
            "is_melee": True,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test Q",
                "rank": 1,
                "cooldown": 5.0,
                "physical_damage": 200,
                "parts": (DamagePart("physical", 200),),
                "total_raw": 200,
                "damage_type": "physical",
            },
            "W": {
                "name": "Test W",
                "rank": 1,
                "cooldown": 5.0,
                "physical_damage": 200,
                "parts": (DamagePart("physical", 200),),
                "total_raw": 200,
                "damage_type": "physical",
            },
        }
        fight = calculate_fight_damage(
            stats,
            abilities,
            [{"name": "Bloodsong"}],
            FightConfig(
                target_health=1000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=5.0,
                auto_attack_uptime=1.0,
                one_rotation=False,
            ),
        )
        ew = fight["breakdown"]["expose_weakness_Bloodsong"]
        assert ew["amplifier"] == pytest.approx(1.08, abs=0.001)


class TestDuskAndDawnSpellbladeAndDoubleOnHit:
    """Tests for Dusk and Dawn's Spellblade and Double On-Hit passives."""

    @pytest.fixture
    def dusk_and_dawn(self) -> dict:
        from src.calculator.data_fetcher import get_item_by_name

        return get_item_by_name("Dusk and Dawn")

    @pytest.fixture
    def nashors(self) -> dict:
        from src.calculator.data_fetcher import get_item_by_name

        return get_item_by_name("Nashor's Tooth")

    def test_dusk_and_dawn_registered_as_spellblade(self) -> None:
        """Dusk and Dawn should be in ITEM_EFFECTS with type spellblade."""
        from src.calculator.item_effects import ITEM_EFFECTS

        effect = ITEM_EFFECTS.get("Dusk and Dawn")
        assert effect is not None
        assert effect["type"] == "spellblade"
        assert effect["damage_type"] == "magic"
        assert effect["base_ad_ratio"] == 0.75
        assert effect["ap_ratio"] == 0.10
        assert effect["double_on_hit"] is True

    def test_spellblade_damage_formula(self) -> None:
        """Dusk and Dawn spellblade should deal 75% base AD + 10% AP."""
        stats = {"base_attack_damage": 104.0, "ability_power": 160.0}
        effect = resolve_damage_effects(_build("Dusk and Dawn")).spellblade
        assert effect is not None
        damage = effect.source.raw_damage(DamageInputs(stats, 18, False, 1000, 1000))
        expected = 0.75 * 104.0 + 0.10 * 160.0  # 78 + 16 = 94
        assert abs(damage - expected) < 0.01

    def test_two_procs_in_four_second_fight(
        self,
        ahri_data: dict,
        dusk_and_dawn: dict,
        nashors: dict,
    ) -> None:
        """Dusk and Dawn should proc twice in a 4-second fight."""
        from src.calculator.stats import calculate_total_stats

        items = [dusk_and_dawn, nashors]
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
                fight_duration_seconds=4.0,
                auto_attack_uptime=1.0,
                one_rotation=False,
            ),
        )
        sb = fight["breakdown"]["spellblade_Dusk and Dawn"]
        assert sb["count"] == 2

    def test_double_on_hit_present_in_breakdown(
        self,
        ahri_data: dict,
        dusk_and_dawn: dict,
        nashors: dict,
    ) -> None:
        """Double on-hit bonus should appear in breakdown when Nashor's is present."""
        from src.calculator.stats import calculate_total_stats

        items = [dusk_and_dawn, nashors]
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
                fight_duration_seconds=4.0,
                auto_attack_uptime=1.0,
                one_rotation=False,
            ),
        )
        assert "double_on_hit_Dusk and Dawn" in fight["breakdown"]
        doh = fight["breakdown"]["double_on_hit_Dusk and Dawn"]
        assert doh["count"] == 2
        assert doh["total_damage"] > 0

    def test_dusk_spellblade_reports_self_heal_sibling(
        self,
        ahri_data: dict,
        dusk_and_dawn: dict,
    ) -> None:
        """The same Spellblade proc exposes Dusk and Dawn's self-heal."""
        from src.calculator.stats import calculate_total_stats

        items = [dusk_and_dawn]
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
                fight_duration_seconds=4.0,
                auto_attack_uptime=1.0,
                one_rotation=False,
            ),
        )
        row = fight["breakdown"]["heal_Dusk and Dawn"]
        assert row["count"] == 2
        assert len(row["proc_times"]) == row["count"]
        assert row["proc_times"] == sorted(row["proc_times"])
        assert row["total_amount"] > 0

    def test_no_double_on_hit_without_on_hit_items(
        self,
        ahri_data: dict,
        dusk_and_dawn: dict,
    ) -> None:
        """No double on-hit entry when no on-hit items are present."""
        from src.calculator.stats import calculate_total_stats

        items = [dusk_and_dawn]
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
                fight_duration_seconds=4.0,
                auto_attack_uptime=1.0,
                one_rotation=False,
            ),
        )
        assert "double_on_hit_Dusk and Dawn" not in fight["breakdown"]

    def test_ahri_level18_dnd_nashors_total_damage(
        self,
        ahri_data: dict,
        dusk_and_dawn: dict,
        nashors: dict,
    ) -> None:
        """Ahri level 18, D&D + Nashor's vs 1000 HP / 100 Armor / 100 MR.

        4-second fight, 100% auto uptime. Expected ~1656 total damage (+-5%).
        """
        from src.calculator.stats import calculate_total_stats

        items = [dusk_and_dawn, nashors]
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
                fight_duration_seconds=4.0,
                auto_attack_uptime=1.0,
                one_rotation=False,
            ),
        )
        expected = 1656
        actual = fight["total_damage"]
        tolerance = expected * 0.05
        assert abs(actual - expected) <= tolerance, (
            f"Total damage {actual:.1f} not within 5% of {expected} "
            f"(diff: {abs(actual - expected) / expected * 100:.1f}%)"
        )

    def test_double_on_hit_with_wits_end(self) -> None:
        """Double on-hit should also work with Wit's End."""
        stats = {
            "attack_damage": 100,
            "ability_power": 0,
            "base_attack_damage": 100,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 0,
            "is_melee": False,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test",
                "rank": 1,
                "cooldown": 5.0,
                "magic_damage": 200,
                "parts": (DamagePart("magic", 200),),
                "total_raw": 200,
                "damage_type": "magic",
            },
        }
        fight = calculate_fight_damage(
            stats,
            abilities,
            [{"name": "Dusk and Dawn"}, {"name": "Wit's End"}],
            FightConfig(
                target_health=1000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=5.0,
                auto_attack_uptime=1.0,
                one_rotation=False,
            ),
        )
        assert "double_on_hit_Dusk and Dawn" in fight["breakdown"]
        doh = fight["breakdown"]["double_on_hit_Dusk and Dawn"]
        assert doh["count"] == 2
        assert doh["total_damage"] > 0

    def test_double_on_hit_with_bork(self) -> None:
        """Double on-hit should work with Blade of the Ruined King."""
        stats = {
            "attack_damage": 100,
            "ability_power": 0,
            "base_attack_damage": 100,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 0,
            "is_melee": True,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test Q",
                "rank": 1,
                "cooldown": 5.0,
                "physical_damage": 200,
                "parts": (DamagePart("physical", 200),),
                "total_raw": 200,
                "damage_type": "physical",
            },
            "W": {
                "name": "Test W",
                "rank": 1,
                "cooldown": 5.0,
                "physical_damage": 200,
                "parts": (DamagePart("physical", 200),),
                "total_raw": 200,
                "damage_type": "physical",
            },
        }
        fight = calculate_fight_damage(
            stats,
            abilities,
            [
                {"name": "Dusk and Dawn"},
                {"name": "Blade of the Ruined King"},
            ],
            FightConfig(
                target_health=2000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=5.0,
                auto_attack_uptime=1.0,
                one_rotation=False,
            ),
        )
        assert "double_on_hit_Dusk and Dawn" in fight["breakdown"]
        doh = fight["breakdown"]["double_on_hit_Dusk and Dawn"]
        assert doh["total_damage"] > 0

    def test_kraken_extra_hits_from_double_on_hit(self) -> None:
        """Double on-hit procs should count as extra hits for Kraken Slayer."""
        stats = {
            "attack_damage": 100,
            "ability_power": 0,
            "base_attack_damage": 100,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 0,
            "is_melee": True,
            "level": 18,
        }
        # Only 2 auto attacks + 2 double on-hit procs = 4 effective hits
        # = 1 Kraken proc (every 3rd hit). Without double on-hit, 2 autos
        # wouldn't reach the 3-hit threshold.
        abilities = {
            "Q": {
                "name": "Test",
                "rank": 1,
                "cooldown": 3.0,
                "physical_damage": 200,
                "parts": (DamagePart("physical", 200),),
                "total_raw": 200,
                "damage_type": "physical",
            },
        }
        fight = calculate_fight_damage(
            stats,
            abilities,
            [
                {"name": "Dusk and Dawn"},
                {"name": "Kraken Slayer"},
            ],
            FightConfig(
                target_health=1000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=2.0,
                auto_attack_uptime=1.0,
                one_rotation=False,
            ),
        )
        # 2 autos + 2 double on-hit = 4 effective hits >= 3, so Kraken procs
        assert "on_hit_Kraken Slayer" in fight["breakdown"]


class TestCullHealing:
    """Cull's direct Reap receipt is separate from its blocked quest state."""

    def test_cull_reap_emits_one_exact_heal_per_authored_auto(
        self,
        ahri_data: dict,
    ) -> None:
        from src.calculator.data_fetcher import get_item_by_name
        from src.calculator.stats import calculate_total_stats

        item = get_item_by_name("Cull")
        items = [item]
        stats = calculate_total_stats(ahri_data, 18, items)
        abilities = parse_ahri_abilities(ahri_data, 18, stats["ability_power"])
        result = calculate_fight_damage(
            stats,
            abilities,
            items,
            FightConfig(
                target_health=3000.0,
                target_armor=0.0,
                target_magic_resistance=0.0,
                fight_duration_seconds=4.0,
                auto_attack_uptime=1.0,
                one_rotation=False,
            ),
        )

        row = result["breakdown"]["heal_Cull"]
        assert row["name"] == "Cull (Reap)"
        assert row["count"] == len(row["heal_events"])
        assert row["amount_per_proc"] == pytest.approx(3.0)
        assert row["total_amount"] == pytest.approx(3.0 * row["count"])
        assert [event["time"] for event in row["heal_events"]] == sorted(
            event["time"] for event in row["heal_events"]
        )


class TestEssenceReaverSpellbladeSiblings:
    """Essence Reaver's Manaflow is tied to each accepted Spellblade proc."""

    def test_essence_reaver_reports_mana_restore(self, ahri_data: dict) -> None:
        from src.calculator.data_fetcher import get_item_by_name
        from src.calculator.stats import calculate_total_stats

        items = [get_item_by_name("Essence Reaver")]
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
                fight_duration_seconds=4.0,
                auto_attack_uptime=1.0,
                one_rotation=False,
            ),
        )
        row = fight["breakdown"]["mana_Essence Reaver"]
        assert row["count"] == 2
        assert len(row["proc_times"]) == row["count"]
        assert row["proc_times"] == sorted(row["proc_times"])
        assert row["total_amount"] > 0

    def test_manaflow_restore_reenters_timed_resource_admission(
        self, ahri_data: dict
    ) -> None:
        """A Spellblade restore can pay for a later accepted ability cast."""
        from src.calculator.data_fetcher import get_item_by_name
        from src.calculator.stats import calculate_total_stats

        item = get_item_by_name("Essence Reaver")
        stats = calculate_total_stats(ahri_data, 18, [item])
        abilities = parse_ahri_abilities(ahri_data, 18, stats["ability_power"])
        # A deliberately expensive, one-second Q fixture makes the ordering
        # observable: the first cast spends 300 mana, its t=1.5 Spellblade
        # attack restores 200, and the second cast at t=2.167 is legal.
        q = deepcopy(abilities["Q"])
        q.update({"resource_type": "MANA", "resource_cost": 300.0, "cooldown": 1.0})
        stats.update(
            {
                "max_mana": 500.0,
                "base_attack_damage": 320.0,
                "attack_damage": 320.0 + stats.get("bonus_attack_damage", 0.0),
                "attack_speed": 1.0,
                "attack_speed_ratio": 1.0,
                "resource_regen_per_second": 0.0,
                "critical_strike_chance": 0.0,
            }
        )

        result = calculate_fight_damage(
            stats,
            {"Q": q},
            [item],
            FightConfig(
                target_health=10000.0,
                target_armor=0.0,
                target_magic_resistance=0.0,
                fight_duration_seconds=4.0,
                auto_attack_uptime=1.0,
                one_rotation=False,
                enforce_resource_limits=True,
                cast_order=["Q"],
            ),
        )

        assert result["breakdown"]["Q"]["casts"] == 2
        assert result["cast_timeline"][1]["resource_before"] == pytest.approx(400.0)


class TestEclipseEverRisingMoon:
    """Tests for Eclipse's Ever Rising Moon passive (% max HP physical proc)."""

    @pytest.fixture
    def eclipse(self) -> dict:
        from src.calculator.data_fetcher import get_item_by_name

        return get_item_by_name("Eclipse")

    def test_eclipse_registered_in_item_effects(self) -> None:
        """Eclipse should be registered in ITEM_EFFECTS with correct type."""
        from src.calculator.item_effects import ITEM_EFFECTS

        effect = ITEM_EFFECTS.get("Eclipse")
        assert effect is not None
        assert effect["type"] == "max_hp_proc"
        assert effect["damage_type"] == "physical"
        assert effect["target_max_hp_ratio_melee"] == 0.06
        assert effect["target_max_hp_ratio_ranged"] == 0.04
        assert effect["cooldown"] == 6.0

    def test_ranged_single_proc_damage(self) -> None:
        """Ranged: 4% of 2000 max HP = 80 raw physical damage (one proc)."""
        effect = resolve_damage_effects(_build("Eclipse")).cooldown_procs[0]
        damage = effect.source.raw_damage(DamageInputs({}, 18, False, 2000.0, 2000.0))
        assert abs(damage - 80.0) < 0.01

    def test_melee_single_proc_damage(self) -> None:
        """Melee: 6% of 2000 max HP = 120 raw physical damage (one proc)."""
        effect = resolve_damage_effects(_build("Eclipse")).cooldown_procs[0]
        damage = effect.source.raw_damage(DamageInputs({}, 18, True, 2000.0, 2000.0))
        assert abs(damage - 120.0) < 0.01

    def test_multiple_procs_over_duration(self) -> None:
        """6s cooldown: 12s fight = 3 procs (0s, 6s, 12s)."""
        effect = resolve_damage_effects(_build("Eclipse")).cooldown_procs[0]
        per_proc = effect.source.raw_damage(DamageInputs({}, 18, False, 1000.0, 1000.0))
        damage = per_proc * (1 + int(12.0 / effect.cooldown))
        # 3 procs * 4% * 1000 = 120
        assert abs(damage - 120.0) < 0.01

    def test_zero_target_health_returns_zero(self) -> None:
        """Zero target max HP should result in zero Eclipse damage."""
        effect = resolve_damage_effects(_build("Eclipse")).cooldown_procs[0]
        damage = effect.source.raw_damage(DamageInputs({}, 18, True, 0.0, 0.0))
        assert damage == 0.0

    def test_eclipse_appears_in_fight_breakdown(self) -> None:
        """Eclipse proc should appear in fight breakdown when item is present."""
        stats = {
            "attack_damage": 100,
            "ability_power": 0,
            "base_attack_damage": 100,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 0,
            "is_melee": False,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test Q",
                "rank": 1,
                "cooldown": 5.0,
                "physical_damage": 200,
                "parts": (DamagePart("physical", 200),),
                "total_raw": 200,
                "damage_type": "physical",
            },
            "W": {
                "name": "Test W",
                "rank": 1,
                "cooldown": 5.0,
                "physical_damage": 200,
                "parts": (DamagePart("physical", 200),),
                "total_raw": 200,
                "damage_type": "physical",
            },
        }
        fight = calculate_fight_damage(
            stats,
            abilities,
            [{"name": "Eclipse"}],
            FightConfig(
                target_health=2000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=5.0,
                auto_attack_uptime=0.0,
                one_rotation=True,
            ),
        )
        assert "proc_Eclipse" in fight["breakdown"]
        proc = fight["breakdown"]["proc_Eclipse"]
        assert proc["damage_type"] == "physical"
        assert proc["total_damage"] > 0
        assert proc["self_shield_events"] == [
            {
                "amount": 80.0,
                "duration": 2.0,
                "source": "Eclipse (Ever Rising Moon)",
            }
        ]
        assert fight["damage_events"][-1]["self_shield"] == {
            "amount": 80.0,
            "duration": 2.0,
            "source": "Eclipse (Ever Rising Moon)",
        }

    def test_eclipse_damage_mitigated_by_armor(self) -> None:
        """Eclipse physical damage should be reduced by target armor."""
        stats = {
            "attack_damage": 100,
            "ability_power": 0,
            "base_attack_damage": 100,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 0,
            "is_melee": False,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test Q",
                "rank": 1,
                "cooldown": 5.0,
                "physical_damage": 100,
                "parts": (DamagePart("physical", 100),),
                "total_raw": 100,
                "damage_type": "physical",
            },
            "W": {
                "name": "Test W",
                "rank": 1,
                "cooldown": 5.0,
                "physical_damage": 100,
                "parts": (DamagePart("physical", 100),),
                "total_raw": 100,
                "damage_type": "physical",
            },
        }
        # 0 armor fight
        fight_no_armor = calculate_fight_damage(
            stats,
            abilities,
            [{"name": "Eclipse"}],
            FightConfig(
                target_health=2000,
                target_armor=0,
                target_magic_resistance=100,
                fight_duration_seconds=1.0,
                one_rotation=True,
            ),
        )
        # 100 armor fight
        fight_with_armor = calculate_fight_damage(
            stats,
            abilities,
            [{"name": "Eclipse"}],
            FightConfig(
                target_health=2000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=1.0,
                one_rotation=True,
            ),
        )
        eclipse_no_armor = fight_no_armor["breakdown"]["proc_Eclipse"]["total_damage"]
        eclipse_with_armor = fight_with_armor["breakdown"]["proc_Eclipse"][
            "total_damage"
        ]
        # 100 armor => 50% mitigation
        assert abs(eclipse_with_armor - eclipse_no_armor * 0.5) < 0.01

    def test_ahri_full_fight_with_eclipse(
        self,
        ahri_data: dict,
        eclipse: dict,
    ) -> None:
        """Ahri level 18 with Eclipse vs 2000 HP / 100 Armor / 100 MR.

        One rotation, no autos. Eclipse should add ~40 mitigated damage.
        (Ranged: 4% of 2000 = 80 raw, 50% mitigated by 100 armor = 40)
        """
        from src.calculator.stats import calculate_total_stats

        items = [eclipse]
        stats = calculate_total_stats(ahri_data, 18, items)
        abilities = parse_ahri_abilities(ahri_data, 18, stats["ability_power"])
        fight = calculate_fight_damage(
            stats,
            abilities,
            items,
            FightConfig(
                target_health=2000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=5.0,
                auto_attack_uptime=0.0,
                one_rotation=True,
            ),
        )
        proc = fight["breakdown"]["proc_Eclipse"]
        assert proc["name"] == "Eclipse (Ever Rising Moon)"
        # Ranged 4% of 2000 = 80 raw. With armor pen from Eclipse lethality,
        # effective armor < 100, so mitigated damage > 40.
        assert proc["total_damage"] > 35
        assert proc["total_damage"] < 80  # Must be mitigated, less than raw

    def test_no_eclipse_when_item_not_present(self) -> None:
        """Eclipse proc should not appear when item is not equipped."""
        stats = {
            "attack_damage": 100,
            "ability_power": 0,
            "base_attack_damage": 100,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 0,
            "is_melee": False,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test",
                "rank": 1,
                "cooldown": 5.0,
                "physical_damage": 200,
                "parts": (DamagePart("physical", 200),),
                "total_raw": 200,
                "damage_type": "physical",
            },
        }
        fight = calculate_fight_damage(
            stats,
            abilities,
            [],
            FightConfig(
                target_health=2000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=5.0,
                one_rotation=True,
            ),
        )
        assert "proc_Eclipse" not in fight["breakdown"]


class TestExperimentalHexplate:
    """Tests for Overdrive (melee 50% / ranged 35% bonus AS on R cast)."""

    def test_hexplate_registered_in_item_effects(self) -> None:
        """Hexplate should be registered in ITEM_EFFECTS."""
        from src.calculator.item_effects import ITEM_EFFECTS

        effect = ITEM_EFFECTS.get("Experimental Hexplate")
        assert effect is not None
        assert effect["type"] == "ult_attack_speed_buff"
        assert effect["bonus_attack_speed_melee"] == 50.0
        assert effect["bonus_attack_speed_ranged"] == 35.0
        assert effect["duration"] == 8.0

    def test_hexplate_increases_auto_count(self) -> None:
        """Hexplate bonus AS (from stats) should yield more autos than without."""
        base_stats = {
            "attack_damage": 100,
            "ability_power": 0,
            "base_attack_damage": 100,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 0,
            "is_melee": True,
            "level": 18,
        }
        # Hexplate 50% bonus AS is now baked into stats by calculate_total_stats
        buffed_stats = {**base_stats, "attack_speed": 1.3125}
        abilities = {
            "Q": {
                "name": "Test",
                "rank": 1,
                "cooldown": 5.0,
                "physical_damage": 100,
                "parts": (DamagePart("physical", 100),),
                "total_raw": 100,
                "damage_type": "physical",
            },
        }
        fight_without = calculate_fight_damage(
            base_stats,
            abilities,
            [],
            FightConfig(
                target_health=1000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=5.0,
                auto_attack_uptime=1.0,
                one_rotation=True,
            ),
        )
        fight_with = calculate_fight_damage(
            buffed_stats,
            abilities,
            [{"name": "Experimental Hexplate"}],
            FightConfig(
                target_health=1000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=5.0,
                auto_attack_uptime=1.0,
                one_rotation=True,
            ),
        )
        autos_without = fight_without["breakdown"]["auto_attacks"]["count"]
        autos_with = fight_with["breakdown"]["auto_attacks"]["count"]
        assert autos_with > autos_without

    def test_hexplate_auto_count_5s_fight(self) -> None:
        """With buffed AS=1.3125 (from stats), 5s => 6 autos."""
        stats = {
            "attack_damage": 100,
            "ability_power": 0,
            "base_attack_damage": 100,
            "attack_speed": 1.3125,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 0,
            "is_melee": True,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test",
                "rank": 1,
                "cooldown": 5.0,
                "physical_damage": 100,
                "parts": (DamagePart("physical", 100),),
                "total_raw": 100,
                "damage_type": "physical",
            },
        }
        fight = calculate_fight_damage(
            stats,
            abilities,
            [{"name": "Experimental Hexplate"}],
            FightConfig(
                target_health=1000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=5.0,
                auto_attack_uptime=1.0,
                one_rotation=True,
            ),
        )
        # AS already includes Hexplate 50% bonus from stats.py
        # floor(1.3125 * 5 * 1.0) = 6
        assert fight["breakdown"]["auto_attacks"]["count"] == 6

    def test_hexplate_full_fight_duration(self) -> None:
        """With buffed AS=1.3125 for full 15s fight: floor(1.3125 * 15) = 19."""
        stats = {
            "attack_damage": 100,
            "ability_power": 0,
            "base_attack_damage": 100,
            "attack_speed": 1.3125,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 0,
            "is_melee": True,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test",
                "rank": 1,
                "cooldown": 5.0,
                "physical_damage": 100,
                "parts": (DamagePart("physical", 100),),
                "total_raw": 100,
                "damage_type": "physical",
            },
        }
        fight = calculate_fight_damage(
            stats,
            abilities,
            [{"name": "Experimental Hexplate"}],
            FightConfig(
                target_health=1000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=15.0,
                auto_attack_uptime=1.0,
                one_rotation=True,
            ),
        )
        # AS includes Hexplate bonus from stats.py, applied for full duration
        # floor(1.3125 * 15 * 1.0) = 19
        assert fight["breakdown"]["auto_attacks"]["count"] == 19

    def test_hexplate_note_in_result(self) -> None:
        """Fight result should include a note about R assumption."""
        stats = {
            "attack_damage": 100,
            "ability_power": 0,
            "base_attack_damage": 100,
            "attack_speed": 1.3125,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 0,
            "is_melee": True,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test",
                "rank": 1,
                "cooldown": 5.0,
                "physical_damage": 100,
                "parts": (DamagePart("physical", 100),),
                "total_raw": 100,
                "damage_type": "physical",
            },
        }
        fight = calculate_fight_damage(
            stats,
            abilities,
            [{"name": "Experimental Hexplate"}],
            FightConfig(
                target_health=1000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=5.0,
                auto_attack_uptime=1.0,
                one_rotation=True,
            ),
        )
        assert len(fight["notes"]) == 1
        assert "Experimental Hexplate" in fight["notes"][0]
        assert "R is assumed" in fight["notes"][0]

    def test_no_note_without_hexplate(self) -> None:
        """No notes when Hexplate is not equipped."""
        stats = {
            "attack_damage": 100,
            "ability_power": 0,
            "base_attack_damage": 100,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 0,
            "is_melee": True,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test",
                "rank": 1,
                "cooldown": 5.0,
                "physical_damage": 100,
                "parts": (DamagePart("physical", 100),),
                "total_raw": 100,
                "damage_type": "physical",
            },
        }
        fight = calculate_fight_damage(
            stats,
            abilities,
            [],
            FightConfig(
                target_health=1000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=5.0,
                auto_attack_uptime=1.0,
                one_rotation=True,
            ),
        )
        assert fight["notes"] == []


class TestFiendhunterBolts:
    """Tests for Fiendhunter Bolts (3 empowered autos after R cast)."""

    def test_fiendhunter_registered_in_item_effects(self) -> None:
        """Fiendhunter should be registered in ITEM_EFFECTS."""
        from src.calculator.item_effects import ITEM_EFFECTS

        effect = ITEM_EFFECTS.get("Fiendhunter Bolts")
        assert effect is not None
        assert effect["type"] == "ult_empowered_autos"
        assert effect["bonus_attack_speed_percent"] == 50.0
        assert effect["empowered_auto_count"] == 3
        assert effect["reduced_crit_ratio"] == 0.80
        assert effect["natural_crit_true_damage_ratio"] == 0.15

    def test_zero_crit_empowered_autos_deal_80pct_crit(self) -> None:
        """With 0% crit chance, empowered autos crit at 80% of crit multiplier.

        AD=100, crit_mult=2.0, 80% crit = 100 * 2.0 * 0.80 = 160 raw.
        No true damage (0% natural crit chance).
        """
        stats = {
            "attack_damage": 100,
            "ability_power": 0,
            "base_attack_damage": 100,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 0,
            "is_melee": True,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test",
                "rank": 1,
                "cooldown": 5.0,
                "physical_damage": 100,
                "parts": (DamagePart("physical", 100),),
                "total_raw": 100,
                "damage_type": "physical",
            },
        }
        fight = calculate_fight_damage(
            stats,
            abilities,
            [{"name": "Fiendhunter Bolts"}],
            FightConfig(
                target_health=1000,
                target_armor=0,
                target_magic_resistance=100,
                fight_duration_seconds=5.0,
                auto_attack_uptime=1.0,
                one_rotation=True,
            ),
        )
        autos = fight["breakdown"]["auto_attacks"]
        assert autos["empowered_count"] == 3
        # Empowered: 100 * 2.0 * 0.80 = 160 per hit (0 armor), 3 hits
        # Normal autos (0% crit): 100 per hit
        # Total empowered physical = 160 * 3 = 480
        empowered_phys = 160.0 * 3
        # buffed_as = 1.0 + 0.625 * 0.50 = 1.3125
        # 3 / (1.3125 * 1.0) = 2.2857s; remaining = 2.7143s
        # normal_autos = floor(1.0 * 2.7143) = 2
        normal_phys = 100.0 * 2
        assert abs(autos["total_damage"] - (empowered_phys + normal_phys)) < 1
        assert "fiendhunter_true_damage" not in fight["breakdown"]

    def test_100_crit_empowered_autos_deal_normal_crit_plus_true(self) -> None:
        """With 100% crit chance, empowered autos deal full crit + 15% true.

        AD=100, crit_mult=2.0, all natural crits.
        Physical: 100 * 2.0 = 200 per hit.
        True: 200 * 0.15 = 30 per hit.
        """
        stats = {
            "attack_damage": 100,
            "ability_power": 0,
            "base_attack_damage": 100,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 100,
            "is_melee": True,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test",
                "rank": 1,
                "cooldown": 5.0,
                "physical_damage": 100,
                "parts": (DamagePart("physical", 100),),
                "total_raw": 100,
                "damage_type": "physical",
            },
        }
        fight = calculate_fight_damage(
            stats,
            abilities,
            [{"name": "Fiendhunter Bolts"}],
            FightConfig(
                target_health=1000,
                target_armor=0,
                target_magic_resistance=100,
                fight_duration_seconds=5.0,
                auto_attack_uptime=1.0,
                one_rotation=True,
            ),
        )
        autos = fight["breakdown"]["auto_attacks"]
        # 3 empowered at full crit = 200 each, 2 normal crits = 200 each
        assert autos["num_crits"] == 5  # all autos crit at 100%
        fh_true = fight["breakdown"]["fiendhunter_true_damage"]
        # True damage: 200 * 0.15 = 30 per hit, 3 empowered hits = 90
        assert abs(fh_true["total_damage"] - 90.0) < 0.01

    def test_ahri_level_18_fiendhunter_zero_crits(self) -> None:
        """Ahri level 18 with Fiendhunter Bolts, 3 autos, 0 natural crits.

        AD=104, crit_mult=2.0, 25% crit chance but no crits rolled.
        Empowered: 104 * 2.0 * 0.80 = 166.4 raw, /2 = 83.2 mitigated.
        Total: 83.2 * 3 = 249.6 -> 250.
        """
        from unittest.mock import patch

        stats = {
            "attack_damage": 104,
            "ability_power": 0,
            "base_attack_damage": 104,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 25,
            "is_melee": False,
            "level": 18,
        }
        abilities = {}
        # Force no crits: random.random() always returns 0.99 (> 0.25)
        with patch("src.calculator.damage.random.random", return_value=0.99):
            fight = calculate_fight_damage(
                stats,
                abilities,
                [{"name": "Fiendhunter Bolts"}],
                FightConfig(
                    target_health=1000,
                    target_armor=100,
                    target_magic_resistance=100,
                    fight_duration_seconds=3.0,
                    auto_attack_uptime=1.0,
                    one_rotation=True,
                ),
            )
        autos = fight["breakdown"]["auto_attacks"]
        assert autos["empowered_count"] == 3
        assert autos["count"] == 3
        assert autos["num_crits"] == 0
        assert round(autos["total_damage"]) == 250
        assert "fiendhunter_true_damage" not in fight["breakdown"]

    def test_ahri_level_18_fiendhunter_one_crit(self) -> None:
        """Ahri level 18, Fiendhunter, 3 autos, 1 natural crit -> 302."""
        from unittest.mock import patch

        stats = {
            "attack_damage": 104,
            "ability_power": 0,
            "base_attack_damage": 104,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 25,
            "is_melee": False,
            "level": 18,
        }
        abilities = {}
        # 1st auto crits (0.1 < 0.25), 2nd and 3rd don't (0.99 > 0.25)
        crit_rolls = iter([0.1, 0.99, 0.99])
        with patch("src.calculator.damage.random.random", side_effect=crit_rolls):
            fight = calculate_fight_damage(
                stats,
                abilities,
                [{"name": "Fiendhunter Bolts"}],
                FightConfig(
                    target_health=1000,
                    target_armor=100,
                    target_magic_resistance=100,
                    fight_duration_seconds=3.0,
                    auto_attack_uptime=1.0,
                    one_rotation=True,
                ),
            )
        autos = fight["breakdown"]["auto_attacks"]
        assert autos["num_crits"] == 1
        assert (
            round(
                autos["total_damage"]
                + fight["breakdown"]["fiendhunter_true_damage"]["total_damage"]
            )
            == 302
        )

    def test_ahri_level_18_fiendhunter_two_crits(self) -> None:
        """Ahri level 18, Fiendhunter, 3 autos, 2 natural crits -> 354."""
        from unittest.mock import patch

        stats = {
            "attack_damage": 104,
            "ability_power": 0,
            "base_attack_damage": 104,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 25,
            "is_melee": False,
            "level": 18,
        }
        abilities = {}
        crit_rolls = iter([0.1, 0.1, 0.99])
        with patch("src.calculator.damage.random.random", side_effect=crit_rolls):
            fight = calculate_fight_damage(
                stats,
                abilities,
                [{"name": "Fiendhunter Bolts"}],
                FightConfig(
                    target_health=1000,
                    target_armor=100,
                    target_magic_resistance=100,
                    fight_duration_seconds=3.0,
                    auto_attack_uptime=1.0,
                    one_rotation=True,
                ),
            )
        autos = fight["breakdown"]["auto_attacks"]
        assert autos["num_crits"] == 2
        total = (
            autos["total_damage"]
            + fight["breakdown"]["fiendhunter_true_damage"]["total_damage"]
        )
        assert round(total) == 354

    def test_ahri_level_18_fiendhunter_three_crits(self) -> None:
        """Ahri level 18, Fiendhunter, 3 autos, 3 natural crits -> 406."""
        from unittest.mock import patch

        stats = {
            "attack_damage": 104,
            "ability_power": 0,
            "base_attack_damage": 104,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 25,
            "is_melee": False,
            "level": 18,
        }
        abilities = {}
        crit_rolls = iter([0.1, 0.1, 0.1])
        with patch("src.calculator.damage.random.random", side_effect=crit_rolls):
            fight = calculate_fight_damage(
                stats,
                abilities,
                [{"name": "Fiendhunter Bolts"}],
                FightConfig(
                    target_health=1000,
                    target_armor=100,
                    target_magic_resistance=100,
                    fight_duration_seconds=3.0,
                    auto_attack_uptime=1.0,
                    one_rotation=True,
                ),
            )
        autos = fight["breakdown"]["auto_attacks"]
        assert autos["num_crits"] == 3
        total = (
            autos["total_damage"]
            + fight["breakdown"]["fiendhunter_true_damage"]["total_damage"]
        )
        assert round(total) == 406

    def test_correct_total_auto_count(self) -> None:
        """3 empowered autos + remaining normal autos at base AS."""
        stats = {
            "attack_damage": 100,
            "ability_power": 0,
            "base_attack_damage": 100,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 0,
            "is_melee": True,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test",
                "rank": 1,
                "cooldown": 5.0,
                "physical_damage": 100,
                "parts": (DamagePart("physical", 100),),
                "total_raw": 100,
                "damage_type": "physical",
            },
        }
        fight = calculate_fight_damage(
            stats,
            abilities,
            [{"name": "Fiendhunter Bolts"}],
            FightConfig(
                target_health=1000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=10.0,
                auto_attack_uptime=1.0,
                one_rotation=True,
            ),
        )
        autos = fight["breakdown"]["auto_attacks"]
        # buffed_as = 1.0 + 0.625 * 0.50 = 1.3125
        # 3 empowered autos take 3 / (1.3125 * 1.0) = 2.2857s
        # remaining = 10.0 - 2.2857 = 7.7143s
        # normal autos = floor(1.0 * 7.7143) = 7
        # total = 3 + 7 = 10
        assert autos["empowered_count"] == 3
        assert autos["count"] == 10

    def test_fiendhunter_note_in_result(self) -> None:
        """Fight result should include a note about R assumption."""
        stats = {
            "attack_damage": 100,
            "ability_power": 0,
            "base_attack_damage": 100,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 0,
            "is_melee": True,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test",
                "rank": 1,
                "cooldown": 5.0,
                "physical_damage": 100,
                "parts": (DamagePart("physical", 100),),
                "total_raw": 100,
                "damage_type": "physical",
            },
        }
        fight = calculate_fight_damage(
            stats,
            abilities,
            [{"name": "Fiendhunter Bolts"}],
            FightConfig(
                target_health=1000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=5.0,
                auto_attack_uptime=1.0,
                one_rotation=True,
            ),
        )
        assert len(fight["notes"]) == 1
        assert "Fiendhunter Bolts" in fight["notes"][0]
        assert "R is assumed" in fight["notes"][0]

    def test_fiendhunter_more_damage_than_no_item(self) -> None:
        """Total damage with Fiendhunter should exceed damage without."""
        from unittest.mock import patch

        stats = {
            "attack_damage": 100,
            "ability_power": 0,
            "base_attack_damage": 100,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 25,
            "is_melee": True,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test",
                "rank": 1,
                "cooldown": 5.0,
                "physical_damage": 100,
                "parts": (DamagePart("physical", 100),),
                "total_raw": 100,
                "damage_type": "physical",
            },
        }
        # Use no crits for deterministic comparison
        with patch("src.calculator.damage.random.random", return_value=0.99):
            fight_with = calculate_fight_damage(
                stats,
                abilities,
                [{"name": "Fiendhunter Bolts"}],
                FightConfig(
                    target_health=1000,
                    target_armor=100,
                    target_magic_resistance=100,
                    fight_duration_seconds=5.0,
                    auto_attack_uptime=1.0,
                    one_rotation=True,
                ),
            )
            fight_without = calculate_fight_damage(
                stats,
                abilities,
                [],
                FightConfig(
                    target_health=1000,
                    target_armor=100,
                    target_magic_resistance=100,
                    fight_duration_seconds=5.0,
                    auto_attack_uptime=1.0,
                    one_rotation=True,
                ),
            )
        assert fight_with["total_damage"] > fight_without["total_damage"]

    def test_no_empowered_autos_at_zero_uptime(self) -> None:
        """With 0% auto uptime, no empowered autos and no Fiendhunter effect."""
        stats = {
            "attack_damage": 100,
            "ability_power": 0,
            "base_attack_damage": 100,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 50,
            "is_melee": True,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test",
                "rank": 1,
                "cooldown": 5.0,
                "physical_damage": 100,
                "parts": (DamagePart("physical", 100),),
                "total_raw": 100,
                "damage_type": "physical",
            },
        }
        fight = calculate_fight_damage(
            stats,
            abilities,
            [{"name": "Fiendhunter Bolts"}],
            FightConfig(
                target_health=1000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=5.0,
                auto_attack_uptime=0.0,
                one_rotation=True,
            ),
        )
        assert fight["breakdown"]["auto_attacks"]["count"] == 0
        assert "fiendhunter_true_damage" not in fight["breakdown"]

    def test_num_crits_in_breakdown(self) -> None:
        """Auto attack breakdown should include num_crits field."""
        from unittest.mock import patch

        stats = {
            "attack_damage": 100,
            "ability_power": 0,
            "base_attack_damage": 100,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 50,
            "is_melee": True,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test",
                "rank": 1,
                "cooldown": 5.0,
                "physical_damage": 100,
                "parts": (DamagePart("physical", 100),),
                "total_raw": 100,
                "damage_type": "physical",
            },
        }
        # 5 autos, rolls: crit, no crit, crit, no crit, no crit
        rolls = iter([0.1, 0.9, 0.1, 0.9, 0.9])
        with patch("src.calculator.damage.random.random", side_effect=rolls):
            fight = calculate_fight_damage(
                stats,
                abilities,
                [],
                FightConfig(
                    target_health=1000,
                    target_armor=0,
                    target_magic_resistance=100,
                    fight_duration_seconds=5.0,
                    auto_attack_uptime=1.0,
                    one_rotation=True,
                ),
            )
        autos = fight["breakdown"]["auto_attacks"]
        assert autos["num_crits"] == 2


class TestRagebladeOnHitAllItems:
    """Tests that phantom hits apply ALL on-hit effects, not just Rageblade."""

    BASE_STATS: dict = {
        "attack_damage": 100,
        "ability_power": 0,
        "magic_penetration_flat": 0,
        "magic_penetration_percent": 0,
        "armor_penetration_percent": 0,
        "flat_armor_penetration": 0,
        "critical_strike_chance": 0,
        "attack_speed": 1.0,
        "attack_speed_ratio": 0.625,
        "is_melee": True,
        "level": 18,
    }

    def test_rageblade_only_hit_count(self) -> None:
        """Rageblade's accelerated schedule yields 9 autos and 2 phantoms."""
        fight = calculate_fight_damage(
            self.BASE_STATS,
            {},
            [{"name": "Guinsoo's Rageblade"}],
            FightConfig(
                target_health=3000,
                target_armor=0,
                target_magic_resistance=0,
                fight_duration_seconds=7.0,
                auto_attack_uptime=1.0,
            ),
        )
        rb = fight["breakdown"].get("on_hit_Guinsoo's Rageblade")
        assert rb is not None
        assert rb["count"] == 11  # 9 scheduled autos + 2 phantoms

    def test_rageblade_plus_nashors_hit_counts(self) -> None:
        """Both Rageblade and Nashor's follow the same accelerated schedule."""
        fight = calculate_fight_damage(
            self.BASE_STATS,
            {},
            [
                {"name": "Guinsoo's Rageblade"},
                {"name": "Nashor's Tooth"},
            ],
            FightConfig(
                target_health=3000,
                target_armor=0,
                target_magic_resistance=0,
                fight_duration_seconds=7.0,
                auto_attack_uptime=1.0,
            ),
        )
        rb = fight["breakdown"]["on_hit_Guinsoo's Rageblade"]
        nt = fight["breakdown"]["on_hit_Nashor's Tooth"]
        assert rb["count"] == 11
        assert nt["count"] == 11  # Nashor's also gets phantom hit bonus

    def test_rageblade_plus_bork_hit_counts(self) -> None:
        """BoRK receives the two phantom applications on the accelerated schedule."""
        fight = calculate_fight_damage(
            self.BASE_STATS,
            {},
            [
                {"name": "Guinsoo's Rageblade"},
                {"name": "Blade of the Ruined King"},
            ],
            FightConfig(
                target_health=3000,
                target_armor=0,
                target_magic_resistance=0,
                fight_duration_seconds=7.0,
                auto_attack_uptime=1.0,
            ),
        )
        autos = fight["breakdown"]["auto_attacks"]
        rb = fight["breakdown"]["on_hit_Guinsoo's Rageblade"]
        bork = fight["breakdown"]["on_hit_Blade of the Ruined King"]

        assert autos["count"] == 9
        assert rb["count"] == 11
        assert bork["count"] == 11

    def test_bork_phantom_hit_double_procs_at_correct_hp(self) -> None:
        """BoRK phantom hit should proc at current HP after first BoRK hit."""
        # 7 autos, phantom on 6th. BoRK should hit twice on auto #6,
        # with the second hit at a lower HP than the first.
        result, hits = _simulate_bork_damage(
            target_health=3000.0,
            num_auto_attacks=7,
            auto_damage_per_hit=100.0,
            other_on_hit_per_hit=30.0,  # Rageblade 30 magic dmg
            effective_armor=0.0,
            is_melee=True,
            phantom_hit_autos={5},  # 6th auto (0-indexed)
        )
        assert hits == 8  # 7 normal + 1 phantom
        # Compare to no phantom hits
        result_no_phantom, hits_no = _simulate_bork_damage(
            target_health=3000.0,
            num_auto_attacks=7,
            auto_damage_per_hit=100.0,
            other_on_hit_per_hit=30.0,
            effective_armor=0.0,
            is_melee=True,
        )
        assert hits_no == 7
        assert result > result_no_phantom

    def test_no_phantom_under_6_autos_with_bork(self) -> None:
        """The fifth scheduled swing reaches the first phantom threshold."""
        fight = calculate_fight_damage(
            self.BASE_STATS,
            {},
            [
                {"name": "Guinsoo's Rageblade"},
                {"name": "Blade of the Ruined King"},
            ],
            FightConfig(
                target_health=3000,
                target_armor=0,
                target_magic_resistance=0,
                fight_duration_seconds=5.0,
                auto_attack_uptime=1.0,
            ),
        )
        rb = fight["breakdown"]["on_hit_Guinsoo's Rageblade"]
        bork = fight["breakdown"]["on_hit_Blade of the Ruined King"]
        assert rb["count"] == 7
        assert bork["count"] == 7

    def test_phantom_hits_in_return_value(self) -> None:
        """Fight result should expose phantom_hit_autos for champion use."""
        fight = calculate_fight_damage(
            self.BASE_STATS,
            {},
            [{"name": "Guinsoo's Rageblade"}],
            FightConfig(
                target_health=3000,
                target_armor=0,
                target_magic_resistance=0,
                fight_duration_seconds=10.0,
                auto_attack_uptime=1.0,
            ),
        )
        assert fight["phantom_hit_count"] == 3  # 12 scheduled autos: 5, 8, 11
        assert fight["phantom_hit_autos"] == {5, 8, 11}

    def test_ability_on_hit_gets_phantom_procs(self) -> None:
        """Ability on-hit damage should also get phantom hit procs."""
        ability_damages = {
            "passive": {
                "name": "Test Passive",
                "damage_type": "physical",
                "total_raw": 0,
                "on_hit": {
                    "name": "Test Passive (on-hit)",
                    "damage_per_hit": 50.0,
                    "damage_type": "physical",
                },
            },
        }
        fight = calculate_fight_damage(
            self.BASE_STATS,
            ability_damages,
            [{"name": "Guinsoo's Rageblade"}],
            FightConfig(
                target_health=3000,
                target_armor=0,
                target_magic_resistance=0,
                fight_duration_seconds=7.0,
                auto_attack_uptime=1.0,
            ),
        )
        passive_oh = fight["breakdown"].get("on_hit_ability_passive")
        assert passive_oh is not None
        assert passive_oh["count"] == 11


class TestKrakenSlayerPhantomHitStacking:
    """Tests that Kraken Slayer gets stack acceleration from phantom hits.

    Phantom hits grant an extra Kraken stack (not an extra damage proc).
    Kraken procs every 3rd stack, and phantom hits can push stacks to 3
    mid-auto to trigger a proc.
    """

    def test_kraken_no_rageblade_normal_stacking(self) -> None:
        """Without Rageblade, Kraken procs every 3rd auto normally."""
        ability_procs, proc_autos = _calculate_stacking_procs(10, set(), 0, 3)
        assert ability_procs == []  # no ability-carried applications
        assert len(proc_autos) == 3  # autos 3, 6, 9
        assert proc_autos == [2, 5, 8]  # 0-indexed

    def test_10_autos_rageblade_4_procs(self) -> None:
        """10 autos + Rageblade (phantoms at 6,9) = 4 Kraken procs."""
        _, phantom_autos = _calculate_phantom_hits(10, ["Guinsoo's Rageblade"])
        _, proc_autos = _calculate_stacking_procs(10, phantom_autos, 0, 3)
        assert len(proc_autos) == 4

    def test_12_autos_rageblade_5_procs(self) -> None:
        """12 autos + Rageblade (phantoms at 6,9,12) = 5 Kraken procs."""
        _, phantom_autos = _calculate_phantom_hits(12, ["Guinsoo's Rageblade"])
        _, proc_autos = _calculate_stacking_procs(12, phantom_autos, 0, 3)
        assert len(proc_autos) == 5

    def test_15_autos_rageblade_6_procs(self) -> None:
        """15 autos + Rageblade (phantoms at 6,9,12,15) = 6 Kraken procs."""
        _, phantom_autos = _calculate_phantom_hits(15, ["Guinsoo's Rageblade"])
        _, proc_autos = _calculate_stacking_procs(15, phantom_autos, 0, 3)
        assert len(proc_autos) == 6

    def test_17_autos_rageblade_7_procs(self) -> None:
        """17 autos + Rageblade (phantoms at 6,9,12,15) = 7 Kraken procs."""
        _, phantom_autos = _calculate_phantom_hits(17, ["Guinsoo's Rageblade"])
        _, proc_autos = _calculate_stacking_procs(17, phantom_autos, 0, 3)
        assert len(proc_autos) == 7

    def test_full_fight_kraken_plus_rageblade(self) -> None:
        """Integration test: Kraken + Rageblade in full fight shows correct procs."""
        stats = {
            "attack_damage": 100,
            "ability_power": 0,
            "magic_penetration_flat": 0,
            "magic_penetration_percent": 0,
            "armor_penetration_percent": 0,
            "flat_armor_penetration": 0,
            "critical_strike_chance": 0,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "is_melee": True,
            "level": 18,
        }
        fight = calculate_fight_damage(
            stats,
            {},
            [
                {"name": "Guinsoo's Rageblade"},
                {"name": "Kraken Slayer"},
            ],
            FightConfig(
                target_health=3000,
                target_armor=0,
                target_magic_resistance=0,
                fight_duration_seconds=10.0,
                auto_attack_uptime=1.0,
            ),
        )
        kraken = fight["breakdown"].get("on_hit_Kraken Slayer")
        assert kraken is not None
        assert kraken["count"] == 5

    def test_kraken_damage_scales_with_missing_hp(self) -> None:
        """Later Kraken procs should deal more due to higher missing HP."""
        # 9 autos, Kraken procs at autos 3, 6, 9 (indices 2, 5, 8)
        # No armor, melee, level 18 => base = 150 + 5*(18-8) = 200
        # First proc at full HP: missing = 0%, bonus = 1.0x => 200
        # Later procs: target has taken damage, missing > 0%, bonus > 1.0x
        total = _simulate_kraken_damage(
            target_health=3000.0,
            num_auto_attacks=9,
            auto_damage_per_hit=100.0,
            other_on_hit_per_hit=0.0,
            effective_armor=0.0,
            is_melee=True,
            level=18,
            kraken_proc_autos=[2, 5, 8],
        )
        # Naive flat (no missing HP bonus): 200 * 3 = 600
        naive_flat = 200.0 * 3
        assert total > naive_flat, (
            f"Simulated {total:.1f} should exceed naive {naive_flat:.1f} "
            f"because later procs benefit from missing HP bonus"
        )

    def test_kraken_first_proc_at_full_hp_is_base_damage(self) -> None:
        """First Kraken proc at full HP should deal base damage (no bonus)."""
        # 3 autos, Kraken procs on auto 3 (index 2), no other damage
        total = _simulate_kraken_damage(
            target_health=3000.0,
            num_auto_attacks=3,
            auto_damage_per_hit=0.0,
            other_on_hit_per_hit=0.0,
            effective_armor=0.0,
            is_melee=True,
            level=18,
            kraken_proc_autos=[2],
        )
        # At full HP, missing ratio = 0, bonus = 1.0x, damage = 200
        assert abs(total - 200.0) < 0.01

    def test_kraken_base_damage_flat_before_level_9(self) -> None:
        """Base damage should be flat 150 (melee) / 120 (ranged) at levels 1-8."""
        for lvl in [1, 5, 8]:
            total = _simulate_kraken_damage(
                target_health=5000.0,
                num_auto_attacks=3,
                auto_damage_per_hit=0.0,
                other_on_hit_per_hit=0.0,
                effective_armor=0.0,
                is_melee=True,
                level=lvl,
                kraken_proc_autos=[2],
            )
            assert abs(total - 150.0) < 0.01, f"Melee level {lvl}: {total}"

            total_ranged = _simulate_kraken_damage(
                target_health=5000.0,
                num_auto_attacks=3,
                auto_damage_per_hit=0.0,
                other_on_hit_per_hit=0.0,
                effective_armor=0.0,
                is_melee=False,
                level=lvl,
                kraken_proc_autos=[2],
            )
            assert (
                abs(total_ranged - 120.0) < 0.01
            ), f"Ranged level {lvl}: {total_ranged}"

    def test_kraken_level_scaling_melee(self) -> None:
        """Melee Kraken base: 150 flat until 9, then +5/level."""
        expected = {9: 155, 10: 160, 14: 180, 18: 200, 20: 210}
        for lvl, exp in expected.items():
            total = _simulate_kraken_damage(
                target_health=5000.0,
                num_auto_attacks=3,
                auto_damage_per_hit=0.0,
                other_on_hit_per_hit=0.0,
                effective_armor=0.0,
                is_melee=True,
                level=lvl,
                kraken_proc_autos=[2],
            )
            assert (
                abs(total - exp) < 0.01
            ), f"Melee level {lvl}: got {total}, expected {exp}"

    def test_kraken_level_scaling_ranged(self) -> None:
        """Ranged Kraken base: 120 flat until 9, then +4/level."""
        expected = {9: 124, 10: 128, 14: 144, 18: 160, 20: 168}
        for lvl, exp in expected.items():
            total = _simulate_kraken_damage(
                target_health=5000.0,
                num_auto_attacks=3,
                auto_damage_per_hit=0.0,
                other_on_hit_per_hit=0.0,
                effective_armor=0.0,
                is_melee=False,
                level=lvl,
                kraken_proc_autos=[2],
            )
            assert (
                abs(total - exp) < 0.01
            ), f"Ranged level {lvl}: got {total}, expected {exp}"

    def test_kraken_max_damage_ranged_level_18(self) -> None:
        """Ranged level 18 at 0% target HP should deal 160 * 1.75 = 280."""
        # Use very high auto damage to push target to 0 HP before Kraken procs
        total = _simulate_kraken_damage(
            target_health=100.0,
            num_auto_attacks=3,
            auto_damage_per_hit=500.0,
            other_on_hit_per_hit=0.0,
            effective_armor=0.0,
            is_melee=False,
            level=18,
            kraken_proc_autos=[2],
        )
        # Target at 0% HP after 2 autos of 500 damage each, missing = 100%
        # Bonus: 1 + 0.75*1.0 = 1.75, damage = 160 * 1.75 = 280
        assert abs(total - 280.0) < 0.01


class TestHeartsteelDamage:
    """Tests for Heartsteel's Colossal Consumption proc."""

    def test_heartsteel_registered_in_item_effects(self) -> None:
        """Heartsteel should be registered with correct type and values."""
        from src.calculator.item_effects import ITEM_EFFECTS

        effect = ITEM_EFFECTS.get("Heartsteel")
        assert effect is not None
        assert effect["type"] == "on_hit_once"
        assert effect["damage_type"] == "physical"
        assert effect["base"] == 70.0
        assert effect["max_hp_ratio"] == 0.06
        assert effect["cooldown"] == 30.0

    def test_heartsteel_damage_calculation(self) -> None:
        """70 + 6% of 3000 max HP = 70 + 180 = 250 raw physical damage."""
        stats = {"health": 3000.0}
        effect = resolve_damage_effects(_build("Heartsteel")).first_autos[0]
        damage = effect.source.raw_damage(DamageInputs(stats, 18, True, 1000, 1000))
        assert abs(damage - 250.0) < 0.01

    def test_heartsteel_damage_low_health(self) -> None:
        """70 + 6% of 1000 max HP = 70 + 60 = 130 raw physical damage."""
        stats = {"health": 1000.0}
        effect = resolve_damage_effects(_build("Heartsteel")).first_autos[0]
        damage = effect.source.raw_damage(DamageInputs(stats, 18, True, 1000, 1000))
        assert abs(damage - 130.0) < 0.01

    def test_heartsteel_damage_zero_health(self) -> None:
        """With 0 health the damage is just the base 70."""
        stats = {"health": 0.0}
        effect = resolve_damage_effects(_build("Heartsteel")).first_autos[0]
        damage = effect.source.raw_damage(DamageInputs(stats, 18, True, 1000, 1000))
        assert abs(damage - 70.0) < 0.01


class TestHexopticsC44BasicDamageAmp:
    """Tests for Hexoptics C44 Magnification basic damage amplification."""

    def test_ranged_amp_with_item(self) -> None:
        """Ranged champs are assumed at max distance: full 10% amp."""
        items = [{"name": "Hexoptics C44"}]
        effect = resolve_damage_effects(items).basic_amp
        assert effect is not None
        assert effect.multiplier(is_melee=False) == pytest.approx(1.10)

    def test_melee_amp_with_item(self) -> None:
        """Melee champs are assumed at ~100 units: 2% amp, not 10%."""
        items = [{"name": "Hexoptics C44"}]
        effect = resolve_damage_effects(items).basic_amp
        assert effect is not None
        assert effect.multiplier(is_melee=True) == pytest.approx(1.02)

    def test_no_amp_without_item(self) -> None:
        """Without Hexoptics C44, there is no basic amp effect."""
        items = [{"name": "Infinity Edge"}]
        assert resolve_damage_effects(items).basic_amp is None

    def test_parsed_values_from_json(self) -> None:
        """Verify parser extracts correct values from item JSON data."""
        from src.calculator.item_effects import ITEM_EFFECTS

        effect = ITEM_EFFECTS.get("Hexoptics C44")
        assert effect is not None, "Hexoptics C44 not found in ITEM_EFFECTS"
        assert effect["type"] == "basic_damage_amp"
        assert abs(effect["max_amp"] - 0.10) < 0.001
        assert abs(effect["max_distance"] - 500.0) < 0.1
        assert abs(effect["melee_assumed_distance"] - 100.0) < 0.1

    def test_fight_damage_auto_attacks_amplified(self) -> None:
        """Auto attack damage should be 10% higher with Hexoptics C44."""
        champion_stats = {
            "attack_damage": 100.0,
            "base_attack_damage": 70.0,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "critical_strike_chance": 0.0,
            "magic_penetration_flat": 0.0,
            "magic_penetration_percent": 0.0,
            "armor_penetration_flat": 0.0,
            "armor_penetration_percent": 0.0,
            "lethality": 0.0,
            "ability_power": 0.0,
            "is_melee": False,
            "level": 18,
        }
        items_with = [{"name": "Hexoptics C44"}]
        items_without: list[dict] = []

        fight_with = calculate_fight_damage(
            champion_stats,
            {},
            items_with,
            FightConfig(
                target_health=2000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=5.0,
                auto_attack_uptime=1.0,
                auto_attacks_only=True,
            ),
        )
        fight_without = calculate_fight_damage(
            champion_stats,
            {},
            items_without,
            FightConfig(
                target_health=2000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=5.0,
                auto_attack_uptime=1.0,
                auto_attacks_only=True,
            ),
        )
        # With Hexoptics, auto damage should be ~10% higher
        ratio = fight_with["total_damage"] / fight_without["total_damage"]
        assert (
            abs(ratio - 1.10) < 0.02
        ), f"Expected ~10% more damage, got ratio {ratio:.3f}"

    def test_fight_damage_melee_gets_reduced_amp(self) -> None:
        """A melee champion fights inside ~100 units, so the amp is ~2%."""
        champion_stats = {
            "attack_damage": 100.0,
            "base_attack_damage": 70.0,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "critical_strike_chance": 0.0,
            "magic_penetration_flat": 0.0,
            "magic_penetration_percent": 0.0,
            "armor_penetration_flat": 0.0,
            "armor_penetration_percent": 0.0,
            "lethality": 0.0,
            "ability_power": 0.0,
            "is_melee": True,
            "level": 18,
        }
        config = FightConfig(
            target_health=2000,
            target_armor=100,
            target_magic_resistance=100,
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
            auto_attacks_only=True,
        )
        fight_with = calculate_fight_damage(
            champion_stats, {}, [{"name": "Hexoptics C44"}], config
        )
        fight_without = calculate_fight_damage(champion_stats, {}, [], config)
        ratio = fight_with["total_damage"] / fight_without["total_damage"]
        assert (
            abs(ratio - 1.02) < 0.005
        ), f"Expected ~2% more damage for melee, got ratio {ratio:.3f}"

    def test_breakdown_shows_amplification(self) -> None:
        """Breakdown should include a 'Damage Amplification' entry."""
        champion_stats = {
            "attack_damage": 100.0,
            "base_attack_damage": 70.0,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "critical_strike_chance": 0.0,
            "magic_penetration_flat": 0.0,
            "magic_penetration_percent": 0.0,
            "armor_penetration_flat": 0.0,
            "armor_penetration_percent": 0.0,
            "lethality": 0.0,
            "ability_power": 0.0,
            "is_melee": False,
            "level": 18,
        }
        fight = calculate_fight_damage(
            champion_stats,
            {},
            [{"name": "Hexoptics C44"}],
            FightConfig(
                target_health=2000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=5.0,
                auto_attack_uptime=1.0,
                auto_attacks_only=True,
            ),
        )
        amp_entry = fight["breakdown"].get("basic_amp_Hexoptics C44")
        assert amp_entry is not None, "Missing basic_amp breakdown entry"
        assert amp_entry["name"] == "Damage Amplification (Hexoptics C44)"
        assert amp_entry["total_damage"] > 0


class TestHorizonFocusHypershotAmp:
    """Tests for Horizon Focus Hypershot damage amplification."""

    def test_parsed_values_from_json(self) -> None:
        """Verify parser extracts correct amp value from item JSON data."""
        from src.calculator.item_effects import ITEM_EFFECTS

        effect = ITEM_EFFECTS.get("Horizon Focus")
        assert effect is not None, "Horizon Focus not found in ITEM_EFFECTS"
        assert effect["type"] == "hypershot_amp"
        assert abs(effect["amp"] - 0.10) < 0.001

    def test_amplifier_with_item(self) -> None:
        """With Horizon Focus, hypershot amp should be 1.10."""
        items = [{"name": "Horizon Focus"}]
        result = resolve_damage_effects(items).hypershot_amp
        assert abs(result - 1.10) < 0.001

    def test_amplifier_without_item(self) -> None:
        """Without Horizon Focus, hypershot amp should be 1.0."""
        items = [{"name": "Liandry's Torment"}]
        result = resolve_damage_effects(items).hypershot_amp
        assert result == 1.0

    def test_first_ability_not_amped(self) -> None:
        """First ability triggers the mark and should NOT be amplified."""
        stats = {
            "attack_damage": 60.0,
            "base_attack_damage": 60.0,
            "attack_speed": 0.6,
            "attack_speed_ratio": 0.625,
            "critical_strike_chance": 0.0,
            "magic_penetration_flat": 0.0,
            "magic_penetration_percent": 0.0,
            "armor_penetration_flat": 0.0,
            "armor_penetration_percent": 0.0,
            "lethality": 0.0,
            "ability_power": 100.0,
            "is_melee": False,
            "level": 9,
        }
        # Two abilities: Q (trigger) and E (amped)
        abilities = {
            "Q": {
                "name": "Test Q",
                "parts": (DamagePart("magic", 200.0),),
                "total_raw": 200.0,
                "damage_type": "magic",
                "cooldown": 6.0,
            },
            "E": {
                "name": "Test E",
                "parts": (DamagePart("magic", 150.0),),
                "total_raw": 150.0,
                "damage_type": "magic",
                "cooldown": 8.0,
            },
        }

        # Without Horizon Focus
        fight_base = calculate_fight_damage(
            stats,
            abilities,
            [],
            FightConfig(
                target_health=2000,
                target_armor=100,
                target_magic_resistance=0,
                fight_duration_seconds=0.5,
                auto_attack_uptime=0.0,
                one_rotation=True,
                cast_order=["Q", "E"],
            ),
        )

        # With Horizon Focus
        fight_hf = calculate_fight_damage(
            stats,
            abilities,
            [{"name": "Horizon Focus"}],
            FightConfig(
                target_health=2000,
                target_armor=100,
                target_magic_resistance=0,
                fight_duration_seconds=0.5,
                auto_attack_uptime=0.0,
                one_rotation=True,
                cast_order=["Q", "E"],
            ),
        )

        # Q does 200, E does 150, both at 0 MR so no mitigation.
        # Horizon Focus should amp E (150) by 10% = +15, but NOT amp Q.
        q_base = fight_base["breakdown"]["Q"]["total_damage"]
        q_hf = fight_hf["breakdown"]["Q"]["total_damage"]
        # Q damage itself should be the same (not amped inline)
        assert (
            abs(q_base - q_hf) < 0.01
        ), f"Q should not change: base={q_base:.1f} vs hf={q_hf:.1f}"

        # The amp entry should exist and NOT include Q damage
        amp_entry = fight_hf["breakdown"].get("damage_amp_Horizon Focus")
        assert amp_entry is not None, "Missing Horizon Focus breakdown entry"
        assert amp_entry["name"] == "Damage Amplification (Horizon Focus)"
        # Bonus should be ~10% of non-Q damage (E = 150)
        assert (
            abs(amp_entry["total_damage"] - 15.0) < 1.0
        ), f"Expected ~15 bonus, got {amp_entry['total_damage']:.1f}"

    def test_mixed_ability_only_first_hit_excluded(self) -> None:
        """For mixed abilities (Ahri Q), only the first hit is the trigger.

        Ahri Q deals magic (outgoing) + true (return). Only the magic
        outgoing hit triggers Hypershot; the true return hit should be amped.
        """
        stats = {
            "attack_damage": 60.0,
            "base_attack_damage": 60.0,
            "attack_speed": 0.6,
            "attack_speed_ratio": 0.625,
            "critical_strike_chance": 0.0,
            "magic_penetration_flat": 0.0,
            "magic_penetration_percent": 0.0,
            "armor_penetration_flat": 0.0,
            "armor_penetration_percent": 0.0,
            "lethality": 0.0,
            "ability_power": 0.0,
            "is_melee": False,
            "level": 9,
        }
        # Simulate Ahri Q: mixed (magic out + true return), 100 each
        abilities = {
            "Q": {
                "name": "Orb of Deception",
                "magic_damage": 100.0,
                "true_damage": 100.0,
                "parts": (
                    DamagePart("magic", 100.0),
                    DamagePart("true", 100.0),
                ),
                "total_raw": 200.0,
                "damage_type": "mixed",
                "cooldown": 7.0,
            },
        }

        fight = calculate_fight_damage(
            stats,
            abilities,
            [{"name": "Horizon Focus"}],
            FightConfig(
                target_health=2000,
                target_armor=100,
                target_magic_resistance=0,
                fight_duration_seconds=0.5,
                auto_attack_uptime=0.0,
                one_rotation=True,
                cast_order=["Q"],
            ),
        )

        # At 0 MR: magic_damage = 100, true_damage = 100, total Q = 200.
        # First hit (magic, 100) triggers Hypershot — NOT amped.
        # Return hit (true, 100) IS amped.
        # So amped_damage = 200 - 100 = 100, bonus = 100 * 0.10 = 10.
        amp_entry = fight["breakdown"].get("damage_amp_Horizon Focus")
        assert amp_entry is not None, "Missing Horizon Focus breakdown"
        assert abs(amp_entry["total_damage"] - 10.0) < 1.0, (
            f"Expected ~10 bonus (return hit only), got "
            f"{amp_entry['total_damage']:.1f}"
        )
        assert amp_entry.get("damage_events"), (
            "Mixed first-hit attribution must remain event-authored for the "
            "frontend timeline"
        )

    def test_zero_damage_opener_does_not_block_hypershot_receipts(self) -> None:
        """A utility opener must not become Horizon Focus's trigger cast."""
        stats = {
            "attack_damage": 60.0,
            "base_attack_damage": 60.0,
            "attack_speed": 0.6,
            "attack_speed_ratio": 0.625,
            "critical_strike_chance": 0.0,
            "magic_penetration_flat": 0.0,
            "magic_penetration_percent": 0.0,
            "armor_penetration_percent": 0.0,
            "lethality": 0.0,
            "ability_power": 100.0,
            "is_melee": False,
            "level": 9,
        }
        abilities = {
            "Q": {
                "name": "Utility Q",
                "parts": (),
                "total_raw": 0.0,
                "damage_type": "magic",
                "cooldown": 6.0,
            },
            "W": {
                "name": "Damage W",
                "parts": (DamagePart("magic", 150.0),),
                "total_raw": 150.0,
                "damage_type": "magic",
                "cooldown": 8.0,
            },
            "E": {
                "name": "Damage E",
                "parts": (DamagePart("magic", 100.0),),
                "total_raw": 100.0,
                "damage_type": "magic",
                "cooldown": 8.0,
            },
        }
        fight = calculate_fight_damage(
            stats,
            abilities,
            [{"name": "Horizon Focus"}],
            FightConfig(
                target_health=2000,
                target_armor=100,
                target_magic_resistance=0,
                fight_duration_seconds=0.5,
                auto_attack_uptime=0.0,
                one_rotation=True,
                cast_order=["Q", "W", "E"],
            ),
        )
        amp_entry = fight["breakdown"]["damage_amp_Horizon Focus"]
        assert amp_entry["damage_events"]
        assert "damage_amp_Horizon Focus" in fight["timeline_coverage"]["exact_sources"]


class TestHullbreakerSkipper:
    """Tests for Hullbreaker Skipper stacking on-hit proc."""

    def test_parsed_values_from_json(self) -> None:
        """Verify parser extracts correct values from item JSON data."""
        from src.calculator.item_effects import ITEM_EFFECTS

        effect = ITEM_EFFECTS.get("Hullbreaker")
        assert effect is not None, "Hullbreaker not found in ITEM_EFFECTS"
        assert effect["type"] == "on_hit_stacking"
        assert abs(effect["base_ad_ratio_melee"] - 1.20) < 0.001
        assert abs(effect["base_ad_ratio_ranged"] - 0.84) < 0.001
        assert abs(effect["max_hp_ratio_melee"] - 0.05) < 0.001
        assert abs(effect["max_hp_ratio_ranged"] - 0.035) < 0.001
        assert effect["hits_required"] == 5

    def test_proc_damage_melee(self) -> None:
        """Melee proc: 120% base AD + 5% max HP."""
        stats = {"base_attack_damage": 100.0, "health": 2000.0}
        effect = resolve_damage_effects(_build("Hullbreaker")).stacking_on_hits[0]
        damage = effect.source.raw_damage(DamageInputs(stats, 18, True, 1000, 1000))
        # 1.20 * 100 + 0.05 * 2000 = 120 + 100 = 220
        assert abs(damage - 220.0) < 0.1

    def test_proc_damage_ranged(self) -> None:
        """Ranged proc: 84% base AD + 3.5% max HP."""
        stats = {"base_attack_damage": 100.0, "health": 2000.0}
        effect = resolve_damage_effects(_build("Hullbreaker")).stacking_on_hits[0]
        damage = effect.source.raw_damage(DamageInputs(stats, 18, False, 1000, 1000))
        # 0.84 * 100 + 0.035 * 2000 = 84 + 70 = 154
        assert abs(damage - 154.0) < 0.1

    def test_stacking_procs_5_hits(self) -> None:
        """5 autos should yield exactly 1 proc."""
        _, proc_autos = _calculate_stacking_procs(5, set(), 0, 5)
        assert len(proc_autos) == 1
        assert proc_autos == [4]  # 0-indexed, 5th auto

    def test_stacking_procs_10_hits(self) -> None:
        """10 autos should yield exactly 2 procs."""
        _, proc_autos = _calculate_stacking_procs(10, set(), 0, 5)
        assert len(proc_autos) == 2

    def test_stacking_procs_4_hits_no_proc(self) -> None:
        """4 autos should yield 0 procs."""
        _, proc_autos = _calculate_stacking_procs(4, set(), 0, 5)
        assert len(proc_autos) == 0

    def test_phantom_hit_adds_stack_not_damage(self) -> None:
        """Phantom hit accelerates stacking but doesn't duplicate proc."""
        # 5 autos, phantom on auto #3 (0-indexed). Stacks:
        #   auto 0: 1, auto 1: 2, auto 2: 3, auto 3: 4+1(phantom)=5 -> proc
        #   auto 4: 1
        # Should get 1 proc on auto 3 (earlier than without phantom)
        _, proc_autos = _calculate_stacking_procs(5, {3}, 0, 5)
        assert len(proc_autos) == 1
        assert 3 in proc_autos  # Proc fires on auto 3, not 4

    def test_fight_damage_with_hullbreaker(self) -> None:
        """Integration: Hullbreaker procs appear in fight breakdown."""
        stats = {
            "attack_damage": 100.0,
            "base_attack_damage": 80.0,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "critical_strike_chance": 0.0,
            "magic_penetration_flat": 0.0,
            "magic_penetration_percent": 0.0,
            "armor_penetration_flat": 0.0,
            "armor_penetration_percent": 0.0,
            "lethality": 0.0,
            "ability_power": 0.0,
            "health": 2000.0,
            "is_melee": True,
            "level": 10,
        }
        fight = calculate_fight_damage(
            stats,
            {},
            [{"name": "Hullbreaker"}],
            FightConfig(
                target_health=3000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=10.0,
                auto_attack_uptime=1.0,
                auto_attacks_only=True,
            ),
        )
        hb_entry = fight["breakdown"].get("on_hit_Hullbreaker")
        assert hb_entry is not None, "Missing Hullbreaker breakdown entry"
        assert hb_entry["name"] == "Hullbreaker (Skipper)"
        assert hb_entry["count"] >= 1
        assert hb_entry["total_damage"] > 0


class TestMuramanaMultiCastR:
    """Tests for Muramana ability procs on multi-cast abilities like Ahri R."""

    def test_r_procs_muramana_per_dash(self) -> None:
        """Ahri R has 3 dashes — Muramana should proc 3 times, not 1."""
        stats = {
            "attack_damage": 80.0,
            "base_attack_damage": 60.0,
            "attack_speed": 0.7,
            "attack_speed_ratio": 0.625,
            "critical_strike_chance": 0.0,
            "magic_penetration_flat": 0.0,
            "magic_penetration_percent": 0.0,
            "armor_penetration_flat": 0.0,
            "armor_penetration_percent": 0.0,
            "lethality": 0.0,
            "ability_power": 100.0,
            "max_mana": 1500.0,
            "is_melee": False,
            "level": 18,
        }

        # Only R: 3 sub-casts
        abilities = {
            "R": {
                "name": "Spirit Rush",
                "parts": (DamagePart("magic", 200.0, count=3),),
                "cast_instances": 3,
                "total_raw": 600.0,
                "damage_type": "magic",
            },
        }

        fight = calculate_fight_damage(
            stats,
            abilities,
            [{"name": "Muramana"}],
            FightConfig(
                target_health=2000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=1.0,
                auto_attack_uptime=0.0,
                one_rotation=True,
                cast_order=["R"],
            ),
        )

        mura_entry = fight["breakdown"].get("muramana_ability")
        assert mura_entry is not None, "Missing Muramana ability breakdown"

        # Muramana ranged ability: 3% max mana per proc * 3 procs
        # = 0.03 * 1500 * 3 = 135 raw physical damage
        source = resolve_damage_effects(_build("Muramana")).per_ability_hits[0]
        per_proc = source.raw_damage(DamageInputs(stats, 18, False, 2000, 2000))
        expected_raw = per_proc * 3
        # After 100 armor: 50% mitigation
        expected_mitigated = expected_raw * 0.5
        assert abs(mura_entry["total_damage"] - expected_mitigated) < 1.0, (
            f"Expected ~{expected_mitigated:.1f}, got "
            f"{mura_entry['total_damage']:.1f}"
        )

    def test_single_cast_ability_procs_once(self) -> None:
        """A normal single-cast ability should proc Muramana once."""
        stats = {
            "attack_damage": 80.0,
            "base_attack_damage": 60.0,
            "attack_speed": 0.7,
            "attack_speed_ratio": 0.625,
            "critical_strike_chance": 0.0,
            "magic_penetration_flat": 0.0,
            "magic_penetration_percent": 0.0,
            "armor_penetration_flat": 0.0,
            "armor_penetration_percent": 0.0,
            "lethality": 0.0,
            "ability_power": 100.0,
            "max_mana": 1500.0,
            "is_melee": False,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test Q",
                "parts": (DamagePart("magic", 200.0),),
                "total_raw": 200.0,
                "damage_type": "magic",
                "cooldown": 7.0,
            },
        }

        fight = calculate_fight_damage(
            stats,
            abilities,
            [{"name": "Muramana"}],
            FightConfig(
                target_health=2000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=1.0,
                auto_attack_uptime=0.0,
                one_rotation=True,
                cast_order=["Q"],
            ),
        )

        mura_entry = fight["breakdown"].get("muramana_ability")
        assert mura_entry is not None
        # 1 proc: 0.03 * 1500 = 45 raw, mitigated by 100 armor = 22.5
        assert abs(mura_entry["total_damage"] - 22.5) < 1.0


class TestNavoriFlickerbladeFight:
    """Integration tests for Navori CD refund in fight calculations."""

    def test_more_casts_with_navori(self) -> None:
        """Navori should produce more ability casts than without."""
        stats = {
            "attack_damage": 100.0,
            "base_attack_damage": 70.0,
            "attack_speed": 1.5,
            "attack_speed_ratio": 0.625,
            "critical_strike_chance": 0.0,
            "magic_penetration_flat": 0.0,
            "magic_penetration_percent": 0.0,
            "armor_penetration_flat": 0.0,
            "armor_penetration_percent": 0.0,
            "lethality": 0.0,
            "ability_power": 0.0,
            "is_melee": False,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test Q",
                "parts": (DamagePart("magic", 200.0),),
                "total_raw": 200.0,
                "damage_type": "magic",
                "cooldown": 7.0,
            },
        }

        fight_no_navori = calculate_fight_damage(
            stats,
            abilities,
            [],
            FightConfig(
                target_health=2000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=15.0,
                auto_attack_uptime=0.8,
                cast_order=["Q"],
            ),
        )
        fight_navori = calculate_fight_damage(
            stats,
            abilities,
            [{"name": "Navori Flickerblade"}],
            FightConfig(
                target_health=2000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=15.0,
                auto_attack_uptime=0.8,
                cast_order=["Q"],
            ),
        )

        q_no = fight_no_navori["breakdown"]["Q"]["casts"]
        q_nav = fight_navori["breakdown"]["Q"]["casts"]
        assert q_nav > q_no, f"Navori should give more casts: {q_nav} vs {q_no} without"

    def test_r_not_affected(self) -> None:
        """R is always 1 cast — Navori should not change it."""
        stats = {
            "attack_damage": 100.0,
            "base_attack_damage": 70.0,
            "attack_speed": 1.5,
            "attack_speed_ratio": 0.625,
            "critical_strike_chance": 0.0,
            "magic_penetration_flat": 0.0,
            "magic_penetration_percent": 0.0,
            "armor_penetration_flat": 0.0,
            "armor_penetration_percent": 0.0,
            "lethality": 0.0,
            "ability_power": 0.0,
            "is_melee": False,
            "level": 18,
        }
        abilities = {
            "R": {
                "name": "Test R",
                "parts": (DamagePart("magic", 100.0, count=3),),
                "cast_instances": 3,
                "total_raw": 300.0,
                "damage_type": "magic",
            },
        }

        fight = calculate_fight_damage(
            stats,
            abilities,
            [{"name": "Navori Flickerblade"}],
            FightConfig(
                target_health=2000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=15.0,
                auto_attack_uptime=0.8,
                cast_order=["R"],
            ),
        )
        assert fight["breakdown"]["R"]["casts"] == 1

    def test_no_effect_in_one_rotation(self) -> None:
        """In one-rotation mode, Navori should not add extra casts."""
        stats = {
            "attack_damage": 100.0,
            "base_attack_damage": 70.0,
            "attack_speed": 1.5,
            "attack_speed_ratio": 0.625,
            "critical_strike_chance": 0.0,
            "magic_penetration_flat": 0.0,
            "magic_penetration_percent": 0.0,
            "armor_penetration_flat": 0.0,
            "armor_penetration_percent": 0.0,
            "lethality": 0.0,
            "ability_power": 0.0,
            "is_melee": False,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test Q",
                "parts": (DamagePart("magic", 200.0),),
                "total_raw": 200.0,
                "damage_type": "magic",
                "cooldown": 7.0,
            },
        }

        fight = calculate_fight_damage(
            stats,
            abilities,
            [{"name": "Navori Flickerblade"}],
            FightConfig(
                target_health=2000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=15.0,
                auto_attack_uptime=0.8,
                one_rotation=True,
                cast_order=["Q"],
            ),
        )
        assert fight["breakdown"]["Q"]["casts"] == 1

    def test_no_effect_without_autos(self) -> None:
        """With 0 uptime, Navori has no autos to refund with."""
        stats = {
            "attack_damage": 100.0,
            "base_attack_damage": 70.0,
            "attack_speed": 1.5,
            "attack_speed_ratio": 0.625,
            "critical_strike_chance": 0.0,
            "magic_penetration_flat": 0.0,
            "magic_penetration_percent": 0.0,
            "armor_penetration_flat": 0.0,
            "armor_penetration_percent": 0.0,
            "lethality": 0.0,
            "ability_power": 0.0,
            "is_melee": False,
            "level": 18,
        }
        abilities = {
            "Q": {
                "name": "Test Q",
                "parts": (DamagePart("magic", 200.0),),
                "total_raw": 200.0,
                "damage_type": "magic",
                "cooldown": 7.0,
            },
        }

        fight_no = calculate_fight_damage(
            stats,
            abilities,
            [],
            FightConfig(
                target_health=2000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=15.0,
                auto_attack_uptime=0.0,
                cast_order=["Q"],
            ),
        )
        fight_nav = calculate_fight_damage(
            stats,
            abilities,
            [{"name": "Navori Flickerblade"}],
            FightConfig(
                target_health=2000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=15.0,
                auto_attack_uptime=0.0,
                cast_order=["Q"],
            ),
        )
        assert (
            fight_no["breakdown"]["Q"]["casts"] == fight_nav["breakdown"]["Q"]["casts"]
        )


class TestStormrazor(_FightHarness):
    """Tests for Stormrazor's first-auto damage."""

    def test_stormrazor_first_auto_damage(self) -> None:
        """Stormrazor deals 100 magic damage on first auto (one proc)."""
        stats = self._make_stats()
        result = self.fight(
            stats,
            target_health=2000,
            target_armor=50,
            target_magic_resistance=50,
            fight_duration_seconds=10.0,
            auto_attack_uptime=0.8,
            items=[{"name": "Stormrazor"}],
        )
        assert "on_hit_once_Stormrazor" in result["breakdown"]
        entry = result["breakdown"]["on_hit_once_Stormrazor"]
        assert entry["damage_type"] == "magic"
        assert entry["total_damage"] > 0


class TestStatikkShiv(_FightHarness):
    """Tests for Statikk Shiv's attack-recharged Electrospark proc."""

    def test_statikk_shiv_one_empowered_auto(self) -> None:
        """Electrospark repeats after its parser-sourced attack recharge."""
        stats = self._make_stats()
        result = self.fight(
            stats,
            target_health=2000,
            target_armor=50,
            target_magic_resistance=50,
            fight_duration_seconds=10.0,
            auto_attack_uptime=0.8,
            items=[{"name": "Statikk Shiv"}],
        )
        assert "on_hit_once_Statikk Shiv" in result["breakdown"]
        entry = result["breakdown"]["on_hit_once_Statikk Shiv"]
        assert entry["count"] == 2
        assert entry["damage_type"] == "magic"

    def test_statikk_shiv_no_autos_no_proc(self) -> None:
        """Without any auto attacks there is no Electrospark proc."""
        stats = self._make_stats()
        result = self.fight(
            stats,
            target_health=2000,
            target_armor=50,
            target_magic_resistance=50,
            fight_duration_seconds=1.0,
            auto_attack_uptime=0.0,
            items=[{"name": "Statikk Shiv"}],
        )
        assert "on_hit_once_Statikk Shiv" not in result["breakdown"]

    def test_statikk_chain_allocates_one_proc_across_selected_roster(self) -> None:
        """Electrospark reaches each selected chain target once, not N times."""
        stats = self._make_stats()
        results = [
            self.fight(
                stats,
                target_health=2000,
                target_armor=0,
                target_magic_resistance=0,
                fight_duration_seconds=5.0,
                auto_attack_uptime=0.8,
                roster_target_index=index,
                roster_target_count=3,
                items=[{"name": "Statikk Shiv"}],
            )
            for index in range(4)
        ]

        assert [
            result["breakdown"].get("on_hit_once_Statikk Shiv", {}).get("count", 0)
            for result in results
        ] == [1, 1, 1, 0]
        assert all(
            result["breakdown"]["on_hit_once_Statikk Shiv"]["targeting"]["kind"]
            == "chain_lightning"
            for result in results[:3]
        )
        assert "on_hit_once_Statikk Shiv" not in results[3]["breakdown"]

    def test_statikk_chain_replays_per_hit_packets_on_secondary_targets(
        self,
    ) -> None:
        """Per-hit effects ride Electrospark's secondary packet once."""
        stats = self._make_stats()
        primary = self.fight(
            stats,
            target_health=2000,
            target_armor=0,
            target_magic_resistance=0,
            fight_duration_seconds=5.0,
            auto_attack_uptime=0.8,
            roster_target_index=0,
            roster_target_count=2,
            items=[{"name": "Statikk Shiv"}, {"name": "Wit's End"}],
        )
        secondary = self.fight(
            stats,
            target_health=2000,
            target_armor=0,
            target_magic_resistance=0,
            fight_duration_seconds=5.0,
            auto_attack_uptime=0.8,
            roster_target_index=1,
            roster_target_count=2,
            items=[{"name": "Statikk Shiv"}, {"name": "Wit's End"}],
        )

        assert "on_hit_chain_Statikk Shiv" not in primary["breakdown"]
        copied = secondary["breakdown"]["on_hit_chain_Statikk Shiv"]
        assert copied["total_damage"] == pytest.approx(45.0)
        assert copied["targeting"]["copied_on_hit_scope"] == "per_hit_source_packets"

    def test_statikk_chain_replays_stack_gated_on_hits(self) -> None:
        """Copied Electrospark hits advance Kraken's secondary ledger."""
        stats = self._make_stats()
        secondary = self.fight(
            stats,
            target_health=2000,
            target_armor=0,
            target_magic_resistance=0,
            fight_duration_seconds=20.0,
            auto_attack_uptime=0.8,
            roster_target_index=1,
            roster_target_count=2,
            items=[{"name": "Statikk Shiv"}, {"name": "Kraken Slayer"}],
        )

        copied = secondary["breakdown"]["on_hit_chain_Statikk Shiv"]
        assert copied["targeting"]["copied_stacking_on_hits"] is True
        # Three Electrospark chain hits land at 0, 8.75, and 17.5 s;
        # the third copied on-hit completes Kraken's three-hit counter.
        assert copied["total_damage"] > 0.0
        assert copied["damage_events"][-1]["time"] == pytest.approx(17.5)

    def test_statikk_parser_includes_attack_energize_branch(self) -> None:
        from src.calculator.data_fetcher import fetch_item_data
        from src.calculator.passive_parser import parse_item_effect

        parsed = parse_item_effect("Statikk Shiv", fetch_item_data())
        assert parsed["energized_attack_stacks"] == 15
        assert parsed["energized_max_stacks"] == 100


class TestRunaanHurricane(_FightHarness):
    """Tests for Wind's Fury roster allocation and copied fixed on-hits."""

    def test_runaan_bolts_allocate_one_per_secondary_roster_target(self) -> None:
        stats = self._make_stats()
        results = [
            self.fight(
                stats,
                target_health=2000,
                target_armor=0,
                target_magic_resistance=0,
                fight_duration_seconds=5.0,
                auto_attack_uptime=0.8,
                roster_target_index=index,
                roster_target_count=4,
                items=[{"name": "Runaan's Hurricane"}],
            )
            for index in range(5)
        ]

        assert "secondary_Runaan's Hurricane" not in results[0]["breakdown"]
        assert [
            result["breakdown"].get("secondary_Runaan's Hurricane", {}).get("count", 0)
            for result in results
        ] == [0, 4, 4, 0, 0]
        assert (
            results[1]["breakdown"]["secondary_Runaan's Hurricane"]["targeting"]["kind"]
            == "runaan_bolt"
        )

    def test_runaan_bolts_replay_per_hit_source_on_hits(self) -> None:
        stats = self._make_stats()
        secondary = self.fight(
            stats,
            target_health=2000,
            target_armor=0,
            target_magic_resistance=0,
            fight_duration_seconds=5.0,
            auto_attack_uptime=0.8,
            roster_target_index=1,
            roster_target_count=2,
            items=[{"name": "Runaan's Hurricane"}, {"name": "Wit's End"}],
        )

        copied = secondary["breakdown"]["on_hit_secondary_Runaan's Hurricane"]
        assert copied["total_damage"] > 0.0
        assert copied["targeting"]["copied_on_hit_scope"] == "per_hit_source_packets"

    @pytest.mark.parametrize(
        "item_name", ["Tiamat", "Profane Hydra", "Ravenous Hydra", "Stridebreaker"]
    )
    def test_cleave_on_hit_replays_secondary_roster_packets(
        self, item_name: str
    ) -> None:
        """Cleave's basic-attack splash is timestamped for secondary slots."""
        secondary = self.fight(
            self._make_stats(),
            one_rotation=False,
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
            target_health=3000.0,
            target_armor=0.0,
            target_magic_resistance=0.0,
            roster_target_index=1,
            roster_target_count=2,
            items=[{"name": item_name}],
        )

        row = secondary["breakdown"][f"on_hit_secondary_{item_name}"]
        assert row["count"] == secondary["breakdown"]["auto_attacks"]["count"]
        assert len(row["damage_events"]) == row["count"]
        assert sum(event["damage"] for event in row["damage_events"]) == pytest.approx(
            row["total_damage"]
        )
        assert row["targeting"]["kind"] == "cleave_secondary"


class TestTitanicHydra(_FightHarness):
    """Tests for Titanic Hydra's Crescent active."""

    def test_titanic_hydra_active_in_breakdown(self) -> None:
        """Titanic Hydra Crescent active appears in fight breakdown."""
        stats = self._make_stats(health=3000.0)
        result = self.fight(
            stats,
            target_health=2000,
            target_armor=50,
            target_magic_resistance=50,
            fight_duration_seconds=10.0,
            auto_attack_uptime=0.8,
            items=[{"name": "Titanic Hydra"}],
        )
        assert "active_Titanic Hydra" in result["breakdown"]
        entry = result["breakdown"]["active_Titanic Hydra"]
        assert entry["damage_type"] == "physical"
        # 4% of 3000 HP = 120 raw per proc
        assert entry["total_damage"] > 0

    def test_titanic_cleave_allocates_secondary_roster_packet(self) -> None:
        """Cleave is replayed once per authored swing on each secondary slot."""
        result = self.fight(
            self._make_stats(health=3000.0),
            one_rotation=False,
            target_health=3000.0,
            target_armor=0.0,
            target_magic_resistance=0.0,
            fight_duration_seconds=12.0,
            auto_attack_uptime=1.0,
            roster_target_index=1,
            roster_target_count=3,
            items=[{"name": "Titanic Hydra"}],
        )

        row = result["breakdown"]["secondary_Titanic Hydra"]
        assert row["count"] == result["breakdown"]["auto_attacks"]["count"]
        assert row["targeting"] == {
            "kind": "hydra_cleave",
            "secondary_target_count": 2,
            "allocated_target_index": 1,
            "roster_target_count": 3,
        }
        assert len(row["damage_events"]) == row["count"]
        assert sum(event["damage"] for event in row["damage_events"]) == pytest.approx(
            row["total_damage"]
        )
        assert row["damage_events"][0]["damage"] == pytest.approx(270.0)
        assert row["damage_events"][1]["damage"] == pytest.approx(90.0)
        assert row["damage_events"][10]["damage"] == pytest.approx(270.0)

        primary = self.fight(
            self._make_stats(health=3000.0),
            one_rotation=False,
            target_health=3000.0,
            target_armor=0.0,
            target_magic_resistance=0.0,
            fight_duration_seconds=12.0,
            auto_attack_uptime=1.0,
            roster_target_index=0,
            roster_target_count=3,
            items=[{"name": "Titanic Hydra"}],
        )
        assert "secondary_Titanic Hydra" not in primary["breakdown"]


class TestSpearOfShojin:
    """Tests for Spear of Shojin's basic-ability haste rule."""

    def test_spear_of_shojin_basic_haste_reduces_q_cd(self) -> None:
        """Basic ability haste reduces Q/W/E cooldowns but not R.

        Verifies via effective_cooldown formula:
        - Q at 6s base, 0 ability haste, 25 basic = 6 * 100/125 = 4.8s
        - R at 60s base, 0 ability haste, 25 basic = still 60s (no basic haste)
        """
        from src.calculator.damage import effective_cooldown

        base_q_cd = 6.0
        base_r_cd = 60.0
        ability_haste = 0.0
        basic_haste = 25.0

        # Q with basic ability haste should be shorter
        q_no_basic = effective_cooldown(base_q_cd, ability_haste)
        q_with_basic = effective_cooldown(base_q_cd, ability_haste + basic_haste)
        assert q_with_basic < q_no_basic
        assert abs(q_with_basic - 4.8) < 0.01

        # R should NOT use basic ability haste
        r_cd = effective_cooldown(base_r_cd, ability_haste)
        assert abs(r_cd - 60.0) < 0.01


class TestSunderedSky(_FightHarness):
    """Tests for Sundered Sky first-auto crit modifier."""

    def test_sundered_sky_first_auto_crits(self) -> None:
        """First auto with Sundered Sky always crits at reduced ratio."""
        stats = self._make_stats(critical_strike_chance=0.0)
        result = calculate_fight_damage(
            stats,
            {},
            [{"name": "Sundered Sky"}],
            FightConfig(
                target_health=2000,
                target_armor=0,
                target_magic_resistance=50,
                fight_duration_seconds=1.0,
                auto_attack_uptime=1.0,
            ),
        )
        auto_entry = result["breakdown"]["auto_attacks"]
        # With 0% crit chance and 1 auto attack, the first auto should
        # still deal more than base AD because of Sundered Sky crit
        assert auto_entry["total_damage"] > 100.0

    def test_sundered_sky_overrides_natural_crit(self) -> None:
        """Even with 100% crit chance, Sundered Sky overrides first auto.

        With 100% crit, normal crit = 200% AD = 200 damage.
        Sundered Sky = 80% of crit = 80% * 200% = 160% AD = 160.
        So Sundered Sky first auto should deal LESS than a normal crit.
        """
        stats = self._make_stats(critical_strike_chance=100.0)
        # Many autos to average: first auto is Sundered Sky, rest are normal crits
        result = calculate_fight_damage(
            stats,
            {},
            [{"name": "Sundered Sky"}],
            FightConfig(
                target_health=5000,
                target_armor=0,
                target_magic_resistance=50,
                fight_duration_seconds=5.0,
                auto_attack_uptime=1.0,
            ),
        )
        auto_entry = result["breakdown"]["auto_attacks"]
        # With 100% crit and 0 armor, normal crit = 200. SS auto = 160.
        # Total should be less than all_crits * count
        count = auto_entry["count"]
        all_normal_crits = 200.0 * count
        assert auto_entry["total_damage"] < all_normal_crits

    def test_sundered_sky_reads_from_registry(self, monkeypatch) -> None:
        """Sundered Sky uses ITEM_EFFECTS registry, not hardcoded values."""
        from src.calculator import item_effects

        patched = dict(item_effects.ITEM_EFFECTS.get("Sundered Sky", {}))
        patched["reduced_crit_ratio"] = 0.50  # 50% instead of 80%
        monkeypatch.setitem(item_effects.ITEM_EFFECTS, "Sundered Sky", patched)

        stats = self._make_stats(critical_strike_chance=0.0)
        result = calculate_fight_damage(
            stats,
            {},
            [{"name": "Sundered Sky"}],
            FightConfig(
                target_health=2000,
                target_armor=0,
                target_magic_resistance=50,
                fight_duration_seconds=2.0,
                auto_attack_uptime=1.0,
            ),
        )
        auto_entry = result["breakdown"]["auto_attacks"]
        # First auto: 50% of crit_multiplier(2.0) = 1.0 * 100 AD = 100
        # Second auto: normal (no crit) = 100
        # Total = 200, average = 100
        assert auto_entry["count"] == 2
        assert auto_entry["total_damage"] == 200.0

    def test_sundered_sky_parsed_values(self) -> None:
        """Parser extracts reduced_crit_ratio and cooldown from JSON."""
        from src.calculator.passive_parser import parse_item_effect
        from src.calculator.data_fetcher import fetch_item_data

        items = fetch_item_data()
        parsed = parse_item_effect("Sundered Sky", items)
        assert parsed is not None
        assert parsed["reduced_crit_ratio"] == 0.80
        assert parsed["cooldown"] == 10.0

    def test_sundered_sky_emits_its_first_attack_heal_receipt(self) -> None:
        """Lightshield Strike's base-AD heal is timestamped with the first auto."""
        stats = self._make_stats(critical_strike_chance=0.0)
        result = calculate_fight_damage(
            stats,
            {},
            [{"name": "Sundered Sky"}],
            FightConfig(
                target_health=2000,
                target_armor=0,
                target_magic_resistance=50,
                fight_duration_seconds=1.0,
                auto_attack_uptime=1.0,
            ),
        )

        row = result["breakdown"]["heal_Sundered Sky"]
        assert row["count"] == 1
        assert row["amount_per_proc"] == pytest.approx(100.0)
        assert row["heal_events"][0]["time"] == pytest.approx(0.0)
        assert callable(row["heal_events"][0]["amount_formula"])
        assert row["heal_events"][0]["temporary_health_duration"] == pytest.approx(8.0)


class TestVoltaicCyclosword(_FightHarness):
    """Tests for Voltaic Cyclosword energized first-auto damage."""

    def test_voltaic_first_auto_damage(self) -> None:
        """Voltaic Cyclosword deals physical damage on first auto."""
        stats = self._make_stats()
        result = calculate_fight_damage(
            stats,
            {},
            [{"name": "Voltaic Cyclosword"}],
            FightConfig(
                target_health=2000,
                target_armor=50,
                target_magic_resistance=50,
                fight_duration_seconds=10.0,
                auto_attack_uptime=0.8,
            ),
        )
        assert "on_hit_once_Voltaic Cyclosword" in result["breakdown"]
        entry = result["breakdown"]["on_hit_once_Voltaic Cyclosword"]
        assert entry["damage_type"] == "physical"
        assert entry["total_damage"] > 0
        assert entry["temporary_lethality"]["amount"] == 15.0
        assert entry["temporary_lethality"]["duration"] == 4.0
        assert entry["temporary_lethality"]["applied_to_triggering_event"] is True
        assert entry["temporary_lethality"]["applied_to_later_events"] is True
        assert entry["temporary_lethality"]["applied_event_count"] == 5

        # Firmament applies before its opening packet and the triggering
        # attack, while later swings through the four-second window use 35
        # effective armor.
        auto_events = result["breakdown"]["auto_attacks"]["damage_events"]
        assert auto_events[0]["damage"] == pytest.approx(100 / 1.35)
        assert auto_events[1]["damage"] == pytest.approx(100 / 1.35)
        assert auto_events[3]["damage"] == pytest.approx(100 / 1.35)
        assert auto_events[4]["damage"] == pytest.approx(100 / 1.5)

    def test_voltaic_recharges_and_reads_current_health(self) -> None:
        """Attack recharge and current-health scaling are both replayed.

        Melee vs 5000 HP: the first proc is ready immediately and the second
        attack-only proc arrives after the sourced six-stack recharge. The
        second packet is smaller because the target has already taken damage.
        """
        stats = self._make_stats()
        result = calculate_fight_damage(
            stats,
            {},
            [{"name": "Voltaic Cyclosword"}],
            FightConfig(
                target_health=5000,
                target_armor=50,
                target_magic_resistance=50,
                fight_duration_seconds=20.0,
                auto_attack_uptime=1.0,
            ),
        )
        entry = result["breakdown"]["on_hit_once_Voltaic Cyclosword"]
        assert entry["count"] == 2
        assert entry["damage_events"][0]["damage"] > entry["damage_events"][1]["damage"]

    def test_voltaic_current_hp_below_cap(self) -> None:
        """Melee vs 2000 HP: 9% current HP = 180, under the 200 cap."""
        stats = self._make_stats()
        result = calculate_fight_damage(
            stats,
            {},
            [{"name": "Voltaic Cyclosword"}],
            FightConfig(
                target_health=2000,
                target_armor=0,
                target_magic_resistance=50,
                fight_duration_seconds=5.0,
                auto_attack_uptime=0.8,
            ),
        )
        entry = result["breakdown"]["on_hit_once_Voltaic Cyclosword"]
        assert entry["total_damage"] == pytest.approx(180.0)

    def test_voltaic_ranged_ratio(self) -> None:
        """Ranged vs 2000 HP: 7% current HP = 140."""
        stats = self._make_stats(is_melee=False)
        result = calculate_fight_damage(
            stats,
            {},
            [{"name": "Voltaic Cyclosword"}],
            FightConfig(
                target_health=2000,
                target_armor=0,
                target_magic_resistance=50,
                fight_duration_seconds=5.0,
                auto_attack_uptime=0.8,
            ),
        )
        entry = result["breakdown"]["on_hit_once_Voltaic Cyclosword"]
        assert entry["total_damage"] == pytest.approx(140.0)

    def test_voltaic_galvanize_triggers_before_damaging_ability(self) -> None:
        """V26.09 Galvanize consumes the ready charge before an ability."""
        stats = self._make_stats()
        abilities = {
            "Q": {
                "name": "Test ability",
                "rank": 1,
                "cooldown": 5.0,
                "parts": (DamagePart("magic", 100.0),),
                "total_raw": 100.0,
                "damage_type": "magic",
            }
        }
        result = calculate_fight_damage(
            stats,
            abilities,
            [{"name": "Voltaic Cyclosword"}],
            FightConfig(
                target_health=2000,
                target_armor=50,
                target_magic_resistance=50,
                fight_duration_seconds=1.0,
                auto_attack_uptime=0.0,
                one_rotation=True,
            ),
        )
        row = result["breakdown"]["on_hit_once_Voltaic Cyclosword_ability"]
        assert row["count"] == 1
        assert row["damage_events"][0]["time"] == pytest.approx(0.0)
        assert row["temporary_lethality"]["applied_to_triggering_event"] is True
        ledger = result["damage_events"]
        assert ledger[0]["source_key"] == "on_hit_once_Voltaic Cyclosword_ability"
        assert ledger[0]["order"] < ledger[1]["order"]

    def test_voltaic_parsed_values(self) -> None:
        """Parser extracts the reworked Firmament: current-HP physical damage
        (melee 9% / ranged 7%) capped at 200."""
        from src.calculator.passive_parser import parse_item_effect
        from src.calculator.data_fetcher import fetch_item_data

        items = fetch_item_data()
        parsed = parse_item_effect("Voltaic Cyclosword", items)
        assert parsed is not None
        assert parsed["current_hp_ratio_melee"] == pytest.approx(0.09)
        assert parsed["current_hp_ratio_ranged"] == pytest.approx(0.07)
        assert parsed["damage_cap"] == 200.0
        assert parsed["temporary_lethality_melee"] == 15.0
        assert parsed["temporary_lethality_ranged"] == 12.0
        assert parsed["temporary_lethality_duration"] == 4.0
        assert parsed["damage_type"] == "physical"

    def test_voltaic_reads_from_registry(self, monkeypatch) -> None:
        """Voltaic Cyclosword uses ITEM_EFFECTS registry."""
        from src.calculator import item_effects

        patched = dict(item_effects.ITEM_EFFECTS.get("Voltaic Cyclosword", {}))
        patched["current_hp_ratio_melee"] = 0.10
        monkeypatch.setitem(item_effects.ITEM_EFFECTS, "Voltaic Cyclosword", patched)

        stats = self._make_stats()
        result = calculate_fight_damage(
            stats,
            {},
            [{"name": "Voltaic Cyclosword"}],
            FightConfig(
                target_health=2000,
                target_armor=0,
                target_magic_resistance=50,
                fight_duration_seconds=5.0,
                auto_attack_uptime=0.8,
            ),
        )
        entry = result["breakdown"]["on_hit_once_Voltaic Cyclosword"]
        # 10% of 2000 = 200 (patched ratio, zero armor)
        assert entry["total_damage"] == 200.0


class TestUnendingDespair(_FightHarness):
    """Tests for Unending Despair periodic AoE damage."""

    def test_unending_despair_in_breakdown(self) -> None:
        """Unending Despair Anguish appears in fight breakdown."""
        stats = self._make_stats(health=3000.0, bonus_health=1000.0)
        result = calculate_fight_damage(
            stats,
            {},
            [{"name": "Unending Despair"}],
            FightConfig(
                target_health=2000,
                target_armor=50,
                target_magic_resistance=50,
                fight_duration_seconds=10.0,
                auto_attack_uptime=0.0,
            ),
        )
        assert "periodic_Unending Despair" in result["breakdown"]
        entry = result["breakdown"]["periodic_Unending Despair"]
        assert entry["damage_type"] == "magic"
        assert entry["total_damage"] > 0

    def test_unending_despair_proc_count(self) -> None:
        """Procs at 4s intervals: 10s fight = 2 procs (at 4s and 8s)."""
        stats = self._make_stats(health=3000.0, bonus_health=1000.0)
        result = calculate_fight_damage(
            stats,
            {},
            [{"name": "Unending Despair"}],
            FightConfig(
                target_health=2000,
                target_armor=50,
                target_magic_resistance=0,
                fight_duration_seconds=10.0,
                auto_attack_uptime=0.0,
            ),
        )
        entry = result["breakdown"]["periodic_Unending Despair"]
        # 2 procs * 3% of 1000 bonus HP = 2 * 30 = 60 raw magic damage
        # 0 MR = 60 mitigated
        assert abs(entry["total_damage"] - 60.0) < 1.0

    def test_unending_despair_no_bonus_health_no_damage(self) -> None:
        """With 0 bonus health, Anguish deals no damage."""
        stats = self._make_stats(health=3000.0, bonus_health=0.0)
        result = calculate_fight_damage(
            stats,
            {},
            [{"name": "Unending Despair"}],
            FightConfig(
                target_health=2000,
                target_armor=50,
                target_magic_resistance=50,
                fight_duration_seconds=10.0,
                auto_attack_uptime=0.0,
            ),
        )
        assert "periodic_Unending Despair" not in result["breakdown"]

    def test_unending_despair_parsed_values(self) -> None:
        """Parser extracts interval and bonus_hp_ratio from JSON."""
        from src.calculator.passive_parser import parse_item_effect
        from src.calculator.data_fetcher import fetch_item_data

        items = fetch_item_data()
        parsed = parse_item_effect("Unending Despair", items)
        assert parsed is not None
        assert parsed["interval"] == 4.0
        assert parsed["bonus_hp_ratio"] == 0.03

    def test_unending_despair_reads_from_registry(self, monkeypatch) -> None:
        """Unending Despair uses ITEM_EFFECTS registry."""
        from src.calculator import item_effects

        patched = dict(item_effects.ITEM_EFFECTS.get("Unending Despair", {}))
        patched["bonus_hp_ratio"] = 0.10  # 10% instead of 3%
        monkeypatch.setitem(item_effects.ITEM_EFFECTS, "Unending Despair", patched)

        stats = self._make_stats(health=3000.0, bonus_health=1000.0)
        result = calculate_fight_damage(
            stats,
            {},
            [{"name": "Unending Despair"}],
            FightConfig(
                target_health=2000,
                target_armor=50,
                target_magic_resistance=0,
                fight_duration_seconds=10.0,
                auto_attack_uptime=0.0,
            ),
        )
        entry = result["breakdown"]["periodic_Unending Despair"]
        # 2 procs * 10% of 1000 bonus HP = 200 raw
        assert abs(entry["total_damage"] - 200.0) < 1.0


class TestTerminusPenetration(_FightHarness):
    """Tests for Terminus armor/magic penetration stacking."""

    def test_terminus_pen_reduces_effective_armor(self) -> None:
        """Terminus pen reduces effective armor vs no Terminus."""
        stats = self._make_stats()
        result_no_terminus = calculate_fight_damage(
            stats,
            {},
            [],
            FightConfig(
                target_health=2000,
                target_armor=100,
                target_magic_resistance=50,
                fight_duration_seconds=10.0,
                auto_attack_uptime=0.8,
            ),
        )
        result_with_terminus = calculate_fight_damage(
            stats,
            {},
            [{"name": "Terminus"}],
            FightConfig(
                target_health=2000,
                target_armor=100,
                target_magic_resistance=50,
                fight_duration_seconds=10.0,
                auto_attack_uptime=0.8,
            ),
        )
        # With Terminus pen, effective armor should be lower
        assert (
            result_with_terminus["effective_armor"]
            < result_no_terminus["effective_armor"]
        )

    def test_terminus_pen_increases_total_damage(self) -> None:
        """Terminus pen should increase total damage dealt."""
        stats = self._make_stats()
        result_no = calculate_fight_damage(
            stats,
            {},
            [],
            FightConfig(
                target_health=2000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=10.0,
                auto_attack_uptime=0.8,
            ),
        )
        result_with = calculate_fight_damage(
            stats,
            {},
            [{"name": "Terminus"}],
            FightConfig(
                target_health=2000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=10.0,
                auto_attack_uptime=0.8,
            ),
        )
        assert result_with["total_damage"] > result_no["total_damage"]

    def test_terminus_pen_parsed_values(self) -> None:
        """Parser extracts dark_pen_per_stack and dark_max_stacks."""
        from src.calculator.passive_parser import parse_item_effect
        from src.calculator.data_fetcher import fetch_item_data

        items = fetch_item_data()
        parsed = parse_item_effect("Terminus", items)
        assert parsed is not None
        assert parsed["dark_pen_per_stack"] == 0.10
        assert parsed["dark_max_stacks"] == 3


class TestCollectorThreshold(_FightHarness):
    """Tests for The Collector execution threshold display."""

    def test_collector_shows_threshold_not_damage(self) -> None:
        """Collector shows execution threshold but adds 0 damage."""
        stats = self._make_stats()
        result = calculate_fight_damage(
            stats,
            {},
            [{"name": "The Collector"}],
            FightConfig(
                target_health=2000,
                target_armor=50,
                target_magic_resistance=50,
                fight_duration_seconds=10.0,
                auto_attack_uptime=0.8,
            ),
        )
        assert "execute" in result["breakdown"]
        entry = result["breakdown"]["execute"]
        assert entry["total_damage"] == 0.0
        assert entry["execution_threshold_hp"] == 100.0  # 5% of 2000
        assert "Collector Execution Threshold" in entry["detail"]

    def test_collector_threshold_scales_with_target_health(self) -> None:
        """Threshold scales with target max health."""
        stats = self._make_stats()
        result = calculate_fight_damage(
            stats,
            {},
            [{"name": "The Collector"}],
            FightConfig(
                target_health=4000,
                target_armor=50,
                target_magic_resistance=50,
                fight_duration_seconds=10.0,
                auto_attack_uptime=0.8,
            ),
        )
        entry = result["breakdown"]["execute"]
        assert entry["execution_threshold_hp"] == 200.0  # 5% of 4000

    def test_collector_parsed_values(self) -> None:
        """Parser extracts threshold from JSON."""
        from src.calculator.passive_parser import parse_item_effect
        from src.calculator.data_fetcher import fetch_item_data

        items = fetch_item_data()
        parsed = parse_item_effect("The Collector", items)
        assert parsed is not None
        assert parsed["threshold"] == 0.05

    def test_collector_reads_from_registry(self, monkeypatch) -> None:
        """Collector threshold uses ITEM_EFFECTS registry."""
        from src.calculator import item_effects

        patched = dict(item_effects.ITEM_EFFECTS.get("The Collector", {}))
        patched["threshold"] = 0.10  # 10% instead of 5%
        monkeypatch.setitem(item_effects.ITEM_EFFECTS, "The Collector", patched)

        stats = self._make_stats()
        result = calculate_fight_damage(
            stats,
            {},
            [{"name": "The Collector"}],
            FightConfig(
                target_health=2000,
                target_armor=50,
                target_magic_resistance=50,
                fight_duration_seconds=10.0,
                auto_attack_uptime=0.8,
            ),
        )
        entry = result["breakdown"]["execute"]
        assert entry["execution_threshold_hp"] == 200.0  # 10% of 2000


class TestOnHitItemSwingEvents(_FightHarness):
    """On-hit item rows author per-swing damage events (phase 1).

    Every on-hit application in these fights rides a simulated auto
    swing, so the item rows stamp their events at those swing times and
    the timeline classifier certifies them exact. Event sums must equal
    the row totals — that IS the classifier's exactness contract.
    """

    def _timed_fight(self, items, *, duration=5.0):
        """Timed fight at full uptime; stateful items may accelerate swings."""
        return self.fight(
            self._make_stats(),
            one_rotation=False,
            fight_duration_seconds=duration,
            auto_attack_uptime=1.0,
            target_health=3000.0,
            target_armor=0.0,
            target_magic_resistance=0.0,
            items=items,
        )

    def test_static_on_hit_item_authors_per_swing_events(self) -> None:
        """Wit's End stamps one uniform event per auto swing."""
        result = self._timed_fight([{"name": "Wit's End"}])

        row = result["breakdown"]["on_hit_Wit's End"]
        events = row["damage_events"]
        auto_times = [
            event["time"]
            for event in result["breakdown"]["auto_attacks"]["damage_events"]
        ]
        assert [event["time"] for event in events] == auto_times
        assert all(
            event["damage"] == pytest.approx(row["damage_per_hit"]) for event in events
        )
        assert sum(event["damage"] for event in events) == pytest.approx(
            row["total_damage"]
        )
        assert "on_hit_Wit's End" in result["timeline_coverage"]["exact_sources"]

    def test_bork_authors_declining_per_swing_events(self) -> None:
        """BoRK's current-HP simulation emits its per-swing values."""
        result = self._timed_fight([{"name": "Blade of the Ruined King"}])

        row = result["breakdown"]["on_hit_Blade of the Ruined King"]
        events = row["damage_events"]
        assert len(events) == row["count"]
        assert [event["time"] for event in events] == [0.0, 1.0, 2.0, 3.0, 4.0]
        damages = [event["damage"] for event in events]
        assert damages == sorted(damages, reverse=True)  # HP decays per swing
        assert damages[0] > damages[-1]
        assert sum(damages) == pytest.approx(row["total_damage"])
        assert (
            "on_hit_Blade of the Ruined King"
            in result["timeline_coverage"]["exact_sources"]
        )

    def test_phantom_hits_double_the_events_on_their_swings(self) -> None:
        """A Rageblade phantom swing carries a second on-hit event."""
        result = self._timed_fight(
            [{"name": "Guinsoo's Rageblade"}, {"name": "Wit's End"}],
            duration=10.0,
        )

        assert result["phantom_hit_autos"] == {5, 8, 11}
        row = result["breakdown"]["on_hit_Wit's End"]
        events = row["damage_events"]
        assert len(events) == 15  # 12 swings + 3 phantom applications
        times = [event["time"] for event in events]
        auto_times = [
            event["time"]
            for event in result["breakdown"]["auto_attacks"]["damage_events"]
        ]
        for index in (5, 8, 11):
            assert times.count(auto_times[index]) == 2
        assert sum(event["damage"] for event in events) == pytest.approx(
            row["total_damage"]
        )
        assert "on_hit_Wit's End" in result["timeline_coverage"]["exact_sources"]
        assert (
            "on_hit_Guinsoo's Rageblade" in result["timeline_coverage"]["exact_sources"]
        )

    def test_kraken_counter_procs_author_swing_events(self) -> None:
        """Kraken's every-3rd-hit procs stamp the swing that landed them."""
        result = self._timed_fight([{"name": "Kraken Slayer"}], duration=9.0)

        row = result["breakdown"]["on_hit_Kraken Slayer"]
        events = row["damage_events"]
        assert [event["time"] for event in events] == [2.0, 5.0, 8.0]
        assert sum(event["damage"] for event in events) == pytest.approx(
            row["total_damage"]
        )
        assert "on_hit_Kraken Slayer" in result["timeline_coverage"]["exact_sources"]


class TestSingleProcAndScheduledEventAuthoring(_FightHarness):
    """Single-proc and scheduled effects author real event times (phase 2).

    On-hit-once procs ride their triggering swing, Titanic's Crescent
    rides cooldown-gated swings, Stormsurge stamps the ledger moment its
    burst threshold was crossed, Malignance's Hatefog starts at the R
    cast, spellblades emit weave-timed events per proc, and item actives
    stamp the engine's rotation-position assumption. Event sums must
    equal the row totals — that IS the classifier's exactness contract.
    """

    def _timed_fight(self, items, *, duration=5.0, **overrides):
        """Timed fight at 1.0 AS / full uptime: swings at 0..duration-1."""
        config = {
            "one_rotation": False,
            "fight_duration_seconds": duration,
            "auto_attack_uptime": 1.0,
            "target_health": 3000.0,
            "target_armor": 0.0,
            "target_magic_resistance": 0.0,
            "items": items,
        }
        config.update(overrides)
        return self.fight(self._make_stats(), **config)

    def _ahri_fight(self, champion_data, item_names, **overrides):
        """Timed 10s fight with real casts and the named items."""
        from src.calculator.stats import calculate_total_stats
        from src.calculator.data_fetcher import get_item_by_name

        items = [get_item_by_name(name) for name in item_names]
        stats = calculate_total_stats(champion_data, 18, items)
        abilities = parse_ahri_abilities(champion_data, 18, stats["ability_power"])
        config = {
            "target_health": 3000.0,
            "target_armor": 100.0,
            "target_magic_resistance": 0.0,
            "fight_duration_seconds": 10.0,
            "auto_attack_uptime": 0.1,
            "one_rotation": False,
            "deterministic": True,
        }
        config.update(overrides)
        return calculate_fight_damage(stats, abilities, items, FightConfig(**config))

    def test_statikk_shiv_stamps_its_triggering_swing(self) -> None:
        """The energized proc's event rides the first qualifying auto."""
        result = self._timed_fight([{"name": "Statikk Shiv"}])

        row = result["breakdown"]["on_hit_once_Statikk Shiv"]
        events = row["damage_events"]
        assert [event["time"] for event in events] == [0.0]
        assert sum(event["damage"] for event in events) == pytest.approx(
            row["total_damage"]
        )
        assert (
            "on_hit_once_Statikk Shiv" in result["timeline_coverage"]["exact_sources"]
        )

    def test_statikk_shiv_recharges_from_its_authored_attack_gain(self) -> None:
        """The parser-sourced 15-stack attack branch repeats every seven swings."""
        result = self._timed_fight([{"name": "Statikk Shiv"}], duration=20.0)

        row = result["breakdown"]["on_hit_once_Statikk Shiv"]
        events = row["damage_events"]
        assert [event["time"] for event in events] == [0.0, 7.0, 14.0]
        assert row["count"] == 3
        assert sum(event["damage"] for event in events) == pytest.approx(
            row["total_damage"]
        )

    def test_item_damage_receipts_are_classified_by_timeline_coverage(self) -> None:
        """Every timestamped item packet has exact or explicitly coarse provenance."""
        result = self._timed_fight(
            [
                {"name": "Statikk Shiv"},
                {"name": "Titanic Hydra"},
                {"name": "Sheen"},
            ],
            duration=3.0,
        )
        coverage = result["timeline_coverage"]
        classified = set(coverage["exact_sources"]) | set(coverage["coarse_sources"])
        for source_key, row in result["breakdown"].items():
            if row.get("damage_events"):
                assert source_key in classified, source_key

    def test_titanic_crescent_stamps_cooldown_gated_swings(self) -> None:
        """Titanic's empowered Cleave rides the first swing off cooldown."""
        result = self._timed_fight([{"name": "Titanic Hydra"}], duration=12.0)

        row = result["breakdown"]["active_Titanic Hydra"]
        events = row["damage_events"]
        assert [event["time"] for event in events] == [0.0, 10.0]
        assert sum(event["damage"] for event in events) == pytest.approx(
            row["total_damage"]
        )
        assert "active_Titanic Hydra" in result["timeline_coverage"]["exact_sources"]

    def test_stormsurge_stamps_the_burst_threshold_crossing(self, ahri_data) -> None:
        """Squall's event lands when the rolling burst window first fills."""
        fight = self._ahri_fight(ahri_data, ["Stormsurge"])

        row = fight["breakdown"]["proc_Stormsurge"]
        events = row["damage_events"]
        assert len(events) == 1
        assert sum(event["damage"] for event in events) == pytest.approx(
            row["total_damage"]
        )
        assert "proc_Stormsurge" in fight["timeline_coverage"]["exact_sources"]

        # The stamp is the ledger moment the rolling window held the
        # item's threshold share of the target's max health.
        effect = resolve_damage_effects(_build("Stormsurge")).cooldown_procs[0]
        proc_time = events[0]["time"]
        window = [
            event
            for event in fight["damage_events"]
            if event["source_key"] != "proc_Stormsurge"
            and proc_time - effect.damage_threshold_window - 1e-9
            <= event["time"]
            <= proc_time + 1e-9
        ]
        assert sum(event["damage"] for event in window) >= (
            effect.damage_threshold_ratio * 3000.0 - 1e-6
        )

    def test_stormsurge_stays_coarse_when_threshold_unreachable(
        self, ahri_data
    ) -> None:
        """An unreachable threshold means Squall never fires."""
        fight = self._ahri_fight(ahri_data, ["Stormsurge"], target_health=10_000_000.0)

        assert "proc_Stormsurge" not in fight["breakdown"]
        assert "proc_Stormsurge" not in fight["timeline_coverage"]["coarse_sources"]

    def test_malignance_hatefog_stamps_the_ult_cast_time(self, ahri_data) -> None:
        """Hatefog's event starts where the cast timeline puts R1."""
        fight = self._ahri_fight(ahri_data, ["Malignance"])

        r_times = [
            event["time"] for event in fight["cast_timeline"] if event["slot"] == "R"
        ]
        row = fight["breakdown"]["ult_proc_Malignance"]
        events = row["damage_events"]
        assert [event["time"] for event in events] == [min(r_times)]
        assert sum(event["damage"] for event in events) == pytest.approx(
            row["total_damage"]
        )
        assert "ult_proc_Malignance" in fight["timeline_coverage"]["exact_sources"]

    def test_spellblade_stamps_weave_timed_events(self, ahri_data) -> None:
        """Each spellblade proc lands one weave delay after its cast."""
        fight = self._ahri_fight(
            ahri_data,
            ["Bloodsong"],
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
        )

        row = fight["breakdown"]["spellblade_Bloodsong"]
        events = row["damage_events"]
        assert len(events) == row["count"] == 2
        effect = resolve_damage_effects(_build("Bloodsong")).spellblade
        first_cast = min(event["time"] for event in fight["cast_timeline"])
        assert events[0]["time"] == pytest.approx(first_cast + effect.weave_delay)
        assert events[1]["time"] >= events[0]["time"] + effect.cooldown
        assert sum(event["damage"] for event in events) == pytest.approx(
            row["total_damage"]
        )
        assert "spellblade_Bloodsong" in fight["timeline_coverage"]["exact_sources"]

    def test_lich_bane_empowered_speed_adjusts_authored_swing_schedule(
        self, ahri_data
    ) -> None:
        """Lich Bane's sourced speed shortens the post-proc swing interval."""
        without_item = self._ahri_fight(
            ahri_data,
            [],
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
        )
        with_lich_bane = self._ahri_fight(
            ahri_data,
            ["Lich Bane"],
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
        )

        baseline = [
            event["time"]
            for event in without_item["breakdown"]["auto_attacks"]["damage_events"]
        ]
        adjusted = [
            event["time"]
            for event in with_lich_bane["breakdown"]["auto_attacks"]["damage_events"]
        ]
        assert adjusted[:3] == pytest.approx(baseline[:3])
        assert adjusted[3] < baseline[3]
        assert "auto_attacks" in with_lich_bane["timeline_coverage"]["exact_sources"]

    def test_spellblade_bonus_true_rider_shares_proc_times(self, corki_data) -> None:
        """Corki's Hextech Munitions rider stamps the same weave times."""
        fight = self._ahri_fight(
            corki_data,
            ["Trinity Force"],
            auto_attack_uptime=1.0,
        )

        plain = fight["breakdown"]["spellblade_Trinity Force"]
        rider = fight["breakdown"]["spellblade_Trinity Force_bonus_true"]
        assert [event["time"] for event in rider["damage_events"]] == [
            event["time"] for event in plain["damage_events"]
        ]
        assert sum(
            event["damage"] for event in plain["damage_events"]
        ) == pytest.approx(plain["total_damage"])
        assert sum(
            event["damage"] for event in rider["damage_events"]
        ) == pytest.approx(rider["total_damage"])
        exact = fight["timeline_coverage"]["exact_sources"]
        assert "spellblade_Trinity Force" in exact
        assert "spellblade_Trinity Force_bonus_true" in exact

    def test_item_active_stamps_the_rotation_position(self, ahri_data) -> None:
        """An item active stamps the engine's after-the-rotation assumption."""
        fight = self._ahri_fight(ahri_data, ["Stridebreaker"])

        row = fight["breakdown"]["active_Stridebreaker"]
        events = row["damage_events"]
        last_cast = max(event["time"] for event in fight["cast_timeline"])
        assert [event["time"] for event in events] == [pytest.approx(last_cast)]
        assert sum(event["damage"] for event in events) == pytest.approx(
            row["total_damage"]
        )
        assert "active_Stridebreaker" in fight["timeline_coverage"]["exact_sources"]

    def test_item_active_without_casts_stamps_fight_start(self) -> None:
        """With no ability casts the active is assumed used at time zero."""
        result = self._timed_fight([{"name": "Stridebreaker"}])

        row = result["breakdown"]["active_Stridebreaker"]
        events = row["damage_events"]
        assert [event["time"] for event in events] == [0.0]
        assert sum(event["damage"] for event in events) == pytest.approx(
            row["total_damage"]
        )
        assert "active_Stridebreaker" in result["timeline_coverage"]["exact_sources"]

    @pytest.mark.parametrize("item_name", ["Profane Hydra", "Ravenous Hydra"])
    def test_ad_cleave_active_allocates_secondary_roster_packet(
        self, item_name: str
    ) -> None:
        """Hydra Crescent actives replay their typed secondary packet."""
        result = self._timed_fight(
            [{"name": item_name}],
            roster_target_index=1,
            roster_target_count=2,
        )

        row = result["breakdown"][f"secondary_{item_name}"]
        assert row["total_damage"] > 0.0
        assert row["damage_events"] == [
            {
                "time": 0.0,
                "damage": row["total_damage"],
                "damage_type": "physical",
            }
        ]
        assert row["targeting"]["kind"] == "active_secondary"
        assert row["targeting"]["allocated_target_index"] == 1


class TestRecurveBowSting(_FightHarness):
    """Recurve Bow's Sting: 15 bonus physical damage on-hit."""

    def test_parsed_values_match_expected(self) -> None:
        """Parser extracts the flat physical on-hit from cached JSON."""
        from src.calculator.passive_parser import parse_item_effect
        from src.calculator.data_fetcher import fetch_item_data

        parsed = parse_item_effect("Recurve Bow", fetch_item_data())
        assert parsed is not None
        assert parsed["base"] == 15.0
        assert parsed["damage_type"] == "physical"

    def test_sting_rides_every_swing_with_armor_mitigation(self) -> None:
        """Five swings vs 100 armor: 15 x 0.5 x 5 = 37.5 physical."""
        result = self.fight(
            self._make_stats(),
            one_rotation=False,
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
            target_health=3000.0,
            target_armor=100.0,
            target_magic_resistance=0.0,
            items=[{"name": "Recurve Bow"}],
        )

        row = result["breakdown"]["on_hit_Recurve Bow"]
        assert row["damage_type"] == "physical"
        assert row["total_damage"] == pytest.approx(37.5)
        events = row["damage_events"]
        assert [event["time"] for event in events] == [0.0, 1.0, 2.0, 3.0, 4.0]
        assert sum(event["damage"] for event in events) == pytest.approx(
            row["total_damage"]
        )
        assert "on_hit_Recurve Bow" in result["timeline_coverage"]["exact_sources"]

    def test_sting_stacks_with_other_named_on_hits(self) -> None:
        """Sting and Wit's End Fray are distinct passives and both apply."""
        result = self.fight(
            self._make_stats(),
            one_rotation=False,
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
            target_health=3000.0,
            target_armor=0.0,
            target_magic_resistance=0.0,
            items=[{"name": "Recurve Bow"}, {"name": "Wit's End"}],
        )

        assert result["breakdown"]["on_hit_Recurve Bow"]["total_damage"] == (
            pytest.approx(75.0)
        )
        assert result["breakdown"]["on_hit_Wit's End"]["total_damage"] == (
            pytest.approx(225.0)
        )


class TestSheenSpellblade:
    """Sheen's Spellblade: 100% base AD physical on the post-cast attack."""

    def test_registered_with_trinity_scheduling_values(self) -> None:
        """Sheen carries the line's 1.5s cooldown that starts post-attack."""
        from src.calculator.item_effects import ITEM_EFFECTS

        effect = ITEM_EFFECTS.get("Sheen")
        assert effect is not None
        assert effect["type"] == "spellblade"
        assert effect["base_ad_ratio"] == 1.0
        assert effect["damage_type"] == "physical"
        assert effect["cooldown"] == 1.5
        assert effect["weave_delay"] == 1.5

    def test_spellblade_damage_equals_base_ad(self) -> None:
        """Sheen's proc is exactly 100% base AD with no AP scaling."""
        stats = {"base_attack_damage": 104.0, "ability_power": 300.0}
        effect = resolve_damage_effects(_build("Sheen")).spellblade
        assert effect is not None
        damage = effect.source.raw_damage(DamageInputs(stats, 18, False, 1000, 1000))
        assert damage == pytest.approx(104.0)

    def test_two_procs_in_five_second_ahri_fight(self, ahri_data: dict) -> None:
        """Sheen weaves twice in 5 seconds, like the rest of the line."""
        from src.calculator.stats import calculate_total_stats
        from src.calculator.data_fetcher import get_item_by_name

        items = [get_item_by_name("Sheen")]
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
                auto_attack_uptime=1.0,
                one_rotation=False,
            ),
        )
        sb = fight["breakdown"]["spellblade_Sheen"]
        assert sb["count"] == 2
        assert sb["damage_type"] == "physical"


class TestHauntingGuiseMadness(_FightHarness):
    """Haunting Guise's Madness: 2%/s in-combat amp, capped at 6%."""

    def test_parsed_values_match_expected(self) -> None:
        """Parser extracts the per-second ramp and its cap from cached JSON."""
        from src.calculator.passive_parser import parse_item_effect
        from src.calculator.data_fetcher import fetch_item_data

        parsed = parse_item_effect("Haunting Guise", fetch_item_data())
        assert parsed is not None
        assert parsed["amp_per_second"] == pytest.approx(0.02)
        assert parsed["amp_max"] == pytest.approx(0.06)

    def test_amp_fraction_uses_the_riftmaker_ramp_model(self) -> None:
        """Average ramp: half the per-second rate over the capped window."""
        effects = resolve_damage_effects(_build("Haunting Guise"))
        amp = {e.item_name: e for e in effects.damage_amplifiers}["Haunting Guise"]
        assert amp.amp_fraction(2.0, 0.0) == pytest.approx(0.02)
        # 6% cap is reached after 3 seconds; longer fights keep that average.
        assert amp.amp_fraction(5.0, 0.0) == pytest.approx(0.03)

    def test_fight_total_is_amplified_with_a_breakdown_row(self) -> None:
        """A 5s auto fight gains the 3% averaged Madness multiplier."""
        result = self.fight(
            self._make_stats(),
            one_rotation=False,
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
            target_health=3000.0,
            target_armor=0.0,
            target_magic_resistance=0.0,
            items=[{"name": "Haunting Guise"}],
        )

        row = result["breakdown"]["damage_amp_Haunting Guise"]
        assert row["multiplier"] == pytest.approx(1.03)
        assert row["total_damage"] > 0


class TestRiftmakerVoidCorruption(_FightHarness):
    """Riftmaker's max-stack omnivamp follows its four-second ramp."""

    def test_parsed_max_stack_omnivamp(self) -> None:
        from src.calculator.data_fetcher import fetch_item_data
        from src.calculator.passive_parser import parse_item_effect

        parsed = parse_item_effect("Riftmaker", fetch_item_data())
        assert parsed is not None
        assert parsed["max_stack_omnivamp"] == pytest.approx(10.0)

    def test_max_stack_omnivamp_is_added_to_ordered_attack_healing(self) -> None:
        result = self.fight(
            self._make_stats(),
            one_rotation=False,
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
            target_health=3000.0,
            target_armor=0.0,
            target_magic_resistance=0.0,
            items=[{"name": "Riftmaker"}],
        )

        assert result["breakdown"]["heal_omnivamp"]["total_amount"] == pytest.approx(
            50.0
        )

    def test_short_riftmaker_fight_has_no_max_stack_omnivamp(self) -> None:
        result = self.fight(
            self._make_stats(),
            one_rotation=False,
            fight_duration_seconds=3.0,
            auto_attack_uptime=1.0,
            target_health=3000.0,
            target_armor=0.0,
            target_magic_resistance=0.0,
            items=[{"name": "Riftmaker"}],
        )

        assert "heal_omnivamp" not in result["breakdown"]


class TestBamisCinderImmolate(_FightHarness):
    """Bami's Cinder's Immolate: flat 15 magic damage per second aura."""

    def test_parsed_values_match_expected(self) -> None:
        """Parser extracts the flat DPS; no bonus-health scaling exists."""
        from src.calculator.passive_parser import parse_item_effect
        from src.calculator.data_fetcher import fetch_item_data

        parsed = parse_item_effect("Bami's Cinder", fetch_item_data())
        assert parsed is not None
        assert parsed["base_per_second"] == 15.0
        assert parsed["damage_type"] == "magic"
        assert "bonus_hp_ratio_per_second" not in parsed

    def test_flat_dps_ignores_bonus_health(self) -> None:
        """The V14.19 flat Immolate must not scale with bonus health."""
        effects = resolve_damage_effects(_build("Bami's Cinder"))
        source = effects.immolates[0]
        inputs = DamageInputs(
            champion_stats={"bonus_health": 2000.0},
            level=11,
            is_melee=True,
            target_max_health=1000.0,
            target_current_health=1000.0,
        )
        assert source.raw_damage(inputs) == pytest.approx(15.0)

    def test_fight_prices_dps_times_duration_with_mr_mitigation(self) -> None:
        """5s vs 100 MR: 15 x 5 x 0.5 = 37.5 magic damage."""
        result = self.fight(
            self._make_stats(),
            one_rotation=False,
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
            target_health=3000.0,
            target_armor=0.0,
            target_magic_resistance=100.0,
            items=[{"name": "Bami's Cinder"}],
        )

        row = result["breakdown"]["immolate_Bami's Cinder"]
        assert row["damage_type"] == "magic"
        assert row["total_damage"] == pytest.approx(37.5)
        assert [event["time"] for event in row["damage_events"]] == [
            1.0,
            2.0,
            3.0,
            4.0,
            5.0,
        ]
        assert sum(event["damage"] for event in row["damage_events"]) == pytest.approx(
            row["total_damage"]
        )
        assert "immolate_Bami's Cinder" in result["timeline_coverage"]["exact_sources"]


class TestFatedAshesInflame(_FightHarness):
    """Fated Ashes' Inflame: 15 flat magic burn over 3s from ability damage."""

    _Q = {
        "name": "Test Q",
        "parts": (DamagePart("magic", 200.0),),
        "total_raw": 200.0,
        "damage_type": "magic",
        "cooldown": 6.0,
    }

    def test_parsed_values_match_expected(self) -> None:
        """Parser extracts the flat burn total; there is no AP scaling."""
        from src.calculator.passive_parser import parse_item_effect
        from src.calculator.data_fetcher import fetch_item_data

        parsed = parse_item_effect("Fated Ashes", fetch_item_data())
        assert parsed is not None
        assert parsed["base_total"] == 15.0
        assert parsed["duration"] == 3.0
        assert parsed["damage_type"] == "magic"
        assert "ap_ratio_total" not in parsed

    def test_flat_burn_ignores_ability_power(self) -> None:
        """Inflame's total is 15 whether the caster has 0 or 500 AP."""
        (burn,) = resolve_damage_effects(_build("Fated Ashes")).burns
        assert burn.duration == pytest.approx(3.0)
        assert burn.tick_interval == pytest.approx(0.5)
        for ability_power in (0.0, 500.0):
            raw = burn.source.raw_damage(
                DamageInputs(
                    {"ability_power": ability_power}, 11, False, 1000.0, 1000.0
                )
            )
            assert raw == pytest.approx(15.0)

    def test_single_cast_burn_prices_base_duration_with_mitigation(self) -> None:
        """One Q, one rotation, 100 MR: the burn is 15 x 0.5 = 7.5 magic."""
        result = self.fight(
            self._make_stats(ability_power=100.0),
            {"Q": dict(self._Q)},
            target_magic_resistance=100.0,
            cast_order=["Q"],
            items=[{"name": "Fated Ashes"}],
        )

        row = result["breakdown"]["burn_Fated Ashes"]
        assert row["damage_type"] == "magic"
        assert row["total_damage"] == pytest.approx(7.5)
        assert sum(event["damage"] for event in row["damage_events"]) == pytest.approx(
            row["total_damage"]
        )
        assert "burn_Fated Ashes" in result["timeline_coverage"]["exact_sources"]


class TestTiamatCrescent(_FightHarness):
    """Tiamat's Crescent active: 75% AD physical on a 10s cooldown."""

    def test_parsed_values_match_expected(self) -> None:
        """Parser extracts the active's AD ratio from cached JSON."""
        from src.calculator.passive_parser import parse_item_effect
        from src.calculator.data_fetcher import fetch_item_data

        parsed = parse_item_effect("Tiamat", fetch_item_data())
        assert parsed is not None
        assert parsed["total_ad_ratio"] == pytest.approx(0.75)
        assert parsed["damage_type"] == "physical"

    def test_registered_with_the_hydra_static_cooldown(self) -> None:
        """The 10s cooldown is code-owned, like the finished Hydras'."""
        from src.calculator.item_effects import ITEM_EFFECTS

        effect = ITEM_EFFECTS.get("Tiamat")
        assert effect is not None
        assert effect["type"] == "active"
        assert effect["cooldown"] == 10.0

    def test_active_deals_three_quarters_total_ad_once(self) -> None:
        """100 total AD vs 100 armor: one Crescent = 75 x 0.5 = 37.5."""
        result = self.fight(
            self._make_stats(),
            one_rotation=False,
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
            target_health=3000.0,
            target_armor=100.0,
            target_magic_resistance=0.0,
            items=[{"name": "Tiamat"}],
        )

        row = result["breakdown"]["active_Tiamat"]
        assert row["damage_type"] == "physical"
        assert row["total_damage"] == pytest.approx(37.5)
        assert "active_Tiamat" in result["timeline_coverage"]["exact_sources"]

    def test_cleave_is_disclosed_as_multi_target_scope(self) -> None:
        """Cleave hits other enemies only; the fight notes must say so."""
        result = self.fight(
            self._make_stats(),
            one_rotation=False,
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
            target_health=3000.0,
            items=[{"name": "Tiamat"}],
        )

        assert any(
            "Cleave" in note and "other enemies" in note
            for note in result.get("notes", [])
        )


class TestHextechAlternatorRevved(_FightHarness):
    """Hextech Alternator's Revved: 65 magic on champion damage, 40s CD."""

    def test_parsed_values_match_expected(self) -> None:
        """Parser extracts the flat proc and the cooldown field."""
        from src.calculator.passive_parser import parse_item_effect
        from src.calculator.data_fetcher import fetch_item_data

        parsed = parse_item_effect("Hextech Alternator", fetch_item_data())
        assert parsed is not None
        assert parsed["base"] == 65.0
        assert parsed["damage_type"] == "magic"
        assert parsed["cooldown"] == 40.0

    def test_compiles_as_champion_damage_proc_without_ap_scaling(self) -> None:
        """Revved is a flat 65 whether the holder has 0 or 500 AP."""
        (proc,) = resolve_damage_effects(_build("Hextech Alternator")).cooldown_procs
        assert proc.trigger == "champion_damage"
        assert proc.cooldown == pytest.approx(40.0)
        for ability_power in (0.0, 500.0):
            raw = proc.source.raw_damage(
                DamageInputs(
                    {"ability_power": ability_power}, 11, False, 1000.0, 1000.0
                )
            )
            assert raw == pytest.approx(65.0)

    def test_short_fight_procs_once_at_the_first_damage_event(self) -> None:
        """A 5s fight yields one proc, stamped when damage first lands."""
        result = self.fight(
            self._make_stats(),
            one_rotation=False,
            fight_duration_seconds=5.0,
            auto_attack_uptime=1.0,
            target_health=3000.0,
            target_armor=0.0,
            target_magic_resistance=100.0,
            items=[{"name": "Hextech Alternator"}],
        )

        row = result["breakdown"]["proc_Hextech Alternator"]
        assert row["damage_type"] == "magic"
        assert row["total_damage"] == pytest.approx(32.5)  # 65 vs 100 MR
        events = row["damage_events"]
        assert [event["time"] for event in events] == [0.0]
        assert "proc_Hextech Alternator" in result["timeline_coverage"]["exact_sources"]

    def test_long_fight_repeats_after_the_forty_second_cooldown(self) -> None:
        """A 45s fight fits a second proc once the cooldown elapses."""
        result = self.fight(
            self._make_stats(),
            one_rotation=False,
            fight_duration_seconds=45.0,
            auto_attack_uptime=1.0,
            target_health=100000.0,
            target_armor=0.0,
            target_magic_resistance=0.0,
            items=[{"name": "Hextech Alternator"}],
        )

        row = result["breakdown"]["proc_Hextech Alternator"]
        events = row["damage_events"]
        assert len(events) == 2
        assert events[0]["time"] == 0.0
        assert events[1]["time"] == pytest.approx(40.0)
        assert row["total_damage"] == pytest.approx(130.0)

    def test_no_damage_means_no_proc(self) -> None:
        """With nothing landing, Revved has no trigger and no row."""
        result = self.fight(
            self._make_stats(),
            one_rotation=False,
            fight_duration_seconds=5.0,
            auto_attack_uptime=0.0,
            items=[{"name": "Hextech Alternator"}],
        )

        assert "proc_Hextech Alternator" not in result["breakdown"]


class TestScoutsSlingshotBullseye(_FightHarness):
    """Scout's Slingshot's Bullseye: 40 magic on champion damage, 40s CD
    refunded 1s per completed attack."""

    def test_parsed_values_match_expected(self) -> None:
        """Parser extracts the proc, its cooldown, and the attack refund."""
        from src.calculator.passive_parser import parse_item_effect
        from src.calculator.data_fetcher import fetch_item_data

        parsed = parse_item_effect("Scout's Slingshot", fetch_item_data())
        assert parsed is not None
        assert parsed["base"] == 40.0
        assert parsed["damage_type"] == "magic"
        assert parsed["cooldown"] == 40.0
        assert parsed["on_attack_cooldown_refund"] == 1.0

    def test_compiles_with_spell_damage_and_refund(self) -> None:
        """Bullseye is spell damage (unlike Revved) and carries its refund."""
        (proc,) = resolve_damage_effects(_build("Scout's Slingshot")).cooldown_procs
        assert proc.trigger == "champion_damage"
        assert proc.cooldown == pytest.approx(40.0)
        assert proc.on_attack_cooldown_refund == pytest.approx(1.0)
        assert proc.source.is_ability_damage is True

    def test_missing_refund_value_fails_loudly(self) -> None:
        """A parse miss on the refund must raise, not default to no refund."""
        from src.calculator import item_effects

        broken = dict(item_effects.ITEM_EFFECTS["Scout's Slingshot"])
        broken.pop("on_attack_cooldown_refund", None)
        with pytest.MonkeyPatch.context() as patcher:
            patcher.setitem(item_effects.ITEM_EFFECTS, "Scout's Slingshot", broken)
            with pytest.raises(KeyError) as exc_info:
                resolve_damage_effects(_build("Scout's Slingshot"))
        message = exc_info.value.args[0]
        assert "Scout's Slingshot" in message
        assert "on_attack_cooldown_refund" in message

    def test_attack_refunds_halve_the_effective_cooldown(self) -> None:
        """At 1.0 attacks/s each second refunds one extra second: procs
        land at 0s, 20s, and 40s of a 45-second fight."""
        result = self.fight(
            self._make_stats(),
            one_rotation=False,
            fight_duration_seconds=45.0,
            auto_attack_uptime=1.0,
            target_health=100000.0,
            target_armor=0.0,
            target_magic_resistance=0.0,
            items=[{"name": "Scout's Slingshot"}],
        )

        row = result["breakdown"]["proc_Scout's Slingshot"]
        events = row["damage_events"]
        assert [event["time"] for event in events] == [0.0, 20.0, 40.0]
        assert row["total_damage"] == pytest.approx(120.0)
        assert "proc_Scout's Slingshot" in result["timeline_coverage"]["exact_sources"]
