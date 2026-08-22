"""P1 Package 3G — Mikael's Blessing active Purify + ally-heal receipt certification.

This file is the independent acceptance matrix for Mikael's Blessing's
Purify active: the explicitly selected ally is cleansed (all crowd control
except Airborne, Blind, Disarm, Nearsight and Suppression, per the cached
wording) and healed for 100 to 250 by the TARGET's level.  It pins the
OBSERVABLES the P1-3G acceptance rules require and runs against today's
source: every behavior that already exists must pass now; genuinely absent
contract pieces are ``xfail`` with reason ``awaiting P3-3G ...``.

Altitude note (disjoint from the P2 Slice 4 matrix): the cleanse kernel
itself (``cleanse_eligibility`` declarations, ``CleanseEligibility.decide``,
``truncate_intervals``, the R1-R27 row matrix) is owned by
``tests/test_cleanse_eligibility.py`` and its consumers; the QSS/Mercurial
self-cast matrix lives there too.  THIS file is the 3G acceptance surface:
it mirrors the same kernel at a different altitude (app result + shared
survival-kernel seam + score/compile + coverage/BIS/optimizer) without
duplicating any R-row assertions.

Contract pinned (typed source-backed values):

* heal_min 100.0 / heal_max 250.0 through the typed ally accessors
  (``ally_item_effect_value`` / ``ally_item_level_value`` — the values live
  in ALLY_ITEM_EFFECTS, NOT ITEM_EFFECTS; ``required_effect_value`` must
  fail loud for Mikael's, never return a stale literal); missing keys
  raise KeyError naming Mikael's AND the key; source_url
  https://wiki.leagueoflegends.com/en-us/Mikael%27s_Blessing and
  source_revision_id 3984364 ride both registries.
* option schema: active_seconds is a float in [0.0, 30.0] with step 0.5,
  default 0.0, label "Purify active seconds".
* Level-domain heal: packet amount == ally_item_level_value(heal_min,
  heal_max, target.level) — level 1 -> 100, level 18 -> 250, monotonic.
* 0.0 no-cast: item presence alone authors NO heal packet, NO cleanse
  receipt, NO cleanse_use receipt (fail closed); a non-zero half-second
  input emits the packet at EXACTLY that time.
* Validation (both layers): > 30 / negative -> "must be between 0.0 and
  30.0"; nan/inf -> "must be finite"; non-numeric -> "must be numeric";
  non-multiple-of-0.5 -> "must be a multiple of 0.5"; the request schema
  (validate_item_input_options / FightParams.from_request -> app 400) and
  the defensive resolver (input_option_float_value) raise identically
  named ValueErrors.  Boundary: 30.0 is schema-valid but a 30.0 activation
  in a shorter fight is skipped with the named "outside_window" reason.
* Selected-ally targeting: the packet targets the selected teammate
  (support_target_selections override honored; default roster order) and is
  priced at THAT ally's level, not at the first teammate's;
  target_scope "explicit_selected_ally"; NO teammates -> no packet (fail
  closed).
* Cleanse decision + exclusions: an eligible control (stun/root/charm)
  active on the ally at activation is REMOVED (interval truncated, downtime
  ends at activation); airborne/suppression are NOT removed with the named
  excluded_control_kind reason; blind/silence/slow are soft kinds that
  never create downtime (control_not_active); a real kind the cleanse table
  does not carry (pull/flee) fails closed with unknown_control (use NOT
  consumed) and a kind outside CC_KIND_VOCABULARY is refused at the timeline
  seam before any decision exists; a control landing AFTER activation is
  untouched (no immunity).
* Receipts: the public result exposes the heal packet (source
  "Mikael's Blessing — Purify", amount, time), the recipient's cleanse
  receipt (decision, removed/kept intervals, heal entry with the sourced
  atom), the caster's cleanse_use receipt, and source_revision_id 3984364
  in the registry/declaration chain.
* Score/receipt parity + compiled: the compiled score kernel FAILS CLOSED
  on the heal+cleanse packet (named support_cleanse receipt) and falls
  back to the receipt walk with equal results; run_fight score-only totals
  equal the full fight.
* Optimizer/BIS/coverage: Mikael's is optimizer-eligible ("Purify cleanses
  and heals an ally."), modeled_state, in get_eligible_legendaries, not
  target-blocked, no stale BIS entry, and review issue 48 is recorded
  (review_issue_refs + the tracked acceptance docs).
* Determinism: identical fights produce identical packets/receipts;
  exactly one Purify packet per fight; one use per fight — a second
  activation is denied with the named use_spent reason (cleanse_denied)
  and truncates nothing further.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.app import app
from src.calculator.defensive_effects import StartingDefenses
from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.item_effects import (
    ALLY_ITEM_EFFECTS,
    ITEM_INPUT_OPTIONS,
    ally_item_effect_value,
    ally_item_level_value,
    input_option_float_value,
    required_effect_value,
    validate_item_input_options,
)
from src.calculator.defensive_effects import resolve_starting_defenses
from src.calculator.optimizer import get_eligible_legendaries
from src.calculator.stats import calculate_total_stats
from src.calculator.participant_timeline import (
    Combatant,
    CoupledSearchContext,
    _WalkCompiler,
    build_participant_timeline,
)
from src.calculator.ledger_projection import LightRow, SHARED_ROW_FIELDS
from src.calculator.pipeline import FightParams, run_fight
from src.calculator.scenario import ChampionLoadout
from src.calculator.survival.compile import (
    UncompilableActionError,
    unrepresentable_template_receipt,
)

from tests.survival_probe import simulate_survival
from tests.survival_probe import survival_of
from tests import item_probe

MIKAELS = "Mikael's Blessing"
MIKAELS_SOURCE = "Mikael's Blessing \u2014 Purify"
SOURCE_URL = "https://wiki.leagueoflegends.com/en-us/Mikael%27s_Blessing"
REVISION_ID = 3984364
HEAL_ATOM_HASH = "cf9fe930ebd40602"
ATOMS_PATH = Path(__file__).resolve().parent.parent / "data" / "atoms" / "items.json"
REPO = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# App-level helpers
# ---------------------------------------------------------------------------


def _calculate(payload: dict) -> dict:
    response = app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_data(as_text=True)[:500]
    return response.get_json()["combat"]


def _calculate_status(payload: dict) -> tuple[int, dict]:
    response = app.test_client().post("/api/calculate", json=payload)
    try:
        body = response.get_json()
    except Exception:  # pragma: no cover - non-JSON error bodies
        body = {}
    return response.status_code, body


def _main(**overrides) -> dict:
    """A deterministic time-based fight request holding Mikael's Blessing."""
    payload = {
        "champion": "Lux",
        "level": 18,
        "items": [MIKAELS],
        "item_options": {MIKAELS: {"active_seconds": 2.5}},
        "fight_mode": "time_based",
        "fight_duration": 8.0,
        "include_auto_attacks": False,
        "ability_ranks": {"Q": 0, "W": 0, "E": 0, "R": 0},
    }
    payload.update(overrides)
    return payload


def _ally(name: str, level: int = 18, **overrides) -> dict:
    return {
        "champion": name,
        "level": level,
        "items": [],
        "ally_effects_enabled": True,
        "ability_ranks": {"Q": 0, "W": 0, "E": 0, "R": 0},
        **overrides,
    }


def _enemy(champion: str = "Aatrox", *, ranks: dict | None = None) -> dict:
    return {
        "champion": champion,
        "level": 18,
        "items": [],
        "ability_ranks": ranks or {"Q": 0, "W": 0, "E": 0, "R": 0},
    }


def _ahri_e() -> dict:
    """Ahri: E charm only (t=0, 1.8s).  Skillshots hit every roster member,
    so the caster is charmed too unless shielded."""
    return _enemy("Ahri", ranks={"Q": 0, "W": 0, "E": 5, "R": 0})


def _purify_events(combat: dict) -> list[dict]:
    return [
        event
        for event in combat.get("support_events", [])
        if event.get("source") == MIKAELS_SOURCE
    ]


# ---------------------------------------------------------------------------
# Timeline-level helpers (the shared survival-kernel seam the P2 matrices
# use; the authoring layer is not re-tested here — packets are authored
# exactly like item_support_effects does: kind heal + cleanse marker)
# ---------------------------------------------------------------------------


def _combatant(participant_id: str, team: str, health: float = 3000.0) -> Combatant:
    defenses = StartingDefenses(
        magic_shield=0.0,
        physical_shield=0.0,
        general_shield=0.0,
        healing_received_multiplier=1.0,
    )
    return Combatant(
        participant_id=participant_id,
        team=team,
        champion_data={"name": participant_id},
        level=1,
        items=(),
        stats={"health": health},
        defenses=defenses,
    )


def _control(
    time: float,
    kind: str,
    duration: float,
    *,
    source: str = "E",
    target: str = "target",
    sequence: int = 0,
) -> dict:
    return {
        "time": time,
        "damage": 0.0,
        "damage_type": "magic",
        "attacker": "enemy",
        "target": target,
        "source_key": source,
        "source": source,
        "is_ability": True,
        "kind": "crowd_control",
        "sequence": sequence,
        "_event_id": f"cc-{sequence}",
        "cc_kind": kind,
        "cc_duration": duration,
    }


def _purify(
    time: float,
    *,
    target: str = "target",
    attacker: str = "caster",
    amount: float = 100.0,
    sequence: int = 0,
) -> dict:
    """One Mikael's Purify activation authored as the walk sees it: a heal
    packet carrying the cleanse marker (item_support_effects emits exactly
    this shape)."""
    return {
        "time": time,
        "kind": "heal",
        "amount": amount,
        "attacker": attacker,
        "target": target,
        "source": MIKAELS_SOURCE,
        "source_key": MIKAELS_SOURCE,
        "cleanse": True,
        "cleanse_item": MIKAELS,
        "sequence": sequence,
        "_event_id": f"purify-{sequence}",
    }


def _simulate(
    incoming: list[dict],
    supports: list[dict],
    *,
    combatants: list[Combatant] | None = None,
    duration: float = 10.0,
) -> dict[str, dict]:
    """One timeline run: enemy controls -> the selected ally, Purify ->
    the same ally from a free caster."""
    if combatants is None:
        combatants = [
            _combatant("enemy", "enemy"),
            _combatant("target", "main"),
            _combatant("caster", "main"),
        ]
    return simulate_survival(
        combatants,
        {"target": [dict(packet) for packet in incoming]},
        {},
        {"target": [dict(packet) for packet in supports]},
        duration,
    )


# ---------------------------------------------------------------------------
# 1. Typed accessor values + option schema + missing-key fail-closed
# ---------------------------------------------------------------------------


def test_typed_heal_values_and_option_schema():
    """heal_min 100.0 / heal_max 250.0 through the typed ally accessors
    (the heal values live in ALLY_ITEM_EFFECTS, not ITEM_EFFECTS); the
    public input option is a float in [0, 30] with step 0.5, default 0.0,
    label 'Purify active seconds'."""
    assert ally_item_effect_value(MIKAELS, "heal_min") == 100.0
    assert ally_item_effect_value(MIKAELS, "heal_max") == 250.0
    assert ALLY_ITEM_EFFECTS[MIKAELS]["source_url"] == SOURCE_URL
    assert ALLY_ITEM_EFFECTS[MIKAELS]["source_revision_id"] == REVISION_ID

    option = ITEM_INPUT_OPTIONS[MIKAELS]["options"]["active_seconds"]
    assert option == {
        "type": "float",
        "label": "Purify active seconds",
        "default": 0.0,
        "min": 0.0,
        "max": 30.0,
        "step": 0.5,
    }
    block = ITEM_INPUT_OPTIONS[MIKAELS]
    assert block["source_url"] == SOURCE_URL
    assert block["source_revision_id"] == REVISION_ID


def test_missing_heal_key_raises_keyerror_naming_mikaels_and_key(monkeypatch):
    """A missing typed key fails loud, naming the item and the key (AGENTS.md
    rule 5: no silent stale fallbacks at call sites)."""
    broken = dict(ALLY_ITEM_EFFECTS[MIKAELS])
    broken.pop("heal_min")
    monkeypatch.setitem(ALLY_ITEM_EFFECTS, MIKAELS, broken)

    with pytest.raises(KeyError) as excinfo:
        ally_item_level_value(MIKAELS, "heal_min", "heal_max", 18)
    message = str(excinfo.value)
    assert "Mikael" in message and "Blessing" in message
    assert "heal_min" in message


def test_item_effects_accessor_fails_loud_for_mikaels():
    """required_effect_value reads ITEM_EFFECTS, where Mikael's has no heal
    record (the values live in ALLY_ITEM_EFFECTS); the accessor must raise
    naming the item and key instead of returning a stale literal."""
    with pytest.raises(KeyError) as excinfo:
        required_effect_value(MIKAELS, "heal_min")
    message = str(excinfo.value)
    assert "Mikael" in message and "Blessing" in message
    assert "heal_min" in message


def test_ally_item_level_value_level_domain():
    """Level-domain heal: level 1 -> 100, level 18 -> 250, monotonic
    between; the packet amount equals this accessor at the target's level
    (pinned again at the app level in section 5)."""
    assert ally_item_level_value(MIKAELS, "heal_min", "heal_max", 1) == pytest.approx(
        100.0
    )
    assert ally_item_level_value(MIKAELS, "heal_min", "heal_max", 18) == pytest.approx(
        250.0
    )
    values = [
        ally_item_level_value(MIKAELS, "heal_min", "heal_max", level)
        for level in range(1, 19)
    ]
    assert values[0] == pytest.approx(100.0)
    assert values[-1] == pytest.approx(250.0)
    assert all(values[i] <= values[i + 1] for i in range(len(values) - 1))
    # Linear interpolation from level 1 (100) to level 18 (250): level 9
    # is 100 + 150 * 8/17.
    assert values[8] == pytest.approx(100.0 + 150.0 * 8 / 17)
    # Out-of-domain levels clamp to the sourced domain (no extrapolation).
    assert ally_item_level_value(MIKAELS, "heal_min", "heal_max", 0) == pytest.approx(
        100.0
    )
    assert ally_item_level_value(MIKAELS, "heal_min", "heal_max", 20) == pytest.approx(
        250.0
    )


# ---------------------------------------------------------------------------
# 2. 0.0 no-cast: presence alone never assumes activation
# ---------------------------------------------------------------------------


def test_active_seconds_zero_no_cast_no_receipts():
    """Item presence with active_seconds 0.0 (and with no option at all)
    authors NO Purify heal packet, NO cleanse receipt on any ally, and NO
    cleanse_use receipt on the caster — presence alone never assumes a
    cast."""
    for item_options in (
        {MIKAELS: {"active_seconds": 0.0}},
        {},
        None,
    ):
        payload = _main(
            enemies=[_ahri_e()],
            allies=[_ally("Jinx")],
        )
        if item_options is None:
            payload.pop("item_options")
        else:
            payload["item_options"] = item_options
        combat = _calculate(payload)
        assert _purify_events(combat) == []
        for pid in ("main", "ally:Jinx"):
            row = survival_of(combat, pid)
            assert row.get("cleanse") is None
            assert row.get("cleanse_use") is None
        # The enemy control still lands (the roster is unchanged).
        assert survival_of(combat, "ally:Jinx")["action_downtime"] == pytest.approx(1.8)


# ---------------------------------------------------------------------------
# 3. Half-second timing + two-layer validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seconds", [0.5, 1.0, 2.5])
def test_valid_half_second_timings_emit_packet_at_exact_time(seconds):
    """A non-zero half-second input emits the Purify packet at EXACTLY that
    time (no rounding, no delay)."""
    combat = _calculate(
        _main(
            item_options={MIKAELS: {"active_seconds": seconds}},
            enemies=[_enemy()],
            allies=[_ally("Jinx")],
        )
    )
    (purify,) = _purify_events(combat)
    assert purify["time"] == pytest.approx(seconds)


@pytest.mark.parametrize("seconds", [30.5, 31.0, 100.0])
def test_validation_rejects_values_above_max(seconds):
    """Above 30 the request schema raises, the defensive resolver raises,
    and the app answers a named 400; there is no clamp path."""
    message = (
        "item_options.Mikael's Blessing.active_seconds must be between 0.0 and 30.0"
    )
    with pytest.raises(ValueError, match=message):
        validate_item_input_options({MIKAELS: {"active_seconds": seconds}})
    with pytest.raises(ValueError, match=message):
        input_option_float_value(
            [get_item_by_name(MIKAELS)],
            {MIKAELS: {"active_seconds": seconds}},
            MIKAELS,
            "active_seconds",
        )
    status, body = _calculate_status(
        _main(item_options={MIKAELS: {"active_seconds": seconds}})
    )
    assert status == 400
    assert body.get("error") == message


@pytest.mark.parametrize("seconds", [-0.5, -1.0, -30.0])
def test_validation_rejects_negative_values(seconds):
    message = (
        "item_options.Mikael's Blessing.active_seconds must be between 0.0 and 30.0"
    )
    with pytest.raises(ValueError, match=message):
        validate_item_input_options({MIKAELS: {"active_seconds": seconds}})
    with pytest.raises(ValueError, match=message):
        input_option_float_value(
            [get_item_by_name(MIKAELS)],
            {MIKAELS: {"active_seconds": seconds}},
            MIKAELS,
            "active_seconds",
        )
    status, body = _calculate_status(
        _main(item_options={MIKAELS: {"active_seconds": seconds}})
    )
    assert status == 400
    assert body.get("error") == message


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (float("nan"), "must be finite"),
        (float("inf"), "must be finite"),
        (float("-inf"), "must be finite"),
        (True, "must be numeric"),
        (None, "must be numeric"),
        ("abc", "must be numeric"),
    ],
)
def test_validation_rejects_non_finite_and_non_numeric(value, message):
    """nan/inf are rejected with 'must be finite'; booleans, None and
    non-numeric strings with 'must be numeric' — at BOTH layers and the
    app."""
    full = f"item_options.Mikael's Blessing.active_seconds {message}"
    with pytest.raises(ValueError, match=full):
        validate_item_input_options({MIKAELS: {"active_seconds": value}})
    with pytest.raises(ValueError, match=full):
        input_option_float_value(
            [get_item_by_name(MIKAELS)],
            {MIKAELS: {"active_seconds": value}},
            MIKAELS,
            "active_seconds",
        )
    status, body = _calculate_status(
        _main(item_options={MIKAELS: {"active_seconds": value}})
    )
    assert status == 400
    assert body.get("error") == full


@pytest.mark.parametrize("seconds", [0.7, 1.3, 2.25, 29.75])
def test_validation_rejects_non_step_multiple(seconds):
    """The option is a 0.5-step control: non-multiples are rejected at both
    layers with the named 'multiple of 0.5' error, never silently
    rounded."""
    full = "item_options.Mikael's Blessing.active_seconds must be a multiple of 0.5"
    with pytest.raises(ValueError, match=full):
        validate_item_input_options({MIKAELS: {"active_seconds": seconds}})
    with pytest.raises(ValueError, match=full):
        input_option_float_value(
            [get_item_by_name(MIKAELS)],
            {MIKAELS: {"active_seconds": seconds}},
            MIKAELS,
            "active_seconds",
        )
    status, body = _calculate_status(
        _main(item_options={MIKAELS: {"active_seconds": seconds}})
    )
    assert status == 400
    assert body.get("error") == full


def test_numeric_strings_are_coerced_by_both_layers():
    """A numeric string '2.5' is coerced (not rejected) by the request
    schema and the resolver, and the app emits the packet at 2.5."""
    parsed = validate_item_input_options({MIKAELS: {"active_seconds": "2.5"}})
    assert parsed[MIKAELS]["active_seconds"] == 2.5
    assert (
        input_option_float_value(
            [get_item_by_name(MIKAELS)],
            {MIKAELS: {"active_seconds": "2.5"}},
            MIKAELS,
            "active_seconds",
        )
        == 2.5
    )
    combat = _calculate(
        _main(
            item_options={MIKAELS: {"active_seconds": "2.5"}},
            enemies=[_enemy()],
            allies=[_ally("Jinx")],
        )
    )
    (purify,) = _purify_events(combat)
    assert purify["time"] == pytest.approx(2.5)


def test_unknown_option_name_rejected_at_request_layer():
    """The request schema rejects unknown option names with a named 400;
    the resolver raises the same named error."""
    with pytest.raises(
        ValueError, match="Unknown option for Mikael's Blessing: start_time"
    ):
        validate_item_input_options({MIKAELS: {"start_time": 1.0}})
    with pytest.raises(
        ValueError, match="Unknown option for Mikael's Blessing: start_time"
    ):
        input_option_float_value(
            [get_item_by_name(MIKAELS)],
            {MIKAELS: {"start_time": 1.0}},
            MIKAELS,
            "start_time",
        )
    status, body = _calculate_status(_main(item_options={MIKAELS: {"start_time": 1.0}}))
    assert status == 400
    assert body.get("error") == "Unknown option for Mikael's Blessing: start_time"


def test_max_boundary_30_seconds_is_schema_valid_and_skipped_outside_window():
    """30.0 is the schema maximum (accepted, no error); in an 8-second
    fight the authored packet cannot fire and the walk skips it with the
    named 'outside_window' reason — no heal, no receipts."""
    status, body = _calculate_status(
        _main(
            item_options={MIKAELS: {"active_seconds": 30.0}},
            enemies=[_enemy()],
            allies=[_ally("Jinx")],
        )
    )
    assert status == 200
    combat = body["combat"]
    (purify,) = _purify_events(combat)
    assert purify["time"] == pytest.approx(30.0)
    assert purify["skipped_reason"] == "outside_window"
    for pid in ("main", "ally:Jinx"):
        assert survival_of(combat, pid).get("cleanse_use") is None
        assert survival_of(combat, pid).get("cleanse") is None


# ---------------------------------------------------------------------------
# 4. Selected-ally targeting
# ---------------------------------------------------------------------------


def test_packet_targets_the_selected_ally_and_override_is_honored():
    """With a teammate roster the packet targets the selected ally: the
    default roster order picks the first teammate; the
    support_target_selections override is honored (index 1 -> Ashe); the
    packet declares target_scope 'explicit_selected_ally' and the
    selection key used by the override."""
    payload = _main(
        enemies=[_enemy()],
        allies=[_ally("Jinx"), _ally("Ashe")],
    )
    combat = _calculate(payload)
    (purify,) = _purify_events(combat)
    assert purify["target"] == "ally:Jinx"
    assert purify["target_scope"] == "explicit_selected_ally"
    selection_key = purify["target_selection_key"]
    assert selection_key == f"heal:{MIKAELS_SOURCE}"

    overridden = _calculate(
        {
            **_main(enemies=[_ahri_e()], allies=[_ally("Jinx"), _ally("Ashe")]),
            "support_target_selections": {selection_key: 1},
        }
    )
    (purify,) = _purify_events(overridden)
    assert purify["target"] == "ally:Ashe"
    assert purify["target_policy"] == "selected_teammate"
    # The heal follows the selection onto the chosen ally only: Ashe is
    # damaged by the charm and restored; Jinx receives nothing.
    assert survival_of(overridden, "ally:Ashe")["healing_received"] > 0.0
    assert survival_of(overridden, "ally:Jinx")["healing_received"] == 0.0


def test_heal_is_priced_at_the_selected_allys_own_level():
    """The TARGET's level is the level of the ally the packet lands on, not
    of the roster's first teammate.  With a level-1 Jinx and a level-18 Ashe
    the default selection heals 100 and index 1 heals 250."""
    allies = [_ally("Jinx", level=1), _ally("Ashe", level=18)]
    default = _calculate(_main(enemies=[_enemy()], allies=allies))
    (first,) = _purify_events(default)
    assert first["target"] == "ally:Jinx"
    assert first["amount"] == pytest.approx(
        ally_item_level_value(MIKAELS, "heal_min", "heal_max", 1)
    )

    overridden = _calculate(
        {
            **_main(enemies=[_enemy()], allies=allies),
            "support_target_selections": {f"heal:{MIKAELS_SOURCE}": 1},
        }
    )
    (second,) = _purify_events(overridden)
    assert second["target"] == "ally:Ashe"
    assert second["amount"] == pytest.approx(
        ally_item_level_value(MIKAELS, "heal_min", "heal_max", 18)
    )


def test_no_teammates_fails_closed():
    """Without a teammate roster Mikael's authors NO Purify packet and NO
    receipts (fail closed) — the item is present and the option is set,
    but there is no selected ally to target."""
    combat = _calculate(_main(enemies=[_enemy()]))
    assert _purify_events(combat) == []
    assert survival_of(combat, "main").get("cleanse_use") is None
    assert survival_of(combat, "main").get("cleanse") is None


# ---------------------------------------------------------------------------
# 5. Level-scaled heal + separate effect + one packet per fight
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "level,expected", [(1, 100.0), (6, 144.11764705882354), (18, 250.0)]
)
def test_packet_amount_equals_ally_item_level_value(level, expected):
    """The packet amount == ally_item_level_value(100, 250, target.level):
    level 1 -> 100, level 18 -> 250, monotonic in between."""
    assert ally_item_level_value(
        MIKAELS, "heal_min", "heal_max", level
    ) == pytest.approx(expected)
    combat = _calculate(
        _main(
            enemies=[_enemy()],
            allies=[_ally("Jinx", level=level)],
        )
    )
    (purify,) = _purify_events(combat)
    assert purify["amount"] == pytest.approx(expected)
    assert purify["amount"] == pytest.approx(
        ally_item_level_value(MIKAELS, "heal_min", "heal_max", level)
    )


def test_heal_fires_even_with_no_active_control():
    """The heal is a SEPARATE effect from the cleanse: with no control
    active on the ally at activation the heal still fires, the decision
    names control_not_active, and the use is consumed."""
    # Ahri's charm damages the ally and ends at 1.8; Purify fires at 2.5
    # (caster free) with nothing left to remove.
    combat = _calculate(
        _main(
            enemies=[_ahri_e()],
            allies=[_ally("Jinx")],
        )
    )
    (purify,) = _purify_events(combat)
    assert purify["amount"] == pytest.approx(250.0)
    assert purify.get("skipped_reason") is None
    jinx = survival_of(combat, "ally:Jinx")
    assert jinx["healing_received"] > 0.0
    assert purify["applied_amount"] == pytest.approx(jinx["healing_received"], abs=0.05)
    assert jinx["cleanse"]["decision"]["reason"] == "control_not_active"
    assert jinx["cleanse"]["heal"]["amount"] == pytest.approx(250.0)
    assert jinx["cleanse"]["heal"]["source"] == MIKAELS_SOURCE
    use = survival_of(combat, "main")["cleanse_use"]
    assert use["uses_before"] == 1
    assert use["uses_after"] == 0


def test_exactly_one_heal_packet_per_fight():
    """No duplicate Purify packets: exactly one support event per fight
    (the heal+cleanse is a single authored packet, not one per effect)."""
    combat = _calculate(
        _main(
            enemies=[_enemy()],
            allies=[_ally("Jinx"), _ally("Ashe")],
        )
    )
    assert len(_purify_events(combat)) == 1


# ---------------------------------------------------------------------------
# 6. Cleanse decision + exclusions (fail closed, named reasons)
# ---------------------------------------------------------------------------


def test_app_level_cleanse_removes_the_allied_control():
    """App level, full path: the caster is spell-shielded (Banshee's Veil
    blocks the charm on the caster only) so Purify at 1.0 fires while
    ally:Jinx is still charmed; the charm interval is truncated to
    [0.0, 1.0], the removed tail is receipted, and the heal lands."""
    combat = _calculate(
        _main(
            items=[MIKAELS, "Banshee's Veil"],
            item_options={MIKAELS: {"active_seconds": 1.0}},
            enemies=[_ahri_e()],
            allies=[_ally("Jinx")],
        )
    )
    assert survival_of(combat, "main")["spell_shield_used"] is True
    (purify,) = _purify_events(combat)
    assert purify.get("skipped_reason") is None

    jinx = survival_of(combat, "ally:Jinx")
    assert jinx["action_downtime"] == pytest.approx(1.0)
    assert [
        (i["kind"], i["start"], i["end"]) for i in jinx["crowd_control_intervals"]
    ] == [("immobilize", 0.0, 1.0)]
    receipt = jinx["cleanse"]
    assert receipt["decision"]["reason"] == ""
    assert receipt["removed_controls"] == [
        {
            "control_kind": "immobilize",
            "source": "E",
            "start": pytest.approx(1.0),
            "end": pytest.approx(1.8),
            "reason": "",
        }
    ]
    assert receipt["downtime_before"] == pytest.approx(1.8)
    assert receipt["downtime_after"] == pytest.approx(1.0)
    assert receipt["heal"]["amount"] == pytest.approx(250.0)
    use = survival_of(combat, "main")["cleanse_use"]
    assert use["uses_before"] == 1
    assert use["uses_after"] == 0


@pytest.mark.parametrize("kind", ["stun", "root", "charm"])
def test_supported_controls_are_removed(kind):
    """A supported control kind active on the ally at activation is
    removed: the tail is truncated, the interval ends at activation, and
    the downtime reflects the truncation."""
    result = _simulate([_control(1.0, kind, 2.0)], [_purify(1.5)])
    target = result["target"]
    receipt = target["cleanse"]
    assert receipt["decision"]["reason"] == ""
    assert receipt["removed_controls"] == [
        {
            "control_kind": kind,
            "source": "E",
            "start": pytest.approx(1.5),
            "end": pytest.approx(3.0),
            "reason": "",
        }
    ]
    assert [
        (i["kind"], i["start"], i["end"]) for i in target["crowd_control_intervals"]
    ] == [(kind, 1.0, 1.5)]
    assert target["action_downtime"] == pytest.approx(0.5)
    assert receipt["heal"]["amount"] == pytest.approx(100.0)


@pytest.mark.parametrize(
    "kind,reason",
    [
        ("airborne", "excluded_control_kind"),
        ("suppression", "excluded_control_kind"),
        ("pull", "unknown_control"),
    ],
)
def test_excluded_kinds_fail_closed_with_named_reason(kind, reason):
    """Airborne and suppression are named exclusions in the sourced wording
    (NOT removed; the interval survives); ``pull`` is a real control kind
    the cleanse table does not carry, so it fails closed with
    unknown_control.  Each rejection is receipted with its named reason and
    no truncation happens.

    ``pull`` rather than an invented kind: ``cc_kind`` is a closed
    vocabulary now, so a misspelling never reaches this layer at all — it
    is refused at the timeline seam (see the test below).  The two
    refusals are different and both are live."""
    result = _simulate([_control(1.0, kind, 2.0)], [_purify(1.5)])
    target = result["target"]
    receipt = target["cleanse"]
    assert receipt["decision"]["reason"] == reason
    assert receipt["removed_controls"] == []
    assert receipt["rejected_controls"] == [
        {
            "control_kind": kind,
            "source": "E",
            "start": pytest.approx(1.0),
            "end": pytest.approx(3.0),
            "reason": reason,
        }
    ]
    assert target["crowd_control_intervals"][0]["end"] == pytest.approx(3.0)
    assert target["action_downtime"] == pytest.approx(2.0)


@pytest.mark.parametrize("kind", ["blind", "silence", "slow"])
def test_soft_kinds_never_create_downtime(kind):
    """Blind/silence/slow are SOFT kinds: the control adds no interval and
    no downtime, so the cleanse receipt names control_not_active (there is
    nothing to remove) and the heal fires.

    ``disarm`` used to stand here; it is not in ``CC_KIND_VOCABULARY``, so
    no packet can carry it — ``silence`` is the soft kind that both the
    vocabulary and the cleanse table declare."""
    result = _simulate([_control(1.0, kind, 2.0)], [_purify(1.5)])
    target = result["target"]
    assert target["crowd_control_intervals"] == []
    assert target["action_downtime"] == pytest.approx(0.0)
    assert target["cleanse"]["decision"]["reason"] == "control_not_active"
    assert target["cleanse"]["removed_controls"] == []
    assert target["cleanse"]["heal"]["amount"] == pytest.approx(100.0)


def test_a_control_the_cleanse_table_does_not_carry_does_not_consume():
    """``flee`` is a real control kind with no cleanse declaration: it
    fails closed with the named unknown_control reason, truncates nothing,
    and does NOT consume a use."""
    result = _simulate([_control(1.0, "flee", 2.0)], [_purify(1.5)])
    target = result["target"]
    receipt = target["cleanse"]
    assert receipt["decision"]["reason"] == "unknown_control"
    assert receipt["removed_controls"] == []
    assert target["crowd_control_intervals"][0]["end"] == pytest.approx(3.0)
    assert target["action_downtime"] == pytest.approx(2.0)
    # unknown_control does not consume the use (committed semantics).
    caster = result["caster"]
    assert caster["cleanse_use"]["uses_before"] == 1
    assert caster["cleanse_use"]["uses_after"] == 1


def test_a_kind_outside_the_vocabulary_never_reaches_the_cleanse_layer():
    """``cc_kind`` is closed: a misspelling is refused at the timeline seam.

    This is the earlier of the two refusals — before any cleanse decision
    exists — and it is a raise rather than a receipt precisely because a
    kind nobody declared must never author a no-op stun.
    """
    with pytest.raises(ValueError, match="CC_KIND_VOCABULARY"):
        _simulate([_control(1.0, "dance", 2.0)], [_purify(1.5)])


def test_control_landing_after_activation_is_untouched():
    """A cleanse creates NO immunity: a control landing after the
    activation applies in full and its interval survives."""
    result = _simulate(
        [
            _control(1.0, "stun", 2.0, source="B"),
            _control(2.5, "stun", 1.0, source="C", sequence=1),
        ],
        [_purify(2.0)],
    )
    target = result["target"]
    receipt = target["cleanse"]
    assert receipt["decision"]["reason"] == ""
    # The active control B is truncated; the future control C is untouched.
    assert receipt["removed_controls"] == [
        {
            "control_kind": "stun",
            "source": "B",
            "start": pytest.approx(2.0),
            "end": pytest.approx(3.0),
            "reason": "",
        }
    ]
    assert [
        (i["source"], i["start"], i["end"]) for i in target["crowd_control_intervals"]
    ] == [("B", 1.0, 2.0), ("C", 2.5, 3.5)]
    assert target["action_downtime"] == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# 7. Downtime: truncation + historical preservation
# ---------------------------------------------------------------------------


def test_downtime_reflects_truncation_and_historical_downtime_remains():
    """The recipient's action_downtime equals the MERGED kept intervals:
    an interval that ended before activation (historical) remains counted
    in full, the interval active at activation ends AT activation, and a
    future control is untouched."""
    result = _simulate(
        [
            _control(0.5, "stun", 0.8, source="A"),  # [0.5, 1.3] historical
            _control(1.0, "stun", 1.5, source="B"),  # [1.0, 2.5] active
            _control(2.5, "stun", 1.0, source="C", sequence=2),  # future
        ],
        [_purify(2.0)],
    )
    target = result["target"]
    receipt = target["cleanse"]
    assert receipt["decision"]["reason"] == ""
    # Historical A remains; B is clamped; C is untouched (no immunity).
    assert [
        (i["source"], i["start"], i["end"]) for i in target["crowd_control_intervals"]
    ] == [("A", 0.5, 1.3), ("B", 1.0, 2.0), ("C", 2.5, 3.5)]
    assert receipt["removed_controls"] == [
        {
            "control_kind": "stun",
            "source": "B",
            "start": pytest.approx(2.0),
            "end": pytest.approx(2.5),
            "reason": "",
        }
    ]
    # Merged kept intervals: [0.5,2.0] (1.5) + [2.5,3.5] (1.0) == 2.5.
    assert receipt["downtime_before"] == pytest.approx(2.0)
    assert receipt["downtime_after"] == pytest.approx(2.5)
    assert target["action_downtime"] == pytest.approx(2.5)
    # Receipt-versus-result parity: the kept intervals match the survival row.
    assert [(i["kind"], i["start"], i["end"]) for i in receipt["intervals_after"]] == [
        (i["kind"], i["start"], i["end"]) for i in target["crowd_control_intervals"]
    ]


# ---------------------------------------------------------------------------
# 8. Same-time ordering (deterministic)
# ---------------------------------------------------------------------------


def test_same_time_control_is_removed_and_outcome_is_deterministic():
    """A control landing exactly at the activation time resolves BEFORE the
    cleanse in the walk's total order, so it is removed ENTIRELY (no
    interval survives); repeated runs are identical."""

    def run() -> dict[str, dict]:
        return _simulate([_control(2.0, "stun", 2.0)], [_purify(2.0)])

    first = run()
    second = run()
    assert first == second  # deterministic
    target = first["target"]
    receipt = target["cleanse"]
    assert receipt["activation_time"] == pytest.approx(2.0)
    assert receipt["decision"]["reason"] == ""
    assert receipt["removed_controls"] == [
        {
            "control_kind": "stun",
            "source": "E",
            "start": pytest.approx(2.0),
            "end": pytest.approx(4.0),
            "reason": "",
        }
    ]
    assert target["crowd_control_intervals"] == []
    assert target["action_downtime"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 9. Receipts: heal packet, cleanse_use, truncated intervals, revision
# ---------------------------------------------------------------------------


def test_public_result_exposes_heal_packet_cleanse_use_and_truncation():
    """The public result exposes (a) the Purify heal packet with source,
    amount and time, (b) the caster's cleanse_use receipt naming the item
    and the consumption, and (c) the recipient's cleanse receipt with the
    decision and the truncated intervals."""
    combat = _calculate(
        _main(
            items=[MIKAELS, "Banshee's Veil"],
            item_options={MIKAELS: {"active_seconds": 1.0}},
            enemies=[_ahri_e()],
            allies=[_ally("Jinx")],
        )
    )
    (purify,) = _purify_events(combat)
    assert purify["source"] == MIKAELS_SOURCE
    assert purify["amount"] == pytest.approx(250.0)
    assert purify["time"] == pytest.approx(1.0)
    assert purify["cleanse"] is True
    assert purify["target"] == "ally:Jinx"
    assert purify["target_scope"] == "explicit_selected_ally"

    use = survival_of(combat, "main")["cleanse_use"]
    assert use["item"] == MIKAELS
    assert use["uses_before"] == 1
    assert use["uses_after"] == 0
    assert use["activations"] == 1
    assert use["cooldown_seconds"] is None
    assert use["cooldown_source_gap"] is True
    assert use["fired_while_crowd_controlled"] is False

    receipt = survival_of(combat, "ally:Jinx")["cleanse"]
    assert receipt["item"] == MIKAELS
    assert receipt["target"] == "ally:Jinx"
    assert receipt["activation_time"] == pytest.approx(1.0)
    assert receipt["decision"]["reason"] == ""
    assert receipt["removed_controls"] == [
        {
            "control_kind": "immobilize",
            "source": "E",
            "start": pytest.approx(1.0),
            "end": pytest.approx(1.8),
            "reason": "",
        }
    ]
    assert [(i["kind"], i["start"], i["end"]) for i in receipt["intervals_after"]] == [
        ("immobilize", 0.0, 1.0)
    ]
    assert receipt["downtime_before"] == pytest.approx(1.8)
    assert receipt["downtime_after"] == pytest.approx(1.0)
    # The truncated intervals match the public survival row (no drift).
    assert [(i["kind"], i["start"], i["end"]) for i in receipt["intervals_after"]] == [
        (i["kind"], i["start"], i["end"])
        for i in survival_of(combat, "ally:Jinx")["crowd_control_intervals"]
    ]


def test_heal_receipt_carries_the_sourced_atom():
    """The cleanse receipt's heal entry carries the sourced heal.flat atom
    (data/atoms/items.json id 3222, hash pinned) and the Purify source."""
    combat = _calculate(
        _main(
            enemies=[_enemy()],
            allies=[_ally("Jinx")],
        )
    )
    heal = survival_of(combat, "ally:Jinx")["cleanse"]["heal"]
    assert heal["amount"] == pytest.approx(250.0)
    assert heal["source"] == MIKAELS_SOURCE
    assert {atom["hash"] for atom in heal["source_atoms"]} == {HEAL_ATOM_HASH}

    atoms = json.loads(ATOMS_PATH.read_text(encoding="utf-8"))
    entries = atoms["objects"].get("3222")
    assert entries is not None
    heal_atoms = [entry for entry in entries if entry["atom_id"] == "heal.flat"]
    assert heal_atoms == [
        {
            "atom_id": "heal.flat",
            "behavior": "heal",
            "source": "Mikael's Blessing.actives[0].branches[0]",
            "name": "Purify",
            "values": [100.0, 250.0],
            "units": ["flat", "flat"],
            "evidence": ["active:Purify@kw:heal"],
            "hash": HEAL_ATOM_HASH,
        }
    ]


def test_source_revision_3984364_rides_the_receipt_chain():
    """source_revision_id 3984364 is pinned in the ally-effect registry,
    the input-option registry, and the cleanse declaration's cache receipt
    (the chain the packet amount, the option schema and the decision all
    trace back to)."""
    assert ALLY_ITEM_EFFECTS[MIKAELS]["source_revision_id"] == REVISION_ID
    assert ITEM_INPUT_OPTIONS[MIKAELS]["source_revision_id"] == REVISION_ID

    from src.calculator.cleanse_eligibility import ITEM_CLEANSE_DECLARATIONS

    declaration = ITEM_CLEANSE_DECLARATIONS[MIKAELS]
    receipts = declaration["source_receipts"]
    assert receipts and receipts[0]["revision_id"] == REVISION_ID
    assert "3222" in str(receipts[0])
    assert declaration["heal"]["amount_min"] == pytest.approx(100.0)
    assert declaration["heal"]["amount_max"] == pytest.approx(250.0)
    assert declaration["target_scope"] == "explicit_selected_ally"
    assert declaration["excluded_control_kinds"] == (
        "airborne",
        "blind",
        "disarm",
        "nearsight",
        "suppression",
    )


# ---------------------------------------------------------------------------
# 10. Score/receipt parity + compiled fail-closed
# ---------------------------------------------------------------------------


def test_compiled_score_path_fails_closed_on_the_heal_cleanse_packet():
    """The compiled score kernel cannot reproduce the action-downtime
    truncation, so a heal packet carrying the cleanse marker fails closed
    with the named 'support_cleanse' receipt (never compiled as a silent
    plain heal); a plain heal stays representable."""
    assert (
        unrepresentable_template_receipt(
            {"kind": "heal", "amount": 100.0, "cleanse": True}
        )
        == "support_cleanse"
    )
    assert (
        unrepresentable_template_receipt(
            {"kind": "heal", "amount": 100.0, "cleanse_item": MIKAELS}
        )
        == "support_cleanse"
    )
    assert unrepresentable_template_receipt({"kind": "heal", "amount": 100.0}) is None
    compiler = _WalkCompiler()
    with pytest.raises(UncompilableActionError) as excinfo:
        compiler.add_support_templates(
            [
                {
                    "kind": "heal",
                    "amount": 100.0,
                    "cleanse": True,
                    "source": MIKAELS_SOURCE,
                    "attacker": "caster",
                    "target": "main",
                    "time": 2.5,
                }
            ],
            0,
            {"main": 0, "caster": 1},
        )
    assert "support_cleanse" in str(excinfo.value)


def _timeline(include_receipt: bool = True, **kwargs):
    """One full participant timeline for a Mikael's support build."""
    params = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": 8,
            "role": "support",
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 0, "W": 0, "E": 0, "R": 0},
            "item_options": {MIKAELS: {"active_seconds": 2.5}},
            "support_target_selections": {f"heal:{MIKAELS_SOURCE}": 0},
            "allies": [_ally("Jinx")],
            "enemies": [_ahri_e()],
        },
        deterministic=True,
    )

    def roster(champion: str, role: str = "mid", items=(), item_options=None):
        return ChampionLoadout(
            champion=champion,
            level=18,
            role=role,
            items=items,
            item_options=item_options or {},
        ).resolve()

    champion = get_champion("Lux")
    item = get_item_by_name(MIKAELS)
    stats = calculate_total_stats(champion, 18, [item], role="support")
    defenses = resolve_starting_defenses(
        "Lux", 18, stats, [item], item_options=params.item_options
    )
    return build_participant_timeline(
        champion,
        18,
        [item],
        params,
        main_stats=stats,
        main_defenses=defenses,
        enemies=[roster("Ahri")],
        allies=[roster("Jinx", role="support")],
        include_receipt=include_receipt,
        **kwargs,
    )


def test_compiled_walk_falls_back_to_the_receipt_walk_with_equal_results():
    """The compiled path fails closed on the heal+cleanse packet and falls
    back to the authoritative receipt walk: the fast result deep-equals
    the legacy receipt walk, and the guard proves both walks actually
    carried the Purify heal+cleanse (the comparison is not trivially
    equal)."""
    legacy = _timeline(include_receipt=False)
    context = CoupledSearchContext()
    fast = _timeline(
        include_receipt=False,
        pair_result_cache={},
        search_context=context,
    )
    assert fast == legacy
    assert context.panels  # the compiled panel was attempted before fallback
    # Guard: the receipt walk carried the real Purify packet and receipt.
    jinx = next(
        row for row in legacy["participants"] if row["participant_id"] == "ally:Jinx"
    )
    receipt = jinx["survival"]["cleanse"]
    assert receipt["decision"]["reason"] == "control_not_active"
    assert receipt["heal"]["amount"] == pytest.approx(250.0)
    assert receipt["heal"]["source"] == MIKAELS_SOURCE


def _scoring_rows(result):
    """The scoring fields of one fight's damage events, in either shape.

    A build the projection finds adequate is served the LIGHT tuple
    ledger, so the score path's rows are positional.  They are read through
    the one declaration of that layout (``ledger_projection.LightRow``)
    rather than a second set of indices here, and compared on the fields
    both shapes carry (``SHARED_ROW_FIELDS``) plus the time the light row
    packs into its sort key.
    """
    rows = []
    for event in result["damage_events"]:
        if isinstance(event, tuple):
            row = LightRow._make(event)
            rows.append(
                (row.sort_key[0],)
                + tuple(getattr(row, field) for field in SHARED_ROW_FIELDS)
            )
        else:
            rows.append(
                (event.get("time"),)
                + tuple(event.get(field) for field in SHARED_ROW_FIELDS)
            )
    return rows


def test_score_only_fight_parity_mikaels_build():
    """run_fight score-only keeps every scoring field identical for a
    Mikael's build (totals, damage events, resource spent)."""
    params = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": 8,
            "role": "support",
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 0, "W": 0, "E": 0, "R": 0},
            "item_options": {MIKAELS: {"active_seconds": 2.5}},
            "support_target_selections": {f"heal:{MIKAELS_SOURCE}": 0},
            "allies": [_ally("Jinx")],
            "enemies": [_ahri_e()],
        },
        deterministic=True,
    )
    champion = get_champion("Lux")
    item = get_item_by_name(MIKAELS)
    full = run_fight(champion, 18, [item], params, score_only=False)
    score = run_fight(champion, 18, [item], params, score_only=True)
    assert score["total_damage"] == full["total_damage"]
    assert score["resource_spent"] == full["resource_spent"]
    assert _scoring_rows(score) == _scoring_rows(full)


# ---------------------------------------------------------------------------
# 11. Optimizer / BIS / coverage + review issue 48
# ---------------------------------------------------------------------------


def test_mikaels_is_optimizer_eligible_with_purify_review_reason():
    """Mikael's is optimizer-eligible (modeled_state) with the sourced
    review reason "Purify cleanses and heals an ally."; the item is in the
    eligible-legendaries set; the target model is "modeled" (not
    target-blocked)."""
    from src.calculator.item_coverage import target_item_model_coverage

    item = get_item_by_name(MIKAELS)
    coverage = item_probe.attacker_coverage(item)
    assert coverage["optimizer_eligible"] is True
    assert coverage["status"] == "modeled_state"
    assert coverage["calculation_eligible"] is True
    assert {"ally_support", "cleanse", "sustain"} <= set(coverage["outcome_dimensions"])
    # The reviewed sentence is derived from the declaration now, not typed
    # into a per-item table; it still names the mechanic and its recipient.
    assert "Purify" in coverage["reason"]

    assert MIKAELS in {entry["name"] for entry in get_eligible_legendaries()}

    target = target_item_model_coverage(item)
    assert target["status"] == "modeled"
    assert target["calculation_eligible"] is True


def test_no_stale_bis_entry_and_review_issue_48_recorded():
    """BIS carries no stale Mikael's entry, and review issue 48 (ally/team
    item families) is recorded for Mikael's both in the coverage registry
    and in the tracked acceptance docs."""
    from src.calculator.item_coverage import review_issue_refs

    assert review_issue_refs(MIKAELS) == [48]

    bis_source = (REPO / "src" / "calculator" / "bis.py").read_text(encoding="utf-8")
    assert "Mikael" not in bis_source

    tracked = json.loads(
        (REPO / "docs" / "cp47-production-acceptance.json").read_text(encoding="utf-8")
    )
    residual = " ".join(tracked["residual_scope"])
    assert "#48" in residual and "Mikael's Blessing" in residual


# ---------------------------------------------------------------------------
# 12. Determinism + exactly one use per fight
# ---------------------------------------------------------------------------


def test_identical_fights_produce_identical_packets_and_receipts():
    """Two identical app fights deep-equal; exactly one Purify packet and
    one cleanse receipt are emitted (no duplicates)."""
    payload = _main(
        enemies=[_ahri_e()],
        allies=[_ally("Jinx")],
    )
    first = _calculate(payload)
    second = _calculate(payload)
    assert first == second
    assert len(_purify_events(first)) == 1
    assert len(_purify_events(second)) == 1
    assert (
        survival_of(first, "ally:Jinx")["cleanse"]
        == survival_of(second, "ally:Jinx")["cleanse"]
    )
    assert (
        survival_of(first, "main")["cleanse_use"]
        == survival_of(second, "main")["cleanse_use"]
    )


def test_second_activation_in_one_fight_is_denied_use_spent():
    """Exactly one use per fight: a second authored activation is denied
    with the named use_spent reason (cleanse_denied), truncates nothing
    further, and the caster's use receipt records both activations."""
    result = _simulate(
        [_control(1.0, "stun", 2.0)],
        [_purify(1.5, sequence=0), _purify(2.0, sequence=1)],
    )
    target = result["target"]
    first = target["cleanse"]
    assert first["decision"]["reason"] == ""
    assert first["use_consumed"] is True
    # The first activation truncated the interval; the denied second one
    # did not truncate anything further.
    assert [
        (i["kind"], i["start"], i["end"]) for i in target["crowd_control_intervals"]
    ] == [("stun", 1.0, 1.5)]
    assert target["cleanse_denied"] == [
        {"time": pytest.approx(2.0), "reason": "use_spent"}
    ]
    caster = result["caster"]
    use = caster["cleanse_use"]
    assert use["item"] == MIKAELS
    assert use["uses_before"] == 1
    assert use["uses_after"] == 0
    assert use["activations"] == 2
    assert use["cooldown_seconds"] is None
    assert use["cooldown_source_gap"] is True
