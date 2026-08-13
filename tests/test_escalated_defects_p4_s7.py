"""Phase 4 S7's two escalations, gated so they cannot fade out.

S7 declares seven authority moves and lands four.  Three of those four
landed here; Shadowflame did not, because its coupled half delivers its
number as a rider on an existing event and the capability registry had no
shape that could say so.  The second entry is a plan/tree divergence a
landed move took deliberately.  Both have since been ruled — Amendments C
and D in the campaign umbrella — and both are retired here, which is why
every test below asserts a *resolved* property rather than a standing one.

Neither belongs in a commit body: a commit body is absorbed by the next
baseline re-capture, and an escalation that only a reader can find is the
prose-outruns-code shape this campaign exists to remove.  So each entry is
joined to a **reproducer** — a live property of the tree that is true while
the defect stands and false once it is fixed — and this file goes red when
one of them stops reproducing.  That is how an entry gets closed
deliberately rather than quietly.

Closing is itself a gated act.  An entry moves to ``retired[]`` only when a
ruling recorded in the umbrella resolves its contradiction, and the test
that reproduced it is **inverted rather than deleted**: it now asserts the
resolved property, so a regression that re-opens the defect turns this file
red from the other direction.  A deleted test would leave a retired entry
saying something nothing checks, which is the failure mode one file down.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.calculator import trigger_stream as ts
from src.calculator.item_behavior_catalog import behavior_rules
from src.calculator.item_behavior import Subject
from tests.test_trigger_stream import RULED_CROSS_PARTICIPANT_PRODUCERS

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "docs" / "receipts" / "escalated-defects-P4-S7.json"

REQUIRED = ("id", "dated", "raised_by", "what", "reproducer")
REQUIRED_TO_RETIRE = ("retired_on", "resolved_by", "resolution")


def _ledger():
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


def _entries():
    return _ledger()["defects"]


def _retired():
    return _ledger()["retired"]


def _retired_entry(entry_id):
    return next(entry for entry in _retired() if entry["id"] == entry_id)


def test_the_ledger_is_not_empty_and_every_entry_is_complete():
    """A ledger nobody has to fill in is a ledger that says nothing."""
    entries = _entries() + _retired()
    assert entries, "the escalation ledger is empty"
    for entry in entries:
        for field in REQUIRED:
            assert entry.get(field), f"{entry.get('id')} omits {field}"
        assert len(entry["dated"]) == 10 and entry["dated"].count("-") == 2


def test_a_retired_entry_names_the_ruling_that_closed_it():
    """Retirement is a recorded ruling, not a deletion.

    An entry that could be closed by editing this file is an entry the
    campaign cannot trust; every retired one names the umbrella amendment
    that resolved it and what that amendment left open.
    """
    for entry in _retired():
        for field in REQUIRED_TO_RETIRE:
            assert entry.get(field), f"{entry['id']} retires without {field}"
        assert "umbrella" in entry["resolved_by"] or "campaign" in entry["resolved_by"]


def test_the_ledger_names_the_slice_and_this_gate():
    body = _ledger()
    assert body["slice"] == "P4-S7"
    assert body["gate"] == "tests/test_escalated_defects_p4_s7.py"


def test_shadowflames_walk_half_now_has_a_declarable_shape():
    """The first entry's reproducer, inverted by Amendment C.

    What the escalation measured was a contradiction between two rules: a
    ``PAIRED`` walk half had to carry a ``packet_source``, and a walk row
    carrying one under a cross-participant authority *was* a producer of the
    set D-07 rules at six.  Cinderbloom's subject is the holder, so joining
    that set would have been a ruled count edited to satisfy a validator.

    The amendment resolves it by keying delivery and authorship separately:
    a rider stamp is a delivery reference, and only a *packet* delivery makes
    a half a cross-participant producer.  Both halves are asserted here —
    the shape exists, and the count it was protecting did not move.
    """
    rule = next(
        rule
        for rule in behavior_rules("Shadowflame")
        if rule.mechanic_id == "shadowflame.cinderbloom"
    )
    assert rule.payload.subject is Subject.HOLDER

    rider = ts.MechanicCapability(
        mechanic="shadowflame.cinderbloom_probe",
        owner=ts.ItemOwner("Shadowflame"),
        engine=ts.Engine.WALK,
        reads=frozenset(),
        needs=frozenset(),
        authority=ts.Authority.COUPLED_AUTHORITATIVE_WITH_PAIR_PREVIEW,
        pairing=ts.Pairing.PAIRED,
        pair_of="shadowflame.cinderbloom",
        divergence_ref=None,
        impl="survival.transitions.apply_action",
        packet_source=ts.RiderDelivery("Shadowflame — Cinderbloom"),
        view_tags=ts.MappingProxyType({ts.Engine.WALK: ts.ViewTag.APPLIED}),
        holder_stacking=ts.HolderStacking.PER_HOLDER,
    )
    ts._validate_pairing(rider.mechanic, rider)
    assert ts.cross_participant_packet_source(rider) is None
    assert _retired_entry("shadowflame_walk_half_has_no_declarable_shape")


def test_a_paired_half_delivering_nothing_at_all_is_still_rejected():
    """The half of the old shape that had to survive the amendment.

    Widening a field to admit a second kind of delivery is one edit away
    from admitting no delivery at all, and that would retire the escalation
    by deleting the rule it was about.
    """
    undelivered = ts.MechanicCapability(
        mechanic="shadowflame.cinderbloom_probe",
        owner=ts.ItemOwner("Shadowflame"),
        engine=ts.Engine.WALK,
        reads=frozenset(),
        needs=frozenset(),
        authority=ts.Authority.COUPLED_AUTHORITATIVE_WITH_PAIR_PREVIEW,
        pairing=ts.Pairing.PAIRED,
        pair_of="shadowflame.cinderbloom",
        divergence_ref=None,
        impl="survival.transitions.apply_action",
        packet_source=None,
        view_tags=ts.MappingProxyType({ts.Engine.WALK: ts.ViewTag.APPLIED}),
        holder_stacking=ts.HolderStacking.PER_HOLDER,
    )
    with pytest.raises(ts.TriggerRegistryError, match="names no delivery"):
        ts._validate_pairing(undelivered.mechanic, undelivered)


def test_the_cross_participant_producer_set_is_still_the_ruled_six():
    """The count the escalation argued from, re-asserted after the amendment.

    Pinned here as well as beside the derivation because this entry's whole
    argument *is* this number: a resolution that moved it would have
    resolved nothing.
    """
    producers = {
        source
        for capability in ts.CAPABILITIES.values()
        if (source := ts.cross_participant_packet_source(capability)) is not None
    }
    assert producers == RULED_CROSS_PARTICIPANT_PRODUCERS


UMBRELLA = ROOT / "docs" / "plans" / "2026-08-08-silent-failure-campaign.md"


def _umbrella_authority_row(mechanic):
    """The semantic-authority table's row for one mechanic, as written."""
    return next(
        line
        for line in UMBRELLA.read_text(encoding="utf-8").splitlines()
        if line.startswith(f"| `{mechanic}` |")
    )


def test_bloodsongs_authority_is_one_member_in_the_plan_and_in_the_tree():
    """The second entry's reproducer, inverted by Amendment D.

    What was escalated was a plan/tree divergence, not a defect in either:
    the table ruled ``COUPLED_AUTHORITATIVE``, the packet builder resolves a
    ``damage_modifier``'s authority through the three members that name a
    second engine, and Bloodsong's pair pricer still exists — so the ruled
    member was unconstructible and the slice landed the one that builds.

    The amendment refreshed the table to that member and kept the pricer as
    a declared preview.  What is asserted here is therefore agreement: the
    row and the registry name one member.  The pricer is asserted alive too,
    because it is the *reason* the row reads as it does — deleting it is
    explicitly not scheduled, and if it ever goes, this is the row that has
    to be re-read rather than quietly left standing.
    """
    walk = ts.CAPABILITIES["bloodsong.expose_weakness"]
    assert walk.authority is ts.Authority.COUPLED_AUTHORITATIVE_WITH_PAIR_PREVIEW
    assert walk.authority.name in _umbrella_authority_row("bloodsong.expose_weakness")
    assert ts.Authority.COUPLED_AUTHORITATIVE not in ts.CROSS_PARTICIPANT_AUTHORITIES
    from src.calculator.damage import _add_expose_weakness

    assert callable(_add_expose_weakness), "the pair pricer this entry is about"
    assert _retired_entry("bloodsong_authority_member_differs_from_the_umbrella")
