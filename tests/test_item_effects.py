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
    ap_multiplier,
    basic_ability_haste,
    _basic_ability_haste,
    bloodmail_bonus_ad,
    bloodmail_retribution_bonus_ad,
    _dawncore_bonus_ap,
    _flowing_water_bonus_ap,
    _mana_to_ap_bonus,
    mana_to_health_bonus,
    _muramana_bonus_ad,
    _passive_attack_speed_bonus,
    guinsoo_attack_speed_percent,
    guinsoo_swing_schedule,
    energized_proc_indices,
    energized_schedule_receipt,
    hydra_cleave_secondary_ad_damage,
    hydra_secondary_target_damage,
    item_bonus_health_multiplier,
    dawncore_bonus_ap,
    flowing_water_bonus_ap,
    mana_to_ap_bonus,
    muramana_bonus_ad,
    passive_attack_speed_bonus,
    permanent_ap_multiplier,
    runaan_secondary_target_count,
    runaan_secondary_target_damage,
    riftmaker_bonus_ap,
    riftmaker_max_stack_omnivamp,
    hubris_eminence_bonus_ad,
    axiom_arc_ultimate_refund_fraction,
    essence_reaver_mana_restore_per_proc,
    yun_tal_permanent_crit_chance,
    statikk_chain_target_bounds,
    statikk_chain_target_count,
    steraks_bonus_ad,
    terminus_max_stack_bonuses,
    _terminus_max_stack_bonuses,
    refresh_item_effects,
    resolve_damage_effects,
    resolve_stat_effects,
    item_input_options_meta,
    input_option_retribution_bonus_ad,
    input_option_crit_chance,
    hubris_input_bonus_ad,
    endless_hunger_input_omnivamp,
    actualizer_active_seconds,
    item_state_receipts,
    validate_item_input_options,
    shield_reduction_fraction,
    required_effect_value,
    ally_item_effect_value,
)


def _build(*names: str) -> list[dict]:
    """Make a minimal item build from item names."""
    return [{"name": name} for name in names]


def test_frozen_heart_registers_typed_attack_speed_aura() -> None:
    assert required_effect_value(
        "Frozen Heart", "attack_speed_reduction"
    ) == pytest.approx(0.20)
    assert required_effect_value("Frozen Heart", "range_units") == pytest.approx(700.0)
    # Target-only effects are still valid registry entries when an item is
    # present in an ordinary attacker build; they simply contribute no damage.
    assert resolve_damage_effects(_build("Frozen Heart")).per_hits == ()


def test_redemption_area_damage_receipt_values_are_typed() -> None:
    assert ally_item_effect_value("Redemption", "beam_delay") == pytest.approx(2.5)
    assert ally_item_effect_value(
        "Redemption", "target_area_range_units"
    ) == pytest.approx(5500.0)
    assert ally_item_effect_value(
        "Redemption", "enemy_max_health_true_damage_ratio"
    ) == pytest.approx(0.10)


def _patch_effect(monkeypatch: pytest.MonkeyPatch, item_name: str, **overrides) -> None:
    """Override keys on one registry entry for the duration of a test."""
    patched = dict(item_effects.ITEM_EFFECTS.get(item_name, {}))
    patched.update(overrides)
    monkeypatch.setitem(item_effects.ITEM_EFFECTS, item_name, patched)


def test_stateful_health_and_time_inputs_are_typed_and_sourced() -> None:
    parsed = validate_item_input_options(
        {
            "Heartsteel": {"bonus_health": 500},
            "Rod of Ages": {"timeless_stacks": 10},
        }
    )
    assert parsed == {
        "Heartsteel": {"bonus_health": 500},
        "Rod of Ages": {"timeless_stacks": 10},
    }
    metadata = item_input_options_meta()
    assert metadata["Heartsteel"]["options"]["bonus_health"]["max"] == 10000
    assert metadata["Rod of Ages"]["options"]["timeless_stacks"]["max"] == 10
    assert metadata["Yun Tal Wildarrows"]["options"]["crit_stacks"]["max"] == 125


def test_cp13_item_state_controls_are_bounded_and_typed() -> None:
    parsed = validate_item_input_options(
        {
            "Actualizer": {"mana_made_real_active": 1},
            "Hubris": {"eminence_stacks": 12, "eminence_active_seconds": 45},
            "Endless Hunger": {"feast_active_seconds": 8},
            "Manamune": {"manaflow_bonus_mana": 360},
        }
    )
    assert parsed["Hubris"]["eminence_stacks"] == 12
    assert parsed["Manamune"]["manaflow_bonus_mana"] == 360
    with pytest.raises(ValueError, match="eminence_active_seconds"):
        validate_item_input_options(
            {"Hubris": {"eminence_stacks": 1, "eminence_active_seconds": 91}}
        )


def test_lord_dominik_amp_receives_holder_context_and_uses_target_bonus_health() -> (
    None
):
    """Giant Slayer receives its current holder and prices target bonus HP."""
    amp = item_effects.lord_dominik_damage_amp_fraction(
        attacker_stats={"bonus_health": 500.0},
        target_bonus_health=750.0,
        maximum=0.15,
        bonus_hp_cap=1500.0,
    )
    same_target_different_holder = item_effects.lord_dominik_damage_amp_fraction(
        attacker_stats={"bonus_health": 1500.0},
        target_bonus_health=750.0,
        maximum=0.15,
        bonus_hp_cap=1500.0,
    )
    assert amp == pytest.approx(0.075)
    assert same_target_different_holder == pytest.approx(amp)
    assert item_effects.lord_dominik_damage_amp_fraction(
        attacker_stats={},
        target_bonus_health=2000.0,
        maximum=0.15,
        bonus_hp_cap=1500.0,
    ) == pytest.approx(0.15)


def test_actualizer_active_window_is_explicit_and_boundary_clipped() -> None:
    items = _build("Actualizer")
    assert actualizer_active_seconds(
        items,
        {"Actualizer": {"mana_made_real_active_seconds": 8.0}},
        fight_duration_seconds=12.0,
    ) == pytest.approx(8.0)
    assert actualizer_active_seconds(
        items,
        {"Actualizer": {"mana_made_real_active_seconds": 0.0}},
        fight_duration_seconds=12.0,
    ) == pytest.approx(0.0)
    assert actualizer_active_seconds(
        items,
        {"Actualizer": {"mana_made_real_active": 1}},
        fight_duration_seconds=4.0,
    ) == pytest.approx(4.0)


def test_cp13_state_receipt_contains_all_conversion_and_timed_boundaries() -> None:
    items = _build(
        "Actualizer",
        "Riftmaker",
        "Overlord's Bloodmail",
        "Heartsteel",
        "Archangel's Staff",
        "Rod of Ages",
        "Hubris",
        "Axiom Arc",
        "Endless Hunger",
        "Swiftmarch",
        "Yun Tal Wildarrows",
        "The Collector",
    )
    receipts = item_state_receipts(
        items,
        {
            "Actualizer": {"mana_made_real_active_seconds": 8.0},
            "Heartsteel": {"bonus_health": 500},
            "Archangel's Staff": {"manaflow_bonus_mana": 360},
            "Rod of Ages": {"timeless_stacks": 10},
            "Hubris": {"eminence_stacks": 4, "eminence_active_seconds": 30},
            "Endless Hunger": {"feast_active_seconds": 8},
            "Yun Tal Wildarrows": {"crit_stacks": 12},
        },
        fight_duration_seconds=12.0,
        is_melee=True,
        bonus_health=400.0,
        bonus_mana=600.0,
        max_mana=1200.0,
        total_attack_damage=200.0,
        total_move_speed=400.0,
        lethality=20.0,
    )
    by_item = {entry["item"]: entry for entry in receipts}
    assert by_item["Actualizer"]["active_until"] == pytest.approx(8.0)
    assert by_item["Riftmaker"]["omnivamp_percent"] == pytest.approx(10.0)
    assert by_item["Archangel's Staff"]["transformed"] is True
    assert by_item["Rod of Ages"]["level_gain"] is True
    assert by_item["Hubris"]["bonus_ad"] == pytest.approx(24.0)
    assert by_item["Endless Hunger"]["omnivamp"] == pytest.approx(15.0)
    assert by_item["The Collector"]["feeds_takedown_state"] is True


def test_cp16_stasis_seconds_is_a_bounded_float_state() -> None:
    parsed = validate_item_input_options(
        {"Zhonya's Hourglass": {"stasis_active_seconds": 2.5}}
    )
    assert parsed == {"Zhonya's Hourglass": {"stasis_active_seconds": 2.5}}
    with pytest.raises(ValueError, match="stasis_active_seconds"):
        validate_item_input_options(
            {"Zhonya's Hourglass": {"stasis_active_seconds": 3.0}}
        )


def test_cp13_takedown_states_read_typed_registry_values() -> None:
    assert hubris_input_bonus_ad(
        _build("Hubris"),
        {"Hubris": {"eminence_stacks": 4, "eminence_active_seconds": 30}},
    ) == pytest.approx(24.0)
    assert hubris_input_bonus_ad(
        _build("Hubris"),
        {"Hubris": {"eminence_stacks": 4, "eminence_active_seconds": 0}},
    ) == pytest.approx(0.0)
    assert endless_hunger_input_omnivamp(
        _build("Endless Hunger"),
        {"Endless Hunger": {"feast_active_seconds": 8}},
    ) == pytest.approx(15.0)


def test_yun_tal_crit_state_is_typed_and_melee_ranged_capped() -> None:
    assert validate_item_input_options({"Yun Tal Wildarrows": {"crit_stacks": 12}}) == {
        "Yun Tal Wildarrows": {"crit_stacks": 12}
    }
    assert input_option_crit_chance(
        _build("Yun Tal Wildarrows"),
        {"Yun Tal Wildarrows": {"crit_stacks": 12}},
        is_melee=True,
    ) == pytest.approx(4.8)
    assert input_option_crit_chance(
        _build("Yun Tal Wildarrows"),
        {"Yun Tal Wildarrows": {"crit_stacks": 125}},
        is_melee=True,
    ) == pytest.approx(25.0)
    assert input_option_crit_chance(
        _build("Yun Tal Wildarrows"),
        {"Yun Tal Wildarrows": {"crit_stacks": 125}},
        is_melee=False,
    ) == pytest.approx(25.0)


@pytest.mark.parametrize(
    "value",
    [
        {"Heartsteel": {"bonus_health": -1}},
        {"Rod of Ages": {"timeless_stacks": 11}},
        {"Rod of Ages": {"timeless_stacks": True}},
        {"Yun Tal Wildarrows": {"crit_stacks": -1}},
        {"Yun Tal Wildarrows": {"crit_stacks": 126}},
        {"Yun Tal Wildarrows": {"crit_stacks": True}},
    ],
)
def test_stateful_item_inputs_fail_closed(value: dict) -> None:
    with pytest.raises(ValueError):
        validate_item_input_options(value)


def test_bloodmail_starting_missing_health_is_typed() -> None:
    assert validate_item_input_options(
        {"Overlord's Bloodmail": {"missing_health_percent": 35}}
    ) == {"Overlord's Bloodmail": {"missing_health_percent": 35}}
    metadata = item_input_options_meta()
    assert (
        metadata["Overlord's Bloodmail"]["options"]["missing_health_percent"]["max"]
        == 70
    )


def test_bloodmail_starting_missing_health_reads_registry_state() -> None:
    items = _build("Overlord's Bloodmail")
    assert input_option_retribution_bonus_ad(
        items,
        {"Overlord's Bloodmail": {"missing_health_percent": 50}},
        total_attack_damage=200.0,
    ) == pytest.approx(70.0)


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

    def test_missing_ultimate_proc_mr_reduction_names_item_and_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        broken = dict(ITEM_EFFECTS["Malignance"])
        broken.pop("mr_reduction")
        monkeypatch.setitem(ITEM_EFFECTS, "Malignance", broken)

        with pytest.raises(KeyError, match="Malignance.*mr_reduction"):
            resolve_damage_effects(_build("Malignance"))

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

    def test_cull_compiles_its_sourced_on_hit_health_receipt(self) -> None:
        effects = resolve_damage_effects(_build("Cull"))

        assert len(effects.on_hit_heals) == 1
        assert effects.on_hit_heals[0].item_name == "Cull"
        assert effects.on_hit_heals[0].amount == pytest.approx(3.0)

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
        assert effects.spellblade.bonus_attack_speed_percent == 50.0

    def test_spellblade_sibling_values_are_typed(self) -> None:
        essence = resolve_damage_effects(_build("Essence Reaver")).spellblade
        dusk = resolve_damage_effects(_build("Dusk and Dawn")).spellblade
        assert essence is not None and dusk is not None
        assert essence.mana_restore_base_ad_ratio == pytest.approx(0.625)
        assert essence.mana_restore_crit_ratio == pytest.approx(25.0)
        assert dusk.self_heal_ap_ratio == pytest.approx(0.10)
        assert dusk.self_heal_bonus_health_ratio == pytest.approx(0.03)

    @pytest.mark.parametrize(
        ("item_name", "key"),
        [
            ("Bloodsong", "expose_weakness_melee"),
            ("Dusk and Dawn", "self_heal_ap_ratio"),
            ("Lich Bane", "bonus_attack_speed_percent"),
            ("Essence Reaver", "mana_restore_base_ad_ratio"),
        ],
    )
    def test_missing_spellblade_sibling_names_item_and_key(
        self, monkeypatch: pytest.MonkeyPatch, item_name: str, key: str
    ) -> None:
        broken = dict(ITEM_EFFECTS[item_name])
        broken.pop(key)
        monkeypatch.setitem(ITEM_EFFECTS, item_name, broken)

        with pytest.raises(KeyError, match=f"{item_name}.*{key}"):
            resolve_damage_effects(_build(item_name))

    def test_guinsoo_seething_attack_speed_is_patch_sourced(self) -> None:
        build = _build("Guinsoo's Rageblade")
        assert guinsoo_attack_speed_percent(build, 0) == 0.0
        assert guinsoo_attack_speed_percent(build, 1) == pytest.approx(8.0)
        assert guinsoo_attack_speed_percent(build, 4) == pytest.approx(32.0)
        assert guinsoo_attack_speed_percent(build, 99) == pytest.approx(32.0)

    def test_guinsoo_schedule_accelerates_after_stacks(self) -> None:
        build = _build("Guinsoo's Rageblade")
        times = guinsoo_swing_schedule(
            build,
            attack_speed=1.0,
            attack_speed_ratio=1.0,
            duration_seconds=5.0,
        )
        assert times[0] == 0.0
        assert len(times) > 5
        # First interval has no Seething bonus; later intervals are shorter.
        assert times[1] < 1.0
        assert times[2] - times[1] < times[1] - times[0]

    def test_guinsoo_schedule_does_not_accumulate_stale_stacks(self) -> None:
        build = _build("Guinsoo's Rageblade")
        times = guinsoo_swing_schedule(
            build,
            attack_speed=0.2,
            attack_speed_ratio=1.0,
            duration_seconds=12.0,
        )
        # At this slow rate each prior stack expires before the next hit, so
        # the schedule stays at one live stack rather than falsely reaching
        # the 32% cap from stale state.
        assert times[-1] - times[-2] == pytest.approx(3.57142857)

    def test_yun_tal_flurry_starts_after_first_attack(self) -> None:
        build = _build("Yun Tal Wildarrows")
        times = guinsoo_swing_schedule(
            build,
            attack_speed=1.0,
            attack_speed_ratio=1.0,
            duration_seconds=3.0,
        )
        assert times[0] == 0.0
        assert times[1] == pytest.approx(1.0)
        assert times[2] - times[1] < 1.0

    def test_yun_tal_flurry_uses_parser_owned_values(self, monkeypatch) -> None:
        _patch_effect(
            monkeypatch,
            "Yun Tal Wildarrows",
            bonus_attack_speed_percent=60.0,
            duration=2.0,
            cooldown=30.0,
            attack_refund_base=1.0,
            attack_refund_crit=2.0,
        )
        times = guinsoo_swing_schedule(
            _build("Yun Tal Wildarrows"),
            attack_speed=1.0,
            attack_speed_ratio=1.0,
            duration_seconds=3.0,
        )
        assert times[2] - times[1] == pytest.approx(1.0 / 1.6)

    def test_statikk_energized_attack_schedule_uses_sourced_15_stacks(self) -> None:
        assert energized_proc_indices("Statikk Shiv", 20, initial_stacks=0) == (
            7,
            14,
        )
        assert energized_proc_indices("Statikk Shiv", 3, initial_stacks=100) == (0,)

    def test_statikk_missing_attack_gain_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        broken = dict(ITEM_EFFECTS["Statikk Shiv"])
        broken.pop("energized_attack_stacks")
        monkeypatch.setitem(ITEM_EFFECTS, "Statikk Shiv", broken)

        with pytest.raises(KeyError, match="Statikk Shiv.*energized_attack_stacks"):
            energized_proc_indices("Statikk Shiv", 3, initial_stacks=100)

    def test_statikk_chain_target_bounds_are_parser_owned(self) -> None:
        assert statikk_chain_target_bounds() == (4, 8)

    def test_statikk_chain_target_count_uses_sourced_level_breakpoints(self) -> None:
        assert [statikk_chain_target_count(level) for level in (1, 6, 10, 14, 20)] == [
            4,
            5,
            6,
            7,
            8,
        ]

    def test_statikk_chain_target_bounds_fail_closed_when_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        broken = dict(ITEM_EFFECTS["Statikk Shiv"])
        broken.pop("chain_targets_max")
        monkeypatch.setitem(ITEM_EFFECTS, "Statikk Shiv", broken)

        with pytest.raises(KeyError, match="chain_targets_max"):
            statikk_chain_target_bounds()

    def test_riftmaker_bonus_health_conversion_uses_sourced_ratio(self) -> None:
        assert riftmaker_bonus_ap(bonus_health=500) == pytest.approx(10)

    def test_riftmaker_conversion_fails_closed_when_ratio_is_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        broken = dict(ITEM_EFFECTS["Riftmaker"])
        broken.pop("bonus_health_to_ap_ratio")
        monkeypatch.setitem(ITEM_EFFECTS, "Riftmaker", broken)

        with pytest.raises(KeyError, match="bonus_health_to_ap_ratio"):
            riftmaker_bonus_ap(bonus_health=500)

    def test_riftmaker_max_stack_omnivamp_uses_four_second_boundary(self) -> None:
        assert riftmaker_max_stack_omnivamp(fight_duration_seconds=3.99) == 0.0
        assert riftmaker_max_stack_omnivamp(
            fight_duration_seconds=4.0
        ) == pytest.approx(10.0)
        assert riftmaker_max_stack_omnivamp(
            fight_duration_seconds=4.0, is_melee=False
        ) == pytest.approx(6.0)

    def test_riftmaker_max_stack_omnivamp_fails_closed_when_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        broken = dict(ITEM_EFFECTS["Riftmaker"])
        broken.pop("max_stack_omnivamp")
        monkeypatch.setitem(ITEM_EFFECTS, "Riftmaker", broken)

        with pytest.raises(KeyError, match="max_stack_omnivamp"):
            riftmaker_max_stack_omnivamp(fight_duration_seconds=5.0)

    def test_hubris_eminence_uses_sourced_base_and_stack_ad(self) -> None:
        assert hubris_eminence_bonus_ad(stacks=4) == pytest.approx(24)
        assert hubris_eminence_bonus_ad(stacks=4, active=False) == 0

    def test_hubris_eminence_fails_closed_when_parser_value_is_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        broken = dict(ITEM_EFFECTS["Hubris"])
        broken.pop("eminence_ad_per_stack")
        monkeypatch.setitem(ITEM_EFFECTS, "Hubris", broken)

        with pytest.raises(KeyError, match="eminence_ad_per_stack"):
            hubris_eminence_bonus_ad(stacks=4)

    def test_axiom_arc_refund_uses_base_and_lethality_scaling(self) -> None:
        assert axiom_arc_ultimate_refund_fraction(lethality=20) == pytest.approx(0.15)

    def test_axiom_arc_refund_fails_closed_when_scaling_is_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        broken = dict(ITEM_EFFECTS["Axiom Arc"])
        broken.pop("ultimate_refund_per_lethality_ratio")
        monkeypatch.setitem(ITEM_EFFECTS, "Axiom Arc", broken)

        with pytest.raises(KeyError, match="ultimate_refund_per_lethality_ratio"):
            axiom_arc_ultimate_refund_fraction(lethality=20)

    def test_essence_reaver_mana_restore_uses_both_parser_ratios(self) -> None:
        assert essence_reaver_mana_restore_per_proc(
            base_attack_damage=100, critical_strike_chance=50
        ) == pytest.approx(75.0)

    def test_essence_reaver_mana_restore_clamps_crit_input(self) -> None:
        assert essence_reaver_mana_restore_per_proc(
            base_attack_damage=100, critical_strike_chance=150
        ) == pytest.approx(87.5)

    def test_yun_tal_permanent_crit_chance_uses_melee_and_ranged_caps(self) -> None:
        assert yun_tal_permanent_crit_chance(stacks=63, is_melee=True) == pytest.approx(
            0.25
        )
        assert yun_tal_permanent_crit_chance(
            stacks=100, is_melee=False
        ) == pytest.approx(0.20)

    def test_yun_tal_permanent_crit_fails_closed_when_bound_is_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        broken = dict(ITEM_EFFECTS["Yun Tal Wildarrows"])
        broken.pop("crit_stack_max_ranged")
        monkeypatch.setitem(ITEM_EFFECTS, "Yun Tal Wildarrows", broken)

        with pytest.raises(KeyError, match="crit_stack_max_ranged"):
            yun_tal_permanent_crit_chance(stacks=2, is_melee=False)

    @pytest.mark.parametrize(
        "item_name", ["Rapid Firecannon", "Stormrazor", "Voltaic Cyclosword"]
    )
    def test_energized_attack_only_schedule_is_explicit_without_movement(
        self, item_name: str
    ) -> None:
        # An omitted movement schedule is an explicit zero-distance timeline,
        # not an invented recharge or a partial result.
        assert energized_proc_indices(item_name, 10, initial_stacks=0) == ()

    def test_energized_movement_schedule_uses_shared_24_unit_source(self) -> None:
        # 10 movement intervals of 240 units plus six attack charges each
        # crosses 100 charges on the sixth attack.
        assert energized_proc_indices(
            "Rapid Firecannon",
            10,
            initial_stacks=0,
            movement_units_per_attack=[240.0] * 10,
        ) == (6,)

    def test_energized_schedule_receipt_is_shared_and_typed(self) -> None:
        receipt = energized_schedule_receipt("Rapid Firecannon")
        assert receipt["source_revision_id"] == 4013385
        assert receipt["max_stacks"] == 100
        assert receipt["attack_stacks"] == 6
        assert receipt["distance_units_per_stack"] == pytest.approx(24.0)

    def test_missing_voltaic_temporary_lethality_names_item_and_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        broken = dict(ITEM_EFFECTS["Voltaic Cyclosword"])
        broken.pop("temporary_lethality_duration")
        monkeypatch.setitem(ITEM_EFFECTS, "Voltaic Cyclosword", broken)

        with pytest.raises(
            KeyError, match="Voltaic Cyclosword.*temporary_lethality_duration"
        ):
            resolve_damage_effects(_build("Voltaic Cyclosword"))

    def test_runaan_bolt_cardinality_excludes_main_target(self) -> None:
        assert runaan_secondary_target_count(roster_target_count=1) == 0
        assert runaan_secondary_target_count(roster_target_count=2) == 1
        assert runaan_secondary_target_count(roster_target_count=4) == 2

    def test_runaan_bolt_damage_uses_parser_owned_ad_ratio(self) -> None:
        assert runaan_secondary_target_damage(total_attack_damage=200) == pytest.approx(
            110
        )

    def test_runaan_bolt_damage_fails_closed_when_ratio_is_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        broken = dict(ITEM_EFFECTS["Runaan's Hurricane"])
        broken.pop("secondary_ad_ratio")
        monkeypatch.setitem(ITEM_EFFECTS, "Runaan's Hurricane", broken)

        with pytest.raises(KeyError, match="secondary_ad_ratio"):
            runaan_secondary_target_damage(total_attack_damage=200)

    def test_titanic_secondary_packet_uses_melee_and_empowered_ratios(self) -> None:
        assert hydra_secondary_target_damage(
            max_health=3000, is_melee=True
        ) == pytest.approx(90)
        assert hydra_secondary_target_damage(
            max_health=3000, is_melee=False, empowered=True
        ) == pytest.approx(135)

    def test_hydra_cleave_secondary_packet_uses_ranged_ratio(self) -> None:
        assert hydra_cleave_secondary_ad_damage(
            total_attack_damage=250,
            is_melee=False,
            item_name="Ravenous Hydra",
        ) == pytest.approx(50)

    def test_warmogs_health_multiplier_reads_registry(self) -> None:
        assert item_bonus_health_multiplier(_build("Warmog's Armor")) == pytest.approx(
            1.12
        )
        assert item_bonus_health_multiplier([]) == 1.0

    def test_muramana_max_mana_conversion_reads_registry(self) -> None:
        assert muramana_bonus_ad(_build("Muramana"), 2500.0) == pytest.approx(50.0)

    def test_terminus_max_stack_state_reads_registry(self) -> None:
        resist, pen = terminus_max_stack_bonuses(_build("Terminus"), level=18)
        assert resist == pytest.approx(24.0)
        assert pen == pytest.approx(30.0)

    def test_awe_mana_to_ap_conversion_reads_registry(self) -> None:
        assert mana_to_ap_bonus(
            _build("Archangel's Staff", "Seraph's Embrace"), 1000.0
        ) == pytest.approx(30.0)

    def test_dawncore_mana_regen_conversion_reads_registry(self) -> None:
        assert dawncore_bonus_ap(_build("Dawncore"), 150.0) == pytest.approx(15.0)

    def test_flowing_water_rapids_conversion_reads_registry(self) -> None:
        assert flowing_water_bonus_ap(
            _build("Staff of Flowing Water")
        ) == pytest.approx(40.0)

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
        assert effects.immolates[0].event_interval == pytest.approx(1.0)
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

    def test_passive_attack_speed_bonus_uses_melee_ranged_registry_values(self) -> None:
        assert passive_attack_speed_bonus(_build("Bandlepipes"), True) == pytest.approx(
            30.0
        )
        assert passive_attack_speed_bonus(
            _build("Bandlepipes"), False
        ) == pytest.approx(20.0)

    def test_ap_multiplier_reads_registered_passive_amplifiers(self) -> None:
        assert ap_multiplier(
            _build("Rabadon's Deathcap", "Blackfire Torch")
        ) == pytest.approx(1.34)

    def test_permanent_ap_multiplier_excludes_combat_only_blackfire(self) -> None:
        assert permanent_ap_multiplier(_build("Rabadon's Deathcap")) == pytest.approx(
            1.30
        )
        assert permanent_ap_multiplier(_build("Blackfire Torch")) == pytest.approx(1.0)

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
        assert effects.ability_amp is not None
        assert effects.ability_amp.multiplier(
            {"bonus_mana": 300.0}, include_actives=True
        ) == pytest.approx(1.165)
        assert effects.armor_reduction is not None
        assert effects.armor_reduction.average_reduction(10) == pytest.approx(0.24)
        amp_by_item = {
            effect.item_name: effect.amp_fraction(4.0, 750.0, {})
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

    def test_immortal_path_slay_stacks_add_typed_omnivamp(self) -> None:
        bonuses = resolve_stat_effects(
            _build("Immortal Path"),
            bonus_mana=0.0,
            max_mana=500.0,
            bonus_health=0.0,
            base_attack_damage=100.0,
            bonus_mana_regen_percent=0.0,
            is_melee=True,
            level=18,
            item_options={"Immortal Path": {"slay_stacks": 10}},
        )
        assert bonuses.bonus_omnivamp == pytest.approx(6.0)

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


class TestManaToHealthBonus:
    """Fimbulwinter's Awe conversion is sourced and typed."""

    @pytest.mark.parametrize("item_name", ["Fimbulwinter", "Winter's Approach"])
    def test_bonus_mana_to_health(self, item_name: str) -> None:
        assert mana_to_health_bonus(_build(item_name), 1000.0) == pytest.approx(150.0)

    def test_absent_returns_zero(self) -> None:
        assert mana_to_health_bonus(_build("Liandry's Torment"), 1000.0) == 0.0

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

    def test_bloodmail_retribution_scales_from_ordered_missing_health(self) -> None:
        assert bloodmail_retribution_bonus_ad(
            total_attack_damage=200.0, missing_health_fraction=0.5
        ) == pytest.approx(70.0)

    @pytest.mark.parametrize(
        ("missing_health", "expected"), [(-0.2, 0.0), (1.5, 140.0)]
    )
    def test_bloodmail_retribution_clamps_health_state(
        self, missing_health: float, expected: float
    ) -> None:
        assert bloodmail_retribution_bonus_ad(
            total_attack_damage=200.0,
            missing_health_fraction=missing_health,
        ) == pytest.approx(expected)

    def test_steraks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_effect(monkeypatch, "Sterak's Gage", base_ad_to_bonus_ad_ratio=0.45)
        assert steraks_bonus_ad(_build("Sterak's Gage"), 100) == 45.0

    def test_basic_ability_haste_reads_spear_registry(self) -> None:
        assert basic_ability_haste(_build("Spear of Shojin")) == pytest.approx(25.0)


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

    def test_thornmail_compiles_bonus_armor_thorns(self) -> None:
        (thorns,) = item_effects.thorns_effects(_build("Thornmail"))
        assert thorns.item_name == "Thornmail"
        assert thorns.damage == 20.0
        assert thorns.bonus_armor_ratio == pytest.approx(0.10)

    def test_thornmail_missing_bonus_armor_key_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        broken = dict(item_effects.ITEM_EFFECTS["Thornmail"])
        broken.pop("bonus_armor_ratio")
        monkeypatch.setitem(item_effects.ITEM_EFFECTS, "Thornmail", broken)
        with pytest.raises(KeyError, match="Thornmail.*bonus_armor_ratio"):
            item_effects.thorns_effects(_build("Thornmail"))

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


class TestCp20ItemState:
    """The residual item family has typed state and no guessed fallbacks."""

    def test_umbral_nightstalker_formula_reads_lethality(self) -> None:
        effect = item_effects.resolve_damage_effects(_build("Umbral Glaive"))
        assert len(effect.first_autos) == 1
        source = effect.first_autos[0].source
        assert source.damage_type == "true"
        assert source.raw_damage(
            DamageInputs({"lethality": 18.0}, 18, False, 2000.0, 2000.0)
        ) == pytest.approx(77.0)

    def test_cp20_options_validate_and_apply_manaflow(self) -> None:
        options = item_effects.validate_item_input_options(
            {
                "Tear of the Goddess": {"manaflow_bonus_mana": 360},
                "Umbral Glaive": {"nightstalker_ready": 1},
                "World Atlas": {"shared_riches_gold": 400, "ward_uses": 3},
            }
        )
        assert item_effects.input_option_stat_bonuses(
            [{"name": "Tear of the Goddess"}], options
        )[3] == pytest.approx(360.0)
        assert (
            item_effects.input_option_value(
                [{"name": "Umbral Glaive"}],
                options,
                "Umbral Glaive",
                "nightstalker_ready",
            )
            == 1
        )


class TestCommandAmpEffect:
    """Imperial Mandate's Command: the holder-side amp the pair engine prices.

    The coupled walk's cross-participant packet (owner-skipped for the
    holder) is tested in test_item_support_effects.py; this accessor feeds
    the holder's own fight.
    """

    def test_imperial_mandate_compiles_sourced_command_values(self) -> None:
        effect = item_effects.command_amp_effect(_build("Imperial Mandate"))
        assert effect is not None
        assert effect.item_name == "Imperial Mandate"
        assert effect.amp_fraction == pytest.approx(0.07)
        assert effect.duration == pytest.approx(4.0)

    def test_builds_without_command_items_compile_none(self) -> None:
        assert item_effects.command_amp_effect(_build("Wit's End")) is None

    def test_missing_key_names_item_and_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        broken = dict(item_effects.ALLY_ITEM_EFFECTS["Imperial Mandate"])
        broken.pop("command_damage_amp")
        monkeypatch.setitem(item_effects.ALLY_ITEM_EFFECTS, "Imperial Mandate", broken)
        with pytest.raises(KeyError, match="Imperial Mandate.*command_damage_amp"):
            item_effects.command_amp_effect(_build("Imperial Mandate"))
