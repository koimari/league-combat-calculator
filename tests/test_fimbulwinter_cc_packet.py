"""P3 Package 3B — Fimbulwinter Everlasting crowd-control packet certification.

This file is the focused test-matrix owner for the Fimbulwinter Everlasting
(``Fimbulwinter — Everlasting``) self-shield contract.  It pins the
OBSERVABLES the coordinator's P3-3B completion must satisfy, and each test
runs against today's source: every behavior that already exists must pass
now; every assertion that targets a receipt the source does not emit yet is
marked ``# P3-3B contract`` and ``xfail`` with reason
``awaiting P3-3B denial receipts``.

Contract under test (binding for the coordinator):

* TRIGGER RULE (kernel-owned ``CcTriggerRule``): immobilize always eligible
  (melee or ranged holder); slow eligible ONLY for a melee holder; a bare
  ``crowd_control: True`` flag is ambiguous and never fires; an unknown
  ``cc_kind`` string never fires; an event with NO CC marker is not even a
  candidate.
* MANA GATE: current mana must EXCEED 20% of max mana (``current_mana >
  max_mana * 0.20``); exactly at the threshold is denied; a manaless holder
  (``max_mana == 0``) is denied.
* GLOBAL COOLDOWN: 8s, inclusive boundary (a trigger at exactly
  ``cooldown_until`` is allowed); the clock starts only on an ACCEPTED
  trigger.
* INSTANCE CADENCE: one shield per cast instance (``ability_instance``;
  fallback ``source_key:round(time,9)``) regardless of cooldown; different
  cast instances each get a shield when the cooldown permits.
* SHIELD: one packet per accepted trigger, ``kind == "shield"``,
  ``target_scope == "self"``, at the triggering event's time; formula
  ``(100 + 0.045 * current_mana) * (1.8 if nearby_enemy_count > 1 else 1.0)``,
  duration 3s, cooldown_until = time + 8.
* FAIL-CLOSED DENIAL RECEIPTS: every denial produces an additional receipt
  entry in the ``derive_item_support_effects`` return list with ``kind ==
  "item_denial"``, ``source == "Fimbulwinter — Everlasting"``, ``time`` of
  the denied event, and a named ``reason``: ``"ranged_slow"``,
  ``"mana_gate"``, ``"cooldown"``, ``"duplicate_instance"``, ``"untyped_cc"``
  (bare ``crowd_control`` flag), ``"unknown_cc_kind"``.  Events with NO CC
  marker are not candidates and produce neither a shield nor a receipt.
  Denial receipts are receipts, not applied packets: the participant
  timeline splits them out of the applied support-event stream into the
  public ``item_denial_receipts`` section.
* TIMELINE CERTIFICATION: a Fimbulwinter fight whose ability events carry a
  typed ``cc_kind`` (or an explicit reviewed marker) is event-certified for
  the CC dimension (``timeline_coverage["complete"] is True``, no
  ``fimbulwinter_everlasting`` coarse source); unreviewed ability events keep
  the current coarse behavior; auto-attack-only windows contain no CC
  candidates and neither trigger Everlasting nor poison certification.

Asserted constants (100 / 0.045 / 0.20 / 1.8 / 3.0 / 8.0 / crowd_control)
are the typed accessors' expected values; per AGENTS.md rule 5 the source
must read them from ``required_effect_value``, and this file also pins the
fail-loud behavior for a missing key.
"""

from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.usefixtures("authorized_fimbulwinter_mana_gate")

from src.calculator.ability_spec import ACTION_BLOCKING_CC_KINDS
from src.calculator.champions import parse_champion_abilities
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.defensive_effects import resolve_starting_defenses
from src.calculator.item_effects import ITEM_EFFECTS, required_effect_value
from src.calculator.item_support_effects import derive_item_support_effects
from src.calculator.participant_timeline import build_participant_timeline
from src.calculator.pipeline import FightParams
from src.calculator.scenario import ChampionLoadout
from src.calculator.stats import calculate_total_stats

FIMBULWINTER = "Fimbulwinter"
EVERLASTING = "Fimbulwinter — Everlasting"

# Typed-accessor expected values (asserted literals are allowed in tests).
BASE_SHIELD = 100.0
CURRENT_MANA_RATIO = 0.045
MANA_THRESHOLD_RATIO = 0.20
MULTI_TARGET_MULTIPLIER = 1.8
DURATION = 3.0
COOLDOWN = 8.0
TRIGGER_KIND_TOKEN = "crowd_control"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _actor(
    participant_id: str,
    team: str,
    item_names: tuple[str, ...],
    *,
    is_melee: bool = False,
    max_mana: float = 1000.0,
):
    return SimpleNamespace(
        participant_id=participant_id,
        team=team,
        level=18,
        items=tuple({"name": name} for name in item_names),
        stats={
            "mana": max_mana,
            "max_mana": max_mana,
            "is_melee": is_melee,
        },
        request=SimpleNamespace(item_options={}, ally_effects_enabled=True),
    )


def _cc_event(
    time: float,
    *,
    ability_instance: str = "E:1",
    source_key: str = "E",
    target: str = "enemy:Aatrox",
    event_id: str | None = None,
    **markers,
) -> dict:
    event = {
        "time": time,
        "target": target,
        "source_key": source_key,
        "ability_instance": ability_instance,
    }
    if event_id is not None:
        event["_event_id"] = event_id
    event.update(markers)
    return event


def _run(
    events: list[dict],
    *,
    is_melee: bool = True,
    max_mana: float = 1000.0,
    cast_timeline: list[dict] | None = None,
    nearby_enemies: int = 1,
) -> list[dict]:
    holder = _actor(
        "main:Ahri", "main", (FIMBULWINTER,), is_melee=is_melee, max_mana=max_mana
    )
    enemies = [_actor(f"enemy:Enemy{i}", "enemy", ()) for i in range(nearby_enemies)]
    result: dict = {"damage_events": events}
    if cast_timeline is not None:
        result["cast_timeline"] = cast_timeline
    return derive_item_support_effects(holder, result, [holder, *enemies])


def _shields(packets: list[dict]) -> list[dict]:
    return [
        p
        for p in packets
        if p.get("kind") == "shield" and p.get("source") == EVERLASTING
    ]


def _denials(packets: list[dict], reason: str | None = None) -> list[dict]:
    rows = [
        p
        for p in packets
        if p.get("kind") == "item_denial" and p.get("source") == EVERLASTING
    ]
    if reason is not None:
        rows = [p for p in rows if p.get("reason") == reason]
    return rows


def _certification_fight(cast_order, *, duration=2.0, uptime=0.0, one_rotation=True):
    ahri = get_champion("Ahri")
    item = get_item_by_name(FIMBULWINTER)
    stats = calculate_total_stats(ahri, 18, [item])
    abilities = parse_champion_abilities(ahri, 18, stats["ability_power"])
    return calculate_fight_damage(
        stats,
        {key: abilities[key] for key in cast_order},
        [item],
        FightConfig(
            target_health=5000.0,
            target_armor=0.0,
            target_magic_resistance=0.0,
            fight_duration_seconds=duration,
            auto_attack_uptime=uptime,
            one_rotation=one_rotation,
            cast_order=cast_order,
        ),
    )


# ---------------------------------------------------------------------------
# 1. Typed / source-backed contract
# ---------------------------------------------------------------------------


class TestTypedContract:
    def test_typed_accessor_values_match_expected_constants(self):
        assert (
            required_effect_value(FIMBULWINTER, "everlasting_base_shield")
            == BASE_SHIELD
        )
        assert (
            required_effect_value(FIMBULWINTER, "everlasting_current_mana_ratio")
            == CURRENT_MANA_RATIO
        )
        assert (
            required_effect_value(FIMBULWINTER, "everlasting_mana_threshold_ratio")
            == MANA_THRESHOLD_RATIO
        )
        assert (
            required_effect_value(FIMBULWINTER, "everlasting_multi_target_multiplier")
            == MULTI_TARGET_MULTIPLIER
        )
        assert required_effect_value(FIMBULWINTER, "everlasting_duration") == DURATION
        assert required_effect_value(FIMBULWINTER, "everlasting_cooldown") == COOLDOWN
        assert (
            required_effect_value(FIMBULWINTER, "everlasting_trigger_kind")
            == TRIGGER_KIND_TOKEN
        )
        assert (
            ITEM_EFFECTS[FIMBULWINTER]["everlasting_trigger_kind"] == TRIGGER_KIND_TOKEN
        )

    def test_missing_typed_key_fails_loud_naming_the_item_and_key(self):
        with pytest.raises(KeyError, match="Fimbulwinter.*everlasting_missing_key"):
            required_effect_value(FIMBULWINTER, "everlasting_missing_key")

    def test_shield_carries_the_cc_trigger_rule_declaration_receipt(self):
        packets = _run(
            [_cc_event(1.0, cc_kind="immobilize", event_id="e1")],
            cast_timeline=[{"time": 1.0, "resource_after": 900.0}],
            nearby_enemies=2,
        )
        shield = _shields(packets)[0]
        receipt = shield["trigger_rule"]
        assert receipt["name"] == "Fimbulwinter — Everlasting crowd-control trigger"
        assert receipt["slow_kind"] == "slow"
        assert receipt["slow_melee_only"] is True
        assert receipt["immobilize_kinds"] == sorted(ACTION_BLOCKING_CC_KINDS)
        # The declaration is source-backed: immobilize kinds are the sourced
        # action-blocking vocabulary, and the rule carries the item source.
        assert set(receipt["immobilize_kinds"]) == set(ACTION_BLOCKING_CC_KINDS)
        assert receipt["source"]["url"] == shield["source_url"]
        assert receipt["source"]["revision_id"] == shield["source_revision_id"]


# ---------------------------------------------------------------------------
# 2. Immobilize is always eligible (melee and ranged holder)
# ---------------------------------------------------------------------------


class TestImmobilizeEligibility:
    def test_melee_holder_immobilize_fires_typed_shield(self):
        packets = _run(
            [_cc_event(1.0, cc_kind="immobilize", event_id="e1")],
            cast_timeline=[{"time": 1.0, "resource_after": 900.0}],
        )
        shields = _shields(packets)
        assert len(shields) == 1
        assert shields[0]["trigger_kind"] == "immobilize"
        assert shields[0]["trigger"] == "immobilize"
        # CC event at t and shield at t; cooldown window opens at t + 8.
        assert shields[0]["time"] == pytest.approx(1.0)
        assert shields[0]["cooldown_until"] == pytest.approx(9.0)

    def test_ranged_holder_immobilize_fires_typed_shield(self):
        packets = _run(
            [_cc_event(1.0, cc_kind="immobilize", event_id="e1")],
            is_melee=False,
            cast_timeline=[{"time": 1.0, "resource_after": 900.0}],
        )
        shields = _shields(packets)
        assert len(shields) == 1
        assert shields[0]["trigger_kind"] == "immobilize"

    @pytest.mark.parametrize("kind", sorted(ACTION_BLOCKING_CC_KINDS))
    def test_every_action_blocking_kind_fires_immobilize(self, kind: str):
        packets = _run(
            [_cc_event(1.0, cc_kind=kind, event_id="e1")],
            cast_timeline=[{"time": 1.0, "resource_after": 900.0}],
        )
        shields = _shields(packets)
        assert len(shields) == 1
        assert shields[0]["trigger_kind"] == "immobilize"

    def test_explicit_hard_cc_flag_fires_immobilize(self):
        packets = _run(
            [_cc_event(1.0, hard_cc=True, event_id="e1")],
            cast_timeline=[{"time": 1.0, "resource_after": 900.0}],
        )
        shields = _shields(packets)
        assert len(shields) == 1
        assert shields[0]["trigger_kind"] == "immobilize"


# ---------------------------------------------------------------------------
# 3. Slow is eligible ONLY for a melee holder
# ---------------------------------------------------------------------------


class TestSlowMeleeOnly:
    def test_melee_holder_slow_fires_typed_shield(self):
        packets = _run(
            [_cc_event(1.0, cc_kind="slow", event_id="e1")],
            cast_timeline=[{"time": 1.0, "resource_after": 900.0}],
        )
        shields = _shields(packets)
        assert len(shields) == 1
        assert shields[0]["trigger_kind"] == "slow"

    def test_ranged_holder_slow_produces_no_everlasting_packet(self):
        packets = _run(
            [_cc_event(1.0, cc_kind="slow", event_id="e1")],
            is_melee=False,
            cast_timeline=[{"time": 1.0, "resource_after": 900.0}],
        )
        assert _shields(packets) == []

    def test_ranged_holder_slow_denial_receipt_is_named(self):
        # P3-3B contract: today the source silently skips; the coordinator
        # must emit a named fail-closed receipt for the ranged-slow denial.
        packets = _run(
            [_cc_event(1.0, cc_kind="slow", event_id="e1")],
            is_melee=False,
            cast_timeline=[{"time": 1.0, "resource_after": 900.0}],
        )
        rows = _denials(packets, reason="ranged_slow")
        assert len(rows) == 1
        row = rows[0]
        assert row["kind"] == "item_denial"
        assert row["source"] == EVERLASTING
        assert row["reason"] == "ranged_slow"
        assert row["time"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 4. Mana threshold boundary: current mana must EXCEED 20% of max
# ---------------------------------------------------------------------------


class TestManaGateBoundary:
    @pytest.mark.parametrize(
        ("resource_after", "expected_shields"),
        [
            (200.0, 0),  # exactly at 20% -> denied
            (150.0, 0),  # below 20% -> denied
            (200.01, 1),  # just above 20% -> accepted
            (999.0, 1),  # comfortably above -> accepted
        ],
    )
    def test_threshold_boundary_shield_presence(self, resource_after, expected_shields):
        packets = _run(
            [_cc_event(1.0, cc_kind="immobilize", event_id="e1")],
            max_mana=1000.0,
            cast_timeline=[{"time": 1.0, "resource_after": resource_after}],
        )
        shields = _shields(packets)
        assert len(shields) == expected_shields
        if expected_shields:
            assert shields[0]["current_mana"] == pytest.approx(resource_after)
            assert shields[0]["mana_threshold"] == pytest.approx(200.0)
            # The accepted invariant: current mana strictly exceeds 20% max.
            assert shields[0]["current_mana"] > shields[0]["mana_threshold"]

    def test_exactly_at_threshold_denial_receipt_is_named(self):
        # P3-3B contract: named receipt for the mana-gate denial.
        packets = _run(
            [_cc_event(1.0, cc_kind="immobilize", event_id="e1")],
            max_mana=1000.0,
            cast_timeline=[{"time": 1.0, "resource_after": 200.0}],
        )
        rows = _denials(packets, reason="mana_gate")
        assert len(rows) == 1
        row = rows[0]
        assert row["kind"] == "item_denial"
        assert row["source"] == EVERLASTING
        assert row["reason"] == "mana_gate"
        assert row["time"] == pytest.approx(1.0)

    def test_below_threshold_denial_receipt_is_named(self):
        # P3-3B contract: named receipt for the mana-gate denial.
        packets = _run(
            [_cc_event(1.0, cc_kind="immobilize", event_id="e1")],
            max_mana=1000.0,
            cast_timeline=[{"time": 1.0, "resource_after": 150.0}],
        )
        rows = _denials(packets, reason="mana_gate")
        assert len(rows) == 1
        row = rows[0]
        assert row["kind"] == "item_denial"
        assert row["source"] == EVERLASTING
        assert row["reason"] == "mana_gate"
        assert row["time"] == pytest.approx(1.0)

    def test_manaless_holder_is_denied(self):
        packets = _run(
            [_cc_event(1.0, cc_kind="immobilize", event_id="e1")],
            max_mana=0.0,
        )
        assert _shields(packets) == []

    def test_manaless_denial_receipt_is_named(self):
        # P3-3B contract: the manaless case is the same mana gate (0 <= 0).
        packets = _run(
            [_cc_event(1.0, cc_kind="immobilize", event_id="e1")],
            max_mana=0.0,
        )
        rows = _denials(packets, reason="mana_gate")
        assert len(rows) == 1
        row = rows[0]
        assert row["kind"] == "item_denial"
        assert row["source"] == EVERLASTING
        assert row["reason"] == "mana_gate"
        assert row["time"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 5. Deterministic 8s global cooldown (inclusive boundary)
# ---------------------------------------------------------------------------


class TestGlobalCooldown:
    def _cd_events(self):
        return [
            _cc_event(1.0, ability_instance="E:1", cc_kind="immobilize", event_id="a"),
            _cc_event(5.0, ability_instance="E:2", cc_kind="immobilize", event_id="b"),
            _cc_event(9.0, ability_instance="E:3", cc_kind="immobilize", event_id="c"),
        ]

    def test_second_trigger_within_8s_is_denied_and_t8_is_inclusive(self):
        packets = _run(self._cd_events())
        shields = _shields(packets)
        assert [s["time"] for s in shields] == [pytest.approx(1.0), pytest.approx(9.0)]
        assert [s["cooldown_until"] for s in shields] == [
            pytest.approx(9.0),
            pytest.approx(17.0),
        ]
        # The clock starts only on ACCEPTED triggers: the t=5 denial must not
        # move the boundary, so t=9 (exactly cooldown_until) is still allowed.
        assert shields[1]["time"] == pytest.approx(shields[0]["cooldown_until"])

    def test_in_flight_denial_receipt_is_named(self):
        # P3-3B contract: named receipt for the cooldown denial at t=5.
        packets = _run(self._cd_events())
        rows = _denials(packets, reason="cooldown")
        assert len(rows) == 1
        row = rows[0]
        assert row["kind"] == "item_denial"
        assert row["source"] == EVERLASTING
        assert row["reason"] == "cooldown"
        assert row["time"] == pytest.approx(5.0)

    def test_cooldown_packet_fields_are_sourced(self):
        packets = _run(
            [_cc_event(1.0, cc_kind="immobilize", event_id="a")],
            cast_timeline=[{"time": 1.0, "resource_after": 900.0}],
        )
        shield = _shields(packets)[0]
        assert shield["cooldown"] == COOLDOWN
        assert shield["cooldown_until"] == pytest.approx(1.0 + COOLDOWN)
        assert shield["duration"] == DURATION
        assert shield["source_url"].endswith("/Fimbulwinter")
        assert shield["source_revision_id"] == 3984419


# ---------------------------------------------------------------------------
# 6. Instance cadence: one shield per cast instance
# ---------------------------------------------------------------------------


class TestInstanceCadence:
    def test_two_cc_events_from_same_instance_yield_one_shield(self):
        packets = _run(
            [
                _cc_event(
                    1.0, ability_instance="E:1", cc_kind="immobilize", event_id="a"
                ),
                _cc_event(
                    1.5, ability_instance="E:1", cc_kind="immobilize", event_id="b"
                ),
            ]
        )
        shields = _shields(packets)
        assert len(shields) == 1
        assert shields[0]["_trigger_event_id"] == "a"

    def test_same_instance_denial_receipt_is_named(self):
        # P3-3B contract: named receipt for the duplicate-instance denial.
        packets = _run(
            [
                _cc_event(
                    1.0, ability_instance="E:1", cc_kind="immobilize", event_id="a"
                ),
                _cc_event(
                    1.5, ability_instance="E:1", cc_kind="immobilize", event_id="b"
                ),
            ]
        )
        rows = _denials(packets, reason="duplicate_instance")
        assert len(rows) == 1
        row = rows[0]
        assert row["kind"] == "item_denial"
        assert row["source"] == EVERLASTING
        assert row["reason"] == "duplicate_instance"
        assert row["time"] == pytest.approx(1.5)

    def test_same_instance_stays_consumed_past_cooldown(self):
        # Instance cadence is checked before the cooldown: the same instance
        # at t=9 (cooldown ready) is still denied by the consumed instance.
        packets = _run(
            [
                _cc_event(
                    1.0, ability_instance="E:1", cc_kind="immobilize", event_id="a"
                ),
                _cc_event(
                    9.0, ability_instance="E:1", cc_kind="immobilize", event_id="b"
                ),
            ]
        )
        assert len(_shields(packets)) == 1

    def test_different_instances_yield_two_shields_when_cooldown_permits(self):
        packets = _run(
            [
                _cc_event(
                    1.0, ability_instance="E:1", cc_kind="immobilize", event_id="a"
                ),
                _cc_event(
                    9.0, ability_instance="E:2", cc_kind="immobilize", event_id="b"
                ),
            ]
        )
        shields = _shields(packets)
        assert [s["time"] for s in shields] == [pytest.approx(1.0), pytest.approx(9.0)]
        assert [s["_trigger_event_id"] for s in shields] == ["a", "b"]

    def test_two_triggers_at_same_time_deterministic_order(self):
        # Same timestamp, different instances: exactly one shield (the first
        # event in list order wins; the second is denied by the cooldown that
        # the first accepted trigger started).  Pins the deterministic order.
        packets = _run(
            [
                _cc_event(
                    1.0, ability_instance="E:1", cc_kind="immobilize", event_id="first"
                ),
                _cc_event(
                    1.0, ability_instance="E:2", cc_kind="immobilize", event_id="second"
                ),
            ]
        )
        shields = _shields(packets)
        assert len(shields) == 1
        assert shields[0]["_trigger_event_id"] == "first"
        assert shields[0]["time"] == pytest.approx(1.0)
        assert shields[0]["cooldown_until"] == pytest.approx(9.0)

    def test_missing_instance_identity_fails_closed_with_named_receipts(self):
        packets = _run(
            [
                _cc_event(
                    1.0, ability_instance=None, cc_kind="immobilize", event_id="a"
                ),
            ]
        )
        assert _shields(packets) == []
        assert [
            (row["reason"], row["event_id"])
            for row in _denials(packets, reason="missing_instance_identity")
        ] == [
            ("missing_instance_identity", "a"),
        ]


# ---------------------------------------------------------------------------
# 7. Missing / ambiguous CC metadata fails closed
# ---------------------------------------------------------------------------


class TestFailClosedMetadata:
    def test_bare_crowd_control_flag_never_fires(self):
        packets = _run([_cc_event(1.0, crowd_control=True, event_id="e1")])
        assert _shields(packets) == []

    def test_bare_crowd_control_denial_receipt_is_named(self):
        # P3-3B contract: a bare crowd_control flag is a candidate but is
        # branch-ambiguous; the coordinator must receipt the denial as
        # "untyped_cc" (no shield is emitted today).
        packets = _run([_cc_event(1.0, crowd_control=True, event_id="e1")])
        rows = _denials(packets, reason="untyped_cc")
        assert len(rows) == 1
        row = rows[0]
        assert row["kind"] == "item_denial"
        assert row["source"] == EVERLASTING
        assert row["reason"] == "untyped_cc"
        assert row["time"] == pytest.approx(1.0)

    def test_unknown_cc_kind_never_fires(self):
        packets = _run([_cc_event(1.0, cc_kind="petrify", event_id="e1")])
        assert _shields(packets) == []

    def test_unknown_cc_kind_denial_receipt_is_named(self):
        # P3-3B contract: an unrecognized cc_kind is not in the sourced
        # vocabulary and must be receipted as "unknown_cc_kind".
        packets = _run([_cc_event(1.0, cc_kind="petrify", event_id="e1")])
        rows = _denials(packets, reason="unknown_cc_kind")
        assert len(rows) == 1
        row = rows[0]
        assert row["kind"] == "item_denial"
        assert row["source"] == EVERLASTING
        assert row["reason"] == "unknown_cc_kind"
        assert row["time"] == pytest.approx(1.0)

    def test_event_with_no_marker_is_not_a_candidate(self):
        # No CC metadata at all: not a candidate, so no shield AND no denial
        # receipt (there is nothing to deny).  This pin is part of the 3B
        # receipt contract: receipts exist only for CC candidates.
        packets = _run([_cc_event(1.0)])
        assert _shields(packets) == []
        assert _denials(packets) == []


# ---------------------------------------------------------------------------
# 8. Exactly one shield packet per accepted trigger; self scope
# ---------------------------------------------------------------------------


class TestNoDuplicatePackets:
    def test_exactly_one_packet_per_accepted_trigger(self):
        packets = _run(
            [_cc_event(1.0, cc_kind="immobilize", event_id="a")],
            cast_timeline=[{"time": 1.0, "resource_after": 900.0}],
        )
        assert len(_shields(packets)) == 1
        assert [row["reason"] for row in _denials(packets)] == [
            "nearby_enemy_spatial_input_unavailable"
        ]

    def test_duplicate_identical_event_entries_do_not_duplicate_shield(self):
        packets = _run(
            [
                _cc_event(1.0, cc_kind="immobilize", event_id="dup"),
                _cc_event(1.0, cc_kind="immobilize", event_id="dup"),
            ]
        )
        assert len(_shields(packets)) == 1

    def test_shield_targets_self(self):
        packets = _run(
            [_cc_event(1.0, cc_kind="immobilize", event_id="a")],
            cast_timeline=[{"time": 1.0, "resource_after": 900.0}],
        )
        shield = _shields(packets)[0]
        assert shield["target_scope"] == "self"
        assert shield["target"] == "main:Ahri"
        assert shield["attacker"] == "main:Ahri"

    def test_multi_target_multiplier_waits_for_typed_spatial_input(self):
        packets = _run(
            [_cc_event(1.0, cc_kind="immobilize", event_id="a")],
            cast_timeline=[{"time": 1.0, "resource_after": 900.0}],
            nearby_enemies=1,
        )
        solo = _shields(packets)[0]
        assert solo["nearby_enemy_count"] is None
        assert solo["multi_target_multiplier"] == pytest.approx(1.0)
        assert solo["amount"] == pytest.approx(
            (BASE_SHIELD + CURRENT_MANA_RATIO * 900.0) * 1.0
        )

        packets = _run(
            [_cc_event(1.0, cc_kind="immobilize", event_id="a")],
            cast_timeline=[{"time": 1.0, "resource_after": 900.0}],
            nearby_enemies=2,
        )
        duo = _shields(packets)[0]
        assert duo["nearby_enemy_count"] is None
        assert duo["multi_target_multiplier"] == pytest.approx(1.0)
        assert duo["amount"] == pytest.approx(
            (BASE_SHIELD + CURRENT_MANA_RATIO * 900.0) * 1.0
        )
        assert [row["reason"] for row in _denials(packets)] == [
            "nearby_enemy_spatial_input_unavailable"
        ]


# ---------------------------------------------------------------------------
# 9. Timeline certification (typed CC events certify the CC dimension)
# ---------------------------------------------------------------------------


class TestTimelineCertification:
    def test_typed_cc_fight_is_event_certified(self):
        # Ahri's E is a reviewed module ability whose damage part carries
        # cc_kind="immobilize": every ability event is typed, so the CC
        # dimension is event-certified and NOT coarse.
        result = _certification_fight(["E"])
        assert result["timeline_coverage"]["complete"] is True
        assert (
            "fimbulwinter_everlasting"
            not in result["timeline_coverage"]["coarse_sources"]
        )
        assert result["timeline_coverage"]["certification"] == "event_order_certified"
        # Provenance: the fight's E events actually carry the typed kind and
        # the reviewed marker.
        e_events = [
            event
            for row in result["breakdown"].values()
            if isinstance(row, dict)
            for event in row.get("damage_events", [])
            if event.get("cc_kind") == "immobilize"
        ]
        assert e_events
        assert all(event.get("cc_kind") == "immobilize" for event in e_events)
        assert all(event.get("cc_reviewed") is True for event in e_events)

    def test_unreviewed_ability_keeps_current_coarse_behavior(self):
        # P3-3B contract target: certifying REVIEWED packets is the 3B goal.
        # Today's observable (pinned, not changed): an unreviewed ability
        # (Ahri Q carries no cc metadata) keeps the CC dimension coarse.
        result = _certification_fight(["Q"])
        assert result["timeline_coverage"]["complete"] is False
        assert (
            "fimbulwinter_everlasting" in result["timeline_coverage"]["coarse_sources"]
        )

    def test_reviewed_charm_fight_attaches_shield_and_certifies_end_to_end(self):
        main = get_champion("Ahri")
        loadout = ChampionLoadout(
            champion="Ahri", level=18, items=(FIMBULWINTER,)
        ).resolve()
        enemy = ChampionLoadout(champion="Aatrox", level=18, items=()).resolve()
        params = FightParams.from_request(
            {
                "fight_mode": "one_rotation",
                "ability_ranks": {"Q": 0, "W": 0, "E": 1, "R": 0},
                "auto_attack_uptime": 0.0,
            },
            deterministic=True,
        )
        result = build_participant_timeline(
            main,
            18,
            list(loadout.item_data),
            params,
            main_stats=loadout.stats,
            main_defenses=resolve_starting_defenses(
                "Ahri", 18, loadout.stats, list(loadout.item_data)
            ),
            enemies=[enemy],
            allies=[],
        )
        shields = [
            event
            for event in result["support_events"]
            if event["source"] == EVERLASTING
        ]
        assert len(shields) == 1
        assert shields[0]["trigger_kind"] == "immobilize"
        assert shields[0]["current_mana"] > shields[0]["mana_threshold"]
        assert result["timeline_coverage"]["complete"] is True
        assert (
            "fimbulwinter_everlasting"
            not in result["timeline_coverage"]["coarse_sources"]
        )


# ---------------------------------------------------------------------------
# 10. Auto-attack-only windows (no CC candidates)
# ---------------------------------------------------------------------------


class TestAutoAttackOnlyWindow:
    def test_auto_only_fight_is_certified_and_has_no_everlasting_packet(self):
        # calculate_fight_damage: no ability events at all -> the CC dimension
        # is exact (nothing to certify) and no Everlasting shield can fire.
        result = _certification_fight([], duration=3.0, uptime=1.0, one_rotation=False)
        assert result["timeline_coverage"]["complete"] is True
        assert (
            "fimbulwinter_everlasting"
            not in result["timeline_coverage"]["coarse_sources"]
        )

    def test_auto_only_participant_timeline_does_not_trigger_or_poison(self):
        # build_participant_timeline with every ability rank 0: only auto
        # attacks land, so no CC candidate exists, no shield fires, and the
        # CC dimension stays certified.
        main = get_champion("Ahri")
        loadout = ChampionLoadout(
            champion="Ahri", level=18, items=(FIMBULWINTER,)
        ).resolve()
        enemy = ChampionLoadout(champion="Aatrox", level=18, items=()).resolve()
        params = FightParams.from_request(
            {
                "fight_mode": "one_rotation",
                "ability_ranks": {"Q": 0, "W": 0, "E": 0, "R": 0},
                "auto_attack_uptime": 1.0,
            },
            deterministic=True,
        )
        result = build_participant_timeline(
            main,
            18,
            list(loadout.item_data),
            params,
            main_stats=loadout.stats,
            main_defenses=resolve_starting_defenses(
                "Ahri", 18, loadout.stats, list(loadout.item_data)
            ),
            enemies=[enemy],
            allies=[],
        )
        shields = [
            event
            for event in result["support_events"]
            if event["source"] == EVERLASTING
        ]
        assert shields == []
        assert result["timeline_coverage"]["complete"] is True
        assert (
            "fimbulwinter_everlasting"
            not in result["timeline_coverage"]["coarse_sources"]
        )
