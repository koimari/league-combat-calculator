"""Production QA regressions for front-end issues #147-#157.

Every test here pins one acceptance criterion from a GitHub ``front-end``
issue against the shipped template, stylesheet, or ``app.js`` source — the
same browser-free contract style as ``test_f0_frontend.py``.

Root cause worth remembering: the stylesheet's ``@media (max-width: 720px)``
block was never closed, so ``[hidden]``, ``.economics-bar``, ``.engine-error``
and ``.breakdown-panel`` silently applied only on phones. That one missing
brace is behind the "banner will not dismiss" (#147), "Best buy unreadable"
(#153) and "certainty legend always visible" (#157) reports, so
:func:`test_stylesheet_braces_balance` guards it directly.
"""

import json
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
INDEX = ROOT / "templates" / "index.html"


@pytest.fixture(autouse=True)
def _isolate_app_config():
    """Keep these route tests off the shared rate-limit budget."""
    previous_testing = app_module.app.config.get("TESTING")
    previous_rate = app_module.app.config.get("RATE_LIMIT_ENABLED", True)
    app_module.app.config["TESTING"] = True
    app_module.app.config["RATE_LIMIT_ENABLED"] = False
    yield
    app_module.app.config["TESTING"] = previous_testing
    app_module.app.config["RATE_LIMIT_ENABLED"] = previous_rate


@pytest.fixture(scope="module")
def source() -> str:
    return APP_JS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def css() -> str:
    return CSS.read_text(encoding="utf-8")


@pytest.fixture()
def page() -> str:
    return app_module.app.test_client().get("/").get_data(as_text=True)


@pytest.fixture()
def soup(page: str) -> BeautifulSoup:
    return BeautifulSoup(page, "html.parser")


def rule_block(css_text: str, selector: str) -> str:
    """Return the declaration block of the first rule matching ``selector``."""
    match = re.search(
        rf"(?:^|[}}\s]){re.escape(selector)}\s*(?:,[^{{}}]*?)?\{{([^}}]*)\}}",
        css_text,
        re.MULTILINE,
    )
    assert match, f"no CSS rule found for {selector!r}"
    return match.group(1)


# ---------------------------------------------------------------------------
# Stylesheet integrity — the root cause behind several of these reports
# ---------------------------------------------------------------------------


def test_stylesheet_braces_balance(css: str):
    """An unclosed block silently scopes the rest of the file to one media
    query. Nothing may be left open at EOF."""
    without_comments = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    depth = 0
    for line_number, line in enumerate(without_comments.splitlines(), start=1):
        depth += line.count("{") - line.count("}")
        assert depth >= 0, f"stylesheet closes an unopened block at line {line_number}"
    assert depth == 0, f"stylesheet ends with {depth} unclosed block(s)"


def test_hidden_attribute_contract_is_unconditional(css: str):
    """``[hidden]`` drives every JS-toggled surface; it must not sit inside a
    media query (issue #147's inert dismiss, #157's ever-present legend)."""
    index = css.index("[hidden]")
    prefix = re.sub(r"/\*.*?\*/", "", css[:index], flags=re.S)
    assert prefix.count("{") == prefix.count(
        "}"
    ), "[hidden] is nested inside an unclosed block"


# ---------------------------------------------------------------------------
# #147 — shared-build banner actions
# ---------------------------------------------------------------------------


def test_share_controls_initialize_without_quick_view(source: str):
    """Share wiring lives in its own initializer, not inside the removed
    quick-view setup that early-returns when ``#quickView`` is absent."""
    assert "function initShareControls()" in source
    assert re.search(r"^initShareControls\(\);", source, re.MULTILINE)

    share_block = source.split("function initShareControls()")[1].split("\n}\n")[0]
    for control in ("shareOpenEditor", "shareDismiss", "shareAnalystButton"):
        assert control in share_block, f"{control} is not wired by initShareControls"

    quick_block = source.split("function bindQuickEvents()")[1].split("\n}\n")[0]
    for control in ("shareOpenEditor", "shareDismiss", "shareAnalystButton"):
        assert (
            control not in quick_block
        ), f"{control} is still coupled to the removed quick view"


def test_share_token_is_read_outside_quick_view_init(source: str):
    """``?share=`` must be honored on a template with no quick view."""
    share_block = source.split("function initShareControls()")[1].split("\n}\n")[0]
    assert 'params.get("share")' in share_block
    assert "renderSharedBuild(shareToken)" in share_block


def test_shared_payload_waits_for_the_item_catalogue(source: str):
    """The payload resolves item *names* against the catalogue, so applying it
    before the patch snapshot loads would drop every item silently."""
    share_block = source.split("function initShareControls()")[1].split("\n}\n")[0]
    assert "whenEngineReady(() => renderSharedBuild(shareToken))" in share_block
    ready = source.split("function whenEngineReady(callback)")[1].split("\n}\n")[0]
    assert "engine.itemCatalogReady" in ready
    assert "scryglass:engine-ready" in ready


def test_share_controls_bind_before_the_snapshot_loads(source: str):
    """Binding must not be deferred with the payload — inert controls are the
    bug (#147). The listeners attach in the same synchronous pass."""
    share_block = source.split("function initShareControls()")[1].split("\n}\n")[0]
    bind_section = share_block.split("whenEngineReady")[0]
    for control in ("shareOpenEditor", "shareDismiss"):
        assert control in bind_section


def test_share_dismiss_clears_the_query_parameter(source: str):
    block = source.split("function initShareControls()")[1].split("\n}\n")[0]
    assert 'searchParams.delete("share")' in block
    assert "history.replaceState" in block


def test_open_in_editor_does_not_depend_on_quick_view(source: str):
    block = source.split("function openSharedBuildInEditor()")[1].split("\n}\n")[0]
    assert "loadSharedBuildIntoAnalyst(payload)" in block
    assert "quickView" not in block
    # A share that never resolved must say so rather than sit inert.
    assert "shareBannerText" in block


def test_shared_build_render_targets_the_analyst_view(source: str):
    """The shared payload renders into the live result column; the old
    ``#quickResults`` host no longer exists in the template."""
    block = source.split("async function renderSharedBuild(token)")[1].split(
        "\nfunction "
    )[0]
    assert "quickResults" not in block
    assert "loadSharedBuildIntoAnalyst(payload)" in block
    assert "showShareError(" in block, "invalid/expired shares must surface an error"
    error_surface = source.split("function showShareError(message)")[1].split(
        "\nfunction "
    )[0]
    assert 'host.id = "shareError"' in error_surface
    assert "engine-error" in error_surface


def test_switch_view_tolerates_a_missing_quick_view(source: str):
    block = source.split("function switchView(view)")[1].split("\n}\n")[0]
    assert "if (quick)" in block or "quick?." in block or "if (!quick)" in block


# ---------------------------------------------------------------------------
# #148 — brand link stays inside the current app
# ---------------------------------------------------------------------------


def test_brand_link_points_at_the_canonical_app_home(soup: BeautifulSoup):
    brand = soup.select_one("a.brand")
    assert brand is not None
    assert brand["href"] == "/"
    assert "scryglass.xyz" not in str(brand)


def test_no_template_routes_users_to_the_retired_site():
    for template in ROOT.joinpath("templates").glob("*.html"):
        assert "scryglass.xyz" not in template.read_text(
            encoding="utf-8"
        ), f"{template.name} still links to the retired site"


def test_brand_link_returns_home_from_a_shared_url():
    """A root-relative href resolves to the app home from nested/shared URLs."""
    client = app_module.app.test_client()
    page = client.get("/?share=abc123").get_data(as_text=True)
    brand = BeautifulSoup(page, "html.parser").select_one("a.brand")
    assert brand["href"] == "/"
    assert client.get(brand["href"]).status_code == 200


# ---------------------------------------------------------------------------
# #149 — page heading readable over the background
# ---------------------------------------------------------------------------


def test_page_heading_uses_a_deliberate_light_treatment(css: str):
    block = rule_block(css, ".app-shell h1")
    assert "#fff" in block.lower() or "var(--white)" in block
    assert "text-shadow" in block


def test_page_heading_is_not_left_to_default_ink(css: str):
    """The dead ``.app-shell > h1`` screen-reader rule never matched the
    nested heading; it must not linger and imply the title is hidden."""
    assert ".app-shell > h1" not in css


def test_heading_remains_legible_without_the_background_image(css: str):
    """``.map-wash`` keeps an opaque dark colour under the illustration, so a
    light heading stays readable if the image never loads."""
    block = rule_block(css, ".map-wash")
    assert "background-color:" in block


# ---------------------------------------------------------------------------
# #150 — Theory / Snapshot explained before selection
# ---------------------------------------------------------------------------


def test_game_state_buttons_carry_accessible_descriptions(soup: BeautifulSoup):
    theory = soup.select_one("#stateTheory")
    live = soup.select_one("#stateLive")
    assert theory["aria-describedby"] == "stateTheoryHelp"
    assert live["aria-describedby"] == "stateLiveHelp"
    assert soup.select_one("#stateTheoryHelp") is not None
    assert soup.select_one("#stateLiveHelp") is not None


def test_game_state_descriptions_explain_both_modes(soup: BeautifulSoup):
    theory = soup.select_one("#stateTheoryHelp").get_text(" ", strip=True).lower()
    live = soup.select_one("#stateLiveHelp").get_text(" ", strip=True).lower()
    assert "unconstrained" in theory
    for constraint in ("level", "role quest", "inventory"):
        assert constraint in live, f"Snapshot copy never mentions {constraint}"


def test_active_game_state_summary_is_a_live_region(soup: BeautifulSoup):
    summary = soup.select_one("#gameStateHelp")
    assert summary is not None
    assert summary.get("aria-live") == "polite"


def test_game_state_summary_follows_the_selected_mode(source: str):
    """The visible summary is derived from the active button's description —
    one home for the copy, no duplicated strings in JS."""
    block = source.split("function renderScenarioRail()")[1].split("\n}\n")[0]
    assert "gameStateHelp" in block
    assert "aria-describedby" in block or "describedby" in block


# ---------------------------------------------------------------------------
# #151 — level changes never blank the stats panel
# ---------------------------------------------------------------------------


def test_invalidation_keeps_the_last_known_loadout_stats(source: str):
    block = source.split("function invalidateOptimization()")[1].split("\n}\n")[0]
    assert (
        "engine.loadoutStats = null" not in block
    ), "dropping the cached stats blanks the panel mid-recalculation"
    assert "loadoutStatsKey" in block


def test_stats_grid_shows_a_scoped_pending_state(source: str):
    block = source.split("function renderPrototypeChampion()")[1].split("\n}\n")[0]
    assert "statsGrid" in block
    assert "aria-busy" in block
    assert "is-pending" in block


def test_stats_placeholder_only_appears_before_any_stats_exist(source: str):
    block = source.split("function renderPrototypeChampion()")[1].split("\n}\n")[0]
    placeholder_line = next(
        line for line in block.splitlines() if "matrix-placeholder" in line
    )
    assert "stats ?" in placeholder_line


def test_loadout_stats_ignores_out_of_order_responses(source: str):
    block = source.split("function scheduleLoadoutStats()")[1].split("\n}\n")[0]
    assert "loadoutStatsRequestId" in block


def test_level_output_announces_the_new_level(soup: BeautifulSoup):
    output = soup.select_one("#levelOutput")
    assert output.get("aria-live") == "polite"


def test_pending_stats_stay_visible_rather_than_hidden(css: str):
    block = rule_block(css, ".stats-grid.is-pending")
    assert "display: none" not in block
    assert "opacity" in block


# ---------------------------------------------------------------------------
# #152 — Find best item gated on a selected enemy
# ---------------------------------------------------------------------------


def test_bis_prerequisite_is_evaluated_on_every_render(source: str):
    assert "function applyPrerequisiteGates()" in source
    render_block = source.split("\nfunction render() {")[1].split("\n}\n")[0]
    assert "applyPrerequisiteGates()" in render_block


def test_bis_button_disables_without_a_complete_enemy(source: str):
    block = source.split("function applyPrerequisiteGates()")[1].split("\n}\n")[0]
    assert "bisButton" in block
    assert "bisReadyForPath" in block or "state.targets" in block
    assert "disabled" in block


def test_bis_prerequisite_message_sits_next_to_the_control(soup: BeautifulSoup):
    note = soup.select_one("#bisPrerequisite")
    assert note is not None, "the prerequisite note must live beside the BIS button"
    button = soup.select_one("#bisButton")
    assert (
        note.find_previous("button", id="bisButton") is button
        or note.find_next("button", id="bisButton") is button
    )


def test_bis_button_exposes_its_prerequisite_to_assistive_tech(soup: BeautifulSoup):
    button = soup.select_one("#bisButton")
    assert button["aria-describedby"] == "bisPrerequisite"


def test_blocked_bis_offers_a_direct_path_to_add_enemy(source: str):
    block = source.split("function applyPrerequisiteGates()")[1].split("\n}\n")[0]
    assert "bisAddEnemy" in block or "addEnemy" in block
    soup = BeautifulSoup(
        app_module.app.test_client().get("/").get_data(as_text=True), "html.parser"
    )
    assert soup.select_one("#bisAddEnemy") is not None


# ---------------------------------------------------------------------------
# #153 — Best buy panel readable
# ---------------------------------------------------------------------------


def test_economics_panel_sits_on_an_opaque_surface(css: str):
    block = rule_block(css, ".economics-bar")
    match = re.search(r"background:\s*rgba\([^)]*?,\s*([\d.]+)\s*\)", block)
    assert match, "the economics panel needs an explicit background"
    assert float(match.group(1)) >= 0.9, "surface is too transparent to read over"


def test_economics_copy_uses_readable_ink(css: str):
    helper = rule_block(css, ".economics-bar small")
    assert "var(--ink-soft)" in helper or "var(--ink)" in helper
    label = rule_block(css, ".economics-bar label")
    assert "var(--ink-soft)" in label or "var(--ink)" in label


def test_economics_controls_reflow_at_narrow_widths(css: str):
    """The panel must not collapse into one unreadable inline sentence."""
    assert re.search(
        r"@media \(max-width: 1080px\)[^@]*?\.economics-bar\s*\{", css, re.S
    ), "no intermediate breakpoint for the economics grid"


def test_economics_disabled_state_stays_legible(css: str):
    block = rule_block(css, ".economics-bar button:disabled")
    match = re.search(r"opacity:\s*([\d.]+)", block)
    assert match and float(match.group(1)) >= 0.6


# ---------------------------------------------------------------------------
# #154 — keystone artwork bounded to slot scale
# ---------------------------------------------------------------------------


def test_keystone_icon_has_an_explicit_size_contract(css: str):
    block = rule_block(css, ".keystone-icon")
    for declaration in ("width", "height", "aspect-ratio"):
        assert declaration in block, f"keystone icon is missing {declaration}"


def test_keystone_image_is_bounded_and_cropped(css: str):
    block = rule_block(css, ".keystone-icon img")
    assert "object-fit" in block
    assert "width: 100%" in block and "height: 100%" in block


def test_keystone_slot_matches_the_item_slot_grammar(css: str):
    block = rule_block(css, ".item-slot")
    assert "width" in block, "the shared slot class needs a bounded width"


def test_keystone_label_wraps_instead_of_stretching_the_card(css: str):
    block = rule_block(css, ".keystone-slot small")
    assert "overflow" in block or "text-overflow" in block


# ---------------------------------------------------------------------------
# #155 — legible event timeline
# ---------------------------------------------------------------------------


def test_timeline_renders_one_lane_per_event(source: str):
    block = source.split("function renderEventTimeline(")[1].split("\nfunction ")[0]
    assert "timeline-event" in block
    assert "<ol" in block, "ordered-list semantics expose event order to AT"


def test_timeline_labels_are_not_truncated_to_fragments(source: str):
    block = source.split("function renderEventTimeline(")[1].split("\nfunction ")[0]
    assert ".slice(0, 3)" not in block, "3-character source fragments are unreadable"


def test_timeline_rows_are_keyed_to_the_ledger_table(source: str):
    assert "data-event-index" in source
    ledger = source.split('$("ledgerTable").innerHTML')[1].split("\n")[0]
    timeline = source.split("function renderEventTimeline(")[1].split("\nfunction ")[0]
    assert "data-event-index" in timeline
    assert "data-event-index" in ledger or "eventRows" in ledger


def test_timeline_label_size_meets_the_legibility_floor(css: str):
    block = rule_block(css, ".timeline-event")
    match = re.search(r"font-size:\s*(\d+(?:\.\d+)?)px", block)
    assert match and float(match.group(1)) >= 12


def test_dense_timelines_scroll_instead_of_overlapping(css: str):
    block = rule_block(css, ".timeline-events")
    assert "overflow-y: auto" in block
    assert "max-height" in block


def test_marker_collision_geometry_is_gone(css: str):
    """Absolutely positioned 17px markers on a shared 1px line collided; the
    lane layout replaces them."""
    assert ".timeline-line i" not in css


def lift_const(source: str, name: str) -> str:
    """Return the full ``const <name> = ...;`` declaration from ``source``.

    Brace-aware so multi-line arrow bodies come back whole; a plain regex
    stops at the first ``;`` inside the body.
    """
    match = re.search(rf"^const {name} = ", source, re.MULTILINE)
    assert match, f"helper {name} not found in app.js"
    depth = 0
    for index in range(match.start(), len(source)):
        character = source[index]
        if character in "{([":
            depth += 1
        elif character in "})]":
            depth -= 1
        elif character == ";" and depth == 0:
            return source[match.start() : index + 1]
    raise AssertionError(f"unterminated declaration for {name}")


def run_timeline_renderer(events: list[dict], duration: float) -> str:
    """Execute the shipped renderEventTimeline() in node against ``events``.

    The renderer is pure given its arguments, so it can be lifted out of
    ``app.js`` verbatim and exercised for real — a source grep cannot tell us
    whether a dense or simultaneous timeline actually comes out legible.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed on this machine")
    source = APP_JS.read_text(encoding="utf-8")
    body = source.split("function renderEventTimeline(")[1].split("\nfunction ")[0]
    # Lift the helpers from app.js rather than restating them: a hand-written
    # copy of fmt()/one() drifts from the shipped formatting and the test
    # would then be asserting against a renderer nobody runs.
    helpers = [
        lift_const(source, name)
        for name in ("escapeHtml", "fmt", "one", "plural", "eventTime")
    ]
    limit = re.search(r"^const TIMELINE_EVENT_LIMIT = \d+;$", source, re.MULTILINE)
    assert limit, "TIMELINE_EVENT_LIMIT not found in app.js"
    harness = f"""
{limit.group(0)}
{chr(10).join(helpers)}
function renderEventTimeline({body}
const events = {json.dumps(events)};
process.stdout.write(renderEventTimeline(events, {duration}, (id) => id || "Participant"));
"""
    result = subprocess.run(
        [node, "-e", harness], capture_output=True, text=True, cwd=ROOT, check=False
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def event(time: float, source: str, damage: float = 100.0, **extra) -> dict:
    return {
        "time": time,
        "source": source,
        "attacker": "Ahri",
        "target": "Garen",
        "damage": damage,
        **extra,
    }


def test_sparse_timeline_names_every_source_in_full():
    html = run_timeline_renderer(
        [event(0.5, "Orb of Deception"), event(3.25, "Charm")], 10
    )
    assert html.count('class="timeline-event"') == 2
    # The old renderer cut these to "Orb" and "Cha".
    assert "Orb of Deception" in html
    assert "Charm" in html
    assert "0.5s" in html and "3.3s" in html
    assert "2 ordered events, oldest first" in html


def test_simultaneous_events_get_separate_lanes():
    """Same-timestamp events used to stack markers on top of each other."""
    html = run_timeline_renderer(
        [event(4.0, "Orb of Deception"), event(4.0, "Spellblade"), event(4.0, "Comet")],
        10,
    )
    assert html.count('class="timeline-event"') == 3
    for source in ("Orb of Deception", "Spellblade", "Comet"):
        assert source in html
    # Every lane keeps its own visible timestamp, so the order is unambiguous.
    # one() strips the trailing .0, so 4.0 renders as "4s".
    assert html.count(">4s<") == 3


def test_dense_timeline_reports_what_it_did_not_draw():
    html = run_timeline_renderer([event(i / 10, f"Hit {i}") for i in range(150)], 15)
    assert html.count('class="timeline-event"') == 60
    assert "First 60 of 150 ordered events" in html, "a silent cap reads as complete"


def test_timeline_lanes_carry_their_index_and_position():
    html = run_timeline_renderer([event(0.0, "Q"), event(5.0, "R")], 10)
    assert 'data-event-index="0"' in html
    assert 'data-event-index="1"' in html
    assert "--at:0%" in html and "--at:50%" in html


def test_timeline_escapes_untrusted_source_text():
    html = run_timeline_renderer([event(1.0, '<img src=x onerror="alert(1)">')], 10)
    assert "<img" not in html
    assert "&lt;img" in html


def test_timeline_states_when_no_events_returned():
    html = run_timeline_renderer([], 10)
    assert "No participant event ledger returned." in html
    assert "timeline-event" not in html


def test_timeline_skips_events_without_a_usable_timestamp():
    html = run_timeline_renderer(
        [event(1.0, "Q"), event(None, "Withheld"), event(2.0, "W")], 10
    )
    assert html.count('class="timeline-event"') == 2
    assert "Withheld" not in html


def test_timeline_shows_a_reason_when_an_event_dealt_no_damage():
    html = run_timeline_renderer(
        [event(1.0, "Q", damage=0, skipped_reason="out of range")], 10
    )
    assert "out of range" in html


# ---------------------------------------------------------------------------
# #156 — no clipping or overlap in the result panel
# ---------------------------------------------------------------------------


def test_result_card_no_longer_crops_expanded_content(css: str):
    block = rule_block(css, ".result-card")
    assert "overflow: hidden" not in block


def test_result_column_is_the_single_sticky_boundary(css: str):
    block = rule_block(css, ".result-column")
    assert "position: sticky" in block
    assert "max-height" in block
    assert "overflow-y: auto" in block


def test_result_column_releases_the_sticky_frame_on_narrow_screens(css: str):
    narrow = css.split("@media (max-width: 800px)")[1].split("@media")[0]
    assert ".result-column" in narrow
    assert "position: static" in narrow


def test_ledger_lines_wrap_instead_of_colliding(css: str):
    block = rule_block(css, ".ledger-line")
    assert "flex-wrap: wrap" in block or "overflow-wrap" in block
    span = rule_block(css, ".ledger-line span")
    assert "overflow-wrap: anywhere" in span


def test_breakdown_receipts_use_on_card_contrast(css: str):
    """The receipts render inside the dark result card; dark ink there is
    invisible (the reported 'Starting defenses' collision)."""
    block = rule_block(css, ".breakdown-panel .breakdown-outcome")
    assert "var(--ink)" not in block


def test_receipt_tables_scroll_within_the_panel(css: str):
    block = rule_block(css, ".breakdown-panel .damage-table-wrap")
    assert "overflow-x: auto" in block


# ---------------------------------------------------------------------------
# #157 — certainty legend stays visible
# ---------------------------------------------------------------------------


def test_certainty_legend_participates_in_flow(css: str):
    block = rule_block(css, ".analyst-trust-legend")
    assert "position: sticky" not in block
    assert "position: fixed" not in block


def test_certainty_legend_is_hidden_until_a_result_exists(soup: BeautifulSoup):
    legend = soup.select_one("#trustLegend")
    assert legend.has_attr("hidden")


def test_certainty_legend_sits_inside_the_scrolling_result_column(soup: BeautifulSoup):
    legend = soup.select_one("#trustLegend")
    assert legend.find_parent(class_="result-column") is not None
    assert legend.find_parent(class_="result-card") is None


def test_certainty_chips_meet_the_readable_size_floor(css: str):
    block = rule_block(css, ".certainty-chip")
    match = re.search(r"font:\s*\d+\s+(\d+(?:\.\d+)?)px", block)
    assert match, "certainty chips need an explicit font size"
    assert float(match.group(1)) >= 11


def test_legend_note_stays_readable_on_its_surface(css: str):
    block = rule_block(css, ".trust-legend-note")
    match = re.search(r"font-size:\s*(\d+(?:\.\d+)?)px", block)
    assert match and float(match.group(1)) >= 12
