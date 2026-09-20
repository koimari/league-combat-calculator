"""SR2: the optimizer's three entry points, mounted and reaching the backend.

``/api/optimize`` had no user-facing control at all. ``app.js`` read
``data-optimize-roster``, ``data-optimize-roster-all`` and
``data-optimize-build`` in its click delegate, and no renderer or template
emitted any of them, so the roster and full-build searches were unreachable
from the page while CI exercised the route 183 times a run.

Mounting them surfaced a second thing a never-run handler can hide: the roster
search addressed ``/api/bis/batch`` through the per-SLOT payload builder, which
refuses a card path, so its first call threw ``Invalid roster optimization
path``. The two builders are split here and both halves are pinned, because a
payload shape and the route that accepts it can each look right alone.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import src.app as app_module

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_JS_PATH = REPO_ROOT / "static" / "js" / "app.js"
TEMPLATE_PATH = REPO_ROOT / "templates" / "index.html"
HARNESS = Path(__file__).resolve().parent / "js" / "bis_batch_payload_harness.mjs"

APP_JS = APP_JS_PATH.read_text(encoding="utf-8")
TEMPLATE = TEMPLATE_PATH.read_text(encoding="utf-8")


def _payloads(tmp_path, paths: list[str]) -> dict:
    """Run app.js's own BIS payload builders over ``paths``."""
    node = shutil.which("node")
    if node is None:  # pragma: no cover - toolchain dependent
        pytest.skip("node is not installed")
    fixture = tmp_path / "fixture.json"
    fixture.write_text(
        json.dumps({"champion": "Ashe", "enemy": "Garen", "paths": paths}),
        encoding="utf-8",
    )
    result = subprocess.run(
        [node, str(HARNESS), str(APP_JS_PATH), str(fixture)],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


# ---------------------------------------------------------------------------
# The mounts
# ---------------------------------------------------------------------------


def test_the_full_build_search_is_reachable_from_the_build_actions_strip():
    """It belongs beside the per-slot search: both are whole-build moves that
    no single slot row owns, which is what that strip is for."""
    strip = TEMPLATE.split('id="buildActions"')[1].split("</section>")[0]
    assert "data-optimize-build" in strip
    assert 'id="optimizeBuildButton"' in strip
    assert 'id="bisButton"' in strip


def test_each_roster_side_carries_its_own_whole_side_search():
    """One button per side, each naming the state root its handler reads."""
    assert 'data-optimize-roster-all="targets"' in TEMPLATE
    assert 'data-optimize-roster-all="allies"' in TEMPLATE
    assert 'id="rosterOptimizeAll"' in TEMPLATE


def test_every_roster_card_carries_a_whole_card_search():
    assert "function rosterOptimizeTrigger(path)" in APP_JS
    assert 'data-optimize-roster="${path}"' in APP_JS
    assert "${optimizeButton}" in APP_JS


def test_the_per_card_trigger_states_its_own_reason_like_the_bis_trigger():
    """Two renderers redraw a roster card without running the gating passes
    (the engine response, and the objective click), so a render-created
    control that waited to be gated would come back enabled and silent."""
    trigger = APP_JS.split("function rosterOptimizeTrigger(path) {")[1].split("\n}")[0]
    assert "Needs a champion and role on this enemy" in trigger
    assert "Needs a champion and role on this ally" in trigger
    assert "Optimization is already running" in trigger
    assert '${blocked ? "disabled" : ""}' in trigger
    # The two template-served controls are gated by the render-time pass.
    gates = APP_JS.split("function applyOptimizerPrerequisiteGates() {")[1].split(
        "\n}\n"
    )[0]
    assert '"[data-optimize-build]"' in gates
    assert '"[data-optimize-roster-all]"' in gates
    assert '"[data-optimize-roster]"' not in gates


def test_the_optimize_family_no_longer_needs_a_gate_exemption():
    """The exemption said the family mounts nothing. It mounts three now, so
    the selector row replaces it in the same change."""
    assert "const CONTROL_FAMILY_EXEMPTIONS = {};" in APP_JS
    gate_table = APP_JS.split("const CONTROL_FAMILY_GATES = {")[1].split("\n};")[0]
    for attribute in (
        "[data-optimize-build]",
        "[data-optimize-roster]",
        "[data-optimize-roster-all]",
    ):
        assert attribute in gate_table, attribute


# ---------------------------------------------------------------------------
# The bug mounting the controls surfaced
# ---------------------------------------------------------------------------


@pytest.mark.needs_node
def test_the_batch_builder_answers_a_card_path_and_the_slot_builder_refuses_it(
    tmp_path,
):
    """The split, from app.js's own two builders.

    ``targets.0`` names a subject and no slot. Before this, the roster search
    asked the SLOT builder for it and got ``null``, so every run of
    ``startRosterOptimization`` threw on its first call.
    """
    built = _payloads(tmp_path, ["targets.0", "targets.0.items.2", "targets.0.boots"])

    card = built["targets.0"]
    assert card["slot"] is None
    assert card["batch"]["subject_team"] == "enemy"
    assert card["batch"]["subject_index"] == 0
    assert "slot_kind" not in card["batch"]
    assert "slot_index" not in card["batch"]

    for path, kind, index in (
        ("targets.0.items.2", "item", 2),
        ("targets.0.boots", "boots", 0),
    ):
        assert built[path]["batch"] is None, path
        assert built[path]["slot"]["slot_kind"] == kind
        assert built[path]["slot"]["slot_index"] == index


@pytest.mark.needs_node
def test_the_batch_builder_refuses_a_path_naming_no_roster_card(tmp_path):
    """Fail closed: a main-build path and an absent index are not cards."""
    built = _payloads(tmp_path, ["attacker.buildA.1", "allies.0", "targets.4"])
    for path in ("attacker.buildA.1", "allies.0", "targets.4"):
        assert built[path]["batch"] is None, path


@pytest.mark.needs_node
def test_the_route_accepts_the_card_payload_the_browser_builds(tmp_path):
    """The other half: the shape above is what ``/api/bis/batch`` wants.

    The browser adds the ``slots`` list the card payload deliberately has no
    slot fields for, and the route writes ``slot_kind``/``slot_index`` per
    entry. Posting app.js's own payload proves the two agree.
    """
    payload = _payloads(tmp_path, ["targets.0"])["targets.0"]["batch"]
    payload["slots"] = [
        {"slot_kind": "boots", "slot_index": 0},
        {"slot_kind": "item", "slot_index": 0},
    ]
    response = app_module.app.test_client().post("/api/bis/batch", json=payload)
    assert response.status_code == 200, response.get_data(as_text=True)
    body = response.get_json()
    assert "error" not in body, body
    assert len(body["results"]) == 2


def test_the_roster_search_asks_the_batch_builder():
    """The wire itself, so a revert to the slot builder fails here."""
    request = APP_JS.split("async function requestBisBatch(path, slots) {")[1].split(
        "\n}"
    )[0]
    assert "bisBatchSubjectPayload(path)" in request
    assert "bisBackendPayload(path)" not in request
    assert 'postJson("/api/bis/batch"' in request
