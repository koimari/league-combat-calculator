"""Phase 4 S7's two escalations, gated so they cannot fade out.

S7 declares seven authority moves and lands four.  Three of those four
landed here; Shadowflame did not, because its coupled half delivers its
number as a rider on an existing event and the capability registry has no
shape that can say so.  The second entry is a plan/tree divergence a landed
move took deliberately.

Neither belongs in a commit body: a commit body is absorbed by the next
baseline re-capture, and an escalation that only a reader can find is the
prose-outruns-code shape this campaign exists to remove.  So each entry is
joined to a **reproducer** — a live property of the tree that is true while
the defect stands and false once it is fixed — and this file goes red when
one of them stops reproducing.  That is how an entry gets closed
deliberately rather than quietly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.calculator import trigger_stream as ts
from src.calculator.item_behavior_catalog import behavior_rules
from src.calculator.item_behavior import Subject

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "docs" / "receipts" / "escalated-defects-P4-S7.json"

REQUIRED = ("id", "dated", "raised_by", "what", "reproducer")


def _entries():
    return json.loads(RECEIPT.read_text(encoding="utf-8"))["defects"]


def test_the_ledger_is_not_empty_and_every_entry_is_complete():
    """A ledger nobody has to fill in is a ledger that says nothing."""
    entries = _entries()
    assert entries, "the escalation ledger is empty"
    for entry in entries:
        for field in REQUIRED:
            assert entry.get(field), f"{entry.get('id')} omits {field}"
        assert len(entry["dated"]) == 10 and entry["dated"].count("-") == 2


def test_the_ledger_names_the_slice_and_this_gate():
    body = json.loads(RECEIPT.read_text(encoding="utf-8"))
    assert body["slice"] == "P4-S7"
    assert body["gate"] == "tests/test_escalated_defects_p4_s7.py"


def test_shadowflames_walk_half_still_has_no_declarable_shape():
    """The first entry's reproducer, as two live properties of the tree.

    A ``PAIRED`` walk half must carry a ``packet_source``; a walk row that
    carries one with a cross-participant authority *is* a cross-participant
    producer, and D-07 rules that set at six.  Cinderbloom's declared
    subject is the holder, so it modifies no other participant's damage and
    cannot honestly join that set.  While both halves of that hold, the
    move has no shape — and the moment either stops holding, this test goes
    red and the entry is closed on purpose.
    """
    rule = next(
        rule
        for rule in behavior_rules("Shadowflame")
        if rule.mechanic_id == "shadowflame.cinderbloom"
    )
    assert rule.payload.subject is Subject.HOLDER

    paired = ts.MechanicCapability(
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
    with pytest.raises(ts.TriggerRegistryError, match="declares no packet_source"):
        ts._validate_pairing(paired.mechanic, paired)


def test_the_cross_participant_producer_set_is_still_the_ruled_six():
    """The other half of the same reproducer, and D-07's own count.

    A ``packet_source`` on that row would satisfy the validator and put
    Cinderbloom in this set, which is the ruled six ``damage_modifier``
    producers.  Pinned here rather than only in the golden instrument
    because the escalation's argument *is* this number.
    """
    producers = {
        capability.packet_source
        for capability in ts.CAPABILITIES.values()
        if capability.engine is ts.Engine.WALK
        and capability.authority in ts.CROSS_PARTICIPANT_AUTHORITIES
        and capability.packet_source is not None
    }
    assert producers == {
        "Abyssal Mask — Unmake",
        "Black Cleaver — Carve",
        "Bloodletter's Curse — Vile Decay",
        "Bloodsong — Expose Weakness",
        "Dream Maker — Blue Dream Bubble",
        "Imperial Mandate — Command",
    }


def test_bloodsongs_landed_authority_is_the_constructible_one():
    """The second entry's reproducer: the ruled member does not build.

    The umbrella rules ``COUPLED_AUTHORITATIVE``; the packet builder
    resolves a ``damage_modifier``'s authority through the three members
    that name a second engine, and Bloodsong's pair pricer still exists.
    While that pricer stands, the ruled member is unconstructible and this
    is the member that shipped.
    """
    walk = ts.CAPABILITIES["bloodsong.expose_weakness"]
    assert walk.authority is ts.Authority.COUPLED_AUTHORITATIVE_WITH_PAIR_PREVIEW
    assert ts.Authority.COUPLED_AUTHORITATIVE not in ts.CROSS_PARTICIPANT_AUTHORITIES
    from src.calculator.damage import _add_expose_weakness

    assert callable(_add_expose_weakness), "the pair pricer this entry is about"
