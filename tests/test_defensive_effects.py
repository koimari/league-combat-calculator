"""Sourced target-defense formulas resolved before the fight engine runs."""

import pytest

from src.calculator.defensive_effects import resolve_starting_defenses


def _stats(**overrides):
    stats = {
        "health": 2000.0,
        "bonus_health": 0.0,
        "bonus_attack_damage": 0.0,
        "max_mana": 0.0,
        "is_melee": False,
    }
    stats.update(overrides)
    return stats


@pytest.mark.parametrize(
    ("level", "is_melee", "expected"),
    [
        (1, True, 110.0),
        (18, True, 280.0),
        (1, False, 82.5),
        (18, False, 210.0),
    ],
)
def test_hexdrinker_lifeline_scales_by_level_and_range_type(level, is_melee, expected):
    defenses = resolve_starting_defenses(
        "Kai'Sa",
        level,
        _stats(is_melee=is_melee),
        [{"name": "Hexdrinker"}],
    )

    assert defenses.threshold_shield_amount == pytest.approx(expected)
    assert defenses.threshold_shield_damage_type == "magic"
    assert defenses.threshold_shield_duration == 2.5


@pytest.mark.parametrize(
    ("is_melee", "expected"),
    [(True, 290.0), (False, 217.5)],
)
def test_maw_lifeline_scales_from_bonus_ad_and_range_type(is_melee, expected):
    defenses = resolve_starting_defenses(
        "Aatrox",
        18,
        _stats(is_melee=is_melee, bonus_attack_damage=60.0),
        [{"name": "Maw of Malmortius"}],
    )

    assert defenses.threshold_shield_amount == pytest.approx(expected)
    assert defenses.threshold_shield_damage_type == "magic"
    assert defenses.threshold_shield_duration == 3.0


@pytest.mark.parametrize(
    ("level", "expected"),
    [(1, 400.0), (8, 400.0), (9, 430.0), (18, 700.0)],
)
def test_shieldbow_lifeline_is_a_level_scaled_general_shield(level, expected):
    defenses = resolve_starting_defenses(
        "Kai'Sa",
        level,
        _stats(),
        [{"name": "Immortal Shieldbow"}],
    )

    assert defenses.threshold_shield_amount == pytest.approx(expected)
    assert defenses.threshold_shield_damage_type == "all"
    assert defenses.threshold_shield_duration == 3.0


def test_lifeline_missing_damage_type_fails_closed(monkeypatch):
    from src.calculator import item_effects

    broken = dict(item_effects.ITEM_EFFECTS["Immortal Shieldbow"])
    broken.pop("damage_type", None)
    monkeypatch.setitem(item_effects.ITEM_EFFECTS, "Immortal Shieldbow", broken)

    with pytest.raises(KeyError, match="Immortal Shieldbow.*damage_type"):
        resolve_starting_defenses(
            "Kai'Sa", 18, _stats(), [{"name": "Immortal Shieldbow"}]
        )


def test_seraph_lifeline_scales_from_maximum_mana():
    defenses = resolve_starting_defenses(
        "Orianna",
        18,
        _stats(max_mana=2500.0),
        [{"name": "Seraph's Embrace"}],
    )

    assert defenses.threshold_shield_amount == pytest.approx(450.0)
    assert defenses.threshold_shield_damage_type == "all"


def test_sterak_lifeline_scales_from_bonus_health_and_spirit_visage():
    defenses = resolve_starting_defenses(
        "Aatrox",
        18,
        _stats(is_melee=True, bonus_health=500.0),
        [{"name": "Sterak's Gage"}, {"name": "Spirit Visage"}],
    )

    assert defenses.threshold_shield_amount == pytest.approx(375.0)
    assert defenses.threshold_shield_duration == 4.5
    assert any(
        "increases every modeled shield" in note for note in defenses.assumptions
    )


def test_lifeline_summary_carries_revision_backed_source():
    defenses = resolve_starting_defenses(
        "Kai'Sa", 18, _stats(), [{"name": "Hexdrinker"}]
    )

    summary = defenses.public_summary()
    assert summary["threshold_shield"] == {
        "amount": 210.0,
        "health_ratio": 0.3,
        "duration": 2.5,
        "damage_type": "magic",
    }
    assert summary["sources"][0]["revision_id"] == 3905721


def test_protoplasm_resolves_level_health_and_bonus_resist_healing():
    defenses = resolve_starting_defenses(
        "Shen",
        7,
        _stats(bonus_armor=20.0, bonus_magic_resistance=30.0),
        [{"name": "Protoplasm Harness"}],
    )

    assert defenses.threshold_health_bonus == pytest.approx(170.588235)
    assert defenses.threshold_health_heal == pytest.approx(293.382353)
    assert defenses.threshold_health_ratio == 0.30
    assert defenses.threshold_health_duration == 5.0
    assert defenses.threshold_shield_amount == 0.0
    summary = defenses.public_summary()
    assert summary["threshold_health"] == {
        "bonus_health": 170.6,
        "healing": 293.4,
        "health_ratio": 0.3,
        "duration": 5.0,
    }
    assert summary["sources"][0]["revision_id"] == 4046863


@pytest.mark.parametrize(
    ("item", "damage_type"),
    [("Armored Advance", "physical"), ("Chainlaced Crushers", "magic")],
)
def test_noxian_boots_resolve_sourced_reactive_shield(item, damage_type):
    defenses = resolve_starting_defenses(
        "Ahri", 18, _stats(bonus_health=500.0), [{"name": item}]
    )

    assert defenses.reactive_shield_amount == pytest.approx(240.0)
    assert defenses.reactive_shield_damage_type == damage_type
    assert defenses.reactive_shield_duration == 5.0
    assert defenses.reactive_shield_cooldown == 15.0
    assert defenses.sources[0].revision_id in {4013702, 4013705}


def test_celestial_opposition_resolves_blessed_reduction():
    defenses = resolve_starting_defenses(
        "Ahri", 18, _stats(), [{"name": "Celestial Opposition"}]
    )

    assert defenses.incoming_damage_multiplier == pytest.approx(0.65)
    assert defenses.incoming_damage_linger == 2.0
    assert defenses.incoming_damage_cooldown == 20.0
    assert defenses.public_summary()["incoming_damage"]["source"] == (
        "Celestial Opposition — Blessed"
    )


def test_bloodthirster_starting_shield_requires_explicit_bounded_state():
    empty = resolve_starting_defenses("Ahri", 18, _stats(), [{"name": "Bloodthirster"}])
    supplied = resolve_starting_defenses(
        "Ahri",
        18,
        _stats(),
        [{"name": "Bloodthirster"}],
        item_options={"Bloodthirster": {"starting_ichorshield": 315}},
    )

    assert empty.general_shield == 0.0
    assert supplied.general_shield == 315.0


def test_spirit_visage_increases_protoplasm_healing_not_temporary_health():
    defenses = resolve_starting_defenses(
        "Shen",
        18,
        _stats(bonus_armor=20.0, bonus_magic_resistance=30.0),
        [{"name": "Protoplasm Harness"}, {"name": "Spirit Visage"}],
    )

    assert defenses.threshold_health_bonus == 300.0
    assert defenses.threshold_health_heal == pytest.approx(609.375)
    assert defenses.healing_received_multiplier == pytest.approx(1.25)


def test_spirit_visage_exposes_received_healing_multiplier_without_a_starting_shield():
    defenses = resolve_starting_defenses(
        "Aatrox",
        18,
        _stats(),
        [{"name": "Spirit Visage"}],
    )

    assert defenses.healing_received_multiplier == pytest.approx(1.25)
    assert any("all modeled healing received" in note for note in defenses.assumptions)


def test_guardian_angel_resolves_sourced_base_health_rebirth():
    defenses = resolve_starting_defenses(
        "Aatrox",
        18,
        _stats(base_health=1800.0),
        [{"name": "Guardian Angel"}],
    )

    assert defenses.revive_health_amount == pytest.approx(900.0)
    assert defenses.revive_delay == pytest.approx(4.0)
    assert defenses.revive_cooldown == pytest.approx(300.0)
    assert defenses.public_summary()["revive"] == {
        "health_amount": 900.0,
        "delay": 4.0,
        "cooldown": 300.0,
    }


@pytest.mark.parametrize(("is_melee", "fraction"), [(True, 0.30), (False, 0.10)])
def test_deaths_dance_resolves_ordered_ignore_pain_and_defy(is_melee, fraction):
    defenses = resolve_starting_defenses(
        "Aatrox",
        18,
        _stats(is_melee=is_melee, bonus_attack_damage=200.0),
        [{"name": "Death's Dance"}],
    )

    assert defenses.damage_deferral_fraction == pytest.approx(fraction)
    assert defenses.damage_deferral_duration == pytest.approx(3.0)
    assert defenses.damage_deferral_ticks == 3
    assert defenses.defy_window == pytest.approx(3.0)
    assert defenses.defy_heal_bonus_ad_ratio == pytest.approx(0.75)
    assert defenses.defy_heal_duration == pytest.approx(2.0)
    assert defenses.defy_heal_ticks == 2


def test_level_scaled_defenses_cap_at_level_eighteen():
    defenses = resolve_starting_defenses(
        "Shen",
        20,
        _stats(),
        [{"name": "Protoplasm Harness"}],
    )

    assert defenses.threshold_health_bonus == 300.0
    assert defenses.threshold_health_heal == 400.0


@pytest.mark.parametrize(
    "item_name",
    ["Banshee's Veil", "Edge of Night", "Verdant Barrier"],
)
def test_annul_is_ready_as_an_opening_spell_shield(item_name):
    defenses = resolve_starting_defenses("Ahri", 18, _stats(), [{"name": item_name}])

    assert defenses.spell_shield_ready is True
    assert defenses.spell_shield_source == f"{item_name} — Annul"
    summary = defenses.public_summary()
    assert summary["spell_shield"] == {
        "ready": True,
        "source": f"{item_name} — Annul",
    }
