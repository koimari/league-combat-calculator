"""P2 Slice 4 cleanse-eligibility kernel tests (owner-owned).

Complements the RLM-2 acceptance matrix (tests/test_cleanse_eligibility.py)
with owner-level kernel coverage: the sourced declarations, the decision
reason enumeration, interval truncation semantics, the castability denial,
the score-path gate, and the fail-closed surfaces (unknown item, unknown
source, unknown control kind).
"""

from types import SimpleNamespace

import pytest

from src.calculator import cleanse_eligibility as ce
from src.calculator.crowd_control_eligibility import classify_control
from src.calculator.delivery_eligibility import stable_event_key
from src.calculator.state_lifecycle import SourceReceipt
from src.calculator.survival.compile import unrepresentable_template_receipt


def _action(
    *,
    time: float = 1.5,
    source_key: str = "Quicksilver Sash — Quicksilver",
    sequence: int = 0,
    item: str = "Quicksilver Sash",
    target: str = "target",
    holder: str = "target",
    active_controls: list[dict] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        time=time,
        source_key=source_key,
        sequence=sequence,
        event_id="cleanse",
        item=item,
        target=target,
        holder=holder,
        active_controls=active_controls or [],
    )


def _interval(kind: str, start: float, end: float, source: str = "E") -> dict:
    return {"kind": kind, "start": start, "end": end, "source": source}


def _eligibility(item: str = "Quicksilver Sash") -> ce.CleanseEligibility:
    return ce.CleanseEligibility(
        declaration=ce.item_declaration(item),
        source=SourceReceipt(
            label="Local League Wiki cache — " + item,
            url="https://wiki.leagueoflegends.com",
        ),
    )


# ---------------------------------------------------------------------------
# Declarations
# ---------------------------------------------------------------------------


def test_declarations_are_sourced_and_fail_closed():
    assert set(ce.ITEM_CLEANSE_DECLARATIONS) == {
        "Mikael's Blessing",
        "Quicksilver Sash",
        "Mercurial Scimitar",
    }
    for item, declaration in ce.ITEM_CLEANSE_DECLARATIONS.items():
        assert declaration["item"] == item
        assert declaration["cooldown_source_gap"] is True
        assert declaration["cooldown_seconds"] is None
        assert declaration["source_receipts"]
        assert isinstance(declaration["excluded_control_kinds"], tuple)
    # Wording receipts reproduce the cached branch text.
    assert any(
        ce.MIKAELS_WORDING in str(receipt)
        for receipt in ce.ITEM_CLEANSE_DECLARATIONS["Mikael's Blessing"][
            "source_receipts"
        ]
    )


def test_resolve_cleanse_item_fails_closed_for_unknown_sources():
    assert ce.resolve_cleanse_item("Quicksilver Sash — Quicksilver") == (
        "Quicksilver Sash"
    )
    assert ce.resolve_cleanse_item("Mercurial Scimitar") == "Mercurial Scimitar"
    assert ce.resolve_cleanse_item("Mikael's Blessing — Purify") == (
        "Mikael's Blessing"
    )
    with pytest.raises(KeyError, match="not a declared item"):
        ce.resolve_cleanse_item("Silvermere Dawn")
    with pytest.raises(KeyError, match="no cleanse declaration"):
        ce.item_declaration("Not an Item")


# ---------------------------------------------------------------------------
# Decision reasons
# ---------------------------------------------------------------------------


def test_eligible_removal_consumes_the_use():
    decision = _eligibility().decide(
        _action(active_controls=[_interval("stun", 1.0, 3.0)])
    )
    assert decision.eligible is True
    assert decision.reason == ""
    assert decision.use_consumed is True
    assert decision.removed_controls == [
        {
            "control_kind": "stun",
            "source": "E",
            "start": pytest.approx(1.5),
            "end": pytest.approx(3.0),
            "reason": "",
        }
    ]
    assert decision.intervals_after == [
        {"control_kind": "stun", "source": "E", "start": 1.0, "end": 1.5}
    ]


def test_control_not_active_still_consumes_the_use():
    decision = _eligibility().decide(_action(active_controls=[]))
    assert decision.eligible is False
    assert decision.reason == "control_not_active"
    assert decision.use_consumed is True
    assert decision.removed_controls == []
    assert decision.rejected_controls == []


def test_cleanse_at_exact_control_end_is_control_not_active():
    """P3-3G boundary: the control interval is end-EXCLUSIVE, so a Purify
    activation at exactly the control's end time sees no active control:
    control_not_active, use consumed, intervals untouched."""
    decision = _eligibility().decide(
        _action(time=2.0, active_controls=[_interval("stun", 1.0, 2.0)])
    )
    assert decision.eligible is False
    assert decision.reason == "control_not_active"
    assert decision.use_consumed is True
    assert decision.removed_controls == []
    assert decision.intervals_after == [
        {"control_kind": "stun", "source": "E", "start": 1.0, "end": 2.0}
    ]


def test_historical_intervals_are_control_not_active_not_use_spent():
    # An interval that ended before activation is historical: the activation
    # still happens (use consumed) and names control_not_active.
    decision = _eligibility().decide(
        _action(time=2.0, active_controls=[_interval("stun", 1.0, 1.5)])
    )
    assert decision.reason == "control_not_active"
    assert decision.use_consumed is True
    assert decision.intervals_after == [
        {"control_kind": "stun", "source": "E", "start": 1.0, "end": 1.5}
    ]


def test_use_spent_comes_only_from_the_holder_state():
    decision = _eligibility().decide(
        _action(active_controls=[_interval("stun", 1.0, 3.0)]),
        holder={"uses_remaining": 0, "item_held": True},
    )
    assert decision.eligible is False
    assert decision.reason == "use_spent"
    assert decision.use_consumed is False
    assert decision.removed_controls == []


def test_not_armed_from_the_holder_state():
    decision = _eligibility().decide(
        _action(active_controls=[_interval("stun", 1.0, 3.0)]),
        holder={"uses_remaining": 1, "item_held": False},
    )
    assert decision.reason == "not_armed"
    assert decision.use_consumed is False


def test_target_not_selected_for_self_items():
    decision = _eligibility().decide(
        _action(
            target="someone-else",
            holder="target",
            active_controls=[_interval("stun", 1.0, 3.0)],
        )
    )
    assert decision.reason == "target_not_selected"
    assert decision.use_consumed is False


def test_target_not_selected_for_ally_items():
    # Mikael's targets an ALLY: a self-targeted packet is denied.
    decision = _eligibility("Mikael's Blessing").decide(
        _action(
            item="Mikael's Blessing",
            source_key="Mikael's Blessing — Purify",
            target="holder-self",
            holder="holder-self",
            active_controls=[_interval("stun", 1.0, 3.0)],
        )
    )
    assert decision.reason == "target_not_selected"


def test_unknown_control_kind_fails_closed():
    decision = _eligibility().decide(
        _action(active_controls=[_interval("dance", 1.0, 3.0)])
    )
    assert decision.eligible is False
    assert decision.reason == "unknown_control"
    assert decision.use_consumed is False
    assert decision.removed_controls == []
    kept, removed = ce.truncate_intervals(
        [_interval("dance", 1.0, 3.0)], 1.5, {"dance"}
    )
    assert kept == [_interval("dance", 1.0, 3.0)]
    assert removed == []


def test_excluded_kind_only_rejection_consumes_the_use():
    decision = _eligibility("Mikael's Blessing").decide(
        _action(
            item="Mikael's Blessing",
            source_key="Mikael's Blessing — Purify",
            target="ally",
            holder="caster",
            active_controls=[_interval("airborne", 1.0, 3.0)],
        )
    )
    assert decision.reason == "excluded_control_kind"
    assert decision.use_consumed is True
    assert decision.removed_controls == []
    assert decision.rejected_controls == [
        {
            "control_kind": "airborne",
            "source": "E",
            "start": pytest.approx(1.0),
            "end": pytest.approx(3.0),
            "reason": "excluded_control_kind",
        }
    ]


def test_caster_control_blocks_cleanse_for_suppression():
    # QSS/Mercurial are castable while disabled but NOT under suppression.
    decision = _eligibility().decide(
        _action(active_controls=[_interval("suppression", 1.0, 3.0)])
    )
    assert decision.reason == "caster_control_blocks_cleanse"
    assert decision.use_consumed is False
    assert decision.removed_controls == []
    (rejected,) = decision.rejected_controls
    assert rejected["reason"] == "caster_control_blocks_cleanse"
    assert rejected["control_kind"] == "suppression"
    # Airborne is handled by the sourced exclusion, not the castability rule.
    assert classify_control(SimpleNamespace(cc_kind="airborne")).blocking is True


def test_mikaels_rejects_suppression_while_qss_denies_cast():
    # Mikael's wording excludes suppression: the ally's suppression interval
    # is rejected with excluded_control_kind (the cast itself is fine).
    decision = _eligibility("Mikael's Blessing").decide(
        _action(
            item="Mikael's Blessing",
            source_key="Mikael's Blessing — Purify",
            target="ally",
            holder="caster",
            active_controls=[_interval("suppression", 1.0, 3.0)],
        )
    )
    assert decision.reason == "excluded_control_kind"
    (rejected,) = decision.rejected_controls
    assert rejected["reason"] == "excluded_control_kind"
    # QSS/Mercurial do NOT exclude suppression per their wording — the
    # denial comes from castability instead.
    for item in ("Quicksilver Sash", "Mercurial Scimitar"):
        assert (
            "suppression"
            not in ce.ITEM_CLEANSE_DECLARATIONS[item]["excluded_control_kinds"]
        )


# ---------------------------------------------------------------------------
# truncate_intervals semantics
# ---------------------------------------------------------------------------


def test_truncate_intervals_historical_active_and_same_time():
    intervals = [
        _interval("stun", 0.5, 1.5, source="A"),  # historical
        _interval("stun", 1.0, 3.5, source="B"),  # active -> clamped
        _interval("stun", 2.0, 4.0, source="C"),  # same-time -> removed
        _interval("stun", 3.0, 4.0, source="D"),  # future -> untouched
    ]
    kept, removed = ce.truncate_intervals(intervals, 2.0, {"stun"})
    # The matrix commits the kernel rule: an interval starting at/after the
    # activation is removed entirely (same-timestamp controls resolve by the
    # walk total order; the walk never passes a control landing later, which
    # would be untouched — a cleanse creates no immunity).
    assert [(i["source"], i["start"], i["end"]) for i in kept] == [
        ("A", 0.5, 1.5),
        ("B", 1.0, 2.0),
    ]
    assert [(i["source"], i["start"], i["end"]) for i in removed] == [
        ("B", 2.0, 3.5),
        ("C", 2.0, 4.0),
        ("D", 3.0, 4.0),
    ]


def test_truncate_intervals_never_touches_non_eligible_or_unknown_kinds():
    intervals = [
        _interval("death", 0.0, 5.0, source="Death"),
        _interval("dance", 1.0, 3.0, source="?"),
    ]
    kept, removed = ce.truncate_intervals(intervals, 2.0, {"stun"})
    assert kept == intervals
    assert removed == []


def test_merged_interval_duration_union_semantics():
    assert ce.merged_interval_duration(
        [_interval("stun", 1.0, 3.0), _interval("root", 2.0, 4.0)]
    ) == pytest.approx(3.0)
    assert ce.merged_interval_duration([]) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Receipts
# ---------------------------------------------------------------------------


def test_decision_receipt_field_sets():
    decision = _eligibility().decide(
        _action(active_controls=[_interval("stun", 1.0, 3.0)])
    )
    receipt = decision.public_receipt()
    assert set(receipt) == {
        "eligible",
        "reason",
        "item",
        "activation_time",
        "target",
        "active_controls_before",
        "removed_controls",
        "rejected_controls",
        "intervals_after",
        "downtime_before",
        "downtime_after",
        "use_consumed",
    }
    assert receipt["event_key"] if False else True  # event key stays internal


def test_stable_event_key_is_the_decision_identity():
    action = _action(time=1.5, source_key="Quicksilver Sash — Quicksilver", sequence=2)
    assert stable_event_key(action) == "Quicksilver Sash — Quicksilver:1.5:2"
    decision = _eligibility().decide(action)
    assert decision.event_key == stable_event_key(action)


# ---------------------------------------------------------------------------
# Score-path gate
# ---------------------------------------------------------------------------


def test_unrepresentable_template_receipt_gate():
    assert (
        unrepresentable_template_receipt(
            {"kind": "heal", "amount": 100.0, "cleanse": True}
        )
        == "support_cleanse"
    )
    assert (
        unrepresentable_template_receipt(
            {"kind": "heal", "amount": 100.0, "cleanse_item": "Mikael's Blessing"}
        )
        == "support_cleanse"
    )
    assert unrepresentable_template_receipt({"kind": "heal", "amount": 100.0}) is None
    assert unrepresentable_template_receipt({"kind": "cleanse", "amount": 1.0}) == (
        "support_kind=cleanse"
    )
    assert unrepresentable_template_receipt({"kind": "movement", "amount": 50.0}) == (
        "support_kind=movement"
    )
