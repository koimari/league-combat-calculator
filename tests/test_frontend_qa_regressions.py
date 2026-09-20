"""Production QA regressions for front-end issues #147-#157.

Every test here pins one acceptance criterion from a GitHub ``front-end``
issue against the shipped template, stylesheet, or ``app.js`` source — the
same browser-free contract style as ``test_frontend_contract.py``.

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
from tests.app_config import app_config

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "static" / "js" / "app.js"
CSS = ROOT / "static" / "css" / "style.css"
INDEX = ROOT / "templates" / "index.html"


@pytest.fixture(autouse=True)
def _isolate_app_config():
    """Keep these route tests off the shared rate-limit budget."""
    with app_config(TESTING=True, RATE_LIMIT_ENABLED=False):
        yield


@pytest.fixture(scope="module")
def source() -> str:
    return APP_JS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def css() -> str:
    return CSS.read_text(encoding="utf-8")


@pytest.fixture
def page() -> str:
    return app_module.app.test_client().get("/advanced").get_data(as_text=True)


@pytest.fixture
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
    without_comments = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    depth = 0
    for line_number, line in enumerate(without_comments.splitlines(), start=1):
        depth += line.count("{") - line.count("}")
        assert depth >= 0, f"stylesheet closes an unopened block at line {line_number}"
    assert depth == 0, f"stylesheet ends with {depth} unclosed block(s)"


# ---------------------------------------------------------------------------
# #147 — shared-build banner actions
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# #148 — brand link stays inside the current app
# ---------------------------------------------------------------------------


def test_brand_link_points_at_the_canonical_app_home(soup: BeautifulSoup):
    brand = soup.select_one("a.brand")
    assert brand is not None
    assert brand["href"] == "/"
    assert "scryglass.xyz" not in str(brand)


def test_calculator_shell_links_to_the_sister_research_site():
    for name in ("index.html", "calculator.html"):
        soup = BeautifulSoup(
            ROOT.joinpath("templates", name).read_text(), "html.parser"
        )
        research = soup.select_one(
            '.calculator-shell-nav a[href="https://scryglass.xyz"]'
        )
        assert research is not None
        assert "Research" in research.get_text()
        assert soup.select_one(".calculator-shell-brand")["href"] == "/"


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


def test_the_map_wash_is_decorative_only(css: str, page: str):
    """The Rift illustration returned as the page background (user decision
    2026-08-08), but #149's criterion survives: nothing readable sits on the
    wash. It is aria-hidden, pointer-inert, behind everything, and keeps an
    opaque base colour; each panel carries its own translucent layer and blur."""
    assert 'class="map-wash" aria-hidden="true"' in page
    block = rule_block(css, ".map-wash")
    assert "z-index: -1" in block
    assert "pointer-events: none" in block
    assert re.search(r"background-color:\s*#[0-9a-f]{6}", block)
    assert ".app-shell" not in css


def test_the_page_title_is_a_screen_reader_landmark(soup: BeautifulSoup):
    heading = soup.select_one("h1")
    assert heading is not None
    assert "visually-hidden" in heading.get("class", [])


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


# ---------------------------------------------------------------------------
# #151 — level changes never blank the stats panel
# ---------------------------------------------------------------------------


def test_level_output_announces_the_new_level(soup: BeautifulSoup):
    output = soup.select_one("#levelOutput")
    assert output.get("aria-live") == "polite"


# ---------------------------------------------------------------------------
# #152 — Find best item gated on a selected enemy
# ---------------------------------------------------------------------------


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
    block = source.split("function applyPrerequisiteGates()")[1].split(
        "\n}\n", maxsplit=1
    )[0]
    assert "bisAddEnemy" in block or "addEnemy" in block
    soup = BeautifulSoup(
        app_module.app.test_client().get("/advanced").get_data(as_text=True),
        "html.parser",
    )
    assert soup.select_one("#bisAddEnemy") is not None


# ---------------------------------------------------------------------------
# #153 — Best buy panel readable
# ---------------------------------------------------------------------------


def test_best_buy_controls_live_in_the_constraints_block(soup: BeautifulSoup):
    """#153 was "the Best buy panel is unreadable".

    The whole economics bar lives in the CONSTRAINTS surface (now the banner
    under the verdict strip): gold, the sell pivot and the action. The
    criteria below are the same ones: a translucent surface, legible ink, a
    legible disabled state and a layout that does not collapse into one
    inline sentence.
    """
    constraints = soup.select_one("#railConstraints")
    assert constraints is not None
    for control_id in ("economicsGold", "economicsSell", "economicsOptimize"):
        node = soup.select_one(f"#{control_id}")
        assert node is not None, control_id
        assert node.find_parent(id="railConstraints") is not None, control_id


def test_optimizer_receipt_has_a_visible_home(soup: BeautifulSoup, source: str):
    """The optimizer's own result is a canvas band, never a toast — and it is
    actually rendered (a ``state.optimizer.summary`` written in seven places
    and read in none would leave every best-buy receipt invisible)."""
    band = soup.select_one("#buyBand")
    assert band is not None
    assert band.has_attr("hidden")
    assert band.find_parent(class_="canvas") is not None
    assert "function renderBuyBand()" in source
    assert (
        "renderBuyBand()"
        in source.split("\nfunction render() {")[1].split("\n}\n", maxsplit=1)[0]
    )
    # Every truncation / withholding note survives into the band.
    receipt = source.split("function renderBuyBand()")[1].split("\n}\n", maxsplit=1)[0]
    assert "summary.notes" in receipt
    assert "Nothing applied" in receipt


# ---------------------------------------------------------------------------
# #154 — keystone artwork bounded to slot scale
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# #155 — legible event timeline
# ---------------------------------------------------------------------------


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


@pytest.mark.needs_node
def test_sparse_timeline_names_every_source_in_full():
    html = run_timeline_renderer(
        [event(0.5, "Orb of Deception"), event(3.25, "Charm")], 10
    )
    assert html.count('class="timeline-event"') == 2
    # The old renderer cut these to "Orb" and "Cha".
    assert "Orb of Deception" in html
    assert "Charm" in html
    assert "0.5s" in html
    assert "3.3s" in html
    assert "2 ordered events, oldest first" in html


@pytest.mark.needs_node
def test_simultaneous_events_get_separate_lanes():
    """Same-timestamp events get separate lanes, never stacked markers."""
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


@pytest.mark.needs_node
def test_dense_timeline_reports_what_it_did_not_draw():
    html = run_timeline_renderer([event(i / 10, f"Hit {i}") for i in range(150)], 15)
    assert html.count('class="timeline-event"') == 60
    assert "First 60 of 150 ordered events" in html, "a silent cap reads as complete"


@pytest.mark.needs_node
def test_timeline_lanes_carry_their_index_and_position():
    html = run_timeline_renderer([event(0.0, "Q"), event(5.0, "R")], 10)
    assert 'data-event-index="0"' in html
    assert 'data-event-index="1"' in html
    assert "--at:0%" in html
    assert "--at:50%" in html


@pytest.mark.needs_node
def test_timeline_escapes_untrusted_source_text():
    html = run_timeline_renderer([event(1.0, '<img src=x onerror="alert(1)">')], 10)
    assert "<img" not in html
    assert "&lt;img" in html


@pytest.mark.needs_node
def test_timeline_states_when_no_events_returned():
    html = run_timeline_renderer([], 10)
    assert "No participant event ledger returned." in html
    assert "timeline-event" not in html


@pytest.mark.needs_node
def test_timeline_skips_events_without_a_usable_timestamp():
    html = run_timeline_renderer(
        [event(1.0, "Q"), event(None, "Withheld"), event(2.0, "W")], 10
    )
    assert html.count('class="timeline-event"') == 2
    assert "Withheld" not in html


@pytest.mark.needs_node
def test_timeline_shows_a_reason_when_an_event_dealt_no_damage():
    html = run_timeline_renderer(
        [event(1.0, "Q", damage=0, skipped_reason="out of range")], 10
    )
    assert "out of range" in html


# ---------------------------------------------------------------------------
# #156 — no clipping or overlap in the result panel
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# #157 — certainty legend stays visible
# ---------------------------------------------------------------------------


def test_certainty_legend_is_hidden_until_a_result_exists(soup: BeautifulSoup):
    legend = soup.select_one("#trustLegend")
    assert legend.has_attr("hidden")


def test_certainty_legend_sits_with_the_ledger_it_explains(soup: BeautifulSoup):
    """The legend belongs to the ledger header (gap ledger), so it appears
    exactly when the receipts it decodes do."""
    legend = soup.select_one("#trustLegend")
    assert legend.find_parent(class_="ledger-band") is not None
    assert legend.find_parent(class_="verdict") is None
