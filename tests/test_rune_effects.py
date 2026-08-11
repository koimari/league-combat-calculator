"""Tests for keystone rune resolution and the Electrocute effect formula."""

import pytest

from src.calculator import rune_effects
from src.calculator.item_effects import DamageInputs


def _inputs(level=1, bonus_ad=0.0, ap=0.0):
    return DamageInputs(
        champion_stats={
            "bonus_attack_damage": bonus_ad,
            "ability_power": ap,
        },
        level=level,
        is_melee=False,
        target_max_health=1000.0,
        target_current_health=1000.0,
    )


class TestResolveKeystone:
    def test_empty_selection_resolves_to_none(self):
        assert rune_effects.resolve_keystone("") is None

    def test_unknown_keystone_raises(self):
        with pytest.raises(ValueError, match="Fake Rune"):
            rune_effects.resolve_keystone("Fake Rune")

    def test_fleet_footwork_resolves_charge_heal_and_speed(self):
        effect = rune_effects.resolve_keystone("Fleet Footwork")
        assert isinstance(effect, rune_effects.KeystoneFleetEffect)
        assert effect.charge_cap == pytest.approx(100.0)
        assert effect.move_speed_duration_seconds == pytest.approx(1.0)
        assert effect.bonus_move_speed_percent(True) == pytest.approx(20.0)
        assert effect.bonus_move_speed_percent(False) == pytest.approx(15.0)
        stats = {"bonus_attack_damage": 100.0, "ability_power": 50.0}
        assert effect.heal_amount(18, stats, False) == pytest.approx(85.5)
        assert effect.heal_amount(
            18, stats, False, against_minion=True
        ) == pytest.approx(12.825)

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
        effect = rune_effects.resolve_keystone("Electrocute")
        assert effect.keystone_name == "Electrocute"
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
        assert effect.bonus_attack_speed_percent(True) == pytest.approx(120.0)
        assert effect.bonus_attack_speed_percent(False) == pytest.approx(60.0)
        assert effect.raw_damage(
            _inputs(level=18, bonus_ad=100.0, ap=50.0)
        ) == pytest.approx(20.0 + 8.0 + 3.0)

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
        effect = rune_effects.resolve_keystone("Electrocute")
        assert effect.raw_damage(_inputs(level=1)) == pytest.approx(70.0)
        assert effect.raw_damage(_inputs(level=11)) == pytest.approx(170.0)
        assert effect.raw_damage(_inputs(level=20)) == pytest.approx(260.0)

    def test_ratio_scaling(self):
        effect = rune_effects.resolve_keystone("Electrocute")
        assert effect.raw_damage(_inputs(level=1, bonus_ad=100.0)) == pytest.approx(
            80.0
        )
        assert effect.raw_damage(_inputs(level=1, ap=200.0)) == pytest.approx(80.0)

    def test_adaptive_type_prefers_larger_contribution(self):
        effect = rune_effects.resolve_keystone("Electrocute")
        physical = {"bonus_attack_damage": 100.0, "ability_power": 100.0}
        magic = {"bonus_attack_damage": 40.0, "ability_power": 100.0}
        assert effect.damage_type(physical) == "physical"  # 10 AD > 5 AP contribution
        assert effect.damage_type(magic) == "magic"  # 4 < 5

    def test_adaptive_type_defaults_to_magic_on_tie_or_zero(self):
        effect = rune_effects.resolve_keystone("Electrocute")
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
            rune_effects.resolve_keystone("Electrocute")


class TestFirstStrike:
    def test_first_strike_resolves_to_window_amp_effect(self):
        effect = rune_effects.resolve_keystone("First Strike")
        assert isinstance(effect, rune_effects.KeystoneWindowAmpEffect)
        assert effect.keystone_name == "First Strike"
        assert effect.breakdown_key == "keystone_First Strike"
        assert effect.window_seconds == 3.0
        assert effect.bonus_damage_ratio == pytest.approx(0.07)
        assert effect.activation_gold == 10.0

    def test_gold_conversion_is_melee_ranged_split(self):
        effect = rune_effects.resolve_keystone("First Strike")
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
                        if k != "melee_ranged_ratios"
                    },
                }
                if name == "First Strike"
                else entry
            )
            for name, entry in rune_effects.RUNE_EFFECTS.items()
        }
        monkeypatch.setattr(rune_effects, "RUNE_EFFECTS", broken)
        with pytest.raises(KeyError, match="First Strike.*melee_ranged_ratios"):
            rune_effects.resolve_keystone("First Strike")


class TestPressTheAttack:
    def test_press_the_attack_resolves_to_proc_amp_effect(self):
        effect = rune_effects.resolve_keystone("Press the Attack")
        assert isinstance(effect, rune_effects.KeystoneProcAmpEffect)
        assert effect.keystone_name == "Press the Attack"
        assert effect.breakdown_key == "keystone_Press the Attack"
        assert effect.amp_breakdown_key == "keystone_Press the Attack amp"
        assert effect.amp_display_name == "Press the Attack amp (keystone)"
        assert effect.stacks_required == 3
        assert effect.stack_duration_seconds == 4.0
        assert effect.cooldown_seconds == 6.0
        assert effect.damage_amp_ratio == pytest.approx(0.08)

    def test_proc_damage_by_level_has_no_ratio_scaling(self):
        effect = rune_effects.resolve_keystone("Press the Attack")
        assert effect.raw_damage(_inputs(level=1)) == pytest.approx(40.0)
        assert effect.raw_damage(_inputs(level=18)) == pytest.approx(160.0)
        assert effect.raw_damage(_inputs(level=20)) == pytest.approx(174.117647)
        # The proc is pure leveled adaptive damage — stats must not move it.
        assert effect.raw_damage(
            _inputs(level=18, bonus_ad=300.0, ap=500.0)
        ) == pytest.approx(160.0)

    def test_adaptive_type_compares_bonus_ad_against_ap(self):
        effect = rune_effects.resolve_keystone("Press the Attack")
        physical = {"bonus_attack_damage": 100.0, "ability_power": 50.0}
        magic = {"bonus_attack_damage": 50.0, "ability_power": 100.0}
        assert effect.damage_type(physical) == "physical"
        assert effect.damage_type(magic) == "magic"

    def test_adaptive_type_defaults_to_magic_on_tie_or_zero(self):
        # Ties follow the champion's adaptive type in game; the engine
        # carries no adaptive type, so it defaults magic like Electrocute.
        effect = rune_effects.resolve_keystone("Press the Attack")
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
                        if k != "damage_amp_ratio"
                    },
                }
                if name == "Press the Attack"
                else entry
            )
            for name, entry in rune_effects.RUNE_EFFECTS.items()
        }
        monkeypatch.setattr(rune_effects, "RUNE_EFFECTS", broken)
        with pytest.raises(KeyError, match="Press the Attack.*damage_amp_ratio"):
            rune_effects.resolve_keystone("Press the Attack")


class TestArcaneComet:
    def test_arcane_comet_resolves_to_ability_proc_effect(self):
        effect = rune_effects.resolve_keystone("Arcane Comet")
        assert isinstance(effect, rune_effects.KeystoneAbilityProcEffect)
        assert effect.keystone_name == "Arcane Comet"
        assert effect.breakdown_key == "keystone_Arcane Comet"
        assert effect.proc_delay_seconds == pytest.approx(0.8)
        assert effect.assumed_travel_distance == 375.0
        # 375 of the 750-unit span → halfway up the 0-100% damage table.
        assert effect.distance_amp_ratio == pytest.approx(0.5)

    def test_cooldown_scales_with_level(self):
        effect = rune_effects.resolve_keystone("Arcane Comet")
        assert effect.cooldown_at(1) == pytest.approx(20.0)
        assert effect.cooldown_at(18) == pytest.approx(8.0)
        assert effect.cooldown_at(20) == pytest.approx(20 - 12 / 17 * 19)
        # Out-of-range levels clamp like the leveling arrays do.
        assert effect.cooldown_at(0) == pytest.approx(20.0)
        assert effect.cooldown_at(30) == pytest.approx(20 - 12 / 17 * 19)

    def test_damage_is_min_formula_amped_by_assumed_distance(self):
        effect = rune_effects.resolve_keystone("Arcane Comet")
        # (15 base at level 1) × 1.5 distance amp
        assert effect.raw_damage(_inputs(level=1)) == pytest.approx(22.5)
        # (100 base at level 18) × 1.5
        assert effect.raw_damage(_inputs(level=18)) == pytest.approx(150.0)
        # (110 base at level 20) × 1.5 — meets the wiki's max-range 220
        # array exactly at the 100%-amp endpoint, halved at ours.
        assert effect.raw_damage(_inputs(level=20)) == pytest.approx(165.0)

    def test_ratios_are_amped_with_the_base(self):
        effect = rune_effects.resolve_keystone("Arcane Comet")
        # (15 + 10% × 100 bonus AD) × 1.5
        assert effect.raw_damage(_inputs(level=1, bonus_ad=100.0)) == pytest.approx(
            37.5
        )
        # (15 + 5% × 200 AP) × 1.5
        assert effect.raw_damage(_inputs(level=1, ap=200.0)) == pytest.approx(37.5)

    def test_adaptive_type_prefers_larger_contribution(self):
        effect = rune_effects.resolve_keystone("Arcane Comet")
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
            rune_effects.resolve_keystone("Arcane Comet")

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
            rune_effects.resolve_keystone("Arcane Comet")

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
            rune_effects.resolve_keystone("Arcane Comet")

    def test_scalar_cooldown_raises_with_context(self, monkeypatch):
        # A wiki edit that flattens the cooldown to one number must fail
        # closed — a flat 20s cooldown would understate every level-up.
        broken = {
            name: ({**entry, "cooldown": 20.0} if name == "Arcane Comet" else entry)
            for name, entry in rune_effects.RUNE_EFFECTS.items()
        }
        monkeypatch.setattr(rune_effects, "RUNE_EFFECTS", broken)
        with pytest.raises(KeyError, match="Arcane Comet.*cooldown"):
            rune_effects.resolve_keystone("Arcane Comet")


class TestKeystoneCatalog:
    def test_all_keystones_listed_with_coverage_flags(self):
        catalog = rune_effects.keystone_catalog()
        assert len(catalog) == 17
        by_name = {entry["name"]: entry for entry in catalog}
        assert by_name["Electrocute"]["implemented"] is True
        assert by_name["Electrocute"]["path"] == "Domination"
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


class TestValidateKeystoneRequest:
    def test_default_empty(self):
        assert rune_effects.validate_keystone_request(None) == ""
        assert rune_effects.validate_keystone_request("") == ""

    def test_valid_name_passes_through(self):
        assert rune_effects.validate_keystone_request("Electrocute") == "Electrocute"
        assert (
            rune_effects.validate_keystone_request("Deathfire Touch")
            == "Deathfire Touch"
        )

    def test_non_string_rejected(self):
        with pytest.raises(ValueError, match="keystone"):
            rune_effects.validate_keystone_request(42)

    def test_unimplemented_rejected(self):
        with pytest.raises(ValueError, match="not modeled"):
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
                rune_effects, "_load_rune_effects", lambda: {"Stub": {"name": "Stub"}}
            )
            rune_effects.refresh_rune_effects()
            assert set(rune_effects.RUNE_EFFECTS) == {"Stub"}
        finally:
            monkeypatch.undo()
            rune_effects.refresh_rune_effects()
        assert "Electrocute" in rune_effects.RUNE_EFFECTS
