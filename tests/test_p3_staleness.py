"""P3 patch-regression: tolerance contract, fixture-driven staleness, API.

The pipeline (scripts/patch_regression.py) compares the wiki cache against
game-file ground truth and writes data/staleness.json.  These tests pin the
tolerance contract ("within 0.5% or +-2 flat is rounding, anything beyond is
stale"), the champion/item stat mappings, the best-effort ability-row rules,
and the /api/staleness endpoints the STALE badge consumes.
"""

import json

import pytest

import scripts.patch_regression as patch_regression
import src.app as app_module

# ---------------------------------------------------------------------------
# Tolerance contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cached", "game"),
    [
        (590.0, 590.0),  # identical
        (594.0, 594.9),  # inside +-2 flat
        (100.0, 100.4),  # inside 0.5% relative
        (35.0, 35.1),  # small ability drift inside 0.5%
        (0.0, 1.5),  # tiny absolute values: +-2 flat carve-out
    ],
)
def test_within_tolerance_accepts_rounding_noise(cached, game):
    assert patch_regression.within_tolerance(cached, game)


@pytest.mark.parametrize(
    ("cached", "game"),
    [
        (594.0, 600.0),  # 1% AND 6 flat -> stale (task example)
        (100.0, 103.0),  # 3% AND >+-2 flat -> stale
        (50.0, 55.0),  # 10% -> stale
    ],
)
def test_within_tolerance_flags_real_drift(cached, game):
    assert not patch_regression.within_tolerance(cached, game)


def test_tighter_ability_carveout_still_flags_one_second_cooldown_drift():
    # The stats tolerance's +-2 flat would swallow a 1s cooldown change;
    # ability rows use a tighter carve-out on purpose.
    assert not patch_regression.within_tolerance(
        7.0, 8.0, flat=patch_regression.COOLDOWN_FLAT_TOLERANCE
    )
    assert patch_regression.within_tolerance(
        7.0, 7.1, flat=patch_regression.COOLDOWN_FLAT_TOLERANCE
    )


# ---------------------------------------------------------------------------
# Champion stat comparison (fixture-driven)
# ---------------------------------------------------------------------------


def _champion_bin(overrides=None, resource="mana"):
    """A minimal champion bin fixture with a CharacterRecord."""
    record = {
        "__type": "CharacterRecord",
        "baseHPModifiable": {"baseValue": 590.0, "__type": "ModifiableFloat"},
        "hpPerLevelModifiable": {"baseValue": 104.0, "__type": "ModifiableFloat"},
        "baseStaticHPRegenModifiable": {
            "baseValue": 0.5,
            "__type": "ModifiableFloat",
        },
        "hpRegenPerLevelModifiable": {
            "baseValue": 0.12,
            "__type": "ModifiableFloat",
        },
        "baseDamageModifiable": {"baseValue": 53.0, "__type": "ModifiableFloat"},
        "damagePerLevelModifiable": {"baseValue": 3.0, "__type": "ModifiableFloat"},
        "baseArmorModifiable": {"baseValue": 21.0, "__type": "ModifiableFloat"},
        "armorPerLevelModifiable": {
            "baseValue": 4.2,
            "__type": "ModifiableFloat",
        },
        "baseMR": {"baseValue": 30.0, "__type": "ModifiableFloat"},
        "{01262a25}": {"baseValue": 1.3, "__type": "ModifiableFloat"},
        "attackSpeedModifiable": {"baseValue": 0.668, "__type": "ModifiableFloat"},
        "attackSpeedPerLevelModifiable": {
            "baseValue": 2.2,
            "__type": "ModifiableFloat",
        },
        "attackSpeedRatioModifiable": {
            "baseValue": 0.625,
            "__type": "ModifiableFloat",
        },
        "baseMoveSpeedModifiable": {"baseValue": 330.0, "__type": "ModifiableFloat"},
        "attackRangeModifiable": {"baseValue": 550.0, "__type": "ModifiableFloat"},
        "primaryAbilityResource": {
            "arType": 0 if resource == "mana" else 8,
            "{726ee5cd}": {"baseValue": 418.0, "__type": "ModifiableFloat"},
            "{6216bf7b}": {"baseValue": 25.0, "__type": "ModifiableFloat"},
            "{c4ab3550}": {"baseValue": 1.6, "__type": "ModifiableFloat"},
            "{3a509002}": {"baseValue": 0.16, "__type": "ModifiableFloat"},
            "__type": "AbilityResourceSlotInfo",
        },
    }
    if overrides:
        for field, value in overrides.items():
            if isinstance(value, dict) and "__type" not in value:
                record[field] = {"baseValue": value, "__type": "ModifiableFloat"}
            else:
                record[field] = value
    return {"Characters/Fixture/CharacterRecords/Root": record}


def _cache_stats(**overrides):
    stats = {
        "health": {"flat": 590.0, "perLevel": 104.0},
        "healthRegen": {"flat": 2.5, "perLevel": 0.6},
        "attackDamage": {"flat": 53.0, "perLevel": 3.0},
        "armor": {"flat": 21.0, "perLevel": 4.2},
        "magicResistance": {"flat": 30.0, "perLevel": 1.3},
        "attackSpeed": {"flat": 0.668, "perLevel": 2.2},
        "attackSpeedRatio": {"flat": 0.625},
        "movespeed": {"flat": 330.0},
        "attackRange": {"flat": 550.0},
        "mana": {"flat": 418.0, "perLevel": 25.0},
        "manaRegen": {"flat": 8.0, "perLevel": 0.8},
    }
    for key, value in overrides.items():
        stats[key] = value
    return stats


def test_champion_stats_match_without_drift():
    bin_data = _champion_bin()
    game_stats, _ = patch_regression.champion_game_stats(bin_data, "Fixture")
    drift, checked, unchecked = patch_regression.compare_champion_stats(
        _cache_stats(), game_stats
    )
    assert drift == {}
    assert checked == 19  # 15 core rows + mana family
    assert unchecked == 0


def test_champion_health_drift_beyond_tolerance_is_stale():
    bin_data = _champion_bin({"baseHPModifiable": 600.0})
    game_stats, _ = patch_regression.champion_game_stats(bin_data, "Fixture")
    drift, _checked, _unchecked = patch_regression.compare_champion_stats(
        _cache_stats(), game_stats
    )
    assert drift["health.flat"] == {"cached": 590.0, "game": 600.0}


def test_health_regen_uses_game_per_second_conversion():
    # game baseStaticHPRegenModifiable is per-second; the cache reports HP5.
    bin_data = _champion_bin({"baseStaticHPRegenModifiable": 0.5})
    game_stats, _ = patch_regression.champion_game_stats(bin_data, "Fixture")
    assert game_stats[("healthRegen", "flat")] == pytest.approx(2.5)
    drift, _checked, _unchecked = patch_regression.compare_champion_stats(
        _cache_stats(), game_stats
    )
    assert drift == {}


def test_non_mana_resources_leave_mana_rows_unchecked_not_stale():
    bin_data = _champion_bin(resource="rage")  # arType 8, no mana fields
    game_stats, ar_type = patch_regression.champion_game_stats(bin_data, "Fixture")
    assert ar_type == 8
    cache = _cache_stats(
        mana={"flat": 100.0, "perLevel": 0.0},
        manaRegen={"flat": 0.0, "perLevel": 0.0},
    )
    drift, _checked, unchecked = patch_regression.compare_champion_stats(
        cache, game_stats
    )
    assert drift == {}  # never stale on an unmappable resource
    assert unchecked == 1


# ---------------------------------------------------------------------------
# Item comparison (fixture-driven)
# ---------------------------------------------------------------------------


def _game_items_bin():
    return {
        "Items/3031": {
            "__type": "ItemData",
            "itemID": 3031,
            "mFlatPhysicalDamageMod": 75.0,
            "mFlatCritChanceMod": 0.25,
            "mFlatHPPoolMod": 0.0,
        },
        "Items/1001": {
            "__type": "ItemData",
            "itemID": 1001,
            "mFlatMovementSpeedMod": 25.0,
            "mFlatHPPoolMod": 0.0,
        },
        "Items/1055": {
            "__type": "ItemData",
            "itemID": 1055,
            "mFlatPhysicalDamageMod": 10.0,
            "mFlatHPPoolMod": 80.0,
            "PercentOmnivampMod": 0.025,
        },
        "Items/446693": {
            "__type": "ItemData",
            "itemID": 446693,
            "mFlatPhysicalDamageMod": 60.0,
        },
    }


def _cache_item(name, **stats_overrides):
    zero = {key: 0.0 for key in ("flat", "percent", "percentBase", "percentBonus")}
    stats = {
        key: dict(zero)
        for key in (
            "health",
            "healthRegen",
            "mana",
            "manaRegen",
            "attackDamage",
            "abilityPower",
            "armor",
            "magicResistance",
            "attackSpeed",
            "movespeed",
            "criticalStrikeChance",
            "lifesteal",
            "omnivamp",
            "abilityHaste",
            "lethality",
            "armorPenetration",
            "magicPenetration",
            "tenacity",
            "healAndShieldPower",
            "cooldownReduction",
        )
    }
    for key, value in stats_overrides.items():
        stats[key] = value
    return {"name": name, "stats": stats}


def test_item_stats_match_and_percent_units_convert():
    cache = _cache_item(
        "Infinity Edge",
        attackDamage={"flat": 75.0},
        criticalStrikeChance={"percent": 25.0},
    )
    game = _game_items_bin()["Items/3031"]
    drift, checked, _unchecked = patch_regression.compare_item_stats(cache, game)
    assert drift == {}
    assert checked == 2  # mFlatPhysicalDamageMod and mFlatCritChanceMod (x100)


def test_item_stat_drift_beyond_tolerance_is_stale():
    cache = _cache_item("Prowler's Claw", attackDamage={"flat": 55.0})
    game = {
        "__type": "ItemData",
        "itemID": 446693,
        "mFlatPhysicalDamageMod": 60.0,
    }
    drift, _checked, _unchecked = patch_regression.compare_item_stats(cache, game)
    assert drift["attackDamage.flat"] == {"cached": 55.0, "game": 60.0}


def test_item_omnivamp_uses_percent_omnivamp_field():
    cache = _cache_item("Doran's Blade", omnivamp={"percent": 2.5})
    game = _game_items_bin()["Items/1055"]
    drift, _checked, _unchecked = patch_regression.compare_item_stats(cache, game)
    assert drift == {}


def test_item_missing_game_field_is_unchecked_not_stale():
    cache = _cache_item("Phantom Dancer", movespeed={"percent": 7.0})
    game = {"__type": "ItemData", "itemID": 3046, "mFlatHPPoolMod": 0.0}
    drift, _checked, unchecked = patch_regression.compare_item_stats(cache, game)
    assert drift == {}
    assert unchecked == 1


# ---------------------------------------------------------------------------
# Ability rows (best-effort contract)
# ---------------------------------------------------------------------------


def _wiki_ability(cooldown=None, cost=None, leveling=None):
    entry = {}
    if cooldown is not None:
        entry["cooldown"] = {
            "modifiers": [{"units": [""] * len(cooldown), "values": cooldown}]
        }
    if cost is not None:
        entry["cost"] = {"modifiers": [{"units": [""] * len(cost), "values": cost}]}
    if leveling:
        entry["effects"] = [
            {"leveling": [{"attribute": attr, "modifiers": [mod]}]}
            for attr, mod in leveling
        ]
    return entry


def _game_spell(cooldown_time=None, mana=None, data_values=None):
    spell = {}
    if cooldown_time is not None:
        spell["cooldownTime"] = cooldown_time
    if mana is not None:
        spell["mana"] = mana
    if data_values is not None:
        spell["DataValues"] = data_values
    return spell


def test_cooldown_row_checked_when_bin_matches():
    entry = _wiki_ability(cooldown=[7, 7, 7, 7, 7])
    spell = _game_spell(cooldown_time=[7.0] * 7)
    checked, stale, _unchecked, _notes, _needs = patch_regression._compare_entry_rows(
        entry, spell, "Q", 0
    )
    assert checked == 1
    assert stale == 0


def test_cooldown_drift_flagged_when_bin_and_ddragon_agree():
    # A real flat cooldown (8s) in both game sources vs a stale wiki row.
    entry = _wiki_ability(cooldown=[10, 9, 8, 7, 6])
    spell = _game_spell(cooldown_time=[8.0] * 7)
    checked, stale, _unchecked, _notes, _needs = patch_regression._compare_entry_rows(
        entry, spell, "Q", 0, ddragon={"cooldown": [8.0], "cost": None}
    )
    assert checked == 0
    assert stale == 1


def test_no_cooldown_in_game_files_is_unchecked_not_stale():
    entry = _wiki_ability(cooldown=[1, 1, 1, 1, 1])
    spell = _game_spell(cooldown_time=[0.0] * 7)
    checked, stale, unchecked, _notes, _needs = patch_regression._compare_entry_rows(
        entry, spell, "Q", 0
    )
    assert checked == 0
    assert stale == 0
    assert unchecked == 1


def test_health_cost_row_unchecked_when_game_has_no_mana_cost():
    entry = _wiki_ability(cost=[20, 20, 20, 20, 20])
    spell = _game_spell(mana=[0.0] * 6)
    checked, stale, unchecked, _notes, _needs = patch_regression._compare_entry_rows(
        entry, spell, "Q", 0, ddragon={"cost": [0.0], "cooldown": None}
    )
    assert checked == 0
    assert stale == 0
    assert unchecked == 1


def test_scaled_display_row_unchecked():
    entry = _wiki_ability(
        cooldown=[4, 3.25, 2.5, 1.75],
        leveling=[],
    )
    entry["cooldown"]["modifiers"][0]["units"] = ["(based on Rampage stacks)"] * 4
    spell = _game_spell(cooldown_time=[4.0] * 7)
    checked, stale, unchecked, _notes, _needs = patch_regression._compare_entry_rows(
        entry, spell, "Q", 0
    )
    assert checked == 0
    assert stale == 0
    assert unchecked == 1


def test_damage_row_value_matched_is_checked():
    entry = _wiki_ability(
        leveling=[
            (
                "Magic Damage",
                {"units": [""] * 5, "values": [35, 60, 85, 110, 135]},
            )
        ]
    )
    spell = _game_spell(
        data_values=[{"name": "BaseDamage", "values": [10, 35, 60, 85, 110, 135, 160]}]
    )
    checked, stale, _unchecked, _notes, _needs = patch_regression._compare_entry_rows(
        entry, spell, "Q", 0
    )
    assert checked == 1
    assert stale == 0


# ---------------------------------------------------------------------------
# End-to-end document (fixture-driven)
# ---------------------------------------------------------------------------


def _write_fixture_game_dir(tmp_path):
    game_dir = tmp_path / "gamefiles"
    (game_dir / "characters").mkdir(parents=True)
    with open(game_dir / "characters" / "fixture.bin.json", "w") as handle:
        json.dump(_champion_bin({"baseHPModifiable": 600.0}), handle)
    with open(game_dir / "characters" / "clean.bin.json", "w") as handle:
        json.dump(_champion_bin(), handle)
    with open(game_dir / "items.bin.json", "w") as handle:
        json.dump(_game_items_bin(), handle)
    return game_dir


def test_build_staleness_flags_drift_and_reports_counts(tmp_path):
    game_dir = _write_fixture_game_dir(tmp_path)
    champions_cache = {
        "Fixture": {
            "stats": _cache_stats(),
            "abilities": {"Q": [_wiki_ability(cooldown=[7, 7, 7, 7, 7])]},
        },
        "Clean": {
            "stats": _cache_stats(),
            "abilities": {},
        },
    }
    items_cache = {
        "3031": _cache_item("Infinity Edge", attackDamage={"flat": 75.0}),
        "446693": _cache_item("Prowler's Claw", attackDamage={"flat": 55.0}),
    }
    document, _pending = patch_regression.build_staleness(
        "16.15", champions_cache, items_cache, game_dir
    )
    assert document["patch"] == "16.15"
    assert document["champions"]["Fixture"]["stale"] is True
    assert document["champions"]["Fixture"]["stat_drift"]["health.flat"] == {
        "cached": 590.0,
        "game": 600.0,
    }
    assert document["champions"]["Clean"]["stale"] is False
    assert document["items"]["3031"]["stale"] is False
    assert document["items"]["446693"]["stale"] is True
    assert document["items"]["446693"]["stat_drift"]["attackDamage.flat"] == {
        "cached": 55.0,
        "game": 60.0,
    }


# ---------------------------------------------------------------------------
# /api/staleness endpoints
# ---------------------------------------------------------------------------


def _staleness_fixture(tmp_path):
    fixture = {
        "patch": "16.15",
        "checked_at": "2026-08-06T00:00:00+00:00",
        "champions": {
            "Kled": {
                "stale": True,
                "stat_drift": {},
                "ability_rows_checked": 0,
                "ability_rows_stale": 0,
                "note": "",
            },
            "Ahri": {
                "stale": False,
                "stat_drift": {},
                "ability_rows_checked": 0,
                "ability_rows_stale": 0,
                "note": "",
            },
        },
        "items": {
            "446693": {
                "name": "Prowler's Claw",
                "stale": True,
                "stat_drift": {},
                "note": "",
            },
            "3031": {
                "name": "Infinity Edge",
                "stale": False,
                "stat_drift": {},
                "note": "",
            },
        },
    }
    path = tmp_path / "staleness.json"
    path.write_text(json.dumps(fixture))
    return path, fixture


def test_api_staleness_serves_report(monkeypatch, tmp_path):
    path, fixture = _staleness_fixture(tmp_path)
    monkeypatch.setattr(app_module, "_staleness_path", lambda: path)
    response = app_module.app.test_client().get("/api/staleness")
    assert response.status_code == 200
    assert response.get_json() == fixture


def test_api_staleness_404_without_report(monkeypatch, tmp_path):
    missing = tmp_path / "missing.json"
    monkeypatch.setattr(app_module, "_staleness_path", lambda: missing)
    response = app_module.app.test_client().get("/api/staleness")
    assert response.status_code == 404
    assert "error" in response.get_json()
