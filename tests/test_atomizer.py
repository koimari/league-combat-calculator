"""Unified Atomizer contract tests.

The atomizer is the single way to atomize anything numerical (items,
abilities, runes, economics, stats, champions) across sessions.  These
tests pin the Atom contract and the per-effect independence rule that the
old item atomizer violated (issue #140).
"""

from pathlib import Path

from src.calculator.atomizer import Atomizer, number_and_unit, split_effect_fragments
from src.calculator.atomizer_domains import (
    atomize_abilities,
    atomize_item,
    atomize_item_catalogue,
    atomize_rune_catalogue,
    atomize_stats,
)
from src.calculator.data_fetcher import fetch_champion_data, fetch_item_data

ROOT = Path(__file__).resolve().parents[1]


def _item(name):
    return next(v for v in fetch_item_data().values() if v.get("name") == name)


def _bolt_atoms() -> list[dict]:
    a = Atomizer("items", source_ref="Test")
    a.add(
        "damage.magic",
        "damage",
        "Test.passives[0]",
        "Bolt",
        values=[50.0],
        units=["flat"],
        evidence=["kw:magic damage"],
    )
    return a.emit()


def test_atom_contract_fields():
    emitted = _bolt_atoms()
    assert len(emitted) == 1
    atom = emitted[0]
    for key in (
        "atom_id",
        "behavior",
        "source",
        "name",
        "values",
        "units",
        "evidence",
        "hash",
    ):
        assert key in atom, key
    assert atom["hash"] == _bolt_atoms()[0]["hash"]  # deterministic
    assert atom["evidence"] == ["kw:magic damage"]


def test_dedup_merges_evidence_per_behavior():
    a = Atomizer("items", source_ref="Test")
    a.add(
        "damage.physical",
        "damage",
        "p[0]",
        "A",
        values=[10.0],
        units=["flat"],
        evidence=["passive:A@kw:physical"],
    )
    a.add(
        "damage.physical",
        "damage",
        "a[0]",
        "B",
        values=[],
        units=[],
        evidence=["active:B@kw:physical damage"],
    )
    emitted = a.emit()
    assert len(emitted) == 1
    assert set(emitted[0]["evidence"]) == {
        "passive:A@kw:physical",
        "active:B@kw:physical damage",
    }


def test_number_and_unit_extraction():
    values, units = number_and_unit("50 (+ 25% AP) bonus magic damage")
    # raw numbers preserved; the % unit is carried separately
    assert values == [50.0, 25.0]
    assert units == ["flat", "percent"]


def test_item_multi_effect_independence_issue_140_fixture():
    """A multi-effect item emits atoms for EVERY effect with exact receipts."""
    ravenous = _item("Ravenous Hydra")
    atoms = atomize_item(ravenous)
    evidence = {ev for atom in atoms for ev in atom["evidence"]}
    assert any(ev.startswith("active:Ravenous Crescent@") for ev in evidence), evidence
    assert any(ev.startswith("passive:Cleave@") for ev in evidence), evidence
    # The active's damage/lifesteal atoms must exist (not absorbed by passive).
    active_damage = [
        a
        for a in atoms
        if any(ev.startswith("active:Ravenous Crescent@") for ev in a["evidence"])
        and a["behavior"] in {"damage", "stat"}
    ]
    assert active_damage, "active emitted no damage/stat atoms"


def test_item_atom_values_are_numeric():
    for name in ("Ravenous Hydra", "Infinity Edge", "Liandry's Torment"):
        atoms = atomize_item(_item(name))
        assert atoms
        for atom in atoms:
            for value in atom["values"]:
                assert isinstance(value, (int, float)), (name, atom)


def test_guardians_horn_atom_keeps_both_damage_reduction_values():
    atoms = atomize_item(_item("Guardian's Horn"))

    reduction = next(
        atom
        for atom in atoms
        if atom["atom_id"] == "damage.reduction" and atom["name"] == "Undaunted"
    )
    assert reduction["values"] == [15.0, 3.75]
    assert reduction["units"] == ["flat", "flat"]
    assert reduction["evidence"] == ["passive:Undaunted@kw:incoming"]


def test_item_catalogue_covers_every_cache_item():
    catalogue = atomize_item_catalogue(fetch_item_data())
    assert len(catalogue) == 324
    assert all(atoms for atoms in catalogue.values())


def test_ability_atomizer_reads_leveling_modifiers():
    from src.calculator.data_fetcher import DEFAULT_DATA_DIR

    ahri = fetch_champion_data(data_directory=DEFAULT_DATA_DIR)["Ahri"]
    slots = atomize_abilities("Ahri", ahri)
    assert "Q" in slots
    q_atoms = slots["Q"]
    assert q_atoms
    for atom in q_atoms:
        assert atom["source"].startswith("Ahri.Q")
        assert all(isinstance(v, float) for v in atom["values"])


def test_ability_atomizer_keeps_multi_modifier_formula_pieces_separate():
    from src.calculator.data_fetcher import DEFAULT_DATA_DIR

    amumu = fetch_champion_data(data_directory=DEFAULT_DATA_DIR)["Amumu"]
    atoms = atomize_abilities("Amumu", amumu)["E"]
    reduction_atoms = [
        atom
        for atom in atoms
        if atom["source"].startswith("Amumu.E[0].effects[0].leveling[0].modifiers[")
    ]
    assert {atom["atom_id"] for atom in reduction_atoms} == {
        "ability.physical _damage _reduction.modifier_0",
        "ability.physical _damage _reduction.modifier_1",
        "ability.physical _damage _reduction.modifier_2",
    }
    assert [
        atom["values"][0] for atom in sorted(reduction_atoms, key=lambda a: a["source"])
    ] == [
        5.0,
        3.0,
        3.0,
    ]


def test_ability_cooldown_receipts_keep_modifier_indexes():
    fixture = {
        "abilities": {
            "Q": [
                {
                    "name": "Test spell",
                    "cooldown": {
                        "modifiers": [
                            {"values": [5]},
                            {"values": [4]},
                        ]
                    },
                }
            ]
        }
    }
    atoms = atomize_abilities("Test", fixture)["Q"]
    receipts = set(atoms[0]["evidence"])
    assert receipts == {
        "cooldown.modifiers[0]",
        "cooldown.modifiers[1]",
    }


def test_ability_atomizer_reads_prose_active_duration():
    fixture = {
        "abilities": {
            "W": [
                {
                    "name": "Wind Wall",
                    "effects": [
                        {
                            "description": (
                                "The wall destroys projectiles for 4 seconds."
                            )
                        }
                    ],
                }
            ]
        }
    }
    atoms = atomize_abilities("Yasuo", fixture)["W"]
    duration = next(
        atom for atom in atoms if atom["atom_id"] == "timing.active_duration"
    )
    assert duration["values"] == [4.0]
    assert duration["units"] == ["s"]
    assert duration["evidence"] == ["active duration@effects[0].description"]


def test_morgana_black_shield_atoms_keep_magic_pool_receipts():
    from src.calculator.data_fetcher import DEFAULT_DATA_DIR

    morgana = fetch_champion_data(data_directory=DEFAULT_DATA_DIR)["Morgana"]
    atoms = atomize_abilities("Morgana", morgana)["E"]
    strength = next(
        atom
        for atom in atoms
        if atom["behavior"] == "ability"
        and atom["evidence"] == ["Magic Shield Strength@effects[0]"]
    )
    duration = next(
        atom for atom in atoms if atom["atom_id"] == "timing.active_duration"
    )

    assert strength["values"] == [100.0, 155.0, 210.0, 265.0, 320.0]
    assert strength["atom_id"] == "ability.magic _shield _strength.modifier_0"
    assert strength["hash"] == "797fffe3046f726e"
    assert duration["values"] == [5.0]
    assert duration["hash"] == "106f001ee676d9f2"


def test_shield_duration_atoms_use_the_shield_sentence():
    expected = {
        ("Jarvan IV", "W"): ("effects[1]", 4.0),
        ("Olaf", "W"): ("effects[1]", 2.5),
        ("Renata Glasc", "E"): ("effects[1]", 3.0),
        ("Thresh", "W"): ("effects[1]", 4.0),
    }
    champion_data = fetch_champion_data()

    for (champion_name, slot), (effect_path, value) in expected.items():
        data = next(
            champion
            for champion in champion_data.values()
            if champion.get("name") == champion_name
        )
        atoms = atomize_abilities(champion_name, data)[slot]
        duration = next(
            atom for atom in atoms if atom["atom_id"] == "timing.shield_duration"
        )
        assert duration["source"].endswith(f".{effect_path}.description")
        assert duration["values"] == [value]
        assert duration["units"] == ["s"]
        assert duration["evidence"] == [f"shield duration@{effect_path}.description"]


def test_taric_invulnerability_atoms_split_delay_and_window():
    champion_data = fetch_champion_data()["Taric"]
    atoms = atomize_abilities("Taric", champion_data)["R"]

    delay = next(
        atom for atom in atoms if atom["atom_id"] == "timing.invulnerability_delay"
    )
    duration = next(
        atom for atom in atoms if atom["atom_id"] == "timing.invulnerability_duration"
    )

    assert delay["values"] == [2.5]
    assert delay["units"] == ["s"]
    assert delay["evidence"] == ["invulnerability delay@effects[0].description"]
    assert duration["values"] == [2.5]
    assert duration["units"] == ["s"]
    assert duration["evidence"] == ["invulnerability duration@effects[0].description"]


def test_prose_control_duration_atoms_keep_the_exact_effect_sentence():
    champion_data = fetch_champion_data()
    expected = {
        ("Orianna", "R", 0): 0.75,
        ("Camille", "E", 1): 0.75,
        ("Darius", "E", 1): 1.0,
    }

    for (champion_name, slot, effect_index), value in expected.items():
        atoms = atomize_abilities(champion_name, champion_data[champion_name])[slot]
        control = next(
            atom for atom in atoms if atom["atom_id"] == "timing.control_duration"
        )
        assert control["source"].endswith(f"effects[{effect_index}].description")
        assert control["values"] == [value]
        assert control["units"] == ["s"]
        assert control["evidence"] == [
            f"control duration@effects[{effect_index}].description"
        ]


def test_knock_them_up_prose_is_typed_as_a_control_duration():
    from src.calculator.data_fetcher import DEFAULT_DATA_DIR

    atoms = atomize_abilities(
        "Malphite", fetch_champion_data(data_directory=DEFAULT_DATA_DIR)["Malphite"]
    )
    atom = next(
        atom
        for atom in atoms["R"]
        if atom["source"] == "Malphite.R[0].effects[0].description"
        and atom["behavior"] == "timing"
        and "control duration@" in atom["evidence"][0]
    )
    assert atom["values"] == [1.5]
    assert atom["units"] == ["s"]


def test_amumu_tantrum_reduction_cap_is_typed_from_its_description():
    champion_data = fetch_champion_data()["Amumu"]
    atoms = atomize_abilities("Amumu", champion_data)["E"]
    atom = next(
        atom
        for atom in atoms
        if atom["source"] == "Amumu.E[0].effects[0].description"
        and atom["atom_id"] == "ability.damage_reduction_cap"
    )
    assert atom["values"] == [50.0]
    assert atom["units"] == ["%"]
    assert atom["evidence"] == ["damage reduction cap@effects[0].description"]


def test_rune_atomizer_preserves_nested_arrays_and_units():
    runes = {
        "Test Rune": {
            "name": "Test Rune",
            "cooldown": 6,
            "effects": {
                "leveling": [[10, 20], [30, 40]],
                "damage_amp_ratio": 0.08,
                "max_stacks": 3,
            },
        }
    }
    atoms = {
        atom["atom_id"]: atom for atom in atomize_rune_catalogue(runes)["Test Rune"]
    }
    assert atoms["rune.cooldown"]["units"] == ["s"]
    assert atoms["rune.effects.leveling"]["values"] == [10.0, 20.0, 30.0, 40.0]
    assert atoms["rune.effects.damage_amp_ratio"]["units"] == ["ratio"]
    assert atoms["rune.effects.max_stacks"]["units"] == ["count"]


def test_rune_atomizer_keeps_glacial_zone_receipts_and_units():
    runes = {
        "Glacial Augment": {
            "name": "Glacial Augment",
            "cooldown": 25.0,
            "effects": {
                "glacial_ray_count": 3,
                "glacial_zone_radius_units": 700.0,
                "glacial_zone_base_duration_seconds": 3.0,
                "glacial_zone_duration_cc_ratio": 1.0,
                "glacial_slow_base_ratio": 0.20,
                "glacial_damage_reduction_ratio": 0.15,
            },
        }
    }
    atoms = {
        atom["atom_id"]: atom
        for atom in atomize_rune_catalogue(runes)["Glacial Augment"]
    }
    assert atoms["rune.effects.glacial_ray_count"]["units"] == ["count"]
    assert atoms["rune.effects.glacial_zone_radius_units"]["units"] == ["units"]
    assert atoms["rune.effects.glacial_zone_base_duration_seconds"]["units"] == ["s"]
    assert atoms["rune.effects.glacial_zone_duration_cc_ratio"]["units"] == ["ratio"]
    assert atoms["rune.effects.glacial_slow_base_ratio"]["units"] == ["ratio"]
    assert atoms["rune.effects.glacial_damage_reduction_ratio"]["units"] == ["ratio"]


def test_rune_atomizer_keeps_stormraider_window_and_percent_receipts():
    runes = {
        "Stormraider's Surge": {
            "name": "Stormraider's Surge",
            "cooldown": [20.0, 10.0],
            "effects": {
                "stormraider_damage_threshold_ratio": 0.25,
                "stormraider_damage_window_seconds": 3.0,
                "stormraider_duration_seconds": 4.0,
                "stormraider_bonus_move_speed_melee_ranged": [48.0, 36.0],
                "stormraider_slow_resist_ratio": 0.50,
            },
        }
    }
    atoms = {
        atom["atom_id"]: atom
        for atom in atomize_rune_catalogue(runes)["Stormraider's Surge"]
    }
    assert atoms["rune.cooldown"]["units"] == ["s", "s"]
    assert atoms["rune.effects.stormraider_damage_threshold_ratio"]["units"] == [
        "ratio"
    ]
    assert atoms["rune.effects.stormraider_damage_window_seconds"]["units"] == ["s"]
    assert atoms["rune.effects.stormraider_duration_seconds"]["units"] == ["s"]
    assert atoms["rune.effects.stormraider_bonus_move_speed_melee_ranged"]["units"] == [
        "percent",
        "percent",
    ]
    assert atoms["rune.effects.stormraider_slow_resist_ratio"]["units"] == ["ratio"]


def test_rune_atomizer_keeps_fleet_charge_heal_and_speed_receipts():
    runes = {
        "Fleet Footwork": {
            "name": "Fleet Footwork",
            "cooldown": [],
            "effects": {
                "fleet_heal_melee_by_level": [10.0, 130.0],
                "fleet_heal_ranged_by_level": [6.0, 78.0],
                "fleet_bonus_ad_ratio_melee_ranged": [0.10, 0.06],
                "fleet_ap_ratio_melee_ranged": [0.05, 0.03],
                "fleet_bonus_move_speed_melee_ranged": [20.0, 15.0],
                "fleet_minion_heal_effectiveness": 0.15,
                "fleet_charge_cap": 100.0,
                "fleet_move_speed_duration_seconds": 1.0,
            },
        }
    }
    atoms = {
        atom["atom_id"]: atom
        for atom in atomize_rune_catalogue(runes)["Fleet Footwork"]
    }
    assert atoms["rune.effects.fleet_heal_melee_by_level"]["units"] == [
        "health",
        "health",
    ]
    assert atoms["rune.effects.fleet_heal_ranged_by_level"]["units"] == [
        "health",
        "health",
    ]
    assert atoms["rune.effects.fleet_bonus_ad_ratio_melee_ranged"]["units"] == [
        "ratio",
        "ratio",
    ]
    assert atoms["rune.effects.fleet_bonus_move_speed_melee_ranged"]["units"] == [
        "percent",
        "percent",
    ]
    assert atoms["rune.effects.fleet_minion_heal_effectiveness"]["units"] == ["ratio"]
    assert atoms["rune.effects.fleet_charge_cap"]["units"] == ["count"]
    assert atoms["rune.effects.fleet_move_speed_duration_seconds"]["units"] == ["s"]


def test_rune_atomizer_keeps_conqueror_force_state_and_heal_receipts():
    runes = {
        "Conqueror": {
            "name": "Conqueror",
            "cooldown": [],
            "effects": {
                "conqueror_adaptive_force_by_level": [1.8, 4.0],
                "conqueror_adaptive_force_max_by_level": [21.6, 48.0],
                "conqueror_heal_melee_ranged_ratios": [0.08, 0.05],
                "conqueror_stack_duration_seconds": 5.0,
                "conqueror_cast_instance_interval_seconds": 4.0,
                "conqueror_stacks_per_application": 2,
                "max_stacks": 12,
            },
        }
    }
    atoms = {
        atom["atom_id"]: atom for atom in atomize_rune_catalogue(runes)["Conqueror"]
    }
    assert atoms["rune.effects.conqueror_adaptive_force_by_level"]["units"] == [
        "adaptive_force",
        "adaptive_force",
    ]
    assert atoms["rune.effects.conqueror_adaptive_force_max_by_level"]["units"] == [
        "adaptive_force",
        "adaptive_force",
    ]
    assert atoms["rune.effects.conqueror_heal_melee_ranged_ratios"]["units"] == [
        "ratio",
        "ratio",
    ]
    assert atoms["rune.effects.conqueror_stack_duration_seconds"]["units"] == ["s"]
    assert atoms["rune.effects.conqueror_cast_instance_interval_seconds"]["units"] == [
        "s"
    ]
    assert atoms["rune.effects.conqueror_stacks_per_application"]["units"] == ["count"]
    assert atoms["rune.effects.max_stacks"]["units"] == ["count"]


def test_rune_atomizer_keeps_deathfire_burn_state_receipts():
    runes = {
        "Deathfire Touch": {
            "name": "Deathfire Touch",
            "cooldown": None,
            "effects": {
                "leveling": [[1.5, 6.0], [2.625, 10.5]],
                "deathfire_bonus_ad_ratios_by_state": [0.035, 0.06125],
                "deathfire_ap_ratios_by_state": [0.0125, 0.021875],
                "deathfire_tick_interval_seconds": 0.5,
                "deathfire_amp_delay_seconds": 3.0,
                "deathfire_amp_ratio": 0.75,
                "deathfire_duration_seconds": {
                    "spell_damage": 4.0,
                    "area_damage": 2.0,
                    "persistent_damage": 1.0,
                    "persistent_area_damage": 1.0,
                    "pet_damage": 1.0,
                },
            },
        }
    }
    atoms = {
        atom["atom_id"]: atom
        for atom in atomize_rune_catalogue(runes)["Deathfire Touch"]
    }
    assert atoms["rune.effects.deathfire_amp_delay_seconds"]["units"] == ["s"]
    assert atoms["rune.effects.deathfire_amp_ratio"]["units"] == ["ratio"]
    assert atoms["rune.effects.deathfire_ap_ratios_by_state"]["units"] == [
        "ratio",
        "ratio",
    ]
    assert atoms["rune.effects.deathfire_tick_interval_seconds"]["units"] == ["s"]
    assert atoms["rune.effects.deathfire_duration_seconds.spell_damage"]["units"] == [
        "s"
    ]


def test_stat_atomizer_preserves_growth_units():
    atoms = atomize_stats(
        {
            "name": "Test",
            "stats": {
                "attackDamage": {
                    "flat": 53,
                    "perLevel": 3,
                    "percent": 0,
                    "percentPerLevel": 0,
                }
            },
        }
    )
    units = {atom["atom_id"]: atom["units"] for atom in atoms}
    assert units["stat.attack_damage.flat"] == ["flat"]
    assert units["stat.attack_damage.per_level"] == ["per_level"]


def test_effect_fragments_split_branches():
    effect = {
        "description": "Deal damage. Heal allies.",
        "branches": ["branch one", "branch two"],
    }
    fragments = split_effect_fragments(effect, prefix="x.passives", index=0)
    assert len(fragments) >= 4  # 2 branches + 2 sentences
    assert fragments[0][1] == "branch one"
