"""F0 ground-up frontend review contract tests.

These tests pin the F0 redesign without a browser:

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
    """The setup rail and duel canvas each exist once in the template.

    Redesign note: ``.content-grid`` (builder column + result column) became
    ``.app-grid`` (setup rail + duel canvas). The control surface below is
    unchanged — only its home moved.
    """
    soup = _soup()
    # The analyst view is the only builder host (quick removed 2026-08-06).
    assert soup.select_one("#analystView") is not None
    assert soup.select_one("#quickView") is None
    assert len(soup.select(".app-grid")) == 1
    assert len(soup.select(".rail")) == 1
    assert len(soup.select(".canvas")) == 1
    for control_id in (
        "championPicker",
        "championName",
        "statsGrid",
        "abilityRow",
        "championOptionsRow",
        "duelA",
        "duelB",
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


def test_every_setup_step_is_a_labelled_disclosure():
    """Each numbered rail step opens in place, and says so to assistive tech.
    The step-head button is the accessible disclosure; the collapsed brief
    card carries the same data-step-toggle as a large pointer target."""
    soup = _soup()
    heads = soup.select("button.step-toggle[data-step-toggle]")
    assert [t["data-step-toggle"] for t in heads] == ["champion", "roster"]
    for toggle in heads:
        assert toggle.get("aria-expanded") == "false"
        controls = toggle.get("aria-controls")
        assert controls and soup.select_one(f"#{controls}") is not None
        assert soup.select_one(f"#{controls}").has_attr("hidden")
    briefs = soup.select(".step-brief[data-step-toggle]")
    assert [b["data-step-toggle"] for b in briefs] == ["champion", "roster"]
    # Every editor stays mounted while collapsed: the staleness module reads
    # #abilityRow whether or not its step is open.
    assert soup.select_one("#abilityRow").find_parent(class_="step-body") is not None


def test_constraint_rows_are_labelled_disclosures():
    soup = _soup()
    rows = soup.select("[data-constraint-toggle]")
    assert [r["data-constraint-toggle"] for r in rows] == [
        "gold",
        "objective",
        "window",
        "state",
        "enemyHits",
    ]
    for row in rows:
        assert row.get("aria-expanded") == "false"
        body = soup.select_one(f"#{row['aria-controls']}")
        assert body is not None and body.has_attr("hidden")


def test_no_duplicate_ids_in_template():
    soup = _soup()
    ids = [node.get("id") for node in soup.select("[id]") if node.get("id")]
    assert len(ids) == len(set(ids)), "duplicate element ids in templates/index.html"


def test_quick_view_is_the_visible_default():
    """The ANALYST view is the app (product decision 2026-08-06): analyst is
    the visible default, quick mode is removed entirely, no view-switch tabs."""
    soup = _soup()
    assert soup.select_one("#quickView") is None
    analyst = soup.select_one("#analystView")
    assert analyst is not None and analyst.get("hidden") is None
    assert soup.select(".view-tab") == []


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


def test_damage_breakdown_lives_in_the_visible_ledger_band():
    """The breakdown is proof behind a deliberate expansion, on the canvas.

    Redesign note: its home moved from ``.result-card`` to the event-ledger
    band under the fight timeline. The criterion is unchanged — one instance,
    inside the visible analyst surface, never a detached container at the
    bottom of the page.
    """
    soup = _soup()
    breakdown = soup.select_one("#damageBreakdown")
    assert breakdown is not None
    assert breakdown.find_parent(class_="ledger-band") is not None
    assert breakdown.find_parent(class_="canvas") is not None
    assert breakdown.find_parent(id="analystView") is not None
    assert len(soup.select("#damageBreakdown")) == 1
    assert soup.select_one("#defenseReceipts").find_parent(class_="ledger-band")


def test_event_ledger_is_a_native_disclosure_with_the_trust_legend():
    soup = _soup()
    band = soup.select_one("#ledgerBand")
    assert band is not None and band.name == "details"
    summary = band.find("summary")
    assert summary is not None
    assert "Open event ledger" in summary.get_text()
    # The legend lives with the ledger header (gap ledger), not floating.
    assert soup.select_one("#trustLegend").find_parent(class_="ledger-band")


def test_engine_error_surface_lives_above_the_verdict():
    soup = _soup()
    error = soup.select_one("#engineError")
    assert error is not None
    assert error.find_parent(class_="banners") is not None
    assert error.find_parent(class_="canvas") is not None
    assert error.get("role") == "alert"
    # Banners sit above the verdict strip, never below the result they qualify.
    banners = soup.select_one(".banners")
    verdict = soup.select_one(".verdict")
    assert banners is not None and verdict is not None
    order = [node for node in soup.select(".canvas > *")]
    assert order.index(banners) < order.index(verdict)


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
    assert "vs target dummy" in button.get_text()
    source = _source()
    assert 'event.target.closest("#addPracticeEnemy")' in source
    assert "PRACTICE_TARGETS" in source
    assert "no-duplicate-champions" in source or "present.has" in source


def test_practice_target_is_the_passive_dummy_with_exact_stat_inputs():
    source = _source()
    assert 'const PRACTICE_DUMMY_KIND = "practice_dummy"' in source
    assert (
        'const PRACTICE_DUMMY_IMAGE = "/static/img/practice-dummy-enemy.png"' in source
    )
    assert "data-dummy-stat" in source
    assert "targetStatOverrides" in source
    assert "No skills or outgoing actions" in source
    assert (ROOT / "static" / "img" / "practice-dummy-enemy.png").is_file()


def test_ability_variant_buttons_write_the_declared_backend_option():
    source = _source()
    assert 'data-ability-variant="${ability.slot}"' in source
    assert (
        'abilityOptionBinding(ability.slot, "ability_variants") === option.key'
        in source
    )
    assert "options[option.key] = abilityInput(variantAbility.slot).variant" in source
    assert "input.variant = Number(abilityVariantButton.dataset.value)" in source
    assert (
        'const variantBinding = abilityOptionBinding(ability.slot, "ability_variants")'
        in source
    )
    assert "ability.variants?.length > 1 && variantBinding" in source
    assert "legacyVariantKeys" in source
    assert 'declared.has("hammer_stance") ? "hammer_stance" : "mega"' in source


def test_quick_to_analyst_bridge_is_wired():
    """Quick mode, its Open-in-Analyst bridge and the whole view-switching
    layer were removed; share links load directly into the analyst view."""
    soup = _soup()
    assert soup.select_one("#quickAnalystButton") is None
    source = _source()
    assert "switchView" not in source
    assert "renderSharedBuild(shareToken)" in source


def test_shared_link_loads_into_the_analyst_view():
    """Share tokens render directly in the analyst view (product decision
    2026-08-06) — no quick read-only card, no view switch."""
    source = _source()
    assert "renderSharedBuild(shareToken)" in source
    assert "loadSharedBuildIntoAnalyst(payload)" in source


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


def test_page_has_one_h1_and_a_sane_heading_order():
    """One page-level H1, then a H2 per setup step, then the champion name.

    Redesign note: the new IA has no visible page title — the rail header
    carries the brand — so the H1 is a screen-reader landmark. The heading
    tree must still describe the page: H1 page, H2 step, H3 champion.
    """
    soup = _soup()
    h1s = soup.select("h1")
    assert len(h1s) == 1
    assert "visually-hidden" in h1s[0].get("class", [])
    assert "calculator" in h1s[0].get_text(strip=True).lower()
    step_headings = soup.select(".step .step-head")
    assert [h.name for h in step_headings] == ["h2", "h2"]
    champion = soup.select_one("#championName")
    assert champion is not None and champion.name == "h3"


def test_visually_hidden_helper_actually_hides():
    css = _css()
    block = css.split(".visually-hidden {")[1].split("}")[0]
    assert "position: absolute" in block
    assert "clip-path" in block or "clip:" in block
    assert "width: 1px" in block


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
