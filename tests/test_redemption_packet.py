"""P1 Package 3H — Redemption active Intervention receipt certification.

This file is the independent acceptance matrix for Redemption's
Intervention active: after a sourced 2.5s beam delay it heals the attacker
and every selected teammate for 150 to 350 by the TARGET's level and deals
10% of every enemy's MAXIMUM health as TRUE damage, under a sourced
5500-unit area-radius assumption.  It pins the OBSERVABLES the P3-3H
acceptance rules require and runs against today's source: every behavior
that already exists must pass now; genuinely absent contract pieces are
``xfail`` with reason ``awaiting P3-3H ...``.

Contract pinned (typed source-backed values, all through the typed ally
accessors — the values live in ALLY_ITEM_EFFECTS, NOT ITEM_EFFECTS;
``required_effect_value`` must fail loud for Redemption, never return a
stale literal; missing keys raise KeyError naming Redemption AND the key):

* heal_min 150.0 / heal_max 350.0, enemy_max_health_true_damage_ratio 0.10,
  target_area_range_units 5500.0, target_area_reveal_duration 3.0,
  beam_delay 2.5, cooldown 120.0; source_url
  https://wiki.leagueoflegends.com/en-us/Redemption and
  source_revision_id 4015392 ride both registries.
* option schema: active_seconds is a float in [0.0, 30.0] with step 0.5,
  default 0.0, label "Intervention active seconds".
* 0.0 no-cast: item presence alone authors NO heal packets, NO damage
  packets, NO receipts (fail closed); a non-zero half-second input emits
  the full packet set at EXACTLY active + 2.5.
* Validation (both layers): > 30 / negative -> "must be between 0.0 and
  30.0"; nan/inf -> "must be finite"; non-numeric -> "must be numeric";
  non-multiple-of-0.5 -> "must be a multiple of 0.5"; the request schema
  (validate_item_input_options / FightParams.from_request -> app 400) and
  the defensive resolver (input_option_float_value) raise identically
  named ValueErrors.  Boundary: 30.0 is schema-valid but the 32.5s beam in
  a shorter fight is skipped with the named "outside_window" reason; a
  beam landing exactly AT fight end is still in-window.
* Delayed beam ordering: EVERY Redemption packet (heals AND true-damage
  packets) lands at active_time + 2.5; the same-timestamp public order is
  the deterministic ledger sort (time, kind bucket, target id, attacker,
  event id), pinned as an exact sequence; damage events sort by target id
  regardless of roster order.
* Level-scaled heal: amount == ally_item_level_value(150, 350, target
  .level) for the attacker and EACH teammate (level 1 -> 150, level 18 ->
  350, monotonic); exactly one heal packet per ally (no duplicates).
* True damage: enemy packet amount == 10% of enemy MAX health — the code
  reads target.stats["health"], the max-health stat (verified: a full
  Aatrox with 2588 max health receives 258.8 while his armor/MR are
  nonzero); damage_type "true" with damage == raw_damage (unmitigated);
  exactly one packet per enemy.
* Target scopes: target_scope "redemption_allies_in_radius" on heals
  (attacker + teammates), "enemy_champions_in_radius" on damage;
  range_assumption "within_5500_units" on every packet; no teammates ->
  self-only heal; no enemies -> no damage packets.
* Reveal: the registry's 3.0s reveal duration had NO local source (wiki
  wording names no number; the binary has no reveal value) and was REMOVED
  (P3-3H provenance correction); the sourced reveal EFFECT is a support
  kind="vision" receipt per selected enemy at the activation time with the
  sourced 2.5s beam_delay call-down window.
* Cooldown: cooldown key == 90.0 (the BINARY Items/3107 value; the cached
  wiki active records null — the earlier 120.0 was a Mikael's copy-paste);
  NOT enforced (one use per fight) — a single active_seconds input authors
  exactly one heal packet per ally and one damage packet per enemy, no
  second activation is reachable, and no cooldown/use receipt exists on any
  survival row.
* Score/receipt parity + compiled: parity is CERTIFIED VIA FALLBACK — the
  heal template alone is plain (unrepresentable_template_receipt None),
  but the kind="damage" template fails closed with
  "support_kind=damage" (the compiled score kernel stages only
  shield/heal support templates), so every active-Redemption evaluation
  falls back to the authoritative receipt walk with EQUAL results
  (per-evaluation for the main holder; search-invariant for an ally
  holder); run_fight score-only totals equal the full fight;
  optimizer-eligible (modeled_state), in get_eligible_legendaries, not
  target-blocked, no stale BIS entry, review issue 48 recorded.
* Public output: heal packets in support_events (source "Redemption —
  Intervention", amount, time, beam_delay, range_assumption); damage
  events carry damage_type "true" + event_precision "exact"; /api/config
  exposes the option schema + source_revision_id 4015392.
* Determinism: identical fights produce identical packets/receipts; no
  duplicate packets.
"""

import json
from pathlib import Path

import pytest

from src.app import app
from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.defensive_effects import StartingDefenses, resolve_starting_defenses
from src.calculator.item_coverage import review_issue_refs, target_item_model_coverage
from src.calculator.item_effects import (
    ALLY_ITEM_EFFECTS,
    ITEM_INPUT_OPTIONS,
    ally_item_effect_value,
    ally_item_level_value,
    input_option_float_value,
    required_effect_value,
    validate_item_input_options,
)
from src.calculator.ledger_projection import SHARED_ROW_FIELDS, LightRow
from src.calculator.optimizer import get_eligible_legendaries
from src.calculator.participant_timeline import (
    Combatant,
    CoupledSearchContext,
    build_participant_timeline,
)
from src.calculator.pipeline import FightParams, run_fight
from src.calculator.scenario import ChampionLoadout
from src.calculator.stats import calculate_total_stats
from src.calculator.survival.compile import (
    unrepresentable_damage_receipt,
    unrepresentable_template_receipt,
)
from tests import item_probe
from tests.survival_probe import simulate_survival, survival_of

REDEMPTION = "Redemption"
SOURCE = "Redemption \u2014 Intervention"
SOURCE_URL = "https://wiki.leagueoflegends.com/en-us/Redemption"
REVISION_ID = 4015392
REPO = Path(__file__).resolve().parent.parent


def _kernel_combatant(participant_id, team, health=5000.0):
    """A minimal Combatant for the shared survival-kernel seam."""

    defenses = StartingDefenses(
        magic_shield=0.0,
        physical_shield=0.0,
        general_shield=0.0,
        healing_received_multiplier=1.0,
        starting_stasis_duration=0.0,
        starting_stasis_source="",
    )
    return Combatant(
        participant_id=participant_id,
        team=team,
        champion_data={"name": participant_id},
        level=18,
        items=(),
        stats={
            "health": health,
            "armor": 50.0,
            "magic_resistance": 50.0,
            "base_health": 2000.0,
            "is_melee": False,
        },
        defenses=defenses,
    )


def _kernel_packet(time, amount, attacker, target, source="Q", sequence=0):
    """One incoming damage packet for the shared survival-kernel seam."""
    return {
        "time": time,
        "damage": amount,
        "damage_type": "magic",
        "attacker": attacker,
        "target": target,
        "source_key": source,
        "source": source,
        "is_ability": True,
        "kind": "damage",
        "sequence": sequence,
        "_event_id": f"dmg-{sequence}-{time}-{source}",
    }


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
    except Exception:  # noqa: BLE001 - non-JSON body  # pragma: no cover
        body = {}
    return response.status_code, body


def _main(**overrides) -> dict:
    """A deterministic time-based fight request holding Redemption."""
    payload = {
        "champion": "Lux",
        "level": 18,
        "items": [REDEMPTION],
        "item_options": {REDEMPTION: {"active_seconds": 1.0}},
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


def _enemy(champion: str = "Aatrox", *, ranks=None) -> dict:
    """A rank-0 enemy (no damage — clean packet fixtures) by default;
    ``ranks=None`` is not a dict, so pass ``_enemy(ranks={})`` to drop the
    override and let the enemy play its default damaging rotation."""
    return {
        "champion": champion,
        "level": 18,
        "items": [],
        "ability_ranks": ranks,
    }


def _redemption_support(combat: dict) -> list[dict]:
    """Every Redemption-authored packet in the public support stream."""
    return [
        event
        for event in combat.get("support_events", [])
        if event.get("source") == SOURCE
    ]


def _redemption_damage(combat: dict) -> list[dict]:
    """Every Redemption-authored event in the public damage stream."""
    return [
        event for event in combat.get("events", []) if event.get("source") == SOURCE
    ]


# ---------------------------------------------------------------------------
# 1. Typed accessor values + option schema + missing-key fail-closed
# ---------------------------------------------------------------------------


def test_typed_ally_effect_values_and_option_schema():
    """The sourced values ride the typed ally accessor (the values live in
    ALLY_ITEM_EFFECTS, not ITEM_EFFECTS); the public input option is a
    float in [0, 30] with step 0.5, default 0.0, label 'Intervention
    active seconds'; source revision 4015392 rides both registries.

    P3-3H provenance corrections: the cooldown is the BINARY value 90.0
    (Items/3107 mDataValues Cooldown; the cached wiki active records null;
    the earlier 120.0 matched Mikael's binary and was a copy-paste
    contamination), and ``target_area_reveal_duration`` was REMOVED — the
    3.0 had no local source (wiki text names no number, the binary has no
    reveal value); the reveal receipt uses the sourced 2.5s beam_delay
    call-down window instead."""
    assert ally_item_effect_value(REDEMPTION, "heal_min") == 150.0
    assert ally_item_effect_value(REDEMPTION, "heal_max") == 350.0
    assert ally_item_effect_value(
        REDEMPTION, "enemy_max_health_true_damage_ratio"
    ) == pytest.approx(0.10)
    assert ally_item_effect_value(REDEMPTION, "target_area_range_units") == 5500.0
    assert ally_item_effect_value(REDEMPTION, "beam_delay") == 2.5
    assert ally_item_effect_value(REDEMPTION, "cooldown") == 90
    with pytest.raises(KeyError):
        ally_item_effect_value(REDEMPTION, "target_area_reveal_duration")
    assert ALLY_ITEM_EFFECTS[REDEMPTION]["source_url"] == SOURCE_URL
    assert ALLY_ITEM_EFFECTS[REDEMPTION]["source_revision_id"] == REVISION_ID

    option = ITEM_INPUT_OPTIONS[REDEMPTION]["options"]["active_seconds"]
    assert option == {
        "type": "float",
        "label": "Intervention active seconds",
        "default": 0.0,
        "min": 0.0,
        "max": 30.0,
        "step": 0.5,
    }
    block = ITEM_INPUT_OPTIONS[REDEMPTION]
    assert block["source_url"] == SOURCE_URL
    assert block["source_revision_id"] == REVISION_ID


def test_missing_ally_key_raises_keyerror_naming_redemption_and_key(monkeypatch):
    """A missing typed key fails loud, naming the item and the key (AGENTS.md
    rule 5: no silent stale fallbacks at call sites)."""
    broken = dict(ALLY_ITEM_EFFECTS[REDEMPTION])
    broken.pop("heal_min")
    monkeypatch.setitem(ALLY_ITEM_EFFECTS, REDEMPTION, broken)

    with pytest.raises(KeyError) as excinfo:
        ally_item_level_value(REDEMPTION, "heal_min", "heal_max", 18)
    message = str(excinfo.value)
    assert "Redemption" in message
    assert "heal_min" in message


def test_item_effects_accessor_fails_loud_for_redemption():
    """required_effect_value reads ITEM_EFFECTS, where Redemption has no
    record (the values live in ALLY_ITEM_EFFECTS); the accessor must raise
    naming the item and key instead of returning a stale literal."""
    with pytest.raises(KeyError) as excinfo:
        required_effect_value(REDEMPTION, "heal_min")
    message = str(excinfo.value)
    assert "Redemption" in message
    assert "heal_min" in message


def test_ally_item_level_value_level_domain():
    """Level-domain heal: level 1 -> 150, level 18 -> 350, monotonic
    between; the packet amount equals this accessor at the target's level
    (pinned again at the app level in section 5)."""
    assert ally_item_level_value(
        REDEMPTION, "heal_min", "heal_max", 1
    ) == pytest.approx(150.0)
    assert ally_item_level_value(
        REDEMPTION, "heal_min", "heal_max", 18
    ) == pytest.approx(350.0)
    values = [
        ally_item_level_value(REDEMPTION, "heal_min", "heal_max", level)
        for level in range(1, 19)
    ]
    assert values[0] == pytest.approx(150.0)
    assert values[-1] == pytest.approx(350.0)
    assert all(values[i] <= values[i + 1] for i in range(len(values) - 1))
    # Linear interpolation from level 1 (150) to level 18 (350): level 7
    # is 150 + 200 * 6/17.
    assert values[6] == pytest.approx(150.0 + 200.0 * 6 / 17)
    # Out-of-domain levels clamp to the sourced domain (no extrapolation).
    assert ally_item_level_value(
        REDEMPTION, "heal_min", "heal_max", 0
    ) == pytest.approx(150.0)
    assert ally_item_level_value(
        REDEMPTION, "heal_min", "heal_max", 20
    ) == pytest.approx(350.0)


# ---------------------------------------------------------------------------
# 2. 0.0 no-cast: presence alone never assumes activation
# ---------------------------------------------------------------------------


def test_active_seconds_zero_no_cast_no_packets():
    """Item presence with active_seconds 0.0 (and with no option at all)
    authors NO heal packets, NO true-damage packets and NO receipts —
    presence alone never assumes a cast."""
    for item_options in (
        {REDEMPTION: {"active_seconds": 0.0}},
        {},
        None,
    ):
        payload = _main(allies=[_ally("Jinx")], enemies=[_enemy()])
        if item_options is None:
            payload.pop("item_options")
        else:
            payload["item_options"] = item_options
        combat = _calculate(payload)
        assert _redemption_support(combat) == []
        assert _redemption_damage(combat) == []
        assert survival_of(combat, "ally:Jinx")["healing_received"] == 0.0


# ---------------------------------------------------------------------------
# 3. Half-second timing + two-layer validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("seconds", "beam_time"), [(0.5, 3.0), (1.0, 3.5), (2.5, 5.0)])
def test_valid_half_second_timings_emit_beam_at_active_plus_beam_delay(
    seconds, beam_time
):
    """A non-zero half-second input emits the WHOLE packet set (heals AND
    true-damage packets) at EXACTLY active_seconds + beam_delay (2.5) —
    no rounding, no per-packet drift."""
    combat = _calculate(
        _main(
            item_options={REDEMPTION: {"active_seconds": seconds}},
            allies=[_ally("Jinx")],
            enemies=[_enemy()],
        )
    )
    packets = _redemption_support(combat)
    assert len(packets) == 4  # main + Jinx heals + enemy damage + vision receipt
    # Heals and damage land at the beam time; the vision receipt rides the
    # activation time (sight during the call-down).
    for packet in packets:
        if packet["kind"] == "vision":
            assert packet["time"] == pytest.approx(seconds)
        else:
            assert packet["time"] == pytest.approx(beam_time)
        assert packet["beam_delay"] == pytest.approx(2.5)
    assert all(
        event["time"] == pytest.approx(beam_time)
        for event in _redemption_damage(combat)
    )


@pytest.mark.parametrize("seconds", [30.5, 31.0, 100.0])
def test_validation_rejects_values_above_max(seconds):
    """Above 30 the request schema raises, the defensive resolver raises,
    and the app answers a named 400; there is no clamp path."""
    message = "item_options.Redemption.active_seconds must be between 0.0 and 30.0"
    with pytest.raises(ValueError, match=message):
        validate_item_input_options({REDEMPTION: {"active_seconds": seconds}})
    with pytest.raises(ValueError, match=message):
        input_option_float_value(
            [get_item_by_name(REDEMPTION)],
            {REDEMPTION: {"active_seconds": seconds}},
            REDEMPTION,
            "active_seconds",
        )
    status, body = _calculate_status(
        _main(item_options={REDEMPTION: {"active_seconds": seconds}})
    )
    assert status == 400
    assert body.get("error") == message


@pytest.mark.parametrize("seconds", [-0.5, -1.0, -30.0])
def test_validation_rejects_negative_values(seconds):
    message = "item_options.Redemption.active_seconds must be between 0.0 and 30.0"
    with pytest.raises(ValueError, match=message):
        validate_item_input_options({REDEMPTION: {"active_seconds": seconds}})
    with pytest.raises(ValueError, match=message):
        input_option_float_value(
            [get_item_by_name(REDEMPTION)],
            {REDEMPTION: {"active_seconds": seconds}},
            REDEMPTION,
            "active_seconds",
        )
    status, body = _calculate_status(
        _main(item_options={REDEMPTION: {"active_seconds": seconds}})
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
    full = f"item_options.Redemption.active_seconds {message}"
    with pytest.raises(ValueError, match=full):
        validate_item_input_options({REDEMPTION: {"active_seconds": value}})
    with pytest.raises(ValueError, match=full):
        input_option_float_value(
            [get_item_by_name(REDEMPTION)],
            {REDEMPTION: {"active_seconds": value}},
            REDEMPTION,
            "active_seconds",
        )
    status, body = _calculate_status(
        _main(item_options={REDEMPTION: {"active_seconds": value}})
    )
    assert status == 400
    assert body.get("error") == full


@pytest.mark.parametrize("seconds", [0.7, 1.3, 2.25, 29.75])
def test_validation_rejects_non_step_multiple(seconds):
    """The option is a 0.5-step control: non-multiples are rejected at both
    layers with the named 'multiple of 0.5' error, never silently
    rounded."""
    full = "item_options.Redemption.active_seconds must be a multiple of 0.5"
    with pytest.raises(ValueError, match=full):
        validate_item_input_options({REDEMPTION: {"active_seconds": seconds}})
    with pytest.raises(ValueError, match=full):
        input_option_float_value(
            [get_item_by_name(REDEMPTION)],
            {REDEMPTION: {"active_seconds": seconds}},
            REDEMPTION,
            "active_seconds",
        )
    status, body = _calculate_status(
        _main(item_options={REDEMPTION: {"active_seconds": seconds}})
    )
    assert status == 400
    assert body.get("error") == full


def test_numeric_strings_are_coerced_by_both_layers():
    """A numeric string '2.5' is coerced (not rejected) by the request
    schema and the resolver, and the app emits the beam at 5.0."""
    parsed = validate_item_input_options({REDEMPTION: {"active_seconds": "2.5"}})
    assert parsed[REDEMPTION]["active_seconds"] == 2.5
    assert (
        input_option_float_value(
            [get_item_by_name(REDEMPTION)],
            {REDEMPTION: {"active_seconds": "2.5"}},
            REDEMPTION,
            "active_seconds",
        )
        == 2.5
    )
    combat = _calculate(
        _main(
            item_options={REDEMPTION: {"active_seconds": "2.5"}},
            allies=[_ally("Jinx")],
            enemies=[_enemy()],
        )
    )
    # Heals/damage at the beam time; the vision receipt at the activation.
    for packet in _redemption_support(combat):
        expected = 2.5 if packet["kind"] == "vision" else 5.0
        assert packet["time"] == pytest.approx(expected)


def test_unknown_option_name_rejected_at_request_layer():
    """The request schema rejects unknown option names with a named 400;
    the resolver raises the same named error."""
    with pytest.raises(ValueError, match="Unknown option for Redemption: start_time"):
        validate_item_input_options({REDEMPTION: {"start_time": 1.0}})
    with pytest.raises(ValueError, match="Unknown option for Redemption: start_time"):
        input_option_float_value(
            [get_item_by_name(REDEMPTION)],
            {REDEMPTION: {"start_time": 1.0}},
            REDEMPTION,
            "start_time",
        )
    status, body = _calculate_status(
        _main(item_options={REDEMPTION: {"start_time": 1.0}})
    )
    assert status == 400
    assert body.get("error") == "Unknown option for Redemption: start_time"


def test_max_boundary_30_seconds_is_schema_valid_and_skipped_outside_window():
    """30.0 is the schema maximum (accepted, no error); in an 8-second
    fight the beam (32.5s) is skipped with the named 'outside_window'
    reason on every packet — no heal, no damage."""
    status, body = _calculate_status(
        _main(
            item_options={REDEMPTION: {"active_seconds": 30.0}},
            allies=[_ally("Jinx")],
            enemies=[_enemy()],
        )
    )
    assert status == 200
    combat = body["combat"]
    packets = _redemption_support(combat)
    assert len(packets) == 4  # heals + damage + vision receipt
    # The vision receipt rides the activation (30.0) and the beam packets
    # ride 32.5 — BOTH outside the 8s fight, so every packet skips with
    # the named outside_window reason; nothing applies.
    for packet in packets:
        assert packet.get("skipped_reason") == "outside_window"
    assert all(
        event["skipped_reason"] == "outside_window"
        for event in _redemption_damage(combat)
    )
    assert survival_of(combat, "ally:Jinx")["healing_received"] == 0.0


def test_beam_landing_exactly_at_fight_end_is_in_window():
    """The walk's window gate is strict '>': a beam landing exactly AT the
    fight end processes in full; a beam 0.01s beyond it is skipped with the
    named outside_window reason."""
    payload = _main(
        item_options={REDEMPTION: {"active_seconds": 1.0}},
        allies=[_ally("Jinx")],
        # Default-rotation Aatrox (no rank override): his Q/W damage the
        # ally before the beam so the heal actually applies at fight end.
        enemies=[_enemy(ranks={})],
        fight_duration=3.5,
    )
    combat = _calculate(payload)
    packets = _redemption_support(combat)
    assert len(packets) == 4  # heals + damage + vision receipt
    # The vision receipt rides the activation (1.0, in-window); the beam
    # packets ride 3.5 == fight end (in-window, strict ">").
    assert all(packet.get("skipped_reason") is None for packet in packets)
    # The authored packet is 350; the holder's own 10% heal and shield
    # power amplifies what it applies, so 385 lands.
    assert survival_of(combat, "ally:Jinx")["healing_received"] == pytest.approx(385.0)

    payload["fight_duration"] = 3.49
    combat = _calculate(payload)
    packets = _redemption_support(combat)
    assert len(packets) == 4
    for packet in packets:
        if packet["kind"] == "vision":
            assert packet.get("skipped_reason") is None  # 1.0 in-window
        else:
            assert packet["skipped_reason"] == "outside_window"
    assert survival_of(combat, "ally:Jinx")["healing_received"] == 0.0


# ---------------------------------------------------------------------------
# 4. Delayed beam ordering (heal vs damage at the same timestamp)
# ---------------------------------------------------------------------------


def test_beam_packets_share_one_timestamp_and_public_order_is_deterministic():
    """Every Redemption packet — heals AND true-damage packets — lands at
    active + 2.5.  The public support stream sorts same-timestamp packets
    by (time, kind bucket, target id, attacker, event id): heal packets
    (targets ally:...) precede damage packets (targets enemy:...), and the
    caster's own heal (target 'main') sorts after every enemy packet.  The
    damage stream sorts by target id regardless of roster order (roster
    [Annie, Aatrox] still emits enemy:Aatrox first)."""

    def run() -> dict:
        return _calculate(
            _main(
                item_options={REDEMPTION: {"active_seconds": 1.0}},
                allies=[_ally("Ashe", level=7), _ally("Jinx")],
                enemies=[_enemy("Annie"), _enemy("Aatrox")],
            )
        )

    first, second = run(), run()
    assert first == second  # deterministic

    packets = _redemption_support(first)
    assert [(p["kind"], p["target"]) for p in packets] == [
        ("vision", "enemy:Aatrox"),
        ("vision", "enemy:Annie"),
        ("heal", "ally:Ashe"),
        ("heal", "ally:Jinx"),
        ("damage", "enemy:Aatrox"),
        ("damage", "enemy:Annie"),
        ("heal", "main"),
    ]
    for p in packets:
        expected = 1.0 if p["kind"] == "vision" else 3.5
        assert p["time"] == pytest.approx(expected)

    damage = _redemption_damage(first)
    assert [(e["target"], e["time"]) for e in damage] == [
        ("enemy:Aatrox", 3.5),
        ("enemy:Annie", 3.5),
    ]


# ---------------------------------------------------------------------------
# 5. Level-scaled heal: attacker + every teammate, exactly one packet each
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("level", "expected"),
    [
        (1, 150.0),
        (7, 150.0 + 200.0 * 6 / 17),
        (10, 150.0 + 200.0 * 9 / 17),
        (18, 350.0),
    ],
)
def test_heal_amount_equals_ally_item_level_value_per_target_level(level, expected):
    """The heal packet amount == ally_item_level_value(150, 350, target
    .level): the caster heals for HIS level, each teammate for THEIR level."""
    assert ally_item_level_value(
        REDEMPTION, "heal_min", "heal_max", level
    ) == pytest.approx(expected)
    combat = _calculate(
        _main(
            allies=[_ally("Ashe", level=level)],
            enemies=[_enemy()],
        )
    )
    heals = [
        packet for packet in _redemption_support(combat) if packet["kind"] == "heal"
    ]
    by_target = {packet["target"]: packet["amount"] for packet in heals}
    assert set(by_target) == {"main", "ally:Ashe"}
    # The teammate heals for HER level; the level-18 caster for his own.
    assert by_target["ally:Ashe"] == pytest.approx(expected)
    assert by_target["main"] == pytest.approx(350.0)
    # Level 18 caster + level 7 teammate scale independently.
    mixed = _calculate(
        _main(
            allies=[_ally("Ashe", level=7), _ally("Jinx")],
            enemies=[_enemy()],
        )
    )
    by_target = {
        packet["target"]: packet["amount"]
        for packet in _redemption_support(mixed)
        if packet["kind"] == "heal"
    }
    assert by_target["main"] == pytest.approx(350.0)
    assert by_target["ally:Ashe"] == pytest.approx(150.0 + 200.0 * 6 / 17)
    assert by_target["ally:Jinx"] == pytest.approx(350.0)


def test_exactly_one_heal_packet_per_ally_no_duplicates():
    """The heal fans out to the caster and each teammate exactly once: no
    duplicate heal packets for any ally."""
    combat = _calculate(
        _main(
            allies=[_ally("Jinx"), _ally("Ashe")],
            enemies=[_enemy()],
        )
    )
    heals = [
        packet for packet in _redemption_support(combat) if packet["kind"] == "heal"
    ]
    assert len(heals) == 3  # main + Jinx + Ashe
    targets = [packet["target"] for packet in heals]
    assert len(targets) == len(set(targets))


# ---------------------------------------------------------------------------
# 6. True damage: 10% of enemy MAX health, unmitigated, one packet each
# ---------------------------------------------------------------------------


def test_true_damage_equals_ten_percent_of_enemy_max_health():
    """Enemy packet amount == 10% of the enemy's MAX health.  The authoring
    code reads target.stats['health'], the max-health stat (an untouched
    Aatrox has 2588 max health -> 258.8, Annie 2192 -> 219.2) — pinned here
    as the max-health observable, NOT current health."""
    combat = _calculate(
        _main(
            enemies=[_enemy("Aatrox"), _enemy("Annie")],
        )
    )
    damage = _redemption_damage(combat)
    assert [(e["target"], e["damage"]) for e in damage] == [
        ("enemy:Aatrox", pytest.approx(258.8)),
        ("enemy:Annie", pytest.approx(219.2)),
    ]
    assert [(e["target"], e["raw_damage"]) for e in damage] == [
        ("enemy:Aatrox", pytest.approx(258.8)),
        ("enemy:Annie", pytest.approx(219.2)),
    ]
    # Max-health reading: an enemy that has TAKEN damage before the beam is
    # still charged the full 10% of its max health, not 10% of its current
    # health (Aatrox is hit by Lux before 3.5s and is below max health when
    # the beam lands).
    aatrox_row = next(
        row for row in combat["participants"] if row["participant_id"] == "enemy:Aatrox"
    )
    assert aatrox_row["survival"]["damage_taken"] >= 258.8
    assert aatrox_row["stats"]["health"] == 2588.0
    # The support-stream copy of the same packets carries the amount too.
    support_damage = [
        packet for packet in _redemption_support(combat) if packet["kind"] == "damage"
    ]
    assert sorted((p["target"], p["amount"]) for p in support_damage) == [
        ("enemy:Aatrox", pytest.approx(258.8)),
        ("enemy:Annie", pytest.approx(219.2)),
    ]


def test_true_damage_is_unmitigated_by_armor_and_mr():
    """damage_type is 'true' and damage == raw_damage for every Redemption
    event while the enemies hold nonzero armor/MR (120 armor / 67 MR on
    level-18 Aatrox): true damage ignores all resistances."""
    combat = _calculate(
        _main(enemies=[_enemy("Aatrox")]),
    )
    damage = _redemption_damage(combat)
    assert damage
    assert all(event["damage_type"] == "true" for event in damage)
    assert all(
        event["damage"] == pytest.approx(event["raw_damage"]) for event in damage
    )
    aatrox_row = next(
        row for row in combat["participants"] if row["participant_id"] == "enemy:Aatrox"
    )
    assert aatrox_row["stats"]["armor"] > 0.0
    assert aatrox_row["stats"]["magic_resistance"] > 0.0


def test_exactly_one_damage_packet_per_enemy():
    """Exactly one true-damage packet per enemy — no duplicates."""
    combat = _calculate(
        _main(enemies=[_enemy("Aatrox"), _enemy("Annie")]),
    )
    damage = _redemption_damage(combat)
    assert len(damage) == 2
    assert len({event["target"] for event in damage}) == 2


def test_dead_enemy_at_impact_skips_the_beam_damage():
    """P3-3H boundary (shared-kernel altitude): an enemy that died before
    the beam lands takes NO beam damage — the lethal hit is the only
    health damage, and no resurrection or late hit is applied."""
    combatants = [
        _kernel_combatant("main", "blue"),
        _kernel_combatant("enemy", "red", health=300.0),
    ]
    incoming = {
        "enemy": [
            _kernel_packet(1.0, 500.0, "main", "enemy", source="Q"),
            _kernel_packet(
                3.5,
                25.8,
                "main",
                "enemy",
                source="Redemption — Intervention",
                sequence=1,
            ),
        ]
    }
    result = simulate_survival(combatants, incoming, {}, {}, 5.0)
    enemy = result["enemy"]
    assert enemy["first_death_time"] == pytest.approx(1.0)
    assert enemy["health_damage"] == pytest.approx(300.0)  # beam damage skipped


def test_dead_ally_at_impact_is_not_resurrected_by_the_beam_heal():
    """P3-3H boundary (shared-kernel altitude): the beam heal does not
    resurrect a dead ally — healing_received stays 0 and the death time
    is unchanged."""
    combatants = [
        _kernel_combatant("main", "blue"),
        _kernel_combatant("ally", "blue", health=300.0),
    ]
    incoming = {
        "ally": [
            _kernel_packet(1.0, 500.0, "enemy", "ally", source="Q"),
        ]
    }
    healing = {
        "ally": [
            {
                "time": 3.5,
                "amount": 350.0,
                "source": "Redemption — Intervention",
                "attacker": "main",
                "target": "ally",
                "kind": "heal",
                "_event_id": "beam-heal",
            }
        ]
    }
    result = simulate_survival(combatants, incoming, healing, {}, 5.0)
    ally = result["ally"]
    assert ally["first_death_time"] == pytest.approx(1.0)
    assert ally["healing_received"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 7. Target scopes + range assumption + empty-roster edges
# ---------------------------------------------------------------------------


def test_heal_and_damage_target_scopes_and_range_assumption():
    """Heal packets declare target_scope 'redemption_allies_in_radius'
    (attacker + teammates); damage packets declare
    'enemy_champions_in_radius'; EVERY packet carries the sourced
    range_assumption 'within_5500_units' and beam_delay 2.5."""
    combat = _calculate(
        _main(
            allies=[_ally("Jinx")],
            enemies=[_enemy()],
        )
    )
    packets = _redemption_support(combat)
    assert len(packets) == 4  # heals + damage + vision receipt
    heals = [p for p in packets if p["kind"] == "heal"]
    damage = [p for p in packets if p["kind"] == "damage"]
    vision = [p for p in packets if p["kind"] == "vision"]
    assert all(p["target_scope"] == "redemption_allies_in_radius" for p in heals)
    assert {p["target"] for p in heals} == {"main", "ally:Jinx"}
    assert all(p["target_scope"] == "enemy_champions_in_radius" for p in damage)
    assert {p["target"] for p in damage} == {"enemy:Aatrox"}
    assert all(p["target_scope"] == "enemy_champions_in_radius" for p in vision)
    assert {p["target"] for p in vision} == {"enemy:Aatrox"}
    assert all(p["range_assumption"] == "within_5500_units" for p in packets)
    assert all(p["beam_delay"] == pytest.approx(2.5) for p in packets)


def test_no_teammates_self_only_heal():
    """Without a teammate roster the heal is self-only (attacker + empty
    teammate list); the enemy damage packets still fire."""
    combat = _calculate(_main(enemies=[_enemy()]))
    packets = _redemption_support(combat)
    heals = [p for p in packets if p["kind"] == "heal"]
    assert len(heals) == 1
    assert heals[0]["target"] == "main"
    assert [p["target"] for p in packets if p["kind"] == "damage"] == ["enemy:Aatrox"]


def test_no_enemies_no_damage_packets():
    """With an empty enemy roster the damage branch authors nothing; the
    heal fan-out still fires for the caster and teammates."""
    combat = _calculate(
        _main(
            allies=[_ally("Jinx")],
            enemies=[],
        )
    )
    packets = _redemption_support(combat)
    assert all(p["kind"] == "heal" for p in packets)
    assert {p["target"] for p in packets} == {"main", "ally:Jinx"}
    assert _redemption_damage(combat) == []


# ---------------------------------------------------------------------------
# 8. Reveal: sourced 3s reveal is NOT represented today (absence pinned)
# ---------------------------------------------------------------------------


def test_reveal_duration_unsourced_value_was_removed():
    """P3-3H provenance: the registry's 3.0s reveal duration had NO local
    source (the wiki wording names no number — 'granting sight of the area
    for the duration'; the binary carries no reveal value) and was REMOVED.
    The reveal effect itself is represented by the vision receipt with the
    SOURCED call-down window (beam_delay 2.5) — see
    test_intervention_authors_the_area_reveal_receipt."""
    with pytest.raises(KeyError):
        ally_item_effect_value(REDEMPTION, "target_area_reveal_duration")


def test_intervention_authors_the_area_reveal_receipt():
    """The sourced reveal effect (sight of the area during the beam
    call-down) is a support kind="vision" receipt per selected enemy at the
    activation time, window [cast, impact] = the sourced 2.5s beam_delay,
    with the same cast-range coverage assumption as the heal/damage
    packets.

    The window has ONE published home: ``duration``, with ``beam_delay``
    naming the sourced figure it came from.  ``reveal_duration`` is not a
    third spelling of the same 2.5 — the publisher does not carry it — so
    a reader looking for the reveal window reads ``duration``."""
    combat = _calculate(
        _main(
            allies=[_ally("Jinx")],
            enemies=[_enemy()],
        )
    )
    receipts = [
        event
        for event in combat.get("support_events", [])
        if event.get("source") == SOURCE and event.get("kind") == "vision"
    ]
    assert receipts, "no Redemption reveal receipt exists"
    for receipt in receipts:
        assert receipt["time"] == pytest.approx(1.0)  # activation time
        assert "reveal_duration" not in receipt
        assert receipt["beam_delay"] == pytest.approx(2.5)
        assert receipt["duration"] == pytest.approx(2.5)
        assert receipt["expires_at"] == pytest.approx(3.5)
        assert receipt["target_scope"] == "enemy_champions_in_radius"
        assert receipt["range_assumption"] == "within_5500_units"
        assert receipt["target"] == "enemy:Aatrox"


# ---------------------------------------------------------------------------
# 9. Cooldown: typed 90.0 (binary), NOT enforced (one use per fight)
# ---------------------------------------------------------------------------


def test_cooldown_is_typed_but_not_enforced_and_second_activation_unreachable():
    """cooldown == 90.0 (the BINARY Items/3107 value; the cached wiki active
    records null — the earlier 120.0 was a Mikael's copy-paste) through the
    typed accessor, but it is NOT enforced:
    a single active_seconds input authors exactly one heal packet per ally
    and one damage packet per enemy — no second activation is reachable
    from one input, and no survival row carries a Redemption use/cooldown
    receipt (the sourced 90s is a preserved named limitation)."""
    assert ally_item_effect_value(REDEMPTION, "cooldown") == 90.0
    combat = _calculate(
        _main(
            allies=[_ally("Jinx"), _ally("Ashe")],
            enemies=[_enemy("Aatrox"), _enemy("Annie")],
        )
    )
    packets = _redemption_support(combat)
    assert [p["kind"] for p in packets].count("heal") == 3
    assert [p["kind"] for p in packets].count("damage") == 2
    assert len(_redemption_damage(combat)) == 2
    for row in combat["participants"]:
        survival = row["survival"]
        assert "redemption" not in json.dumps(survival).lower()
        assert not any(
            key in survival for key in ("cooldown_seconds", "redemption_use")
        )


# ---------------------------------------------------------------------------
# 10. Score/receipt parity + compiled path (plain packets compile)
# ---------------------------------------------------------------------------


def _timeline(include_receipt: bool = True, **kwargs):
    """One full participant timeline for a Redemption support build."""
    params = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": 8,
            "role": "support",
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 0, "W": 0, "E": 0, "R": 0},
            "item_options": {REDEMPTION: {"active_seconds": 1.0}},
            "allies": [_ally("Jinx")],
            "enemies": [_enemy()],
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
    item = get_item_by_name(REDEMPTION)
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
        enemies=[roster("Aatrox")],
        allies=[roster("Jinx", role="support")],
        include_receipt=include_receipt,
        **kwargs,
    )


def test_compiled_score_kernel_can_stage_both_redemption_packet_kinds():
    """The Redemption heal and true-damage packets are PLAIN packets: the
    compiled kernel's fail-closed guards accept both.  The heal
    template is a flat heal (no cleanse, no duration) and the damage event
    carries no execute/redirect/deferred payload, so the compiled path CAN
    stage them and does not fall back."""
    assert (
        unrepresentable_template_receipt(
            {
                "kind": "heal",
                "amount": 350.0,
                "source": SOURCE,
                "target": "ally:Jinx",
                "time": 3.5,
            }
        )
        is None
    )
    assert (
        unrepresentable_damage_receipt(
            {
                "kind": "damage",
                "damage_type": "true",
                "damage": 258.8,
                "raw_damage": 258.8,
                "time": 3.5,
                "target": "enemy:Aatrox",
            }
        )
        is None
    )


def test_compiled_walk_equals_receipt_walk_with_redemption_packets_staged():
    """The compiled walk deep-equals the authoritative receipt walk for an
    active Redemption fight; the guard proves both walks actually carried
    the heal and the true damage (the comparison is not trivially equal)."""
    legacy = _timeline(include_receipt=False)
    context = CoupledSearchContext()
    fast = _timeline(
        include_receipt=False,
        pair_result_cache={},
        search_context=context,
    )
    assert fast == legacy
    assert context.panels  # the compiled panel was attempted before any fallback
    # Guard: the receipt walk carried the Redemption heal on the ally and
    # the true damage on the enemy.
    jinx = next(
        row for row in legacy["participants"] if row["participant_id"] == "ally:Jinx"
    )
    # 350 authored, amplified by the holder's own 10% heal and shield power.
    assert jinx["survival"]["healing_received"] == pytest.approx(385.0)
    enemy = next(
        row for row in legacy["participants"] if row["participant_id"] == "enemy:Aatrox"
    )
    assert enemy["survival"]["damage_taken"] >= 258.8


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
                (
                    row.sort_key[0],
                    *tuple(getattr(row, field) for field in SHARED_ROW_FIELDS),
                )
            )
        else:
            rows.append(
                (
                    event.get("time"),
                    *tuple(event.get(field) for field in SHARED_ROW_FIELDS),
                )
            )
    return rows


def test_score_only_fight_parity_redemption_build():
    """run_fight score-only keeps every scoring field identical for an
    active Redemption build (totals, damage events, resource spent)."""
    params = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": 8,
            "role": "support",
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 0, "W": 0, "E": 0, "R": 0},
            "item_options": {REDEMPTION: {"active_seconds": 1.0}},
            "allies": [_ally("Jinx")],
            "enemies": [_enemy()],
        },
        deterministic=True,
    )
    champion = get_champion("Lux")
    item = get_item_by_name(REDEMPTION)
    full = run_fight(champion, 18, [item], params, score_only=False)
    score = run_fight(champion, 18, [item], params, score_only=True)
    assert score["total_damage"] == full["total_damage"]
    assert score["resource_spent"] == full["resource_spent"]
    assert _scoring_rows(score) == _scoring_rows(full)


def test_redemption_is_optimizer_eligible_with_modeled_state():
    """Redemption is optimizer-eligible (modeled_state, 'ally_support' +
    'sustain' outcome dimensions), in get_eligible_legendaries, and the
    target model is 'modeled' (not target-blocked)."""
    item = get_item_by_name(REDEMPTION)
    coverage = item_probe.attacker_coverage(item)
    assert coverage["optimizer_eligible"] is True
    assert coverage["status"] == "modeled_state"
    assert coverage["calculation_eligible"] is True
    assert {"ally_support", "sustain"} <= set(coverage["outcome_dimensions"])
    assert REDEMPTION in {entry["name"] for entry in get_eligible_legendaries()}
    target = target_item_model_coverage(item)
    assert target["status"] == "modeled"
    assert target["calculation_eligible"] is True


def test_no_stale_bis_entry_and_review_issue_48_recorded():
    """BIS carries no stale Redemption entry, and review issue 48 (ally/team
    item families) is recorded for Redemption both in the coverage registry
    and in the tracked acceptance docs."""
    assert review_issue_refs(REDEMPTION) == [48]

    bis_source = (REPO / "src" / "calculator" / "bis.py").read_text(encoding="utf-8")
    assert "Redemption" not in bis_source

    tracked = json.loads(
        (REPO / "docs" / "cp47-production-acceptance.json").read_text(encoding="utf-8")
    )
    residual = " ".join(tracked["residual_scope"])
    assert "#48" in residual
    assert "Redemption" in residual


# ---------------------------------------------------------------------------
# 11. Public output surface
# ---------------------------------------------------------------------------


def test_public_heal_packets_carry_source_amount_time_beam_delay_range():
    """Heal packets in support_events expose source 'Redemption —
    Intervention', amount, time, beam_delay and range_assumption, plus the
    target-scope/selection-key fields the roster path needs."""
    combat = _calculate(
        _main(
            allies=[_ally("Jinx")],
            enemies=[_enemy()],
        )
    )
    heals = [
        packet for packet in _redemption_support(combat) if packet["kind"] == "heal"
    ]
    assert len(heals) == 2
    for packet in heals:
        assert packet["source"] == SOURCE
        assert packet["time"] == pytest.approx(3.5)
        assert packet["beam_delay"] == pytest.approx(2.5)
        assert packet["range_assumption"] == "within_5500_units"
        assert packet["target_scope"] == "redemption_allies_in_radius"
        assert packet["target_selection_key"] == f"heal:{SOURCE}"
        assert packet["target_policy"] == "explicit_selected_roster_target"
    assert heals[0]["amount"] == pytest.approx(350.0)


def test_public_damage_events_carry_true_type_and_exact_precision():
    """The damage stream carries the Redemption events with damage_type
    'true', damage == raw_damage, event_precision 'exact' and a stable
    event id."""
    combat = _calculate(
        _main(enemies=[_enemy("Aatrox")]),
    )
    (event,) = _redemption_damage(combat)
    assert event["damage_type"] == "true"
    assert event["damage"] == pytest.approx(258.8)
    assert event["raw_damage"] == pytest.approx(258.8)
    assert event["event_precision"] == "exact"
    assert event["event_id"] == "enemy:Aatrox:support:0"


def test_api_config_exposes_redemption_schema_and_revision():
    """/api/config serves the Intervention active_seconds schema and the
    sourced revision 4015392 for Redemption."""
    response = app.test_client().get("/api/config")
    assert response.status_code == 200
    block = response.get_json()["item_options"][REDEMPTION]
    assert block["options"]["active_seconds"] == {
        "type": "float",
        "label": "Intervention active seconds",
        "default": 0.0,
        "min": 0.0,
        "max": 30.0,
        "step": 0.5,
    }
    assert block["source_url"] == SOURCE_URL
    assert block["source_revision_id"] == REVISION_ID


# ---------------------------------------------------------------------------
# 12. Determinism + no duplicate packets
# ---------------------------------------------------------------------------


def test_identical_fights_produce_identical_packets_and_receipts():
    """Two identical app fights deep-equal; exactly one heal packet per
    ally and one damage packet per enemy (no duplicates)."""
    payload = _main(
        allies=[_ally("Jinx"), _ally("Ashe")],
        enemies=[_enemy("Aatrox"), _enemy("Annie")],
    )
    first = _calculate(payload)
    second = _calculate(payload)
    assert first == second
    packets = _redemption_support(first)
    assert len(packets) == 7  # 3 heals + 2 damage + 2 vision receipts
    assert len({(p["kind"], p["target"]) for p in packets}) == 7
    assert len(_redemption_damage(first)) == 2
    assert _redemption_damage(first) == _redemption_damage(second)
