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
    DamageInputs,
    _ap_multiplier,
    _basic_ability_haste,
    bloodmail_bonus_ad,
    _dawncore_bonus_ap,
    _flowing_water_bonus_ap,
    _mana_to_ap_bonus,
    _muramana_bonus_ad,
    _passive_attack_speed_bonus,
    steraks_bonus_ad,
    _terminus_max_stack_bonuses,
    refresh_item_effects,
    resolve_damage_effects,
    resolve_stat_effects,
    shield_reduction_fraction,
)


def _build(*names: str) -> list[dict]:
    """Make a minimal item build from item names."""
    return [{"name": name} for name in names]


def _patch_effect(monkeypatch: pytest.MonkeyPatch, item_name: str, **overrides) -> None:
    """Override keys on one registry entry for the duration of a test."""
    patched = dict(item_effects.ITEM_EFFECTS.get(item_name, {}))
    patched.update(overrides)
    monkeypatch.setitem(item_effects.ITEM_EFFECTS, item_name, patched)


class TestResolveDamageEffects:
    """Compile registry data into the fight engine's typed build projection."""

    def test_formula_reads_live_registry_values(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_effect(monkeypatch, "Nashor's Tooth", base=100.0, ap_ratio=0.5)

        effects = resolve_damage_effects(_build("Nashor's Tooth"))
        inputs = DamageInputs(
            champion_stats={"ability_power": 200.0},
            level=18,
            is_melee=False,
            target_max_health=1000.0,
            target_current_health=1000.0,
        )

        assert effects.per_hits[0].source.raw_damage(inputs) == 200.0

    def test_missing_required_key_names_item_and_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        broken = dict(ITEM_EFFECTS["Nashor's Tooth"])
        broken.pop("base")
        monkeypatch.setitem(ITEM_EFFECTS, "Nashor's Tooth", broken)

        with pytest.raises(KeyError) as exc_info:
            resolve_damage_effects(_build("Nashor's Tooth"))
        message = exc_info.value.args[0]
        assert "Nashor's Tooth" in message
        assert "base" in message

    def test_unknown_effect_type_names_item_and_type(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        broken = dict(ITEM_EFFECTS["Statikk Shiv"])
        broken["type"] = "on_hit_onc"
        monkeypatch.setitem(ITEM_EFFECTS, "Statikk Shiv", broken)

        with pytest.raises(ValueError, match="Statikk Shiv.*on_hit_onc"):
            resolve_damage_effects(_build("Statikk Shiv"))

    def test_one_item_can_emit_multiple_behaviors(self) -> None:
        effects = resolve_damage_effects(_build("Titanic Hydra", "Muramana"))

        assert {effect.source.item_name for effect in effects.per_hits} == {
            "Titanic Hydra",
            "Muramana",
        }
        assert [effect.source.item_name for effect in effects.auto_cooldowns] == [
            "Titanic Hydra"
        ]
        assert [effect.item_name for effect in effects.per_ability_hits] == ["Muramana"]

    def test_spellblade_compiles_formula_and_scheduling(self) -> None:
        effects = resolve_damage_effects(_build("Lich Bane"))
        inputs = DamageInputs(
            champion_stats={"base_attack_damage": 100.0, "ability_power": 200.0},
            level=18,
            is_melee=False,
            target_max_health=1000.0,
            target_current_health=1000.0,
        )

        assert effects.spellblade is not None
        assert effects.spellblade.source.raw_damage(inputs) == 165.0
        assert effects.spellblade.cooldown == 1.5
        assert effects.spellblade.weave_delay == 1.5

    def test_phase_families_compile_into_typed_buckets(self) -> None:
        effects = resolve_damage_effects(
            _build(
                "Liandry's Torment",
                "Sunfire Aegis",
                "Unending Despair",
                "Luden's Echo",
                "Malignance",
                "Hextech Rocketbelt",
            )
        )

        assert [effect.source.item_name for effect in effects.burns] == [
            "Liandry's Torment"
        ]
        assert [source.item_name for source in effects.immolates] == ["Sunfire Aegis"]
        assert [effect.source.item_name for effect in effects.periodic] == [
            "Unending Despair"
        ]
        assert [effect.source.item_name for effect in effects.cooldown_procs] == [
            "Luden's Echo"
        ]
        assert [effect.source.item_name for effect in effects.ultimate_procs] == [
            "Malignance"
        ]
        assert [source.item_name for source in effects.actives] == [
            "Hextech Rocketbelt"
        ]

    def test_auto_trigger_families_compile_without_item_dispatch(self) -> None:
        effects = resolve_damage_effects(
            _build(
                "Rapid Firecannon",
                "Dead Man's Plate",
                "Heartsteel",
                "Statikk Shiv",
                "Stormrazor",
                "Voltaic Cyclosword",
                "Hullbreaker",
                "Kraken Slayer",
                "Eclipse",
            )
        )

        assert [effect.source.item_name for effect in effects.first_autos] == [
            "Rapid Firecannon",
            "Dead Man's Plate",
            "Heartsteel",
            "Statikk Shiv",
            "Stormrazor",
            "Voltaic Cyclosword",
        ]
        assert [effect.source.item_name for effect in effects.stacking_on_hits] == [
            "Hullbreaker",
            "Kraken Slayer",
        ]
        assert any(
            effect.source.item_name == "Eclipse" for effect in effects.cooldown_procs
        )

    def test_engine_modifiers_compile_as_typed_values(self) -> None:
        effects = resolve_damage_effects(
            _build(
                "Guinsoo's Rageblade",
                "Terminus",
                "Navori Flickerblade",
                "Infinity Edge",
                "Sundered Sky",
                "Shadowflame",
                "Experimental Hexplate",
                "Fiendhunter Bolts",
                "Actualizer",
                "Hexoptics C44",
                "The Collector",
                "Liandry's Torment",
                "Riftmaker",
                "Lord Dominik's Regards",
                "Spear of Shojin",
                "Abyssal Mask",
                "Horizon Focus",
                "Black Cleaver",
            )
        )

        assert effects.phantom_hit is not None
        assert effects.phantom_hit.stacking_autos == 5
        assert effects.phantom_hit.interval == 3
        assert effects.stacking_pen is not None
        assert effects.stacking_pen.max_pen == pytest.approx(0.30)
        assert effects.stacking_pen.average_pen(6) == pytest.approx(0.15)
        assert effects.navori_refund_percent == pytest.approx(0.15)
        assert effects.crit_damage_bonus == pytest.approx(0.30)
        assert effects.first_auto_crit is not None
        assert effects.first_auto_crit.reduced_crit_ratio == pytest.approx(0.80)
        assert effects.magic_true_crit is not None
        assert effects.magic_true_crit.health_threshold == pytest.approx(0.40)
        assert effects.ultimate_auto_buff is not None
        assert effects.ultimate_auto_buff.empowered_auto_count == 3
        assert effects.basic_amp is not None
        assert effects.basic_amp.item_name == "Hexoptics C44"
        assert effects.ability_amp_source == "Actualizer"
        assert effects.basic_amp.multiplier(is_melee=False) == pytest.approx(1.10)
        assert effects.basic_amp.multiplier(is_melee=True) == pytest.approx(1.02)
        assert effects.magic_amp == pytest.approx(1.12)
        assert effects.hypershot_amp == pytest.approx(1.10)
        assert effects.ability_amp is not None
        assert effects.ability_amp.multiplier(
            {"bonus_mana": 300.0}, include_actives=True
        ) == pytest.approx(1.165)
        assert effects.armor_reduction is not None
        assert effects.armor_reduction.average_reduction(10) == pytest.approx(0.24)
        amp_by_item = {
            effect.item_name: effect.amp_fraction(4.0, 750.0)
            for effect in effects.damage_amplifiers
        }
        assert amp_by_item == pytest.approx(
            {
                "Liandry's Torment": 0.03,
                "Riftmaker": 0.04,
                "Lord Dominik's Regards": 0.075,
                "Spear of Shojin": 0.06,
            }
        )
        assert effects.execute is not None
        assert effects.execute.threshold == pytest.approx(0.05)
        assert len(effects.conditional_notes) == 2

    @pytest.mark.parametrize(
        ("autos", "expected"),
        [(0, 0.0), (1, 0.0), (2, 0.05), (4, 0.10), (6, 0.15), (12, 0.225)],
    )
    def test_stacking_pen_cadence(self, autos: int, expected: float) -> None:
        effect = resolve_damage_effects(_build("Terminus")).stacking_pen
        assert effect is not None
        assert effect.average_pen(autos) == pytest.approx(expected)

    def test_shaped_charge_compiles_formula_and_cooldown(self) -> None:
        effects = resolve_damage_effects(_build("Bastionbreaker"))
        inputs = DamageInputs(
            champion_stats={"lethality": 20.0},
            level=18,
            is_melee=True,
            target_max_health=1000.0,
            target_current_health=1000.0,
        )

        assert len(effects.shaped_charges) == 1
        effect = effects.shaped_charges[0]
        assert effect.cooldown == 20.0
        assert effect.source.raw_damage(inputs) == 80.0

    def test_terminus_shadow_scales_with_bonus_ad_and_ap(self) -> None:
        effect = resolve_damage_effects(_build("Terminus")).per_hits[0]
        inputs = DamageInputs(
            champion_stats={"bonus_attack_damage": 100.0, "ability_power": 200.0},
            level=18,
            is_melee=True,
            target_max_health=1000.0,
            target_current_health=1000.0,
        )

        assert effect.source.raw_damage(inputs) == pytest.approx(60.0)


class TestResolveStatEffects:
    """One compiled StatBonuses answers every stat-passive question."""

    def test_empty_build_is_neutral(self) -> None:
        bonuses = resolve_stat_effects(
            [],
            bonus_mana=0.0,
            max_mana=500.0,
            bonus_health=0.0,
            base_attack_damage=100.0,
            bonus_mana_regen_percent=0.0,
            is_melee=True,
            level=18,
        )
        assert bonuses.bonus_ap == 0.0
        assert bonuses.ap_multiplier == 1.0
        assert bonuses.bonus_ad == 0.0
        assert bonuses.attack_speed_percent == 0.0
        assert bonuses.bonus_resists == 0.0
        assert bonuses.bonus_pen_percent == 0.0
        assert bonuses.basic_ability_haste == 0.0
        assert bonuses.bonus_move_speed_percent == 0.0
        assert bonuses.permanent_bonus_ap == 0.0
        assert bonuses.permanent_ap_multiplier == 1.0
        assert bonuses.permanent_bonus_ad == 0.0

    def test_combined_build_resolves_every_conversion(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_effect(monkeypatch, "Muramana", max_mana_to_ad_ratio=0.02)
        _patch_effect(monkeypatch, "Sterak's Gage", base_ad_to_bonus_ad_ratio=0.45)
        _patch_effect(monkeypatch, "Rabadon's Deathcap", ap_percent_increase=0.30)
        _patch_effect(monkeypatch, "Archangel's Staff", bonus_mana_to_ap_ratio=0.01)
        build = _build(
            "Muramana", "Sterak's Gage", "Rabadon's Deathcap", "Archangel's Staff"
        )

        bonuses = resolve_stat_effects(
            build,
            bonus_mana=600.0,
            max_mana=1500.0,
            bonus_health=0.0,
            base_attack_damage=100.0,
            bonus_mana_regen_percent=0.0,
            is_melee=False,
            level=18,
        )

        assert bonuses.bonus_ad == 30.0 + 45.0  # Muramana 2% of 1500 + Sterak's 45%
        assert bonuses.bonus_ap == 6.0  # Awe: 1% of 600 bonus mana
        assert bonuses.ap_multiplier == 1.30
        assert bonuses.permanent_bonus_ap == 6.0
        assert bonuses.permanent_ap_multiplier == 1.30
        assert bonuses.permanent_bonus_ad == 75.0

    def test_temporary_combat_ap_is_not_permanent_item_ap(self) -> None:
        build = _build("Blackfire Torch", "Staff of Flowing Water")
        bonuses = resolve_stat_effects(
            build,
            bonus_mana=0.0,
            max_mana=500.0,
            bonus_health=0.0,
            base_attack_damage=100.0,
            bonus_mana_regen_percent=0.0,
            is_melee=False,
            level=18,
        )

        assert bonuses.ap_multiplier == pytest.approx(1.04)
        assert bonuses.permanent_ap_multiplier == 1.0
        assert bonuses.bonus_ap == 40.0
        assert bonuses.permanent_bonus_ap == 0.0


class TestApMultiplier:
    """Rabadon's / Blackfire Torch additive %AP increase."""

    def test_no_items_returns_1(self) -> None:
        assert _ap_multiplier([]) == 1.0

    def test_rabadons(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_effect(monkeypatch, "Rabadon's Deathcap", ap_percent_increase=0.30)
        assert _ap_multiplier(_build("Rabadon's Deathcap")) == 1.30

    def test_stacks_additively(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 30% + 4% = 34%, NOT 1.30 x 1.04
        _patch_effect(monkeypatch, "Rabadon's Deathcap", ap_percent_increase=0.30)
        _patch_effect(monkeypatch, "Blackfire Torch", ap_amp_per_target=0.04)
        build = _build("Rabadon's Deathcap", "Blackfire Torch")
        assert abs(_ap_multiplier(build) - 1.34) < 1e-9


class TestManaToApBonus:
    """Awe passives: Archangel's Staff and Seraph's Embrace."""

    def test_absent_returns_zero(self) -> None:
        assert _mana_to_ap_bonus(_build("Liandry's Torment"), 1000) == 0.0

    def test_archangels(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_effect(monkeypatch, "Archangel's Staff", bonus_mana_to_ap_ratio=0.01)
        assert _mana_to_ap_bonus(_build("Archangel's Staff"), 600) == 6.0

    def test_both_awe_items_sum(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_effect(monkeypatch, "Archangel's Staff", bonus_mana_to_ap_ratio=0.01)
        _patch_effect(monkeypatch, "Seraph's Embrace", bonus_mana_to_ap_ratio=0.02)
        build = _build("Archangel's Staff", "Seraph's Embrace")
        assert _mana_to_ap_bonus(build, 1000) == 30.0


class TestDawncoreBonusAp:
    def test_absent_returns_zero(self) -> None:
        assert _dawncore_bonus_ap([], 150.0) == 0.0

    def test_ap_per_regen_unit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_effect(
            monkeypatch,
            "Dawncore",
            ap_per_mana_regen_unit=10.0,
            mana_regen_threshold_percent=100.0,
        )
        assert _dawncore_bonus_ap(_build("Dawncore"), 150.0) == 15.0


class TestFlowingWaterBonusAp:
    def test_absent_returns_zero(self) -> None:
        assert _flowing_water_bonus_ap([]) == 0.0

    def test_reads_registry_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_effect(monkeypatch, "Staff of Flowing Water", rapids_bonus_ap=40.0)
        assert _flowing_water_bonus_ap(_build("Staff of Flowing Water")) == 40.0


class TestPassiveAttackSpeedBonus:
    def test_no_items_returns_zero(self) -> None:
        assert _passive_attack_speed_bonus([], is_melee=False) == 0.0

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
        assert _passive_attack_speed_bonus(build, is_melee=True) == 30.0
        assert _passive_attack_speed_bonus(build, is_melee=False) == 20.0

    def test_hexplate_and_yun_tal_sum(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_effect(
            monkeypatch,
            "Experimental Hexplate",
            bonus_attack_speed_melee=50.0,
            bonus_attack_speed_ranged=35.0,
        )
        _patch_effect(
            monkeypatch, "Yun Tal Wildarrows", bonus_attack_speed_percent=30.0
        )
        build = _build("Experimental Hexplate", "Yun Tal Wildarrows")
        assert _passive_attack_speed_bonus(build, is_melee=True) == 80.0
        assert _passive_attack_speed_bonus(build, is_melee=False) == 65.0


class TestBonusAdConversions:
    """Muramana, Overlord's Bloodmail, and Sterak's Gage AD conversions."""

    def test_muramana(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_effect(monkeypatch, "Muramana", max_mana_to_ad_ratio=0.02)
        assert _muramana_bonus_ad(_build("Muramana"), 1500) == 30.0

    def test_muramana_absent(self) -> None:
        assert _muramana_bonus_ad([], 1500) == 0.0

    def test_bloodmail(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_effect(
            monkeypatch, "Overlord's Bloodmail", bonus_health_to_ad_ratio=0.025
        )
        assert bloodmail_bonus_ad(_build("Overlord's Bloodmail"), 400) == 10.0

    def test_steraks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_effect(monkeypatch, "Sterak's Gage", base_ad_to_bonus_ad_ratio=0.45)
        assert steraks_bonus_ad(_build("Sterak's Gage"), 100) == 45.0


class TestTerminusMaxStackBonuses:
    def test_absent_returns_zeros(self) -> None:
        assert _terminus_max_stack_bonuses([], 18) == (0.0, 0.0)

    def test_level_18_max_stacks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_effect(
            monkeypatch,
            "Terminus",
            dark_max_stacks=3,
            dark_pen_per_stack=0.10,
            light_resist_min=6.0,
            light_resist_max=8.0,
        )
        resist, pen = _terminus_max_stack_bonuses(_build("Terminus"), 18)
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
        resist, _ = _terminus_max_stack_bonuses(_build("Terminus"), 1)
        assert resist == 18.0  # 6 per stack at level 1 x 3 stacks


class TestBasicAbilityHaste:
    def test_absent_returns_zero(self) -> None:
        assert _basic_ability_haste([]) == 0.0

    def test_shojin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_effect(monkeypatch, "Spear of Shojin", basic_ability_haste=25.0)
        assert _basic_ability_haste(_build("Spear of Shojin")) == 25.0


class TestMissingKeyFailsLoudly:
    """A missing effect key is a parser/defaults bug — never a silent default."""

    def test_keyerror_names_item_and_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        broken = dict(item_effects.ITEM_EFFECTS.get("Sterak's Gage", {}))
        broken.pop("base_ad_to_bonus_ad_ratio", None)
        monkeypatch.setitem(item_effects.ITEM_EFFECTS, "Sterak's Gage", broken)
        with pytest.raises(KeyError, match="base_ad_to_bonus_ad_ratio"):
            steraks_bonus_ad(_build("Sterak's Gage"), 100)


class TestItemEffectProvenance:
    """Static schema, parsed values, and offline fallback stay separate."""

    def test_successful_partial_parse_does_not_borrow_offline_values(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.calculator import data_fetcher, passive_parser

        monkeypatch.setattr(data_fetcher, "fetch_item_data", lambda **_kwargs: {})
        monkeypatch.setattr(
            passive_parser,
            "parse_all_item_effects",
            lambda _items: {"Lich Bane": {"base_ad_ratio": 0.75}},
        )

        registry = item_effects._build_item_effects()

        assert registry["Lich Bane"]["type"] == "spellblade"
        assert registry["Lich Bane"]["formula"] == "base_ad_ap"
        assert "ap_ratio" not in registry["Lich Bane"]
        assert "cooldown" not in registry["Lich Bane"]

        monkeypatch.setattr(item_effects, "ITEM_EFFECTS", registry)
        with pytest.raises(KeyError, match="ap_ratio"):
            resolve_damage_effects(_build("Lich Bane"))

    @pytest.mark.parametrize("failure_stage", ["load", "parse", "empty"])
    def test_whole_pipeline_failure_uses_complete_offline_snapshot(
        self,
        monkeypatch: pytest.MonkeyPatch,
        failure_stage: str,
    ) -> None:
        from src.calculator import data_fetcher, passive_parser

        if failure_stage == "load":

            def fail_load(**_kwargs):
                raise OSError("cache unavailable")

            monkeypatch.setattr(data_fetcher, "fetch_item_data", fail_load)
        else:
            monkeypatch.setattr(data_fetcher, "fetch_item_data", lambda **_kwargs: {})
            if failure_stage == "parse":

                def fail_parse(_items):
                    raise ValueError("parser unavailable")

                monkeypatch.setattr(
                    passive_parser,
                    "parse_all_item_effects",
                    fail_parse,
                )
            else:
                monkeypatch.setattr(
                    passive_parser,
                    "parse_all_item_effects",
                    lambda _items: {},
                )

        assert item_effects._build_item_effects() == item_effects._OFFLINE_ITEM_EFFECTS

    def test_every_offline_key_has_exactly_one_owner(self) -> None:
        for item_name, offline_values in item_effects._OFFLINE_ITEM_EFFECTS.items():
            static_keys = frozenset(item_effects._STATIC_ITEM_EFFECTS[item_name])
            parseable_keys = item_effects._PARSEABLE_ITEM_KEYS[item_name]
            assert static_keys.isdisjoint(parseable_keys)
            assert static_keys | parseable_keys == frozenset(offline_values)

    def test_cached_parse_matches_offline_snapshot(self) -> None:
        from src.calculator.data_fetcher import DEFAULT_DATA_DIR, fetch_item_data
        from src.calculator.passive_parser import parse_all_item_effects

        parsed = parse_all_item_effects(
            fetch_item_data(data_directory=DEFAULT_DATA_DIR)
        )
        for item_name, parseable_keys in item_effects._PARSEABLE_ITEM_KEYS.items():
            if not parseable_keys:
                continue
            assert item_name in parsed
            for key in parseable_keys:
                assert key in parsed[item_name], f"{item_name}.{key} was not parsed"
                expected = item_effects._OFFLINE_ITEM_EFFECTS[item_name][key]
                actual = parsed[item_name][key]
                if isinstance(expected, (int, float)):
                    assert actual == pytest.approx(expected), f"{item_name}.{key}"
                else:
                    assert actual == expected, f"{item_name}.{key}"

            classified = parseable_keys | frozenset(
                item_effects._STATIC_ITEM_EFFECTS[item_name]
            )
            assert frozenset(parsed[item_name]) <= classified


class TestTargetDefenseParsing:
    def test_shieldbow_lifeline_is_parser_backed(self) -> None:
        from src.calculator.data_fetcher import DEFAULT_DATA_DIR, fetch_item_data
        from src.calculator.passive_parser import parse_item_effect

        parsed = parse_item_effect(
            "Immortal Shieldbow",
            fetch_item_data(data_directory=DEFAULT_DATA_DIR),
        )

        assert parsed == {
            "health_threshold": 0.30,
            "shield_base": 400.0,
            "shield_max": 700.0,
            "shield_scale_start_level": 9,
            "shield_scale_end_level": 18,
            "duration": 3.0,
        }


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
            lambda: dict(fake_registry),
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
        monkeypatch.setattr(item_effects, "_build_item_effects", lambda: {})
        item_effects.ITEM_EFFECTS["Removed Item"] = {"type": "on_hit"}
        refresh_item_effects()
        assert "Removed Item" not in ITEM_EFFECTS


class TestActualizerAbilityDamageAmp:
    """Tests for Actualizer ability damage amplification."""

    def test_amp_no_bonus_mana(self) -> None:
        items = [{"name": "Actualizer"}]
        stats = {"bonus_mana": 0.0}
        # 15% base amp, no bonus mana
        effect = resolve_damage_effects(items).ability_amp
        assert effect is not None
        result = effect.multiplier(stats, include_actives=True)
        assert abs(result - 1.15) < 0.001

    def test_amp_with_300_bonus_mana(self) -> None:
        items = [{"name": "Actualizer"}]
        stats = {"bonus_mana": 300.0}
        # 15% + 0.5% * 3 = 16.5%
        effect = resolve_damage_effects(items).ability_amp
        assert effect is not None
        result = effect.multiplier(stats, include_actives=True)
        assert abs(result - 1.165) < 0.001

    def test_amp_disabled_when_actives_off(self) -> None:
        items = [{"name": "Actualizer"}]
        stats = {"bonus_mana": 300.0}
        effect = resolve_damage_effects(items).ability_amp
        assert effect is not None
        result = effect.multiplier(stats, include_actives=False)
        assert result == 1.0

    def test_no_actualizer(self) -> None:
        items = [{"name": "Liandry's Torment"}]
        stats = {"bonus_mana": 300.0}
        assert resolve_damage_effects(items).ability_amp is None


class TestShieldReductionFraction:
    """Serpent's Fang Shield Reaver: the fraction cut from non-magic shields."""

    def test_absent_returns_zero(self) -> None:
        assert shield_reduction_fraction([], is_melee=True) == 0.0

    def test_melee_and_ranged_sourced_values(self) -> None:
        build = _build("Serpent's Fang")
        assert shield_reduction_fraction(build, is_melee=True) == 0.50
        assert shield_reduction_fraction(build, is_melee=False) == 0.35

    def test_missing_key_names_item_and_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        broken = dict(item_effects.ITEM_EFFECTS.get("Serpent's Fang", {}))
        broken.pop("shield_reduction_melee", None)
        monkeypatch.setitem(item_effects.ITEM_EFFECTS, "Serpent's Fang", broken)
        with pytest.raises(KeyError, match="shield_reduction_melee"):
            shield_reduction_fraction(_build("Serpent's Fang"), is_melee=True)


class TestValuesSourcedFromTheCache:
    """Values the Wiki text supplies must not be rescued by static literals.

    A code-owned literal wins silently when the parser breaks, so any value
    the cache can state has to leave ``_STATIC_VALUE_KEYS_BY_ITEM`` and come
    back through ``passive_parser``.
    """

    def test_muramana_shock_ability_ratios_are_parsed(self) -> None:
        from src.calculator.data_fetcher import fetch_item_data
        from src.calculator.passive_parser import parse_item_effect

        assert "Muramana" not in item_effects._STATIC_VALUE_KEYS_BY_ITEM
        parsed = parse_item_effect("Muramana", fetch_item_data())

        assert parsed["max_mana_ratio_on_hit"] == pytest.approx(0.012)
        assert parsed["max_mana_ratio_ability_melee"] == pytest.approx(0.04)
        assert parsed["max_mana_ratio_ability_ranged"] == pytest.approx(0.03)

    def test_hexplate_overdrive_range_split_is_parsed(self) -> None:
        from src.calculator.data_fetcher import fetch_item_data
        from src.calculator.passive_parser import parse_item_effect

        assert "Experimental Hexplate" not in item_effects._STATIC_VALUE_KEYS_BY_ITEM
        parsed = parse_item_effect("Experimental Hexplate", fetch_item_data())

        assert parsed["bonus_attack_speed_melee"] == 50.0
        assert parsed["bonus_attack_speed_ranged"] == 35.0

    def test_refresh_keeps_both_range_values(self) -> None:
        """A refresh must not collapse a split back onto one number."""
        refresh_item_effects()
        hexplate = ITEM_EFFECTS["Experimental Hexplate"]

        assert hexplate["bonus_attack_speed_melee"] == 50.0
        assert hexplate["bonus_attack_speed_ranged"] == 35.0
        assert "bonus_attack_speed_percent" not in hexplate


class TestThornsEffects:
    """Bramble Vest's Thorns: the reactive packet the coupled timeline reads."""

    def test_bramble_compiles_sourced_reactive_values(self) -> None:
        (thorns,) = item_effects.thorns_effects(_build("Bramble Vest"))
        assert thorns.item_name == "Bramble Vest"
        assert thorns.damage == 10.0
        assert thorns.damage_type == "magic"
        assert thorns.grievous_duration == 3.0

    def test_builds_without_thorns_items_compile_empty(self) -> None:
        assert item_effects.thorns_effects(_build("Wit's End")) == ()

    def test_missing_key_names_item_and_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        broken = dict(item_effects.ITEM_EFFECTS.get("Bramble Vest", {}))
        broken.pop("base", None)
        monkeypatch.setitem(item_effects.ITEM_EFFECTS, "Bramble Vest", broken)
        with pytest.raises(KeyError, match="Bramble Vest.*base"):
            item_effects.thorns_effects(_build("Bramble Vest"))
