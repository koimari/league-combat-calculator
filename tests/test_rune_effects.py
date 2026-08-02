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


class TestKeystoneCatalog:
    def test_all_keystones_listed_with_coverage_flags(self):
        catalog = rune_effects.keystone_catalog()
        assert len(catalog) == 17
        by_name = {entry["name"]: entry for entry in catalog}
        assert by_name["Electrocute"]["implemented"] is True
        assert by_name["Electrocute"]["path"] == "Domination"
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
