"""Tests for item_effects stat-passive accessors and registry refresh.

The accessors own both the ITEM_EFFECTS lookup and the numeric semantics
of each stat-granting passive.  Tests monkeypatch the registry entry to a
known value so they exercise accessor logic without depending on the
current patch's parsed numbers.
"""

import copy

import pytest

from src.calculator import item_effects
from src.calculator.item_effects import (
    ITEM_EFFECTS,
    get_ap_multiplier,
    get_basic_ability_haste,
    get_bloodmail_bonus_ad,
    get_dawncore_bonus_ap,
    get_flowing_water_bonus_ap,
    get_mana_to_ap_bonus,
    get_muramana_bonus_ad,
    get_passive_attack_speed_bonus,
    get_steraks_bonus_ad,
    get_terminus_max_stack_bonuses,
    refresh_item_effects,
)


def _build(*names: str) -> list[dict]:
    """Make a minimal item build from item names."""
    return [{"name": name} for name in names]


def _patch_effect(monkeypatch: pytest.MonkeyPatch, item_name: str, **overrides) -> None:
    """Override keys on one registry entry for the duration of a test."""
    patched = dict(item_effects.ITEM_EFFECTS.get(item_name, {}))
    patched.update(overrides)
    monkeypatch.setitem(item_effects.ITEM_EFFECTS, item_name, patched)


class TestApMultiplier:
    """Rabadon's / Blackfire Torch additive %AP increase."""

    def test_no_items_returns_1(self) -> None:
        assert get_ap_multiplier([]) == 1.0

    def test_rabadons(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_effect(monkeypatch, "Rabadon's Deathcap", ap_percent_increase=0.30)
        assert get_ap_multiplier(_build("Rabadon's Deathcap")) == 1.30

    def test_stacks_additively(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 30% + 4% = 34%, NOT 1.30 x 1.04
        _patch_effect(monkeypatch, "Rabadon's Deathcap", ap_percent_increase=0.30)
        _patch_effect(monkeypatch, "Blackfire Torch", ap_amp_per_target=0.04)
        build = _build("Rabadon's Deathcap", "Blackfire Torch")
        assert abs(get_ap_multiplier(build) - 1.34) < 1e-9


class TestManaToApBonus:
    """Awe passives: Archangel's Staff and Seraph's Embrace."""

    def test_absent_returns_zero(self) -> None:
        assert get_mana_to_ap_bonus(_build("Liandry's Torment"), 1000) == 0.0

    def test_archangels(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_effect(monkeypatch, "Archangel's Staff", bonus_mana_to_ap_ratio=0.01)
        assert get_mana_to_ap_bonus(_build("Archangel's Staff"), 600) == 6.0

    def test_both_awe_items_sum(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_effect(monkeypatch, "Archangel's Staff", bonus_mana_to_ap_ratio=0.01)
        _patch_effect(monkeypatch, "Seraph's Embrace", bonus_mana_to_ap_ratio=0.02)
        build = _build("Archangel's Staff", "Seraph's Embrace")
        assert get_mana_to_ap_bonus(build, 1000) == 30.0


class TestDawncoreBonusAp:
    def test_absent_returns_zero(self) -> None:
        assert get_dawncore_bonus_ap([], 150.0) == 0.0

    def test_ap_per_regen_unit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_effect(
            monkeypatch,
            "Dawncore",
            ap_per_mana_regen_unit=10.0,
            mana_regen_threshold_percent=100.0,
        )
        assert get_dawncore_bonus_ap(_build("Dawncore"), 150.0) == 15.0


class TestFlowingWaterBonusAp:
    def test_absent_returns_zero(self) -> None:
        assert get_flowing_water_bonus_ap([]) == 0.0

    def test_reads_registry_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_effect(monkeypatch, "Staff of Flowing Water", rapids_bonus_ap=40.0)
        assert get_flowing_water_bonus_ap(_build("Staff of Flowing Water")) == 40.0


class TestPassiveAttackSpeedBonus:
    def test_no_items_returns_zero(self) -> None:
        assert get_passive_attack_speed_bonus([], is_melee=False) == 0.0

    def test_bandlepipes_melee_ranged_split(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_effect(
            monkeypatch,
            "Bandlepipes",
            bonus_attack_speed_melee=30.0,
            bonus_attack_speed_ranged=20.0,
        )
        build = _build("Bandlepipes")
        assert get_passive_attack_speed_bonus(build, is_melee=True) == 30.0
        assert get_passive_attack_speed_bonus(build, is_melee=False) == 20.0

    def test_hexplate_and_yun_tal_sum(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_effect(
            monkeypatch, "Experimental Hexplate", bonus_attack_speed_percent=50.0
        )
        _patch_effect(
            monkeypatch, "Yun Tal Wildarrows", bonus_attack_speed_percent=30.0
        )
        build = _build("Experimental Hexplate", "Yun Tal Wildarrows")
        assert get_passive_attack_speed_bonus(build, is_melee=False) == 80.0


class TestBonusAdConversions:
    """Muramana, Overlord's Bloodmail, and Sterak's Gage AD conversions."""

    def test_muramana(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_effect(monkeypatch, "Muramana", max_mana_to_ad_ratio=0.02)
        assert get_muramana_bonus_ad(_build("Muramana"), 1500) == 30.0

    def test_muramana_absent(self) -> None:
        assert get_muramana_bonus_ad([], 1500) == 0.0

    def test_bloodmail(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_effect(
            monkeypatch, "Overlord's Bloodmail", bonus_health_to_ad_ratio=0.025
        )
        assert get_bloodmail_bonus_ad(_build("Overlord's Bloodmail"), 400) == 10.0

    def test_steraks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_effect(monkeypatch, "Sterak's Gage", base_ad_to_bonus_ad_ratio=0.45)
        assert get_steraks_bonus_ad(_build("Sterak's Gage"), 100) == 45.0


class TestTerminusMaxStackBonuses:
    def test_absent_returns_zeros(self) -> None:
        assert get_terminus_max_stack_bonuses([], 18) == (0.0, 0.0)

    def test_level_18_max_stacks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_effect(
            monkeypatch,
            "Terminus",
            dark_max_stacks=3,
            dark_pen_per_stack=0.10,
            light_resist_min=6.0,
            light_resist_max=8.0,
        )
        resist, pen = get_terminus_max_stack_bonuses(_build("Terminus"), 18)
        assert resist == 24.0  # 8 per stack at 18 x 3 stacks
        assert abs(pen - 30.0) < 1e-9  # 10% x 3 stacks, as percentage

    def test_level_1_uses_min_resist(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_effect(
            monkeypatch,
            "Terminus",
            dark_max_stacks=3,
            light_resist_min=6.0,
            light_resist_max=8.0,
        )
        resist, _ = get_terminus_max_stack_bonuses(_build("Terminus"), 1)
        assert resist == 18.0  # 6 per stack at level 1 x 3 stacks


class TestBasicAbilityHaste:
    def test_absent_returns_zero(self) -> None:
        assert get_basic_ability_haste([]) == 0.0

    def test_shojin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_effect(monkeypatch, "Spear of Shojin", basic_ability_haste=25.0)
        assert get_basic_ability_haste(_build("Spear of Shojin")) == 25.0


class TestMissingKeyFailsLoudly:
    """A missing effect key is a parser/defaults bug — never a silent default."""

    def test_keyerror_names_item_and_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        broken = dict(item_effects.ITEM_EFFECTS.get("Sterak's Gage", {}))
        broken.pop("base_ad_to_bonus_ad_ratio", None)
        monkeypatch.setitem(item_effects.ITEM_EFFECTS, "Sterak's Gage", broken)
        with pytest.raises(KeyError, match="base_ad_to_bonus_ad_ratio"):
            get_steraks_bonus_ad(_build("Sterak's Gage"), 100)


class TestRefreshItemEffects:
    """refresh_item_effects must mutate the registry dict in place."""

    @pytest.fixture(autouse=True)
    def preserve_registry(self):
        """Snapshot and restore ITEM_EFFECTS around each test."""
        saved = copy.deepcopy(item_effects.ITEM_EFFECTS)
        yield
        item_effects.ITEM_EFFECTS.clear()
        item_effects.ITEM_EFFECTS.update(saved)

    def test_refresh_mutates_in_place(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A from-import binding of ITEM_EFFECTS sees refreshed content."""
        fake_registry = {"Test Item": {"type": "on_hit", "base": 123.0}}
        monkeypatch.setattr(
            item_effects,
            "_build_item_effects",
            lambda defaults: dict(fake_registry),
        )

        # ITEM_EFFECTS at this module's top is a from-import binding —
        # exactly the pattern used by calculator/__init__.py.
        binding_before = ITEM_EFFECTS
        refresh_item_effects()

        assert ITEM_EFFECTS is binding_before  # same object, not rebound
        assert ITEM_EFFECTS == fake_registry
        assert item_effects.ITEM_EFFECTS is binding_before

    def test_refresh_drops_stale_entries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """clear() before update(): entries absent from the rebuild vanish."""
        monkeypatch.setattr(item_effects, "_build_item_effects", lambda defaults: {})
        item_effects.ITEM_EFFECTS["Removed Item"] = {"type": "on_hit"}
        refresh_item_effects()
        assert "Removed Item" not in ITEM_EFFECTS
