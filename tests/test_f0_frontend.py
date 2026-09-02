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

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

import src.app as app_module
from src.calculator.champions import champion_options_meta_map
from tests.app_config import app_config

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "static" / "js" / "app.js"
CSS = ROOT / "static" / "css" / "style.css"
OPTIONS_HARNESS = (
    Path(__file__).resolve().parent / "js" / "champion_options_harness.mjs"
)
BIS_PROFILES = ROOT / "static" / "bis-profiles.json"
PATCH_SNAPSHOT = ROOT / "static" / "data.json"


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
    with app_config(TESTING=True, RATE_LIMIT_ENABLED=False):
        yield


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
        assert controls
        assert soup.select_one(f"#{controls}") is not None
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
        assert body is not None
        assert body.has_attr("hidden")


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
    assert analyst is not None
    assert analyst.get("hidden") is None
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


def test_empty_champion_state_hides_dependent_controls_and_stats():
    soup = _soup()
    card = soup.select_one(".champion-card")
    identity = soup.select_one(".champion-identity")
    controls = soup.select_one("#identityControls")
    stats = soup.select_one("#statsGrid")
    assert card is not None
    assert "is-empty" in card.get("class", [])
    assert identity is not None
    assert "is-empty" in identity.get("class", [])
    assert controls is not None
    assert controls.has_attr("hidden")
    assert controls.get("aria-hidden") == "true"
    assert stats is not None
    assert stats.has_attr("hidden")
    assert stats.get("aria-hidden") == "true"
    source = _source()
    assert "identityControls" in source
    assert "statsGrid.hidden = !champion" in source


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
    assert band is not None
    assert band.name == "details"
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
    assert banners is not None
    assert verdict is not None
    order = list(soup.select(".canvas > *"))
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
    assert 'data-ability-variant="${slot}"' in source
    # A Variant row renders only when the slot has a bound module option.
    assert (
        'const bound = ability.variants?.length > 1 && abilityOptionBinding(slot, "ability_variants");'
        in source
    )
    assert (
        'abilityOptionBinding(ability.slot, "ability_variants") === option.key'
        in source
    )
    assert "input.variant = Number(abilityVariantButton.dataset.value)" in source
    assert "legacyVariantKeys" in source
    # Which key a global form toggle binds is decided in one place; the rule
    # itself is pinned by
    # ``test_global_form_binding_checks_set_membership_not_property_lookup``.
    assert "globalFormToggles" in source


def _authored_abilities(champion):
    """The champion's hand-authored kit in the served patch snapshot."""
    snapshot = json.loads(PATCH_SNAPSHOT.read_text(encoding="utf-8"))
    entry = next(
        (row for row in snapshot["champions"] if row["name"] == champion), None
    )
    return (entry or {}).get("abilities", [])


def _payload_probe(champion, variants, tmp_path):
    """Run app.js's real payload builder over the kit the browser renders:
    the served snapshot's abilities merged with the wiki forms by app.js's own
    ``mergeBisProfiles``. Returns ``options``, ``bindings``, ``kit`` and
    ``selected``."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    profiles = json.loads(BIS_PROFILES.read_text(encoding="utf-8"))
    fixture = tmp_path / "fixture.json"
    fixture.write_text(
        json.dumps(
            {
                "champion": champion,
                "options": champion_options_meta_map()[champion]["options"],
                "abilities": _authored_abilities(champion),
                "abilityForms": profiles["champions"][champion]["abilities"],
                "variants": variants,
            }
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [node, str(OPTIONS_HARNESS), str(APP_JS), str(fixture)],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def _champion_options_payload(champion, variants, tmp_path):
    """The ``champion_options`` app.js would POST."""
    return _payload_probe(champion, variants, tmp_path)["options"]


def _kit(champion, tmp_path):
    """Each slot's rendered variants as ``(name, source form)`` pairs."""
    kit = _payload_probe(champion, {}, tmp_path)["kit"]
    return {
        slot: [(variant["name"], variant["form"]) for variant in variants]
        for slot, variants in kit.items()
    }


def test_variant_flattening_stamps_every_variant_with_its_source_form(tmp_path):
    """``VARIANT_BOOLEAN_OPTIONS`` counts two different things: a ``form`` axis
    and a ``variant`` (packet) axis. Only the stamp tells them apart — Gnar's Q
    puts two Mini packets and one Mega packet on one flat index."""
    gnar = _kit("Gnar", tmp_path)
    assert gnar["Q"] == [
        ("Physical Damage", 0),  # Boomerang Throw, Mini
        ("Reduced Damage", 0),  # ... its reduced packet, still Mini
        ("Physical Damage", 1),  # Boulder Toss, Mega
    ]
    assert gnar["W"] == [("Bonus Magic Damage", 0), ("Physical Damage", 1)]
    jayce = _kit("Jayce", tmp_path)
    assert jayce["Q"] == [
        ("Physical Damage", 0),  # To the Skies!, hammer
        ("Physical Damage", 1),  # Shock Blast, cannon
        ("Increased Damage", 1),  # ... accelerated, cannon
    ]
    # A hand-authored kit declares no forms, so every variant is form 0 and
    # its boolean is a packet toggle.
    assert _kit("Ziggs", tmp_path)["R"] == [("Epicenter", 0), ("Outer blast", 0)]


@pytest.mark.parametrize(
    ("champion", "variants", "key", "expected"),
    [
        ("Ziggs", {"R": 0}, "r_sweet_spot", True),
        ("Ziggs", {"R": 1}, "r_sweet_spot", False),
        ("Jayce", {"Q": 2}, "accelerated_q", True),
        ("Jayce", {"Q": 1}, "accelerated_q", False),
        ("Jayce", {"W": 0}, "hammer_stance", True),
        ("Jayce", {"W": 2}, "hammer_stance", False),
        ("Gnar", {"W": 1}, "mega", True),
        ("Gnar", {"W": 0}, "mega", False),
    ],
)
def test_variant_buttons_send_booleans_not_variant_indices(
    champion, variants, key, expected, tmp_path
):
    """Variant-driven options the backend types as booleans must reach it as
    booleans: the raw index answered ``champion_options.<key> must be true or
    false`` (Gnar's ``mega``, then Ziggs' ``r_sweet_spot``, then Jayce's
    ``accelerated_q``) and left the whole champion uncalculable."""
    options = _champion_options_payload(champion, variants, tmp_path)
    assert options[key] is expected


@pytest.mark.parametrize(
    ("clicked", "mega", "mirrored"),
    [
        (0, False, 0),  # Boomerang Throw — Mini
        (1, False, 0),  # its reduced packet — still Mini
        (2, True, 1),  # Boulder Toss — the Mega Q
    ],
)
def test_gnar_q_variants_read_their_form_not_the_flat_index(
    clicked, mega, mirrored, tmp_path
):
    """Gnar's Q flattens three variants onto one index while W/E carry two, so
    `mega` cannot be a flat index. Before the form stamp, clicking Boomerang
    Throw's *reduced* packet sent ``mega: true`` and clicking Boulder Toss —
    the real Mega Q — sent ``mega: false``, while W/E rendered Mega for both.
    """
    probe = _payload_probe("Gnar", {"Q": clicked}, tmp_path)
    assert probe["options"]["mega"] is mega
    # The mirror follows the form, so W/E can never disagree with the payload.
    assert probe["selected"]["W"] == mirrored
    assert probe["selected"]["E"] == mirrored
    assert probe["kit"]["W"][mirrored]["form"] == probe["kit"]["Q"][clicked]["form"]


def test_no_jayce_variant_click_can_send_hammer_stance_with_accelerated_q(tmp_path):
    """Accelerated Shock Blast is a *cannon* packet, so no fight can be in
    hammer stance and fire it. Q binds ``accelerated_q`` and therefore sat
    outside the form mirror: clicking hammer on P/W/E left Q on its cannon
    packet and the payload carried both. Every click on every form-axis slot,
    not a sample of them — the whole point is that no reachable state exists.
    """
    kit = _payload_probe("Jayce", {}, tmp_path)["kit"]
    seen = []
    for slot in ("P", "Q", "W", "E"):
        for index in range(len(kit[slot])):
            options = _champion_options_payload("Jayce", {slot: index}, tmp_path)
            assert not (
                options["hammer_stance"] and options["accelerated_q"]
            ), f"{slot}={index} sent {options}"
            seen.append(options["hammer_stance"])
    # Non-vacuous: the sweep really reaches both stances.
    assert set(seen) == {True, False}


@pytest.mark.parametrize(
    ("clicked", "index", "hammer_stance", "accelerated_q", "mirrored_q"),
    [
        ("W", 0, True, False, 0),  # Lightning Field — hammer, so Q is hammer's
        ("W", 2, False, False, 1),  # Hyper Charge — cannon, plain Shock Blast
        ("Q", 0, True, False, 0),  # To the Skies! — a hammer Q means hammer
        ("Q", 2, False, True, 2),  # accelerated Shock Blast — cannon
    ],
)
def test_jayce_q_rides_the_form_axis_its_option_does_not_name(
    clicked, index, hammer_stance, accelerated_q, mirrored_q, tmp_path
):
    """Membership of the form mirror is the variant's form stamp, not the
    option the slot's control writes. Before the fix, clicking To the Skies!
    (Jayce's hammer Q) sent ``hammer_stance: false``, and clicking hammer on
    W left Q on ``accelerated_q: true``."""
    probe = _payload_probe("Jayce", {clicked: index}, tmp_path)
    assert probe["options"]["hammer_stance"] is hammer_stance
    assert probe["options"]["accelerated_q"] is accelerated_q
    assert probe["selected"]["Q"] == mirrored_q
    # Every mirrored slot lands in one form; R renders no Variant control and
    # the wiki stamps its two forms inverted, so it stays out.
    forms = {
        slot: probe["kit"][slot][probe["selected"][slot]]["form"]
        for slot in ("P", "Q", "W", "E")
    }
    assert len(set(forms.values())) == 1, forms


@pytest.mark.parametrize("variants", [{"R": 0}, {"R": 1}])
def test_ziggs_variant_payload_is_accepted_by_the_calculate_route(variants, tmp_path):
    """The bug was only visible at the boundary: both R variants must POST."""
    options = _champion_options_payload("Ziggs", variants, tmp_path)
    response = app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Ziggs",
            "level": 18,
            "items": [],
            "champion_options": options,
            "target_health": 2000,
            "target_armor": 50,
            "target_mr": 50,
        },
    )
    assert response.status_code == 200, response.get_json()


def test_global_form_binding_checks_set_membership_not_property_lookup():
    """``"hammer_stance" in declared`` on a Set checks properties, never
    membership — it silently returned "mega" for Jayce, whose module declares
    no such option, leaving his variant buttons wired to a dead key."""
    source = _source()
    assert '"hammer_stance" in declared' not in source
    assert "globalFormToggles().find((key) => declared.has(key))" in source


@pytest.mark.parametrize(
    ("champion", "expected"),
    [
        ("Ziggs", {"P": None, "Q": None, "W": None, "E": None, "R": "r_sweet_spot"}),
        (
            "Jayce",
            {
                "P": "hammer_stance",
                "Q": "accelerated_q",
                "W": "hammer_stance",
                "E": "hammer_stance",
                "R": None,
            },
        ),
    ],
)
def test_slot_owned_booleans_never_answer_the_global_form_lookup(
    champion, expected, tmp_path
):
    """A boolean a single slot claims — by explicit binding (Ziggs' R) or by
    name (Jayce's ``accelerated_q``) — must not be offered to that champion's
    other slots just because it joined the index map."""
    assert _payload_probe(champion, {}, tmp_path)["bindings"] == expected


def test_the_variant_index_to_boolean_rule_has_one_home():
    """The dedicated ``r_sweet_spot`` branch is gone; the map is the rule."""
    source = _source()
    assert 'options[option.key] = abilityInput("R").variant === 0;' not in source
    assert (
        "options[option.key] = abilityInput(variantAbility.slot).variant" not in source
    )


def test_global_form_variant_click_syncs_every_bound_slot():
    """Q/W/E all bind the same global form toggle; clicking Boulder Toss must
    not leave W/E rendering the Mini kit (and the payload is read from the
    first bound slot, so unsynced slots would silently disagree with it)."""
    source = _source()
    assert "syncGlobalFormVariants" in source


def test_global_form_variants_default_to_the_module_option_default():
    """A fresh champion pick must not flip a form toggle: variant index 0 is
    Jayce's hammer kit, but his module defaults hammer_stance to false
    (cannon).  Reset seeds each bound slot's variant from the option default,
    and the payload falls back to the option value when no variant input
    exists (share-restore clears abilityInputs)."""
    source = _source()
    assert "defaultFormVariantIndex" in source
    # One home for the starting index: a boolean toggle through
    # VARIANT_BOOLEAN_OPTIONS, an index-valued option clamped to the list.
    assert "variant: defaultFormVariantIndex(ability)" in source
    # Payload never reads the synthetic variant-0 fallback for form toggles.
    assert (
        "options[option.key] = abilityInput(variantAbility.slot).variant" not in source
    )


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
        ("durationRange", "Fight length"),
        ("uptimeRange", "Auto attack uptime percent"),
    ):
        node = soup.select_one(f"#{slider_id}")
        assert node is not None, slider_id
        assert node.get("aria-label") == label, slider_id


def test_favicon_link_present():
    soup = _soup()
    link = soup.select_one('link[rel="icon"]')
    assert link is not None
    assert link.get("href")


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
    assert champion is not None
    assert champion.name == "h3"


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
        check=False,
    )
    assert result.returncode == 0, result.stderr
