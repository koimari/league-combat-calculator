"""The oracle pass over S6/S7's diffs raised four dissents; three escalate.

The pass returned 78 ``new_value_correct``, 2 ``old_value_correct`` and 2
``both_wrong``.  One dissent was a real defect — Bloodsong's Expose Weakness
armed twice inside its own window and multiplied a packet by 1.08 squared —
and is corrected in its own commit.  The other three are not absorbable and
not fixable from an implementation lane: one silent-failure the correction
narrows but does not remove, and two gaps in the oracle protocol itself.

Each entry is joined to a **reproducer** — a live property of the tree that
is true while the defect stands and false once it is fixed — and this file
goes red when one of them stops reproducing.  That is how an entry is closed
deliberately rather than quietly, and it is why the escalation is an artifact
rather than a sentence in a commit body: a commit body is absorbed by the
next baseline re-capture.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import golden_snapshot as gs  # noqa: E402  (path is set above)

# R-17's allowlist reader, from its own home: a standing coupled diff is
# legal exactly when a committed receipt claims it, and that predicate has
# one implementation rather than one per gate that needs it.
from tests.test_coupled_golden_allowlist import (  # noqa: E402
    allowlisted_coupled_paths,
    unexplained,
)

from src.calculator.ability_spec import AttackClass, DamageClass  # noqa: E402
from src.calculator.survival.actions import SurvivalAction  # noqa: E402
from src.calculator.survival.transitions import (  # noqa: E402
    _apply_cross_participant_modifiers,
    _apply_damage_modifier,
)

RECEIPTS = ROOT / "docs" / "receipts"
RECEIPT = RECEIPTS / "escalated-defects-S6S7-oracle.json"

REQUIRED = ("id", "dated", "raised_by", "what", "reproducer")
REQUIRED_TO_RETIRE = ("retired_on", "resolved_by", "resolution")

EXPOSE = "Bloodsong — Expose Weakness"
UNMAKE = "Abyssal Mask — Unmake"


def _ledger():
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


def _entries():
    return _ledger()["defects"]


def _committed_allowlists():
    """Every committed R-17 allowlist, as ``(filename, parsed block)``."""
    return [
        (receipt.name, json.loads(receipt.read_text(encoding="utf-8")))
        for receipt in sorted(RECEIPTS.glob("expected-golden-diff-*.json"))
    ]


def _superseding_value(path, recorded, origin, origin_entry):
    """The value a later capture declares for *path*, walking the supersession chain.

    A receipt records what it measured on its own tree; an allowlist that moves
    the leaf again carries a ``supersedes`` block naming the receipt and entry
    it replaces (or the allowlist whose claim it replaces).  The chain is
    walked from *origin*; two claimants on one predecessor raise rather than
    pick, and an allowlist that merely mentions the path claims nothing.
    """
    claims: dict[str, tuple[str, dict]] = {}
    for name, block in _committed_allowlists():
        for claimed, row in (block.get("expected_diff_values") or {}).items():
            if claimed != path or not isinstance(row, dict):
                continue
            supersedes = row.get("supersedes")
            if not isinstance(supersedes, dict):
                continue
            target = supersedes.get("receipt")
            if target == origin:
                if supersedes.get("entry") != origin_entry:
                    continue
            elif not isinstance(target, str) or not target.startswith(
                "expected-golden-diff-"
            ):
                continue
            if target in claims:
                raise AssertionError(
                    f"{path}: {sorted((claims[target][0], name))} each claim to "
                    f"supersede {target}; supersession is not a precedence question"
                )
            claims[target] = (name, row)
    value, predecessor, walked = recorded, origin, {origin}
    while predecessor in claims:
        name, row = claims[predecessor]
        assert "new" in row, f"{name} claims to supersede {path} without a new value"
        assert name not in walked, f"{path}: the supersession chain revisits {name}"
        value, predecessor = row["new"], name
        walked.add(name)
    return value


def _ids():
    return {entry["id"] for entry in _entries()}


class _Ledger:
    """The one ledger call the two transitions under test make."""

    @staticmethod
    def write(action, **fields):
        """Write onto the packet, exactly as OutcomeLedger.write does."""
        if action.event is not None:
            action.event.update(fields)

    @staticmethod
    def skip(action, reason):  # pylint: disable=unused-argument
        """Record nothing: no test here arms an unavailable modifier."""


class _Ctx:
    """The one context member the two transitions under test read."""

    ledger = _Ledger()


class TestTheLedgerIsWellFormed:
    """A ledger nobody has to fill in is a ledger that says nothing."""

    def test_every_entry_is_complete(self):
        entries = _entries() + _ledger()["retired"]
        assert entries, "the escalation ledger is empty"
        for entry in entries:
            for field in REQUIRED:
                assert entry.get(field), f"{entry.get('id')} omits {field}"
            assert len(entry["dated"]) == 10 and entry["dated"].count("-") == 2

    def test_a_retired_entry_names_the_ruling_that_closed_it(self):
        """Retirement is a recorded ruling, not a deletion."""
        for entry in _ledger()["retired"]:
            for field in REQUIRED_TO_RETIRE:
                assert entry.get(field), f"{entry['id']} retires without {field}"

    def test_the_ledger_names_the_slice_and_this_gate(self):
        body = _ledger()
        assert body["slice"] == "S6S7-oracle"
        assert body["gate"] == "tests/test_escalated_defects_s6s7_oracle.py"


class TestTheReceiptCanStillContradictTheNumber:
    """First entry's reproducer: two modifiers, one published factor."""

    def test_the_defect_is_declared(self):
        assert (
            "support_damage_multiplier_publishes_one_of_several_applied_factors"
            in _ids()
        )

    def test_two_holders_apply_two_factors_and_the_receipt_names_one(self):
        """The applied product is 1.08 squared; the receipt says 1.08.

        This is the shape that hid the corrected defect: every moved leaf
        carried a truthful-looking multiplier beside a value the multiplier
        does not produce.  The refresh rule folds two arms of one mechanic by
        one holder and deliberately leaves this — two *holders*, which
        ``HolderStacking.PER_HOLDER`` exists to keep — standing.
        """
        state = {"active_damage_modifiers": []}
        for holder in (0, 1):
            _apply_damage_modifier(
                _Ctx(),
                SurvivalAction(
                    source=EXPOSE,
                    time=1.0,
                    duration=4.0,
                    attacker=holder,
                    multiplier=1.08,
                    amount=0.08,
                    damage_classes=frozenset(DamageClass),
                    attack_classes=frozenset(AttackClass),
                    event={},
                ),
                state,
            )
        packet = SurvivalAction(
            time=2.0,
            attacker=2,
            damage_type="physical",
            basic_attack=True,
            event={},
        )
        amount = _apply_cross_participant_modifiers(_Ctx(), packet, state, 100.0)
        published = packet.event["support_damage_multiplier"]["multiplier"]
        assert amount == pytest.approx(100.0 * 1.08 * 1.08)
        assert published == pytest.approx(1.08)
        assert amount != pytest.approx(100.0 * published)

    def test_two_mechanics_on_one_packet_publish_one_of_them(self):
        """The same shape without a second holder — two different curses."""
        state = {"active_damage_modifiers": []}
        for source, multiplier in ((EXPOSE, 1.08), (UNMAKE, 1.12)):
            _apply_damage_modifier(
                _Ctx(),
                SurvivalAction(
                    source=source,
                    time=0.0,
                    duration=4.0,
                    attacker=0,
                    multiplier=multiplier,
                    amount=multiplier - 1.0,
                    damage_classes=frozenset(DamageClass),
                    attack_classes=frozenset(AttackClass),
                    event={},
                ),
                state,
            )
        packet = SurvivalAction(
            time=1.0,
            attacker=2,
            damage_type="magic",
            basic_attack=True,
            event={},
        )
        amount = _apply_cross_participant_modifiers(_Ctx(), packet, state, 100.0)
        published = packet.event["support_damage_multiplier"]["multiplier"]
        assert amount == pytest.approx(100.0 * 1.08 * 1.12)
        assert amount != pytest.approx(100.0 * published)


class TestOrdinalAddressingSubstitutesEvents:
    """Second entry's reproducer: a leaf path is an ordinal, not an identity."""

    def test_the_defect_is_declared(self):
        assert (
            "ordinal_addressed_leaf_paths_hand_an_oracle_two_different_events" in _ids()
        )

    def test_one_inserted_member_reports_every_later_member_as_a_change(self):
        """The oracle is handed two values that describe two different events.

        ``leaf_report`` pairs ``events[n]`` with ``events[n]`` **for a list
        whose members carry no identity**, so removing or inserting an earlier
        member re-labels every later one.  S6/S7 removed two events from one
        scenario, and two of this pass's four dissents are readings of that
        substitution rather than of a wrong number.

        The members below carry no ``event_id`` on purpose: that is the
        residual this entry still names.  The identity-bearing case — every
        event-family list in the coupled snapshot — is remedied, and the
        entry's ``ruled_and_remedied`` block records it; see
        ``TestTheIdentityKeyedReportRemediesTheIdentityBearingCase``.
        """
        old = {
            "combat": {
                "events": [{"damage_type": "physical"}, {"damage_type": "magic"}]
            }
        }
        new = {
            "combat": {
                "events": [
                    {"damage_type": "true"},
                    {"damage_type": "physical"},
                    {"damage_type": "magic"},
                ]
            }
        }
        diffs = {diff.path: (diff.old, diff.new) for diff in gs.leaf_report(old, new)}
        assert diffs["/combat/events[0]/damage_type"] == ("physical", "true")
        assert diffs["/combat/events[1]/damage_type"] == ("magic", "physical")

    def test_the_re_adjudication_confirms_the_substitution(self):
        """An oracle now demonstrates the hazard this entry only suspected.

        The two events[82] leaves were re-briefed by event identity under the
        R-15/R-18 amendment.  Both verdicts say the offered new value belongs
        to a different record, which is this entry's claim proven from outside
        the lanes that produced it — a confirmation, never a closure, so the
        entry stays open and both prior receipts stand unedited.
        """
        entry = next(
            e
            for e in _entries()
            if e["id"]
            == "ordinal_addressed_leaf_paths_hand_an_oracle_two_different_events"
        )
        block = entry["re_adjudicated_under_the_amendment"]
        for name in block["pass"]:
            body = json.loads((RECEIPTS / name).read_text(encoding="utf-8"))
            assert body["verdict"] == "old_value_correct", name
            assert body["leaf"].endswith(
                ("events[82]/damage_type", "events[82]/sequence")
            )
            assert body["supersedes_prior_brief_defect"]["defect"], name
        prior = {
            name: json.loads((RECEIPTS / name).read_text(encoding="utf-8"))["verdict"]
            for name in block["supersedes"]
        }
        assert prior == {
            "oracle-S6S7-leaf10.json": "old_value_correct",
            "oracle-S6S7-leaf30.json": "both_wrong",
        }
        assert (
            "ordinal_addressed_leaf_paths_hand_an_oracle_two_different_events" in _ids()
        )


class TestTheVerdictSetCannotSayNoEvidence:
    """Third entry's reproducer: a 'cannot certify' has to be spelled as a dissent."""

    def test_the_defect_is_declared(self):
        assert (
            "the_verdict_enum_has_no_member_for_a_leaf_the_evidence_tree_cannot_decide"
            in _ids()
        )

    @pytest.mark.parametrize(
        "receipt,verdict",
        [
            ("oracle-S6S7-leaf24.json", "old_value_correct"),
            ("oracle-S6S7-leaf30.json", "both_wrong"),
        ],
    )
    def test_a_dissent_still_carries_its_own_statement_of_no_evidence(
        self, receipt, verdict
    ):
        """Both receipts say, in their own words, that nothing could decide.

        The verdict they had to return says the opposite, because R-19's set
        has no member for it.  While both halves are true of the committed
        receipt the escalation stands.
        """
        body = json.loads((RECEIPTS / receipt).read_text(encoding="utf-8"))
        assert body["verdict"] == verdict
        prose = json.dumps(body).lower()
        assert "not" in prose
        assert any(
            marker in prose
            for marker in (
                "cannot",
                "could not",
                "no such computation",
                "not excludable",
            )
        )

    def test_the_ruled_subclass_is_reclassified_and_the_rest_is_not(self):
        """R-15's amendment answers one subclass of this gap, and says which.

        A leaf whose value a *ruling* removed is adjudicated by citing that
        ruling.  A leaf that is merely undecidable from the evidence tree —
        ``oracle-S6S7-leaf30``'s ``sequence`` — is not, so the entry stays
        open with its own reproducer intact.  Both halves are asserted, or
        "narrowed" would be indistinguishable from "closed".
        """
        entry = _entry_by_id(
            "the_verdict_enum_has_no_member_for_a_leaf_the_evidence_tree_cannot_decide"
        )
        block = entry["narrowed_by_a_ruling"]
        body = _classification(C4_CLASSIFICATION)
        assert block["reclassifies"]["receipt"].endswith(C4_CLASSIFICATION)
        assert body["leaves_reclassified"][0]["supersedes"].endswith(
            "oracle-S6S7-leaf24.json"
        )
        # The superseded receipt stands, unedited, with its own verdict.
        superseded = json.loads(
            (RECEIPTS / "oracle-S6S7-leaf24.json").read_text(encoding="utf-8")
        )
        assert superseded["verdict"] == "old_value_correct"
        # ...and the leaf that is *not* ruled keeps the entry open.
        assert "oracle-S6S7-leaf30" in block["why_this_entry_stays_open"]
        assert (
            "the_verdict_enum_has_no_member_for_a_leaf_the_evidence_tree_cannot_decide"
            in _ids()
        )

    def test_the_second_ruled_subclass_is_reclassified_and_the_rest_is_not(self):
        """Amendment J answers a second subclass, and the same both-halves rule.

        A campaign-authored justification string asserting a fact about
        ``src``-level vocabulary is adjudicated by *source assertion* — the
        machine check that binds it to the predicate producing it — so an
        investigator's verdict on that portion never decided it and the
        receipt is answered where it stands.  Asserted here the way the first
        narrowing is: the ruling is a document a reader can open, the check it
        rests on is a file that exists, the answered receipt is unedited with
        its own verdict, and the undecidable leaf still holds the entry open.
        """
        entry = _entry_by_id(
            "the_verdict_enum_has_no_member_for_a_leaf_the_evidence_tree_cannot_decide"
        )
        block = entry["narrowed_again_by_a_ruling"]
        umbrella = (
            ROOT / "docs" / "plans" / "2026-08-08-silent-failure-campaign.md"
        ).read_text(encoding="utf-8")
        assert (
            "Amendment J — 2026-08-15, how a campaign-authored justification "
            "string is adjudicated" in block["answers"]
        )
        assert (
            "Amendment J — 2026-08-15, how a campaign-authored justification "
            "string is adjudicated" in umbrella
        )
        gate, _, _rest = block["reclassifies"]["the_source_assertion"].partition(" ")
        assert (ROOT / gate).exists(), gate
        answered = json.loads(
            (RECEIPTS / "oracle-P3-3.8-leaf24.json").read_text(encoding="utf-8")
        )
        assert answered["verdict"] == "old_value_correct"
        row = next(
            candidate
            for candidate in json.loads(
                (RECEIPTS / "standing-dissent-adjudications.json").read_text(
                    encoding="utf-8"
                )
            )["adjudications"]
            if candidate["receipt"] == "oracle-P3-3.8-leaf24.json"
        )
        assert row["kind"] == "citation"
        # ...and the leaf no ruling reaches still keeps the entry open.
        assert "oracle-S6S7-leaf30" in block["why_this_entry_stays_open"]


# ---------------------------------------------------------------------------
# The two reclassifications: a ruled membership transition is adjudicated by
# citation, and the instrument no longer manufactures the leaves it replaced.
# ---------------------------------------------------------------------------

C3_CLASSIFICATION = "classification-P4D-C3-events-82-ordinal-substitution.json"
C4_CLASSIFICATION = (
    "classification-P4D-C4-support-events-owner-ruled-field-removal.json"
)
P4D_ALLOWLIST = "expected-golden-diff-P4D-identity-keyed-report.json"
COUPLED_BASELINE = ROOT / "scripts" / "golden_coupled_baseline.json"


def _entry_by_id(entry_id):
    for entry in _entries():
        if entry["id"] == entry_id:
            return entry
    raise AssertionError(f"{entry_id} is not an open entry of this ledger")


def _classification(name):
    return json.loads((RECEIPTS / name).read_text(encoding="utf-8"))


def _c3_identity(field, recorded):
    """The identity a later capture declares for one C3 ``measured_after`` field.

    The identity's last part is the pair walk's own per-pair index, so a
    capture that changes how many rows that walk authors renumbers it.  The
    classification keeps what it measured on its tree; the successor is read
    from the committed allowlist that declares it.
    """
    return _superseding_value(
        f"/classification-P4D-C3/the_instrument_fix/measured_after/{field}",
        recorded,
        C3_CLASSIFICATION,
        "the_instrument_fix.measured_after",
    )


def _c4_path(recorded):
    """The ordinal a later capture declares for the C4 record's own leaf.

    Same reason as above, one list over: the record is addressed by position
    in a list that grew, so the position moved while the record did not.
    """
    return _superseding_value(
        "/classification-P4D-C4/the_instrument_fix/measured_after/path",
        recorded,
        C4_CLASSIFICATION,
        "the_instrument_fix.measured_after",
    )


def _allowlisted():
    body = json.loads((RECEIPTS / P4D_ALLOWLIST).read_text(encoding="utf-8"))
    return set(body["expected_diff_paths"]["coupled_golden"])


def _standing():
    """Every standing coupled diff, keyed by path — the live report."""
    baseline = json.loads(COUPLED_BASELINE.read_text(encoding="utf-8"))
    current = gs.rebuild_for(baseline)
    for snapshot in (baseline, current):
        for key in gs.COMPARE_EXCLUDED_PROVENANCE:
            snapshot.get("metadata", {}).pop(key, None)
    return {diff.path: diff for diff in gs.leaf_report(baseline, current)}


class TestARuledMembershipTransitionIsAdjudicatedByCitation:
    """R-15's 2026-08-14 amendment, exercised on the two leaves it was ruled for.

    A classification receipt is not a verdict: it records that the leaf was
    never a value question, cites the ruling that produced the absence, and
    points at the allowlist entry that is therefore its whole receipt.  The
    gate asserts each of those four things, and asserts the superseded
    receipts still stand with their own verdicts — the supersession discipline
    that keeps a reclassification from being a quiet deletion.
    """

    @pytest.mark.parametrize("name", [C3_CLASSIFICATION, C4_CLASSIFICATION])
    def test_it_is_a_classification_and_not_a_verdict(self, name):
        body = _classification(name)
        assert body["artifact"] == "leaf_classification"
        assert "verdict" not in body
        assert body["category_error"]["name"] in (
            "ordinal substitution",
            "ruled field removal",
        )

    @pytest.mark.parametrize("name", [C3_CLASSIFICATION, C4_CLASSIFICATION])
    def test_it_names_the_defect_in_the_brief_it_replaces(self, name):
        """Clause 3: a supersession that names no defect is oracle shopping."""
        body = _classification(name)
        assert body["defect_in_the_prior_brief"]["defect"]

    @pytest.mark.parametrize("name", [C3_CLASSIFICATION, C4_CLASSIFICATION])
    def test_every_superseded_receipt_stands_unedited_with_its_verdict(self, name):
        body = _classification(name)
        superseded = [leaf["supersedes"] for leaf in body["leaves_reclassified"]]
        superseded += body.get("prior_chain", {}).get(
            "also_superseded_through_the_pass_above", []
        )
        assert superseded
        for path in superseded:
            filed = json.loads((RECEIPTS / Path(path).name).read_text(encoding="utf-8"))
            assert filed["verdict"] in ("old_value_correct", "both_wrong")

    @pytest.mark.parametrize("name", [C3_CLASSIFICATION, C4_CLASSIFICATION])
    def test_the_cited_ruling_is_one_a_reader_can_open(self, name):
        """R-15's second guard: never 'ruled elsewhere'."""
        for citation in _classification(name)["ruling_cited"]["openable_at"]:
            target = ROOT / citation.split(" -- ")[0].strip()
            assert target.exists(), citation

    @pytest.mark.parametrize("name", [C3_CLASSIFICATION, C4_CLASSIFICATION])
    def test_the_allowlist_entry_is_the_receipt(self, name):
        body = _classification(name)
        assert body["allowlist_entry"]["path"] in _allowlisted()
        assert body["allowlist_entry"]["status"] == "NOT_OWED_RULED_MEMBERSHIP"


def _cleaver(section):
    """One list out of the re-captured coupled baseline's cleaver scenario."""
    baseline = json.loads(COUPLED_BASELINE.read_text(encoding="utf-8"))
    return baseline["coupled_scenarios"]["cleaver_bloodsong_roster"]["combat"][section]


class TestTheIdentityKeyedReportRemediesTheIdentityBearingCase:
    """The measured half, now read off the baseline the boundary capture pinned.

    These assertions read the live compare while the re-capture was blocked:
    a reclassification whose own instrument still produced the leaf it
    reclassified would have been prose.  The Phase 4 boundary re-capture
    absorbed those membership transitions, so the compare is clean and every
    "the report no longer spells it" assertion would now pass whatever the
    instrument did — the vacuously-green shape this campaign exists to kill.
    They are therefore turned over onto the committed baseline, which is where
    the remedy now lives: the record the ordinal was substituting is what the
    baseline holds at that ordinal, and the removed identities are gone from
    the list rather than re-spelled as value changes.  The compare being clean
    is asserted rather than assumed, so a dirty one fails here too.
    """

    def test_the_ordinal_addressed_leaves_are_no_longer_reported(self):
        standing = _standing()
        # The instrument guard, stated as R-17 actually leaves it. Between two
        # phase boundaries the compare *cannot* be empty -- a landed slice's
        # allowlisted diffs are standing by design -- so demanding emptiness
        # here would forbid every semantic slice until the next re-capture.
        # What must hold, and what a broken instrument would break, is that
        # every standing diff is claimed by a committed allowlist.
        assert (
            unexplained(tuple(standing.values()), allowlisted_coupled_paths()) == ()
        ), "the coupled compare holds a diff no receipt claims"
        for path in (
            "/coupled_scenarios/cleaver_bloodsong_roster/combat/events[82]/damage_type",
            "/coupled_scenarios/cleaver_bloodsong_roster/combat/events[82]/sequence",
            "/coupled_scenarios/cleaver_bloodsong_roster/combat/support_events[17]/owner",
        ):
            assert path not in standing, path

    def test_each_reclassified_leaf_is_pinned_as_the_membership_it_became(self):
        """The inversion: the baseline holds the post-membership record itself."""
        c3 = _classification(C3_CLASSIFICATION)["the_instrument_fix"]["measured_after"]
        events = _cleaver("events")
        identities = [event.get(gs.IDENTITY_FIELD) for event in events]
        removed = _c3_identity("identity", c3["identity"])
        assert removed not in identities, removed
        sibling = _c3_identity("sibling_removal/identity", "main:enemy:Aatrox:34")
        assert sibling not in identities, sibling
        ordinal = int(c3["path"].rsplit("[", 1)[1].rstrip("]"))
        assert events[ordinal][gs.IDENTITY_FIELD] == _c3_identity(
            "the_record_the_ordinal_used_to_substitute/identity",
            "main:enemy:Aatrox:35",
        )

        c4 = _classification(C4_CLASSIFICATION)["the_instrument_fix"]["measured_after"]
        support = _cleaver("support_events")
        # The record, not the ordinal: this list grew by four Carve armings
        # when the re-capture landed, so the position the classification
        # measured moved.  The successor is declared in a committed allowlist
        # and the record is asserted there, carrying the absence the ruling
        # made -- a stronger reading than the ordinal merely running off the
        # end of a shorter list, which is what it used to say.
        ordinal = int(_c4_path(c4["path"]).rsplit("/", 1)[0].rsplit("[", 1)[1][:-1])
        assert support[ordinal][gs.IDENTITY_FIELD] == c4["identity"]
        assert "owner" not in support[ordinal]
        armings = [
            row for row in support if row.get("source") == "Bloodsong — Expose Weakness"
        ]
        assert [row[gs.IDENTITY_FIELD] for row in armings] == [
            "enemy:Aatrox:support:0",
            "enemy:Aatrox:support:1",
            c4["identity"],
        ]
        assert not [row for row in armings if "owner" in row]

    def test_the_record_the_ordinal_substituted_is_field_for_field_unmoved(self):
        """main:enemy:Aatrox:35 was compared against another event; it is unmoved.

        Its pre-capture reading is quoted by the classification receipt as
        "field for field it is what the baseline holds at ordinal 84", so the
        baseline is asked for exactly that: the record now standing where the
        substitution was reported carries the identity the ordinal displaced.
        """
        quoted = _classification(C3_CLASSIFICATION)["the_instrument_fix"][
            "measured_after"
        ]["the_record_the_ordinal_used_to_substitute"]
        assert "main:enemy:Aatrox:35" in quoted
        standing = _c3_identity(
            "the_record_the_ordinal_used_to_substitute/identity",
            "main:enemy:Aatrox:35",
        )
        events = _cleaver("events")
        matching = [
            event for event in events if event.get(gs.IDENTITY_FIELD) == standing
        ]
        assert len(matching) == 1
        assert events.index(matching[0]) == len(events) - 1

    def test_the_entry_records_the_remedy_and_stays_open(self):
        entry = _entry_by_id(
            "ordinal_addressed_leaf_paths_hand_an_oracle_two_different_events"
        )
        block = entry["ruled_and_remedied"]
        assert block["commit"]
        assert C3_CLASSIFICATION in block["reclassification"]
        assert "reproducer still reproduces" in block["why_this_entry_stays_open"]
