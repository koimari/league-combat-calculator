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

    def test_unimplemented_keystone_fails_closed(self):
        with pytest.raises(ValueError, match="not modeled"):
            rune_effects.resolve_keystone("Dark Harvest")

    def test_electrocute_resolves(self):
        effect = rune_effects.resolve_keystone("Electrocute")
        assert effect.keystone_name == "Electrocute"
        assert effect.stacks_required == 3
        assert effect.stack_window_seconds == 3.0
        assert effect.cooldown_seconds == 20.0
        assert effect.proc_delay_seconds == 0.25


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
        )
        assert slot is not None
        assert slot.window() == (0.0, 3.0)
        assert slot.fractions[0] == pytest.approx(0.07)
        assert slot.uniform_bonus_damage_type() == "true"

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
        assert by_name["Dark Harvest"]["implemented"] is False
        assert all(entry["path"] for entry in catalog)
        assert all(entry["icon"] for entry in catalog)


class TestValidateKeystoneRequest:
    def test_default_empty(self):
        assert rune_effects.validate_keystone_request(None) == ""
        assert rune_effects.validate_keystone_request("") == ""

    def test_valid_name_passes_through(self):
        assert rune_effects.validate_keystone_request("Electrocute") == "Electrocute"

    def test_non_string_rejected(self):
        with pytest.raises(ValueError, match="keystone"):
            rune_effects.validate_keystone_request(42)

    def test_unimplemented_rejected(self):
        with pytest.raises(ValueError, match="not modeled"):
            rune_effects.validate_keystone_request("Summon Aery")


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
