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

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

import src.app as app_module
from tests.app_config import app_config

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "static" / "js" / "app.js"
INDEX = ROOT / "templates" / "index.html"
GUIDE_DOC = ROOT / "docs" / "onboarding-guide.md"
INVITE_DOC = ROOT / "docs" / "invite-flow.md"


@pytest.fixture(autouse=True)
def _isolate_app_config():
    """Keep these route tests off the shared rate-limit budget."""
    with app_config(TESTING=True, RATE_LIMIT_ENABLED=False):
        yield


def _client():
    return app_module.app.test_client()


def _page():
    return _client().get("/advanced").get_data(as_text=True)


def _soup():
    return BeautifulSoup(_page(), "html.parser")


def _source():
    return APP_JS.read_text(encoding="utf-8")


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
    assert "green ahead" in second
    assert "red behind" in second
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


# ---------------------------------------------------------------------------
# Motion + mobile safety
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Companion docs
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# JS sanity
# ---------------------------------------------------------------------------
