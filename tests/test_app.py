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
            {"champion": "Aatrox", "fight_mode": "timed", "fight_duration": 11},
        ),
        (
            "/api/optimize",
            {"champion": "Aatrox", "fight_mode": "timed", "fight_duration": 11},
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


def test_loadout_stats_exposes_target_item_coverage_without_hiding_the_card():
    response = app_module.app.test_client().post(
        "/api/loadout-stats",
        json={"champion": "Galio", "level": 12, "items": ["Banshee's Veil"]},
    )

    assert response.status_code == 200
    coverage = response.get_json()["target_model_coverage"]
    assert coverage["complete"] is False
    assert coverage["blocked"][0]["name"] == "Banshee's Veil"


def test_calculate_withholds_an_unmodeled_enemy_spell_shield():
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

    assert response.status_code == 400
    assert "Banshee's Veil" in response.get_json()["error"]
    assert "first-hostile-ability" in response.get_json()["error"]


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
    assert data["timeline_coverage"]["complete"] is False
    assert "passive" in data["timeline_coverage"]["coarse_sources"]
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
        "one_rotation_duration_seconds": 5.0,
    }
    assert data["champion_options"]["Soraka"]["sources"][1] == {
        "label": "Equinox",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Soraka/Equinox",
        "revision_id": 3907153,
        "revision_timestamp": "2025-06-06T18:23:34Z",
    }
    assert data["input_limits"] == {
        "fight_duration": [1.0, 10.0],
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

    def test_item_apis_expose_optimizer_coverage(self):
        client = app_module.app.test_client()
        items = {item["name"]: item for item in client.get("/api/items").get_json()}
        boots = {item["name"]: item for item in client.get("/api/boots").get_json()}

        assert items["Runaan's Hurricane"]["model_coverage"]["status"] == "blocked"
        assert items["Void Staff"]["model_coverage"]["status"] == "stats_only"
        assert boots["Immortal Path"]["model_coverage"]["status"] == "blocked"

    def test_boot_api_marks_role_quest_tiers(self):
        boots = app_module.app.test_client().get("/api/boots").get_json()
        assert {boot["tier"] for boot in boots} == {2, 3}

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


def test_optimize_rejects_locked_item_with_unmodeled_damage_effect():
    response = app_module.app.test_client().post(
        "/api/optimize",
        json={
            "champion": "Ahri",
            "level": 18,
            "max_legendary_slots": 1,
            "locked_items": ["Runaan's Hurricane"],
        },
    )

    assert response.status_code == 400
    assert response.get_json()["error"].startswith(
        "Runaan's Hurricane cannot be locked into BIS search yet"
    )


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
