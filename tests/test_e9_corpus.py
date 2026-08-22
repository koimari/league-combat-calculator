"""E9 - Practice-Tool corpus verification.

Every non-legacy corpus scenario is driven through ``/api/calculate`` and its
exact expected receipt is asserted against the coupled combat ledger
(``combat``) and the legacy aggregate response.  There is no selection: a
receipt an engine change breaks stays executed and fails loudly on its own
numbers, which is the gate the corpus exists to be.

A scenario's ``sha`` is provenance -- the commit its receipt was last probed
at, written by ``scripts/repin_corpus.py`` and never dereferenced here, so the
corpus gates a shallow checkout as fully as a clone.  The legacy four
(cp21-*/e0-*/vladimir-*) predate the E-series rework, are enumerated in
``LEGACY_SCENARIO_IDS`` and are re-verified only by a deliberate re-capture.

Every expected number below was produced by probing ``/api/calculate``;
nothing is hand-invented (each scenario carries its formula in
``expected.formula`` for the audit trail), and re-pinning re-probes.
"""

import json
import sys
from pathlib import Path

import pytest

from scripts.repin_corpus import (
    LEGACY_SCENARIO_IDS,
    check_pins,
    load_corpus,
    non_legacy_scenarios,
)

from src import app as app_module

pytestmark = pytest.mark.usefixtures("authorized_fimbulwinter_mana_gate")

REPO_ROOT = Path(__file__).resolve().parents[1]
CORPUS_PATH = REPO_ROOT / "data" / "practice-corpus" / "scenarios.json"
REPIN_SCRIPT = REPO_ROOT / "scripts" / "repin_corpus.py"

# Response values are rounded to one decimal (amounts/damage); survival
# timestamps to three.  The tolerances below cover that rounding.
AMOUNT_ABS = 0.15
TIME_ABS = 0.01


@pytest.fixture(scope="module")
def corpus() -> dict:
    return load_corpus()


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
    response = app_module.app.test_client().post("/api/calculate", json=_payload(setup))
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
    assert survival["healing_reduction_window_sources"] == expected["reduction_sources"]


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


_EXECUTED = non_legacy_scenarios(load_corpus())


@pytest.mark.parametrize("scenario", _EXECUTED, ids=[s["id"] for s in _EXECUTED])
def test_scenario_receipt_reproduces(scenario):
    """Every non-legacy scenario reproduces its receipt on this engine."""
    kind = scenario["expected"]["kind"]
    assert kind in _KIND_ASSERTIONS, f"unknown receipt kind {kind!r}"
    data = _run_calculate(scenario["setup"])
    _KIND_ASSERTIONS[kind](data, scenario["expected"])


# ---------------------------------------------------------------------------
# The gate itself (R-22): the executed set, and a red it can reproduce
# ---------------------------------------------------------------------------


def test_the_reader_walks_no_history():
    """Reader and writer alike answer from the tree, never from git."""
    assert not hasattr(sys.modules[__name__], "subprocess")
    reader_half = REPIN_SCRIPT.read_text(encoding="utf-8").split("# The writer")[0]
    assert "subprocess.run" not in reader_half
    assert _EXECUTED == non_legacy_scenarios(load_corpus())


def test_check_passes_on_the_committed_corpus():
    """The committed corpus satisfies the gate."""
    assert check_pins(load_corpus(), parametrized=[s["id"] for s in _EXECUTED]) == ()


def test_check_fails_on_a_missing_pin(corpus):
    """A scenario carrying no provenance is reported, by scenario id."""
    mutated = json.loads(json.dumps(corpus))
    victim = non_legacy_scenarios(mutated)[0]
    victim["sha"] = ""
    reasons = check_pins(mutated, parametrized=[s["id"] for s in _EXECUTED])
    assert any(victim["id"] in reason for reason in reasons), reasons


def test_check_fails_on_an_empty_corpus(corpus):
    """A corpus that asserts nothing fails rather than reporting green."""
    mutated = json.loads(json.dumps(corpus))
    mutated["scenarios"] = [
        s for s in mutated["scenarios"] if s["id"] in LEGACY_SCENARIO_IDS
    ]
    reasons = check_pins(mutated, parametrized=[s["id"] for s in _EXECUTED])
    assert any("holds 0 non-legacy" in reason for reason in reasons), reasons


def test_check_fails_on_a_short_corpus(corpus):
    """Losing one scenario from the executed set is a failure, not a smaller run."""
    mutated = json.loads(json.dumps(corpus))
    dropped = non_legacy_scenarios(mutated)[0]
    mutated["scenarios"] = [s for s in mutated["scenarios"] if s["id"] != dropped["id"]]
    reasons = check_pins(mutated, parametrized=[s["id"] for s in _EXECUTED])
    assert any("test_e9_corpus" in reason for reason in reasons), reasons


def test_check_fails_when_the_receipt_count_disagrees(corpus):
    """The fingerprints receipt's non_legacy_count is a gate, once it exists."""
    reasons = check_pins(
        corpus,
        parametrized=[s["id"] for s in _EXECUTED],
        expected_count=len(_EXECUTED) + 1,
    )
    assert any("non_legacy_count" in reason for reason in reasons), reasons
