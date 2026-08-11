"""P1a beta-onboarding contract tests.

Pins the first-run onboarding overlay and its two companion docs without a
browser, following the F0/P5 static-contract pattern:

* the overlay markup renders in the served page: one dismissible 3-step tour
  (champion setup → build setup → result proof), hidden by
  default, ``role=dialog`` + ``aria-modal``, Skip/Back/Next/Close wired
* app.js drives it purely additively: reads the ``scryglass_onboarded``
  localStorage flag, persists it on every dismiss path (Skip / × / Escape /
  finishing), never restructures existing code
* mobile + motion safety: the overlay is fixed-viewport, scrollable, sized
  down under a 640px media query with >= 40px touch targets, and all
  animation is disabled under ``prefers-reduced-motion``
* ``docs/onboarding-guide.md`` and ``docs/invite-flow.md`` exist with the
  required user-facing sections
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
INDEX = ROOT / "templates" / "index.html"
GUIDE_DOC = ROOT / "docs" / "onboarding-guide.md"
INVITE_DOC = ROOT / "docs" / "invite-flow.md"


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


def _client():
    return app_module.app.test_client()


def _page():
    return _client().get("/").get_data(as_text=True)


def _soup():
    return BeautifulSoup(_page(), "html.parser")


def _source():
    return APP_JS.read_text(encoding="utf-8")


def _inline_css():
    soup = _soup()
    style = soup.find("style")
    assert style is not None
    return style.get_text()


# ---------------------------------------------------------------------------
# First-run overlay renders on a fresh session
# ---------------------------------------------------------------------------


def test_overlay_markup_renders_in_the_served_page():
    soup = _soup()
    overlay = soup.select_one("#onboardingOverlay")
    assert overlay is not None
    # Starts hidden (fresh session shows it only after app.js opens it).
    assert overlay.has_attr("hidden")
    assert overlay.get("role") == "dialog"
    assert overlay.get("aria-modal") == "true"
    assert overlay.get("aria-labelledby") == "onboardingTitle"


def test_overlay_has_exactly_three_steps_with_required_copy():
    """The tour describes the shipped IA.

    Redesign note: the previous copy walked a Quick mode that was removed in
    2026-08, so the tour taught a screen nobody could reach. It now walks the
    three regions the user actually meets — the setup rail, the duel, and the
    receipts — and still ends on the certainty chips.
    """
    soup = _soup()
    steps = soup.select(".onboarding-step")
    assert len(steps) == 3
    headings = [step.find("h3").get_text(strip=True) for step in steps]
    assert headings == [
        "Set the scenario in the rail",
        "Build and read the duel",
        "Open the receipts",
    ]
    # Step 1 names the two numbered steps, the constraints block, and where
    # builds actually live now that they are not a rail step.
    first = steps[0].get_text()
    for token in ("Champion", "Roster", "Builds", "Constraints".lower()):
        assert token.lower() in first.lower(), token
    # Step 2 explains how to read the delta spine without relying on colour.
    second = steps[1].get_text().lower()
    assert "delta" in second
    assert "green ahead" in second and "red behind" in second
    # Step 3 names the ledger and the certainty chips.
    assert "event ledger" in steps[2].get_text().lower()
    assert "EXACT" in steps[2].get_text()
    assert "ESTIMATE" in steps[2].get_text()
    assert "BOUNDARY" in steps[2].get_text()
    # Progress dots match the step count.
    dots = soup.select(".onboarding-dots span")
    assert len(dots) == 3


def test_overlay_copy_does_not_reference_the_removed_quick_mode():
    page = _page()
    overlay = BeautifulSoup(page, "html.parser").select_one("#onboardingOverlay")
    assert overlay is not None
    text = overlay.get_text(" ", strip=True).lower()
    for stale in ("quick mode", "best next item", "in analyst"):
        assert stale not in text, stale


def test_overlay_has_skip_back_next_and_close_controls():
    soup = _soup()
    skip = soup.select_one(".onboarding-skip")
    assert skip is not None
    assert "Skip tour" in skip.get_text()
    # The skip control is always reachable — never hidden by the template.
    assert skip.has_attr("hidden") is False
    assert soup.select_one(".onboarding-next") is not None
    assert soup.select_one(".onboarding-back") is not None
    assert soup.select_one(".onboarding-close") is not None
    assert (
        soup.select_one(".onboarding-close").get("aria-label") == "Close welcome tour"
    )


def test_overlay_ids_are_unique_in_the_template():
    ids = [node.get("id") for node in _soup().select("[id]") if node.get("id")]
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# Dismissal + persisted flag (localStorage "scryglass_onboarded")
# ---------------------------------------------------------------------------


def test_overlay_js_reads_the_fresh_session_flag():
    source = _source()
    assert "initOnboardingOverlay" in source
    assert 'ONBOARDING_KEY = "scryglass_onboarded"' in source
    assert 'localStorage.getItem(ONBOARDING_KEY) === "1"' in source
    # Fresh session (flag absent) must not return early.
    assert "if (seen) return;" in source


def test_overlay_dismissal_persists_the_flag():
    source = _source()
    assert 'localStorage.setItem(ONBOARDING_KEY, "1")' in source
    # Every dismiss path funnels through finish() -> persistDismissal().
    assert 'skipButton.addEventListener("click", finish)' in source
    assert 'closeButton.addEventListener("click", finish)' in source
    assert 'event.key === "Escape"' in source
    assert "persistDismissal()" in source
    assert "finish()" in source


def test_overlay_skip_never_blocks_and_returns_to_the_page():
    source = _source()
    # Skip is a plain click handler, not a forced flow: no confirm(), no
    # modal trap, no reload.
    assert "window.confirm" not in source.split("initOnboardingOverlay")[-1]
    assert "window.location.reload" not in source.split("initOnboardingOverlay")[-1]
    assert "overlay.hidden = true" in source
    assert 'overlay.classList.remove("is-open")' in source


def test_overlay_js_is_additive():
    source = _source()
    # The onboarding block is a self-contained IIFE appended after the
    # existing bootstrap; it must not touch the render path.
    onboarding_block = source.split("// --- First-run onboarding overlay")[-1]
    assert "function initOnboardingOverlay()" in onboarding_block
    assert "render(" not in onboarding_block
    # The existing bootstrap is untouched.
    assert "initShareControls();" in source


def test_overlay_js_handles_unavailable_storage_quietly():
    source = _source()
    assert "storage blocked — never show a tour we cannot remember" in source
    assert "localStorage.getItem(ONBOARDING_KEY)" in source


# ---------------------------------------------------------------------------
# Motion + mobile safety
# ---------------------------------------------------------------------------


def test_overlay_respects_prefers_reduced_motion():
    css = _inline_css()
    assert re.search(
        r"@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{[^}]*animation:\s*none\s*!important",
        css,
    )


def test_overlay_works_on_mobile_viewports():
    css = _inline_css()
    # Fixed full-viewport overlay that scrolls on small screens.
    assert ".onboarding-overlay {" in css
    assert "position: fixed;" in css
    assert "overflow-y: auto;" in css
    # A dedicated small-viewport media query sizes the card down. Extract
    # the whole block (nested braces) before asserting on its contents.
    mobile_match = re.search(r"@media\s*\(max-width:\s*640px\)\s*\{", css)
    assert mobile_match is not None
    depth = 0
    end = mobile_match.end()
    for i in range(mobile_match.end(), len(css)):
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            if depth == 0:
                end = i
                break
            depth -= 1
    mobile_block = css[mobile_match.end() : end]
    assert ".onboarding-card" in mobile_block
    assert "calc(100dvh - 24px)" in mobile_block
    # F0 design principle 6: touch targets >= 40px on mobile.
    assert "min-height: 44px" in mobile_block
    # The overlay is centered on desktop but top-aligned on mobile so the
    # card is never clipped.
    assert "align-items: start;" in mobile_block


def test_overlay_hidden_attribute_is_not_defeated_by_inline_css():
    css = _inline_css()
    assert re.search(
        r"\.onboarding-overlay\[hidden\]\s*\{[^}]*display:\s*none\s*!important",
        css,
    )
    assert re.search(
        r"\.onboarding-step\[hidden\]\s*\{[^}]*display:\s*none\s*!important",
        css,
    )
    # Opening state is explicit, so .is-open never fights [hidden].
    assert ".onboarding-overlay.is-open" in css


# ---------------------------------------------------------------------------
# Companion docs
# ---------------------------------------------------------------------------


def test_onboarding_guide_exists_with_required_sections():
    assert GUIDE_DOC.is_file()
    text = GUIDE_DOC.read_text(encoding="utf-8")
    for required in (
        "## 1. The fastest path to an answer",
        "## 2. Reading the ranked candidates",
        "## 3. Certainty chips legend",
        "## 4. The STALE badge",
        "## 5. Share links",
        "## 6. The feedback widget",
        "## 7. What to do on patch day",
    ):
        assert required in text, required
    for phrase in (
        "Find best item for a slot",
        "+ Add",
        "EXACT",
        "ESTIMATE",
        "BOUNDARY",
        "STALE",
        "did this match",
        "patch",
    ):
        assert phrase.lower() in text.lower(), phrase


def test_invite_flow_doc_exists_with_required_sections():
    assert INVITE_DOC.is_file()
    text = INVITE_DOC.read_text(encoding="utf-8")
    for required in (
        "## 1. How an invite is issued",
        "## 2. What the invitee sees",
        "## 3. Invite rotation",
        "## 4. Failure modes and fallbacks",
    ):
        assert required in text, required
    for phrase in (
        "SCRYGLASS_INVITE_CODES",
        "SCRYGLASS_AUTH_USERS",
        "beta landing",
        "Invite code",
        "rotation",
        "401",
    ):
        assert phrase in text, phrase
    assert "first-run overlay" in text.lower()


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
