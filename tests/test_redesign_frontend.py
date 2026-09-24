"""Contract tests for the 2a/2b redesign's own guarantees.

The ported issue suites (``test_frontend_contract``, ``test_frontend_qa_regressions``,
``test_casual_ux_and_trust_labels``, ``test_onboarding``) still own the criteria that predate
the redesign. This file owns what the redesign itself promises, from
``docs/redesign/design-language.md`` and ``docs/redesign/gap-ledger.md``:

* the rail is a three-step wizard whose editors stay mounted while collapsed
* the duel canvas reads verdict -> mirrored builds + delta spine -> timeline
* colour is never the only carrier of win/lose state
* comparison off collapses to a dedicated single-build layout, never an
  empty Build B column (locked decision 2)
* every optimizer, coverage and not-modeled receipt has a visible home
* the renderer still invents nothing: no formulas, no item-id literals, and
  no insight sentence the backend did not supply
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

import src.app as app_module
from tests.app_config import app_config

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "static" / "js" / "app.js"
CSS = ROOT / "static" / "css" / "style.css"


@pytest.fixture(autouse=True)
def _isolate_app_config():
    with app_config(TESTING=True, RATE_LIMIT_ENABLED=False):
        yield


@pytest.fixture(scope="module")
def source() -> str:
    return APP_JS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def css() -> str:
    return CSS.read_text(encoding="utf-8")


@pytest.fixture
def soup() -> BeautifulSoup:
    page = app_module.app.test_client().get("/advanced").get_data(as_text=True)
    return BeautifulSoup(page, "html.parser")


def function_body(source: str, signature: str) -> str:
    """Return the text of one top-level function, brace-matched."""
    start = source.index(signature)
    depth = 0
    for index in range(start, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"unterminated function for {signature!r}")


# ---------------------------------------------------------------------------
# Layout concept: two permanent regions
# ---------------------------------------------------------------------------


def test_the_screen_is_a_rail_beside_a_canvas(soup: BeautifulSoup, css: str):
    grid = soup.select_one(".app-grid")
    assert grid is not None
    children = list(grid.find_all(recursive=False))
    assert [node.get("class")[0] for node in children] == ["rail", "canvas"]
    block = css[css.index(".app-grid {") : css.index(".app-grid.is-editing")]
    assert "grid-template-columns: var(--rail-width)" in block


def test_onboarding_followup_copy_stays_in_the_text_column(css: str):
    block = css[css.index(".onboarding-step > p") :]
    assert block.startswith(".onboarding-step > p { grid-column: 2;")


def test_shared_js_loads_before_the_scripts_that_read_it():
    """A page script that calls ``window.scryglass.onReady`` while it loads
    binds nothing unless shared.js ran first, so the reader set is derived
    and every one of them must sit below shared.js in the page."""
    scripts = ROOT / "static" / "js"
    index = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    loaded = re.findall(r'<script[^>]*src="/static/js/([^"]+)"', index)
    readers = [
        name
        for name in loaded
        if "window.scryglass.onReady(" in (scripts / name).read_text(encoding="utf-8")
    ]
    assert readers
    assert all(loaded.index(name) > loaded.index("shared.js") for name in readers)


def test_step_editors_stay_mounted_while_collapsed(soup: BeautifulSoup):
    """staleness.js reads #abilityRow at any time, and a collapsed step must
    not drop the state its summary describes."""
    for control_id in (
        "abilityRow",
        "championOptionsRow",
        "statsGrid",
    ):
        node = soup.select_one(f"#{control_id}")
        assert node is not None, control_id
        assert node.find_parent(class_="step-body") is not None, control_id


# ---------------------------------------------------------------------------
# Duel canvas
# ---------------------------------------------------------------------------


def test_canvas_bands_are_in_the_answer_first_order(soup: BeautifulSoup):
    canvas = soup.select_one(".canvas")
    order = [
        node.get("class", [None])[0] or node.get("id")
        for node in canvas.find_all(recursive=False)
    ]
    assert order[:2] == ["banners", "verdict"]
    for band in ("duel", "hp-band", "timeline-band", "ledger-band"):
        assert band in order, band
    assert order.index("duel") < order.index("timeline-band")
    assert order.index("timeline-band") < order.index("ledger-band")
    # The optimizer takeover band sits under the verdict, above the duel.
    assert order.index("buy-band") < order.index("duel")


# ---------------------------------------------------------------------------
# Solo layout (locked decision 2)
# ---------------------------------------------------------------------------


def test_solo_verdict_shows_absolutes_and_an_enable_affordance(
    soup: BeautifulSoup, css: str
):
    enable = soup.select_one("#enableBuildB")
    assert enable is not None
    assert enable.find_parent(class_="verdict-b") is not None
    assert enable.has_attr("data-toggle-compare")
    # In solo the empty challenger numbers are replaced, never left as dashes.
    assert re.search(
        r"\.verdict\.is-solo \.verdict-b \.verdict-number[^{]*\{[^}]*display: none", css
    )
    assert re.search(
        r"\.verdict\.is-solo \.verdict-enable \{[^}]*display: inline-block", css
    )


# ---------------------------------------------------------------------------
# Honest numbers
# ---------------------------------------------------------------------------


def test_item_stat_lines_actually_resolve_from_the_served_catalogue():
    """The stat line the UI shows is the served entry, so /api/items must
    carry real numbers (an older cache generation sent zeroes for all)."""
    client = app_module.app.test_client()
    served = {entry["name"]: entry for entry in client.get("/api/items").get_json()}
    with_stats = [
        name
        for name, entry in served.items()
        if any(entry[field] for field in ("ap", "ad", "hp", "armor", "mr"))
    ]
    assert len(with_stats) > len(served) // 2, "served catalogue must carry stats"
    deathcap = served["Rabadon's Deathcap"]
    assert deathcap["ap"] > 0
    assert deathcap["price"] > 0


# ---------------------------------------------------------------------------
# Receipts that must keep a visible home
# ---------------------------------------------------------------------------


def test_not_modeled_disclosure_sits_beside_the_verdict(soup: BeautifulSoup):
    panel = soup.select_one("#notModeledPanel")
    assert panel is not None
    assert panel.name == "details"
    assert panel.has_attr("hidden")
    assert "Qualified result" in panel.find("summary").get_text()
    canvas = soup.select_one(".canvas")
    order = list(canvas.find_all(recursive=False))
    assert order.index(panel) < order.index(soup.select_one(".duel"))


def test_certainty_chips_and_legend_survive(source: str, soup: BeautifulSoup):
    assert "certaintyChipHtml(row.slot)" in source
    assert soup.select_one("#trustLegend") is not None
    assert len(soup.select("#trustLegend .certainty-chip")) == 3


def test_scenario_sentence_stays_a_hidden_live_region(soup: BeautifulSoup):
    sentence = soup.select_one("#scenarioSentence")
    assert sentence is not None
    assert sentence.get("aria-live") == "polite"
    assert "visually-hidden" in sentence.get("class", [])


def test_share_panel_keeps_its_permanence_warning(soup: BeautifulSoup):
    note = soup.select_one(".share-panel-note")
    assert note is not None
    assert "permanent" in note.get_text().lower()
    assert "read-only" in note.get_text().lower()


# ---------------------------------------------------------------------------
# Interaction repairs (2026-08-08): the mock is a screen, not a poster.
# Each test below pins an affordance the first implementation pass missed.
# ---------------------------------------------------------------------------


def test_collapsed_briefs_are_click_targets_for_their_step(
    soup: BeautifulSoup, css: str
):
    """The champion/roster summary cards open their editor on click — not
    just the small Edit caption in the step header."""
    for brief_id, step in (
        ("championBrief", "champion"),
        ("rosterBrief", "roster"),
    ):
        brief = soup.select_one(f"#{brief_id}")
        assert brief is not None, brief_id
        assert brief.get("data-step-toggle") == step, brief_id
    assert re.search(r"\.step-brief\[data-step-toggle\] \{[^}]*cursor: pointer", css)


def test_comparison_can_be_turned_off_from_the_duel_itself(
    soup: BeautifulSoup, css: str, source: str
):
    """Enable Build B appears in solo; the duel must carry the way back.
    A toggle whose label reads as a status ("Build B enabled") is not a
    control — both affordances name the action they perform."""
    disable = soup.select_one("#disableBuildB")
    assert disable is not None
    assert disable.has_attr("data-toggle-compare")
    assert disable.find_parent(class_="verdict-b") is not None
    # Shown in duel mode, hidden in solo (where enable takes its place).
    assert re.search(r"\.verdict\.is-solo \.verdict-disable \{[^}]*display: none", css)
    enable = soup.select_one("#enableBuildB")
    assert enable is not None
    assert enable.has_attr("data-toggle-compare")
    assert "Enable Build B" in enable.get_text(strip=True)
    assert "Disable Build B" in disable.get_text(strip=True)


def test_first_run_shows_a_start_checklist_not_a_ghost_duel(
    soup: BeautifulSoup, css: str, source: str
):
    """Until the scenario has a champion, an enemy and items, the canvas
    leads with a three-step start checklist; the duel bands wait."""
    band = soup.select_one("#startBand")
    assert band is not None
    canvas = soup.select_one(".canvas")
    order = list(canvas.find_all(recursive=False))
    assert order.index(band) < order.index(soup.select_one(".duel"))
    for hidden_band in (".duel", ".hp-band", ".timeline-band", ".ledger-band"):
        assert re.search(
            r"\.canvas\.is-start "
            + re.escape(hidden_band)
            + r"[^{]*\{[^}]*display: none",
            css,
        ), hidden_band
    body = function_body(source, "function renderStartBand(")
    # Each checklist row opens the step it names through the shared handler.
    # Filling a build is not a checklist row: the duel panel that follows is
    # where that happens, and the engine already scores an itemless champion.
    assert 'data-step-toggle="${step}"' in body
    for step in ('"champion"', '"roster"'):
        assert step in body, step
    assert '"builds"' not in body
    assert 'classList.toggle("is-start"' in source


# ---------------------------------------------------------------------------
# Second interaction pass (2026-08-08): background, centre editing, the
# constraints banner, and closing an editor from the canvas.
# ---------------------------------------------------------------------------


def test_advanced_workspace_uses_the_shared_theme_adapter(soup: BeautifulSoup):
    assert "calculator-advanced" in soup.body.get("class", [])
    assert soup.body["data-theme"] == "paper"
    assert soup.select_one('link[href="/static/css/scryglass-theme.css"]') is not None
    adapter = Path("static/css/scryglass-theme.css").read_text()
    assert ".calculator-advanced .map-wash { display: none; }" in adapter
    assert "--paper-panel: var(--surface)" in adapter
    assert "--rail-panel: var(--surface)" in adapter


def test_advanced_workspace_loads_shared_fonts_and_theme_controls(soup: BeautifulSoup):
    assert soup.select_one('link[href="/static/calculator/calculator.css"]') is not None
    assert soup.select_one("#calculator-theme") is not None
    assert soup.select_one('script[src="/static/calculator/calculator.js"]') is not None
    fonts = soup.select('link[href*="fonts.googleapis.com/css"]')
    assert fonts and "Atkinson" in fonts[0]["href"]


def test_constraints_ride_the_canvas_as_a_banner(soup: BeautifulSoup, css: str):
    """The constraints shape every calculation, so they sit as a command bar
    directly under the verdict strip — not at the bottom of the rail."""
    bar = soup.select_one("#railConstraints")
    assert bar is not None
    assert bar.find_parent(class_="canvas") is not None
    assert bar.find_parent(class_="rail") is None
    canvas = soup.select_one(".canvas")
    order = list(canvas.find_all(recursive=False))
    assert order.index(soup.select_one(".verdict")) < order.index(bar)
    assert order.index(bar) < order.index(soup.select_one(".duel"))
    # All five rows plus the action stay wired.
    toggles = [
        t["data-constraint-toggle"] for t in bar.select("[data-constraint-toggle]")
    ]
    assert toggles == ["gold", "objective", "window", "state", "enemyHits"]
    assert bar.select_one("#economicsOptimize") is not None
    block = re.search(r"\.constraints-bar \{([^}]*)\}", css)
    assert block is not None
    assert "var(--rail-panel)" in block.group(1)


def test_pre_duel_editing_happens_centre_canvas(source: str, soup: BeautifulSoup):
    """Until the scenario is ready an open step's editor is relocated into
    #startEditor on the canvas; once the duel is live, editing returns to the
    widened rail. One DOM home per editor — moved, never duplicated."""
    assert soup.select_one("#startEditor") is not None
    body = function_body(source, "function applyRailDisclosure()")
    assert "const centreEditing = editing && !scenarioReady()" in body
    assert "centreHost.appendChild(body)" in body
    assert "section.appendChild(body)" in body
    assert 'classList.toggle("is-start-editing", centreEditing)' in body


# ---------------------------------------------------------------------------
# The event-order panel, driven headlessly through the real eventorder.js
# ---------------------------------------------------------------------------

EVENT_ORDER_JS = ROOT / "static" / "js" / "eventorder.js"
EVENT_ORDER_HARNESS = Path(__file__).resolve().parent / "js" / "event_order_harness.mjs"


def _event_order_panel(results, tmp_path):
    """Dispatch each result as one ``scryglass:result`` and read the mount."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    fixture = tmp_path / "fixture.json"
    fixture.write_text(json.dumps({"results": results}), encoding="utf-8")
    process = subprocess.run(
        [node, str(EVENT_ORDER_HARNESS), str(EVENT_ORDER_JS), str(fixture)],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(process.stdout)


def _calculate_receipt():
    response = app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Ziggs",
            "level": 11,
            "items": [],
            "target_health": 2000,
            "target_armor": 50,
            "target_mr": 50,
        },
    )
    assert response.status_code == 200
    return response.get_json()


@pytest.mark.needs_node
def test_the_event_order_panel_renders_from_the_published_result(tmp_path):
    """eventorder.js reads the receipt app.js publishes on "scryglass:result"
    rather than wrapping window.fetch to sniff /api/calculate, which would
    force it to load before app.js — the same numbers, one script-order
    constraint fewer."""
    receipt = _calculate_receipt()
    assert receipt["rotation"]["order"] == ["Q", "W", "E", "R"]
    panel = _event_order_panel([receipt], tmp_path)
    assert panel["listened"] == 1
    rendered = panel["seen"][0]
    assert rendered["hidden"] is False
    for slot in receipt["rotation"]["order"]:
        assert f"<b>{slot}</b>" in rendered["html"]
    assert receipt["rotation"]["rationale"][:40] in rendered["html"]


@pytest.mark.needs_node
def test_the_panel_stays_hidden_for_a_result_with_no_rotation(tmp_path):
    """A comparison response and an engine error both arrive on the same
    signal; neither carries a rotation receipt."""
    panel = _event_order_panel(
        [{"results": [{"total_damage": 1}]}, {"error": "Engine unavailable"}], tmp_path
    )
    assert [seen["hidden"] for seen in panel["seen"]] == [True, True]
    assert panel["seen"][0]["html"] == ""
