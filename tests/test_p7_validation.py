"""P7 validation-loop contract tests.

Covers the game-receipt import flow (POST /api/receipts), the match
tolerance semantics (max(10% relative, absolute 20)), the systematic-bias
aggregation (GET /api/validation + /api/validation/champions), and the P4
trust-label data endpoints (GET /api/certainty, GET /api/not-modeled).
Everything runs against an isolated SQLite file exactly like the P6 suite.
"""

import pytest

import src.app as app_module

# The app imports its persistence layer as the top-level ``db`` module (src/
# is placed on sys.path by app.py).  ``import src.db`` would create a second
# module instance with its own engine, so tests must use the same ``db`` the
# app resolves.
from src import db


@pytest.fixture
def sqlite_database(tmp_path, monkeypatch):
    """Point the app at an isolated SQLite file and reset the engine."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'p7.sqlite3'}")
    db.reset()
    yield db
    db.reset()


@pytest.fixture(autouse=True)
def _isolate_app_config():
    """Keep these route tests off the shared rate-limit budget."""
    previous_testing = app_module.app.config.get("TESTING")
    previous_rate = app_module.app.config.get("RATE_LIMIT_ENABLED", True)
    app_module.app.config["TESTING"] = True
    app_module.app.config["RATE_LIMIT_ENABLED"] = False
    yield
    if previous_testing is None:
        app_module.app.config.pop("TESTING", None)
    else:
        app_module.app.config["TESTING"] = previous_testing
    app_module.app.config["RATE_LIMIT_ENABLED"] = previous_rate


def _client():
    return app_module.app.test_client()


def _payload(**overrides):
    """The shape app.js's engineFightPayload sends, against a solo target.

    Every field the UI fills, the timed window it requests for a champion
    whose module certifies it, and the target block it always carries.
    """
    payload = {
        "champion": "Ahri",
        "level": 18,
        "boots": "Sorcerer's Shoes",
        "include_boots": True,
        "items": ["Liandry's Torment", "Shadowflame"],
        "item_options": {},
        "keystone": "",
        "target_health": 1000,
        "target_bonus_health": 0,
        "target_armor": 100,
        "target_mr": 100,
        "enemies": [],
        "allies": [],
        "role": "mid",
        "role_quest_complete": False,
        "include_actives": True,
        "include_crossover": True,
        "champion_options": {},
        "ability_ranks": {"Q": 5, "W": 3, "E": 3, "R": 2},
        "rotations": 1,
        "auto_attack_uptime_mode": "calculated",
        "enemies_attack": True,
        "fight_mode": "time_based",
        "fight_duration": 10,
        "include_auto_attacks": True,
        "auto_attack_uptime": 0,
    }
    payload.update(overrides)
    return payload


def _predict(client, payload):
    response = client.post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_json()
    return response.get_json()["total_damage"]


# ---------------------------------------------------------------------------
# Receipt import flow
# ---------------------------------------------------------------------------


def test_receipt_round_trip_matched(sqlite_database):
    client = _client()
    payload = _payload()
    predicted = _predict(client, payload)

    created = client.post(
        "/api/receipts",
        json={
            "champion": "Ahri",
            "loadout": payload,
            "observed": {"tdd": predicted},
            "source": "manual",
        },
    )
    assert created.status_code == 201
    body = created.get_json()
    assert set(body) >= {
        "feedback_id",
        "matched",
        "predicted",
        "observed",
        "delta",
    }
    assert body["matched"] is True
    assert body["predicted"]["tdd"] == predicted
    assert body["observed"]["tdd"] == predicted
    assert body["delta"] == 0.0
    assert isinstance(body["feedback_id"], int)

    listed = client.get("/api/validation?champion=Ahri").get_json()
    assert listed["count"] == 1
    row = listed["feedback"][0]
    assert row["feedback_id"] == body["feedback_id"]
    assert row["delta"] == 0.0
    assert row["source"] == "manual"
    assert row["expected"]["tdd"] == predicted
    assert row["actual"]["tdd"] == predicted


def test_receipt_prediction_matches_calculate_output(sqlite_database):
    """The receipt's model prediction is exactly /api/calculate's total."""
    client = _client()
    payload = _payload()
    predicted = _predict(client, payload)
    receipt = client.post(
        "/api/receipts",
        json={"champion": "Ahri", "loadout": payload, "observed": {"tdd": predicted}},
    )
    body = receipt.get_json()
    assert body["predicted"]["tdd"] == predicted
    # Per-source prediction includes ability letters and item rows.
    assert set(body["predicted"]["sources"]) >= {"Q", "W", "E", "R"}


def _ui_payload():
    """The same shape at the level cap, against a roster that fights back."""
    enemy = {
        "kind": "champion",
        "champion": "Garen",
        "level": 18,
        "items": ["Sunfire Aegis"],
        "boots": "Plated Steelcaps",
        "include_boots": True,
        "item_options": {},
        "role": "",
        "role_quest_complete": False,
        "champion_options": {},
        "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
    }
    return _payload(
        level=20,
        items=["Liandry's Torment", "Shadowflame", "Rabadon's Deathcap"],
        role="top",
        role_quest_complete=True,
        ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
        rotations=2,
        enemies=[enemy],
    )


def test_receipt_predicts_the_total_the_ui_displays_for_a_roster_fight(
    sqlite_database,
):
    """feedback.js posts the exact payload behind the displayed result, and
    the receipt must predict the number that was on screen: in a roster
    fight app.js headlines the attacker's combat row, not the rotation
    ``total_damage`` — so the /api/validation bias flag measures what the
    user actually compared against their game."""
    client = _client()
    payload = _ui_payload()
    result = client.post("/api/calculate", json=payload).get_json()
    main = next(
        row for row in result["combat"]["breakdown"] if row["participant_id"] == "main"
    )
    assert main["total_damage"] != result["total_damage"]

    receipt = client.post(
        "/api/receipts",
        json={"champion": "Ahri", "loadout": payload, "source": "manual"},
    )
    assert receipt.status_code == 201, receipt.get_json()
    body = receipt.get_json()
    assert body["predicted"]["tdd"] == main["total_damage"]
    assert body["predicted"]["sources"] == {
        source["name"]: source["total_damage"] for source in main["sources"]
    }
    assert body["matched"] is True  # a bare receipt confirms the prediction

    row = client.get("/api/validation?champion=Ahri").get_json()["feedback"][0]
    assert row["loadout"] == payload
    assert row["expected"]["tdd"] == main["total_damage"]


def test_receipt_confirmation_when_observed_omitted(sqlite_database):
    """Omitted observed = positive confirmation receipt (observed := predicted)."""
    client = _client()
    payload = _payload()
    created = client.post(
        "/api/receipts", json={"champion": "Ahri", "loadout": payload}
    )
    assert created.status_code == 201
    body = created.get_json()
    assert body["matched"] is True
    assert body["observed"]["tdd"] == body["predicted"]["tdd"]
    assert body["delta"] == 0.0


def test_receipt_absolute_tolerance_floor(sqlite_database):
    """Small predictions use the absolute 20-damage floor, not a 10% band."""
    client = _client()
    # Level 1, one ability, no items, the shortest window -> a small prediction.
    payload = _payload(
        level=1, items=[], boots="", ability_ranks={"Q": 1}, fight_duration=3
    )
    predicted = _predict(client, payload)
    assert predicted < 200  # sanity: this is the small-damage regime
    tolerance = max(0.10 * predicted, 20.0)
    assert tolerance == 20.0

    within = client.post(
        "/api/receipts",
        json={
            "champion": "Ahri",
            "loadout": payload,
            "observed": {"tdd": predicted + 15.0},
        },
    ).get_json()
    assert within["matched"] is True
    assert within["delta"] == 15.0

    beyond = client.post(
        "/api/receipts",
        json={
            "champion": "Ahri",
            "loadout": payload,
            "observed": {"tdd": predicted + 25.0},
        },
    ).get_json()
    assert beyond["matched"] is False


def test_receipt_relative_tolerance(sqlite_database):
    """Large predictions use the relative 10% band."""
    client = _client()
    payload = _payload()
    predicted = _predict(client, payload)
    assert predicted >= 200  # relative band dominates
    tolerance = max(0.10 * predicted, 20.0)
    assert tolerance == pytest.approx(0.10 * predicted)

    inside = client.post(
        "/api/receipts",
        json={
            "champion": "Ahri",
            "loadout": payload,
            "observed": {"tdd": predicted * 1.095},
        },
    ).get_json()
    assert inside["matched"] is True

    outside = client.post(
        "/api/receipts",
        json={
            "champion": "Ahri",
            "loadout": payload,
            "observed": {"tdd": predicted * 1.11},
        },
    ).get_json()
    assert outside["matched"] is False


def test_receipt_raw_paste_parsing(sqlite_database):
    client = _client()
    payload = _payload()
    created = client.post(
        "/api/receipts",
        json={
            "champion": "Ahri",
            "loadout": payload,
            "observed": "Q 347.2\nW: 154\nE 176\nR 320\ntotal 997",
            "source": "combat_log",
        },
    )
    assert created.status_code == 201
    body = created.get_json()
    assert body["observed"]["tdd"] == 997.0
    assert body["observed"]["sources"] == {
        "Q": 347.2,
        "W": 154.0,
        "E": 176.0,
        "R": 320.0,
    }


def test_receipt_json_paste(sqlite_database):
    client = _client()
    payload = _payload()
    import json as jsonlib

    created = client.post(
        "/api/receipts",
        json={
            "champion": "Ahri",
            "loadout": payload,
            "observed": jsonlib.dumps(
                {"tdd": 1000.0, "sources": {"Q": 400.0, "W": 600.0}}
            ),
            "source": "combat_log",
        },
    )
    assert created.status_code == 201
    body = created.get_json()
    assert body["observed"]["tdd"] == 1000.0
    assert body["observed"]["sources"]["Q"] == 400.0


def test_receipt_off_by_percent(sqlite_database):
    client = _client()
    payload = _payload()
    predicted = _predict(client, payload)

    higher = client.post(
        "/api/receipts",
        json={
            "champion": "Ahri",
            "loadout": payload,
            "observed": {"off_by_percent": 10, "direction": "higher"},
        },
    ).get_json()
    assert higher["observed"]["tdd"] == pytest.approx(predicted * 1.10)
    assert higher["delta"] == pytest.approx(0.10 * predicted)
    # At exactly 10% the tolerance (10% or 20, larger) is exactly met.
    assert higher["matched"] is True

    lower = client.post(
        "/api/receipts",
        json={
            "champion": "Ahri",
            "loadout": payload,
            "observed": {"off_by_percent": 30, "direction": "lower"},
        },
    ).get_json()
    assert lower["observed"]["tdd"] == pytest.approx(predicted * 0.70)
    assert lower["matched"] is False


def test_receipt_validation_errors(sqlite_database):
    client = _client()
    payload = _payload()
    assert (
        client.post(
            "/api/receipts", json={"champion": "Ahri", "observed": {"tdd": "x"}}
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/receipts",
            json={"champion": "Ahri", "loadout": payload, "source": "spreadsheet"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/receipts",
            json={"loadout": payload, "observed": {"tdd": 1}},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/receipts",
            json={"champion": "Ahri", "loadout": [], "observed": {"tdd": 1}},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/receipts",
            json={"champion": "Ahri", "loadout": payload, "observed": {"tdd": -5}},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/receipts",
            json={
                "champion": "Ahri",
                "loadout": payload,
                "observed": {"off_by_percent": 5000},
            },
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/receipts",
            json={
                "champion": "Ahri",
                "loadout": payload,
                "observed": {"off_by_percent": 5, "direction": "sideways"},
            },
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/receipts",
            json={"champion": "NotAChampion", "observed": {"tdd": 1}},
        ).status_code
        == 404
    )


# ---------------------------------------------------------------------------
# Systematic-bias aggregation
# ---------------------------------------------------------------------------


def test_validation_summary_flags_systematic_bias(sqlite_database):
    client = _client()
    payload = _payload()
    predicted = _predict(client, payload)

    # Five receipts all ~20% high -> bias +20%, n=5 -> flagged.
    for _ in range(5):
        response = client.post(
            "/api/receipts",
            json={
                "champion": "Ahri",
                "loadout": payload,
                "observed": {"tdd": predicted * 1.20},
            },
        )
        assert response.status_code == 201
    # A second champion with one accurate receipt stays unflagged.
    client.post(
        "/api/receipts",
        json={
            "champion": "Darius",
            "loadout": _payload(champion="Darius", items=[], boots=""),
            "observed": {"tdd": 1.0},
        },
    )

    summary = client.get("/api/validation?champion=Ahri").get_json()
    assert summary["count"] == 5
    assert len(summary["feedback"]) == 5
    assert all(
        row["delta"] == pytest.approx(0.20 * predicted) for row in summary["feedback"]
    )

    ahri = next(entry for entry in summary["systematic"] if entry["champion"] == "Ahri")
    assert ahri["n"] == 5
    assert ahri["bias"] == pytest.approx(20.0, abs=0.5)
    assert ahri["flagged"] is True

    all_champions = client.get("/api/validation/champions").get_json()["champions"]
    ahri_entry = next(entry for entry in all_champions if entry["champion"] == "Ahri")
    assert ahri_entry["count"] == 5
    assert ahri_entry["receipts"] == 5
    assert ahri_entry["flagged"] is True
    darius_entry = next(
        entry for entry in all_champions if entry["champion"] == "Darius"
    )
    assert darius_entry["count"] == 1
    assert darius_entry["flagged"] is False


def test_validation_under_threshold_not_flagged(sqlite_database):
    client = _client()
    payload = _payload()
    predicted = _predict(client, payload)
    # Only 4 receipts at +20%: below the n>=5 gate.
    for _ in range(4):
        client.post(
            "/api/receipts",
            json={
                "champion": "Ahri",
                "loadout": payload,
                "observed": {"tdd": predicted * 1.20},
            },
        )
    summary = client.get("/api/validation?champion=Ahri").get_json()
    ahri = next(entry for entry in summary["systematic"] if entry["champion"] == "Ahri")
    assert ahri["n"] == 4
    assert ahri["flagged"] is False


def test_validation_limit_and_filter(sqlite_database):
    client = _client()
    payload = _payload()
    predicted = _predict(client, payload)
    for champion in ("Ahri", "Darius"):
        client.post(
            "/api/receipts",
            json={
                "champion": champion,
                "loadout": _payload(champion=champion, items=[], boots=""),
                "observed": {"tdd": predicted},
            },
        )
    listed = client.get("/api/validation?limit=1").get_json()
    assert listed["count"] == 1
    assert client.get("/api/validation?limit=nope").status_code == 400
    ahri_only = client.get("/api/validation?champion=Ahri").get_json()
    assert ahri_only["count"] == 1
    assert ahri_only["feedback"][0]["champion"] == "Ahri"


def test_validation_summary_db_direct(sqlite_database):
    """The db-level aggregation counts P6-style rows without deltas too."""
    db.add_feedback(champion="Ahri", expected={}, actual={}, source="manual")
    for _ in range(5):
        db.add_feedback(
            champion="Ahri",
            expected={"tdd": 100.0},
            actual={"tdd": 120.0},
            source="manual",
            matched=False,
            delta=20.0,
        )
    summary = db.validation_summary(champion="Ahri")
    assert len(summary) == 1
    entry = summary[0]
    assert entry["count"] == 6  # includes the delta-less manual row
    assert entry["receipts"] == 5
    assert entry["bias"] == pytest.approx(20.0)
    assert entry["flagged"] is True


# ---------------------------------------------------------------------------
# P4 trust-label data
# ---------------------------------------------------------------------------


def test_certainty_contract_shape(sqlite_database):
    client = _client()
    body = client.get("/api/certainty?champion=Ahri").get_json()
    assert body["champion"] == "Ahri"
    assert set(body) >= {"champion", "slots", "certified", "registration"}
    assert body["certified"] is True
    assert set(body["slots"]) >= {"P", "Q", "W", "E", "R"}
    for slot, info in body["slots"].items():
        assert set(info) == {"certainty", "reason"}
        assert info["certainty"] in {"exact", "estimate", "boundary"}
        assert isinstance(info["reason"], str) and info["reason"]


def test_certainty_ahri_levels(sqlite_database):
    """Ahri: P is a no-damage boundary; Q/W/E/R are exact formulas."""
    client = _client()
    slots = client.get("/api/certainty?champion=Ahri").get_json()["slots"]
    assert slots["P"]["certainty"] == "boundary"
    assert "no enemy damage" in slots["P"]["reason"]
    for slot in ("Q", "W", "E", "R"):
        assert slots[slot]["certainty"] == "exact"
        assert "sourced formula" in slots[slot]["reason"]


def test_certainty_aurora_boundaries_and_options(sqlite_database):
    """Aurora: utility W is a documented boundary; Q multi-target is an option.

    Q's subsequent bolts are modeled behind the ``q_marked_enemies``
    player-controlled option, so the slot is an estimate; W remains a
    documented non-computed utility boundary.
    """
    client = _client()
    slots = client.get("/api/certainty?champion=Aurora").get_json()["slots"]
    assert slots["W"]["certainty"] == "boundary"
    assert slots["Q"]["certainty"] == "estimate"
    assert "q_marked_enemies" in slots["Q"]["reason"]
    assert slots["E"]["certainty"] == "exact"
    assert slots["R"]["certainty"] == "exact"


def test_certainty_estimate_from_options(sqlite_database):
    """Caitlyn: p_pre_stacks / w_traps are player-controlled defaults."""
    client = _client()
    slots = client.get("/api/certainty?champion=Caitlyn").get_json()["slots"]
    assert slots["P"]["certainty"] == "estimate"
    assert "p_pre_stacks" in slots["P"]["reason"]
    assert slots["W"]["certainty"] == "estimate"
    assert "w_traps" in slots["W"]["reason"]


def test_certainty_errors(sqlite_database):
    client = _client()
    assert client.get("/api/certainty").status_code == 400
    assert client.get("/api/certainty?champion=NotAChampion").status_code == 404


def test_not_modeled_documented_boundaries(sqlite_database):
    client = _client()
    body = client.get("/api/not-modeled?champion=Ahri").get_json()
    assert body["champion"] == "Ahri"
    assert body["items"]
    assert any("kill boundary" in item for item in body["items"])
    assert client.get("/api/not-modeled").status_code == 400
    assert client.get("/api/not-modeled?champion=NotAChampion").status_code == 404
