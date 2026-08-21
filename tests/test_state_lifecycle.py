"""P1 state-lifecycle kernel: primitives, ordering, and public receipts.

Covers the shared trigger/state contracts (roadmap P1): trigger
predicates, stack gain/loss, caps, durations, refresh rules (refresh /
extend / replace / none), expiry (all-at-once and step-down), interval
gates, combat freeze, consume/reset, cooldowns (global and per-target),
charge pools, lockout windows, deterministic ordering, and fail-closed
validation.  Consumer wiring lives in test_state_lifecycle_consumers.py.
"""

import pytest

from src.calculator import state_lifecycle as sl

# ---------------------------------------------------------------------------
# Deterministic ordering
# ---------------------------------------------------------------------------


class TestDeterministicOrdering:
    def test_expiry_precedes_gain_precedes_cooldown_start_at_one_timestamp(self):
        timeline = sl.StateTimeline()
        gain = timeline.record(1.0, "gain", sequence=7, tier=sl.TIER_GAIN)
        cooldown = timeline.record(
            1.0, "cooldown_start", sequence=7, tier=sl.TIER_COOLDOWN_START
        )
        expiry = timeline.record(1.0, "expire", sequence=7, tier=sl.TIER_EXPIRE)
        ordered = timeline.transitions()
        assert [t.kind for t in ordered] == ["expire", "gain", "cooldown_start"]
        assert ordered[0] is expiry
        assert ordered[1] is gain
        assert ordered[2] is cooldown

    def test_same_tier_ties_break_by_sequence_then_insertion(self):
        timeline = sl.StateTimeline()
        first = timeline.record(0.0, "gain", sequence=2)
        second = timeline.record(0.0, "gain", sequence=1)
        third = timeline.record(0.0, "gain", sequence=1)
        ordered = timeline.transitions()
        assert ordered[0] is second
        assert ordered[1] is third
        assert ordered[2] is first

    def test_public_receipt_is_json_safe_and_ordered(self):
        timeline = sl.StateTimeline()
        timeline.record(2.0, "gain", sequence=0, detail={"stacks_after": 1})
        timeline.record(1.0, "expire", sequence=0, tier=sl.TIER_EXPIRE)
        receipt = timeline.public_receipt()
        assert [row["time"] for row in receipt] == [1.0, 2.0]
        assert receipt[0]["kind"] == "expire"
        assert receipt[0]["detail"] == {}
        assert receipt[1]["detail"] == {"stacks_after": 1}


# ---------------------------------------------------------------------------
# StackRule validation (fail-closed)
# ---------------------------------------------------------------------------


class TestStackRuleFailClosed:
    def test_validation_names_state_and_source(self):
        with pytest.raises(ValueError, match="TestState.*duration_seconds"):
            sl.StackRule(
                name="TestState",
                max_stacks=3,
                gain_per_application=1,
                duration_seconds=0.0,
                source=sl.SourceReceipt(label="TestSource", url="https://x"),
            ).validate()

    def test_unknown_refresh_policy_raises(self):
        with pytest.raises(ValueError, match="unknown refresh policy"):
            sl.StackRule(
                name="S",
                max_stacks=2,
                gain_per_application=1,
                duration_seconds=1.0,
                refresh="sometimes",
            ).validate()

    def test_step_down_requires_step_seconds(self):
        with pytest.raises(ValueError, match="step_down"):
            sl.StackRule(
                name="S",
                max_stacks=2,
                gain_per_application=1,
                duration_seconds=1.0,
                expiry="step_down",
            ).validate()

    def test_interval_requires_an_instance_key(self):
        with pytest.raises(ValueError, match="interval_key"):
            sl.StackRule(
                name="S",
                max_stacks=2,
                gain_per_application=1,
                duration_seconds=1.0,
                interval_seconds=4.0,
            ).validate()

    def test_non_positive_gain_raises(self):
        with pytest.raises(ValueError, match="gain_per_application"):
            sl.StackRule(
                name="S",
                max_stacks=2,
                gain_per_application=0,
                duration_seconds=1.0,
            ).validate()

    def test_negative_trigger_time_raises(self):
        state = sl.TimedStackState(
            sl.StackRule(
                name="S", max_stacks=2, gain_per_application=1, duration_seconds=1.0
            )
        )
        with pytest.raises(ValueError, match="trigger time"):
            state.apply_gain(-1.0, kind="hit")

    def test_missing_source_is_optional_but_never_a_number(self):
        # A rule without a source is allowed only when every value came
        # from the consumer's own typed accessor; the receipt shows None.
        rule = sl.StackRule(
            name="S", max_stacks=2, gain_per_application=1, duration_seconds=1.0
        )
        assert rule.public_receipt()["source"] is None


# ---------------------------------------------------------------------------
# TimedStackState: refresh + step-down drain (Ashe Focus shape)
# ---------------------------------------------------------------------------


class TestTimedStackRefreshAndDrain:
    def _ashe_rule(self, cap_behavior: str = "noop") -> sl.StackRule:
        return sl.StackRule(
            name="Ashe.Focus",
            max_stacks=4,
            gain_per_application=1,
            duration_seconds=4.0,
            refresh="refresh",
            expiry="step_down",
            expiry_step_seconds=1.0,
            cap_behavior=cap_behavior,  # type: ignore[arg-type]
        )

    def test_gain_refresh_and_drain_sequence(self):
        state = sl.TimedStackState(self._ashe_rule())
        for time, seq in ((0.0, 0), (1.0, 1), (2.0, 2), (3.0, 3)):
            state.apply_gain(time, kind="on_attack", sequence=seq)
        assert state.stacks == 4
        # The window lasts 4s after the last gain (t=3 -> deadline 7).
        assert state.public_receipt()["expires_at"] == pytest.approx(7.0)
        # First drain step lands AT the deadline, then one per second.
        expected = [(7.0, 4, 3), (8.0, 3, 2), (9.0, 2, 1), (10.0, 1, 0)]
        for time, before, after in expected:
            transitions = state._materialize_expiries(time, sequence=99)
            assert transitions, f"expected an expiry at t={time}"
            assert transitions[-1].detail["stacks_before"] == before
            assert transitions[-1].detail["stacks_after"] == after
        assert state.stacks == 0

    def test_refresh_moves_the_deadline(self):
        state = sl.TimedStackState(self._ashe_rule())
        state.apply_gain(0.0, kind="on_attack", sequence=0)
        state.apply_gain(3.0, kind="on_attack", sequence=1)
        assert state.public_receipt()["expires_at"] == pytest.approx(7.0)
        kinds = [t.kind for t in state.timeline.transitions()]
        assert kinds == ["gain", "refresh"]

    def test_capped_gain_does_not_refresh_with_noop_cap_behavior(self):
        state = sl.TimedStackState(self._ashe_rule())
        for time in (0.0, 1.0, 2.0, 3.0):
            state.apply_gain(time, kind="on_attack", sequence=int(time))
        deadline_before = state.public_receipt()["expires_at"]
        denied = state.apply_gain(4.0, kind="on_attack", sequence=4)
        assert state.stacks == 4
        assert state.public_receipt()["expires_at"] == deadline_before
        assert denied[-1].kind == "gain_denied"
        assert denied[-1].detail["reason"] == "at_cap"

    def test_capped_gain_refreshes_with_refresh_cap_behavior(self):
        state = sl.TimedStackState(self._ashe_rule(cap_behavior="refresh"))
        for time in (0.0, 1.0, 2.0, 3.0):
            state.apply_gain(time, kind="on_attack", sequence=int(time))
        state.apply_gain(4.0, kind="on_attack", sequence=4)
        assert state.stacks == 4
        assert state.public_receipt()["expires_at"] == pytest.approx(8.0)

    def test_expiry_at_the_exact_boundary_precedes_a_same_time_gain(self):
        state = sl.TimedStackState(self._ashe_rule())
        state.apply_gain(0.0, kind="on_attack", sequence=0)
        transitions = state.apply_gain(4.0, kind="on_attack", sequence=7)
        kinds = [t.kind for t in transitions]
        assert kinds == ["expire", "gain"]
        assert transitions[0].detail["stacks_after"] == 0
        assert transitions[1].detail["stacks_before"] == 0
        assert transitions[1].detail["stacks_after"] == 1


# ---------------------------------------------------------------------------
# TimedStackState: extend vs replace vs none (per-stack timers)
# ---------------------------------------------------------------------------


class TestStackRefreshPolicies:
    def _rule(self, refresh: str) -> sl.StackRule:
        return sl.StackRule(
            name="S",
            max_stacks=3,
            gain_per_application=1,
            duration_seconds=4.0,
            refresh=refresh,  # type: ignore[arg-type]
        )

    def test_extend_keeps_the_later_deadline(self):
        state = sl.TimedStackState(self._rule("extend"))
        state.apply_gain(0.0, kind="hit", sequence=0)
        state.apply_gain(2.0, kind="hit", sequence=1)
        # extend moves the deadline to at least gain + duration
        # (max(4.0, 2.0 + 4.0) = 6.0); refresh would have reset it to 6.0
        # too, but extend never shortens a later deadline.
        assert state.public_receipt()["expires_at"] == pytest.approx(6.0)
        assert state.timeline.transitions()[-1].kind == "extend"

    def test_replace_sets_the_count_absolutely(self):
        rule = sl.StackRule(
            name="S",
            max_stacks=3,
            gain_per_application=1,
            duration_seconds=4.0,
            refresh="replace",
            gain_by_kind={"big": 2},
        )
        state = sl.TimedStackState(rule)
        state.apply_gain(0.0, kind="big", sequence=0)
        assert state.stacks == 2
        state.apply_gain(2.0, kind="hit", sequence=1)
        assert state.stacks == 1
        assert state.timeline.transitions()[-1].kind == "replace"

    def test_none_uses_per_stack_timers(self):
        state = sl.TimedStackState(
            sl.StackRule(
                name="Rengar.Ferocity",
                max_stacks=4,
                gain_per_application=1,
                duration_seconds=1.0,
                refresh="none",
            )
        )
        for time, seq in ((0.0, 0), (0.4, 1), (0.8, 2)):
            state.apply_gain(time, kind="basic_ability_cast", sequence=seq)
        assert state.stacks == 3
        # Each stack dies 1s after its own gain, oldest first.
        state._materialize_expiries(1.0, sequence=99)
        assert state.stacks == 2
        state._materialize_expiries(1.4, sequence=99)
        assert state.stacks == 1
        state._materialize_expiries(1.8, sequence=99)
        assert state.stacks == 0

    def test_combat_freeze_suppresses_expiry_and_rearms(self):
        state = sl.TimedStackState(
            sl.StackRule(
                name="Rengar.Ferocity",
                max_stacks=4,
                gain_per_application=1,
                duration_seconds=1.0,
                refresh="none",
                combat_extension_seconds=10.0,
            )
        )
        state.apply_gain(0.0, kind="basic_ability_cast", sequence=0)
        state.note_activity(0.5, kind="damage_taken", sequence=5)
        state._materialize_expiries(1.0, sequence=99)
        assert state.stacks == 1  # frozen
        state._materialize_expiries(10.4, sequence=99)
        assert state.stacks == 1  # freeze re-armed to 10.5 at t=0.5
        state._materialize_expiries(10.5, sequence=99)
        assert state.stacks == 0  # expired at the freeze boundary
        freeze = [t for t in state.timeline.transitions() if t.kind == "combat_freeze"]
        assert len(freeze) == 2
        assert freeze[1].detail["freeze_until"] == pytest.approx(10.5)

    def test_consume_at_cap_empowers_and_clears(self):
        state = sl.TimedStackState(
            sl.StackRule(
                name="Rengar.Ferocity",
                max_stacks=4,
                gain_per_application=1,
                duration_seconds=1.0,
                refresh="none",
                combat_extension_seconds=10.0,
            )
        )
        for seq in range(4):
            state.apply_gain(float(seq), kind="basic_ability_cast", sequence=seq)
        consumed = state.consume(4.0, sequence=4)
        assert consumed is not None
        assert consumed.kind == "consume"
        assert consumed.detail["empowered"] is True
        assert consumed.detail["stacks_before"] == 4
        assert state.stacks == 0

    def test_consume_below_cap_is_denied_and_does_not_mutate(self):
        state = sl.TimedStackState(
            sl.StackRule(
                name="Rengar.Ferocity",
                max_stacks=4,
                gain_per_application=1,
                duration_seconds=1.0,
                refresh="none",
                combat_extension_seconds=10.0,
            )
        )
        state.apply_gain(0.0, kind="basic_ability_cast", sequence=0)
        assert state.consume(1.0, sequence=1) is None
        assert state.stacks == 1
        assert state.timeline.transitions()[-1].kind == "consume_denied"

    def test_reset_is_idempotent_and_recorded_once(self):
        state = sl.TimedStackState(
            sl.StackRule(
                name="S", max_stacks=4, gain_per_application=1, duration_seconds=5.0
            )
        )
        state.apply_gain(0.0, kind="hit", sequence=0)
        first = state.reset(1.0, sequence=1, reason="cash_in")
        assert first is not None and first.kind == "reset"
        assert first.detail["reason"] == "cash_in"
        assert state.reset(1.0, sequence=1, reason="cash_in") is None  # silent


# ---------------------------------------------------------------------------
# Interval gate (Conqueror's per-cast-instance cadence)
# ---------------------------------------------------------------------------


class TestIntervalGate:
    def _rule(self) -> sl.StackRule:
        return sl.StackRule(
            name="Conqueror",
            max_stacks=12,
            gain_per_application=2,
            duration_seconds=5.0,
            refresh="refresh",
            interval_seconds=4.0,
            interval_key="source_key",
            interval_gate_packets=frozenset({"ability_cast"}),
        )

    def test_repeat_cast_within_interval_is_denied(self):
        state = sl.TimedStackState(self._rule())
        state.apply_gain(
            0.0,
            kind="ability_cast",
            packet="ability_cast",
            meta={"source_key": "Q", "source": "Q"},
            sequence=0,
        )
        denied = state.apply_gain(
            2.0,
            kind="ability_cast",
            packet="ability_cast",
            meta={"source_key": "Q", "source": "Q"},
            sequence=1,
        )
        assert denied[-1].kind == "gain_denied"
        assert denied[-1].detail["reason"] == "interval_gate"
        assert state.stacks == 2

    def test_gate_is_per_source_slot(self):
        state = sl.TimedStackState(self._rule())
        state.apply_gain(
            0.0,
            kind="ability_cast",
            packet="ability_cast",
            meta={"source_key": "Q", "source": "Q"},
            sequence=0,
        )
        state.apply_gain(
            1.0,
            kind="ability_cast",
            packet="ability_cast",
            meta={"source_key": "W", "source": "W"},
            sequence=1,
        )
        assert state.stacks == 4

    def test_gate_only_applies_to_declared_packets(self):
        state = sl.TimedStackState(self._rule())
        state.apply_gain(
            0.0,
            kind="ability_cast",
            packet="ability_cast",
            meta={"source_key": "Q", "source": "Q"},
            sequence=0,
        )
        state.apply_gain(
            1.0,
            kind="basic_attack",
            packet="basic_attack",
            meta={"source_key": "auto_attacks", "source": "auto"},
            sequence=1,
        )
        assert state.stacks == 4

    def test_interval_boundary_is_inclusive(self):
        state = sl.TimedStackState(self._rule())
        state.apply_gain(
            0.0,
            kind="ability_cast",
            packet="ability_cast",
            meta={"source_key": "Q", "source": "Q"},
            sequence=0,
        )
        state.apply_gain(
            4.0,
            kind="ability_cast",
            packet="ability_cast",
            meta={"source_key": "Q", "source": "Q"},
            sequence=1,
        )
        assert state.stacks == 4


# ---------------------------------------------------------------------------
# WindowStackGate (Eclipse pair gate + per-target cooldown)
# ---------------------------------------------------------------------------


class TestWindowStackGate:
    def _gate(self, cooldown: float = 6.0) -> sl.WindowStackGate:
        return sl.WindowStackGate(
            sl.WindowGateRule(
                name="Eclipse",
                stacks_required=2,
                window_seconds=2.0,
                cooldown_seconds=cooldown,
                per_target=True,
            )
        )

    def test_pair_completes_inside_the_window(self):
        gate = self._gate()
        assert gate.feed(0.0, sequence=0) == []
        procs = gate.feed(1.5, sequence=1)
        assert len(procs) == 1
        assert procs[0].time == 1.5
        kinds = [t.kind for t in gate.timeline.transitions()]
        assert kinds == ["gain", "proc", "cooldown_start"]

    def test_window_lapse_restarts_and_records_expiry(self):
        gate = self._gate()
        gate.feed(0.0, sequence=0)
        gate.feed(3.0, sequence=1)  # 3.0 > 0.0 + 2.0: window restarts
        assert gate.procs() == []
        kinds = [t.kind for t in gate.timeline.transitions()]
        assert kinds == ["gain", "expire", "gain"]
        assert gate.timeline.transitions()[1].detail["reason"] == "window_lapse"
        procs = gate.feed(3.5, sequence=2)
        assert len(procs) == 1

    def test_per_target_cooldown_skips_triggers_until_ready(self):
        gate = self._gate(cooldown=6.0)
        gate.feed(0.0, sequence=0)
        gate.feed(1.0, sequence=1)  # proc; cooldown until 7.0
        assert gate.feed(2.0, sequence=2) == []  # skipped
        assert gate.feed(5.0, sequence=3) == []  # still skipped
        kinds = [t.kind for t in gate.timeline.transitions()]
        assert kinds.count("trigger_skipped") == 2
        # Inclusive boundary: exactly at ready time the next pair can arm.
        gate.feed(7.0, sequence=4)
        procs = gate.feed(8.0, sequence=5)
        assert len(procs) == 1
        assert procs[0].time == 8.0

    def test_per_target_isolation(self):
        gate = self._gate(cooldown=6.0)
        gate.feed(0.0, sequence=0, target="A")
        gate.feed(1.0, sequence=1, target="A")  # proc for A, CD until 7.0
        gate.feed(1.5, sequence=2, target="B")  # B unaffected
        procs = gate.feed(2.0, sequence=3, target="B")
        assert len(procs) == 1
        assert procs[0].target == "B"
        # A is still on cooldown.
        assert gate.feed(2.5, sequence=4, target="A") == []
        # A can re-arm after its own cooldown.
        gate.feed(7.0, sequence=5, target="A")
        assert len(gate.feed(8.0, sequence=6, target="A")) == 1

    def test_public_receipt_exposes_every_transition(self):
        gate = self._gate()
        gate.feed(0.0, sequence=0)
        gate.feed(1.0, sequence=1)
        receipt = gate.public_receipt()
        assert receipt["rule"]["stacks_required"] == 2
        assert [t["kind"] for t in receipt["transitions"]] == [
            "gain",
            "proc",
            "cooldown_start",
        ]
        assert receipt["procs"][0]["time"] == 1.0
        assert receipt["procs"][0]["precision"] == "exact"

    def test_validate_rejects_single_stack_rule(self):
        with pytest.raises(ValueError, match="stacks_required"):
            sl.WindowStackGate(
                sl.WindowGateRule(
                    name="Eclipse",
                    stacks_required=1,
                    window_seconds=2.0,
                    cooldown_seconds=6.0,
                )
            )


# ---------------------------------------------------------------------------
# Cooldowns (global and per-target)
# ---------------------------------------------------------------------------


class TestCooldownState:
    def test_global_cooldown_gates_and_starts(self):
        state = sl.CooldownState(
            sl.CooldownRule(name="Everlasting", cooldown_seconds=8.0)
        )
        assert state.is_ready(0.0)
        start = state.start(1.0, sequence=0)
        assert start.kind == "cooldown_start"
        assert start.detail["cooldown_until"] == pytest.approx(9.0)
        assert not state.is_ready(5.0)
        assert state.is_ready(9.0)  # inclusive boundary

    def test_per_target_cooldown_keeps_independent_clocks(self):
        state = sl.CooldownState(
            sl.CooldownRule(name="PerTarget", cooldown_seconds=4.0, per_target=True)
        )
        state.start(0.0, target="A", sequence=0)
        state.start(0.5, target="B", sequence=1)
        assert not state.is_ready(1.0, target="A")
        assert not state.is_ready(1.0, target="B")
        assert state.is_ready(4.0, target="A")
        assert not state.is_ready(4.0, target="B")
        assert state.is_ready(4.5, target="B")

    def test_rule_validation_fails_closed(self):
        with pytest.raises(ValueError, match="cooldown_seconds"):
            sl.CooldownState(sl.CooldownRule(name="Bad", cooldown_seconds=0.0))


# ---------------------------------------------------------------------------
# CC trigger predicate and instance cadence
# ---------------------------------------------------------------------------


class TestCcTriggerRule:
    def _rule(self) -> sl.CcTriggerRule:
        return sl.CcTriggerRule(name="Everlasting", slow_melee_only=True)

    def test_immobilize_kinds_match(self):
        rule = self._rule()
        assert rule.match({"cc_kind": "stun"}, is_melee=False) == "immobilize"
        assert rule.match({"cc_kind": "root"}, is_melee=True) == "immobilize"
        assert rule.match({"hard_cc": True}, is_melee=False) == "immobilize"
        assert rule.match({"immobilized": True}, is_melee=False) == "immobilize"

    def test_slow_is_melee_only(self):
        rule = self._rule()
        assert rule.match({"cc_kind": "slow"}, is_melee=True) == "slow"
        assert rule.match({"cc_kind": "slow"}, is_melee=False) == ""
        assert rule.match({"slowed": True}, is_melee=True) == "slow"

    def test_bare_crowd_control_flag_is_not_enough(self):
        rule = self._rule()
        assert rule.match({"crowd_control": True}, is_melee=True) == ""
        assert rule.is_candidate({"crowd_control": True}) is True

    def test_candidate_filter_covers_markers_and_kinds(self):
        rule = self._rule()
        assert rule.is_candidate({"cc_kind": "airborne"})
        assert rule.is_candidate({"cc_kind": "slow"})
        assert rule.is_candidate({"slowed": True})
        assert not rule.is_candidate({"damage": 100})

    def test_denial_reason_names_every_non_matching_candidate(self):
        rule = self._rule()
        # Accepted branches produce no denial.
        assert rule.denial_reason({"cc_kind": "stun"}, is_melee=False) is None
        assert rule.denial_reason({"cc_kind": "slow"}, is_melee=True) is None
        assert rule.denial_reason({"hard_cc": True}, is_melee=False) is None
        # An event with NO CC metadata is not CC-adjacent: no receipt.
        assert rule.denial_reason({"damage": 100}, is_melee=True) is None
        assert rule.denial_reason({"time": 1.0}, is_melee=True) is None
        # Unknown cc_kind strings are outside the sourced vocabulary.
        assert rule.denial_reason({"cc_kind": "petrify"}, is_melee=True) == (
            "unknown_cc_kind"
        )
        # A bare crowd_control flag cannot distinguish the branches.
        assert rule.denial_reason({"crowd_control": True}, is_melee=True) == (
            "untyped_cc"
        )
        # Slow-classified events on a ranged holder are rejected by name.
        assert rule.denial_reason({"cc_kind": "slow"}, is_melee=False) == "ranged_slow"
        assert rule.denial_reason({"slowed": True}, is_melee=False) == "ranged_slow"
        assert rule.denial_reason({"slow": True}, is_melee=False) == "ranged_slow"

    def test_denial_reason_prefers_typed_kind_over_flags(self):
        rule = self._rule()
        # A typed slow with a bare flag on a ranged holder is the slow branch.
        assert (
            rule.denial_reason(
                {"cc_kind": "slow", "crowd_control": True}, is_melee=False
            )
            == "ranged_slow"
        )
        # A typed unknown kind wins over the bare flag.
        assert (
            rule.denial_reason(
                {"cc_kind": "petrify", "crowd_control": True}, is_melee=True
            )
            == "unknown_cc_kind"
        )


class TestInstanceCadence:
    def test_once_only_consumes_an_instance(self):
        cadence = sl.InstanceCadence(once_only=True)
        assert cadence.allow(1.0, "E:1") is True
        assert cadence.allow(9.0, "E:1") is False

    def test_interval_cadence_allows_first_and_after_window(self):
        cadence = sl.InstanceCadence(interval_seconds=4.0)
        assert cadence.allow(0.0, "Q") is True
        assert cadence.allow(2.0, "Q") is False
        assert cadence.allow(4.0, "Q") is True

    def test_none_instance_is_always_allowed(self):
        cadence = sl.InstanceCadence(once_only=True)
        assert cadence.allow(0.0, None) is True
        assert cadence.allow(1.0, None) is True

    def test_invalid_combination_raises(self):
        with pytest.raises(ValueError, match="cannot combine"):
            sl.InstanceCadence(interval_seconds=1.0, once_only=True)
