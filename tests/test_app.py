"""Route-level contracts for shared fight request parsing."""

from dataclasses import replace

import pytest

import src.app as app_module


def test_calculate_and_optimize_share_fight_request_semantics(monkeypatch):
    captured = {}
    champion_data = {"name": "Ahri"}

    monkeypatch.setattr(app_module, "get_champion", lambda _name: champion_data)

    def fake_run_fight(data, level, items, params):
        captured["calculate"] = params
        return {
            "champion_stats": {},
            "breakdown": {},
            "total_damage": 0.0,
            "auto_attack_damage": 0.0,
            "ability_damage": 0.0,
            "damage_by_type": {"physical": 0.0, "magic": 0.0, "true": 0.0},
            "effective_mr": params.target_magic_resistance,
            "effective_armor": params.target_armor,
            "notes": [],
        }

    def fake_optimize_build(*, fight_params, **_kwargs):
        captured["optimize"] = fight_params
        return {"items": [], "total_damage": 0.0}

    monkeypatch.setattr(app_module, "run_fight", fake_run_fight)
    monkeypatch.setattr(app_module, "optimize_build", fake_optimize_build)

    payload = {
        "champion": "Ahri",
        "level": 18,
        "fight_mode": "auto_only",
        "fight_duration": 12,
        "include_auto_attacks": False,
        "auto_attack_uptime": 0.7,
        "auto_attacks_only": True,
        "target_health": 2400,
        "target_bonus_health": 600,
        "target_armor": 80,
        "target_mr": 70,
    }

    client = app_module.app.test_client()
    calculate_response = client.post("/api/calculate", json=payload)
    optimize_response = client.post("/api/optimize", json=payload)

    assert calculate_response.status_code == 200
    assert optimize_response.status_code == 200
    assert captured["calculate"].auto_attack_uptime == 0.7
    assert captured["calculate"] == replace(captured["optimize"], deterministic=False)


def test_config_exposes_all_request_defaults():
    response = app_module.app.test_client().get("/api/config")

    assert response.status_code == 200
    data = response.get_json()
    assert data["default_target"] == {
        "health": 1000.0,
        "bonus_health": 0.0,
        "armor": 100.0,
        "mr": 100.0,
    }
    assert data["fight_defaults"] == {
        "mode": "one_rotation",
        "duration_seconds": 8.0,
        "auto_attack_uptime": 0.8,
        "one_rotation_duration_seconds": 5.0,
    }


class TestIconUrlsAreHttps:
    """The wiki cache stores Data Dragon icon URLs as http://; the site
    serves over https, so browsers flag every icon as mixed content.
    app.py normalizes the scheme at the API boundary — the cache itself
    stays whatever the scraper wrote."""

    def test_champion_and_item_icons_are_https(self):
        client = app_module.app.test_client()
        champs = client.get("/api/champions").get_json()
        items = client.get("/api/items").get_json()
        boots = client.get("/api/boots").get_json()

        icons = [c["icon"] for c in champs] + [i["icon"] for i in items + boots]
        assert icons
        assert not [u for u in icons if u.startswith("http://")]

    def test_ability_icons_are_https(self):
        abilities = app_module.app.test_client().get("/api/abilities/Aatrox").get_json()

        assert all(not a["icon"].startswith("http://") for a in abilities.values())


class TestChampionVerifiedFlags:
    """/api/champions marks module-backed champions verified; the picker
    greys out the rest (generic-path numbers are estimates — CLAUDE.md
    rule 6). Verified champions sort first, then unverified, A-Z within
    each group."""

    def test_flags_match_the_module_registry(self):
        champs = app_module.app.test_client().get("/api/champions").get_json()
        by_name = {c["name"]: c["verified"] for c in champs}

        assert by_name["Aatrox"] is True
        assert by_name["Bel'Veth"] is True
        assert by_name["Kled"] is False
        assert by_name["Teemo"] is False

    def test_verified_champions_sort_first(self):
        champs = app_module.app.test_client().get("/api/champions").get_json()
        flags = [c["verified"] for c in champs]

        assert True in flags and False in flags
        assert flags.index(False) == flags.count(True)  # no interleaving

    def test_each_group_is_alphabetical(self):
        champs = app_module.app.test_client().get("/api/champions").get_json()
        for group in (True, False):
            names = [c["name"] for c in champs if c["verified"] is group]
            assert names == sorted(names)


class TestUpdateDataDevGate:
    """/api/update-data re-scrapes the wiki and rewrites data/ — a local
    patch-day workflow, never a public endpoint. It only exists when
    LOL_CALC_DEV=1 (run_web.bat sets it; the deployed site doesn't)."""

    def test_update_data_is_404_without_dev_flag(self, monkeypatch):
        monkeypatch.delenv("LOL_CALC_DEV", raising=False)

        response = app_module.app.test_client().get("/api/update-data")

        assert response.status_code == 404

    def test_update_data_streams_events_in_dev_mode(self, monkeypatch):
        monkeypatch.setenv("LOL_CALC_DEV", "1")
        monkeypatch.setattr(
            app_module, "_run_data_update", lambda: iter([{"phase": "done"}])
        )
        refreshed = []
        monkeypatch.setattr(
            app_module, "refresh_item_effects", lambda: refreshed.append(True)
        )

        response = app_module.app.test_client().get("/api/update-data")

        assert response.status_code == 200
        assert response.mimetype == "text/event-stream"
        assert b'data: {"phase": "done"}' in response.data
        assert refreshed == [True]

    def test_config_exposes_dev_mode_off_by_default(self, monkeypatch):
        monkeypatch.delenv("LOL_CALC_DEV", raising=False)

        data = app_module.app.test_client().get("/api/config").get_json()

        assert data["dev_mode"] is False

    def test_config_exposes_dev_mode_on_when_flagged(self, monkeypatch):
        monkeypatch.setenv("LOL_CALC_DEV", "1")

        data = app_module.app.test_client().get("/api/config").get_json()

        assert data["dev_mode"] is True


@pytest.mark.parametrize("slot_count", [1, 2, 3, 4, 5, 6])
def test_optimize_accepts_slot_counts_one_through_six(monkeypatch, slot_count):
    monkeypatch.setattr(app_module, "get_champion", lambda _name: {"name": "Ahri"})
    monkeypatch.setattr(
        app_module,
        "optimize_build",
        lambda **_kwargs: {"items": [], "total_damage": 0.0},
    )

    payload = {"champion": "Ahri", "level": 18, "max_legendary_slots": slot_count}
    response = app_module.app.test_client().post("/api/optimize", json=payload)

    assert response.status_code == 200


@pytest.mark.parametrize("slot_count", [0, 7, -1])
def test_optimize_rejects_slot_counts_outside_one_through_six(monkeypatch, slot_count):
    monkeypatch.setattr(app_module, "get_champion", lambda _name: {"name": "Ahri"})

    payload = {"champion": "Ahri", "level": 18, "max_legendary_slots": slot_count}
    response = app_module.app.test_client().post("/api/optimize", json=payload)

    assert response.status_code == 400
    assert "max_legendary_slots" in response.get_json()["error"]


def test_optimize_rejects_more_locked_items_than_slots(monkeypatch):
    monkeypatch.setattr(app_module, "get_champion", lambda _name: {"name": "Ahri"})

    payload = {
        "champion": "Ahri",
        "level": 18,
        "max_legendary_slots": 2,
        "locked_items": ["Luden's Echo", "Rabadon's Deathcap", "Shadowflame"],
    }
    response = app_module.app.test_client().post("/api/optimize", json=payload)

    assert response.status_code == 400
    assert "locked" in response.get_json()["error"].lower()


@pytest.mark.parametrize(
    "invalid_values",
    [
        {"cast_order": ["Q", "Q", "E", "R"]},
        {"ability_ranks": {"Q": 6}},
        {"ability_ranks": {"R": 4}},
    ],
)
def test_calculate_and_optimize_reject_the_same_invalid_fight_params(invalid_values):
    payload = {"champion": "Ahri", "level": 18, **invalid_values}
    client = app_module.app.test_client()

    calculate = client.post("/api/calculate", json=payload)
    optimize = client.post("/api/optimize", json=payload)

    assert calculate.status_code == 400
    assert optimize.status_code == 400
    assert calculate.get_json() == optimize.get_json()


class TestBreakdownProcRowShape:
    """Proc-style breakdown rows reach the UI in ONE shape:
    count / damage_per_hit / unit="procs" — the shape app.js's detail
    cell renders ("N procs @ X each"). The procs/damage_per_proc
    spelling never left app.py's row builder, so those rows displayed
    an empty detail cell (the user-reported "no kraken procs")."""

    def test_kraken_counter_row_one_rotation_belveth(self):
        """Bel'Veth one-rotation, bare Kraken: Q's 4 dashes + 8 slashes
        (passive + Kraken AS) = 12 shared hits = 4 procs, rendered."""
        payload = {
            "champion": "Belveth",
            "level": 14,
            "items": ["Kraken Slayer"],
            "fight_mode": "one_rotation",
        }
        response = app_module.app.test_client().post("/api/calculate", json=payload)
        assert response.status_code == 200
        row = response.get_json()["breakdown"]["on_hit_Kraken Slayer"]
        assert row["count"] == 4
        assert row["unit"] == "procs"
        assert row["damage_per_hit"] is not None and row["damage_per_hit"] > 0

    def test_spellblade_row_carries_proc_detail(self):
        """Any champ + Trinity Force, timed with autos: the spellblade
        row renders its proc detail through the API."""
        payload = {
            "champion": "Ahri",
            "level": 14,
            "items": ["Trinity Force"],
            "fight_mode": "timed",
            "fight_duration": 8,
            "include_auto_attacks": True,
        }
        response = app_module.app.test_client().post("/api/calculate", json=payload)
        assert response.status_code == 200
        breakdown = response.get_json()["breakdown"]
        spellblade_rows = [
            row for key, row in breakdown.items() if key.startswith("spellblade")
        ]
        assert spellblade_rows, f"no spellblade row in {sorted(breakdown)}"
        row = spellblade_rows[0]
        assert row["count"] and row["count"] > 0
        assert row["unit"] == "procs"
        assert row["damage_per_hit"] is not None and row["damage_per_hit"] > 0

    def test_no_row_uses_the_old_proc_spelling(self):
        """The procs/damage_per_proc spelling is retired from breakdown
        rows engine-wide (Guinsoo build exercises phantom + counter)."""
        payload = {
            "champion": "Belveth",
            "level": 14,
            "items": ["Kraken Slayer", "Guinsoo's Rageblade", "Trinity Force"],
            "fight_mode": "timed",
            "fight_duration": 8,
            "include_auto_attacks": True,
        }
        response = app_module.app.test_client().post("/api/calculate", json=payload)
        assert response.status_code == 200
        for key, row in response.get_json()["breakdown"].items():
            assert "procs" not in row, key
            assert "damage_per_proc" not in row, key
