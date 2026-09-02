"""P3 slice 1 — Shared Mana Resource Ledger: full contract test matrix.

Kernel under test: ``src.calculator.resource_ledger`` (owned by RLM-1).

This file tests ONLY the ledger kernel. It imports nothing from the
damage/pipeline internals, so the kernel must be testable standalone.

Matrix sections (mirrors the roadmap slice-1 matrix):
    KERNEL          1-16  ResourceEvent / ResourceAccount / ResourceLedger
    MANAFLOW       17-29  ManaflowDeclaration / ManaflowLedger
    LOST CHAPTER   30-39  EnlightenDeclaration / enlighten_schedule
    REGRESSION     40-43  contract-level composition (no engine imports)
    row 44 is a comment-only note (Catalyst is out of slice; its matrix
    lives in tests/test_catalyst_resource_ledger.py)

Contract clarifications received from RLM-1 (binding):
    * ManaflowLedger(declaration, *, owner, authored_bonus_mana=0.0); hit()
      events carry owner=owner.
    * charges_available_at(time): banked = 1 + int(time // interval);
      available = max(0, min(max_charges, banked - use_count)) — charges
      refill over a long window (up to max_charges stored).
    * hit() returns (receipt: dict, event: ResourceEvent | None); receipt is
      JSON-safe with exact keys {time, source, accepted, reason, target_kind,
      hit_identity, charge_consumed, use_count, bonus_total, bonus_delta,
      cap, atom}; success reason is "charge_consumed"; at bonus_total == cap
      the hit is denied "cap_reached" with NO charge consumed.
    * one level-up per fight (enlighten_schedule takes one time); it raises
      ValueError for level_up_time < 0 or non-finite maximum_mana; emitted
      events carry owner (keyword, default "").
    * ResourceAccount rejects current outside [0, maximum] at construction.
    * OP_CLAMP requires amount 0.0 (nonzero raises ValueError); pins current
      into [0, maximum] with reason "clamped"/"noop".
    * ResourceLedger.run applies in (time, tier, sequence, insertion) order,
      returns receipts for those events in applied order; receipts() returns
      ALL receipts including prior apply() calls.
"""

import itertools

import pytest

from src.calculator.resource_ledger import (
    OP_CLAMP,
    OP_GAIN,
    OP_MAX_INCREASE,
    OP_REFUND,
    OP_REGEN,
    OP_SPEND,
    RESOURCE_KIND_MANA,
    EnlightenDeclaration,
    ManaflowDeclaration,
    ManaflowLedger,
    ResourceAccount,
    ResourceEvent,
    ResourceLedger,
    enlighten_schedule,
)

# ---------------------------------------------------------------------------
# Helpers (local to this file; no engine imports)
# ---------------------------------------------------------------------------


def _event(
    operation,
    amount,
    *,
    time=0.0,
    sequence=0,
    tier=0.0,
    source="test",
    owner="Ahri",
    atoms=(),
    detail=None,
):
    """Keyword-constructed mana event with sane defaults."""
    return ResourceEvent(
        owner=owner,
        kind=RESOURCE_KIND_MANA,
        operation=operation,
        amount=amount,
        time=time,
        source=source,
        sequence=sequence,
        tier=tier,
        atoms=atoms,
        detail=detail if detail is not None else {},
    )


def _account(*, maximum=1000.0, current=None, owner="Ahri"):
    return ResourceAccount(owner, maximum=maximum, current=current)


def _ledger(*, maximum=1000.0, current=None, owner="Ahri"):
    return ResourceLedger(owner, maximum=maximum, current=current)


#: Tear's sourced rule as a fixture: the kernel is standalone, so the
#: numbers are supplied here rather than read from the item registry.
_TEAR_RULE = {
    "item": "Tear of the Goddess",
    "charge_interval": 8.0,
    "max_charges": 4,
    "bonus_mana_per_trigger": 3.0,
    "bonus_mana_per_champion": 6.0,
    "bonus_mana_max": 360.0,
    "on_hit_charge": False,
    "source_url": "https://wiki.leagueoflegends.com/en-us/Tear_of_the_Goddess",
    "source_revision_id": 4026380,
    "atom": ("stat.mana", "f8e104e5f65ff397"),
}


def _declaration(**decl_kw):
    return ManaflowDeclaration(**{**_TEAR_RULE, **decl_kw})


def _tear(*, owner="Ahri", authored=0.0, **decl_kw):
    return ManaflowLedger(
        _declaration(**decl_kw), owner=owner, authored_bonus_mana=authored
    )


def _assert_json_safe(value, path="$"):
    """Assert a value contains only JSON-safe primitives.

    Tuples are permitted (the kernel models atoms as tuples; they convert to
    lists under json.dumps).
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return
    if isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            _assert_json_safe(item, f"{path}[{i}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            assert isinstance(key, str), f"{path}: non-string key {key!r}"
            _assert_json_safe(item, f"{path}.{key}")
        return
    raise AssertionError(f"{path}: not JSON-safe ({type(value).__name__})")


def _tick_index(event):
    """Tick index carried in an Enlighten gain event's detail (1-based)."""
    for key in ("tick", "tick_index"):
        if key in event.detail:
            return event.detail[key]
    raise AssertionError(
        f"enlighten event detail lacks a tick index; keys={sorted(event.detail)}"
    )


# ---------------------------------------------------------------------------
# KERNEL — ResourceEvent / ResourceAccount / ResourceLedger (matrix 1-16)
# ---------------------------------------------------------------------------


class TestKernel:
    # 1. spend: accepted spend reduces current by amount, receipt records before/after.
    def test_01_spend_reduces_current_and_records_before_after(self):
        acct = _account(current=500.0)
        receipt = acct.apply(_event(OP_SPEND, 200.0))
        assert receipt.accepted is True
        assert receipt.current_before == pytest.approx(500.0)
        assert receipt.current_after == pytest.approx(300.0)
        assert acct.current == pytest.approx(300.0)
        assert receipt.amount == pytest.approx(200.0)
        assert receipt.operation == OP_SPEND

    # 2. insufficient denial: spend > current -> accepted False, reason
    #    "insufficient_resource", current unchanged.
    def test_02_insufficient_spend_denied_current_unchanged(self):
        acct = _account(current=500.0)
        receipt = acct.apply(_event(OP_SPEND, 600.0))
        assert receipt.accepted is False
        assert receipt.reason == "insufficient_resource"
        assert receipt.current_before == pytest.approx(500.0)
        assert receipt.current_after == pytest.approx(500.0)
        assert acct.current == pytest.approx(500.0)

    def test_02b_spend_equal_to_current_drains_to_zero(self):
        acct = _account(current=500.0)
        receipt = acct.apply(_event(OP_SPEND, 500.0))
        assert receipt.accepted is True
        assert acct.current == pytest.approx(0.0)

    # 3. gain: gain clamps at maximum (CAPPED receipt when exceeding); under
    #    max -> exact amount.
    def test_03_gain_exact_under_max_and_capped_over(self):
        acct = _account(current=400.0)
        ok = acct.apply(_event(OP_GAIN, 100.0))
        assert ok.accepted is True
        assert acct.current == pytest.approx(500.0)
        assert ok.current_after == pytest.approx(500.0)

        capped = acct.apply(_event(OP_GAIN, 800.0))  # 500 + 800 > 1000
        assert capped.accepted is True
        assert capped.reason == "CAPPED"
        assert capped.current_after == pytest.approx(1000.0)
        assert acct.current == pytest.approx(1000.0)

    # 4. refund: refund returns mana, clamps at maximum.
    def test_04_refund_returns_mana_and_clamps(self):
        acct = _account(current=500.0)
        ok = acct.apply(_event(OP_REFUND, 300.0))
        assert ok.accepted is True
        assert acct.current == pytest.approx(800.0)

        capped = acct.apply(_event(OP_REFUND, 800.0))  # 800 + 800 > 1000
        assert capped.accepted is True
        assert capped.reason == "CAPPED"
        assert acct.current == pytest.approx(1000.0)

    # 5. regen: regen tick adds amount, clamps; ledger-level: a run with
    #    regen ops between spends reproduces expected currents.
    def test_05_regen_tick_adds_and_clamps(self):
        acct = _account(current=400.0)
        ok = acct.apply(_event(OP_REGEN, 50.0))
        assert ok.accepted is True
        assert acct.current == pytest.approx(450.0)

        capped = acct.apply(_event(OP_REGEN, 800.0))  # 450 + 800 > 1000
        assert capped.accepted is True
        assert capped.reason == "CAPPED"
        assert acct.current == pytest.approx(1000.0)

    def test_05b_ledger_run_regen_between_spends(self):
        ledger = _ledger(current=500.0)
        events = [
            _event(OP_SPEND, 200.0, time=1.0),
            _event(OP_REGEN, 50.0, time=2.0),
            _event(OP_SPEND, 100.0, time=3.0),
            _event(OP_REGEN, 50.0, time=4.0),
        ]
        receipts = ledger.run(events)
        assert len(receipts) == 4
        expected = [(500.0, 300.0), (300.0, 350.0), (350.0, 250.0), (250.0, 300.0)]
        for receipt, (before, after) in zip(receipts, expected, strict=False):
            assert receipt.current_before == pytest.approx(before)
            assert receipt.current_after == pytest.approx(after)
        assert ledger.receipts()[-1].current_after == pytest.approx(300.0)

    # 6. max increase: maximum grows by amount, current unchanged (the
    #    sourced Tear rule), current_after == current_before.
    def test_06_max_increase_grows_maximum_current_unchanged(self):
        acct = _account(current=500.0)
        receipt = acct.apply(_event(OP_MAX_INCREASE, 6.0))
        assert acct.maximum == pytest.approx(1006.0)
        assert acct.current == pytest.approx(500.0)
        assert receipt.current_after == pytest.approx(receipt.current_before)
        assert receipt.maximum_before == pytest.approx(1000.0)
        assert receipt.maximum_after == pytest.approx(1006.0)

    # 7. cap / overcap: gain beyond maximum capped (receipt CAPPED,
    #    current_after == maximum).
    def test_07_overcap_gain_capped(self):
        acct = _account(current=990.0)
        receipt = acct.apply(_event(OP_GAIN, 50.0))
        assert receipt.accepted is True
        assert receipt.reason == "CAPPED"
        assert receipt.current_after == pytest.approx(1000.0)
        assert acct.current == pytest.approx(1000.0)

    # 8. zero: amount 0.0 op accepted as no-op for gain/spend/regen.
    def test_08_zero_amounts_accepted_noop(self):
        acct = _account(current=500.0)
        for op in (OP_GAIN, OP_SPEND, OP_REFUND, OP_REGEN, OP_MAX_INCREASE):
            receipt = acct.apply(_event(op, 0.0))
            assert receipt.accepted is True, op
            assert receipt.current_after == pytest.approx(500.0), op
        assert acct.current == pytest.approx(500.0)
        assert acct.maximum == pytest.approx(1000.0)

        # spend 0 with empty pool is still an accepted no-op (not denied)
        empty = _account(current=0.0)
        receipt = empty.apply(_event(OP_SPEND, 0.0))
        assert receipt.accepted is True
        assert empty.current == pytest.approx(0.0)

    # 9. unknown kind: account/event kind != "mana" -> ValueError.
    def test_09_unknown_kind_raises(self):
        with pytest.raises(ValueError):
            ResourceAccount("Ahri", maximum=1000.0, kind="energy")
        with pytest.raises(ValueError):
            ResourceLedger("Ahri", maximum=1000.0, kind="health")
        acct = _account()
        bad = ResourceEvent(owner="Ahri", kind="energy", operation=OP_GAIN, amount=10.0)
        with pytest.raises(ValueError):
            acct.apply(bad)

    # 10. unknown operation: op not in the typed set -> ValueError.
    def test_10_unknown_operation_raises(self):
        acct = _account()
        bad = _event("heal", 10.0)
        with pytest.raises(ValueError):
            acct.apply(bad)
        ledger = _ledger()
        with pytest.raises(ValueError):
            ledger.apply(bad)

    # 11. invalid amount: negative or nan/inf -> ValueError.
    @pytest.mark.parametrize(
        "operation", [OP_GAIN, OP_SPEND, OP_REFUND, OP_REGEN, OP_MAX_INCREASE]
    )
    @pytest.mark.parametrize(
        "amount", [-1.0, float("nan"), float("inf"), float("-inf")]
    )
    def test_11_invalid_amounts_raise(self, operation, amount):
        acct = _account()
        with pytest.raises(ValueError):
            acct.apply(_event(operation, amount))

    # 12. wrong owner: event owner != account owner -> ValueError.
    def test_12_wrong_owner_raises(self):
        acct = _account(owner="Ahri")
        with pytest.raises(ValueError):
            acct.apply(_event(OP_SPEND, 10.0, owner="Lux"))
        ledger = _ledger(owner="Ahri")
        with pytest.raises(ValueError):
            ledger.apply(_event(OP_SPEND, 10.0, owner="Lux"))

    # 13. stable same-time order: events at the same (time, tier) ordered by
    #     sequence; regen/restore before spend at the same timestamp when tier
    #     lower; assert exact receipt order.
    def test_13_same_time_order_by_sequence_and_tier(self):
        ledger = _ledger(current=300.0)
        events = [
            _event(OP_GAIN, 100.0, time=10.0, tier=0.0, sequence=0, source="restore"),
            _event(OP_REGEN, 50.0, time=10.0, tier=0.0, sequence=1),
            _event(OP_SPEND, 200.0, time=10.0, tier=1.0, sequence=0),
        ]
        receipts = ledger.run(events)
        assert [r.operation for r in receipts] == [OP_GAIN, OP_REGEN, OP_SPEND]
        assert [r.sequence for r in receipts] == [0, 1, 0]
        assert [r.tier for r in receipts] == [0.0, 0.0, 1.0]
        # restore -> regen -> spend: 300 -> 400 -> 450 -> 250
        assert receipts[-1].current_after == pytest.approx(250.0)
        assert receipts[-1].accepted is True  # spend saw the restored mana

    def test_13b_same_key_events_keep_insertion_order(self):
        # Same (time, tier, sequence): insertion order is the tie-break.
        # gain first (capped at max) then spend -> 997; reversed -> 1000.
        ledger = _ledger(current=1000.0)
        receipts = ledger.run(
            [
                _event(OP_GAIN, 5.0, time=20.0, tier=0.0, sequence=0),
                _event(OP_SPEND, 3.0, time=20.0, tier=0.0, sequence=0),
            ]
        )
        assert [r.operation for r in receipts] == [OP_GAIN, OP_SPEND]
        assert receipts[0].reason == "CAPPED"
        assert receipts[1].current_after == pytest.approx(997.0)

    # 14. deterministic rerun: run the same event list twice -> identical
    #     receipts (compare .public() rows).
    def test_14_deterministic_rerun_identical_receipts(self):
        events = [
            _event(OP_REGEN, 100.0, time=1.0, sequence=0),
            _event(OP_SPEND, 200.0, time=1.0, sequence=1),
            _event(OP_GAIN, 50.0, time=2.0),
            _event(OP_MAX_INCREASE, 10.0, time=3.0),
            _event(OP_REFUND, 700.0, time=4.0),
            _event(OP_CLAMP, 0.0, time=5.0),
        ]
        # deliberate input scramble: run() must sort internally
        scrambled = [events[4], events[2], events[1], events[0], events[5], events[3]]
        first = _ledger(current=500.0).run(scrambled)
        second = _ledger(current=500.0).run(scrambled)
        assert len(first) == len(events) == 6
        assert [r.public() for r in first] == [r.public() for r in second]
        assert first == second  # dataclass equality as well

    # 15. clamp op: explicit OP_CLAMP pins current into [0, maximum] with receipt.
    def test_15_clamp_pins_current_with_receipt(self):
        acct = _account(current=500.0)
        receipt = acct.apply(_event(OP_CLAMP, 0.0))
        assert receipt.accepted is True
        assert receipt.operation == OP_CLAMP
        assert receipt.current_after == pytest.approx(500.0)  # already in range
        assert 0.0 <= acct.current <= acct.maximum

        at_max = _account(current=1000.0)
        at_max.apply(_event(OP_CLAMP, 0.0))
        assert at_max.current == pytest.approx(1000.0)

        at_zero = _account(current=0.0)
        at_zero.apply(_event(OP_CLAMP, 0.0))
        assert at_zero.current == pytest.approx(0.0)

    def test_15b_clamp_amount_must_be_zero(self):
        acct = _account()
        with pytest.raises(ValueError):
            acct.apply(_event(OP_CLAMP, 5.0))
        with pytest.raises(ValueError):
            acct.apply(_event(OP_CLAMP, -1.0))

    # 16. account starts: current defaults to maximum when current=None;
    #     base/bonus properties correct after max_increase ops.
    def test_16_account_starts_and_base_bonus_maximum(self):
        acct = _account(maximum=1000.0)  # current=None
        assert acct.current == pytest.approx(1000.0)
        assert acct.maximum == pytest.approx(1000.0)
        assert acct.base_maximum == pytest.approx(1000.0)
        assert acct.bonus_maximum == pytest.approx(0.0)

        acct.apply(_event(OP_MAX_INCREASE, 6.0))
        acct.apply(_event(OP_MAX_INCREASE, 4.0))
        assert acct.maximum == pytest.approx(1010.0)
        assert acct.base_maximum == pytest.approx(1000.0)
        assert acct.bonus_maximum == pytest.approx(10.0)
        # sourced Tear rule: current stays where it was (1000 == old max)
        assert acct.current == pytest.approx(1000.0)

        explicit = _account(maximum=1000.0, current=300.0)
        assert explicit.current == pytest.approx(300.0)
        assert explicit.bonus_maximum == pytest.approx(0.0)

    def test_16b_construction_rejects_out_of_range_current(self):
        with pytest.raises(ValueError):
            _account(maximum=1000.0, current=1500.0)
        with pytest.raises(ValueError):
            _account(maximum=1000.0, current=-5.0)


# ---------------------------------------------------------------------------
# TEAR — ManaflowDeclaration / ManaflowLedger (matrix 17-29)
# ---------------------------------------------------------------------------


class TestTear:
    # 17. initial progress: authored_bonus_mana=120 -> bonus_total starts at
    #     120, cap room = 240; hits grant until cap.
    def test_17_initial_progress_hits_grant_until_cap(self):
        tear = _tear(authored=120.0)
        assert tear.bonus_total == pytest.approx(120.0)
        assert tear.cap == pytest.approx(360.0)
        assert tear.cap - tear.bonus_total == pytest.approx(240.0)

        # 40 champion hits every 8s (charge refills each window) -> +240
        granted = 0.0
        for k in range(40):
            receipt, event = tear.hit(time=8.0 * k, hit_identity=f"cast-{k}")
            assert receipt["accepted"] is True, receipt
            assert receipt["reason"] == "charge_consumed"
            assert event is not None
            assert event.amount == pytest.approx(6.0)
            granted += event.amount
        assert tear.bonus_total == pytest.approx(360.0)
        assert tear.use_count == 40
        assert granted == pytest.approx(240.0)
        assert tear.bonus_total - 120.0 == pytest.approx(granted)

        # one more hit at the cap: denied, no event, no charge consumed
        receipt, event = tear.hit(time=320.0, hit_identity="cast-over")
        assert receipt["accepted"] is False
        assert receipt["reason"] == "cap_reached"
        assert event is None
        assert tear.use_count == 40
        assert tear.bonus_total == pytest.approx(360.0)

    # 18. champion hit: proven hit with identity consumes charge, grants 6
    #     (per_champion), returns max_increase event with amount 6 and atoms
    #     carrying the declaration atom.
    def test_18_champion_hit_grants_per_champion_with_atoms(self):
        declaration = _declaration()
        tear = ManaflowLedger(declaration, owner="Ahri")
        receipt, event = tear.hit(time=0.0, hit_identity="q-1", target_kind="champion")
        assert receipt["accepted"] is True
        assert receipt["reason"] == "charge_consumed"
        assert receipt["bonus_delta"] == pytest.approx(6.0)
        assert receipt["bonus_total"] == pytest.approx(6.0)
        assert receipt["use_count"] == 1
        assert receipt["charge_consumed"] is True
        assert receipt["time"] == pytest.approx(0.0)
        assert receipt["target_kind"] == "champion"
        assert receipt["hit_identity"] == "q-1"
        assert receipt["atom"] == declaration.atom

        assert event is not None
        assert event.operation == OP_MAX_INCREASE
        assert event.amount == pytest.approx(6.0)
        assert event.owner == "Ahri"
        assert event.kind == RESOURCE_KIND_MANA
        assert declaration.atom in event.atoms

    # 19. non-champion if representable: target_kind="minion" grants
    #     per_trigger (3).
    def test_19_minion_hit_grants_per_trigger(self):
        tear = _tear()
        receipt, event = tear.hit(time=0.0, hit_identity="wave-1", target_kind="minion")
        assert receipt["accepted"] is True
        assert receipt["bonus_delta"] == pytest.approx(3.0)
        assert event is not None
        assert event.amount == pytest.approx(3.0)

    # 20. cadence: charges_available_at(0)=1, at 7.999=1, at 8.0=2, at 16.0=3;
    #     capped at max_charges (e.g., at 100s -> 4).
    def test_20_charge_cadence_and_refill(self):
        tear = _tear()  # fresh: use_count 0
        assert tear.charges_available_at(0.0) == 1
        assert tear.charges_available_at(7.999) == 1
        assert tear.charges_available_at(8.0) == 2
        assert tear.charges_available_at(16.0) == 3
        assert tear.charges_available_at(100.0) == 4  # capped at max_charges
        assert tear.charges_available_at(-1.0) == 0  # floored at 0

        # after a hit at t=0 the pool is spent and refills at the next window
        tear.hit(time=0.0, hit_identity="q")
        assert tear.charges_available_at(7.999) == 0
        assert tear.charges_available_at(8.0) == 1
        assert tear.charges_available_at(100.0) == 4  # still capped

    # 21. stored-charge max: more hits than stored charges -> denial receipts
    #     "no_charge_available" after the stored pool is spent; use_count
    #     equals the number of charges that were stored.
    def test_21_stored_charge_pool_spent_denials(self):
        tear = _tear()
        assert tear.stored_charges == 1
        first, event = tear.hit(time=0.0, hit_identity="a")
        assert first["accepted"] is True
        assert event is not None
        for i in range(4):  # hits 2-5 at the same instant: pool is spent
            receipt, event = tear.hit(time=0.0, hit_identity=f"spam-{i}")
            assert receipt["accepted"] is False
            assert receipt["reason"] == "no_charge_available"
            assert receipt["charge_consumed"] is False
            assert event is None
        assert tear.use_count == 1
        assert tear.stored_charges == 0  # banked(0)=1 minus 1 used
        assert tear.bonus_total == pytest.approx(6.0)

    # 22. multiple hits: sequential hits consume sequential charges (times 0,
    #     8, 16, 24 -> 4 hits ok; a 5th before the next refill is denied).
    def test_22_sequential_hits_consume_sequential_charges(self):
        tear = _tear()
        for t in (0.0, 8.0, 16.0, 24.0):
            receipt, event = tear.hit(time=t, hit_identity=f"seq-{t}")
            assert receipt["accepted"] is True, receipt
            assert event is not None
        assert tear.use_count == 4
        assert tear.bonus_total == pytest.approx(24.0)
        assert tear.stored_charges == 0  # banked(24)=4, 4 used

        # 5th hit before the t=32 refill: denied
        receipt, event = tear.hit(time=24.0, hit_identity="seq-5th")
        assert receipt["accepted"] is False
        assert receipt["reason"] == "no_charge_available"
        assert event is None

        # the refill window: banked becomes 5 at t=32 -> one charge available
        receipt, event = tear.hit(time=32.0, hit_identity="seq-refill")
        assert receipt["accepted"] is True
        assert event is not None
        assert event.amount == pytest.approx(6.0)
        assert tear.use_count == 5

    # 23. cap: hits stop granting at 360 total (authored + granted) with
    #     "cap_reached" receipts; max_increase events stop. A charge can be
    #     available at the exact cap: the hit is denied and NO charge is
    #     consumed (RLM-1 pinned decision).
    def test_23_cap_reached_denial_no_charge_consumed(self):
        tear = _tear(authored=355.0)  # 5 mana of room
        receipt, event = tear.hit(time=0.0, hit_identity="near-cap")
        assert receipt["accepted"] is True
        assert receipt["bonus_delta"] == pytest.approx(5.0)  # min(6, 5)
        assert event is not None
        assert event.amount == pytest.approx(5.0)
        assert tear.bonus_total == pytest.approx(360.0)

        # t=8: a charge IS available (banked 2, used 1) but the cap binds
        receipt, event = tear.hit(time=8.0, hit_identity="at-cap")
        assert receipt["accepted"] is False
        assert receipt["reason"] == "cap_reached"
        assert receipt["charge_consumed"] is False
        assert receipt["bonus_delta"] == pytest.approx(0.0)
        assert event is None
        assert tear.use_count == 1  # no charge consumed at the cap
        assert tear.bonus_total == pytest.approx(360.0)

    # 24. denied cast: a cast whose spend op was denied (insufficient mana)
    #     never produces a Tear hit (driver-side rule: the identity is only
    #     supplied for accepted casts). Missing identity is rejected.
    def test_24_denied_cast_never_hits_and_missing_identity(self):
        # (a) a denied spend on the ledger -> no hit is ever driven
        ledger = _ledger(current=100.0)
        denial = ledger.apply(_event(OP_SPEND, 300.0, time=0.0))
        assert denial.accepted is False
        assert denial.reason == "insufficient_resource"

        tear = _tear()
        # the driver never calls hit() for the denied cast -> no consumption,
        # no grants (no hit receipts exist at all)
        assert tear.use_count == 0
        assert tear.bonus_total == pytest.approx(0.0)
        assert tear.charges_available_at(0.0) == 1

        # (b) a later proven hit still consumes normally (denied cast did not
        #     block or consume anything)
        receipt, event = tear.hit(time=0.0, hit_identity="proven-cast")
        assert receipt["accepted"] is True
        assert event is not None
        assert tear.use_count == 1

        # (c) missing/empty hit_identity -> denied, no charge consumed, no event
        tear2 = _tear()
        for bad_identity in ("", None):
            receipt, event = tear2.hit(time=0.0, hit_identity=bad_identity)
            assert receipt["accepted"] is False
            assert receipt["reason"] == "missing_hit_identity"
            assert receipt["charge_consumed"] is False
            assert event is None
        assert tear2.use_count == 0
        assert tear2.bonus_total == pytest.approx(0.0)

    # 25. no proven hit: no cast timeline -> no hits -> no grants;
    #     charges_available stays 1; bonus_total unchanged.
    def test_25_no_hits_no_grants(self):
        tear = _tear(authored=50.0)
        assert tear.use_count == 0
        assert tear.bonus_total == pytest.approx(50.0)
        assert tear.charges_available_at(0.0) == 1
        assert tear.stored_charges == 1
        assert tear.cap == pytest.approx(360.0)

    # 26. same-time hits: two hits at the same time with sequence 0 and 1 ->
    #     deterministic order, both consume from the same charge pool (second
    #     denied if only 1 charge).
    def test_26_same_time_hits_deterministic_pool(self):
        tear = _tear()
        first, ev1 = tear.hit(time=5.0, hit_identity="a", sequence=0)
        second, ev2 = tear.hit(time=5.0, hit_identity="b", sequence=1)
        assert first["accepted"] is True
        assert ev1 is not None
        assert second["accepted"] is False
        assert second["reason"] == "no_charge_available"
        assert ev2 is None
        assert tear.use_count == 1

        # reproducible: identical inputs on a fresh flow -> identical outcomes
        again = _tear()
        r1, _ = again.hit(time=5.0, hit_identity="a", sequence=0)
        r2, _ = again.hit(time=5.0, hit_identity="b", sequence=1)
        assert r1 == first
        assert r2 == second

    # 27. evidence-backed current-and-max behavior: after applying a
    #     successful hit's max_increase event to a ResourceAccount, maximum
    #     grew by 6 and current stayed identical.
    def test_27_max_increase_event_applied_to_account(self):
        tear = _tear(owner="Ahri")
        _, event = tear.hit(time=0.0, hit_identity="q")
        assert event is not None
        acct = ResourceAccount("Ahri", maximum=1000.0, current=500.0)
        receipt = acct.apply(event)
        assert acct.maximum == pytest.approx(1006.0)
        assert acct.current == pytest.approx(500.0)
        assert receipt.maximum_before == pytest.approx(1000.0)
        assert receipt.maximum_after == pytest.approx(1006.0)
        assert receipt.current_before == pytest.approx(500.0)
        assert receipt.current_after == pytest.approx(500.0)

    # 28. receipt: hit receipt carries accepted, reason, charge/use/bonus
    #     fields, amount, time, source, atoms; JSON-safe.
    def test_28_hit_receipt_fields_and_json_safety(self):
        declaration = _declaration()
        tear = ManaflowLedger(declaration, owner="Ahri")
        first, _ = tear.hit(time=0.0, hit_identity="q-1")
        second, _ = tear.hit(time=8.0, hit_identity="q-2")
        denied, _ = tear.hit(time=8.0, hit_identity="q-3")

        expected_keys = {
            "time",
            "source",
            "accepted",
            "reason",
            "target_kind",
            "hit_identity",
            "charge_consumed",
            "use_count",
            "bonus_total",
            "bonus_delta",
            "cap",
            "atom",
        }
        for receipt in (first, second, denied):
            assert expected_keys <= set(receipt), sorted(receipt)
            _assert_json_safe(receipt)
            assert receipt["source"]
            assert receipt["atom"] == declaration.atom
            assert receipt["cap"] == pytest.approx(360.0)

        assert first["accepted"] is True
        assert first["reason"] == "charge_consumed"
        assert first["use_count"] == 1
        assert first["bonus_total"] == pytest.approx(6.0)
        assert first["bonus_delta"] == pytest.approx(6.0)
        assert first["charge_consumed"] is True

        assert second["use_count"] == 2
        assert second["bonus_total"] == pytest.approx(12.0)

        assert denied["accepted"] is False
        assert denied["reason"] == "no_charge_available"
        assert denied["charge_consumed"] is False
        assert denied["bonus_delta"] == pytest.approx(0.0)

    # 29. parity: total granted bonus mana from max_increase events ==
    #     ManaflowLedger.bonus_total - authored (for a sequence of hits), and
    #     never exceeds cap.
    def test_29_grant_parity_with_bonus_total(self):
        tear = _tear(authored=0.0)
        granted = 0.0
        for t in (0.0, 8.0, 16.0, 24.0):
            _, event = tear.hit(time=t, hit_identity=f"h-{t}")
            assert event is not None
            granted += event.amount
            assert tear.bonus_total <= tear.cap
        assert granted == pytest.approx(24.0)
        assert tear.bonus_total - 0.0 == pytest.approx(granted)
        assert tear.bonus_total <= tear.cap


# ---------------------------------------------------------------------------
# LOST CHAPTER — EnlightenDeclaration / enlighten_schedule (matrix 30-39)
# ---------------------------------------------------------------------------


class TestEnlighten:
    # 30. absent: no level-up event -> enlighten_schedule not invoked -> no
    #     gain ops (schedule construction is the only trigger; helper
    #     assertion that no events exist otherwise).
    def test_30_no_level_up_no_gain_ops(self):
        ledger = _ledger(current=500.0)
        receipts = ledger.run(
            [
                _event(OP_SPEND, 100.0, time=1.0),
                _event(OP_REGEN, 50.0, time=2.0),
            ]
        )
        assert len(receipts) == 2
        assert all(r.operation != OP_GAIN for r in receipts)
        assert all(r.operation != OP_GAIN for r in ledger.receipts())

        # constructing a schedule is a pure function: it emits events but
        # never touches a ledger/account
        schedule = enlighten_schedule(
            level_up_time=2.0, maximum_mana=1000.0, declaration=EnlightenDeclaration()
        )
        assert len(schedule) == 3
        assert ledger.receipts()[-1].operation == OP_REGEN  # unchanged

    # 31. explicit level-up: schedule at t=2 with max 1000 -> 3 gain events
    #     at 3.0, 4.0, 5.0 each 66.666... (1000*0.2/3), amounts sum to 200.
    def test_31_explicit_level_up_schedule(self):
        events = enlighten_schedule(
            level_up_time=2.0, maximum_mana=1000.0, declaration=EnlightenDeclaration()
        )
        assert len(events) == 3
        assert [e.time for e in events] == pytest.approx([3.0, 4.0, 5.0])
        for e in events:
            assert e.operation == OP_GAIN
            assert e.kind == RESOURCE_KIND_MANA
            assert e.amount == pytest.approx(1000.0 * 0.2 / 3)
        assert sum(e.amount for e in events) == pytest.approx(200.0)

    # 32. 20% amount: each tick amount == maximum_mana * restore_percent/100 /
    #     ticks; total == 20%.
    def test_32_twenty_percent_tick_amounts(self):
        decl = EnlightenDeclaration(restore_percent=20.0, duration_seconds=3.0, ticks=3)
        events = enlighten_schedule(
            level_up_time=1.0, maximum_mana=1000.0, declaration=decl
        )
        for e in events:
            assert e.amount == pytest.approx(1000.0 * 20.0 / 100.0 / 3)
        assert sum(e.amount for e in events) == pytest.approx(1000.0 * 0.20)

        custom = EnlightenDeclaration(
            restore_percent=25.0, duration_seconds=4.0, ticks=4
        )
        events = enlighten_schedule(
            level_up_time=0.0, maximum_mana=800.0, declaration=custom
        )
        assert len(events) == 4
        for e in events:
            assert e.amount == pytest.approx(800.0 * 25.0 / 100.0 / 4)  # 50.0
        assert sum(e.amount for e in events) == pytest.approx(800.0 * 0.25)  # 200.0

    # 33. 3-second schedule: tick times land at level_up_time + k*duration/ticks
    #     for k in 1..ticks (RLM-1-pinned formula). Last tick completes exactly
    #     at level_up_time + duration; the first-to-last span is
    #     duration*(ticks-1)/ticks (= 2.0s for the default 3s/3-tick schedule).
    #     NOTE: the matrix wording "span exactly duration_seconds from first to
    #     last tick" conflicts with the pinned formula; the pinned formula wins
    #     (see the ambiguity note at the end of this file).
    def test_33_three_second_schedule_times(self):
        decl = EnlightenDeclaration(duration_seconds=3.0, ticks=3)
        events = enlighten_schedule(
            level_up_time=2.0, maximum_mana=1000.0, declaration=decl
        )
        step = decl.duration_seconds / decl.ticks
        for k, e in enumerate(events, start=1):
            assert e.time == pytest.approx(2.0 + k * step)
        assert events[0].time == pytest.approx(2.0 + step)  # first tick at +1s
        assert events[-1].time == pytest.approx(
            2.0 + decl.duration_seconds
        )  # last at +3s
        assert events[-1].time - events[0].time == pytest.approx(
            decl.duration_seconds * (decl.ticks - 1) / decl.ticks
        )

    # 34. near-full cap: applying the gain events to an account near maximum
    #     -> each tick clamps (CAPPED receipts), current never exceeds maximum.
    def test_34_near_full_cap_each_tick_clamps(self):
        events = enlighten_schedule(
            level_up_time=2.0, maximum_mana=1000.0, declaration=EnlightenDeclaration()
        )
        acct = ResourceAccount(events[0].owner, maximum=1000.0, current=990.0)
        receipts = [acct.apply(e) for e in events]
        assert len(receipts) == 3
        for receipt in receipts:
            assert receipt.accepted is True
            assert receipt.reason == "CAPPED"
            assert receipt.current_after == pytest.approx(1000.0)
            assert receipt.current_after <= receipt.maximum_after
        assert acct.current == pytest.approx(1000.0)

    # 35. multiple level-ups only if sourced and representable: the kernel
    #     exposes ONE level-up per fight (enlighten_schedule takes one time);
    #     schedule() is the only trigger and validates its inputs.
    def test_35_single_trigger_contract_and_validation(self):
        decl = EnlightenDeclaration()
        for bad_time in (-1.0, -0.001):
            with pytest.raises(ValueError):
                enlighten_schedule(
                    level_up_time=bad_time, maximum_mana=1000.0, declaration=decl
                )
        for bad_max in (float("nan"), float("inf"), float("-inf")):
            with pytest.raises(ValueError):
                enlighten_schedule(
                    level_up_time=2.0, maximum_mana=bad_max, declaration=decl
                )
        # level_up_time == 0 is a valid single level-up timing
        events = enlighten_schedule(
            level_up_time=0.0, maximum_mana=1000.0, declaration=decl
        )
        assert [e.time for e in events] == pytest.approx([1.0, 2.0, 3.0])

    # 36. same-time cast order: gain tick at t and spend at t with tier 0 vs 1
    #     -> gain applies first (spend sees the restored mana).
    def test_36_same_time_gain_before_spend_by_tier(self):
        events = enlighten_schedule(
            level_up_time=2.0, maximum_mana=1000.0, declaration=EnlightenDeclaration()
        )
        ledger = ResourceLedger(events[0].owner, maximum=1000.0, current=100.0)
        gain_tick = events[1]  # t=4.0, tier 0
        spend = _event(
            OP_SPEND, 150.0, time=4.0, tier=1.0, sequence=0, owner=events[0].owner
        )
        receipts = ledger.run([spend, gain_tick])  # deliberate reverse input
        assert [r.operation for r in receipts] == [OP_GAIN, OP_SPEND]
        assert receipts[1].accepted is True  # 100 + 66.67 >= 150
        assert receipts[1].current_after == pytest.approx(
            100.0 + 66.66666666666667 - 150.0
        )

    # 37. later cast enabled: a cast that would be denied before the level-up
    #     is accepted after the ticks land.
    def test_37_later_cast_enabled_after_ticks(self):
        events = enlighten_schedule(
            level_up_time=2.0, maximum_mana=1000.0, declaration=EnlightenDeclaration()
        )
        ledger = ResourceLedger(events[0].owner, maximum=1000.0, current=500.0)
        receipts = ledger.run(
            [
                _event(OP_SPEND, 600.0, time=0.0, owner=events[0].owner),
                _event(OP_SPEND, 600.0, time=2.5, owner=events[0].owner),
                *events,  # ticks at 3.0 / 4.0 / 5.0
                _event(OP_SPEND, 600.0, time=6.0, owner=events[0].owner),
            ]
        )
        assert len(receipts) == 6
        assert receipts[0].accepted is False  # denied before level-up
        assert receipts[0].reason == "insufficient_resource"
        assert receipts[1].accepted is False  # still denied before first tick
        assert receipts[2].operation == OP_GAIN
        assert receipts[-1].accepted is True  # 500 + 200 >= 600 after ticks
        assert ledger.receipts()[-1].current_after == pytest.approx(100.0)

    # 38. receipt: gain events carry source "Lost Chapter — Enlighten",
    #     operation OP_GAIN, and the tick index in detail; receipts after
    #     apply show before/after.
    def test_38_enlighten_event_and_receipt_fields(self):
        events = enlighten_schedule(
            level_up_time=2.0, maximum_mana=1000.0, declaration=EnlightenDeclaration()
        )
        for k, e in enumerate(events, start=1):
            assert e.source == "Lost Chapter — Enlighten"
            assert e.operation == OP_GAIN
            assert _tick_index(e) == k  # 1-based tick index in detail

        acct = ResourceAccount(events[0].owner, maximum=1000.0, current=700.0)
        receipts = [acct.apply(e) for e in events]
        expected = [700.0, 766.6666666666666, 833.3333333333333]
        for receipt, before in zip(receipts, expected, strict=False):
            assert receipt.current_before == pytest.approx(before)
            assert receipt.current_after == pytest.approx(before + 66.66666666666667)
        assert acct.current == pytest.approx(900.0)

    def test_38b_schedule_owner_keyword_propagates(self):
        decl = EnlightenDeclaration()
        events = enlighten_schedule(
            level_up_time=1.0, maximum_mana=1000.0, declaration=decl, owner="Ahri"
        )
        assert all(e.owner == "Ahri" for e in events)
        default_events = enlighten_schedule(
            level_up_time=1.0, maximum_mana=1000.0, declaration=decl
        )
        assert all(e.owner == "" for e in default_events)

    # 39. parity: sum of tick amounts == 20% of the maximum at level-up time.
    def test_39_tick_amount_parity(self):
        decl = EnlightenDeclaration()
        for maximum in (500.0, 1000.0, 1234.5):
            events = enlighten_schedule(
                level_up_time=3.0, maximum_mana=maximum, declaration=decl
            )
            assert sum(e.amount for e in events) == pytest.approx(maximum * 0.20)


# ---------------------------------------------------------------------------
# REGRESSION — contract-level, no engine imports (matrix 40-43)
# ---------------------------------------------------------------------------


class TestRegression:
    # 40. ordinary cast receipts: a ledger run with regen + spends + restores
    #     mirrors the engine's cast_timeline shape (resource_before/restored/
    #     after derivable from receipts).
    def test_40_cast_receipts_mirror_timeline_shape(self):
        ledger = _ledger(current=600.0)
        receipts = ledger.run(
            [
                _event(OP_REGEN, 50.0, time=1.0, source="regen-tick"),
                _event(OP_SPEND, 300.0, time=2.0, source="cast-A"),
                _event(OP_GAIN, 100.0, time=3.0, source="restore"),
                _event(OP_SPEND, 200.0, time=4.0, source="cast-B"),
            ]
        )
        assert len(receipts) == 4
        # resource_before/after chain: each receipt's before == previous after
        for prev, cur in itertools.pairwise(receipts):
            assert cur.current_before == pytest.approx(prev.current_after)
        # derivable timeline shape
        before = [r.current_before for r in receipts]
        after = [r.current_after for r in receipts]
        restored = sum(r.amount for r in receipts if r.operation == OP_GAIN)
        spent = sum(r.amount for r in receipts if r.operation == OP_SPEND)
        assert before == pytest.approx([600.0, 650.0, 350.0, 450.0])
        assert after == pytest.approx([650.0, 350.0, 450.0, 250.0])
        assert restored == pytest.approx(100.0)
        assert spent == pytest.approx(500.0)
        assert after[-1] == pytest.approx(600.0 + 50.0 - 300.0 + 100.0 - 200.0)

    # 41. manaless: ResourceAccount with maximum 0 -> any spend denied;
    #     gains/regen no-op; no exceptions.
    def test_41_manaless_account_fail_closed(self):
        acct = ResourceAccount("Ahri", maximum=0.0)  # current defaults to 0
        assert acct.current == pytest.approx(0.0)

        spend = acct.apply(_event(OP_SPEND, 5.0))
        assert spend.accepted is False
        assert spend.reason == "insufficient_resource"
        assert acct.current == pytest.approx(0.0)

        for op in (OP_GAIN, OP_REGEN, OP_REFUND):
            receipt = acct.apply(_event(op, 100.0))
            assert receipt.accepted is True
            assert receipt.reason == "CAPPED"
            assert acct.current == pytest.approx(0.0)  # no-op in effect

        noop = acct.apply(_event(OP_SPEND, 0.0))
        assert noop.accepted is True
        assert acct.current == pytest.approx(0.0)
        assert acct.maximum == pytest.approx(0.0)

    # 42. Tear plus Lost Chapter: compose both in one ledger run (Tear
    #     max_increase + Enlighten gains + spends) -> order deterministic,
    #     all receipts present, final current within [0, maximum].
    def test_42_tear_and_lost_chapter_composition(self):
        declaration = _declaration()
        tear = ManaflowLedger(declaration, owner="", authored_bonus_mana=0.0)
        _, tear_event = tear.hit(time=2.0, hit_identity="cast-2")
        assert tear_event is not None

        gains = enlighten_schedule(
            level_up_time=4.0, maximum_mana=1000.0, declaration=EnlightenDeclaration()
        )
        # kernel-generated events must share one owner convention
        owners = {tear_event.owner, *(e.owner for e in gains)}
        assert len(owners) == 1, f"kernel events must share one owner, got {owners}"

        ledger = ResourceLedger(tear_event.owner, maximum=1000.0, current=400.0)
        events = [
            _event(OP_SPEND, 300.0, time=1.0, tier=1.0, owner=tear_event.owner),
            tear_event,
            *gains,  # t=5,6,7 (level-up at 4)
            _event(OP_SPEND, 200.0, time=8.0, tier=1.0, owner=tear_event.owner),
        ]
        receipts = ledger.run(events)
        assert len(receipts) == 6
        expected_ops = [OP_SPEND, OP_MAX_INCREASE, OP_GAIN, OP_GAIN, OP_GAIN, OP_SPEND]
        assert [r.operation for r in receipts] == expected_ops
        times = [r.time for r in receipts]
        assert times == sorted(times)  # applied in (time, ...) order
        assert all(r.accepted for r in receipts)

        final = ledger.receipts()[-1]
        assert final.current_after == pytest.approx(
            400.0 - 300.0 + 3 * (1000.0 * 0.2 / 3) - 200.0
        )
        assert 0.0 <= final.current_after <= final.maximum_after
        # Tear side state: one proven hit, one grant
        assert tear.use_count == 1
        assert tear.bonus_total == pytest.approx(6.0)

    # 43. no duplicate events: the same event applied twice produces two
    #     receipts (and rerun determinism holds); a driver that projects
    #     packets from receipts never duplicates (receipt count == event
    #     count after run()).
    def test_43_no_duplicate_events(self):
        ledger = _ledger(current=500.0)
        event = _event(OP_GAIN, 10.0, time=1.0)
        receipts = ledger.run([event, event])
        assert len(receipts) == 2  # one receipt per application, never merged
        assert receipts[0].current_before == pytest.approx(500.0)
        assert receipts[1].current_before == pytest.approx(510.0)
        assert len(ledger.receipts()) == 2

        more = ledger.run([event])
        assert len(more) == 1
        assert len(ledger.receipts()) == 3  # receipts() accumulates everything

        # same input on a fresh ledger -> identical receipts (determinism)
        fresh = _ledger(current=500.0)
        assert fresh.run([event, event]) == receipts


# ---------------------------------------------------------------------------
# Matrix row 44 — comment-only note (no test function by design):
#
# Catalyst is OUT of slice for P3S1 (its behavior is unchanged and already
# covered elsewhere). Catalyst regression coverage lives in
# tests/test_catalyst_resource_ledger.py (P3 package 3A matrix owner) and
# tests/test_item_sustain.py — not here.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Ambiguity / contract-note block (fail-closed notes for RLM-1)
# ---------------------------------------------------------------------------
# Rows that could NOT be written exactly as the matrix worded them, and the
# resolution taken (all resolutions follow RLM-1's binding clarifications):
#
# 1. Row 33 ("tick times span exactly duration_seconds from first to last
#    tick") conflicts with the pinned enlighten_schedule formula
#    (level_up_time + k*duration/ticks, k in 1..ticks): the first-to-last
#    span is duration*(ticks-1)/ticks (2.0s for the default 3s/3-tick
#    schedule), and the LAST tick lands exactly at level_up_time + duration.
#    test_33 asserts the pinned formula. If "span == duration" was intended,
#    the schedule formula (and test_31's pinned times 3.0/4.0/5.0) must
#    change — tell RLM-1 before doing so.
#
# 2. Matrix row 21's wording "use_count == stored charges" is read as
#    "use_count equals the number of charges that were stored (the pool at
#    that time)". Per the clarified formula, the stored_charges property is
#    the AVAILABLE pool (banked - use_count, capped, floored): after the
#    pool is spent at t=0, stored_charges == 0 while use_count == 1.
#
# 3. Matrix row 22's "5th denied": under the clarified refill semantics a
#    5th hit at t>=32 SUCCEEDS (banked reaches 5, one charge refills).
#    test_22 pins "4 hits ok; a 5th before the next refill (t<32) is denied;
#    at t=32 the refilled charge is usable".
#
# 4. OP_CLAMP: amount must be 0.0 (nonzero raises ValueError, per RLM-1).
#    The "clamped" reason is unreachable through the public API (all other
#    ops maintain current within [0, maximum]); test_15 asserts the
#    reachable "noop" in-range behavior only.
#
# 5. enlighten_schedule's tick index in event.detail is pinned loosely:
#    test_38 accepts either "tick" or "tick_index" (1-based). Please use one
#    of those exact keys.
#
# 6. ManaflowLedger.hit() receipt uses the exact key set RLM-1 clarified
#    (time/source/accepted/reason/target_kind/hit_identity/charge_consumed/
#    use_count/bonus_total/bonus_delta/cap/atom); test_28 requires all keys
#    and JSON-safe values (tuples permitted — they are the kernel's atom
#    representation and convert to lists under json.dumps).
#
# 7. ResourceLedger.run determinism (row 14) is interpreted as
#    fresh-ledger reproducibility: same initial state + same events ->
#    identical receipts. Re-running on the SAME ledger is intentionally
#    stateful (before/after values legitimately differ).
#
# 8. regen_per_second is accepted by the constructors but its runtime
#    behavior is unspecified in the contract; no test asserts automatic
#    regen. Explicit OP_REGEN events carry their own amounts.
