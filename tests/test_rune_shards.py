"""The stat shards: three rows of three, priced out of the cached Rune page.

A shard is the simplest thing on a rune page and the easiest to fake, so
every number here is followed from the cache the wiki filled to the stat the
engine publishes:

* the **compile** — each of the nine reads its own cached entry and nothing
  else, and the one shard this engine holds no channel for says so instead of
  granting zero;
* the **stats** — the grant lands in the channel that stat belongs to, so
  adaptive force splits by build, attack speed goes through the champion's
  attack-speed ratio and health scaling reads its level;
* the **fight and the card** — the same page priced through
  ``/api/calculate`` and shown by ``/api/loadout-stats``, which is the whole
  point of wiring the page into the loadout.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import src.app as app_module
from src.calculator import rune_effects
from src.calculator.ability_spec import Disposition
from src.calculator.calculate import calculate_payload
from src.calculator.rune_paths import shards


def _grant(row: int, name: str, level: int = 9, **context) -> float:
    """Compile one shard and price its grant at one level."""
    effect = rune_effects.resolve_shard(row, name)
    return effect.amount(
        rune_effects.RuneStatContext(
            level=level,
            is_melee=context.get("is_melee", False),
            bonus_attack_damage=context.get("bonus_attack_damage", 0.0),
            ability_power=context.get("ability_power", 0.0),
            options={},
        )
    )


def _description(row: int, name: str) -> str:
    """The wiki text one shard option was parsed from."""
    for slot in rune_effects.RUNE_SHARDS["slots"]:
        if slot["row"] == row:
            for option in slot["options"]:
                if option["name"] == name:
                    return option["description"]
    raise AssertionError(f"row {row} has no option {name!r}")


# ---------------------------------------------------------------------------
# The compile: nine options, one cached number each
# ---------------------------------------------------------------------------


class TestEachShardCompilesFromItsCachedEntry:
    @pytest.mark.parametrize(
        ("row", "name", "stat", "amount", "quoted"),
        [
            (1, "Adaptive Force", rune_effects.RuneStat.ADAPTIVE_FORCE, 9.0, "9"),
            (
                1,
                "Attack Speed",
                rune_effects.RuneStat.ATTACK_SPEED_PERCENT,
                10.0,
                "10%",
            ),
            (1, "Cooldown Reduction", rune_effects.RuneStat.ABILITY_HASTE, 8.0, "8"),
            (2, "Adaptive Force", rune_effects.RuneStat.ADAPTIVE_FORCE, 9.0, "9"),
            (2, "Movement Speed", rune_effects.RuneStat.MOVE_SPEED_PERCENT, 2.5, "2.5"),
            (3, "Health", rune_effects.RuneStat.BONUS_HEALTH, 65.0, "65"),
        ],
    )
    def test_a_flat_shard_grants_the_number_its_description_states(
        self, row, name, stat, amount, quoted
    ):
        effect = rune_effects.resolve_shard(row, name)
        assert isinstance(effect, rune_effects.RuneStatGrantEffect)
        assert effect.stat is stat
        # Flat means flat: the same grant at level 1 and at the cap.
        assert _grant(row, name, level=1) == pytest.approx(amount)
        assert _grant(row, name, level=20) == pytest.approx(amount)
        assert quoted in _description(row, name)

    @pytest.mark.parametrize("row", [2, 3])
    @pytest.mark.parametrize(
        ("level", "health"), [(1, 10.0), (9, 90.0), (18, 180.0), (20, 200.0)]
    )
    def test_health_scaling_reads_its_level_table(self, row, level, health):
        """``{{pp|10 * x for 20}}``: 10 bonus health per level, 200 at the cap."""
        effect = rune_effects.resolve_shard(row, "Health Scaling")
        assert effect.stat is rune_effects.RuneStat.BONUS_HEALTH
        assert _grant(row, "Health Scaling", level=level) == pytest.approx(health)
        assert "10 * x for 20" in _description(row, "Health Scaling")

    def test_the_same_name_in_two_rows_is_two_different_selections(self):
        """Rows 2 and 3 both offer health scaling, and a page may take both."""
        flex = rune_effects.resolve_shard(2, "Health Scaling")
        defense = rune_effects.resolve_shard(3, "Health Scaling")
        assert flex.rune_name == "Flex shard: Health Scaling"
        assert defense.rune_name == "Defense shard: Health Scaling"
        assert _grant(2, "Adaptive Force") == _grant(1, "Adaptive Force")

    def test_tenacity_is_selectable_and_receipted_rather_than_worth_zero(self):
        """No ``RuneStat`` channel carries tenacity, so nothing pretends to."""
        effect = rune_effects.resolve_shard(3, "Tenacity and Slow Resist")
        assert isinstance(effect, rune_effects.RuneNoDamageEffect)
        assert effect.zero_policy.disposition is Disposition.WITHHELD
        assert "crowd control" in effect.receipts[0]
        assert "Defense shard: Tenacity and Slow Resist" in effect.receipts[0]
        assert not any(
            stat.value == "tenacity_percent" for stat in rune_effects.RuneStat
        )

    def test_movement_speed_grants_the_stat_and_discloses_what_it_cannot_move(self):
        effect = rune_effects.resolve_shard(2, "Movement Speed")
        assert effect.stat is rune_effects.RuneStat.MOVE_SPEED_PERCENT
        assert "no damage number" in effect.disclosures[0]

    def test_a_shard_whose_parse_degraded_raises_naming_the_shard_and_key(self):
        """Rule 5: a missing cached key is a loud failure, never a fallback."""
        compiler = shards.COMPILERS[(1, "Cooldown Reduction")]
        with pytest.raises(KeyError) as excinfo:
            compiler({"name": "Cooldown Reduction", "effects": {}})
        assert "Offense shard: Cooldown Reduction" in str(excinfo.value)
        assert "ability_haste" in str(excinfo.value)

    def test_an_unmodeled_shard_fails_closed(self):
        with pytest.raises(ValueError, match="not modeled yet"):
            rune_effects.resolve_shard(1, "Health")


class TestTheShardCatalogThePickerRenders:
    def test_three_rows_of_three_options_each_implemented(self):
        catalog = rune_effects.shard_catalog()
        assert [row["name"] for row in catalog] == ["Offense", "Flex", "Defense"]
        assert [row["row"] for row in catalog] == [1, 2, 3]
        options = [option for row in catalog for option in row["options"]]
        assert len(options) == 9
        assert all(option["implemented"] for option in options)

    def test_the_api_serves_that_catalog(self):
        config = app_module.app.test_client().get("/api/config").get_json()
        assert config["rune_shards"] == rune_effects.shard_catalog()

    def test_the_row_name_comes_from_the_cached_page(self):
        assert rune_effects.shard_row_name(1) == "Offense"
        with pytest.raises(KeyError, match="stat shard row 9"):
            rune_effects.shard_row_name(9)


# ---------------------------------------------------------------------------
# The fight: the same page through the real pipeline
# ---------------------------------------------------------------------------


def _fight(**overrides):
    """Ahri at level 9 with one plain rod — an AP build, one rotation."""
    payload = {
        "champion": "Ahri",
        "level": 9,
        "items": ["Needlessly Large Rod"],
        "fight_mode": "one_rotation",
    }
    payload.update(overrides)
    return calculate_payload(payload)


class TestTheShardsMoveTheFightTheyAreOn:
    def test_two_adaptive_shards_and_a_health_shard_on_an_ap_build(self):
        """+9 adaptive twice is +18 AP for an AP build; the health shard is +65."""
        bare = _fight()
        page = _fight(stat_shards=["Adaptive Force", "Adaptive Force", "Health"])
        assert bare["champion_stats"]["ability_power"] == 65
        assert page["champion_stats"]["ability_power"] == 83
        assert bare["champion_stats"]["health"] == 1291
        assert page["champion_stats"]["health"] == 1356
        assert page["champion_stats"]["bonus_health"] == 65
        assert bare["total_damage"] == pytest.approx(542.9)
        assert page["total_damage"] == pytest.approx(580.0)

    def test_adaptive_force_follows_the_build_into_attack_damage(self):
        """An AD build takes the same shard as bonus AD at the cached 0.6 ratio."""
        base = {
            "champion": "Caitlyn",
            "level": 9,
            "items": ["Long Sword"],
            "fight_mode": "timed",
            "fight_duration": 10.0,
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
        }
        bare = calculate_payload(dict(base))
        page = calculate_payload(dict(base, stat_shards=["Adaptive Force"]))
        assert rune_effects.adaptive_force_attack_damage_ratio() == 0.6
        # 9 adaptive force is 5.4 bonus AD, and no ability power at all.
        assert bare["champion_stats"]["bonus_attack_damage"] == 10
        assert page["champion_stats"]["bonus_attack_damage"] == 15
        assert page["champion_stats"]["ability_power"] == 0

    def test_the_attack_speed_shard_buys_a_swing(self):
        """+10% bonus AS through Caitlyn's AS ratio is a ninth auto in 10s."""
        base = {
            "champion": "Caitlyn",
            "level": 9,
            "items": [],
            "fight_mode": "timed",
            "fight_duration": 10.0,
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
        }
        bare = calculate_payload(dict(base))
        page = calculate_payload(dict(base, stat_shards=["Attack Speed"]))
        assert bare["champion_stats"]["attack_speed"] == pytest.approx(0.8495)
        assert page["champion_stats"]["attack_speed"] == pytest.approx(0.912)
        assert bare["auto_attack_schedule"]["expected_autos_total"] == 8
        assert page["auto_attack_schedule"]["expected_autos_total"] == 9
        assert bare["auto_attack_damage"] == pytest.approx(352.0)
        assert page["auto_attack_damage"] == pytest.approx(396.0)

    def test_the_haste_shard_buys_a_cast(self):
        """8 ability haste over a 12s window is a seventh cast for Ahri."""
        base = {
            "champion": "Ahri",
            "level": 9,
            "items": [],
            "fight_mode": "timed",
            "fight_duration": 12.0,
        }
        bare = calculate_payload(dict(base))
        page = calculate_payload(dict(base, stat_shards=["Cooldown Reduction"]))
        assert page["champion_stats"]["ability_haste"] == 8.0
        assert len(bare["cast_timeline"]) == 6
        assert len(page["cast_timeline"]) == 7
        assert bare["total_damage"] == pytest.approx(665.5)
        assert page["total_damage"] == pytest.approx(705.5)

    def test_health_scaling_reads_the_level_and_stacks_across_its_two_rows(self):
        """10 per level at level 9 is +90 health, and both rows is +180."""
        assert _fight()["champion_stats"]["health"] == 1291
        flex = _fight(stat_shards=["", "Health Scaling"])
        both = _fight(stat_shards=["", "Health Scaling", "Health Scaling"])
        assert flex["champion_stats"]["health"] == 1381
        assert both["champion_stats"]["health"] == 1471

    def test_the_two_shards_with_no_damage_axis_say_so_and_move_no_number(self):
        bare = _fight()
        speed = _fight(stat_shards=["", "Movement Speed"])
        tenacity = _fight(stat_shards=["", "", "Tenacity and Slow Resist"])
        assert speed["champion_stats"]["move_speed"] == pytest.approx(338.25)
        assert speed["total_damage"] == pytest.approx(bare["total_damage"])
        assert tenacity["total_damage"] == pytest.approx(bare["total_damage"])
        assert not bare["notes"]
        assert any("movement speed shard" in note for note in speed["notes"])
        assert any(
            "Tenacity and Slow Resist is not priced" in note
            for note in tenacity["notes"]
        )

    def test_a_request_with_no_shards_is_the_fight_unchanged(self):
        """The page is opt-in: an absent shard list prices exactly as before."""
        assert _fight(stat_shards=[]) == _fight()


class TestThePageRulesTheShardsObey:
    @pytest.mark.parametrize(
        ("shard_list", "rule"),
        [
            (["Health"], "names shard row 1"),
            (["Adaptive Force", "Attack Speed"], "names shard row 2"),
            (["Fake Shard"], "names shard row 1"),
            (
                ["Adaptive Force", "Adaptive Force", "Health", "Health"],
                "at most 3",
            ),
        ],
    )
    def test_an_illegal_shard_selection_is_refused_by_name(self, shard_list, rule):
        response = app_module.app.test_client().post(
            "/api/calculate",
            json={
                "champion": "Ahri",
                "level": 9,
                "items": [],
                "fight_mode": "one_rotation",
                "stat_shards": shard_list,
            },
        )
        assert response.status_code == 400
        assert rule in response.get_json()["error"]

    def test_a_row_may_be_left_empty_without_shifting_the_rows_after_it(self):
        page = rune_effects.validate_rune_page(None, None, ["", "Movement Speed"])
        assert page.stat_shards == ("", "Movement Speed")


# ---------------------------------------------------------------------------
# The stat card: the page the fight prices is the page the card shows
# ---------------------------------------------------------------------------


def _card(**overrides) -> dict:
    """One ``/api/loadout-stats`` response for the Ahri build above."""
    payload = {"champion": "Ahri", "level": 9, "items": ["Needlessly Large Rod"]}
    payload.update(overrides)
    response = app_module.app.test_client().post("/api/loadout-stats", json=payload)
    assert response.status_code == 200, response.get_json()
    return response.get_json()["stats"]


class TestTheLoadoutStatCardCarriesTheRunePage:
    def test_the_card_shows_what_the_page_grants(self):
        """Absolute Focus's +16 and the adaptive shard's +9 are both AP here."""
        bare = _card()
        page = _card(
            keystone="Arcane Comet",
            minor_runes=["Absolute Focus"],
            stat_shards=["Adaptive Force", "Movement Speed", "Health"],
        )
        assert bare["ability_power"] == 65
        assert page["ability_power"] == 90
        assert bare["health"] == 1291
        assert page["health"] == 1356
        assert bare["move_speed"] == pytest.approx(330.0)
        assert page["move_speed"] == pytest.approx(338.25)

    def test_the_card_and_the_fight_agree_on_the_same_page(self):
        shard_page = ["Adaptive Force", "Adaptive Force", "Health"]
        card = _card(stat_shards=shard_page)
        fight = _fight(stat_shards=shard_page)["champion_stats"]
        for stat in ("ability_power", "health", "attack_speed", "ability_haste"):
            assert card[stat] == fight[stat], stat

    def test_a_loadout_with_no_runes_is_the_card_unchanged(self):
        assert _card(keystone="", minor_runes=[], stat_shards=[]) == _card()

    def test_the_card_refuses_an_illegal_page_the_way_the_fight_does(self):
        response = app_module.app.test_client().post(
            "/api/loadout-stats",
            json={"champion": "Ahri", "level": 9, "stat_shards": ["Health"]},
        )
        assert response.status_code == 400
        assert "names shard row 1" in response.get_json()["error"]

    def test_a_practice_dummy_holds_no_rune_page(self):
        response = app_module.app.test_client().post(
            "/api/loadout-stats",
            json={"kind": "practice_dummy", "stat_shards": ["Adaptive Force"]},
        )
        assert response.status_code == 400
        assert "practice dummies have no runes" in response.get_json()["error"]


# ---------------------------------------------------------------------------
# The picker, driven headlessly through the real app.js
# ---------------------------------------------------------------------------

RUNE_HARNESS = Path(__file__).resolve().parent / "js" / "rune_page_harness.mjs"
APP_JS = Path(__file__).resolve().parent.parent / "static" / "js" / "app.js"


@pytest.fixture(scope="module")
def shard_page_ui(tmp_path_factory):
    """Run app.js over a page whose three shard rows are all filled."""
    if shutil.which("node") is None:  # pragma: no cover - toolchain dependent
        pytest.skip("node is not installed")
    config = app_module.app.test_client().get("/api/config").get_json()
    fixture = {
        "runes": config["runes"],
        "shards": config["rune_shards"],
        "capabilities": config["capabilities"],
        "page": {
            "keystone": "Arcane Comet",
            "minorRunes": ["", "Absolute Focus", "Scorch", "", ""],
            "statShards": ["Adaptive Force", "Movement Speed", "Health"],
            "runeOptions": {},
        },
        "countedOption": {
            "key": "stacks",
            "label": "Stacks",
            "kind": "count",
            "default": 0,
            "minimum": 0,
            "maximum": 10,
            "disclosure": "synthetic",
        },
    }
    path = tmp_path_factory.mktemp("shards") / "fixture.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")
    result = subprocess.run(
        ["node", str(RUNE_HARNESS), str(APP_JS), str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


class TestThePickerFillsThreeRowsAndTellsTheStatCard:
    def test_each_row_offers_exactly_its_own_three_options(self, shard_page_ui):
        assert shard_page_ui["shardChoices"] == [
            ["Adaptive Force", "Attack Speed", "Cooldown Reduction"],
            ["Adaptive Force", "Movement Speed", "Health Scaling"],
            ["Health", "Tenacity and Slow Resist", "Health Scaling"],
        ]

    def test_the_stat_card_request_carries_the_whole_page(self, shard_page_ui):
        """Without this the card would show pre-rune stats under a rune page."""
        card = shard_page_ui["statCard"]
        assert card["stat_shards"] == ["Adaptive Force", "Movement Speed", "Health"]
        assert card["keystone"] == "Arcane Comet"
        assert card["minor_runes"] == ["Absolute Focus", "Scorch"]
        assert card["rune_options"] == {}

    def test_what_the_picker_builds_is_a_page_the_server_prices(self, shard_page_ui):
        card = shard_page_ui["statCard"]
        page = rune_effects.validate_rune_page(
            card["keystone"], card["minor_runes"], card["stat_shards"]
        )
        grants = rune_effects.compile_rune_page(page).grants(
            level=9, is_melee=False, bonus_attack_damage=0.0, ability_power=100.0
        )
        # The shard's 9 plus Absolute Focus's own 15.71 at level 9, both
        # adaptive and both resolving to ability power on an AP build.
        assert grants.ability_power == pytest.approx(9.0 + 15.705882352941176)
        assert grants.bonus_health == pytest.approx(65.0)
        assert grants.move_speed_percent == pytest.approx(2.5)
