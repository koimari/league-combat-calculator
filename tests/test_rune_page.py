"""The rune page: what the cache holds, what a request may ask for, what it costs.

Three layers, in the order a request meets them.

* The **roster** — ``data/runes.json`` holds all 62 runes with the path and
  row Data Dragon states, plus the two page-level blocks no rune owns: the
  Rune page's stat-shard table and ``Template:Adaptive``'s conversion.
* The **rules** — ``validate_rune_page`` enforces every rule the game does
  and names the one it refused on.
* The **numbers** — each exemplar priced through the real engine, with the
  arithmetic quoted.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import src.app as app_module
from src.calculator import rune_effects
from src.calculator.ability_spec import DamagePart
from src.calculator.calculate import calculate_payload
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.rune_paths import precision

# ---------------------------------------------------------------------------
# The roster
# ---------------------------------------------------------------------------


class TestTheCachedRoster:
    def test_five_paths_of_a_keystone_row_and_three_minor_rows(self):
        rows: dict[tuple[str, int], int] = {}
        for entry in rune_effects.RUNE_EFFECTS.values():
            key = (entry["path"], entry["row"])
            rows[key] = rows.get(key, 0) + 1
        assert len(rune_effects.RUNE_EFFECTS) == 62
        assert {path for path, _ in rows} == {
            "Precision",
            "Domination",
            "Sorcery",
            "Resolve",
            "Inspiration",
        }
        assert {row for _, row in rows} == {0, 1, 2, 3}
        # Precision and Sorcery carry a fourth keystone; every minor row is three.
        assert sum(count for (_, row), count in rows.items() if row == 0) == 17
        assert all(count == 3 for (_, row), count in rows.items() if row > 0)

    def test_every_entry_downloaded_and_carries_its_text(self):
        for name, entry in rune_effects.RUNE_EFFECTS.items():
            assert "error" not in entry, name
            assert entry["description"], name
            assert entry["icon"], name

    def test_the_roster_is_cached_in_the_wiki_s_path_order(self):
        seen: list[str] = []
        for entry in rune_effects.RUNE_EFFECTS.values():
            if not seen or seen[-1] != entry["path"]:
                seen.append(entry["path"])
        assert seen == ["Precision", "Domination", "Sorcery", "Resolve", "Inspiration"]

    def test_the_wiki_title_case_difference_did_not_drop_a_rune(self):
        """Data Dragon says "Jack Of All Trades"; the wiki page says "of"."""
        entry = rune_effects.RUNE_EFFECTS["Jack Of All Trades"]
        assert entry["path"] == "Inspiration"
        assert entry["row"] == 3
        assert "Jack" in entry["description"]

    def test_the_shard_table_is_three_rows_of_three_with_its_revision(self):
        shards = rune_effects.RUNE_SHARDS
        assert shards["source"].endswith("/Rune")
        assert isinstance(shards["revision"], int)
        assert shards["revision"] > 0
        assert [slot["name"] for slot in shards["slots"]] == [
            "Offense",
            "Flex",
            "Defense",
        ]
        assert [slot["row"] for slot in shards["slots"]] == [1, 2, 3]
        assert all(len(slot["options"]) == 3 for slot in shards["slots"])
        offense = {option["name"]: option for option in shards["slots"][0]["options"]}
        assert offense["Attack Speed"]["effects"]["attack_speed_percent"] == 10.0
        assert offense["Cooldown Reduction"]["effects"]["ability_haste"] == 8.0
        assert offense["Adaptive Force"]["effects"]["adaptive_force"] == 9.0

    def test_the_adaptive_conversion_is_read_off_its_own_template(self):
        adaptive = rune_effects.ADAPTIVE_FORCE
        assert adaptive["source"].endswith("Template:Adaptive")
        assert isinstance(adaptive["revision"], int)
        assert adaptive["revision"] > 0
        assert adaptive["attack_damage_ratio"] == 0.6


# ---------------------------------------------------------------------------
# The rules
# ---------------------------------------------------------------------------


@pytest.fixture(name="uncompiled_rune")
def fixture_uncompiled_rune(monkeypatch):
    """One roster rune with its compiler taken away, and its name.

    Every rune the roster offers compiles now, so the refusal an *unmodeled*
    rune is owed can no longer be proved by naming one — it is proved by
    removing a compiler. The merged vocabulary is cached, so the cache is
    cleared on the way in and again on the way out, once monkeypatch has put
    the compiler back.
    """
    name = "Triumph"
    monkeypatch.delitem(precision.COMPILERS, name)
    rune_effects._compilers.cache_clear()
    yield name
    rune_effects._compilers.cache_clear()


class TestPageValidation:
    def test_a_legal_page_passes_through(self):
        page = rune_effects.validate_rune_page(
            "Arcane Comet", ["Absolute Focus", "Scorch"], ["", "", ""]
        )
        assert page.keystone == "Arcane Comet"
        assert page.minor_runes == ("Absolute Focus", "Scorch")
        assert page.rune_names == ("Arcane Comet", "Absolute Focus", "Scorch")

    def test_an_empty_page_is_legal_and_selects_nothing(self):
        page = rune_effects.validate_rune_page()
        assert page.rune_names == ()
        assert rune_effects.resolve_rune_page(page) == ()

    def test_an_unknown_rune_names_itself(self):
        with pytest.raises(ValueError, match="Unknown rune 'Fake Rune'"):
            rune_effects.validate_rune_page("", ["Fake Rune"])

    def test_an_unmodeled_rune_is_refused_not_priced_at_zero(self, uncompiled_rune):
        with pytest.raises(ValueError, match="not modeled yet"):
            rune_effects.validate_rune_page("", [uncompiled_rune])

    def test_a_repeated_rune_is_refused(self):
        """The shared public-list policy owns this one, not the page rules."""
        with pytest.raises(ValueError, match="must not contain duplicates"):
            rune_effects.validate_rune_page("", ["Scorch", "Scorch"])

    def test_two_runes_in_one_row_name_both_and_the_row(self):
        """The rules of the page are checked before this engine's coverage."""
        with pytest.raises(ValueError, match=r"one rune per row.*Sorcery row 3"):
            rune_effects.validate_rune_page("", ["Scorch", "Waterwalking"])

    def test_a_keystone_in_the_minor_list_is_refused(self):
        with pytest.raises(ValueError, match="is a keystone, not a minor rune"):
            rune_effects.validate_rune_page("", ["Electrocute"])

    def test_a_minor_rune_in_the_keystone_field_is_refused(self):
        with pytest.raises(ValueError, match="is a minor rune, not a keystone"):
            rune_effects.validate_rune_page("Scorch")

    def test_three_paths_are_refused(self):
        with pytest.raises(ValueError, match="draws from two paths"):
            rune_effects.validate_rune_page(
                "", ["Scorch", "Coup de Grace", "Cosmic Insight"]
            )

    def test_a_second_secondary_path_is_refused_even_under_the_keystone(self):
        """Two minors each from two paths is three paths, not two."""
        with pytest.raises(ValueError, match="keystone's path is Sorcery"):
            rune_effects.validate_rune_page(
                "Arcane Comet",
                ["Triumph", "Legend: Haste", "Cheap Shot", "Sixth Sense"],
            )

    def test_four_from_one_path_cannot_even_be_spelled(self):
        """A path has three minor rows, so one-per-row already forbids it."""
        with pytest.raises(ValueError, match="one rune per row"):
            rune_effects.validate_rune_page(
                "Arcane Comet",
                ["Axiom Arcanist", "Transcendence", "Scorch", "Nimbus Cloak"],
            )

    def test_three_from_the_secondary_path_are_refused(self, monkeypatch):
        _compile_every_minor(monkeypatch)
        with pytest.raises(
            ValueError, match="at most 2 minor runes from its secondary"
        ):
            rune_effects.validate_rune_page(
                "Arcane Comet", ["Triumph", "Legend: Haste", "Coup de Grace"]
            )

    def test_the_keystone_s_path_is_the_three_rune_path(self, monkeypatch):
        """Three Sorcery minors are legal under a Sorcery keystone only."""
        _compile_every_minor(monkeypatch)
        legal = ["Axiom Arcanist", "Transcendence", "Scorch"]
        assert rune_effects.validate_rune_page("Arcane Comet", legal).minor_runes == (
            tuple(legal)
        )
        with pytest.raises(
            ValueError, match="at most 2 minor runes from its secondary"
        ):
            rune_effects.validate_rune_page("Electrocute", legal)

    def test_a_shard_not_in_its_row_lists_the_row_s_options(self):
        with pytest.raises(ValueError, match="stat_shards\\[0\\] names shard row 1"):
            rune_effects.validate_rune_page("", None, ["Health"])

    def test_every_offered_shard_compiles(self):
        assert rune_effects.validate_rune_page(
            "", None, ["Adaptive Force"]
        ).stat_shards == ("Adaptive Force",)

    def test_too_many_shards_are_refused(self):
        with pytest.raises(ValueError, match="stat_shards may contain at most 3"):
            rune_effects.validate_rune_page("", None, ["", "", "", ""])

    def test_the_same_shard_in_two_rows_is_legal(self):
        """Adaptive Force is offered in rows 1 and 2; positions tell them apart."""
        page = rune_effects.validate_rune_page(
            "", None, ["Adaptive Force", "Adaptive Force", ""]
        )
        assert page.stat_shards == ("Adaptive Force", "Adaptive Force", "")

    def test_an_option_for_an_unselected_rune_is_refused(self):
        with pytest.raises(ValueError, match="this rune page does not select"):
            rune_effects.validate_rune_page(
                "", ["Scorch"], None, {"Absolute Focus": {"above_health_threshold": 0}}
            )

    def test_an_undeclared_option_key_is_refused(self):
        with pytest.raises(ValueError, match="declares no option 'made_up'"):
            rune_effects.validate_rune_page(
                "", ["Absolute Focus"], None, {"Absolute Focus": {"made_up": 1}}
            )

    def test_a_declared_option_survives_onto_the_page(self):
        page = rune_effects.validate_rune_page(
            "",
            ["Absolute Focus"],
            None,
            {"Absolute Focus": {"above_health_threshold": 0}},
        )
        assert page.options == {"Absolute Focus": {"above_health_threshold": 0.0}}


def _compile_every_minor(monkeypatch):
    """Let the shape rules be tested without waiting on units B, C and D.

    The path rules are about paths and rows, not about which runes happen to
    have a compiler yet; stubbing the compiler table keeps this file testing
    the rule instead of today's coverage.
    """
    stub = dict(rune_effects._compilers())
    for name in rune_effects.RUNE_EFFECTS:
        stub.setdefault(name, lambda entry: None)
    monkeypatch.setattr(rune_effects, "_compilers", lambda: stub)


# ---------------------------------------------------------------------------
# The numbers
# ---------------------------------------------------------------------------

_STATS = {
    "armor_penetration_bonus_percent": 0.0,
    "armor_penetration_percent": 0.0,
    "basic_ability_haste": 0.0,
    "bonus_health": 0.0,
    "bonus_mana": 0.0,
    "flat_armor_penetration": 0.0,
    "is_melee": True,
    "lethality": 0.0,
    "magic_penetration_flat": 0.0,
    "magic_penetration_percent": 0.0,
    "max_mana": 0.0,
    "move_speed": 0.0,
    "omnivamp_percent": 0.0,
    "resource_regen_per_second": 0.0,
    "ultimate_haste": 0.0,
    "attack_damage": 100.0,
    "base_attack_damage": 60.0,
    "bonus_attack_damage": 40.0,
    "ability_power": 0.0,
    "attack_speed": 0.7,
    "attack_speed_ratio": 0.7,
    "critical_strike_chance": 0.0,
    "health": 2000.0,
    "armor": 50.0,
    "magic_resistance": 50.0,
    "level": 18,
    "ability_haste": 0.0,
}
_ABILITIES = {
    "Q": {
        "name": "Test Q",
        "rank": 1,
        "cooldown": 6.0,
        "damage_type": "magic",
        "total_raw": 300.0,
        "parts": (DamagePart("magic", 300.0),),
    }
}
# 300 raw magic into 100 MR is 150 post-mitigation; a 20s window casts Q at
# 0, 6, 12 and 18 seconds against a 400-health target.
_MITIGATED_CAST = 150.0


def _fight(**overrides):
    config = {
        "target_health": 400.0,
        "target_armor": 100.0,
        "target_magic_resistance": 100.0,
        "fight_duration_seconds": 20.0,
        "auto_attack_uptime": 0.0,
        "one_rotation": False,
        "deterministic": True,
    }
    config.update(overrides)
    return calculate_fight_damage(dict(_STATS), _ABILITIES, [], FightConfig(**config))


class TestTheWalkerPricesEachShape:
    def test_a_page_with_no_runes_is_the_fight_unchanged(self):
        bare = _fight()
        assert bare["total_damage"] == pytest.approx(4 * _MITIGATED_CAST)
        assert not [key for key in bare["breakdown"] if key.startswith("rune_")]

    def test_scorch_burns_once_per_cooldown_window(self):
        """40 magic at level 18 into 100 MR is 20, twice in a 20s window."""
        result = _fight(minor_runes=("Scorch",))
        row = result["breakdown"]["rune_Scorch"]
        assert row["name"] == "Scorch (rune)"
        assert row["damage_type"] == "magic"
        assert row["count"] == 2
        assert row["total_damage"] == pytest.approx(40.0)
        # Casts at 0 and 12 (its 10s cooldown skips the 6s cast); each burn
        # lands one second later.
        assert [event["time"] for event in row["damage_events"]] == [1.0, 13.0]
        assert result["total_damage"] == pytest.approx(4 * _MITIGATED_CAST + 40.0)

    def test_coup_de_grace_amplifies_only_what_lands_under_the_gate(self):
        """400 max health: the casts at 12s and 18s land under 160."""
        result = _fight(minor_runes=("Coup de Grace",))
        row = result["breakdown"]["rune_Coup de Grace"]
        assert row["name"] == "Damage Amplification (Coup de Grace)"
        assert row["multiplier"] == pytest.approx(1.08)
        assert row["total_damage"] == pytest.approx(2 * _MITIGATED_CAST * 0.08)
        assert result["total_damage"] == pytest.approx(4 * _MITIGATED_CAST + 24.0)

    def test_coup_de_grace_on_a_target_that_never_drops_says_so(self):
        result = _fight(minor_runes=("Coup de Grace",), target_health=10_000.0)
        assert "rune_Coup de Grace" not in result["breakdown"]
        assert any(
            note.startswith("Coup de Grace amplified nothing")
            for note in result["notes"]
        )

    def test_cosmic_insight_books_nothing_and_publishes_why(self):
        result = _fight(minor_runes=("Cosmic Insight",))
        assert result["total_damage"] == pytest.approx(4 * _MITIGATED_CAST)
        assert any("is not priced" in note for note in result["notes"])

    def test_a_keystone_and_its_minors_are_walked_together(self):
        result = _fight(
            keystone="Electrocute",
            minor_runes=("Scorch", "Coup de Grace", "Cosmic Insight"),
        )
        # Scorch's two burns join the ledger the gate reads, so the amp grows.
        amped = 2 * _MITIGATED_CAST + 20.0
        assert result["breakdown"]["rune_Scorch"]["total_damage"] == pytest.approx(40.0)
        assert result["breakdown"]["rune_Coup de Grace"][
            "total_damage"
        ] == pytest.approx(amped * 0.08)
        # Casts six seconds apart never land three instances inside
        # Electrocute's three-second stack window.
        assert "keystone_Electrocute" not in result["breakdown"]
        assert any("Electrocute never procced" in note for note in result["notes"])


class TestTheStatGrantReachesTheStatBlock:
    def test_absolute_focus_grants_its_level_table_through_the_real_pipeline(self):
        """30 adaptive force at 18, taken as ability power on an AP build.

        Rabadon's multiplies it with the rest: 169 -> 208 is 39 = 30 x 1.3.
        """
        request = {
            "champion": "Ahri",
            "level": 18,
            "items": ["Rabadon's Deathcap"],
            "fight_mode": "one_rotation",
            "target_health": 1000.0,
            "target_armor": 100.0,
            "target_mr": 100.0,
        }
        bare = calculate_payload(dict(request))
        with_rune = calculate_payload({**request, "minor_runes": ["Absolute Focus"]})
        assert bare["champion_stats"]["ability_power"] == 169
        assert with_rune["champion_stats"]["ability_power"] == 208
        assert bare["total_damage"] == pytest.approx(1041.1, abs=0.05)
        assert with_rune["total_damage"] == pytest.approx(1121.5, abs=0.05)
        assert any("Absolute Focus is priced" in n for n in with_rune["notes"])

    def test_the_adaptive_choice_reads_the_build_after_its_item_passives(self):
        """155 bonus AD against 169 AP: the larger is AP, so AP takes it.

        The comparison has to happen after the item passives, not over the
        item stat subtotals: Rabadon's multiplier and every conversion are
        invisible to the subtotals, and reading them would hand this build
        18 attack damage instead of 30 ability power.
        """
        request = {
            "champion": "Ahri",
            "level": 18,
            "fight_mode": "one_rotation",
            "items": ["Rabadon's Deathcap", "Bloodthirster", "Infinity Edge"],
        }
        bare = calculate_payload(dict(request))
        with_rune = calculate_payload({**request, "minor_runes": ["Absolute Focus"]})
        assert (
            bare["champion_stats"]["bonus_attack_damage"],
            bare["champion_stats"]["ability_power"],
        ) == (155, 169)
        assert with_rune["champion_stats"]["bonus_attack_damage"] == 155
        assert with_rune["champion_stats"]["ability_power"] == 208

    def test_turning_its_option_off_returns_the_bare_numbers(self):
        request = {
            "champion": "Ahri",
            "level": 18,
            "items": ["Rabadon's Deathcap"],
            "fight_mode": "one_rotation",
            "minor_runes": ["Absolute Focus"],
            "rune_options": {"Absolute Focus": {"above_health_threshold": 0}},
        }
        gated = calculate_payload(dict(request))
        bare = calculate_payload(
            {
                key: value
                for key, value in request.items()
                if not key.startswith("rune") and key != "minor_runes"
            }
        )
        assert gated["champion_stats"]["ability_power"] == (
            bare["champion_stats"]["ability_power"]
        )
        assert gated["total_damage"] == pytest.approx(bare["total_damage"])


# ---------------------------------------------------------------------------
# The public boundary
# ---------------------------------------------------------------------------


def _request(**overrides):
    payload = {
        "champion": "Ahri",
        "level": 11,
        "items": [],
        "fight_mode": "one_rotation",
    }
    payload.update(overrides)
    return payload


class TestTheRunePageOverHttp:
    def test_a_full_legal_page_returns_and_names_its_runes(self):
        client = app_module.app.test_client()
        response = client.post(
            "/api/calculate",
            json=_request(
                keystone="Arcane Comet",
                minor_runes=["Absolute Focus", "Scorch"],
                fight_mode="time_based",
                fight_duration=20.0,
            ),
        )
        assert response.status_code == 200
        result = response.get_json()
        assert "rune_Scorch" in result["breakdown"]
        assert any("Absolute Focus" in note for note in result["notes"])

    @pytest.mark.parametrize(
        ("payload", "rule"),
        [
            ({"minor_runes": ["Scorch", "Waterwalking"]}, "one rune per row"),
            ({"minor_runes": ["Fake Rune"]}, "Unknown rune"),
            ({"minor_runes": ["Scorch", "Scorch"]}, "must not contain duplicates"),
            ({"keystone": "Scorch"}, "is a minor rune, not a keystone"),
            ({"stat_shards": ["Health"]}, "names shard row 1"),
        ],
    )
    def test_an_illegal_page_returns_400_naming_the_rule(self, payload, rule):
        client = app_module.app.test_client()
        response = client.post("/api/calculate", json=_request(**payload))
        assert response.status_code == 400
        assert rule in response.get_json()["error"]

    def test_an_unmodeled_rune_returns_400_over_http_too(self, uncompiled_rune):
        client = app_module.app.test_client()
        response = client.post(
            "/api/calculate", json=_request(minor_runes=[uncompiled_rune])
        )
        assert response.status_code == 400
        assert "not modeled yet" in response.get_json()["error"]


# ---------------------------------------------------------------------------
# The picker, driven headlessly through the real app.js
# ---------------------------------------------------------------------------

RUNE_HARNESS = Path(__file__).resolve().parent / "js" / "rune_page_harness.mjs"
APP_JS = Path(__file__).resolve().parent.parent / "static" / "js" / "app.js"


@pytest.fixture(scope="module")
def rune_page_ui(tmp_path_factory):
    """Run app.js's rune-page code over the catalogue /api/config publishes."""
    if shutil.which("node") is None:  # pragma: no cover - toolchain dependent
        pytest.skip("node is not installed")
    config = app_module.app.test_client().get("/api/config").get_json()
    fixture = {
        "runes": config["runes"],
        "shards": config["rune_shards"],
        "capabilities": config["capabilities"],
        "page": {
            "keystone": "Arcane Comet",
            "minorRunes": ["", "Absolute Focus", "Scorch", "Coup de Grace", ""],
            "statShards": ["Adaptive Force", "", ""],
            "runeOptions": {"Absolute Focus": {"above_health_threshold": 0}},
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
        # Replayed through pickMinorRune after every other reading is taken.
        "picks": [
            "Manaflow Band",
            "Triumph",
            "Legend: Alacrity",
            "Absorb Life",
            "Cheap Shot",
        ],
    }
    path = tmp_path_factory.mktemp("runes") / "fixture.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")
    result = subprocess.run(
        ["node", str(RUNE_HARNESS), str(APP_JS), str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


class TestThePickerBuildsTheRequestTheServerValidates:
    def test_the_payload_builder_is_the_one_place_the_page_is_serialised(
        self, rune_page_ui
    ):
        assert rune_page_ui["payload"] == {
            "keystone": "Arcane Comet",
            # Empty slots are dropped; shard slots are positional and trimmed.
            "minor_runes": ["Absolute Focus", "Scorch", "Coup de Grace"],
            "stat_shards": ["Adaptive Force"],
            "rune_options": {"Absolute Focus": {"above_health_threshold": 0}},
        }

    def test_what_it_builds_is_a_page_the_server_accepts(self, rune_page_ui):
        payload = rune_page_ui["payload"]
        page = rune_effects.validate_rune_page(
            payload["keystone"],
            payload["minor_runes"],
            payload["stat_shards"],
            payload["rune_options"],
        )
        assert page.minor_runes == tuple(payload["minor_runes"])
        assert page.stat_shards == tuple(payload["stat_shards"])

    def test_picking_can_only_reach_a_page_the_server_accepts(self, rune_page_ui):
        """Legality is the picker's own state transition, not a filtered list
        of offers: a primary pick lands in its own row, a secondary pick starts
        the pair, a same-row pick replaces, and a pick from a third path
        restarts the pair rather than leaving two paths on the page."""
        assert rune_page_ui["picks"] == [
            # Arcane Comet is Sorcery, so a Sorcery rune lands in its own row.
            [
                "Manaflow Band",
                ["Manaflow Band", "Absolute Focus", "Scorch", "Coup de Grace", ""],
            ],
            # An off-path pick joins the secondary pair the page already holds.
            [
                "Triumph",
                [
                    "Manaflow Band",
                    "Absolute Focus",
                    "Scorch",
                    "Coup de Grace",
                    "Triumph",
                ],
            ],
            # A third, on its own row, drops the oldest of the pair.
            [
                "Legend: Alacrity",
                [
                    "Manaflow Band",
                    "Absolute Focus",
                    "Scorch",
                    "Triumph",
                    "Legend: Alacrity",
                ],
            ],
            # Same row as Triumph, so it replaces Triumph, not Alacrity.
            [
                "Absorb Life",
                [
                    "Manaflow Band",
                    "Absolute Focus",
                    "Scorch",
                    "Legend: Alacrity",
                    "Absorb Life",
                ],
            ],
            # A third path restarts the pair — two secondary paths never coexist.
            [
                "Cheap Shot",
                ["Manaflow Band", "Absolute Focus", "Scorch", "Cheap Shot", ""],
            ],
        ]
        for _, page in rune_page_ui["picks"]:
            minors = [name for name in page if name]
            if len(minors) == 5:
                rune_effects.validate_rune_page("Arcane Comet", minors, [])

    def test_the_shard_rows_are_the_published_table(self, rune_page_ui):
        assert rune_page_ui["shardChoices"] == [
            ["Adaptive Force", "Attack Speed", "Cooldown Reduction"],
            ["Adaptive Force", "Movement Speed", "Health Scaling"],
            ["Health", "Tenacity and Slow Resist", "Health Scaling"],
        ]

    def test_eight_enabled_slots_and_the_option_carries_its_disclosure(
        self, rune_page_ui
    ):
        rows = rune_page_ui["rows"]
        assert rows.count('data-picker="minor-rune"') == 5
        assert rows.count('data-picker="stat-shard"') == 3
        assert "disabled" not in rows
        assert 'data-rune-option="above_health_threshold"' in rows
        assert "0 turns the grant off" in rows

    def test_each_option_renders_the_control_its_kind_declares(self, rune_page_ui):
        """A switch is a checkbox; a count is a bounded number input."""
        rows = rune_page_ui["rows"]
        assert (
            '<input type="checkbox" data-rune-option="above_health_threshold"' in rows
        )
        assert '<input type="number" step="1" min="0" max="10"' in rows
        assert 'data-rune-option="stacks"' in rows

    def test_the_picker_reads_its_side_from_the_path_it_was_opened_on(
        self, rune_page_ui
    ):
        assert rune_page_ui["sides"] == ["A", "B", "B", "A"]

    def test_copy_a_to_b_copies_the_whole_page(self, rune_page_ui):
        assert rune_page_ui["copied"] == {
            "keystone": "Arcane Comet",
            "minorRunes": ["", "Absolute Focus", "Scorch", "Coup de Grace", ""],
            "statShards": ["Adaptive Force", "", ""],
            "runeOptions": {"Absolute Focus": {"above_health_threshold": 0}},
        }
