"""P5 casual-UX + P4 trust-label frontend contract tests.

These tests pin the *contracts the browser UI consumes* without a browser:

* the Quick view surface (tabs, guided steps, run button, share)
* the quick-mode "Best next item" flow: /api/calculate baseline + /api/bis
  next-slot candidates with the score/components the UI turns into deltas
* build sharing: POST /api/builds -> POST /api/share -> GET /api/share/<token>
  round trip with view counting, including the ``ability_ranks`` sanitize the
  UI applies for level-derived transform kits
* trust labels: /api/certainty and /api/not-modeled consumption with the
  documented response shapes; a failed fetch renders an unavailable state,
  never placeholder chips
* mobile/touch requirements: portrait media queries that stack the top-3
  cards and single-column picker grids
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

import src.app as app_module

from src import db

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "static" / "js" / "app.js"
CSS = ROOT / "static" / "css" / "style.css"

LEVEL_DERIVED_KITS = {"Elise", "Jayce", "Karma", "Nidalee", "Udyr"}
QUICK_LEVEL = 18
QUICK_MAX_ITEMS = 5


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
    app_module.app.config["RATE_LIMIT_ENABLED"] = previous_rate


@pytest.fixture
def sqlite_database(tmp_path, monkeypatch):
    """Point the app at an isolated SQLite file and reset the engine."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'p5.sqlite3'}")
    db.reset()
    yield db
    db.reset()


def _client():
    return app_module.app.test_client()


def _champion_names() -> set[str]:
    response = _client().get("/api/champions")
    assert response.status_code == 200
    return {entry["name"] for entry in response.get_json()}


def _item_names() -> set[str]:
    response = _client().get("/api/items")
    assert response.status_code == 200
    return {entry["name"] for entry in response.get_json()}


def _quick_payload(champion="Ahri", items=None, enemies=None, **overrides):
    """Mirror quickCalculatePayload() in static/js/app.js exactly.

    An explicit enemy list overrides, otherwise the practice target (Jhin, no
    items) is used — mirroring quickEnemyLoadout()."""
    if enemies is None:
        enemies = [{"champion": "Jhin", "level": 18, "role": "bottom", "items": []}]
    payload = {
        "champion": champion,
        "level": QUICK_LEVEL,
        "role": "mid",
        "items": list(items or [])[:QUICK_MAX_ITEMS],
        "item_options": {},
        "ability_ranks": None,
        "champion_options": {},
        "enemies": enemies,
        "allies": [],
        "role_quest_complete": False,
        "include_actives": True,
        "include_crossover": False,
        "rotations": 1,
        "fight_mode": "one_rotation",
        "fight_duration": 10,
        "auto_attack_uptime_mode": "calculated",
        "include_auto_attacks": True,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Page contract
# ---------------------------------------------------------------------------


def test_index_renders_the_analyst_view_surface():
    """Product decision 2026-08-06: the analyst view IS the app. Quick mode is
    hidden, the view-switch tab bar is gone, and the analyst builder is the
    visible landing."""
    page = _client().get("/").get_data(as_text=True)
    soup = BeautifulSoup(page, "html.parser")

    assert soup.select(".view-tab") == []  # no Quick/Analyst tabs
    assert soup.select_one("#quickView") is None  # quick mode removed entirely
    analyst = soup.select_one("#analystView")
    assert analyst is not None and analyst.get("hidden") is None
    for required_id in (
        "championPicker",
        "roleSelect",
        "levelInput",
        "duelA",
    ):
        assert soup.select_one(f"#{required_id}") is not None, required_id


def test_analyst_view_is_touch_first_and_has_no_hover_dependency():
    """The analyst builder's controls are real <button>/<input> elements, never
    hover-revealed (mobile-safe)."""
    page = _client().get("/").get_data(as_text=True)
    soup = BeautifulSoup(page, "html.parser")
    picker = soup.select_one("#championPicker")
    assert picker is not None and picker.get("type") == "button"
    assert soup.select_one("#roleSelect") is not None
    assert soup.select_one("#levelInput") is not None


def test_mobile_css_stacks_the_duel_vertically():
    """Quick mode's card grid is gone; the same criterion now applies to the
    duel canvas — on a phone the three-column duel becomes one column, the
    picker grid becomes one column, and nothing is hover-only."""
    css = CSS.read_text(encoding="utf-8")
    narrow = css.split("@media (max-width: 860px)")[1].split("@media")[0]
    assert ".duel" in narrow and "grid-template-columns: minmax(0, 1fr)" in narrow
    assert ".verdict" in narrow
    assert ".app-grid" in narrow

    phone = css.split("@media (max-width: 520px)")[1]
    assert ".picker-grid" in phone and "minmax(0, 1fr)" in phone
    assert "min-height: 40px" in phone, "touch targets must stay reachable"

    # Nothing the reader needs may depend on hover. Read-only rows carry no
    # hover styles at all; .duel-row is a real <button> since the duel became
    # editable in place, so its hover is affordance feedback — but it may only
    # restyle, never reveal (no display/visibility/content changes).
    for selector in (".spine-row:hover", ".health-row:hover"):
        assert selector not in css
    for match in re.finditer(r"\.duel-row[^{]*:hover[^{]*\{([^}]*)\}", css):
        for revealing in ("display", "visibility", "content"):
            assert revealing not in match.group(1)


# ---------------------------------------------------------------------------
# Quick-mode "Best next item" flow (the exact requests the UI issues)
# ---------------------------------------------------------------------------


def test_quick_flow_baseline_and_next_slot_deltas_are_computable():
    """The UI calls /api/calculate for the baseline, then /api/bis for the
    next slot and renders candidate.score - baseline.tdd deltas.  This pins
    that both calls succeed with the quick payload and the deltas are real."""
    client = _client()
    baseline = client.post("/api/calculate", json=_quick_payload(items=[]))
    assert baseline.status_code == 200
    base = baseline.get_json()
    main = next(
        (
            row
            for row in base["combat"]["participants"]
            if row["participant_id"] == "main"
        ),
        None,
    )
    main_breakdown = next(
        (row for row in base["combat"]["breakdown"] if row["participant_id"] == "main"),
        None,
    )
    base_tdd = (
        main_breakdown["total_damage"] if main_breakdown else base["total_damage"]
    )
    base_ehp = main["survival"]["effective_health"] if main else 0
    assert base_tdd > 0 and base_ehp > 0

    bis = client.post(
        "/api/bis",
        json=_quick_payload(
            items=[],
            slot_index=0,
            slot_kind="item",
            subject_team="main",
            objective="overall",
        ),
    )
    assert bis.status_code == 200
    data = bis.get_json()
    certified = data.get("candidates") or []
    assert certified, "single-enemy quick BIS must be event-order certified"
    top3 = certified[:3]
    assert len(top3) == 3
    for candidate in top3:
        assert candidate["name"]
        assert candidate["score"] > 0
        assert candidate["survival"]["effective_health"] > 0
        assert float(candidate["score"]) - base_tdd != 0.0
        assert candidate["timeline_coverage"].get("complete") is True


def test_quick_flow_boots_slot_when_five_items_owned():
    """With five legendaries the UI recommends the boots slot (slot_kind
    boots, slot_index 0), mirroring the analyst six-slot contract."""
    items = [
        "Liandry's Torment",
        "Rabadon's Deathcap",
        "Zhonya's Hourglass",
        "Void Staff",
        "Morellonomicon",
    ]
    payload = _quick_payload(
        items=items,
        slot_index=0,
        slot_kind="boots",
        subject_team="main",
        objective="overall",
    )
    response = _client().post("/api/bis", json=payload)
    assert response.status_code == 200, response.get_json()
    data = response.get_json()
    candidates = data.get("candidates") or data.get("partial_candidates") or []
    assert candidates
    assert all(
        candidate["timeline_coverage"].get("complete")
        for candidate in data.get("candidates") or []
    )


def test_optimize_accepts_the_quick_payload_shape():
    """The task permits /api/optimize as the quick-mode engine; pin that the
    quick payload (champion/level/role/enemies/fight params + locked_items)
    is a legal optimize request returning ranked_builds the UI could render."""
    payload = _quick_payload(items=[])
    payload.update(locked_items=[], max_legendary_slots=5)
    response = _client().post("/api/optimize", json=payload)
    assert response.status_code == 200, response.get_json()
    data = response.get_json()
    assert data.get("items") and data.get("ranked_builds")
    for ranked in data["ranked_builds"][:2]:
        assert ranked["items"] and ranked["total_damage"] > 0
        assert ranked["timeline_coverage"] is not None


# ---------------------------------------------------------------------------
# Build sharing
# ---------------------------------------------------------------------------


def _save_and_share(client, payload, slug="quick-build"):
    # Mirror mintShareUrl(): /api/builds stores ability_ranks in a JSON
    # column and rejects null, so the UI saves {} for level-derived kits.
    saved_payload = dict(payload)
    if saved_payload.get("ability_ranks") is None:
        saved_payload["ability_ranks"] = {}
    response = client.post("/api/builds", json=saved_payload)
    assert response.status_code == 201, response.get_json()
    build_id = response.get_json()["build_id"]
    share = client.post("/api/share", json={"build_id": build_id, "slug": slug})
    assert share.status_code == 201, share.get_json()
    return build_id, share.get_json()


def test_share_round_trip_reads_back_and_counts_views(sqlite_database):
    client = _client()
    _, share = _save_and_share(client, _quick_payload(items=["Liandry's Torment"]))
    token = share["token"]
    assert share["url"] == f"/api/share/{token}"

    first = client.get(f"/api/share/{token}")
    assert first.status_code == 200
    payload = first.get_json()
    assert payload["champion"] == "Ahri"
    assert payload["items"] == ["Liandry's Torment"]
    assert payload["request"]["champion"] == "Ahri"
    assert payload["request"]["rotations"] == 1
    assert payload["request"]["fight_mode"] == "one_rotation"
    assert payload["share"]["views"] == 1

    second = client.get(f"/api/share/{token}")
    assert second.get_json()["share"]["views"] == 2


def test_shared_payload_recalculates_after_client_sanitize(sqlite_database):
    """The UI saves ability_ranks null as {} (the save endpoint rejects null)
    and restores null for level-derived transform kits before recalculating."""
    for champion in ("Ahri", "Jayce"):
        client = _client()
        _, share = _save_and_share(
            client, _quick_payload(champion=champion), slug=f"{champion.lower()}-build"
        )
        request = client.get(f"/api/share/{share['token']}").get_json()["request"]
        assert request["ability_ranks"] == {}
        if champion in LEVEL_DERIVED_KITS:
            request["ability_ranks"] = None
        recalc = client.post("/api/calculate", json=request)
        assert recalc.status_code == 200, (champion, recalc.get_json())


def test_analyst_share_payload_mirrors_calculate(sqlite_database):
    """The analyst 'Share this build' button mirrors the /api/calculate
    payload (engineFightPayload('A')): boots and fight settings ride the
    same keys and survive the save/share round trip."""
    payload = _quick_payload(items=["Liandry's Torment", "Shadowflame"])
    payload.update(
        boots="Sorcerer's Shoes",
        include_boots=True,
        keystone="",
        item_options={},
        ability_ranks={"Q": 5, "W": 3, "E": 3, "R": 2},
    )
    client = _client()
    _, share = _save_and_share(client, payload, slug="analyst-build")
    saved = client.get(f"/api/share/{share['token']}").get_json()
    assert saved["request"]["boots"] == "Sorcerer's Shoes"
    assert saved["request"]["ability_ranks"] == {"Q": 5, "W": 3, "E": 3, "R": 2}
    recalc = client.post("/api/calculate", json=saved["request"])
    assert recalc.status_code == 200, recalc.get_json()


def test_share_index_loads_with_share_query_param():
    """On load with ?share=<token> the server serves the calculator page and
    the frontend contract renders it read-only via /api/share/<token>."""
    page = _client().get("/?share=abc123").get_data(as_text=True)
    assert "Scryglass — Item calculator" in page
    assert 'id="shareBanner"' in page
    source = APP_JS.read_text(encoding="utf-8")
    assert 'params.get("share")' in source
    assert "fetch(`/api/share/${encodeURIComponent(token)}`)" in source


# ---------------------------------------------------------------------------
# Trust labels (P4)
# ---------------------------------------------------------------------------


def test_certainty_and_not_modeled_endpoint_contracts():
    """The frontend consumes the deployed routes and renders a non-2xx answer
    as an unavailable state: no chips, the backend's error in the legend note.
    No contract-shaped mock may stand in for sourced data."""
    source = APP_JS.read_text(encoding="utf-8")
    assert "fetch(`${path}?champion=${encodeURIComponent(champion)}`)" in source
    assert 'fetchTrustContract("/api/certainty"' in source
    assert 'fetchTrustContract("/api/not-modeled"' in source
    assert "throw new Error(payload?.error || `HTTP ${response.status}`)" in source
    assert "return { error: `${path} unavailable (${error.message})` }" in source
    assert "`Certainty unavailable — ${failure}`" in source
    for gone in ("certaintyMock", "notModeledMock", "Placeholder", "mockBuilder"):
        assert gone not in source, gone

    # The UI labels every allowed certainty value.
    assert 'exact: { label: "EXACT"' in source
    assert 'estimate: { label: "ESTIMATE"' in source
    assert 'boundary: { label: "BOUNDARY"' in source


def test_breakdown_rows_carry_slot_keys_for_certainty_chips():
    source = APP_JS.read_text(encoding="utf-8")
    assert "Object.entries(result?.breakdown || {})" in source
    assert "slot: slotKey" in source
    assert "certaintyChipHtml(row.slot)" in source
    assert 'class="certainty-chip certainty-' in source


def test_trust_panels_render_not_modeled_list():
    source = APP_JS.read_text(encoding="utf-8")
    assert 'document.getElementById("notModeledList")' in source
    page = _client().get("/").get_data(as_text=True)
    assert 'id="notModeledList"' in page


def test_app_js_wires_the_share_endpoints_and_carries_no_quick_layer():
    """Quick mode's DOM left in 2026-08; its render/wiring layer is gone too.
    The share flow it grew is analyst functionality and stays wired."""
    source = APP_JS.read_text(encoding="utf-8")
    for needle in (
        'postJson("/api/builds"',
        'postJson("/api/share"',
        "window.location.origin}/?share=",
        'getElementById("shareAnalystButton")',
    ):
        assert needle in source, needle
    for gone in (
        'fetch("/static/quick-presets.json")',
        "data-quick-preset",
        'getElementById("quickRun")',
        'getElementById("quickShareButton")',
        "QUICK_STATE",
    ):
        assert gone not in source, gone


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
