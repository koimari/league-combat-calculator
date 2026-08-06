"""F0 ground-up frontend review contract tests.

These tests pin the F0 redesign (see docs/frontend-review-findings.md and
docs/frontend-design.md) without a browser:

* the analyst builder exists exactly once — no duplicate template ids, one
  ``.content-grid``, quick view is the visible default
* the damage breakdown and the engine error surface live inside the visible
  result column (previously hidden containers)
* dead renderers are gone (``renderBuilder``, ``renderResults``,
  ``renderExactResults``, ``renderEngineUnavailable`` and friends)
* the new affordances are wired: practice target, quick→analyst bridge,
  shared-link read-only mode, visible engine error, calculating state
* accessibility fixes: labelled range sliders, favicon, no stray 404
* ``node --check`` still passes for the shipped JS
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from bs4 import BeautifulSoup

import src.app as app_module

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "static" / "js" / "app.js"
CSS = ROOT / "static" / "css" / "style.css"


def _client():
    return app_module.app.test_client()


def _page():
    return _client().get("/").get_data(as_text=True)


def _soup():
    return BeautifulSoup(_page(), "html.parser")


def _source():
    return APP_JS.read_text(encoding="utf-8")


def _css():
    return CSS.read_text(encoding="utf-8")


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
    if previous_rate is None:
        app_module.app.config.pop("RATE_LIMIT_ENABLED", None)
    else:
        app_module.app.config["RATE_LIMIT_ENABLED"] = previous_rate


# ---------------------------------------------------------------------------
# A single analyst builder (the F0 de-duplication)
# ---------------------------------------------------------------------------


def test_analyst_builder_exists_exactly_once():
    """The analyst builder must not be duplicated in the template."""
    soup = _soup()
    # The P5 analyst view is the only builder host.
    assert soup.select_one("#analystView") is not None
    assert soup.select_one("#quickView") is not None
    assert len(soup.select(".content-grid")) == 1
    for control_id in (
        "championPicker",
        "championName",
        "statsGrid",
        "abilityRow",
        "championOptionsRow",
        "slotsA",
        "slotsB",
        "bisButton",
        "enemies",
        "allies",
        "resultStatus",
        "scoreA",
        "metricList",
        "healthRows",
        "timeline",
        "ledgerTable",
        "roleSelect",
        "levelInput",
        "stateReadout",
    ):
        assert len(soup.select(f"#{control_id}")) == 1, control_id


def test_no_duplicate_ids_in_template():
    soup = _soup()
    ids = [node.get("id") for node in soup.select("[id]") if node.get("id")]
    assert len(ids) == len(set(ids)), "duplicate element ids in templates/index.html"


def test_quick_view_is_the_visible_default():
    """Quick mode is the landing; the analyst view starts hidden."""
    soup = _soup()
    quick = soup.select_one("#quickView")
    analyst = soup.select_one("#analystView")
    assert quick is not None and analyst is not None
    assert quick.get("hidden") is None
    assert analyst.get("hidden") is not None
    tabs = soup.select(".view-tab")
    assert [tab.get("data-view") for tab in tabs] == ["quick", "analyst"]
    assert tabs[0].get("aria-selected") == "true"


def test_hidden_attribute_is_enforced_in_css():
    """Class display rules (e.g. .quick-view) must not override [hidden]."""
    css = _css()
    assert re.search(r"\[hidden\]\s*\{[^}]*display:\s*none\s*!important", css)


def test_share_analyst_button_is_reachable_inside_analyst_view():
    soup = _soup()
    button = soup.select_one("#shareAnalystButton")
    assert button is not None
    assert button.find_parent(id="analystView") is not None


# ---------------------------------------------------------------------------
# Visible result-column surfaces (previously hidden containers)
# ---------------------------------------------------------------------------


def test_damage_breakdown_lives_in_the_visible_result_column():
    soup = _soup()
    breakdown = soup.select_one("#damageBreakdown")
    assert breakdown is not None
    # The breakdown renders inside the result card of the analyst view
    # (renderExactBreakdown flips its own hidden attribute).  The only hidden
    # ancestor may be the analyst view wrapper itself, never a legacy
    # sibling container at the bottom of the page.
    result_card = breakdown.find_parent(class_="result-card")
    assert result_card is not None
    assert breakdown.find_parent(id="analystView") is not None
    # The old detached placement (sibling of the hidden legacy divs) is gone:
    # there is exactly one damageBreakdown and it is not a direct child of
    # the analystView wrapper.
    assert len(soup.select("#damageBreakdown")) == 1


def test_engine_error_surface_lives_in_the_result_column():
    soup = _soup()
    error = soup.select_one("#engineError")
    assert error is not None
    assert error.find_parent(class_="result-column") is not None
    assert error.get("role") == "alert"


def test_legacy_hidden_dom_is_removed():
    page = _page()
    for legacy_id in (
        "builder",
        "winnerVisual",
        "scoreGrid",
        "resistanceOutput",
        "threshold",
        "mechanicsOutput",
        "rotationTable",
        "resultContext",
        "resultFootnote",
        "tableA",
        "tableB",
        "baseDamage",
        "apRatio",
        "physicalDamage",
        "adRatio",
    ):
        assert f'id="{legacy_id}"' not in page, legacy_id


def test_engine_failures_render_visibly():
    source = _source()
    assert "showEngineError" in source
    assert "hideEngineError" in source
    assert 'document.getElementById("engineError")' in source
    assert 'status.textContent = "error"' in source
    # The old silent hidden-div error path must be gone.
    assert '$("why").textContent = failure.error' not in source
    assert '$("resultContext").textContent = "Engine boundary"' not in source


def test_calculating_pending_state_is_rendered():
    source = _source()
    assert 'status.textContent = "calculating"' in source
    assert 'status.classList.add("calculating")' in source
    assert 'status.classList.remove("calculating")' in source
    css = _css()
    assert "#resultStatus.calculating" in css


# ---------------------------------------------------------------------------
# New affordances
# ---------------------------------------------------------------------------


def test_practice_target_affordance_is_wired():
    soup = _soup()
    button = soup.select_one("#addPracticeEnemy")
    assert button is not None
    assert "vs practice target" in button.get_text()
    source = _source()
    assert 'event.target.closest("#addPracticeEnemy")' in source
    assert "PRACTICE_TARGETS" in source
    assert "no-duplicate-champions" in source or "present.has" in source


def test_quick_to_analyst_bridge_is_wired():
    soup = _soup()
    button = soup.select_one("#quickAnalystButton")
    assert button is not None
    assert "Open in analyst" in button.get_text()
    source = _source()
    assert (
        'document.getElementById("quickAnalystButton").addEventListener("click", openQuickInAnalyst)'
        in source
    )
    assert "function openQuickInAnalyst" in source
    assert 'switchView("analyst")' in source


def test_shared_link_read_only_mode_collapses_the_form():
    source = _source()
    assert 'classList.add("is-shared")' in source
    assert 'classList.remove("is-shared")' in source
    css = _css()
    assert ".quick-view.is-shared .quick-steps" in css


def test_bis_hint_when_scenario_incomplete():
    source = _source()
    assert "Best-in-slot needs an enemy roster" in source
    assert 'if (!bisReadyForPath("attacker.buildA.0"))' in source


# ---------------------------------------------------------------------------
# Dead code removal
# ---------------------------------------------------------------------------


def test_dead_renderers_are_removed():
    source = _source()
    for dead in (
        "function renderBuilder(",
        "function renderResults(",
        "function renderExactResults(",
        "function renderEngineUnavailable(",
        "function renderResistanceOutput(",
        "function renderDamageBreakdown(",
        "function renderMechanicsOutput(",
        "function renderExactStatMatrix(",
        "function renderExactResistance(",
        "function renderExactMechanics(",
        "function applyRosterBuild(",
        "function optimizeRosterBuild(",
        "function reoptimizeAttackerAfterRosterChange(",
        "function rosterBisCandidates(",
        "function rosterBisStacks(",
        "function bisCandidates(",
        "function stacksForBis(",
        "function openRosterBis(",
    ):
        assert dead not in source, dead
    # The live exact breakdown renderer survives.
    assert "function renderExactBreakdown(" in source


def test_manual_package_bindings_are_null_safe():
    source = _source()
    assert (
        'if (element) element.addEventListener("input", updateDamagePackage)' in source
    )
    assert 'const baseDamage = $("baseDamage");' in source


# ---------------------------------------------------------------------------
# Accessibility
# ---------------------------------------------------------------------------


def test_range_sliders_have_accessible_names():
    soup = _soup()
    for slider_id, label in (
        ("rotationRange", "Rotations"),
        ("durationRange", "Window per rotation"),
        ("uptimeRange", "Auto attack uptime percent"),
    ):
        node = soup.select_one(f"#{slider_id}")
        assert node is not None, slider_id
        assert node.get("aria-label") == label, slider_id


def test_favicon_link_present():
    soup = _soup()
    link = soup.select_one('link[rel="icon"]')
    assert link is not None and link.get("href")


def test_analyst_mode_has_a_single_visible_heading():
    """The analyst view has one page-level H1; the champion name is an H2."""
    soup = _soup()
    h1s = soup.select("#analystView h1")
    assert len(h1s) == 1
    assert h1s[0].get_text(strip=True) == "Item calculator"
    champion = soup.select_one("#championName")
    assert champion is not None and champion.name == "h2"


# ---------------------------------------------------------------------------
# JS sanity
# ---------------------------------------------------------------------------


def test_node_check_passes_for_app_js():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed on this machine")
    result = subprocess.run(
        [node, "--check", str(APP_JS)],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr
