"""The plan-document gate (R-37), including the red it reproduces on demand.

This module is how ``plan_audit.py`` rides R-01 row 1 instead of becoming a
twelfth gate row: the first class runs the real audit over the real plans, and
every class after it injects a document the audit must reject, so no check here
can quietly stop being able to fail.
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import plan_audit  # noqa: E402  (path is set above)

UMBRELLA = plan_audit.PLANS_DIR / plan_audit.UMBRELLA_NAME


def cite(target, line, fragment=None):
    """One markdown line carrying a citation, optionally with its fragment."""
    body = f"`{target}:{line}`"
    return f"- the thing {body}" + (f" (`{fragment}`)" if fragment else "")


class TestTheRealPlans:
    """The gate itself."""

    def test_the_plan_documents_are_clean(self):
        findings = plan_audit.audit()
        assert findings == (), "\n".join(str(f) for f in findings)

    def test_every_plan_document_is_audited(self):
        names = {path.name for path in plan_audit.plan_documents()}
        assert plan_audit.UMBRELLA_NAME in names
        assert "silent-failure-runbook.md" in names
        assert len(names) == 8

    def test_the_umbrella_carries_citations_worth_checking(self):
        """A citation check over a document with no citations proves nothing."""
        text = UMBRELLA.read_text(encoding="utf-8")
        citations = plan_audit.parse_citations(text, plan_audit.UMBRELLA_NAME)
        assert len(citations) >= 5
        assert any(citation.fragment for citation in citations)

    def test_the_recorded_h5_ruling_passes_the_audit(self):
        """H5 was recorded after the plans were last verified (umbrella criterion 11)."""
        text = UMBRELLA.read_text(encoding="utf-8")
        h5 = [line for line in text.splitlines() if line.startswith("| **H5** |")]
        assert h5, "the umbrella no longer records an H5 row"
        assert "Recorded ruling: SCOPED" in h5[0]
        assert "DESCOPED" not in h5[0]
        assert plan_audit.audit(documents=[UMBRELLA]) == ()


class TestCitationParsing:
    def test_a_parenthesised_fragment_adjoins(self):
        (citation,) = plan_audit.parse_citations(
            cite("scripts/plan_audit.py", 1, "REPO_ROOT"), "doc.md"
        )
        assert citation.fragment == "REPO_ROOT"

    def test_a_comma_separated_neighbour_is_not_a_fragment(self):
        """Phase 2's Defy triple is three sibling pointers, not a referent."""
        line = (
            "(`a/b.py:97`, `scripts/plan_audit.py:1`, `SurvivalAction.defy_trigger_id`)"
        )
        citations = plan_audit.parse_citations(line, "doc.md")
        assert [c.fragment for c in citations] == [None, None]

    def test_prose_between_citation_and_span_is_not_adjacency(self):
        (citation,) = plan_audit.parse_citations(
            "`scripts/plan_audit.py:1` consults `REPO_ROOT`", "doc.md"
        )
        assert citation.fragment is None

    def test_a_fragment_past_the_line_wrap_still_adjoins(self):
        """A wrap is invisible to a reader and must be invisible to the gate."""
        (citation,) = plan_audit.parse_citations(
            "the constant `scripts/plan_audit.py:1`\n  (`REPO_ROOT`) resolves it",
            "doc.md",
        )
        assert citation.fragment == "REPO_ROOT"

    def test_a_wrapped_citation_is_found_at_its_own_line(self):
        """Joining a paragraph must not move a finding to the block's first line."""
        (citation,) = plan_audit.parse_citations(
            "a paragraph that wraps before it cites\n  `scripts/plan_audit.py:1`",
            "doc.md",
        )
        assert citation.doc_line == 2

    def test_a_citation_split_by_a_wrap_is_parsed_at_all(self):
        """An unclosed span on one line used to hide the citation entirely."""
        (citation,) = plan_audit.parse_citations(
            "the six migrated sites are `survival/compile.py:316, :319,\n  :1011`",
            "doc.md",
        )
        assert (citation.target, citation.start) == ("survival/compile.py", 316)

    def test_a_table_row_does_not_adopt_the_row_below_it(self):
        first, second = plan_audit.parse_citations(
            "| a | `scripts/plan_audit.py:1` |\n| b | `scripts/plan_audit.py:2` |",
            "doc.md",
        )
        assert (first.fragment, second.fragment) == (None, None)

    def test_a_new_list_item_starts_its_own_block(self):
        first, second = plan_audit.parse_citations(
            "- `scripts/plan_audit.py:1`\n- (`REPO_ROOT`) `scripts/plan_audit.py:2`",
            "doc.md",
        )
        assert first.fragment is None
        assert second.fragment == "REPO_ROOT"

    def test_a_range_keeps_both_ends(self):
        (citation,) = plan_audit.parse_citations(
            "`scripts/plan_audit.py:10-20`", "d.md"
        )
        assert (citation.start, citation.end) == (10, 20)


class TestCitationChecks:
    def test_an_unknown_file_is_reported(self):
        (finding,) = plan_audit.check_citations(
            plan_audit.parse_citations(cite("src/calculator/nowhere.py", 12), "d.md")
        )
        assert "names no file" in finding.message

    def test_a_line_past_the_end_of_the_file_is_reported(self):
        (finding,) = plan_audit.check_citations(
            plan_audit.parse_citations(cite("scripts/plan_audit.py", 99999), "d.md")
        )
        assert "past its last line" in finding.message

    def test_a_fragment_at_the_cited_line_passes(self):
        lines = (
            (REPO_ROOT / "scripts" / "plan_audit.py")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        at = next(i for i, l in enumerate(lines, 1) if l.startswith("CITATION_WINDOW"))
        assert (
            plan_audit.check_citations(
                plan_audit.parse_citations(
                    cite("scripts/plan_audit.py", at, "CITATION_WINDOW"), "d.md"
                )
            )
            == ()
        )

    def test_a_moved_fragment_is_drift_and_names_where_it_went(self):
        """R-37: a drifted number is refreshed, and the instrument says to what."""
        (finding,) = plan_audit.check_citations(
            plan_audit.parse_citations(
                cite("scripts/plan_audit.py", 1, "CITATION_WINDOW"), "d.md"
            )
        )
        assert "has drifted" in finding.message
        assert "refresh the locator in a doc-only commit" in finding.message

    def test_a_vanished_fragment_is_escalated_rather_than_re_pointed(self):
        (finding,) = plan_audit.check_citations(
            plan_audit.parse_citations(
                cite("scripts/plan_audit.py", 1, "no_such_symbol_anywhere"), "d.md"
            )
        )
        assert "plan/tree divergence to escalate" in finding.message
        assert "drifted" not in finding.message

    def test_a_vanished_fragment_past_a_wrap_is_escalated_too(self):
        """The red for the paragraph rule: a wrapped pair the gate used to skip."""
        (finding,) = plan_audit.check_citations(
            plan_audit.parse_citations(
                "the reader `scripts/plan_audit.py:1`\n  (`no_such_symbol_anywhere`)",
                "d.md",
            )
        )
        assert "plan/tree divergence to escalate" in finding.message

    def test_whitespace_inside_a_fragment_is_insignificant(self):
        """Documents compress code; the source is formatted."""
        source = (REPO_ROOT / "src" / "calculator" / "cast_dependency.py").read_text(
            encoding="utf-8"
        )
        line = next(
            number
            for number, text in enumerate(source.splitlines(), start=1)
            if text.startswith("BASE_CAST_SLOTS")
        )
        assert (
            plan_audit.check_citations(
                plan_audit.parse_citations(
                    cite(
                        "src/calculator/cast_dependency.py",
                        line,
                        'BASE_CAST_SLOTS: tuple[str, ...] = ("P","Q","W","E","R")',
                    ),
                    "d.md",
                )
            )
            == ()
        )

    def test_a_citation_inside_the_named_definition_passes(self):
        """A plan may name an enclosing function and cite a block inside it."""
        lines = (
            (REPO_ROOT / "scripts" / "plan_audit.py")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        start = next(
            i for i, l in enumerate(lines, 1) if l.startswith("def check_citations")
        )
        inside = start + 12
        assert (
            plan_audit.check_citations(
                plan_audit.parse_citations(
                    cite("scripts/plan_audit.py", inside, "check_citations"), "d.md"
                )
            )
            == ()
        )

    def test_a_qualified_fragment_is_located_by_its_last_segment(self):
        lines = (
            (REPO_ROOT / "scripts" / "plan_audit.py")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        at = next(
            i for i, l in enumerate(lines, 1) if l.startswith("def write_inventory")
        )
        assert (
            plan_audit.check_citations(
                plan_audit.parse_citations(
                    cite("scripts/plan_audit.py", at, "plan_audit.write_inventory()"),
                    "d.md",
                )
            )
            == ()
        )

    def test_a_renamed_owner_is_a_divergence_even_when_its_member_is_there(self):
        """The leading segments of a qualified fragment are claims too."""
        lines = (
            (REPO_ROOT / "scripts" / "plan_audit.py")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        at = next(
            i for i, l in enumerate(lines, 1) if l.startswith("def write_inventory")
        )
        (finding,) = plan_audit.check_citations(
            plan_audit.parse_citations(
                cite("scripts/plan_audit.py", at, "NoSuchOwner.write_inventory()"),
                "d.md",
            )
        )
        assert "NoSuchOwner" in finding.message
        assert "divergence to escalate" in finding.message


class TestGoldenFigures:
    COUNTS = {51437: ("golden.leaves",), 670: ("golden.entries",)}

    def test_a_correctly_restated_live_count_fails(self):
        """Prong one: the value match, against counts read from the receipt."""
        (finding,) = plan_audit.check_golden_figures(
            "d.md", "the baseline holds 51437 things", self.COUNTS
        )
        assert "golden.leaves" in finding.message
        assert "sole" in finding.message

    def test_a_non_golden_integer_passes(self):
        assert (
            plan_audit.check_golden_figures("d.md", "42 champions", self.COUNTS) == ()
        )

    def test_a_retired_figure_fails_even_though_no_receipt_holds_it(self, monkeypatch):
        """Prong one's other half — the seam the empty constant is driven through."""
        monkeypatch.setattr(plan_audit, "RETIRED_GOLDEN_FIGURES", ("1234",))
        (finding,) = plan_audit.check_golden_figures(
            "d.md", "the baseline once held 1234 of them", {}
        )
        assert "retired golden figure" in finding.message

    def test_a_wrong_figure_beside_a_shape_keyword_fails(self):
        """Prong two: what a value match can never see."""
        (finding,) = plan_audit.check_golden_figures(
            "d.md", "the golden baseline holds 999 entries", {}
        )
        assert "no `fingerprint:` citation marker" in finding.message

    def test_a_wrong_figure_past_a_wrap_fails_and_names_its_own_line(self):
        """Prong two reads the paragraph too, or a wrap hides the claim."""
        (finding,) = plan_audit.check_golden_figures(
            "d.md", "the golden baseline\n  holds 999 entries", {}
        )
        assert "no `fingerprint:` citation marker" in finding.message
        assert finding.line == 2

    def test_a_marked_figure_passes(self):
        assert (
            plan_audit.check_golden_figures(
                "d.md", "golden holds 999 entries (fingerprint:golden.entries)", {}
            )
            == ()
        )

    def test_an_identifier_is_not_a_shape_keyword(self):
        """`golden_snapshot.py` in a gate command must not arm the prong."""
        assert (
            plan_audit.check_golden_figures(
                "d.md", "| 2 | `python scripts/golden_snapshot.py compare` |", {}
            )
            == ()
        )

    def test_the_allowlist_admits_only_its_own_document(self):
        row = plan_audit.COLLISION_ALLOWLIST[0]
        assert row.admits(row.doc, row.value, "anything")
        assert not row.admits("other.md", row.value, "anything")

    def test_every_allowance_still_matches_something(self):
        """A dead allowance is an exemption nobody notices has stopped applying."""
        texts = {
            path.name: path.read_text(encoding="utf-8")
            for path in plan_audit.plan_documents()
        }
        for row in plan_audit.COLLISION_ALLOWLIST:
            lines = [l for l in texts[row.doc].splitlines() if row.context in l]
            assert lines, f"{row.doc} no longer contains {row.context!r}"

    def test_the_live_counts_come_from_the_receipt(self):
        counts = plan_audit.live_golden_counts(
            json.loads(plan_audit.FINGERPRINTS_PATH.read_text(encoding="utf-8"))
        )
        assert counts, "the fingerprints receipt carries no golden shape counts"
        assert all(isinstance(value, int) for value in counts)


class TestDecisionInventory:
    @pytest.fixture(scope="class")
    def umbrella(self):
        return UMBRELLA.read_text(encoding="utf-8")

    @pytest.fixture(scope="class")
    def derived(self, umbrella):
        return plan_audit.derive_inventory(umbrella)

    def test_the_committed_inventory_matches_the_umbrella(self, derived):
        committed = json.loads(plan_audit.INVENTORY_PATH.read_text(encoding="utf-8"))
        assert plan_audit.check_inventory(derived, committed) == ()
        assert committed == derived

    def test_every_declared_decision_has_exactly_one_owning_document(self, derived):
        for row in derived["decisions"]:
            assert row["documents"], row["id"]
            if len(row["documents"]) > 1:
                assert row["split"], row["id"]

    def test_the_reserve_gaps_are_declared_by_nobody(self, derived):
        declared = {row["id"] for row in derived["decisions"]}
        assert set(derived["reserve_gaps"]).isdisjoint(declared)
        assert "D-15" in derived["reserve_gaps"]
        assert "D-79" in derived["reserve_gaps"]

    def test_the_split_table_is_reproduced_in_full(self, derived):
        split = {row["id"] for row in derived["decisions"] if row["split"]}
        assert split == {
            "D-38",
            "D-44",
            "D-45",
            "D-47",
            "D-49",
            "D-63",
            "D-68",
            "D-101",
        }
        for row in derived["decisions"]:
            if row["split"]:
                assert row["halves"].strip(), row["id"]

    def test_a_missing_inventory_row_fails(self, derived):
        committed = json.loads(json.dumps(derived))
        committed["decisions"] = committed["decisions"][1:]
        (finding,) = plan_audit.check_inventory(derived, committed)
        assert "absent from the inventory" in finding.message

    def test_an_invented_inventory_row_fails(self, derived):
        committed = json.loads(json.dumps(derived))
        committed["decisions"].append(
            {"id": "D-77", "documents": ["phase-9.md"], "split": False}
        )
        (finding,) = plan_audit.check_inventory(derived, committed)
        assert "declared by no decision table" in finding.message

    def test_a_re_owned_decision_fails(self, derived):
        committed = json.loads(json.dumps(derived))
        committed["decisions"][0]["documents"] = ["phase-4-program-engine.md"]
        (finding,) = plan_audit.check_inventory(derived, committed)
        assert "but the manifest declares" in finding.message

    def test_a_missing_inventory_file_fails(self, derived):
        (finding,) = plan_audit.check_inventory(derived, None)
        assert "nothing to diff-gate" in finding.message

    def test_a_declared_reserve_gap_fails(self, derived):
        poisoned = json.loads(json.dumps(derived))
        poisoned["reserve_gaps"] = poisoned["reserve_gaps"] + [
            poisoned["decisions"][0]["id"]
        ]
        findings = plan_audit.check_inventory(poisoned, poisoned)
        assert any("unassigned reserve gap" in f.message for f in findings)

    def test_an_unsplit_decision_with_two_owners_fails(self, derived):
        poisoned = json.loads(json.dumps(derived))
        row = next(r for r in poisoned["decisions"] if not r["split"])
        row["documents"] = ["phase-1-coverage-evidence.md", "phase-4-program-engine.md"]
        findings = plan_audit.check_inventory(poisoned, poisoned)
        assert any("the split table does not" in f.message for f in findings)

    def test_the_manifest_is_the_authority_not_the_phase_headers(self, umbrella):
        """The umbrella's own row lists what it documents and owns nothing."""
        owners = plan_audit.manifest_owners(
            umbrella, plan_audit.declared_decisions(umbrella)
        )
        assert plan_audit.UMBRELLA_NAME not in {
            document for documents in owners.values() for document in documents
        }
