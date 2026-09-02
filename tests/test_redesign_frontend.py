"""Contract tests for the 2a/2b redesign's own guarantees.

The ported issue suites (``test_f0_frontend``, ``test_frontend_qa_147_157``,
``test_p5_ux``, ``test_p1a_onboarding``) still own the criteria that predate
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
    page = app_module.app.test_client().get("/").get_data(as_text=True)
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


def test_opening_a_step_widens_the_rail_and_dims_the_live_canvas(css: str):
    """2b: the duel stays live but dimmed behind the editor."""
    editing = css[css.index(".app-grid.is-editing {") :][:400]
    assert "var(--rail-width-open)" in editing
    dim = re.search(r"\.app-grid\.is-editing \.canvas \{([^}]*)\}", css)
    assert dim is not None
    assert "opacity: .55" in dim.group(1)


def test_onboarding_followup_copy_stays_in_the_text_column(soup: BeautifulSoup):
    inline_css = "\n".join(style.get_text() for style in soup.select("head style"))
    assert ".onboarding-step > p" in inline_css
    assert "grid-column: 2" in inline_css


def test_roster_slots_keep_a_fixed_size_when_the_boots_slot_wraps(css: str):
    block = css[css.index(".roster-slot-wrap {") : css.index(".roster-slot-label {")]
    assert "flex: 0 0 34px;" in block
    assert "width: 34px;" in block
    assert "max-width: 34px;" in block

    phone = css[css.index("@media (max-width: 520px)") :]
    assert "flex-basis: 40px;" in phone
    assert ".roster-item-slot { height: 40px; }" in phone


def test_a_dimmed_canvas_is_also_inert(source: str):
    """Dimming without inerting would leave stale numbers clickable. Only
    rail-mode editing dims — centre-mode editing lives inside the canvas."""
    body = function_body(source, "function applyRailDisclosure()")
    assert "canvas.inert = railEditing" in body
    assert 'canvas.setAttribute("aria-hidden", String(railEditing))' in body


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


def test_only_one_step_and_one_constraint_row_open_at_a_time(source: str):
    body = function_body(source, "function applyRailDisclosure()")
    assert "state.ui.expandedStep === step" in body
    assert "state.ui.expandedConstraint === toggle.dataset.constraintToggle" in body
    handler = source.split(
        'const stepToggle = event.target.closest("[data-step-toggle]")'
    )[1]
    assert "state.ui.expandedConstraint = null" in handler.split("return;")[0]


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


def test_build_b_mirrors_build_a_around_the_spine(css: str):
    block = re.search(r"\.duel-b \.duel-row \{([^}]*)\}", css)
    assert block is not None
    assert "row-reverse" in block.group(1)
    assert "text-align: right" in block.group(1)


def test_delta_spine_bars_read_b_against_a(source: str):
    body = function_body(source, "function spineDivergence(")
    # Direction is metric-aware: lower is better for kill time.
    assert "metric.lower ? raw < 0 : raw > 0" in body
    assert 'favours: (metric.lower ? raw < 0 : raw > 0) ? "b" : "a"' in body


def test_spine_never_makes_colour_the_only_carrier(source: str):
    """Every row states both values and names the winner in its accessible
    name, so the green/red bar is decoration, not the message."""
    body = function_body(source, "function spineRowHtml(")
    assert "Build A ${escapeHtml(spoken(aLabel" in body
    assert "Build B ${escapeHtml(spoken(bLabel" in body
    assert '"Build B ahead"' in body
    assert '"Build A ahead"' in body
    assert 'aria-label="${escapeHtml(metric.label)}' in body


def test_spine_keeps_the_kill_time_exception_note(source: str):
    body = function_body(source, "function renderPrototypeResult(")
    assert "const lowerObjective = Object.values(OBJECTIVES)" in body
    assert "const directionNote = lowerObjective?.label" in body


def test_gold_delta_and_recommendation_ride_the_spine_footer(source: str):
    body = function_body(source, "function renderPrototypeResult(")
    assert '$("spineFoot").textContent' in body
    assert "Gold delta ${signedGold(goldDelta)}" in body


# ---------------------------------------------------------------------------
# Solo layout (locked decision 2)
# ---------------------------------------------------------------------------


def test_comparison_off_uses_a_dedicated_single_build_layout(css: str, source: str):
    block = re.search(r"\.duel\.is-solo \{([^}]*)\}", css)
    assert block is not None
    assert "justify-content: center" in block.group(1)
    assert re.search(r"\.duel\.is-solo \.duel-b \{[^}]*display: none", css)
    body = function_body(source, "function renderPrototypeResult(")
    assert 'classList.toggle("is-solo", !duelling)' in body


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


def test_solo_spine_shows_absolute_values(source: str):
    body = function_body(source, "function spineRowHtml(")
    assert 'class="spine-row is-solo"' in body
    assert "if (!comparing)" in body


# ---------------------------------------------------------------------------
# Honest numbers
# ---------------------------------------------------------------------------


def test_renderer_never_invents_the_roster_insight_sentence(source: str):
    """The 2b mock shows a "…pushes your best fifth slot from X to Y" callout.
    No backend receipt produces it, so it must not reach the DOM."""
    code = "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("//")
    )
    for invented in ("fifth slot", "Death's Dance push", "affects your BIS.".lower()):
        assert invented not in code, invented
    body = function_body(source, "function renderPrototypeRoster(")
    assert "no backend receipt produces that sentence" in body.lower()


def test_fight_chart_is_drawn_from_the_ordered_event_ledger(source: str):
    body = function_body(source, "function mainDamageSeries(")
    assert 'event.attacker === "main"' in body
    assert "result?.combat?.events" in body
    # No local damage model: the series is a cumulative sum of receipts.
    assert "running += row.damage" in body


def test_fight_chart_discloses_damage_it_could_not_place_in_time(source: str):
    body = function_body(source, "function renderFightChart(")
    assert "uncovered" in body
    assert "without an authored timestamp" in body


def test_cumulative_curve_is_carried_to_the_window_end(source: str):
    body = function_body(source, "function polylinePoints(")
    assert "last.time < duration" in body


def test_simultaneous_casts_share_one_marker(source: str):
    body = function_body(source, "function castMarkers(")
    assert "byTime" in body
    assert "CHART_MARK_LIMIT" in body


def test_item_prices_come_from_the_catalogue_not_a_formula(source: str):
    body = function_body(source, "function buildListPrice(")
    assert "getItem(id)?.price" in body
    # The helper is documented as reading catalogue data, not modelling it.
    preamble = source[: source.index("function buildListPrice(")][-600:]
    assert "receipts-only contract" in preamble
    # The receipts-only contract still holds for the redesign's own helpers.
    for banned in ("0.7025", "0.0175", "crit / 100"):
        assert banned not in source


def test_served_item_numbers_win_over_the_snapshot(source: str):
    """buildItemCatalog publishes the served entries verbatim: a served 0 is
    a real 0, and static/data.json carries no item that could outrank them."""
    assert "SNAPSHOT_NUMERIC_FIELDS" not in source
    assert "preferReportedNumbers" not in source
    body = function_body(source, "function buildItemCatalog(")
    assert "DATA.items = catalog.map((entry) => ({" in body
    assert "...entry," in body


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


def test_optimizer_receipts_survive_into_the_band(source: str):
    """Every truncation, withholding and coverage note the optimizer returns
    reaches the band — silently dropping one reads as a certified result."""
    purchase = function_body(source, "async function startPurchaseOptimize()")
    assert "exhaustive_within_scope" in purchase
    assert "budget-aware local search" in purchase
    assert "time budget" in purchase
    assert "search_timeline_coverage" in purchase
    # A best-buy winner is always applied with an honest guarantee label;
    # the silent "withheld · nothing applied" dead end is gone.
    assert "withheld" not in purchase
    # An item that cannot land in a visible slot is reported, never dropped.
    assert "Could not be placed" in purchase
    build = function_body(source, "async function optimizeMainBuildFromBackend()")
    assert "is_certified_best" in build
    assert "timeline_withheld_candidate_count" in build


def test_bis_dialog_keeps_every_coverage_note(source: str):
    body = function_body(source, "async function openBackendBis(path)")
    for receipt in (
        "certified subset · search not exhaustive",
        "withheld before timeline",
        "partial receipts withheld",
        "candidate_scope",
    ):
        assert receipt in body, receipt


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


def test_the_app_fills_the_viewport_not_a_floating_1440_card(css: str):
    """The mock's 1440px was its design canvas, not a product decision: the
    shell grows with the viewport instead of floating in dead wash."""
    block = re.search(r"\.app-card \{([^}]*)\}", css)
    assert block is not None
    assert "min(1440px" not in block.group(1)
    assert "width: 100%" in block.group(1)
    assert "min-height" in block.group(1)


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


def test_duel_rows_open_the_item_picker_for_their_exact_slot(source: str):
    """Filled or empty, a canvas slot row is a button wired into the same
    data-picker/data-path delegation step 3 uses — the duel is editable."""
    body = function_body(source, "function duelRowHtml(")
    assert "<button" in body
    assert 'data-picker="item"' in body
    render = function_body(source, "function renderDuelSide(")
    assert "attacker.build${side}.${index}" in render or "slotPath" in render
    # The keystone row opens the keystone picker, not the item picker.
    assert 'data-picker="keystone"' in render


def test_an_empty_duel_side_points_at_the_slots_directly_below_it(source: str):
    """ "Open step 3 to fill it" was a dead end even before step 3 left: the
    slot rows are right there, so the empty state names them."""
    render = function_body(source, "function renderDuelSide(")
    assert "is empty" in render
    assert "click any slot below to add an item" in render
    assert "data-step-toggle" not in render
    assert "roster-empty" not in render


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


def test_feedback_widget_is_a_collapsed_disclosure_that_waits_for_a_scenario():
    """The validation widget stays silent without a champion and collapses
    behind a summary otherwise — it never leads the canvas with Yes/No."""
    feedback = (ROOT / "static" / "js" / "feedback.js").read_text(encoding="utf-8")
    assert "<details" in feedback
    assert "feedback-body" in feedback
    assert "if (!STATE.champion)" in feedback
    # The old refreshContext re-parsed its own rendered HTML with a regex.
    assert "statusMarkup().match(" not in feedback


def test_feedback_widget_validates_the_displayed_payload(source: str):
    """A receipt's loadout is the exact /api/calculate payload behind the
    number on screen, published by app.js. The widget's old DOM re-capture
    (a different fight mode, an 18 cap, an empty roster) is gone, so the
    /api/validation bias flag is measured against what the UI displayed."""
    feedback = (ROOT / "static" / "js" / "feedback.js").read_text(encoding="utf-8")
    for gone in ("captureFromDom", "_snapshot", 'byId("championName")', "Math.min(18"):
        assert gone not in feedback, gone
    assert "window.scryglass.getCurrentLoadout" in feedback
    assert 'addEventListener("scryglass:result", refreshContext)' in feedback
    assert (
        "window.scryglass = { getCurrentLoadout: () => engine.responses?.requests.a"
        " ?? null, postJson };" in source
    )
    # C3: the widget posts through app.js's one JSON POST, not its own fetch.
    assert "fetch(" not in feedback
    assert 'window.scryglass.postJson("/api/receipts", body)' in feedback
    calculation = function_body(source, "function scheduleEngineCalculation()")
    assert "requests: { a: payloads[0], b: payloads[1] || null }" in calculation
    assert (
        'dispatchEvent(new CustomEvent("scryglass:result",'
        " { detail: engine.responses.a }))" in calculation
    )


def test_the_dead_quick_mode_layer_is_gone(source: str):
    """Quick mode's DOM left in 2026-08; its render/wiring layer survived as
    dead code addressing elements that do not exist. It is removed, while the
    shared utilities it grew (trust labels, share, practice targets) stay."""
    for gone in (
        "QUICK_STATE",
        "renderQuickView",
        "bindQuickEvents",
        "initQuickView",
        "switchView",
        'getElementById("quickRun")',
    ):
        assert gone not in source, gone
    for kept in (
        "PRACTICE_TARGETS",
        "function loadTrustLabels(",
        "function certaintyChipHtml(",
        "function initShareControls(",
    ):
        assert kept in source, kept


def test_engine_ready_is_dispatched_by_render_not_a_monkey_patch(source: str):
    """The old bootstrap reassigned render()/renderPrototypeChampion at the
    bottom of the file to bolt on an event and trust-label loads."""
    assert "__scryglassEngineReadyHook" not in source
    assert "_originalRenderPrototypeChampion" not in source
    body = function_body(source, "function render()")
    assert 'dispatchEvent(new Event("scryglass:engine-ready"))' in body


# ---------------------------------------------------------------------------
# Second interaction pass (2026-08-08): background, centre editing, the
# constraints banner, and closing an editor from the canvas.
# ---------------------------------------------------------------------------


def test_the_rift_illustration_is_the_page_background(soup: BeautifulSoup, css: str):
    """The page sits on the Summoner's Rift illustration (as the pre-redesign
    production page did), with an opaque dark base while the image loads."""
    wash = soup.select_one(".map-wash")
    assert wash is not None
    assert wash.get("aria-hidden") == "true"
    block = re.search(r"\.map-wash \{([^}]*)\}", css)
    assert block is not None
    assert "rift-background-user.webp" in block.group(1)
    assert "position: fixed" in block.group(1)
    assert re.search(r"background-color:\s*#[0-9a-f]{6}", block.group(1))


def test_panel_language_keeps_the_wash_visible_and_uses_system_sans(
    soup: BeautifulSoup, css: str
):
    """Panels stay translucent and typography uses the Apple system stack."""
    tokens = re.search(r":root\s*\{([^}]*)\}", css)
    assert tokens is not None
    assert re.search(r"--panel-alpha:\s*\.67", tokens.group(1))
    assert "--paper-panel: rgba(246, 242, 223, var(--panel-alpha))" in tokens.group(1)
    assert "--rail-panel: rgba(10, 23, 18, var(--panel-alpha))" in tokens.group(1)
    assert re.search(r"--font:\s*-apple-system,\s*BlinkMacSystemFont", tokens.group(1))
    assert "Godya Display" not in css
    assert "Manrope" not in css
    assert not soup.select(
        'link[href*="fonts.googleapis.com"], link[href*="fonts.gstatic.com"]'
    )
    assert re.search(r"\.app-card\s*\{[^}]*background: var\(--paper-panel\)", css)
    assert re.search(r"\.rail\s*\{[^}]*background: var\(--rail-panel\)", css)


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


def test_clicking_the_canvas_closes_an_open_step(source: str):
    """The dimmed duel (or the start state's whitespace) acts as Done. The
    close never swallows a live control's click and never fires on dialogs,
    which live outside #appGrid."""
    handler = source.split(
        'const stepToggle = event.target.closest("[data-step-toggle]")'
    )[1]
    close = handler.split('if (event.target.closest("#buyDismiss"))')[0]
    assert 'event.target.closest("#appGrid")' in close
    assert '!event.target.closest(".rail")' in close
    assert '!event.target.closest("#startEditor")' in close
    assert "state.ui.expandedStep = null" in close


def test_opening_the_champion_step_with_no_champion_opens_the_picker(source: str):
    """ "Choose your champion" means choose one: the checklist row (and the
    rail step) open the editor with the roster dialog already up."""
    handler = source.split(
        'const stepToggle = event.target.closest("[data-step-toggle]")'
    )[1]
    branch = handler.split("applyRailDisclosure();")[1].split("return;")[0]
    assert 'next === "champion" && !state.attacker.champion' in branch
    assert 'openPicker("champion", "attacker.champion")' in branch


# ---------------------------------------------------------------------------
# The event-order panel, driven headlessly through the real eventorder.js
# ---------------------------------------------------------------------------

EVENT_ORDER_JS = ROOT / "static" / "js" / "eventorder.js"
EVENT_ORDER_HARNESS = Path(__file__).resolve().parent / "js" / "event_order_harness.mjs"


def _event_order_panel(results, tmp_path):
    """Dispatch each result as one ``scryglass:result`` and read the mount."""
    node = shutil.which("node")
    if node is None:  # pragma: no cover - toolchain dependent
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
            "deterministic": True,
        },
    )
    assert response.status_code == 200
    return response.get_json()


def test_the_event_order_panel_renders_from_the_published_result(tmp_path):
    """eventorder.js used to wrap window.fetch to sniff /api/calculate, which
    forced it to load before app.js. It reads the receipt app.js publishes on
    "scryglass:result" instead — the same numbers, one script-order constraint
    fewer."""
    receipt = _calculate_receipt()
    assert receipt["rotation"]["order"] == ["Q", "W", "E", "R"]
    panel = _event_order_panel([receipt], tmp_path)
    assert panel["listened"] == 1
    rendered = panel["seen"][0]
    assert rendered["hidden"] is False
    for slot in receipt["rotation"]["order"]:
        assert f"<b>{slot}</b>" in rendered["html"]
    assert receipt["rotation"]["rationale"][:40] in rendered["html"]


def test_the_panel_stays_hidden_for_a_result_with_no_rotation(tmp_path):
    """A comparison response and an engine error both arrive on the same
    signal; neither carries a rotation receipt."""
    panel = _event_order_panel(
        [{"results": [{"total_damage": 1}]}, {"error": "Engine unavailable"}], tmp_path
    )
    assert [seen["hidden"] for seen in panel["seen"]] == [True, True]
    assert panel["seen"][0]["html"] == ""


def test_eventorder_never_touches_the_apps_own_request():
    source = EVENT_ORDER_JS.read_text(encoding="utf-8")
    for gone in ("window.fetch", "installFetchCapture", "__scryglassEventOrderCapture"):
        assert gone not in source, gone
    assert 'document.addEventListener("scryglass:result"' in source
