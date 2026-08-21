"""Tests for keystone rune resolution and every compiled keystone's formula.

Every number a compiler produces is asserted against the value read live
out of ``rune_effects.RUNE_EFFECTS`` (parsed from ``data/runes.json``),
never against a number typed here, and every required key is deleted in
turn to prove the compiler raises instead of falling back — CLAUDE.md rule
5 for runes, as evidence rather than as a claim.
"""

import pytest

from src.calculator import rune_effects
from src.calculator.ability_spec import Disposition
from src.calculator.item_effects import DamageInputs


def _inputs(level=1, bonus_ad=0.0, ap=0.0, is_melee=False, **stats):
    return DamageInputs(
        champion_stats={
            "bonus_attack_damage": bonus_ad,
            "ability_power": ap,
            **stats,
        },
        level=level,
        is_melee=is_melee,
        target_max_health=1000.0,
        target_current_health=1000.0,
    )


def _cached(name):
    """The rune's cached ``effects`` block — the test's only source of numbers."""
    return rune_effects.RUNE_EFFECTS[name]["effects"]


def _without(name, key):
    """The whole registry with one key dropped from one rune's effects."""
    return {
        rune: (
            {
                **entry,
                "effects": {k: v for k, v in entry["effects"].items() if k != key},
            }
            if rune == name
            else entry
        )
        for rune, entry in rune_effects.RUNE_EFFECTS.items()
    }


class TestResolveKeystone:
    def test_empty_selection_resolves_to_none(self):
        assert rune_effects.resolve_rune("") is None

    def test_unknown_keystone_raises(self):
        with pytest.raises(ValueError, match="Fake Rune"):
            rune_effects.resolve_rune("Fake Rune")

    def test_every_cached_keystone_has_a_compiler(self):
        keystones = {
            name
            for name, entry in rune_effects.RUNE_EFFECTS.items()
            if entry.get("row") == 0
        }
        assert set(rune_effects._KEYSTONE_COMPILERS) == keystones

    def test_a_keystone_with_no_compiler_still_fails_closed(self, monkeypatch):
        """The withhold survives its own population emptying.

        All 17 cached keystones compile, so the fail-closed path is proven
        on a synthetic rune instead of being deleted with its last user.
        """
        monkeypatch.setitem(
            rune_effects.RUNE_EFFECTS, "Synthetic Keystone", {"name": "Synthetic"}
        )
        with pytest.raises(ValueError, match="not modeled"):
            rune_effects.resolve_rune("Synthetic Keystone")

    def test_fleet_footwork_resolves_charge_heal_and_speed(self):
        effect = rune_effects.resolve_keystone("Fleet Footwork")
        assert isinstance(effect, rune_effects.KeystoneFleetEffect)
        assert effect.charge_cap == pytest.approx(100.0)
        assert effect.move_speed_duration_seconds == pytest.approx(1.0)
        assert effect.bonus_move_speed_percent(True) == pytest.approx(20.0)
        assert effect.bonus_move_speed_percent(False) == pytest.approx(15.0)
        stats = {"bonus_attack_damage": 100.0, "ability_power": 50.0}
        assert effect.heal_amount(18, stats, False) == pytest.approx(103.5)
        assert effect.heal_amount(
            18, stats, False, against_minion=True
        ) == pytest.approx(15.525)

    def test_conqueror_resolves_force_stack_timing_and_healing(self):
        effect = rune_effects.resolve_keystone("Conqueror")
        assert isinstance(effect, rune_effects.KeystoneConquerorEffect)
        assert effect.max_stacks == 12
        assert effect.stacks_per_application == 2
        assert effect.stack_duration_seconds == pytest.approx(5.0)
        assert effect.cast_instance_interval_seconds == pytest.approx(4.0)
        assert effect.adaptive_force_at(18, 12) == pytest.approx(48.0)
        assert effect.max_adaptive_force_at(18) == pytest.approx(48.0)
        assert effect.bonus_attack_damage_at(18, 12) == pytest.approx(28.8)
        assert effect.ability_power_at(18, 12) == pytest.approx(48.0)
        assert effect.heal_amount(100.0, True) == pytest.approx(8.0)
        assert effect.heal_amount(100.0, False) == pytest.approx(5.0)

    def test_deathfire_resolves_burn_states_and_tick_formula(self):
        effect = rune_effects.resolve_keystone("Deathfire Touch")
        assert isinstance(effect, rune_effects.KeystoneDeathfireEffect)
        assert effect.duration_for("spell_damage") == pytest.approx(4.0)
        assert effect.duration_for("area_damage") == pytest.approx(2.0)
        assert effect.duration_for("persistent_damage") == pytest.approx(1.0)
        assert effect.duration_for("persistent_area_damage") == pytest.approx(1.0)
        assert effect.duration_for("pet_damage") == pytest.approx(1.0)
        stats = {"bonus_attack_damage": 100.0, "ability_power": 100.0}
        assert effect.raw_tick(18, stats) == pytest.approx(10.75)
        assert effect.raw_tick(18, stats, amplified=True) == pytest.approx(18.8125)
        assert effect.amp_ratio == pytest.approx(0.75)

    def test_electrocute_resolves(self):
        effect = rune_effects.resolve_rune("Electrocute")
        assert effect.rune_name == "Electrocute"
        assert effect.stacks_required == 3
        assert effect.stack_window_seconds == 3.0
        assert effect.cooldown_seconds == 20.0
        assert effect.proc_delay_seconds == 0.25

    def test_summon_aery_resolves_with_separate_flight_receipts(self):
        effect = rune_effects.resolve_keystone("Summon Aery")
        assert isinstance(effect, rune_effects.KeystoneAeryEffect)
        assert effect.damage_flight_seconds == pytest.approx(0.45)
        assert effect.shield_flight_seconds == pytest.approx(0.35)
        assert effect.shield_duration_seconds == pytest.approx(2.0)
        assert effect.linger_seconds == pytest.approx(2.0)

    def test_guardian_resolves_threshold_cooldown_and_shield_formula(self):
        effect = rune_effects.resolve_keystone("Guardian")
        assert isinstance(effect, rune_effects.KeystoneGuardianEffect)
        assert effect.threshold_at(1) == pytest.approx(50.0)
        assert effect.threshold_at(18) == pytest.approx(165.0)
        assert effect.cooldown_at(1) == pytest.approx(75.0)
        assert effect.cooldown_at(18) == pytest.approx(40.0)
        assert effect.trigger_window_seconds == pytest.approx(2.5)
        assert effect.shield_duration_seconds == pytest.approx(2.0)
        assert effect.shield_amount(
            18, {"ability_power": 100.0, "bonus_health": 500.0}
        ) == pytest.approx(150.0 + 20.0 + 30.0)

    def test_aftershock_resolves_capped_resistance_and_shockwave(self):
        effect = rune_effects.resolve_keystone("Aftershock")
        assert isinstance(effect, rune_effects.KeystoneAftershockEffect)
        assert effect.cooldown_seconds == pytest.approx(20.0)
        assert effect.duration_seconds == pytest.approx(2.5)
        assert effect.shockwave_radius == pytest.approx(350.0)
        stats = {"bonus_armor": 100.0, "bonus_magic_resistance": 20.0}
        assert effect.resistance_bonus(18, stats, "armor") == pytest.approx(120.0)
        assert effect.resistance_bonus(18, stats, "magic_resistance") == pytest.approx(
            60.0
        )
        assert effect.resistance_bonus(
            18, {"bonus_armor": 300.0}, "armor"
        ) == pytest.approx(150.0)
        assert effect.shockwave_raw_damage(
            18, {"bonus_health": 500.0}
        ) == pytest.approx(160.0)

    def test_glacial_resolves_zone_slow_and_source_filter_values(self):
        effect = rune_effects.resolve_keystone("Glacial Augment")
        assert isinstance(effect, rune_effects.KeystoneGlacialEffect)
        assert effect.cooldown_seconds == pytest.approx(25.0)
        assert effect.ray_count == 3
        assert effect.zone_radius_units == pytest.approx(700.0)
        assert effect.zone_width_units == pytest.approx(80.0)
        assert effect.zone_duration(2.0) == pytest.approx(5.0)
        assert effect.slow_ratio(
            {
                "bonus_attack_damage": 100.0,
                "ability_power": 200.0,
                "heal_and_shield_power_percent": 20.0,
            }
        ) == pytest.approx(0.20 + 0.07 + 0.12 + 0.18)
        assert effect.damage_reduction_ratio == pytest.approx(0.15)

    def test_stormraider_resolves_damage_window_and_movement_burst(self):
        effect = rune_effects.resolve_keystone("Stormraider's Surge")
        assert isinstance(effect, rune_effects.KeystoneStormraiderEffect)
        assert effect.cooldown_at(1) == pytest.approx(20.0)
        assert effect.cooldown_at(18) == pytest.approx(10.0)
        assert effect.damage_threshold_ratio == pytest.approx(0.25)
        assert effect.damage_window_seconds == pytest.approx(3.0)
        assert effect.duration_seconds == pytest.approx(4.0)
        assert effect.bonus_move_speed_percent(True) == pytest.approx(48.0)
        assert effect.bonus_move_speed_percent(False) == pytest.approx(36.0)
        assert effect.slow_resist_ratio == pytest.approx(0.50)

    def test_grasp_resolves_timed_stack_and_health_riders(self):
        effect = rune_effects.resolve_keystone("Grasp of the Undying")
        assert isinstance(effect, rune_effects.KeystoneGraspEffect)
        assert effect.stack_cadence_seconds == pytest.approx(1.0)
        assert effect.stack_generation_seconds == pytest.approx(3.0)
        assert effect.max_stacks == 4
        assert effect.ready_window_seconds == pytest.approx(5.0)
        stats = {"health": 2000.0}
        assert effect.raw_damage(stats, True) == pytest.approx(70.0)
        assert effect.raw_damage(stats, False) == pytest.approx(28.0)
        assert effect.heal_amount(stats, True) == pytest.approx(26.0)
        assert effect.bonus_health(False) == pytest.approx(2.0)

    def test_hail_of_blades_resolves_timed_attack_window_and_true_rider(self):
        effect = rune_effects.resolve_keystone("Hail of Blades")
        assert isinstance(effect, rune_effects.KeystoneHailOfBladesEffect)
        assert effect.initial_stacks == 2
        assert effect.stack_duration_seconds == pytest.approx(3.0)
        assert effect.reset_stack_limit == 2
        assert effect.cooldown_seconds == pytest.approx(10.0)
        assert effect.bonus_attack_speed_percent(True) == pytest.approx(90.0)
        assert effect.bonus_attack_speed_percent(False) == pytest.approx(60.0)
        assert effect.raw_damage(
            _inputs(level=18, bonus_ad=100.0, ap=50.0)
        ) == pytest.approx(20.0 + 12.0 + 5.0)

    def test_lethal_tempo_resolves_stack_speed_bolt_and_expiry_values(self):
        effect = rune_effects.resolve_keystone("Lethal Tempo")
        assert isinstance(effect, rune_effects.KeystoneLethalTempoEffect)
        assert effect.max_stacks == 6
        assert effect.stack_duration_seconds == pytest.approx(6.0)
        assert effect.expiry_step_seconds == pytest.approx(0.5)
        assert effect.attack_speed_percent(True, 6) == pytest.approx(36.0)
        assert effect.attack_speed_percent(False, 6) == pytest.approx(28.8)
        inputs = _inputs(level=18)
        inputs = DamageInputs(
            champion_stats={"bonus_attack_damage": 100.0, "bonus_attack_speed": 20.0},
            level=18,
            is_melee=True,
            target_max_health=1000.0,
            target_current_health=1000.0,
        )
        assert effect.bolt_raw_damage(inputs, True, 6) == pytest.approx(30.0 * 1.56)

    def test_dark_harvest_resolves_threshold_and_soul_formula(self):
        effect = rune_effects.resolve_keystone("Dark Harvest")
        assert isinstance(effect, rune_effects.KeystoneDarkHarvestEffect)
        assert effect.health_threshold_ratio == pytest.approx(0.50)
        assert effect.cooldown_seconds == pytest.approx(35.0)
        assert effect.proc_delay_seconds == pytest.approx(1.75)
        assert effect.takedown_reset_seconds == pytest.approx(1.0)
        assert effect.raw_damage(_inputs()) == pytest.approx(30.0)
        assert effect.raw_damage(_inputs(), souls=2) == pytest.approx(52.0)


class TestElectrocuteFormula:
    def test_base_damage_by_level(self):
        effect = rune_effects.resolve_rune("Electrocute")
        assert effect.raw_damage(_inputs(level=1)) == pytest.approx(70.0)
        assert effect.raw_damage(_inputs(level=11)) == pytest.approx(170.0)
        assert effect.raw_damage(_inputs(level=20)) == pytest.approx(260.0)

    def test_ratio_scaling(self):
        effect = rune_effects.resolve_rune("Electrocute")
        assert effect.raw_damage(_inputs(level=1, bonus_ad=100.0)) == pytest.approx(
            80.0
        )
        assert effect.raw_damage(_inputs(level=1, ap=200.0)) == pytest.approx(80.0)

    def test_adaptive_type_prefers_larger_contribution(self):
        effect = rune_effects.resolve_rune("Electrocute")
        physical = {"bonus_attack_damage": 100.0, "ability_power": 100.0}
        magic = {"bonus_attack_damage": 40.0, "ability_power": 100.0}
        assert effect.damage_type(physical) == "physical"  # 10 AD > 5 AP contribution
        assert effect.damage_type(magic) == "magic"  # 4 < 5

    def test_adaptive_type_defaults_to_magic_on_tie_or_zero(self):
        effect = rune_effects.resolve_rune("Electrocute")
        assert (
            effect.damage_type({"bonus_attack_damage": 0.0, "ability_power": 0.0})
            == "magic"
        )
        tie = {"bonus_attack_damage": 50.0, "ability_power": 100.0}  # 5 == 5
        assert effect.damage_type(tie) == "magic"

    def test_missing_registry_key_raises_with_context(self, monkeypatch):
        broken = {
            name: (
                {
                    **entry,
                    "effects": {
                        k: v for k, v in entry["effects"].items() if k != "ap_ratio"
                    },
                }
                if name == "Electrocute"
                else entry
            )
            for name, entry in rune_effects.RUNE_EFFECTS.items()
        }
        monkeypatch.setattr(rune_effects, "RUNE_EFFECTS", broken)
        with pytest.raises(KeyError, match="Electrocute.*ap_ratio"):
            rune_effects.resolve_rune("Electrocute")


class TestFirstStrike:
    def test_first_strike_resolves_to_window_amp_effect(self):
        effect = rune_effects.resolve_rune("First Strike")
        assert isinstance(effect, rune_effects.RuneWindowAmpEffect)
        assert effect.rune_name == "First Strike"
        assert effect.breakdown_key == "keystone_First Strike"
        assert effect.activation_gold == 10.0

    def test_the_window_and_the_ratio_live_in_the_declaration(self):
        """One number, one home: the amp chain slot owns both (3.2)."""
        from src.calculator.interpreters import (  # pylint: disable=import-outside-toplevel
            delta_amp,
        )
        from src.calculator.item_behavior import (  # pylint: disable=import-outside-toplevel
            AmpChainSlot,
        )

        slot = delta_amp.resolve_slot(
            ["First Strike"],
            AmpChainSlot.OPENING_WINDOW,
            level=18,
            fight_duration_seconds=10.0,
            target_bonus_health=0.0,
            holder_is_melee=True,
        )
        assert slot is not None
        assert slot.window() == (0.0, 3.0)
        assert slot.fractions[0] == pytest.approx(0.07)
        assert slot.uniform_bonus_damage_type() == "true"

    def test_gold_conversion_is_melee_ranged_split(self):
        effect = rune_effects.resolve_rune("First Strike")
        assert effect.gold_conversion(is_melee=True) == pytest.approx(0.50)
        assert effect.gold_conversion(is_melee=False) == pytest.approx(0.35)

    def test_missing_registry_key_raises_with_context(self, monkeypatch):
        broken = {
            name: (
                {
                    **entry,
                    "effects": {
                        k: v
                        for k, v in entry["effects"].items()
                        if k != "gold_conversion_ratios"
                    },
                }
                if name == "First Strike"
                else entry
            )
            for name, entry in rune_effects.RUNE_EFFECTS.items()
        }
        monkeypatch.setattr(rune_effects, "RUNE_EFFECTS", broken)
        with pytest.raises(KeyError, match="First Strike.*gold_conversion_ratios"):
            rune_effects.resolve_rune("First Strike")


class TestPressTheAttack:
    def test_press_the_attack_resolves_to_proc_amp_effect(self):
        effect = rune_effects.resolve_rune("Press the Attack")
        assert isinstance(effect, rune_effects.RuneProcAmpEffect)
        assert effect.rune_name == "Press the Attack"
        assert effect.breakdown_key == "keystone_Press the Attack"
        assert effect.amp_breakdown_key == "keystone_Press the Attack amp"
        assert effect.amp_display_name == "Press the Attack amp (keystone)"
        assert effect.stacks_required == 3
        assert effect.stack_duration_seconds == 4.0
        assert effect.cooldown_seconds == 6.0

    def test_the_lasting_amp_lives_in_the_declaration(self):
        """One number, one home: the amp chain slot owns the ratio (3.2)."""
        from src.calculator.interpreters import (  # pylint: disable=import-outside-toplevel
            delta_amp,
        )
        from src.calculator.item_behavior import (  # pylint: disable=import-outside-toplevel
            AmpChainSlot,
        )

        slot = delta_amp.resolve_slot(
            ["Press the Attack"],
            AmpChainSlot.LASTING_PROC_AMP,
            level=18,
            fight_duration_seconds=10.0,
            target_bonus_health=0.0,
            holder_is_melee=True,
        )
        assert slot is not None
        assert slot.fractions[0] == pytest.approx(0.08)
        # The triggering swing lands the instant the buff turns on, so it is
        # outside a strict after-trigger activation.
        assert not slot.applies_after(2.0, 2.0)
        assert slot.applies_after(2.5, 2.0)
        assert slot.prices_damage_type("magic")
        assert not slot.prices_damage_type("true")

    def test_proc_damage_by_level_has_no_ratio_scaling(self):
        effect = rune_effects.resolve_rune("Press the Attack")
        assert effect.raw_damage(_inputs(level=1)) == pytest.approx(40.0)
        assert effect.raw_damage(_inputs(level=18)) == pytest.approx(160.0)
        assert effect.raw_damage(_inputs(level=20)) == pytest.approx(174.117647)
        # The proc is pure leveled adaptive damage — stats must not move it.
        assert effect.raw_damage(
            _inputs(level=18, bonus_ad=300.0, ap=500.0)
        ) == pytest.approx(160.0)

    def test_adaptive_type_compares_bonus_ad_against_ap(self):
        effect = rune_effects.resolve_rune("Press the Attack")
        physical = {"bonus_attack_damage": 100.0, "ability_power": 50.0}
        magic = {"bonus_attack_damage": 50.0, "ability_power": 100.0}
        assert effect.damage_type(physical) == "physical"
        assert effect.damage_type(magic) == "magic"

    def test_adaptive_type_defaults_to_magic_on_tie_or_zero(self):
        # Ties follow the champion's adaptive type in game; the engine
        # carries no adaptive type, so it defaults magic like Electrocute.
        effect = rune_effects.resolve_rune("Press the Attack")
        assert (
            effect.damage_type({"bonus_attack_damage": 0.0, "ability_power": 0.0})
            == "magic"
        )

    def test_missing_registry_key_raises_with_context(self, monkeypatch):
        broken = {
            name: (
                {
                    **entry,
                    "effects": {
                        k: v
                        for k, v in entry["effects"].items()
                        if k != "stack_duration_seconds"
                    },
                }
                if name == "Press the Attack"
                else entry
            )
            for name, entry in rune_effects.RUNE_EFFECTS.items()
        }
        monkeypatch.setattr(rune_effects, "RUNE_EFFECTS", broken)
        with pytest.raises(KeyError, match="Press the Attack.*stack_duration_seconds"):
            rune_effects.resolve_rune("Press the Attack")

    def test_a_missing_amp_ratio_raises_through_the_reference(self, monkeypatch):
        """Rule 5 reaches keystones: the declaration's read fails loud too."""
        broken = {
            name: (
                {
                    **entry,
                    "effects": {
                        k: v
                        for k, v in entry["effects"].items()
                        if k != "damage_amp_ratio"
                    },
                }
                if name == "Press the Attack"
                else entry
            )
            for name, entry in rune_effects.RUNE_EFFECTS.items()
        }
        monkeypatch.setattr(rune_effects, "RUNE_EFFECTS", broken)
        from src.calculator.value_ref import (  # pylint: disable=import-outside-toplevel
            ValueRef,
        )

        with pytest.raises(KeyError, match="Press the Attack.*damage_amp_ratio"):
            ValueRef("RUNE_EFFECTS", "Press the Attack", "damage_amp_ratio").get()


class TestArcaneComet:
    def test_arcane_comet_resolves_to_ability_proc_effect(self):
        effect = rune_effects.resolve_rune("Arcane Comet")
        assert isinstance(effect, rune_effects.RuneAbilityProcEffect)
        assert effect.rune_name == "Arcane Comet"
        assert effect.breakdown_key == "keystone_Arcane Comet"
        assert effect.proc_delay_seconds == pytest.approx(0.8)
        assert effect.assumed_travel_distance == 375.0
        # 375 of the 750-unit span → halfway up the 0-100% damage table.
        assert effect.distance_amp_ratio == pytest.approx(0.5)

    def test_cooldown_scales_with_level(self):
        effect = rune_effects.resolve_rune("Arcane Comet")
        assert effect.cooldown_at(1) == pytest.approx(20.0)
        assert effect.cooldown_at(18) == pytest.approx(8.0)
        assert effect.cooldown_at(20) == pytest.approx(20 - 12 / 17 * 19)
        # Out-of-range levels clamp like the leveling arrays do.
        assert effect.cooldown_at(0) == pytest.approx(20.0)
        assert effect.cooldown_at(30) == pytest.approx(20 - 12 / 17 * 19)

    def test_damage_is_min_formula_amped_by_assumed_distance(self):
        effect = rune_effects.resolve_rune("Arcane Comet")
        # (15 base at level 1) × 1.5 distance amp
        assert effect.raw_damage(_inputs(level=1)) == pytest.approx(22.5)
        # (100 base at level 18) × 1.5
        assert effect.raw_damage(_inputs(level=18)) == pytest.approx(150.0)
        # (110 base at level 20) × 1.5 — meets the wiki's max-range 220
        # array exactly at the 100%-amp endpoint, halved at ours.
        assert effect.raw_damage(_inputs(level=20)) == pytest.approx(165.0)

    def test_ratios_are_amped_with_the_base(self):
        effect = rune_effects.resolve_rune("Arcane Comet")
        # (15 + 10% × 100 bonus AD) × 1.5
        assert effect.raw_damage(_inputs(level=1, bonus_ad=100.0)) == pytest.approx(
            37.5
        )
        # (15 + 5% × 200 AP) × 1.5
        assert effect.raw_damage(_inputs(level=1, ap=200.0)) == pytest.approx(37.5)

    def test_adaptive_type_prefers_larger_contribution(self):
        effect = rune_effects.resolve_rune("Arcane Comet")
        physical = {"bonus_attack_damage": 100.0, "ability_power": 100.0}
        magic = {"bonus_attack_damage": 40.0, "ability_power": 100.0}
        assert effect.damage_type(physical) == "physical"  # 10 > 5
        assert effect.damage_type(magic) == "magic"  # 4 < 5
        assert (
            effect.damage_type({"bonus_attack_damage": 0.0, "ability_power": 0.0})
            == "magic"
        )

    def test_missing_distance_scaling_raises_with_context(self, monkeypatch):
        broken = {
            name: (
                {
                    **entry,
                    "effects": {
                        k: v
                        for k, v in entry["effects"].items()
                        if k != "distance_scaling"
                    },
                }
                if name == "Arcane Comet"
                else entry
            )
            for name, entry in rune_effects.RUNE_EFFECTS.items()
        }
        monkeypatch.setattr(rune_effects, "RUNE_EFFECTS", broken)
        with pytest.raises(KeyError, match="Arcane Comet.*distance_scaling"):
            rune_effects.resolve_rune("Arcane Comet")

    def test_swapped_leveling_tables_raise_with_context(self, monkeypatch):
        # The compiler picks leveling[0] as the minimum-damage table by
        # sentence order. A reworded wiki description leading with the
        # max-range table would silently double every comet — certify
        # that max = min × (1 + full amp) or fail closed.
        broken = {
            name: (
                {
                    **entry,
                    "effects": {
                        **entry["effects"],
                        "leveling": list(reversed(entry["effects"]["leveling"])),
                    },
                }
                if name == "Arcane Comet"
                else entry
            )
            for name, entry in rune_effects.RUNE_EFFECTS.items()
        }
        monkeypatch.setattr(rune_effects, "RUNE_EFFECTS", broken)
        with pytest.raises(KeyError, match="Arcane Comet.*leveling"):
            rune_effects.resolve_rune("Arcane Comet")

    def test_degenerate_distance_span_raises_with_context(self, monkeypatch):
        broken = {
            name: (
                {
                    **entry,
                    "effects": {
                        **entry["effects"],
                        "distance_scaling": {
                            "values": [0.0, 100.0],
                            "distance_range": [750.0, 750.0],
                        },
                    },
                }
                if name == "Arcane Comet"
                else entry
            )
            for name, entry in rune_effects.RUNE_EFFECTS.items()
        }
        monkeypatch.setattr(rune_effects, "RUNE_EFFECTS", broken)
        with pytest.raises(KeyError, match="Arcane Comet.*distance_scaling"):
            rune_effects.resolve_rune("Arcane Comet")

    def test_scalar_cooldown_raises_with_context(self, monkeypatch):
        # A wiki edit that flattens the cooldown to one number must fail
        # closed — a flat 20s cooldown would understate every level-up.
        broken = {
            name: ({**entry, "cooldown": 20.0} if name == "Arcane Comet" else entry)
            for name, entry in rune_effects.RUNE_EFFECTS.items()
        }
        monkeypatch.setattr(rune_effects, "RUNE_EFFECTS", broken)
        with pytest.raises(KeyError, match="Arcane Comet.*cooldown"):
            rune_effects.resolve_rune("Arcane Comet")


# Every key each new compiler reads out of the rune's ``effects`` block.
# Deleting one must raise, naming the rune and the key: rule 5's "no literal
# fallbacks" is only a claim until every read is proven to have no fallback.
_COMPILED_KEYS = {
    "Summon Aery": (
        "leveling",
        "bonus_ad_ratio",
        "ap_ratio",
        "damage_flight_seconds",
        "shield_flight_seconds",
        "shield_duration_seconds",
        "linger_seconds",
    ),
    "Guardian": (
        "leveling",
        "ap_ratio",
        "bonus_health_ratio",
        "trigger_window_seconds",
        "shield_duration_seconds",
    ),
    "Aftershock": (
        "leveling",
        "bonus_health_ratio",
        "bonus_armor_ratio",
        "bonus_magic_resistance_ratio",
        "flat_armor",
        "flat_magic_resistance",
        "resistance_duration_seconds",
        "shockwave_radius",
    ),
    "Grasp of the Undying": (
        "grasp_damage_melee_ranged_ratios",
        "grasp_heal_melee_ranged_ratios",
        "grasp_bonus_health_melee_ranged",
        "combat_stack_generation_seconds",
        "ready_window_seconds",
        "max_stacks",
    ),
    "Hail of Blades": (
        "leveling",
        "bonus_ad_ratio",
        "ap_ratio",
        "hail_bonus_attack_speed_melee_ranged",
        "hail_initial_stacks",
        "hail_stack_duration_seconds",
        "hail_reset_stack_limit",
    ),
    "Lethal Tempo": (
        "lethal_tempo_attack_speed_percent_melee_ranged",
        "lethal_tempo_bolt_damage_melee_by_level",
        "lethal_tempo_bolt_damage_ranged_by_level",
        "lethal_tempo_stack_duration_seconds",
        "lethal_tempo_expiry_step_seconds",
        "max_stacks",
    ),
    "Fleet Footwork": (
        "fleet_heal_melee_by_level",
        "fleet_heal_ranged_by_level",
        "fleet_bonus_ad_ratio_melee_ranged",
        "fleet_ap_ratio_melee_ranged",
        "fleet_bonus_move_speed_melee_ranged",
        "fleet_move_speed_duration_seconds",
        "fleet_minion_heal_effectiveness",
        "fleet_charge_cap",
    ),
    "Conqueror": (
        "conqueror_adaptive_force_by_level",
        "conqueror_adaptive_force_max_by_level",
        "conqueror_heal_melee_ranged_ratios",
        "conqueror_stack_duration_seconds",
        "conqueror_cast_instance_interval_seconds",
        "conqueror_stacks_per_application",
        "max_stacks",
    ),
    "Deathfire Touch": (
        "leveling",
        "deathfire_bonus_ad_ratios_by_state",
        "deathfire_ap_ratios_by_state",
        "deathfire_tick_interval_seconds",
        "deathfire_amp_delay_seconds",
        "deathfire_amp_ratio",
        "deathfire_duration_seconds",
    ),
    "Dark Harvest": (
        "health_threshold_ratio",
        "base_damage",
        "soul_damage",
        "bonus_ad_ratio",
        "ap_ratio",
        "proc_delay_seconds",
        "takedown_reset_seconds",
    ),
    "Stormraider's Surge": (
        "stormraider_damage_threshold_ratio",
        "stormraider_damage_window_seconds",
        "stormraider_duration_seconds",
        "stormraider_bonus_move_speed_melee_ranged",
        "stormraider_slow_resist_ratio",
    ),
    "Glacial Augment": (
        "glacial_ray_count",
        "glacial_zone_radius_units",
        "glacial_zone_width_units",
        "glacial_zone_base_duration_seconds",
        "glacial_zone_duration_cc_ratio",
        "glacial_slow_base_ratio",
        "glacial_slow_bonus_ad_ratio_per_100",
        "glacial_slow_ap_ratio_per_100",
        "glacial_slow_heal_shield_ratio_per_10",
        "glacial_damage_reduction_ratio",
    ),
}


@pytest.mark.parametrize(
    "name,key",
    [(name, key) for name, keys in _COMPILED_KEYS.items() for key in keys],
)
def test_every_compiled_number_fails_loud_when_the_cache_loses_it(
    monkeypatch, name, key
):
    monkeypatch.setattr(rune_effects, "RUNE_EFFECTS", _without(name, key))
    with pytest.raises(KeyError) as raised:
        rune_effects.resolve_rune(name)
    # ``str`` of a KeyError is its argument's repr, which backslash-escapes
    # the apostrophe in "Stormraider's Surge".
    message = str(raised.value).replace("\\'", "'")
    assert name in message
    assert key in message


def test_dark_harvest_fails_loud_without_its_top_level_cooldown(monkeypatch):
    broken = {
        name: (
            {k: v for k, v in entry.items() if k != "cooldown"}
            if name == "Dark Harvest"
            else entry
        )
        for name, entry in rune_effects.RUNE_EFFECTS.items()
    }
    monkeypatch.setattr(rune_effects, "RUNE_EFFECTS", broken)
    with pytest.raises(KeyError, match="Dark Harvest.*cooldown"):
        rune_effects.resolve_rune("Dark Harvest")


class TestKeystonesThatBookNoDamage:
    """Unsealed Spellbook prices nothing, and says so rather than refusing.

    Its effect is a summoner-spell selection state — the holder picks the
    equipped and swapped spells, each spell has its own effect — and the
    cached template carries no numeric value for the rune itself. It is
    still compiled and selectable; a keystone that refuses is the failure
    this shape removes.
    """

    def test_unsealed_spellbook_declares_a_structural_zero(self):
        name = "Unsealed Spellbook"
        effect = rune_effects.resolve_rune(name)
        assert isinstance(effect, rune_effects.RuneNoDamageEffect)
        assert effect.zero_policy.disposition is Disposition.STRUCTURAL_ZERO
        assert effect.receipts[0].startswith(f"{name} deals no damage in any fight:")

    def test_it_is_the_only_keystone_that_books_none(self):
        booked_none = {
            name
            for name, entry in rune_effects.RUNE_EFFECTS.items()
            if isinstance(entry, dict)
            and entry.get("row") == 0
            and isinstance(
                rune_effects.resolve_rune(name), rune_effects.RuneNoDamageEffect
            )
        }
        assert booked_none == {"Unsealed Spellbook"}

    def test_a_receipt_without_a_reason_is_rejected(self):
        with pytest.raises(ValueError, match="reason"):
            rune_effects.RuneNoDamageEffect(
                rune_name="Synthetic",
                zero_policy=rune_effects.ZeroPolicy(Disposition.WITHHELD, "  "),
            )


class TestRuneCatalog:
    def test_the_whole_roster_is_listed_with_its_slot(self):
        catalog = rune_effects.rune_catalog()
        assert len(catalog) == 62
        by_name = {entry["name"]: entry for entry in catalog}
        assert by_name["Electrocute"]["path"] == "Domination"
        assert by_name["Electrocute"]["row"] == 0
        assert by_name["Coup de Grace"]["row"] == 3
        assert by_name["First Strike"]["implemented"] is True
        assert by_name["Press the Attack"]["implemented"] is True
        assert by_name["Arcane Comet"]["implemented"] is True
        assert by_name["Summon Aery"]["implemented"] is True
        assert by_name["Guardian"]["implemented"] is True
        assert by_name["Aftershock"]["implemented"] is True
        assert by_name["Grasp of the Undying"]["implemented"] is True
        assert by_name["Dark Harvest"]["implemented"] is True
        assert by_name["Fleet Footwork"]["implemented"] is True
        assert by_name["Conqueror"]["implemented"] is True
        assert all(entry["path"] for entry in catalog)
        assert all(entry["icon"] for entry in catalog)
        assert {entry["row"] for entry in catalog} == {0, 1, 2, 3}

    def test_every_keystone_and_the_four_exemplars_are_implemented(self):
        by_name = {entry["name"]: entry for entry in rune_effects.rune_catalog()}
        keystones = [entry for entry in by_name.values() if entry["row"] == 0]
        assert len(keystones) == 17
        assert all(entry["implemented"] is True for entry in keystones)
        for name in ("Absolute Focus", "Coup de Grace", "Scorch", "Cosmic Insight"):
            assert by_name[name]["implemented"] is True, name

    def test_an_uncompiled_rune_is_published_greyed_out(self, monkeypatch):
        monkeypatch.setitem(
            rune_effects.RUNE_EFFECTS,
            "Synthetic Keystone",
            {"name": "Synthetic Keystone", "path": "Sorcery", "icon": "x"},
        )
        catalog = {entry["name"]: entry for entry in rune_effects.rune_catalog()}
        assert catalog["Synthetic Keystone"]["implemented"] is False

    def test_the_declared_option_reaches_the_catalog(self):
        by_name = {entry["name"]: entry for entry in rune_effects.rune_catalog()}
        options = by_name["Absolute Focus"]["options"]
        assert [option["key"] for option in options] == ["above_health_threshold"]
        assert options[0]["default"] == 1.0
        assert options[0]["disclosure"]

    def test_the_shard_table_publishes_three_rows_of_three(self):
        catalog = rune_effects.shard_catalog()
        assert [row["row"] for row in catalog] == [1, 2, 3]
        assert [row["name"] for row in catalog] == ["Offense", "Flex", "Defense"]
        assert all(len(row["options"]) == 3 for row in catalog)
        assert catalog[0]["options"][0]["name"] == "Adaptive Force"
        # Every shard compiles; tests/test_rune_shards.py prices each one.
        assert all(
            option["implemented"] for row in catalog for option in row["options"]
        )


class TestValidateKeystoneRequest:
    def test_default_empty(self):
        assert rune_effects.validate_rune_page(None).keystone == ""
        assert rune_effects.validate_rune_page("").keystone == ""

    def test_valid_name_passes_through(self):
        page = rune_effects.validate_rune_page("Electrocute")
        assert page.keystone == "Electrocute"
        assert rune_effects.validate_keystone_request("Electrocute") == "Electrocute"
        assert (
            rune_effects.validate_keystone_request("Deathfire Touch")
            == "Deathfire Touch"
        )

    def test_non_string_rejected(self):
        with pytest.raises(ValueError, match="keystone"):
            rune_effects.validate_rune_page(42)

    def test_every_cached_keystone_is_selectable(self):
        for name, entry in rune_effects.RUNE_EFFECTS.items():
            if entry.get("row") != 0:
                continue
            assert rune_effects.validate_rune_page(name).keystone == name

    def test_a_minor_rune_is_not_a_keystone(self):
        with pytest.raises(ValueError, match="minor rune"):
            rune_effects.validate_rune_page("Scorch")

    def test_uncompiled_rejected(self, monkeypatch):
        monkeypatch.setitem(
            rune_effects.RUNE_EFFECTS, "Synthetic Keystone", {"name": "Synthetic"}
        )
        with pytest.raises(ValueError, match="not modeled"):
            rune_effects.validate_rune_page("Synthetic Keystone")
            rune_effects.validate_keystone_request("Unsealed Spellbook")

    def test_fleet_options_require_bounded_integer_charges(self):
        assert rune_effects.validate_keystone_options(
            {"starting_charges": 100}, "Fleet Footwork"
        ) == {"starting_charges": 100}
        with pytest.raises(ValueError, match="integer"):
            rune_effects.validate_keystone_options(
                {"starting_charges": 10.5}, "Fleet Footwork"
            )
        with pytest.raises(ValueError, match="between"):
            rune_effects.validate_keystone_options(
                {"starting_charges": 101}, "Fleet Footwork"
            )

    def test_conqueror_options_require_bounded_integer_stacks(self):
        assert rune_effects.validate_keystone_options(
            {"starting_stacks": 12}, "Conqueror"
        ) == {"starting_stacks": 12}
        with pytest.raises(ValueError, match="integer"):
            rune_effects.validate_keystone_options(
                {"starting_stacks": 2.5}, "Conqueror"
            )
        with pytest.raises(ValueError, match="between"):
            rune_effects.validate_keystone_options({"starting_stacks": 13}, "Conqueror")


class TestRefreshRuneEffects:
    def test_refresh_rereads_the_cache_in_place(self, monkeypatch):
        try:
            monkeypatch.setattr(
                rune_effects, "_load_rune_cache", lambda: {"Stub": {"name": "Stub"}}
            )
            rune_effects.refresh_rune_effects()
            assert set(rune_effects.RUNE_EFFECTS) == {"Stub"}
        finally:
            monkeypatch.undo()
            rune_effects.refresh_rune_effects()
        assert "Electrocute" in rune_effects.RUNE_EFFECTS
        assert rune_effects.RUNE_SHARDS["slots"]
        assert rune_effects.ADAPTIVE_FORCE["attack_damage_ratio"] == 0.6


class TestTheSharedTableAccessors:
    """The doors every compiler reads a table through, and what each refuses.

    Three of them, and the difference between them is what a table's columns
    *are*: ``required_leveling`` and ``required_level_table`` read champion
    levels, ``keyed_columns`` reads a table keyed by something else, and
    ``threshold_gates`` reads a list of (threshold, bonus) pairs. They live in
    ``rune_effects`` rather than in one path module because runes from three
    paths read them.
    """

    def test_a_level_table_may_be_either_width_the_wiki_renders(self):
        """Twenty columns from an explicit range, eighteen from a stepless one.

        Cheap Shot's table states ``1 to 20 by 1`` and renders twenty;
        Sudden Impact's states ``20 to 80`` and renders Module:Ability
        progression's default eighteen. Both are complete.
        """
        assert rune_effects.LEVEL_TABLE_SIZES == (18, 20)
        widths = {
            name: len(
                rune_effects.required_leveling(
                    name, rune_effects.RuneValues(name, _cached(name))
                )
            )
            for name in ("Cheap Shot", "Sudden Impact")
        }
        assert widths == {"Cheap Shot": 20, "Sudden Impact": 18}

    @pytest.mark.parametrize("width", [17, 19, 21])
    def test_any_other_width_is_still_a_degraded_parse(self, width):
        """The relaxation must not admit a twenty-level table missing columns."""
        values = rune_effects.RuneValues("Synthetic", {"leveling": [[1.0] * width]})
        with pytest.raises(KeyError, match="Synthetic.*18 or 20"):
            rune_effects.required_leveling("Synthetic", values)

    def test_a_keyed_table_is_read_by_its_own_rule_not_the_level_one(self):
        """Gathering Storm states eight minute columns, and eight is enough."""
        name = "Gathering Storm"
        values = rune_effects.RuneValues(name, _cached(name))
        assert len(rune_effects.keyed_columns(name, values, "leveling", 1)) == 8
        with pytest.raises(KeyError, match="18 or 20"):
            rune_effects.required_leveling(name, values, "leveling", 1)

    def test_a_keyed_table_of_one_column_states_no_step(self):
        values = rune_effects.RuneValues("Synthetic", {"leveling": [[3.0]]})
        with pytest.raises(KeyError, match="needs at least two"):
            rune_effects.keyed_columns("Synthetic", values, "leveling", 0)

    def test_threshold_gates_read_both_halves_of_each_pair(self):
        name = "Transcendence"
        values = rune_effects.RuneValues(name, _cached(name))
        gates = rune_effects.threshold_gates(name, values, "ability_haste_level_gates")
        assert gates == ((5, 5.0), (8, 5.0))

    def test_an_empty_gate_list_is_a_degraded_parse(self):
        values = rune_effects.RuneValues("Synthetic", {"gates": []})
        with pytest.raises(KeyError, match="states no gates"):
            rune_effects.threshold_gates("Synthetic", values, "gates")
