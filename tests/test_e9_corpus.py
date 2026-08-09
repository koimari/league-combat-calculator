"""E9 — Practice-Tool corpus verification.

Every active corpus scenario is driven through ``/api/calculate`` on the
CURRENT engine and its exact expected receipt is asserted against the
coupled combat ledger (``combat``) and the legacy aggregate response.

SHA semantics
-------------
Each scenario's ``sha`` records the git HEAD its receipt was probed at —
provenance for the audit trail, not a gate.  Receipts are asserted against
the current engine unconditionally: an engine change that moves a receipt
fails here with the numeric diff, and the fix is to re-probe
``/api/calculate``, update ``expected``, and record the new ``sha`` in the
same commit.  (An earlier design skipped every receipt and failed a
pin-freshness meta-test whenever ``src/`` changed at all, which forced a
re-pin commit per engine PR while deferring the actual numeric signal.)

The four legacy scenarios (cp21-*/e0-*/vladimir-*) predate the E-series
rework: their expected values are only valid at their recorded commits, so
they are skipped until a deliberate re-capture promotes them.

Every expected number below was produced by probing ``/api/calculate`` at
the recorded commit; nothing is hand-invented (each scenario carries its
formula in ``expected.formula`` for the audit trail).
"""

import json
from pathlib import Path

import pytest

from src import app as app_module

REPO_ROOT = Path(__file__).resolve().parents[1]
CORPUS_PATH = REPO_ROOT / "data" / "practice-corpus" / "scenarios.json"

# Response values are rounded to one decimal (amounts/damage); survival
# timestamps to three.  The tolerances below cover that rounding.
AMOUNT_ABS = 0.15
TIME_ABS = 0.01

# Pre-E-series scenarios whose expected values are only valid at their
# recorded commits; excluded from current-engine verification until a
# deliberate re-capture promotes them.
LEGACY_SCENARIOS = {
    "cp21-ziggs-outer-blast",
    "cp21-bis-utility-ahri",
    "e0-vladimir-sanguine-pool-heal",
    "vladimir-hemoplague-multitarget",
}


def _load_corpus() -> dict:
    with CORPUS_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture(scope="module")
def corpus() -> dict:
    return _load_corpus()


def _payload(setup: dict) -> dict:
    """Translate a corpus setup tuple into an /api/calculate request."""
    payload = {
        "champion": setup["champion"],
        "level": setup.get("level", 18),
        "items": setup.get("items", []),
        "role": setup.get("role", "mid"),
    }
    ranks = setup.get("ranks")
    if ranks:
        payload["ability_ranks"] = ranks
    options = setup.get("champion_options")
    if options:
        payload["champion_options"] = options
    fight = setup.get("fight", "one_rotation")
    payload["fight_mode"] = fight
    if fight != "one_rotation":
        payload["fight_duration"] = setup.get("fight_duration", 10)
    auto = setup.get("auto")
    if auto is True:
        payload["include_auto_attacks"] = True
    elif auto is False:
        payload["include_auto_attacks"] = False
    if setup.get("auto_attack_uptime") is not None:
        payload["auto_attack_uptime"] = setup["auto_attack_uptime"]
    enemies = setup.get("enemies", [])
    if enemies:
        parsed = []
        for enemy in enemies:
            entry = {
                "champion": enemy["champion"],
                "level": enemy.get("level", 18),
                "items": enemy.get("items", []),
                "role": enemy.get("role", "mid"),
            }
            if enemy.get("ranks"):
                entry["ability_ranks"] = enemy["ranks"]
            parsed.append(entry)
        payload["enemies"] = parsed
    return payload


def _run_calculate(setup: dict) -> dict:
    """POST one /api/calculate fight; fail loudly on a non-200 response."""
    previous_testing = app_module.app.config.get("TESTING")
    app_module.app.config["TESTING"] = True
    try:
        response = app_module.app.test_client().post(
            "/api/calculate", json=_payload(setup)
        )
    finally:
        if previous_testing is None:
            app_module.app.config.pop("TESTING", None)
        else:
            app_module.app.config["TESTING"] = previous_testing
    assert response.status_code == 200, response.get_data(as_text=True)[:500]
    return response.get_json()


def _main_events(combat: dict) -> list[dict]:
    return [e for e in combat["events"] if e.get("attacker") == "main"]


def _main_heals(combat: dict) -> list[dict]:
    return [e for e in combat["healing_events"] if e.get("attacker") == "main"]


def _main_survival(combat: dict) -> dict:
    return next(
        row for row in combat["participants"] if row["participant_id"] == "main"
    )["survival"]


def _source_breakdown(combat: dict, name: str) -> dict:
    for source in combat["breakdown"][0]["sources"]:
        if source["name"] == name:
            return source
    raise AssertionError(f"source {name!r} missing from combat breakdown")


def _support_shields(combat: dict, recipient: str) -> list[dict]:
    return [
        event
        for event in combat.get("support_events", [])
        if event.get("kind") == "shield" and event.get("recipient") == recipient
    ]


# ---------------------------------------------------------------------------
# Receipt kinds
# ---------------------------------------------------------------------------


def _assert_self_healing_events(data: dict, expected: dict) -> None:
    assert data["self_healing"] == pytest.approx(
        expected["self_healing"], abs=AMOUNT_ABS
    )
    heals = _main_heals(data["combat"])
    events_by_id = {e["event_id"]: e for e in data["combat"]["events"]}
    for want in expected["healing_events"]:
        candidates = [
            h
            for h in heals
            if h["source"] == want["source"]
            and float(h["time"]) == pytest.approx(want["time"], abs=TIME_ABS)
        ]
        if want.get("trigger_source"):
            candidates = [
                h
                for h in candidates
                if events_by_id[h["trigger_event_id"]]["source"]
                == want["trigger_source"]
            ]
        assert candidates, f"no {want['source']} heal at {want['time']}"
        heal = candidates[0]
        assert heal["raw_amount"] == pytest.approx(want["amount"], abs=AMOUNT_ABS)


def _assert_dot_ticks(data: dict, expected: dict) -> None:
    events = [
        e
        for e in _main_events(data["combat"])
        if e.get("source") == expected["source"] and e.get("raw_damage", 0.0) > 0.0
    ]
    assert len(events) == expected["ticks"]
    for event in events:
        assert event["raw_damage"] == pytest.approx(expected["per_tick_raw"], abs=0.06)
    assert sum(e["raw_damage"] for e in events) == pytest.approx(
        expected["total_raw"], abs=1.0
    )


def _assert_breakdown_source(data: dict, expected: dict) -> None:
    source = _source_breakdown(data["combat"], expected["source"])
    assert source["total_damage"] == pytest.approx(
        expected["total_damage"], abs=AMOUNT_ABS
    )
    if "attack_count" in expected:
        events = [
            e
            for e in _main_events(data["combat"])
            if e.get("damage_type") == expected.get("damage_type")
            and e.get("raw_damage", 0.0)
            == pytest.approx(expected["per_attack_raw"], abs=0.06)
        ]
        assert len(events) == expected["attack_count"]
    if "raw_damage" in expected:
        # raw is documented, not serialized per-source; recompute it from
        # the post-mitigation total and the target's effective resistance.
        if expected.get("damage_type", "magic") == "magic":
            resistance = data["effective_mr"]
        else:
            resistance = data["effective_armor"]
        recomputed = source["total_damage"] * (100.0 + resistance) / 100.0
        assert recomputed == pytest.approx(expected["raw_damage"], abs=1.0)


def _assert_ability_event(data: dict, expected: dict) -> None:
    events = [
        e for e in _main_events(data["combat"]) if e.get("source") == expected["source"]
    ]
    assert events, f"no {expected['source']} event"
    event = events[0]
    assert event["time"] == pytest.approx(expected["time"], abs=TIME_ABS)
    assert event["raw_damage"] == pytest.approx(expected["raw_damage"], abs=AMOUNT_ABS)
    assert event["damage"] == pytest.approx(expected["damage"], abs=AMOUNT_ABS)


def _assert_grey_health(data: dict, expected: dict) -> None:
    heals = [
        h
        for h in _main_heals(data["combat"])
        if h.get("grey_health") is True
        and h["source"] == expected["healing_events"][0]["source"]
    ]
    by_time = {round(float(h["time"]), 3): h for h in heals}
    for want in expected["healing_events"]:
        heal = by_time[round(float(want["time"]), 3)]
        assert heal["raw_amount"] == pytest.approx(want["amount"], abs=AMOUNT_ABS)
    survival = _main_survival(data["combat"])
    assert survival["grey_health_stored"] == pytest.approx(
        expected["grey_health_stored"], abs=1e-3
    )
    assert survival["grey_health_consumed"] == pytest.approx(
        expected["grey_health_consumed"], abs=1e-3
    )


def _assert_support_shield(data: dict, expected: dict) -> None:
    shields = _support_shields(data["combat"], "main")
    assert shields, "no self shield support event"
    shield = shields[0]
    assert str(shield["source"]).startswith(expected["source"])
    assert shield["amount"] == pytest.approx(expected["shield"], abs=1e-3)
    assert shield["applied_amount"] == pytest.approx(
        expected["applied"], abs=AMOUNT_ABS
    )
    survival = _main_survival(data["combat"])
    assert survival["support_shield_received"] == pytest.approx(
        expected["received"], abs=AMOUNT_ABS
    )
    if "absorbed" in expected:
        assert survival["shield_absorbed"] == pytest.approx(
            expected["absorbed"], abs=AMOUNT_ABS
        )
    if "venom_factor" in expected:
        assert survival["venom_factor"] == pytest.approx(expected["venom_factor"])
    if "cooldown" in expected:
        assert shield["cooldown"] == pytest.approx(expected["cooldown"])


def _assert_revive(data: dict, expected: dict) -> None:
    survival = _main_survival(data["combat"])
    assert survival["revived"] is expected["revived"]
    assert survival["first_death_time"] == pytest.approx(
        expected["first_death_time"], abs=1e-3
    )
    assert survival["revive_time"] == pytest.approx(expected["revive_time"], abs=1e-3)
    assert survival["revive_health_restored"] == pytest.approx(
        expected["revive_health_restored"], abs=AMOUNT_ABS
    )
    assert survival["revive_source"] == expected["revive_source"]
    assert survival["death_time"] == pytest.approx(expected["death_time"], abs=1e-3)


def _assert_grievous(data: dict, expected: dict) -> None:
    heals = _main_heals(data["combat"])
    by_time = {round(float(h["time"]), 3): h for h in heals}
    for want in expected["healing_events"]:
        heal = by_time[round(float(want["time"]), 3)]
        assert heal["raw_amount"] == pytest.approx(want["raw"], abs=AMOUNT_ABS)
        assert heal["applied_amount"] == pytest.approx(want["applied"], abs=AMOUNT_ABS)
        assert heal["healing_reduction_factor"] == pytest.approx(want["factor"])
    survival = _main_survival(data["combat"])
    assert survival["healing_received"] == pytest.approx(
        expected["healing_received"], abs=AMOUNT_ABS
    )
    assert survival["healing_reduced"] == pytest.approx(
        expected["healing_reduced"], abs=AMOUNT_ABS
    )
    assert survival["healing_reduction_sources"] == expected["reduction_sources"]


def _assert_venom_shield(data: dict, expected: dict) -> None:
    shields = _support_shields(data["combat"], "enemy:Ahri")
    assert shields, "no enemy Ahri shield support event"
    shield = shields[0]
    assert shield["amount"] == pytest.approx(expected["shield"], abs=1e-3)
    assert shield["applied_amount"] == pytest.approx(expected["applied"], abs=1e-3)
    assert shield["venom"]["factor"] == pytest.approx(expected["venom_factor"])
    survival = next(
        row
        for row in data["combat"]["participants"]
        if row["participant_id"] == "enemy:Ahri"
    )["survival"]
    assert survival["venom_factor"] == pytest.approx(expected["venom_factor"])
    assert survival["venom_until"] == pytest.approx(expected["venom_until"], abs=1e-3)
    assert survival["support_shield_received"] == pytest.approx(
        expected["received"], abs=AMOUNT_ABS
    )


def _assert_threshold_shield(data: dict, expected: dict) -> None:
    survival = _main_survival(data["combat"])
    assert survival["threshold_shield_triggered"] is expected["triggered"]
    assert survival["shield_absorbed"] == pytest.approx(
        expected["absorbed"], abs=AMOUNT_ABS
    )
    assert survival["max_health"] == pytest.approx(expected["max_health"])
    stats = next(
        row for row in data["combat"]["participants"] if row["participant_id"] == "main"
    )["stats"]
    assert stats["bonus_health"] == pytest.approx(expected["bonus_health"])
    assert survival["death_time"] == pytest.approx(expected["death_time"], abs=1e-3)


def _assert_lifesteal(data: dict, expected: dict) -> None:
    heals = [
        h for h in _main_heals(data["combat"]) if h["source"] == expected["source"]
    ]
    assert len(heals) == expected["heal_count"]
    for heal in heals:
        assert heal["raw_amount"] == pytest.approx(
            expected["heal_per_auto"], abs=AMOUNT_ABS
        )
    assert sum(h["raw_amount"] for h in heals) == pytest.approx(
        expected["healing_total"], abs=AMOUNT_ABS
    )


_KIND_ASSERTIONS = {
    "self_healing_events": _assert_self_healing_events,
    "dot_ticks": _assert_dot_ticks,
    "breakdown_source": _assert_breakdown_source,
    "ability_event": _assert_ability_event,
    "grey_health": _assert_grey_health,
    "support_shield": _assert_support_shield,
    "revive": _assert_revive,
    "grievous": _assert_grievous,
    "venom_shield": _assert_venom_shield,
    "threshold_shield": _assert_threshold_shield,
    "lifesteal": _assert_lifesteal,
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_corpus_schema_version(corpus):
    assert corpus["schema_version"] == 1


def test_all_scenarios_have_required_fields(corpus):
    for scenario in corpus["scenarios"]:
        assert scenario["id"]
        assert scenario["tier"] in {"production", "local", "pending"}
        assert scenario["sha"]
        assert scenario["setup"]["champion"]
        assert scenario["expected"]
        if "fight" in scenario.get("setup", {}):
            assert scenario.get(
                "practice_tool_steps"
            ), f"{scenario['id']} is a fight scenario without practice steps"


_ACTIVE = [s for s in _load_corpus()["scenarios"] if s["id"] not in LEGACY_SCENARIOS]


@pytest.mark.parametrize("scenario", _ACTIVE, ids=[s["id"] for s in _ACTIVE])
def test_scenario_receipt_reproduces_on_current_engine(scenario):
    """Every active scenario's receipt reproduces on the engine at HEAD.

    A failure here means an engine change moved this receipt: re-probe
    ``/api/calculate``, update ``expected``, and record the new ``sha``.
    """
    kind = scenario["expected"]["kind"]
    assert kind in _KIND_ASSERTIONS, f"unknown receipt kind {kind!r}"
    data = _run_calculate(scenario["setup"])
    _KIND_ASSERTIONS[kind](data, scenario["expected"])
