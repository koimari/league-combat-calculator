"""Route-level contracts for shared fight request parsing."""

from dataclasses import replace
from pathlib import Path
import base64
import hashlib
import sqlite3

import pytest

import src.app as app_module
from src.rate_limit import TokenBucketStore


@pytest.fixture(autouse=True)
def _disable_rate_limits_between_route_tests():
    """Only dedicated tests spend the production abuse-control budget."""
    previous = app_module.app.config.get("RATE_LIMIT_ENABLED", True)
    app_module.app.config["RATE_LIMIT_ENABLED"] = False
    yield
    app_module.app.config["RATE_LIMIT_ENABLED"] = previous


def test_index_uses_scryglass_editorial_shell_without_changing_calculator_contract():
    response = app_module.app.test_client().get("/")
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Scryglass — Item calculator" in page
    assert 'class="brand" href="https://scryglass.xyz/"' in page
    assert "<h1>Item calculator</h1>" in page
    for required_id in (
        "builder",
        "winnerVisual",
        "scoreGrid",
        "resistanceOutput",
        "damageBreakdown",
        "rotationTable",
    ):
        assert f'id="{required_id}"' in page


def _test_password_hash(password="secret"):
    salt = b"test-scryglass-salt"
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16_384, r=8, p=1)
    enc = lambda value: base64.urlsafe_b64encode(value).rstrip(b"=").decode()
    return f"scrypt$16384$8$1${enc(salt)}${enc(digest)}"


def test_password_auth_gate_fails_closed_without_configuration(monkeypatch):
    monkeypatch.setenv("SCRYGLASS_AUTH_REQUIRED", "1")
    monkeypatch.delenv("SCRYGLASS_AUTH_SECRET", raising=False)
    monkeypatch.delenv("SCRYGLASS_AUTH_USERS", raising=False)

    client = app_module.app.test_client()
    gated = client.get("/", follow_redirects=False)
    assert gated.status_code == 302
    assert gated.headers["Location"].endswith("/auth/login?next=/")
    assert client.get("/healthz").get_json() == {"status": "ok"}
    login_setup = client.get("/auth/login")
    assert login_setup.status_code == 503
    assert "SCRYGLASS_AUTH_SECRET" in login_setup.get_json()["error"]


def test_password_auth_accepts_only_configured_accounts(monkeypatch):
    monkeypatch.setenv("SCRYGLASS_AUTH_REQUIRED", "1")
    monkeypatch.setenv("SCRYGLASS_AUTH_SECRET", "test-auth-secret")
    monkeypatch.setenv(
        "SCRYGLASS_AUTH_USERS",
        '{"LSAccessAccount":"%s","SkywayAccessAccount":"%s","KoiAccessAccount":"%s"}'
        % (
            _test_password_hash(),
            _test_password_hash("skyway-secret"),
            _test_password_hash("koi-secret"),
        ),
    )
    client = app_module.app.test_client()
    assert client.get("/", follow_redirects=False).status_code == 302
    bad = client.post(
        "/auth/login", data={"username": "LSAccessAccount", "password": "wrong"}
    )
    assert bad.status_code == 401
    good = client.post(
        "/auth/login",
        data={"username": "LSAccessAccount", "password": "secret", "next": "/"},
        follow_redirects=False,
    )
    assert good.status_code == 302
    assert good.headers["Location"].endswith("/")
    assert (
        client.get("/auth/status").get_json()["user"]["username"] == "LSAccessAccount"
    )
    page = client.get("/")
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert "Signed in as <strong>LSAccessAccount</strong>" in body
    assert "/auth/logout" in body
    assert "Articles" not in body and "Ratings" not in body and "Matches" not in body
    assert 'data-theme="dark"' in body

    client = app_module.app.test_client()
    koi = client.post(
        "/auth/login",
        data={"username": "KoiAccessAccount", "password": "koi-secret", "next": "/"},
        follow_redirects=False,
    )
    assert koi.status_code == 302
    assert (
        client.get("/auth/status").get_json()["user"]["username"] == "KoiAccessAccount"
    )
    assert (
        client.post(
            "/auth/login",
            data={"username": "Admin", "password": "koi-secret"},
        ).status_code
        == 401
    )


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
        "fight_duration": 10,
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


@pytest.mark.parametrize(
    ("endpoint", "payload"),
    [
        ("/api/calculate", ["Aatrox"]),
        ("/api/optimize", ["Aatrox"]),
        ("/api/calculate", {"champion": "Aatrox", "level": "nope"}),
        ("/api/optimize", {"champion": "Aatrox", "level": "nope"}),
        ("/api/calculate", {"champion": {}, "level": 18}),
        ("/api/optimize", {"champion": {}, "level": 18}),
        (
            "/api/calculate",
            {"champion": "Aatrox", "fight_mode": "timed", "fight_duration": 31},
        ),
        (
            "/api/optimize",
            {"champion": "Aatrox", "fight_mode": "timed", "fight_duration": 31},
        ),
        ("/api/calculate", {"champion": "Aatrox", "target_health": "nan"}),
        ("/api/optimize", {"champion": "Aatrox", "target_health": "inf"}),
        ("/api/calculate", {"champion": "Aatrox", "ability_ranks": []}),
        ("/api/optimize", {"champion": "Aatrox", "champion_options": []}),
        ("/api/calculate", {"champion": "Aatrox", "include_crossover": "yes"}),
        ("/api/calculate", {"champion": "Aatrox", "cast_order": [{}, "W", "E", "R"]}),
        ("/api/calculate", {"champion": "Aatrox", "ability_ranks": {"Q": 1.5}}),
        (
            "/api/calculate",
            {"champion": "Aatrox", "champion_options": {"unknown": True}},
        ),
        (
            "/api/calculate",
            {"champion": "Aatrox", "champion_options": {"sweetspot": "false"}},
        ),
        (
            "/api/calculate",
            {"champion": "Kai'Sa", "champion_options": {"q_evolved": "maybe"}},
        ),
        (
            "/api/optimize",
            {"champion": "Kai'Sa", "champion_options": {"w_evolved": 1}},
        ),
        ("/api/calculate", {"champion": "Aatrox", "items": "Kraken Slayer"}),
        (
            "/api/calculate",
            {"champion": "Aatrox", "items": ["Kraken Slayer"] * 7},
        ),
        ("/api/optimize", {"champion": "Aatrox", "locked_items": "Kraken Slayer"}),
    ],
)
def test_public_post_routes_reject_malformed_or_unbounded_input(endpoint, payload):
    response = app_module.app.test_client().post(endpoint, json=payload)

    assert response.status_code == 400
    assert response.is_json
    assert response.get_json()["error"]


def test_public_post_routes_reject_request_bodies_over_32_kib():
    response = app_module.app.test_client().post(
        "/api/calculate",
        json={"champion": "Aatrox", "padding": "x" * 33_000},
    )

    assert response.status_code == 413
    assert response.get_json() == {"error": "Request body exceeds 32 KiB"}


def test_public_bounds_accept_the_existing_ui_maxima():
    response = app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Aatrox",
            "level": 20,
            "role": "top",
            "role_quest_complete": True,
            "fight_mode": "timed",
            "fight_duration": 10,
            "include_auto_attacks": True,
            "auto_attack_uptime": 1,
            "target_health": 10_000,
            "target_bonus_health": 10_000,
            "target_armor": 500,
            "target_mr": 500,
        },
    )

    assert response.status_code == 200


def test_loadout_stats_returns_champion_derived_full_matrix():
    response = app_module.app.test_client().post(
        "/api/loadout-stats",
        json={
            "champion": "Galio",
            "level": 12,
            "items": ["Hollow Radiance"],
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["champion"] == "Galio"
    assert data["stats"]["health"] == 2240
    assert data["stats"]["base_health"] == 1840
    assert data["stats"]["bonus_health"] == 400
    assert data["stats"]["magic_resistance"] == 92


def test_calculate_exposes_immolate_cadence_in_the_shared_frontend_ledger():
    response = app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Galio",
            "level": 12,
            "role": "mid",
            "items": ["Bami's Cinder"],
            "enemies": [{"champion": "Ahri", "level": 12, "role": "mid"}],
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["timeline_coverage"]["complete"] is True
    assert "immolate_Bami's Cinder" in data["timeline_coverage"]["exact_sources"]
    events = [
        event
        for event in data["combat"]["events"]
        if event["source"] == "immolate_Bami's Cinder"
    ]
    assert [event["time"] for event in events] == [1.0, 2.0, 3.0, 4.0, 5.0]


def test_calculate_applies_self_granted_annie_molten_shield():
    response = app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Annie",
            "level": 12,
            "enemies": [{"champion": "Ahri", "level": 12}],
        },
    )

    assert response.status_code == 200
    main = next(
        row
        for row in response.get_json()["combat"]["participants"]
        if row["participant_id"] == "main"
    )
    assert main["survival"]["support_shield_received"] == 60.0


def test_loadout_stats_exposes_target_item_coverage_without_hiding_the_card():
    response = app_module.app.test_client().post(
        "/api/loadout-stats",
        json={"champion": "Galio", "level": 12, "items": ["Banshee's Veil"]},
    )

    assert response.status_code == 200
    coverage = response.get_json()["target_model_coverage"]
    assert coverage["complete"] is True
    assert coverage["blocked"] == []


def test_calculate_applies_an_opening_enemy_spell_shield():
    response = app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Ziggs",
            "level": 12,
            "enemies": [
                {"champion": "Galio", "level": 12, "items": ["Banshee's Veil"]}
            ],
        },
    )

    assert response.status_code == 200
    body = response.get_json()
    galio = next(
        row for row in body["combat"]["participants"] if row["champion"] == "Galio"
    )
    assert galio["survival"]["spell_shield_used"] is True
    blocked = [
        event
        for event in body["combat"]["events"]
        if event.get("skipped_reason") == "spell_shield"
    ]
    assert blocked
    assert all(
        event["spell_shield_source"] == "Banshee's Veil — Annul" for event in blocked
    )


def test_calculate_applies_kaenic_starting_magic_shield():
    response = app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Ziggs",
            "level": 12,
            "enemies": [
                {"champion": "Kai'Sa", "level": 14, "items": ["Kaenic Rookern"]}
            ],
        },
    )

    assert response.status_code == 200
    target = response.get_json()["targets"][0]
    expected_shield = target["target"]["stats"]["health"] * 0.15
    assert target["target"]["starting_defenses"]["magic_shield"] == pytest.approx(
        expected_shield, abs=0.1
    )
    assert target["result"]["magic_shield_absorbed"] > 0


def test_calculate_applies_shieldbow_lifeline_in_one_rotation():
    response = app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Ziggs",
            "level": 18,
            "items": ["Rabadon's Deathcap", "Shadowflame"],
            "enemies": [
                {
                    "champion": "Kai'Sa",
                    "level": 18,
                    "items": ["Immortal Shieldbow"],
                }
            ],
        },
    )

    assert response.status_code == 200
    target = response.get_json()["targets"][0]
    assert target["target"]["starting_defenses"]["threshold_shield"]["amount"] == 700
    assert target["result"]["threshold_shield_absorbed"] > 0


def test_calculate_prices_steraks_lifeline_in_certified_timed_fight():
    response = app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Ahri",
            "level": 18,
            "items": ["Liandry's Torment", "Shadowflame", "Rabadon's Deathcap"],
            "fight_mode": "timed",
            "fight_duration": 10,
            "enemies": [
                {
                    "champion": "Galio",
                    "level": 18,
                    "items": ["Sterak's Gage"],
                }
            ],
        },
    )

    assert response.status_code == 200
    target = response.get_json()["targets"][0]
    assert target["result"]["timeline_coverage"]["complete"] is True
    assert target["target"]["starting_defenses"]["threshold_shield"]["amount"] > 0
    assert target["result"]["threshold_shield_absorbed"] > 0


def test_calculate_withholds_uncertified_timed_fight_against_lifeline():
    response = app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Ziggs",
            "level": 18,
            "items": ["Muramana"],
            "fight_mode": "timed",
            "fight_duration": 10,
            "enemies": [
                {
                    "champion": "Galio",
                    "level": 18,
                    "items": ["Sterak's Gage"],
                }
            ],
        },
    )

    assert response.status_code == 400
    error = response.get_json()["error"]
    assert "Sterak's Gage" in error
    assert "muramana_ability" in error
    assert "not event-certified" in error


def test_timed_fight_rejects_one_rotation_only_enemy_module_cleanly():
    """The coupled timeline runs every roster member as an attacker, so a
    timed window with a one-rotation-only enemy module is a clean 400
    naming the member — never an uncaught 500 mid-timeline."""
    response = app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Ahri",
            "level": 18,
            "items": ["Rabadon's Deathcap"],
            "fight_mode": "timed",
            "fight_duration": 10,
            "enemies": [{"champion": "Kai'Sa", "level": 18, "items": []}],
        },
    )

    assert response.status_code == 400
    error = response.get_json()["error"]
    assert "Enemy Kai'Sa" in error
    assert "One Rotation" in error


def test_timed_fight_rejects_one_rotation_only_ally_module_cleanly():
    response = app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Ahri",
            "level": 18,
            "items": ["Rabadon's Deathcap"],
            "fight_mode": "timed",
            "fight_duration": 10,
            "allies": [{"champion": "Vi", "level": 18, "items": []}],
        },
    )

    assert response.status_code == 400
    error = response.get_json()["error"]
    assert "Ally Vi" in error
    assert "One Rotation" in error


def test_one_rotation_fight_still_accepts_one_rotation_only_enemy_module():
    response = app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Ahri",
            "level": 18,
            "items": ["Rabadon's Deathcap"],
            "enemies": [{"champion": "Kai'Sa", "level": 18, "items": []}],
        },
    )

    assert response.status_code == 200
    assert response.get_json()["scenario"]["primary_target"] == "Kai'Sa"


def test_crossover_curve_fails_closed_for_uncertified_lifeline_enemy():
    """The curve's timed windows need the same certified-timeline gate.

    A one-rotation request keeps its primary result, but the crossover
    curve silently re-runs the fight in timed mode; against a Lifeline
    enemy that pricing needs a certified event order.
    """
    response = app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Ziggs",
            "level": 18,
            "items": ["Muramana"],
            "include_crossover": True,
            "enemies": [
                {
                    "champion": "Galio",
                    "level": 18,
                    "items": ["Sterak's Gage"],
                }
            ],
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["total_damage"] > 0
    assert data["comparison_curve"] == []
    status = data["comparison_curve_status"]
    assert status["available"] is False
    assert "Sterak's Gage" in status["reason"]
    assert "not event-certified" in status["reason"]


def test_crossover_curve_stays_available_for_certified_lifeline_enemy():
    response = app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Ahri",
            "level": 18,
            "items": ["Liandry's Torment", "Shadowflame", "Rabadon's Deathcap"],
            "include_crossover": True,
            "enemies": [
                {
                    "champion": "Galio",
                    "level": 18,
                    "items": ["Sterak's Gage"],
                }
            ],
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["comparison_curve_status"] == {"available": True}
    assert len(data["comparison_curve"]) == 6


def test_calculate_can_sum_one_damage_package_across_enemy_roster():
    client = app_module.app.test_client()
    payload = {
        "champion": "Ziggs",
        "level": 12,
        "items": ["Luden's Echo"],
        "enemies": [
            {
                "champion": "Galio",
                "level": 12,
                "items": ["Hollow Radiance"],
            },
            {"champion": "Kai'Sa", "level": 14, "items": []},
        ],
        "allies": [{"champion": "Orianna", "level": 12, "items": []}],
    }

    response = client.post("/api/calculate", json=payload)

    assert response.status_code == 200
    data = response.get_json()
    assert data["scenario"]["target_count"] == 2
    assert data["scenario"]["primary_target"] == "Galio"
    assert [row["target"]["champion"] for row in data["targets"]] == [
        "Galio",
        "Kai'Sa",
    ]
    assert data["targets"][0]["target"]["stats"]["bonus_health"] == 400
    assert data["allies"][0]["champion"] == "Orianna"
    assert data["scenario"]["ally_effects"]["unmodeled"] == ["Orianna"]
    assert data["total_damage"] == round(
        sum(row["result"]["total_damage"] for row in data["targets"]), 1
    )
    assert data["damage_by_type"]["magic"] == round(
        sum(row["result"]["damage_by_type"]["magic"] for row in data["targets"]),
        1,
    )
    assert data["timeline_coverage"]["complete"] is True
    assert "passive" in data["timeline_coverage"]["exact_sources"]
    assert "proc_Luden's Echo" in data["timeline_coverage"]["exact_sources"]
    assert all("timeline_coverage" in row["result"] for row in data["targets"])


def test_calculate_comparison_curve_recomputes_six_timed_windows():
    response = app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Ziggs",
            "level": 12,
            "items": ["Liandry's Torment"],
            "include_crossover": True,
            "enemies": [
                {
                    "champion": "Galio",
                    "level": 12,
                    "items": ["Hollow Radiance"],
                }
            ],
        },
    )

    assert response.status_code == 200
    curve = response.get_json()["comparison_curve"]
    assert [point["rotation"] for point in curve] == [1, 2, 3, 4, 5, 6]
    assert [point["seconds"] for point in curve] == [5, 10, 15, 20, 25, 30]
    assert all(point["total_damage"] > 0 for point in curve)
    assert all(point["dps"] > 0 for point in curve)
    assert curve[-1]["total_damage"] > curve[0]["total_damage"]


def test_calculate_models_protoplasm_as_health_and_healing_not_a_shield():
    response = app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Ziggs",
            "level": 12,
            "items": ["Liandry's Torment"],
            "enemies": [
                {
                    "champion": "Shen",
                    "level": 7,
                    "items": ["Protoplasm Harness"],
                }
            ],
        },
    )

    assert response.status_code == 200
    target = response.get_json()["targets"][0]
    defense = target["target"]["starting_defenses"]
    assert defense["threshold_shield"]["amount"] == 0
    assert defense["threshold_health"] == {
        "bonus_health": 170.6,
        "healing": 205.9,
        "health_ratio": 0.3,
        "duration": 5.0,
    }
    result = target["result"]
    assert result["threshold_health_triggered"] is False
    assert result["target_healing_received"] == 0
    assert result["target_ending_health"] < target["target"]["stats"]["health"]


def test_optimizer_scores_every_selected_enemy(monkeypatch):
    captured = {}

    def fake_optimize_build(**kwargs):
        captured.update(kwargs)
        return {"items": [], "boots": None, "total_damage": 0.0}

    monkeypatch.setattr(app_module, "optimize_build", fake_optimize_build)
    response = app_module.app.test_client().post(
        "/api/optimize",
        json={
            "champion": "Ziggs",
            "level": 12,
            "enemies": [
                {
                    "champion": "Galio",
                    "level": 12,
                    "items": ["Hollow Radiance"],
                },
                {"champion": "Kai'Sa", "level": 14},
            ],
        },
    )

    assert response.status_code == 200
    targets = captured["target_fight_params"]
    assert len(targets) == 2
    assert targets[0].target_health == 2240
    assert targets[0].target_bonus_health == 400
    assert targets[0].target_magic_resistance == 92
    assert targets[1].target_health == 1873
    assert [target.roster_target_index for target in targets] == [0, 1]
    assert [target.roster_target_count for target in targets] == [2, 2]


def test_enabled_ally_staff_buff_changes_attacker_stats_and_damage():
    client = app_module.app.test_client()
    base = client.post(
        "/api/calculate", json={"champion": "Ziggs", "level": 12}
    ).get_json()
    buffed_response = client.post(
        "/api/calculate",
        json={
            "champion": "Ziggs",
            "level": 12,
            "allies": [
                {
                    "champion": "Nami",
                    "level": 12,
                    "items": ["Staff of Flowing Water"],
                    "ally_effects_enabled": True,
                }
            ],
        },
    )

    assert buffed_response.status_code == 200
    buffed = buffed_response.get_json()
    assert buffed["champion_stats"]["ability_power"] == 40
    assert buffed["champion_stats"]["ability_haste"] == 15
    assert buffed["total_damage"] > base["total_damage"]
    assert buffed["scenario"]["ally_effects"]["modeled"] == [
        "Staff of Flowing Water — Rapids"
    ]


def test_ludens_charges_are_shared_across_selected_targets():
    response = app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Ziggs",
            "level": 12,
            "items": ["Luden's Echo"],
            "enemies": [
                {"champion": "Ahri", "level": 1},
                {"champion": "Lux", "level": 1},
            ],
        },
    )

    assert response.status_code == 200
    targets = response.get_json()["targets"]
    primary = targets[0]["result"]["breakdown"]["proc_Luden's Echo"]
    secondary = targets[1]["result"]["breakdown"]["proc_Luden's Echo"]
    # Two targets: primary + four repeated 20% charges = 1.8x; the
    # secondary receives one full charge. Solo pricing is 2.0x.
    assert primary["total_damage"] / secondary["total_damage"] == pytest.approx(
        1.8, rel=0.02
    )


def test_optimize_rejects_unknown_locked_items_as_client_input():
    response = app_module.app.test_client().post(
        "/api/optimize",
        json={"champion": "Aatrox", "locked_items": ["Definitely Not An Item"]},
    )

    assert response.status_code == 404
    assert response.get_json() == {"error": "Item 'Definitely Not An Item' not found"}


@pytest.mark.parametrize("endpoint", ["/api/calculate", "/api/optimize"])
def test_public_post_routes_accept_all_dedicated_champion_modules(
    monkeypatch, endpoint
):
    class RecordingLimiter:
        calls = 0

        def consume(self, *_args, **_kwargs):
            self.calls += 1
            return True, 0.0

    limiter = RecordingLimiter()
    monkeypatch.setattr(app_module, "_rate_limiter", limiter)
    app_module.app.config["RATE_LIMIT_ENABLED"] = True
    payload = {
        "champion": "Kled",
        "level": 20,
        "role": "top",
        "role_quest_complete": True,
        "fight_mode": "timed",
        "fight_duration": 10,
        "include_auto_attacks": True,
        "auto_attack_uptime": 1,
        "target_health": 10_000,
        "target_bonus_health": 10_000,
        "target_armor": 500,
        "target_mr": 500,
        "max_legendary_slots": 6,
    }

    response = app_module.app.test_client().post(endpoint, json=payload)

    assert response.status_code != 422
    assert not response.get_json().get("error", "").endswith("not verified")


def test_optimizer_global_bucket_returns_json_429(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "get_champion", lambda _name: {"name": "Ahri"})
    monkeypatch.setattr(
        app_module,
        "optimize_build",
        lambda **_kwargs: {"items": [], "total_damage": 0.0},
    )
    monkeypatch.setattr(
        app_module,
        "_rate_limiter",
        TokenBucketStore(tmp_path / "rate-limits.sqlite3"),
        raising=False,
    )
    app_module.app.config["RATE_LIMIT_ENABLED"] = True
    client = app_module.app.test_client()

    responses = [
        client.post("/api/optimize", json={"champion": "Ahri", "level": 18})
        for _ in range(3)
    ]

    assert [response.status_code for response in responses] == [200, 200, 429]
    assert responses[-1].get_json() == {"error": "Optimizer is busy; retry shortly"}
    assert int(responses[-1].headers["Retry-After"]) >= 1


def test_optimizer_budget_caps_measured_worst_case_cpu_share():
    capacity, refill_per_second = app_module._RATE_LIMIT_POLICIES["optimize"]

    assert capacity == 2
    assert 1.81 * refill_per_second <= 0.20


def test_rate_limit_store_failure_fails_closed(monkeypatch):
    class BrokenLimiter:
        def consume(self, *_args, **_kwargs):
            raise sqlite3.OperationalError("disk unavailable")

    monkeypatch.setattr(app_module, "_rate_limiter", BrokenLimiter())
    app_module.app.config["RATE_LIMIT_ENABLED"] = True

    response = app_module.app.test_client().post(
        "/api/calculate", json={"champion": "Aatrox"}
    )

    assert response.status_code == 503
    assert response.get_json() == {"error": "Rate-limit service unavailable"}
    assert response.headers["Retry-After"] == "1"


def test_malformed_requests_do_not_spend_the_expensive_work_budget(monkeypatch):
    class RecordingLimiter:
        calls = 0

        def consume(self, *_args, **_kwargs):
            self.calls += 1
            return True, 0.0

    limiter = RecordingLimiter()
    monkeypatch.setattr(app_module, "_rate_limiter", limiter)
    app_module.app.config["RATE_LIMIT_ENABLED"] = True

    response = app_module.app.test_client().post("/api/optimize", json=[])

    assert response.status_code == 400
    assert limiter.calls == 0


@pytest.mark.parametrize("path", ["/", "/api/config", "/not-found"])
def test_security_headers_cover_html_json_and_errors(path):
    response = app_module.app.test_client().get(path)

    assert response.headers["Strict-Transport-Security"] == (
        "max-age=31536000; includeSubDomains"
    )
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert response.headers["Permissions-Policy"] == (
        "camera=(), geolocation=(), microphone=()"
    )
    assert response.headers["Cross-Origin-Opener-Policy"] == "same-origin"
    assert response.headers["Cross-Origin-Resource-Policy"] == "same-origin"
    policy = response.headers["Content-Security-Policy"]
    assert "default-src 'self'" in policy
    assert "script-src 'self'" in policy
    assert "frame-ancestors 'none'" in policy
    assert "object-src 'none'" in policy
    assert "https://ddragon.leagueoflegends.com" in policy
    assert "img-src 'self' https:;" not in policy
    assert "unsafe-eval" not in policy


def test_local_http_csp_does_not_upgrade_its_own_static_assets():
    response = app_module.app.test_client().get(
        "/", environ_base={"REMOTE_ADDR": "127.0.0.1", "wsgi.url_scheme": "http"}
    )

    assert (
        "upgrade-insecure-requests" not in response.headers["Content-Security-Policy"]
    )


def test_picker_rendering_never_puts_api_strings_into_inner_html():
    source = Path("static/js/app.js").read_text(encoding="utf-8")

    assert "el.innerHTML = `" not in source
    assert "createPickerContent" in source


def test_frontend_uses_level_derived_ranks_for_nonstandard_kits():
    source = Path("static/js/app.js").read_text(encoding="utf-8")

    assert '"Elise", "Jayce", "Karma", "Nidalee", "Udyr"' in source
    assert "if (usesLevelDerivedRanks(state.attacker.champion)) return null;" in source
    assert "ability_ranks: usesLevelDerivedRanks(target.champion)" in source


def test_damage_breakdown_leads_with_result_and_keeps_event_audit_disclosed():
    source = Path("static/js/app.js").read_text(encoding="utf-8")

    assert "function breakdownOutcome" in source
    assert 'class="breakdown-outcome" role="status"' in source
    assert "function survivalStatus" in source
    assert "alive at window end" in source
    assert "revived at ${one(reviveTime)}s" in source
    assert "defeated at ${one(deathTime)}s" in source
    assert 'class="breakdown-audit"' in source
    assert 'aria-label="Event order audit"' in source


def test_bis_frontend_surfaces_backend_withheld_candidate_receipts():
    source = Path("static/js/app.js").read_text(encoding="utf-8")

    assert "result.withheld_candidates" in source
    assert "result.withheld_candidate_count" in source
    assert "withheld before timeline" in source
    assert "result.timeline_withheld_candidates" in source
    assert "result.timeline_withheld_candidate_count" in source
    assert 'aria-label="${escapeHtml(entry.name || "Candidate")} withheld"' in source
    assert "const rows = certifiedRows" in source
    assert "Partial event order is an audit receipt, never a ranked preview" in source
    assert "const partialCards = displayPartialRows.map" in source
    assert "partial event order ·" in source
    assert "certified subset · search not exhaustive" in source


def test_bis_frontend_sends_and_filters_by_the_selected_objective():
    source = Path("static/js/app.js").read_text(encoding="utf-8")

    assert (
        'payload.objective = OBJECTIVES[objective] ? objective : "overall";' in source
    )
    assert "data-bis-objective" in source
    assert "result.objective || {}" in source
    assert "bisContext.objective = objective" in source


def test_item_picker_uses_backend_coverage_and_locks_unsupported_items():
    source = Path("static/js/app.js").read_text(encoding="utf-8")

    assert "mergeItemCoverage" in source
    assert 'fetch("/api/items")' in source
    assert 'fetch("/api/boots")' in source
    assert "backendAvailable" in source
    assert "findItemByBackendName" in source
    assert "entry.targetModelCoverage" in source
    assert "itemCoverage?.calculation_eligible" in source


def test_item_mechanics_label_uses_backend_coverage_status():
    source = Path("static/js/app.js").read_text(encoding="utf-8")

    assert "item?.modelCoverage?.status" in source
    assert '["blocked", "review_pending"].includes(coverageStatus)' in source
    assert "const backendCalculated = Boolean" in source


def test_frontend_round_trips_all_backend_champion_options():
    source = Path("static/js/app.js").read_text(encoding="utf-8")
    template = Path("templates/index.html").read_text(encoding="utf-8")

    assert "function resetChampionOptions()" in source
    assert "function renderChampionOptions()" in source
    assert "state.attacker.championOptions" in source
    assert 'data-champion-option="' in source
    assert "definition.options.map((option)" in source
    assert 'id="championOptionsRow"' in template
    assert (
        '$("championOptionsRow").innerHTML = champion ? renderChampionOptions() : "";'
        in source
    )
    assert 'data-ability-hits="${ability.slot}"' in source
    assert 'data-ability-variant="${ability.slot}"' in source
    assert "function abilityBindsChampionOption(key)" in source
    assert "!abilityBindsChampionOption(option.key)" in source


def test_config_exposes_one_authoritative_capability_contract_for_every_participant():
    response = app_module.app.test_client().get("/api/config")

    assert response.status_code == 200
    contract = response.get_json()["capabilities"]
    assert contract["schema_version"] == 1
    assert set(contract["participants"]) == {"main", "enemy", "ally"}
    assert (
        contract["participants"]["enemy"]["fields"]["champion"]["state_path"]
        == "targets.*.champion"
    )
    assert (
        contract["participants"]["ally"]["fields"]["ally_effects_enabled"]["supported"]
        is True
    )
    assert (
        contract["participants"]["main"]["fields"]["ally_effects_enabled"]["supported"]
        is False
    )
    assert contract["participants"]["main"]["fields"]["ally_effects_enabled"]["reason"]
    assert contract["scenario"]["fields"]["window"]["payload_field"] == "fight_duration"
    assert (
        contract["scenario"]["fields"]["auto_attack_uptime_mode"]["payload_field"]
        == "auto_attack_uptime_mode"
    )


def test_capability_contract_has_a_frontend_control_and_serialization_for_every_supported_field():
    config = app_module.app.test_client().get("/api/config").get_json()
    contract = config["capabilities"]
    source = Path("static/js/app.js").read_text(encoding="utf-8")
    template = Path("templates/index.html").read_text(encoding="utf-8")
    frontend = f"{source}\n{template}"

    for participant in contract["participants"].values():
        for field, descriptor in participant["fields"].items():
            if not descriptor["supported"]:
                assert descriptor["reason"]
                continue
            assert descriptor["frontend_token"] in frontend, field
            assert descriptor["payload_field"] in source, field
    for field, descriptor in contract["scenario"]["fields"].items():
        assert descriptor["supported"] is True
        assert descriptor["frontend_token"] in frontend, field
        assert descriptor["payload_field"] in source, field

    assert "capabilityAttributes" in source
    assert 'attrs.push("disabled"' in source
    assert 'aria-disabled="true"' in source
    assert "engine.capabilities = config.capabilities" in source
    assert "champion_options: Object.fromEntries" in source


def test_live_builder_surfaces_backend_item_state_controls_for_all_participants():
    source = Path("static/js/app.js").read_text(encoding="utf-8")

    assert "function stackControl(path, id, compact = false)" in source
    assert "item && stackSpec(id) ? stackControl(path, id)" in source
    assert "item && stackSpec(id) ? stackControl(path, id, true)" in source
    assert 'data-stack-path="${path}"' in source
    assert "function setStackValue(path, value)" in source
    assert "engineItemOptions(itemIds, itemStacks)" in source


def test_roster_boots_are_labeled_serialized_and_applied_to_enemy_and_ally_stats():
    source = Path("static/js/app.js").read_text(encoding="utf-8")

    assert "const path = isBoots ? `${root}.${index}.boots`" in source
    assert 'const emptyLabel = isBoots ? "Add boots" : "Add item";' in source
    assert 'class="roster-slot-label">Boots</span>' in source
    assert (
        'boots: target.includeBoots && selectedBoot ? itemName(selectedBoot) : ""'
        in source
    )
    assert "include_boots: Boolean(target.includeBoots)" in source
    assert "function engineAlly(ally)" in source
    assert "function normalizeRosterRoleState(loadout)" in source
    assert "normalizeRosterRoleState(state[root]?.[Number(indexText)])" in source
    assert "normalizeAttackerSupportItemsForRole();" in source

    response = app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Ziggs",
            "level": 12,
            "enemies": [
                {
                    "champion": "Galio",
                    "level": 12,
                    "role": "mid",
                    "boots": "Sorcerer's Shoes",
                    "include_boots": True,
                }
            ],
            "allies": [
                {
                    "champion": "Nami",
                    "level": 12,
                    "role": "support",
                    "boots": "Ionian Boots of Lucidity",
                    "include_boots": True,
                }
            ],
        },
    )

    assert response.status_code == 200
    body = response.get_json()
    enemy = body["targets"][0]["target"]
    ally = body["allies"][0]
    assert enemy["items"] == ["Sorcerer's Shoes"]
    assert enemy["stats"]["magic_penetration_flat"] == 12
    assert ally["items"] == ["Ionian Boots of Lucidity"]
    assert ally["stats"]["ability_haste"] == 10


def test_roster_role_quest_control_round_trips_enemy_and_ally_state():
    source = Path("static/js/app.js").read_text(encoding="utf-8")

    assert "function rosterOrdinarySlotCount(loadout)" in source
    assert 'data-roster-quest="${root}.${index}"' in source
    assert "const roleQuestComplete = Boolean(loadout.roleQuestComplete);" in source
    assert 'class="roster-quest-toggle' in source
    assert "role_quest_complete: Boolean(target.roleQuestComplete)" in source
    assert "loadout.boots = 0;" in source

    response = app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Ziggs",
            "level": 12,
            "enemies": [
                {
                    "champion": "Galio",
                    "level": 12,
                    "role": "mid",
                    "role_quest_complete": True,
                }
            ],
            "allies": [
                {
                    "champion": "Nami",
                    "level": 12,
                    "role": "support",
                    "role_quest_complete": True,
                }
            ],
        },
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["targets"][0]["target"]["role_quest_complete"] is True
    assert body["allies"][0]["role_quest_complete"] is True


def test_resistance_table_surfaces_all_backend_starting_defense_receipts():
    source = Path("static/js/app.js").read_text(encoding="utf-8")

    assert "physical_shield" in source
    assert "general_shield" in source
    assert "threshold_shield?.amount" in source
    assert "spell_shield?.ready" in source
    assert "basic_damage_flat_reduction" in source
    assert "critical_strike_damage_multiplier" in source
    assert "<th>Starting defenses</th>" in source
    assert "magic_shield_absorbed" in source
    assert "target_healing_received" in source
    assert "main.survival?.healing_received" in source
    assert "const hasHealingReceipt" in source
    assert "main.survival?.support_shield_received" in source
    assert "support shield received" in source
    assert "aResult.damage_by_type" in source
    assert "aResult.self_healing" in source
    assert "aResult.threshold_health_triggered" in source
    assert "aResult.target_ending_health" in source
    assert "aResult.target_effective_max_health" in source
    assert "threshold_health_bonus_gained" in source
    assert "function exactSupportOutputs(result)" in source
    assert "total_amount" in source
    assert 'result.error_code === "no_complete_event_order"' in source


def test_calculate_aggregates_backend_shield_receipts_across_targets():
    response = app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Ziggs",
            "level": 12,
            "enemies": [
                {"champion": "Kai'Sa", "level": 14, "items": ["Kaenic Rookern"]},
                {"champion": "Galio", "level": 14, "items": ["Kaenic Rookern"]},
            ],
        },
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["magic_shield_absorbed"] == pytest.approx(
        sum(target["result"]["magic_shield_absorbed"] for target in body["targets"])
    )


@pytest.mark.parametrize(
    ("item", "output_key", "output_type"),
    [
        ("Essence Reaver", "mana_Essence Reaver", "mana"),
        ("Dusk and Dawn", "heal_Dusk and Dawn", "health"),
        ("Cull", "heal_Cull", "health"),
        ("Sundered Sky", "heal_Sundered Sky", "health"),
    ],
)
def test_calculate_exposes_spellblade_sibling_receipts(item, output_key, output_type):
    response = app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Ahri",
            "level": 18,
            "items": [item],
            "fight_mode": "timed",
            "fight_duration": 4,
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
        },
    )

    assert response.status_code == 200
    row = response.get_json()["breakdown"][output_key]
    assert row["total_amount"] > 0
    assert row["output_type"] == output_type


def test_optimizer_certifies_the_reviewed_champion_boundary():
    response = app_module.app.test_client().post(
        "/api/optimize",
        json={
            "champion": "Akshan",
            "level": 18,
            "fight_mode": "one_rotation",
            "include_boots": False,
            "max_legendary_slots": 1,
            "locked_items": ["Shadowflame"],
        },
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["timeline_coverage"]["complete"] is True
    assert body["timeline_coverage"]["coarse_sources"] == []
    assert body["ranked_builds"]


def test_stat_matrix_surfaces_backend_resource_and_critical_stat_fields():
    source = Path("static/js/app.js").read_text(encoding="utf-8")

    assert '["Mana regen"' in source
    assert '["Gold per 10"' in source
    assert '["Critical damage"' in source
    assert "item.manaRegen" in source
    assert "item.goldPer10" in source
    assert "item.critDamage" in source


def test_frontend_applies_backend_stat_conversion_metadata():
    source = Path("static/js/app.js").read_text(encoding="utf-8")

    assert "item.statConversions?.bonus_mana_to_health_ratio" in source
    assert "total.hp += total.mana * manaToHealthRatio" in source
    assert "item.statConversions?.bonus_mana_to_ap_ratio" in source
    assert "total.ap += total.mana * manaToApRatio" in source
    assert "item.statConversions?.bonus_health_to_ap_ratio" in source
    assert "total.ap += total.hp * healthToApRatio" in source
    assert "item.statConversions?.item_bonus_health_ratio" in source
    assert "getItem(id)?.statConversions?.base_ad_to_bonus_ad_ratio" in source
    assert "getItem(id)?.statConversions?.bonus_health_to_ad_ratio" in source
    assert "item.statConversions?.rapids_bonus_ap" in source
    assert "item.statConversions?.ap_per_mana_regen_unit" in source
    assert "bonus_attack_speed_melee" in source
    assert "bonus_attack_speed_percent" in source
    assert "max_mana_to_ad_ratio" in source


def test_primary_participant_ledger_surfaces_backend_support_events():
    source = Path("static/js/app.js").read_text(encoding="utf-8")

    assert "supportEvents = Array.isArray(aResult?.combat?.support_events)" in source
    assert 'supportRows.join("")' in source
    assert "event.target_policy || event.target_scope" in source
    assert "support shield received" in source


def test_frontend_surfaces_native_utility_and_target_allocation_receipts():
    source = Path("static/js/app.js").read_text(encoding="utf-8")

    assert "utility_outcomes?.focus" in source
    assert "Applied non-TDD outcomes" in source
    assert "speed_percent_seconds" in source
    assert "target_allocation" in source
    assert "authored roster-index policy" in source


def test_frontend_consumes_backend_calculation_defaults():
    source = Path("static/js/app.js").read_text(encoding="utf-8")

    assert "config.default_target" in source
    assert "engine.defaultTarget.health" in source
    assert "config.fight_defaults" in source
    assert "config.exclusivity_groups" in source
    assert "one_rotation_duration_seconds" in source
    assert "state.fight.duration = oneRotationDuration" in source
    assert "function optimizerExclusiveGroups()" in source
    assert "Object.values(engine.exclusivityGroups || {})" in source


def test_frontend_consumes_every_backend_item_option_and_its_stat_metadata():
    source = Path("static/js/app.js").read_text(encoding="utf-8")
    options = app_module.app.test_client().get("/api/config").get_json()["item_options"]

    assert {
        "Dark Seal",
        "Mejai's Soulstealer",
        "Heartsteel",
        "Rod of Ages",
        "Yun Tal Wildarrows",
        "Overlord's Bloodmail",
        "Zhonya's Hourglass",
        "Seeker's Armguard",
        "Locket of the Iron Solari",
        "Mikael's Blessing",
        "Redemption",
        "Shurelya's Battlesong",
        "Knight's Vow",
    } <= set(options)
    assert (
        options["Heartsteel"]["stat_effects"]["bonus_health"]["bonus_health_per_unit"]
        == 1.0
    )
    assert (
        options["Rod of Ages"]["stat_effects"]["timeless_stacks"]["bonus_mana_per_unit"]
        == 30.0
    )
    assert options["Yun Tal Wildarrows"]["derived"]["crit_chance_cap"] == 0.25
    assert (
        options["Overlord's Bloodmail"]["options"]["missing_health_percent"]["max"]
        == 70
    )
    assert (
        options["Zhonya's Hourglass"]["options"]["stasis_active_seconds"]["max"] == 2.5
    )
    assert "function itemOptionSpec(id)" in source
    assert "definition.stat_effects?.[key]" in source
    assert "options[item.backendName || item.name] = { [spec.key]" in source
    assert "LEGACY_STACK_ITEM_NAMES" in source
    assert "specs.length === 1 && LEGACY_STACK_ITEM_NAMES.has(itemName(id))" in source
    assert "crit_chance_per_stack_${suffix}" in source
    assert "bonus_attack_speed_percent" in source
    assert "on_hit_magic_damage" in source
    assert "chain_fraction" in source
    assert (
        options["Locket of the Iron Solari"]["options"]["active_seconds"]["max"] == 30.0
    )
    assert options["Knight's Vow"]["options"]["worthy_target_index"]["max"] == 4


def test_frontend_consumes_backend_sustain_stat_families():
    source = Path("static/js/app.js").read_text(encoding="utf-8")

    assert '"lifesteal", "omnivamp", "healAndShieldPower"' in source
    assert '"healthRegen", "tenacity", "manaRegen"' in source
    assert '"Life steal"' in source
    assert '"Heal/shield power"' in source
    assert "stats.lifesteal_percent" in source
    assert "stats.heal_and_shield_power_percent" in source


def test_frontend_consumes_ordered_item_targeting_receipts():
    """Stateful item scope from the backend remains visible to the UI."""
    source = Path("static/js/app.js").read_text(encoding="utf-8")

    assert "entry.temporary_lethality" in source
    assert 'targeting?.kind === "chain_lightning"' in source
    assert "targeting.chain_target_count" in source
    assert "targeting.allocated_target_index" in source
    assert 'targeting?.kind === "runaan_bolt"' in source
    assert 'targeting?.kind === "runaan_bolt_copied_on_hit"' in source
    assert 'targeting?.kind === "hydra_cleave"' in source
    assert 'targeting?.kind === "active_secondary"' in source
    assert 'targeting?.kind === "cleave_secondary"' in source


def test_frontend_consumes_standalone_self_healing_receipts():
    """Top-level standalone healing is rendered when no combat ledger exists."""
    source = Path("static/js/app.js").read_text(encoding="utf-8")

    assert "function healingEventsForResult(result)" in source
    assert "result.self_healing_events" in source
    assert "if (combatEvents.length) return combatEvents;" in source
    assert "const healingEvents = healingEventsForResult(aResult);" in source


def test_config_exclusivity_groups_cover_frontend_optimizer_families():
    groups = (
        app_module.app.test_client().get("/api/config").get_json()["exclusivity_groups"]
    )

    assert {"Spellblade", "Hydra", "Fatality", "Glory"} <= set(groups)
    assert "Lich Bane" in groups["Spellblade"]
    assert "Ravenous Hydra" in groups["Hydra"]


def test_frontend_exposes_the_full_reviewed_module_contract():
    source = Path("static/js/app.js").read_text(encoding="utf-8")

    assert 'entry.engine_registration === "reviewed_module"' in source
    assert (
        "if (entry.availability?.ready) engine.reviewed.add(entry.name);" not in source
    )
    assert "champion.engineRegistration = entry.engine_registration || null" in source
    assert "generated packet · not reviewed" not in source


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "data:image/svg+xml,<svg onload=alert(1)>",
        "//attacker.example/icon.png",
        "https://attacker.example/icon.png",
        "not a url",
    ],
)
def test_icon_api_rejects_non_http_urls(url):
    assert app_module._https_icon(url) == ""


def test_health_endpoint_is_lightweight_json():
    response = app_module.app.test_client().get("/healthz")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


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
        "auto_attack_uptime_mode": "calculated",
        "one_rotation_duration_seconds": 5.0,
    }
    assert data["champion_options"]["Soraka"]["sources"][1] == {
        "label": "Equinox",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Soraka/Equinox",
        "revision_id": 3907153,
        "revision_timestamp": "2025-06-06T18:23:34Z",
    }
    assert data["input_limits"] == {
        "fight_duration": [1.0, 30.0],
        "auto_attack_uptime": [0.0, 1.0],
        "target_health": [1.0, 10_000.0],
        "target_bonus_health": [0.0, 10_000.0],
        "target_armor": [0.0, 500.0],
        "target_mr": [0.0, 500.0],
    }
    assert data["item_options"]["Dark Seal"]["options"]["glory_stacks"]["max"] == 10
    assert (
        data["item_options"]["Mejai's Soulstealer"]["options"]["glory_stacks"]["max"]
        == 25
    )


def test_calculated_auto_uptime_is_sourced_and_used_for_jinx_one_rotation():
    client = app_module.app.test_client()
    response = client.post(
        "/api/calculate",
        json={
            "champion": "Jinx",
            "level": 12,
            "items": ["Doran's Blade"],
            "fight_mode": "one_rotation",
            "auto_attack_uptime_mode": "calculated",
            "ability_ranks": {"Q": 4, "W": 3, "E": 3, "R": 2},
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    policy = data["auto_attack_policy"]
    assert policy["status"] == "calculated"
    assert policy["uptime"] == pytest.approx(0.76)
    assert {entry["slot"] for entry in policy["components"]} == {"Q", "W", "E", "R"}
    assert data["auto_attack_damage"] > 0


def test_calculated_auto_uptime_repeats_for_timed_rotation_windows():
    response = app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Jinx",
            "level": 12,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 10,
            "rotations": 2,
            "include_auto_attacks": True,
            "auto_attack_uptime_mode": "calculated",
            "ability_ranks": {"Q": 4, "W": 3, "E": 3, "R": 2},
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["auto_attack_policy"]["status"] == "calculated"
    assert data["auto_attack_policy"]["uptime"] == pytest.approx(0.76)
    assert data["auto_attack_policy"]["rotation_mode"] == "time_based"
    assert data["auto_attack_damage"] > 0
    assert data["auto_attack_schedule"] == {
        "status": "known",
        "rotation_count": 2,
        "expected_autos_per_rotation": 5.0,
        "expected_autos_total": 10,
        "window_seconds": 10.0,
        "semantics": "sequential timed window; cooldowns, resources, cast lockouts, and item events follow the engine ledger",
    }


def test_frontend_exposes_calculated_uptime_mode_and_policy_receipt():
    source = Path("static/js/app.js").read_text(encoding="utf-8")
    template = Path("templates/index.html").read_text(encoding="utf-8")

    assert 'aaUptimeMode: "calculated"' in source
    assert "payload.auto_attack_uptime_mode = state.fight.aaUptimeMode" in source
    assert "rotations: state.fight.rotations" in source
    assert "auto_attack_schedule" in source
    assert "aResult?.auto_attack_policy" in source
    assert 'id="uptimeModeToggle"' in template
    assert 'id="uptimeOutput">CALCULATED' in template


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

    def test_manual_item_api_includes_reconstructable_partial_builds(self):
        items = app_module.app.test_client().get("/api/items").get_json()
        names = {item["name"] for item in items}

        assert {"Ruby Crystal", "Dark Seal", "Doran's Ring"} <= names

    def test_item_apis_expose_authoritative_ids_and_picker_stats(self):
        client = app_module.app.test_client()
        items = client.get("/api/items").get_json()
        boots = client.get("/api/boots").get_json()

        assert all(
            item["id"] and "price" in item and "categories" in item
            for item in items + boots
        )
        assert {item["id"] for item in items} & {2530, 3040, 3042, 3121, 3866}
        assert any(item["name"] == "Blade of the Ruined King" for item in items)
        bloodthirster = next(item for item in items if item["name"] == "Bloodthirster")
        doran_blade = next(item for item in items if item["name"] == "Doran's Blade")
        assert bloodthirster["lifesteal"] == 15.0
        # Current full Wiki entry replaces the stale cache's old omnivamp
        # stat with Life Draining, a post-mitigation heal passive.
        assert doran_blade["omnivamp"] == 0.0
        assert all(
            key in bloodthirster
            for key in (
                "lifesteal",
                "omnivamp",
                "healAndShieldPower",
                "healthRegen",
                "tenacity",
                "manaRegen",
                "goldPer10",
                "critDamage",
            )
        )
        fimbulwinter = next(item for item in items if item["name"] == "Fimbulwinter")
        assert fimbulwinter["statConversions"]["bonus_mana_to_health_ratio"] == 0.15
        muramana = next(item for item in items if item["name"] == "Muramana")
        assert muramana["statConversions"]["max_mana_to_ad_ratio"] == 0.02
        archangel = next(item for item in items if item["name"] == "Archangel's Staff")
        assert archangel["statConversions"]["bonus_mana_to_ap_ratio"] == 0.01
        riftmaker = next(item for item in items if item["name"] == "Riftmaker")
        assert riftmaker["statConversions"]["bonus_health_to_ap_ratio"] == 0.02
        bloodmail = next(
            item for item in items if item["name"] == "Overlord's Bloodmail"
        )
        assert bloodmail["statConversions"]["bonus_health_to_ad_ratio"] == 0.025
        steraks = next(item for item in items if item["name"] == "Sterak's Gage")
        assert steraks["statConversions"]["base_ad_to_bonus_ad_ratio"] == 0.45
        warmogs = next(item for item in items if item["name"] == "Warmog's Armor")
        assert warmogs["statConversions"]["item_bonus_health_ratio"] == 0.12
        dawncore = next(item for item in items if item["name"] == "Dawncore")
        assert dawncore["statConversions"]["ap_per_mana_regen_unit"] == 10.0
        hunger = next(item for item in items if item["name"] == "Endless Hunger")
        assert hunger["statConversions"]["famine_base_ability_haste"] == 5.0
        bandlepipes = next(item for item in items if item["name"] == "Bandlepipes")
        assert bandlepipes["statConversions"]["bonus_attack_speed_ranged"] == 20.0

    def test_item_apis_expose_optimizer_coverage(self):
        client = app_module.app.test_client()
        items = {item["name"]: item for item in client.get("/api/items").get_json()}
        boots = {item["name"]: item for item in client.get("/api/boots").get_json()}

        assert (
            items["Runaan's Hurricane"]["model_coverage"]["status"] == "modeled_effect"
        )
        assert (
            "copied_on_hit"
            in items["Runaan's Hurricane"]["model_coverage"]["outcome_dimensions"]
        )
        assert items["Void Staff"]["model_coverage"]["status"] == "stats_only"
        assert items["Essence Reaver"]["model_coverage"]["status"] == "modeled_effect"
        assert items["Essence Reaver"]["model_coverage"]["optimizer_eligible"] is True
        assert items["Heartsteel"]["model_coverage"]["status"] == "modeled_state"
        assert items["Rod of Ages"]["model_coverage"]["status"] == "modeled_state"
        assert items["Heartsteel"]["model_coverage"]["optimizer_eligible"] is True
        assert items["Rod of Ages"]["model_coverage"]["optimizer_eligible"] is True
        assert boots["Immortal Path"]["model_coverage"]["status"] == "blocked"
        assert items["Guardian Angel"]["model_coverage"]["outcome_dimensions"] == [
            "revive"
        ]
        assert "Rebirth" in items["Guardian Angel"]["model_coverage"]["reason"]
        assert items["Zhonya's Hourglass"]["model_coverage"]["outcome_dimensions"] == [
            "stasis"
        ]
        assert "Time Stop" in items["Zhonya's Hourglass"]["model_coverage"]["reason"]
        assert items["Runaan's Hurricane"]["target_model_coverage"]["status"]
        assert "calculation_eligible" in boots["Immortal Path"]["target_model_coverage"]

    def test_boot_api_marks_role_quest_tiers(self):
        boots = app_module.app.test_client().get("/api/boots").get_json()
        assert {boot["tier"] for boot in boots} == {2, 3}
        by_name = {boot["name"]: boot for boot in boots}
        assert by_name["Plated Steelcaps"]["upgrade_to"] == "Armored Advance"
        assert by_name["Armored Advance"]["upgrade_from"] == "Plated Steelcaps"

    def test_config_exposes_support_quest_item_gate(self):
        config = app_module.app.test_client().get("/api/config").get_json()
        support = config["role_quest"]["support_item"]
        assert support["complete_allowed_stages"] == ["upgraded"]
        assert "Dream Maker" in support["stages"]["upgraded"]
        assert "World Atlas" in support["stages"]["starter"]

    def test_boot_stats_change_damage_and_omnivamp_healing(self):
        client = app_module.app.test_client()
        base = {
            "champion": "Jinx",
            "level": 12,
            "items": [],
            "role": "bottom",
            "target_health": 2_000,
            "target_armor": 100,
            "target_mr": 100,
            "auto_attack_uptime": 1.0,
            "auto_attack_uptime_mode": "explicit",
            "fight_duration": 10,
            "enemies": [{"champion": "Galio", "level": 12, "role": "mid"}],
        }
        no_boots = client.post("/api/calculate", json=base).get_json()
        attack_speed_boots = client.post(
            "/api/calculate",
            json={**base, "boots": "Berserker's Greaves"},
        ).get_json()
        omnivamp_boots = client.post(
            "/api/calculate",
            json={**base, "boots": "Gluttonous Greaves"},
        ).get_json()
        gunmetal_response = client.post(
            "/api/calculate",
            json={
                **base,
                "role": "mid",
                "role_quest_complete": True,
                "boots": "Gunmetal Greaves",
            },
        )
        gunmetal_boots = gunmetal_response.get_json()

        assert attack_speed_boots["total_damage"] > no_boots["total_damage"]
        assert (
            attack_speed_boots["champion_stats"]["attack_speed"]
            > no_boots["champion_stats"]["attack_speed"]
        )
        assert omnivamp_boots["champion_stats"]["omnivamp_percent"] == 4.0
        main = next(
            row
            for row in omnivamp_boots["combat"]["participants"]
            if row["participant_id"] == "main"
        )
        assert main["survival"]["healing_received"] > 0
        assert gunmetal_response.status_code == 200
        assert (
            gunmetal_boots["champion_stats"]["attack_speed"]
            > no_boots["champion_stats"]["attack_speed"]
        )
        assert gunmetal_boots["champion_stats"]["lifesteal_percent"] == 5.0

    def test_completed_mid_quest_accepts_upgraded_magic_penetration_boots(self):
        response = app_module.app.test_client().post(
            "/api/calculate",
            json={
                "champion": "Ziggs",
                "level": 12,
                "role": "mid",
                "role_quest_complete": True,
                "boots": "Spellslinger's Shoes",
                "items": [],
            },
        )

        assert response.status_code == 200
        assert response.get_json()["champion_stats"]["magic_penetration_flat"] == 18.0

    def test_ability_icons_are_https(self):
        abilities = app_module.app.test_client().get("/api/abilities/Aatrox").get_json()

        assert all(not a["icon"].startswith("http://") for a in abilities.values())
        assert set(abilities) == {"P", "Q", "W", "E", "R"}
        assert all(ability["ingested"] for ability in abilities.values())
        assert abilities["Q"]["name"] == "The Darkin Blade"

    def test_champion_api_exposes_all_ingested_and_reviewed_slots(self):
        champions = app_module.app.test_client().get("/api/champions").get_json()

        assert len(champions) == 173
        assert all(champion["ability_ingestion"]["complete"] for champion in champions)
        assert all(
            set(champion["abilities"]) == {"P", "Q", "W", "E", "R"}
            for champion in champions
        )
        assert all(champion["verified"] for champion in champions)
        by_name = {champion["name"]: champion for champion in champions}
        assert by_name["Aatrox"]["engine_registration"] == "reviewed_module"
        assert by_name["Teemo"]["engine_registration"] == "reviewed_module"


class TestChampionVerifiedFlags:
    """/api/champions exposes the complete dedicated-module registry."""

    def test_flags_match_the_module_registry(self):
        champs = app_module.app.test_client().get("/api/champions").get_json()
        by_name = {c["name"]: c["verified"] for c in champs}

        assert by_name["Aatrox"] is True
        assert by_name["Bel'Veth"] is True
        assert by_name["Kled"] is True
        assert by_name["Teemo"] is True

    def test_unverified_champions_expose_specific_fail_closed_reasons(self):
        champs = app_module.app.test_client().get("/api/champions").get_json()
        by_name = {champion["name"]: champion for champion in champs}

        assert by_name["Soraka"]["availability"] == {
            "ready": True,
            "verification": "reviewed_module",
            "blockers": [],
        }
        assert by_name["Teemo"]["availability"] == {
            "ready": True,
            "verification": "reviewed_module",
            "blockers": [],
        }
        assert by_name["Teemo"]["patch_last_changed"]

    def test_verified_champions_sort_first(self):
        champs = app_module.app.test_client().get("/api/champions").get_json()
        flags = [c["verified"] for c in champs]

        assert all(flags)

    def test_each_group_is_alphabetical(self):
        champs = app_module.app.test_client().get("/api/champions").get_json()
        for group in (True,):
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

        client = app_module.app.test_client()
        config_response = client.get("/api/config")
        response = client.get("/api/update-data")

        assert "HttpOnly" in config_response.headers["Set-Cookie"]
        assert "SameSite=Strict" in config_response.headers["Set-Cookie"]
        assert response.status_code == 200
        assert response.mimetype == "text/event-stream"
        assert b'data: {"phase": "done"}' in response.data
        assert refreshed == [True]

    def test_update_data_needs_same_site_bootstrap_cookie(self, monkeypatch):
        monkeypatch.setenv("LOL_CALC_DEV", "1")

        response = app_module.app.test_client().get("/api/update-data")

        assert response.status_code == 404

    def test_dev_mode_rejects_non_local_host_even_from_loopback(self, monkeypatch):
        monkeypatch.setenv("LOL_CALC_DEV", "1")
        client = app_module.app.test_client()

        config = client.get("/api/config", headers={"Host": "attacker.example"})
        update = client.get("/api/update-data", headers={"Host": "attacker.example"})

        assert config.get_json()["dev_mode"] is False
        assert update.status_code == 404

    def test_update_data_is_404_for_remote_request_even_with_dev_flag(
        self, monkeypatch
    ):
        monkeypatch.setenv("LOL_CALC_DEV", "1")
        monkeypatch.setattr(
            app_module,
            "_run_data_update",
            lambda: pytest.fail("remote update must not run"),
        )

        response = app_module.app.test_client().get(
            "/api/update-data", environ_base={"REMOTE_ADDR": "203.0.113.10"}
        )

        assert response.status_code == 404

    def test_config_hides_dev_mode_from_remote_requests(self, monkeypatch):
        monkeypatch.setenv("LOL_CALC_DEV", "1")

        data = (
            app_module.app.test_client()
            .get("/api/config", environ_base={"REMOTE_ADDR": "203.0.113.10"})
            .get_json()
        )

        assert data["dev_mode"] is False

    def test_config_exposes_dev_mode_off_by_default(self, monkeypatch):
        monkeypatch.delenv("LOL_CALC_DEV", raising=False)

        data = app_module.app.test_client().get("/api/config").get_json()

        assert data["dev_mode"] is False

    def test_config_exposes_dev_mode_on_when_flagged(self, monkeypatch):
        monkeypatch.setenv("LOL_CALC_DEV", "1")

        data = app_module.app.test_client().get("/api/config").get_json()

        assert data["dev_mode"] is True


@pytest.mark.parametrize("slot_count", [1, 2, 3, 4, 5])
def test_optimize_accepts_standard_slot_counts(monkeypatch, slot_count):
    monkeypatch.setattr(app_module, "get_champion", lambda _name: {"name": "Ahri"})
    monkeypatch.setattr(
        app_module,
        "optimize_build",
        lambda **_kwargs: {"items": [], "total_damage": 0.0},
    )

    payload = {"champion": "Ahri", "level": 18, "max_legendary_slots": slot_count}
    response = app_module.app.test_client().post("/api/optimize", json=payload)

    assert response.status_code == 200


def test_optimize_accepts_six_items_only_after_bottom_quest(monkeypatch):
    monkeypatch.setattr(app_module, "get_champion", lambda _name: {"name": "Ahri"})
    captured = {}

    def fake_optimize(**kwargs):
        captured.update(kwargs)
        return {"items": [], "total_damage": 0.0}

    monkeypatch.setattr(app_module, "optimize_build", fake_optimize)
    client = app_module.app.test_client()

    rejected = client.post(
        "/api/optimize",
        json={"champion": "Ahri", "level": 18, "max_legendary_slots": 6},
    )
    accepted = client.post(
        "/api/optimize",
        json={
            "champion": "Ahri",
            "level": 18,
            "max_legendary_slots": 6,
            "role": "bottom",
            "role_quest_complete": True,
        },
    )

    assert rejected.status_code == 400
    assert accepted.status_code == 200
    assert captured["max_legendary_slots"] == 6


def test_optimize_uses_tier_three_boots_only_for_completed_mid_quest(monkeypatch):
    monkeypatch.setattr(app_module, "get_champion", lambda _name: {"name": "Ahri"})
    tiers = []

    def fake_optimize(**kwargs):
        tiers.append(kwargs["boots_tier"])
        return {"items": [], "total_damage": 0.0}

    monkeypatch.setattr(app_module, "optimize_build", fake_optimize)
    client = app_module.app.test_client()
    assert (
        client.post("/api/optimize", json={"champion": "Ahri", "level": 18}).status_code
        == 200
    )
    assert (
        client.post(
            "/api/optimize",
            json={
                "champion": "Ahri",
                "level": 18,
                "role": "mid",
                "role_quest_complete": True,
            },
        ).status_code
        == 200
    )

    assert tiers == [2, 3]


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


def test_optimize_accepts_locked_item_with_roster_bolt_model():
    response = app_module.app.test_client().post(
        "/api/optimize",
        json={
            "champion": "Ahri",
            "level": 18,
            "max_legendary_slots": 1,
            "locked_items": ["Runaan's Hurricane"],
        },
    )

    assert response.status_code == 200
    assert "Runaan's Hurricane" in response.get_json()["items"]


@pytest.mark.parametrize(
    "items",
    [
        ["Lich Bane", "Trinity Force"],
        ["Dark Seal", "Mejai's Soulstealer"],
    ],
)
def test_calculate_rejects_backend_illegal_item_groups(items):
    response = app_module.app.test_client().post(
        "/api/calculate",
        json={"champion": "Ziggs", "level": 12, "items": items},
    )

    assert response.status_code == 400
    assert "cannot be equipped together" in response.get_json()["error"]


def test_calculate_accepts_manual_attacker_runaan_item():
    response = app_module.app.test_client().post(
        "/api/calculate",
        json={"champion": "Ahri", "level": 18, "items": ["Runaan's Hurricane"]},
    )

    assert response.status_code == 200


def test_calculate_accepts_typed_ally_item_team_effects():
    response = app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Ahri",
            "level": 18,
            "allies": [{"champion": "Lulu", "level": 18, "items": ["Ardent Censer"]}],
        },
    )

    assert response.status_code == 200
    support = response.get_json()["combat"]["support_events"]
    sanctify = next(
        event for event in support if event["source"] == "Ardent Censer — Sanctify"
    )
    assert sanctify["bonus_attack_speed_percent"] == 25.0
    assert sanctify["on_hit_magic_damage"] == 20.0


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


def test_calculate_and_optimize_reject_level_impossible_ranks():
    payload = {
        "champion": "Ahri",
        "level": 5,
        "ability_ranks": {"Q": 3, "W": 1, "E": 0, "R": 1},
    }
    client = app_module.app.test_client()

    calculate = client.post("/api/calculate", json=payload)
    optimize = client.post("/api/optimize", json=payload)

    assert calculate.status_code == 400
    assert optimize.status_code == 400
    assert "R rank 1 requires champion level 6" in calculate.get_json()["error"]


def test_bis_main_request_preserves_authored_ability_ranks():
    request = app_module._bis_main_request(
        {
            "champion": "Ahri",
            "level": 6,
            "ability_ranks": {"Q": 3, "W": 1, "E": 1, "R": 1},
            "cast_order": ["R", "Q", "W", "E"],
            "ally_effects_enabled": False,
        }
    )

    assert request.ability_ranks == {"Q": 3, "W": 1, "E": 1, "R": 1}
    assert request.cast_order == ["R", "Q", "W", "E"]
    assert request.ally_effects_enabled is False


def test_bis_rejects_level_impossible_ranks_and_unknown_champion_options():
    client = app_module.app.test_client()
    impossible_rank = client.post(
        "/api/bis",
        json={
            "champion": "Ahri",
            "level": 5,
            "ability_ranks": {"Q": 3, "W": 1, "E": 0, "R": 1},
        },
    )
    assert impossible_rank.status_code == 400
    assert "R rank 1 requires champion level 6" in impossible_rank.get_json()["error"]

    unknown_option = client.post(
        "/api/bis",
        json={"champion": "Vayne", "level": 18, "champion_options": {"unknown": True}},
    )
    assert unknown_option.status_code == 400
    assert (
        "champion_options contains unknown option" in unknown_option.get_json()["error"]
    )


class TestBreakdownProcRowShape:
    """Proc-style breakdown rows reach the UI in ONE shape:
    count / damage_per_hit / unit="procs" — the shape app.js's detail
    cell renders ("N procs @ X each"). The procs/damage_per_proc
    spelling never left app.py's row builder, so those rows displayed
    an empty detail cell (the user-reported "no kraken procs")."""

    def test_kraken_counter_row_one_rotation_belveth(self):
        """Bel'Veth 26.15, bare Kraken: Q's 4 dashes + 6 slashes
        (20% passive + Kraken AS is below the next 40% E threshold) =
        10 shared hits = 3 procs, rendered."""
        payload = {
            "champion": "Belveth",
            "level": 14,
            "items": ["Kraken Slayer"],
            "fight_mode": "one_rotation",
        }
        response = app_module.app.test_client().post("/api/calculate", json=payload)
        assert response.status_code == 200
        row = response.get_json()["breakdown"]["on_hit_Kraken Slayer"]
        assert row["count"] == 3
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

    def test_guinsoo_seething_schedule_is_used_by_timed_calculation(self):
        """A timed build uses Seething's sourced swing schedule, not a flat AS count."""
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
        breakdown = response.get_json()["breakdown"]
        assert breakdown["auto_attacks"]["count"] > 0
        assert breakdown["on_hit_Guinsoo's Rageblade"]["count"] > 0

    def test_temporary_lethality_receipt_reaches_frontend_breakdown(self):
        """Stateful penetration metadata is not dropped by API serialization."""
        result = app_module._serialize_fight_result(
            {
                "champion_stats": {},
                "total_damage": 120.0,
                "health_damage": 120.0,
                "ability_damage": 0.0,
                "auto_attack_damage": 120.0,
                "damage_by_type": {"physical": 120.0},
                "breakdown": {
                    "on_hit_once_Voltaic Cyclosword": {
                        "name": "Voltaic Cyclosword (Firmament)",
                        "total_damage": 120.0,
                        "count": 1,
                        "unit": "procs",
                        "damage_per_hit": 120.0,
                        "temporary_lethality": {
                            "amount": 15.0,
                            "duration": 4.0,
                            "applies_after_event": True,
                            "applied_to_later_events": True,
                            "applied_event_count": 3,
                        },
                    }
                },
            }
        )

        assert result["breakdown"]["on_hit_once_Voltaic Cyclosword"][
            "temporary_lethality"
        ] == {
            "amount": 15.0,
            "duration": 4.0,
            "applies_after_event": True,
            "applied_to_later_events": True,
            "applied_event_count": 3,
        }

    def test_chain_targeting_receipt_reaches_frontend_breakdown(self):
        """Roster allocation metadata survives the public serializer."""
        result = app_module._serialize_fight_result(
            {
                "champion_stats": {},
                "total_damage": 60.0,
                "health_damage": 60.0,
                "ability_damage": 0.0,
                "auto_attack_damage": 60.0,
                "damage_by_type": {"magic": 60.0},
                "breakdown": {
                    "on_hit_once_Statikk Shiv": {
                        "name": "Statikk Shiv (Electrospark)",
                        "total_damage": 60.0,
                        "count": 1,
                        "unit": "procs",
                        "damage_per_hit": 60.0,
                        "targeting": {
                            "kind": "chain_lightning",
                            "chain_target_count": 7,
                            "allocated_target_index": 2,
                            "roster_target_count": 3,
                            "copied_on_hit_effects": False,
                        },
                    }
                },
            }
        )

        assert result["breakdown"]["on_hit_once_Statikk Shiv"]["targeting"] == {
            "kind": "chain_lightning",
            "chain_target_count": 7,
            "allocated_target_index": 2,
            "roster_target_count": 3,
            "copied_on_hit_effects": False,
        }

    def test_riftmaker_conditional_omnivamp_reaches_public_calculation(self):
        response = app_module.app.test_client().post(
            "/api/calculate",
            json={
                "champion": "Ahri",
                "level": 18,
                "items": ["Riftmaker"],
                "fight_mode": "timed",
                "fight_duration": 5,
                "include_auto_attacks": True,
                "auto_attack_uptime": 1.0,
            },
        )

        assert response.status_code == 200
        result = response.get_json()
        assert result["champion_stats"]["omnivamp_percent"] == pytest.approx(10.0)
        assert result["self_healing"] > 0.0
        assert result["self_healing_events"]
        assert all(
            event["source"] == "Omnivamp (explicit single-target attacks and on-hit)"
            for event in result["self_healing_events"]
        )

    def test_aggregated_targets_preserve_self_healing_receipts(self):
        response = app_module.app.test_client().post(
            "/api/calculate",
            json={
                "champion": "Ahri",
                "level": 18,
                "items": ["Riftmaker"],
                "enemies": [
                    {"champion": "Lux", "level": 18},
                    {"champion": "Sona", "level": 18},
                ],
                "fight_mode": "timed",
                "fight_duration": 5,
                "include_auto_attacks": True,
                "auto_attack_uptime": 1.0,
            },
        )

        assert response.status_code == 200
        result = response.get_json()
        assert result["self_healing"] > 0.0
        assert len(result["self_healing_events"]) >= 2
        assert result["self_healing"] == pytest.approx(
            sum(event["result"]["self_healing"] for event in result["targets"])
        )


def test_attacker_above_level_18_requires_completed_top_quest(monkeypatch):
    """Levels 19-20 are top-quest rewards; every other role caps at 18."""
    monkeypatch.setattr(app_module, "get_champion", lambda _name: {"name": "Ahri"})

    def fake_run_fight(data, level, items, params):
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

    monkeypatch.setattr(app_module, "run_fight", fake_run_fight)
    monkeypatch.setattr(
        app_module,
        "optimize_build",
        lambda **_kwargs: {"items": [], "total_damage": 0.0},
    )
    client = app_module.app.test_client()

    cases = [
        ({}, 400),
        ({"role": "mid", "role_quest_complete": True}, 400),
        ({"role": "top", "role_quest_complete": False}, 400),
        ({"role": "top", "role_quest_complete": True}, 200),
    ]
    for extra, expected in cases:
        for endpoint in ("/api/calculate", "/api/optimize"):
            payload = {"champion": "Ahri", "level": 19, **extra}
            response = client.post(endpoint, json=payload)
            assert response.status_code == expected, (endpoint, extra)
            if expected == 400:
                assert "top" in response.get_json()["error"]
