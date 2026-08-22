"""#78: one authoritative backend capability contract for every frontend control.

The capability contract in ``src/calculator/capabilities.py`` is the single
source of truth for the control surface.  These are static coverage gates
that pin the contract to the actual frontend:

* every control id / data-path / data-picker / data-proto-range /
  data-capability-field / control attribute that ``static/js/app.js`` or
  ``templates/index.html`` mounts maps to a declared capability token;
* every declared supported token is actually referenced by the frontend;
* the API responses that feed controls (``/api/config``, ``/api/champions``,
  ``champion_options_meta``, ``item_input_options_meta``) expose exactly the
  capability-declared fields.

The tables below are the audit surface: the contract test maps each mounted
control to the ``(kind, field)`` descriptor that must exist in the contract,
then cross-checks the descriptor's ``frontend_token`` against the frontend
source.  Adding a control to the frontend without declaring it in
``capabilities.py`` fails these tests; declaring a token no control mounts
fails them too.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

import src.app as app_module

APP_JS = Path("static/js/app.js").read_text(encoding="utf-8")
TEMPLATE = Path("templates/index.html").read_text(encoding="utf-8")
FRONTEND = f"{APP_JS}\n{TEMPLATE}"

# ---------------------------------------------------------------------------
# Frontend -> capability mapping tables
# ---------------------------------------------------------------------------

# data-picker values and the participant fields they mount.  ``data-picker``
# is the shared mount point for the champion, item (build slots and quest
# boots), and rune-page pickers.
DATA_PICKER_VALUES = {
    "champion": [("main", "champion"), ("enemy", "champion"), ("ally", "champion")],
    "item": [("main", "items"), ("enemy", "items"), ("ally", "items")],
    "keystone": [("main", "keystone")],
    "minor-rune": [("main", "minor_runes")],
    "stat-shard": [("main", "stat_shards")],
}

# Literal data-path templates the frontend renders.  Values resolve to the
# participant field the path writes into (the roster path is generic across
# enemy/ally participants; ``${path}`` is the generic item-slot picker path).
DATA_PATH_VALUES = {
    "attacker.champion": [("main", "champion")],
    "attacker.keystone${side}": [("main", "keystone")],
    "attacker.minorRunes${side}.${index}": [("main", "minor_runes")],
    "attacker.statShards${side}.${index}": [("main", "stat_shards")],
    "${root}.${index}.champion": [("enemy", "champion"), ("ally", "champion")],
    "${path}": [("main", "items"), ("enemy", "items"), ("ally", "items")],
}

# data-proto-range values (the fight-window range controls).
DATA_PROTO_RANGE_VALUES = {
    "duration": ("scenario", "window"),
    "aaUptime": ("scenario", "auto_attack_uptime"),
}

# Bare control attributes app.js emits, mapped to the capability descriptor
# that owns them.  Several attributes mount the same family on more than one
# participant kind (e.g. every roster card mounts ``data-roster-role``).
CONTROL_ATTRIBUTES = {
    # main loadout
    "data-ability-rank": [("main", "ability_ranks")],
    "data-ability-variant": [("main", "ability_variants")],
    "data-role": [("main", "role")],
    "data-role-quest": [("main", "role_quest_complete")],
    "data-include-boots": [("main", "include_boots")],
    "data-champion-option": [("main", "champion_options")],
    "data-rune-option": [("main", "rune_options")],
    # The rune page dialog: one pick control for keystone, minor and shard
    # rows; the duel rune rows (data-picker) open it at their section.
    "data-rune-pick": [
        ("main", "keystone"),
        ("main", "minor_runes"),
        ("main", "stat_shards"),
    ],
    "data-keystone-option": [("main", "keystone")],
    "data-keystone-option-key": [("main", "keystone")],
    "data-copy": [("main", "items")],
    # roster loadouts
    "data-roster-rank": [("enemy", "ability_ranks"), ("ally", "ability_ranks")],
    "data-roster-role": [("enemy", "role"), ("ally", "role")],
    "data-roster-quest": [
        ("enemy", "role_quest_complete"),
        ("ally", "role_quest_complete"),
    ],
    "data-roster-champion-option": [
        ("enemy", "champion_options"),
        ("ally", "champion_options"),
    ],
    "data-include-roster-boots": [
        ("enemy", "include_boots"),
        ("ally", "include_boots"),
    ],
    "data-ally-effects": [("ally", "ally_effects_enabled")],
    # shared participant controls
    "data-level-path": [("main", "level"), ("enemy", "level"), ("ally", "level")],
    "data-level-delta": [("main", "level"), ("enemy", "level"), ("ally", "level")],
    "data-level-range": [("main", "level"), ("enemy", "level"), ("ally", "level")],
    "data-level-set": [("main", "level"), ("enemy", "level"), ("ally", "level")],
    "data-roster-level-all": [("enemy", "level"), ("ally", "level")],
    "data-stack-path": [
        ("main", "item_options"),
        ("enemy", "item_options"),
        ("ally", "item_options"),
    ],
    "data-item-option-path": [
        ("main", "item_options"),
        ("enemy", "item_options"),
        ("ally", "item_options"),
    ],
    "data-dummy-stat": [("enemy", "target_stats")],
    "data-reset-dummy-stats": [("enemy", "target_stats")],
    # scenario controls
    "data-fight-mode": [("scenario", "actions")],
    # feature controls
    "data-bis-path": [("controls", "best_in_slot")],
    "data-bis-objective": [("controls", "best_in_slot")],
    "data-bis-value": [("controls", "best_in_slot")],
    "data-optimize-roster": [("controls", "optimize")],
    "data-optimize-roster-all": [("controls", "optimize")],
    "data-game-state": [("controls", "game_state")],
    "data-objective": [("controls", "objective")],
    "data-remove-target": [("controls", "roster_membership")],
    "data-remove-ally": [("controls", "roster_membership")],
    "data-remove-": [("controls", "roster_membership")],
    "data-add-ally": [("controls", "roster_membership")],
    "data-add-target": [("controls", "roster_membership")],
    "data-picker-value": [("controls", "picker")],
    "data-optimize-build": [("controls", "optimize")],
    "data-toggle-compare": [("main", "items")],
}

# Attributes that carry a value identifying the control family.  Their values
# are validated by the dedicated value tables above.
VALUE_ATTRIBUTES = {
    "data-picker",
    "data-path",
    "data-proto-range",
    "data-capability-field",
}

# Attributes that ride on a mapped control as payload modifiers, or belong to
# non-calculator surfaces (CSS theming, the design-review dev overlay).
EXCLUDED_ATTRIBUTES = {
    "data-delta",
    "data-value",
    "data-option-key",
    "data-option-type",
    "data-item-option-id",
    "data-item-option-key",
    "data-rune-name",
    "data-rune-side",
    "data-rune-row",
    # The rune page section a duel row scrolls to; display only.
    "data-rune-focus",
    "data-build",
    "data-theme",
    "data-review-action",
    "data-review-field",
    "data-review-index",
    # #155: a read-only key tying an event-ledger timeline lane to its table
    # row. It carries no input and drives no payload field.
    "data-event-index",
    # The ability card's slot key, for styling and tests; it carries no input.
    "data-ability-slot",
    # Removed quick mode (2026-08-06): the data-quick-* attrs survive only in
    # dead JS retained for rollback safety; no quick control is mounted.
    "data-quick-pick",
    "data-quick-role",
    "data-quick-preset",
    "data-quick-remove",
    # Redesign disclosure controls. They open and close a setup step or a
    # constraints row in the rail; they carry no input and drive no payload
    # field, so there is nothing for the capability contract to gate.
    "data-step-toggle",
    "data-constraint-toggle",
    # Read-only hover affordances: the wiki-style item card anchor and the
    # fight-timeline build spotlight. They display receipts, never input.
    "data-item-tooltip",
    "data-chart-focus",
}

# Interactive control ids in the template (buttons, selects, inputs, dialogs),
# mapped to the capability that owns them.
CONTROL_IDS = {
    "championPicker": ("main", "champion"),
    "roleSelect": ("main", "role"),
    "levelInput": ("main", "level"),
    "levelRange": ("main", "level"),
    "rosterLevelMain": ("enemy", "level"),
    "questToggle": ("main", "role_quest_complete"),
    "bootsToggle": ("main", "include_boots"),
    "bisButton": ("controls", "best_in_slot"),
    "addEnemy": ("controls", "roster_membership"),
    "addAlly": ("controls", "roster_membership"),
    "durationRange": ("scenario", "window"),
    "uptimeRange": ("scenario", "auto_attack_uptime"),
    "uptimeModeToggle": ("scenario", "auto_attack_uptime_mode"),
    "enemyHitsToggle": ("scenario", "enemies_attack"),
    "stateTheory": ("controls", "game_state"),
    "stateLive": ("controls", "game_state"),
    "shareAnalystButton": ("controls", "share"),
    "shareOpenEditor": ("controls", "share"),
    "sharePanelClose": ("controls", "share"),
    "shareCopy": ("controls", "share"),
    "shareUrl": ("controls", "share"),
    "shareDismiss": ("controls", "share"),
    "picker": ("controls", "picker"),
    "pickerClose": ("controls", "picker"),
    "pickerSearch": ("controls", "picker"),
    "bis": ("controls", "best_in_slot"),
    "bisClose": ("controls", "best_in_slot"),
    "runePage": ("main", "keystone"),
    "runePageClose": ("main", "keystone"),
    "addPracticeEnemy": ("controls", "roster_membership"),
    # #152: the shortcut out of the blocked Best-in-slot state; it delegates
    # to #addEnemy, so it belongs to the same capability.
    "bisAddEnemy": ("controls", "roster_membership"),
    "economicsGold": ("controls", "purchase_optimize"),
    "economicsOptimize": ("controls", "purchase_optimize"),
    "economicsSell": ("controls", "purchase_optimize"),
    # Redesign: comparison toggles live on the verdict strip only — enable on
    # the empty challenger side, disable from the live duel. Both write the
    # same build state.
    "enableBuildB": ("main", "items"),
    "disableBuildB": ("main", "items"),
}


# ---------------------------------------------------------------------------
# Contract helpers
# ---------------------------------------------------------------------------


def _contract() -> dict:
    """Return the served capability contract from /api/config."""
    response = app_module.app.test_client().get("/api/config")
    assert response.status_code == 200
    return response.get_json()["capabilities"]


def _descriptor(contract: dict, kind: str, field: str) -> dict:
    """Resolve one (kind, field) descriptor in the contract."""
    if kind == "scenario":
        return contract["scenario"]["fields"][field]
    if kind == "controls":
        return contract["controls"]["fields"][field]
    return contract["participants"][kind]["fields"][field]


def _assert_declared(contract: dict, kind: str, field: str) -> None:
    """Assert a (kind, field) capability exists, is supported, and is mounted."""
    descriptor = _descriptor(contract, kind, field)
    assert descriptor["supported"] is True, (kind, field)
    assert descriptor["frontend_token"] in FRONTEND, (kind, field)


def _declared_supported_fields(contract: dict):
    """Yield (kind, field, descriptor) for every supported declaration."""
    for kind in ("main", "enemy", "ally"):
        for field, descriptor in contract["participants"][kind]["fields"].items():
            if descriptor["supported"]:
                yield kind, field, descriptor
    for field, descriptor in contract["scenario"]["fields"].items():
        if descriptor["supported"]:
            yield "scenario", field, descriptor
    for field, descriptor in contract["controls"]["fields"].items():
        if descriptor["supported"]:
            yield "controls", field, descriptor


# ---------------------------------------------------------------------------
# (a) Every frontend control maps to a declared capability token
# ---------------------------------------------------------------------------


def test_every_frontend_control_attribute_maps_to_a_declared_capability():
    contract = _contract()

    for value in sorted(set(re.findall(r'data-picker="([^"]+)"', FRONTEND))):
        assert value in DATA_PICKER_VALUES, f"undeclared data-picker value: {value}"
        for kind, field in DATA_PICKER_VALUES[value]:
            descriptor = _descriptor(contract, kind, field)
            assert descriptor["frontend_token"] == f'data-picker="{value}"', (
                kind,
                field,
            )

    for value in sorted(set(re.findall(r'data-path="([^"]+)"', FRONTEND))):
        assert value in DATA_PATH_VALUES, f"undeclared data-path value: {value}"
        for kind, field in DATA_PATH_VALUES[value]:
            _assert_declared(contract, kind, field)

    for value in sorted(set(re.findall(r'data-proto-range="([^"]+)"', FRONTEND))):
        assert (
            value in DATA_PROTO_RANGE_VALUES
        ), f"undeclared data-proto-range value: {value}"
        kind, field = DATA_PROTO_RANGE_VALUES[value]
        descriptor = _descriptor(contract, kind, field)
        assert descriptor["frontend_token"] == f'data-proto-range="{value}"'

    for attribute, targets in CONTROL_ATTRIBUTES.items():
        if attribute.endswith("-"):
            assert attribute in FRONTEND, attribute
        else:
            assert re.search(rf"\b{re.escape(attribute)}\b", FRONTEND), attribute
        for kind, field in targets:
            _assert_declared(contract, kind, field)

    emitted = set(re.findall(r"\bdata-[a-z0-9-]+", FRONTEND))
    unknown = emitted - (
        set(CONTROL_ATTRIBUTES) | VALUE_ATTRIBUTES | EXCLUDED_ATTRIBUTES
    )
    assert not unknown, f"unmapped frontend data-* attribute(s): {sorted(unknown)}"


def test_every_interactive_control_id_maps_to_a_declared_capability():
    contract = _contract()
    soup = BeautifulSoup(TEMPLATE, "html.parser")
    found = {
        tag.get("id")
        for tag in soup.find_all(["button", "select", "input", "dialog", "textarea"])
        if tag.get("id")
    }
    unknown = found - set(CONTROL_IDS)
    assert not unknown, f"unmapped control id(s): {sorted(unknown)}"
    for control_id, (kind, field) in CONTROL_IDS.items():
        assert control_id in FRONTEND, control_id
        _assert_declared(contract, kind, field)


def test_data_capability_field_bindings_name_only_declared_fields():
    contract = _contract()

    for field in sorted(
        set(re.findall(r'dataset\.capabilityField\s*=\s*"([a-z_]+)"', APP_JS))
    ):
        assert field in (
            set(contract["scenario"]["fields"])
            | {
                f
                for kind in ("main", "enemy", "ally")
                for f in contract["participants"][kind]["fields"]
            }
        ), field

    for kind, field in sorted(
        set(
            re.findall(
                r'capabilityFor\(\s*"(main|enemy|ally)"\s*,\s*"([a-z_]+)"', APP_JS
            )
        )
    ):
        assert field in contract["participants"][kind]["fields"], (kind, field)

    for kind, field in sorted(
        set(
            re.findall(
                r'capabilityAttributes\(\s*"(main|enemy|ally)"\s*,\s*"([a-z_]+)"',
                APP_JS,
            )
        )
    ):
        assert field in contract["participants"][kind]["fields"], (kind, field)

    for field in sorted(
        set(re.findall(r'scenarioCapabilityFor\(\s*"([a-z_]+)"', APP_JS))
    ):
        assert field in contract["scenario"]["fields"], field

    for field in sorted(
        set(
            re.findall(r'abilityCapabilityAttributes?\(\s*[^,]+,\s*"([a-z_]+)"', APP_JS)
        )
    ):
        assert field in contract["participants"]["main"]["fields"], field

    for field in sorted(
        set(re.findall(r'capabilityAttributes?\(\s*[^,]+,\s*"([a-z_]+)"', APP_JS))
    ):
        assert field in {
            f
            for kind in ("main", "enemy", "ally")
            for f in contract["participants"][kind]["fields"]
        } | set(contract["scenario"]["fields"]), field


# ---------------------------------------------------------------------------
# (b) Every declared capability token is referenced by the frontend
# ---------------------------------------------------------------------------


def test_every_declared_capability_token_is_referenced_by_the_frontend():
    contract = _contract()
    for kind, field, descriptor in _declared_supported_fields(contract):
        assert descriptor["frontend_token"] in FRONTEND, (kind, field)
        if descriptor["conditional"]:
            assert descriptor["availability"], (kind, field)


# ---------------------------------------------------------------------------
# (c) API responses expose exactly the capability-declared fields
# ---------------------------------------------------------------------------


def test_api_responses_expose_exactly_the_capability_declared_fields():
    client = app_module.app.test_client()
    config = client.get("/api/config").get_json()
    contract = config["capabilities"]

    # Scenario limits are served verbatim to the range controls; the engine's
    # rotation count is not a public control.
    assert config["input_limits"] == contract["scenario"]["limits"]
    assert "rotations" not in contract["scenario"]["fields"]
    assert "rotationRange" not in TEMPLATE

    # champion_options_meta feeds the champion-option controls.
    catalog = contract["catalogs"]["champion_options"]
    assert catalog["supported"] is True
    assert catalog["count"] == len(config["champion_options"]) > 0
    for meta in config["champion_options"].values():
        assert set(catalog["keys"]) <= set(meta)

    # item_input_options_meta feeds the item-option stack controls.
    catalog = contract["catalogs"]["item_options"]
    assert catalog["supported"] is True
    assert catalog["count"] == len(config["item_options"]) > 0
    for meta in config["item_options"].values():
        assert set(catalog["keys"]) <= set(meta)

    # role_quest feeds the quest toggle and the boots toggle (exact key set).
    catalog = contract["catalogs"]["role_quest"]
    assert catalog["supported"] is True
    assert set(config["role_quest"]) == set(catalog["keys"])

    # keystones feed the keystone picker (participants.main.keystone).
    assert isinstance(config["keystones"], list)
    assert config["keystones"]

    # /api/champions exposes exactly the declared slots and entry keys, which
    # feed the ability-rank and per-ability option controls.
    champions = client.get("/api/champions").get_json()
    abilities = next(c for c in champions if c["name"] == "Ahri")["abilities"]
    catalog = contract["catalogs"]["abilities"]
    assert list(abilities) == list(catalog["slots"])
    for entry in abilities.values():
        assert set(catalog["keys"]) <= set(entry)

    # fight defaults feed the scenario window/uptime controls.
    defaults = config["fight_defaults"]
    assert {
        "mode",
        "duration_seconds",
        "auto_attack_uptime",
        "auto_attack_uptime_mode",
        "one_rotation_duration_seconds",
    } <= set(defaults)
    assert defaults["auto_attack_uptime_mode"] in {"calculated", "explicit"}


# ---------------------------------------------------------------------------
# The runtime-disable path, driven headlessly through the real app.js
# ---------------------------------------------------------------------------

GATES_HARNESS = Path(__file__).resolve().parent / "js" / "capability_gates_harness.mjs"
APP_JS_PATH = Path(__file__).resolve().parent.parent / "static" / "js" / "app.js"


def _control_gates(contract: dict, tmp_path) -> dict:
    """Run app.js's control-family gating over one capability contract."""
    node = shutil.which("node")
    if node is None:  # pragma: no cover - toolchain dependent
        pytest.skip("node is not installed")
    fixture = tmp_path / "fixture.json"
    fixture.write_text(json.dumps({"capabilities": contract}), encoding="utf-8")
    result = subprocess.run(
        [node, str(GATES_HARNESS), str(APP_JS_PATH), str(fixture)],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_every_gated_control_family_is_declared_and_mounted(tmp_path):
    """Each family the browser can disable must be a published control family
    whose controls are in the served document when the pass runs."""
    contract = _contract()
    soup = BeautifulSoup(
        app_module.app.test_client().get("/").get_data(as_text=True), "html.parser"
    )
    for name, gate in _control_gates(contract, tmp_path)["gates"].items():
        assert name in contract["controls"]["fields"], name
        assert soup.select(gate["selector"]), (name, gate["selector"])


def test_a_refused_control_family_reaches_the_page_with_its_reason(tmp_path):
    """The pass matched a refused field by ``frontend_token``, which the
    contract strips from every unsupported field on purpose — so it could
    never fire. The family name survives refusal; the reason is the
    backend's."""
    contract = _contract()
    assert contract["controls"]["fields"]["best_in_slot"]["supported"] is True
    contract["controls"]["fields"]["best_in_slot"] = {
        "supported": False,
        "reason": "Best-in-slot is offline for this snapshot.",
        "payload_field": "best_in_slot",
        "state_path": None,
        "frontend_token": None,
        "conditional": False,
        "availability": "static",
    }
    refusals = _control_gates(contract, tmp_path)["refusals"]
    assert [refusal["name"] for refusal in refusals] == ["best_in_slot"]
    assert refusals[0]["reason"] == "Best-in-slot is offline for this snapshot."
    assert refusals[0]["selector"] == ".bis-trigger, #bisButton"
    assert refusals[0]["mark"] is True


def test_a_fully_supported_contract_refuses_nothing(tmp_path):
    assert _control_gates(_contract(), tmp_path)["refusals"] == []


def test_the_gate_table_covers_every_declared_control_family(tmp_path):
    """A family is gated or it is an exemption that says why — never neither.

    ``optimize`` is the exemption: it mounts no control at all, so the pass has
    nothing to disable. Mounting one means adding its gate row here.
    """
    gates = _control_gates(_contract(), tmp_path)
    declared = set(_contract()["controls"]["fields"])
    assert set(gates["gates"]) | set(gates["exemptions"]) == declared
    assert set(gates["gates"]) & set(gates["exemptions"]) == set()
    assert set(gates["exemptions"]) == {"optimize"}
    assert gates["exemptions"]["optimize"]


def test_the_exempt_family_really_mounts_nothing():
    """The exemption's stated cause, checked: app.js reads the optimize
    attributes in its click delegate and emits none of them, so the roster and
    full-build searches have no entry point on the page."""
    for attribute in (
        "data-optimize-roster",
        "data-optimize-roster-all",
        "data-optimize-build",
    ):
        assert f'closest("[{attribute}]")' in APP_JS, attribute
        assert f'{attribute}="' not in FRONTEND, attribute


def test_the_refusal_pass_runs_at_render_time():
    """A boot-time sweep cannot see a control a later render creates, so the
    pass is the last DOM step of ``render()`` and the boot chain no longer
    calls it. ``.bis-trigger`` and the roster ``[data-picker]`` rows are
    render-created, and both are gated families."""
    render_body = APP_JS.split("\nfunction render() {")[1].split("\n}")[0]
    assert "applyControlCapabilities();" in render_body
    assert APP_JS.count("applyControlCapabilities();") == 1
    for emitted in ('class="bis-trigger', 'data-picker="item"'):
        assert emitted in APP_JS, emitted


def test_no_published_control_family_is_refused():
    """The runtime-disable pass is contract coverage, not a live path: nothing
    ``_feature_fields`` publishes carries a refusal. Adding the first real one
    is the change that retires this test and the note in its docstring."""
    fields = _contract()["controls"]["fields"]
    assert fields
    for name, field in fields.items():
        assert field["supported"] is True, name
        assert field["reason"] is None, name
