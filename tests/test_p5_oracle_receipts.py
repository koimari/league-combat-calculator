"""Gate for Phase 5's oracle receipts against their diff allowlists.

R-19 says a qualifying golden occurrence moves no baseline until an
independent investigator files a receipt naming the leaf, both values and
a verdict from a closed set.  Sixty-four receipts and fourteen receipts
were filed, and nothing read them: the leaf paths in the P5-retire set all
omitted the ``/fights/manual_target/`` segment, so not one of them was a
string that appears in the compare output or in the committed allowlist,
and a commit body counted the verdicts by hand and got the count wrong.
Both failures are the campaign's own shape — a check that could not fail
was indistinguishable from a check that passed.

So the join is machine-checked here.  For each committed
``expected-golden-diff-P5-*.json``: every expected diff path has exactly
one receipt whose ``leaf_path`` is that path *literally*, every receipt
carries a verdict from R-19's closed set, and the allowlist's recorded
tally is recomputed from the receipts rather than trusted.

The second half joins the allowlists to the *tree*.  R-17 forbids
re-capturing a baseline inside a semantic slice, so a phase's coupled-golden
diffs stand against the committed baseline plus its allowlists until the
boundary re-capture — which makes "zero diffs" uncheckable inside the phase
and left it being checked by hand, one leaf at a time.
``TestTheCoupledCompareIsFullyAllowlisted`` runs R-01 row 3's compare and
asserts what the phase actually claims: no differing leaf outside a
committed allowlist, none outside a ``rotation`` receipt object, no
allowlist entry excusing a diff that no longer moves, and the pair baseline
identical.  It survives the re-capture — an empty compare satisfies every
clause.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

RECEIPTS = Path(__file__).resolve().parents[1] / "docs" / "receipts"

# R-19's closed verdict set.  A receipt outside it has not answered the
# question the investigator was sent to answer.
VERDICTS = {"new_value_correct", "old_value_correct", "both_wrong"}

# The Phase 5 slices whose allowlists carry an oracle-receipt block.
ALLOWLISTS = sorted(
    path.name for path in RECEIPTS.glob("expected-golden-diff-P5-*.json")
)


def _load(name):
    return json.loads((RECEIPTS / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module", params=ALLOWLISTS)
def allowlist(request):
    """One slice's committed diff allowlist."""
    return request.param, _load(request.param)


def _receipts(block):
    """Every receipt file the block's prefix names, by leaf path."""
    by_path = {}
    for path in sorted(RECEIPTS.glob(f"{block['prefix']}leaf*.json")):
        receipt = json.loads(path.read_text(encoding="utf-8"))
        by_path.setdefault(receipt["leaf_path"], []).append((path.name, receipt))
    return by_path


class TestOracleReceiptsCoverTheirAllowlist:
    def test_the_allowlist_declares_its_receipts(self, allowlist) -> None:
        name, data = allowlist
        assert "oracle_receipts" in data, f"{name} names no oracle receipts"
        assert data["oracle_receipts"]["prefix"].startswith("oracle-P5-")

    def test_every_expected_diff_path_has_exactly_one_receipt(self, allowlist) -> None:
        """The join R-19 implies, as strings rather than as intent."""
        name, data = allowlist
        block = data["oracle_receipts"]
        by_path = _receipts(block)
        expected = data["expected_diff_paths"]["coupled_golden"]
        assert expected, f"{name} allowlists no coupled-golden path"
        for path in expected:
            covering = by_path.get(path, [])
            assert len(covering) == 1, f"{name}: {path} has {len(covering)} receipts"
        assert set(by_path) == set(expected), (
            f"{name}: receipts cover paths outside the allowlist: "
            f"{sorted(set(by_path) - set(expected))}"
        )

    def test_the_recorded_receipt_names_are_the_files_on_disk(self, allowlist) -> None:
        name, data = allowlist
        block = data["oracle_receipts"]
        by_path = _receipts(block)
        for path, filename in block["by_leaf_path"].items():
            assert by_path[path][0][0] == filename, f"{name}: {path}"

    def test_every_receipt_carries_a_verdict_and_both_values(self, allowlist) -> None:
        name, data = allowlist
        for covering in _receipts(data["oracle_receipts"]).values():
            filename, receipt = covering[0]
            assert receipt["verdict"] in VERDICTS, f"{name}: {filename}"
            for field in ("old_value", "new_value"):
                assert field in receipt, f"{name}: {filename} omits {field}"

    def test_the_recorded_tally_is_the_measured_tally(self, allowlist) -> None:
        """The one count in the campaign that is a count of receipts."""
        name, data = allowlist
        block = data["oracle_receipts"]
        measured = {verdict: 0 for verdict in VERDICTS}
        for covering in _receipts(block).values():
            measured[covering[0][1]["verdict"]] += 1
        recorded = block["verdict_tally"]
        for verdict, count in measured.items():
            assert recorded[verdict] == count, f"{name}: {verdict}"
        assert recorded["total"] == sum(measured.values()), name
        assert (
            recorded["dissenting"]
            == measured["old_value_correct"] + measured["both_wrong"]
        ), name


# ---------------------------------------------------------------------------
# The other half of the join: the tree against the allowlists
# ---------------------------------------------------------------------------

# The two snapshot counters umbrella criterion 4 disowns to
# ``campaign-fingerprints.json``: they count the snapshot's own leaves, so
# publishing a receipt key moves them and no allowlist may state their value.
DISOWNED_COUNTERS = (
    "/metadata/fingerprint/leaves",
    "/metadata/fingerprint/numeric_leaves",
)


def _live_coupled_diffs():
    """Every differing leaf path in R-01 row 3's compare, right now."""
    from scripts.golden_snapshot import (
        COMPARE_EXCLUDED_PROVENANCE,
        leaf_report,
        rebuild_for,
    )

    baseline = json.loads(
        (Path(__file__).resolve().parents[1] / "scripts")
        .joinpath("golden_coupled_baseline.json")
        .read_text(encoding="utf-8")
    )
    current = rebuild_for(baseline)
    for snapshot in (baseline, current):
        for key in COMPARE_EXCLUDED_PROVENANCE:
            snapshot.get("metadata", {}).pop(key, None)
    return tuple(diff.path for diff in leaf_report(baseline, current))


def _allowlisted_paths():
    """Every coupled-golden path any committed slice allowlist declares."""
    paths: set[str] = set()
    for path in sorted(RECEIPTS.glob("expected-golden-diff-*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        paths.update(data.get("expected_diff_paths", {}).get("coupled_golden", ()))
    return paths


def unallowlisted(diff_paths, allowlisted):
    """Every differing leaf no committed allowlist declares.

    The empty tuple is the pass condition.  Pure, so the negative tests
    below can hand it a diff nobody allowed and watch it say so.
    """
    return tuple(sorted(set(diff_paths) - set(allowlisted) - set(DISOWNED_COUNTERS)))


# Leaves some *other* phase's allowlist claims.  The clause below is Phase
# 5's own: its retirement moves no computed number, so every leaf it moves is
# inside a ``rotation`` receipt object.  That says nothing about what other
# phases may move, and it was written when Phase 5's were the only standing
# diffs — Phase 3's 3.8 coverage flip already contributed regenerated
# ``item_coverage[].reason`` strings, and Phase 4 S7's authority moves
# contribute declared number moves.  So the exemption is every non-P5
# committed allowlist, read from the receipts rather than listed here, and
# the clause keeps meaning exactly what Phase 5 claims: *this phase* moved
# nothing outside a rotation object.
def _leaves_other_slices_claim():
    """Coupled leaves any committed non-P5 allowlist declares."""
    claimed: set[str] = set()
    for receipt in sorted(RECEIPTS.glob("expected-golden-diff-*.json")):
        if receipt.name.startswith("expected-golden-diff-P5-"):
            continue
        data = json.loads(receipt.read_text(encoding="utf-8"))
        claimed.update(data.get("expected_diff_paths", {}).get("coupled_golden", ()))
    return frozenset(claimed)


def outside_a_rotation_receipt(diff_paths):
    """Every differing leaf that is not inside a ``rotation`` object.

    Less the two disowned counters, and less the leaves another phase's
    allowlist claims: this clause is Phase 5's claim about Phase 5's diffs.
    A damage, timeline, stat or combat leaf *no committed allowlist declares*
    still lands here, which is what the negative test below drives.
    """
    exempt = set(DISOWNED_COUNTERS) | _leaves_other_slices_claim()
    return tuple(
        sorted(
            path
            for path in diff_paths
            if "/rotation/" not in path and path not in exempt
        )
    )


class TestTheCoupledCompareIsFullyAllowlisted:
    """Phase 5 criterion 7 as amended: zero *unallowlisted* diffs.

    R-17 forbids re-capturing a baseline inside a semantic slice, so a
    phase's diffs stand against the committed baseline plus a committed
    allowlist until the boundary re-capture.  "Zero diffs" was therefore
    never checkable inside the phase and was checked by hand instead — the
    verifier read all of them against both allowlists one at a time.  This
    is that reading, mechanised, and it survives the re-capture: once the
    boundary lands the compare is empty and every clause holds trivially.
    """

    def test_no_differing_leaf_is_outside_a_committed_allowlist(self) -> None:
        assert unallowlisted(_live_coupled_diffs(), _allowlisted_paths()) == ()

    def test_an_undeclared_diff_is_reported(self) -> None:
        """R-05: the check fails on command, with a leaf nobody allowed."""
        smuggled = "/coupled_scenarios/x/fights/manual_target/total_damage"
        assert unallowlisted(
            _live_coupled_diffs() + (smuggled,), _allowlisted_paths()
        ) == (smuggled,)

    def test_every_differing_leaf_is_inside_a_rotation_receipt(self) -> None:
        """No computed number moves — the retirement's whole claim.

        A leaf outside a ``rotation`` object is a damage, timeline, stat or
        combat leaf, and one of those moving is the seed failing to be
        reproduced rather than the receipt gaining a field.
        """
        assert outside_a_rotation_receipt(_live_coupled_diffs()) == ()

    def test_a_moved_number_is_reported(self) -> None:
        """R-05 for the second clause: a damage leaf is never excusable."""
        moved = "/coupled_scenarios/x/fights/manual_target/breakdown/Q/total"
        assert outside_a_rotation_receipt(_live_coupled_diffs() + (moved,)) == (moved,)

    def test_the_allowlists_are_not_stale(self) -> None:
        """Every P5 allowlist path still moves — until P5's re-capture.

        A path that stopped moving is an allowlist entry excusing a diff
        that no longer exists, which is how an allowlist grows into a
        blanket.

        The retirement condition is *P5's own* re-capture, not an empty
        compare.  The original spelling retired on the global compare being
        empty, which held only while Phase 5's diffs were the only standing
        ones; the moment a later phase landed a declared move the clause
        woke up and demanded Phase 5's long-re-captured paths still differ.
        So the guard reads Phase 5's own paths: none of them moving is the
        re-capture having happened, and it is exactly then that this clause
        has nothing left to say.
        """
        differing = set(_live_coupled_diffs())
        declared: set[str] = set()
        for path in sorted(RECEIPTS.glob("expected-golden-diff-P5-*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            declared.update(data["expected_diff_paths"]["coupled_golden"])
        if not declared & differing:
            return
        assert sorted(declared - differing) == []

    def test_the_pair_baseline_is_identical(self) -> None:
        """R-01 row 2's claim, pinned where the phase's other claims are."""
        from scripts.golden_snapshot import (
            COMPARE_EXCLUDED_PROVENANCE,
            leaf_report,
            rebuild_for,
        )

        baseline = json.loads(
            (Path(__file__).resolve().parents[1] / "scripts")
            .joinpath("golden_baseline.json")
            .read_text(encoding="utf-8")
        )
        current = rebuild_for(baseline)
        for snapshot in (baseline, current):
            for key in COMPARE_EXCLUDED_PROVENANCE:
                snapshot.get("metadata", {}).pop(key, None)
        assert [diff.path for diff in leaf_report(baseline, current)] == []


# ---------------------------------------------------------------------------
# The escalation ledger: defects the slice found, refused to fix, and owes
# ---------------------------------------------------------------------------

ESCALATED = RECEIPTS / "escalated-defects-P5-retire.json"

# Every field an entry must carry to be an escalation rather than a note.
REQUIRED_FIELDS = (
    "id",
    "dated",
    "origin",
    "raised_by",
    "site",
    "defect",
    "live_signature",
    "not_fixed_here_because",
    "resolution",
)


def _escalated():
    return json.loads(ESCALATED.read_text(encoding="utf-8"))


def _sites(entry):
    """An entry's site records, whether it named one or several."""
    site = entry["site"]
    return list(site) if isinstance(site, list) else [site]


def _syndra_edges():
    """Syndra's merged edges, exactly as production publishes them."""
    from scripts.cast_dependency_audit import slot_option_keys
    from src.calculator.champions import parse_champion_abilities
    from src.calculator.data_fetcher import fetch_champion_data
    from src.calculator.rotation_resolver import resolved_edges
    from src.calculator.stats import calculate_total_stats

    data = next(
        champion
        for champion in fetch_champion_data().values()
        if champion.get("name") == "Syndra"
    )
    stats = calculate_total_stats(data, 18, [])
    parsed = parse_champion_abilities(
        data,
        18,
        stats["ability_power"],
        ability_ranks=None,
        champion_stats=stats,
        target_stats={
            "target_max_health": 2000.0,
            "target_current_health": 2000.0,
            "target_missing_health": 0.0,
        },
        champion_options={"splinters": 120},
    )
    return parsed, resolved_edges("Syndra", parsed, data, slot_option_keys("Syndra"))[0]


def _cc_setup_citation_prints_the_field_name(entry) -> None:
    """The published cc-setup sentence names the field, not the marker."""
    signature = entry["live_signature"]
    parsed, edges = _syndra_edges()
    authored = {
        part.cc_kind
        for part in parsed[signature["setup_slot"]].get("parts", ())
        if getattr(part, "cc_kind", None)
    }
    assert authored == {signature["authored_cc_kind"]}
    published = [
        edge.sentence()
        for edge in edges
        if edge.kind == "cc_setup" and edge.setup == signature["setup_slot"]
    ]
    assert published, "no cc_setup edge is published — the defect may be gone"
    for sentence in published:
        assert signature["published_sentence_contains"] in sentence
        assert signature["published_sentence_omits"] not in sentence


def _recast_citation_says_one_thing_twice(entry) -> None:
    """The published recast sentence restates its own cite, unconditioned."""
    signature = entry["live_signature"]
    setup, consume, kind = signature["edge"]
    _, edges = _syndra_edges()
    published = [
        edge.sentence()
        for edge in edges
        if (edge.setup, edge.consume, edge.kind) == (setup, consume, kind)
    ]
    assert published == [signature["published_sentence"]]
    assert signature["published_sentence_omits"] not in published[0]


# One reproducer per escalated defect, keyed by the receipt's own id.  A
# closed registry rather than a loop over prose: an entry with no
# reproducer is an escalation nothing can see, which is the shape this
# ledger exists to prevent.
REPRODUCERS = {
    "cc_setup_citation_prints_the_field_name": _cc_setup_citation_prints_the_field_name,
    "recast_citation_says_one_thing_twice": _recast_citation_says_one_thing_twice,
}


class TestTheEscalatedDefectsAreStillTracked:
    """The two defects the P5-retire oracles found and this phase may not fix.

    Both are older than the slice that surfaced them and correctly went
    unfixed inside it — each moves committed baseline leaves and owes its
    own R-20 population and its own oracle receipts.  But an escalation
    that exists only in a commit body evaporates at the phase-boundary
    re-capture: the moved leaves enter the new baseline, the compare goes
    quiet, and no artifact anywhere says a defect is still shipping.  That
    is the campaign's own failure shape, aimed at its own escalation path.

    So the ledger is committed and joined to three things at once: the
    oracle receipts that raised it, the source sites that carry it, and
    the sentences production publishes today.  Fixing a defect turns this
    red, which is the point — the entry is closed deliberately, in the
    slice that fixes it, rather than fading out with a re-capture.
    """

    def test_every_entry_carries_what_an_escalation_needs(self) -> None:
        entries = _escalated()["defects"]
        assert entries, "the escalation ledger is empty"
        for entry in entries:
            for field in REQUIRED_FIELDS:
                assert entry.get(field), f"{entry.get('id')} omits {field}"
            assert len(entry["dated"]) == 10 and entry["dated"].count("-") == 2

    def test_every_entry_names_the_oracle_verdicts_that_raised_it(self) -> None:
        """The join to R-19: an escalation is a dissent somebody filed."""
        allowlisted = set(
            _load("expected-golden-diff-P5-seed-syndra.json")["expected_diff_paths"][
                "coupled_golden"
            ]
        )
        for entry in _escalated()["defects"]:
            for raised in entry["raised_by"]:
                receipt = json.loads(
                    (RECEIPTS / raised["receipt"]).read_text(encoding="utf-8")
                )
                assert receipt["verdict"] == raised["verdict"], raised["receipt"]
                assert receipt["verdict"] != "new_value_correct", raised["receipt"]
                assert receipt["leaf_path"] in allowlisted, raised["receipt"]

    def test_every_site_still_carries_the_defect(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for entry in _escalated()["defects"]:
            for site in _sites(entry):
                source = (root / site["file"]).read_text(encoding="utf-8")
                assert site["fragment"] in source, f"{entry['id']}: {site['file']}"

    def test_every_entry_has_a_reproducer(self) -> None:
        """Totality, in the D-52 idiom: no entry without a way to see it."""
        assert {entry["id"] for entry in _escalated()["defects"]} == set(REPRODUCERS)

    @pytest.mark.parametrize("entry_id", sorted(REPRODUCERS))
    def test_the_defect_still_reproduces(self, entry_id) -> None:
        entry = next(e for e in _escalated()["defects"] if e["id"] == entry_id)
        REPRODUCERS[entry_id](entry)

    def test_a_baseline_reaching_defect_is_still_in_the_committed_baseline(
        self,
    ) -> None:
        """The clause the re-capture would otherwise silence.

        A defect the committed coupled baseline already carries is one the
        boundary re-capture absorbs.  The occurrence count is measured
        here and written nowhere: a count of leaves in a committed
        baseline belongs to ``campaign-fingerprints.json`` and to no
        document (umbrella criterion 4).
        """
        baseline = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "scripts"
                / "golden_coupled_baseline.json"
            ).read_text(encoding="utf-8")
        )
        for entry in _escalated()["defects"]:
            if not entry.get("reaches_the_committed_coupled_baseline"):
                continue
            fragment = entry["live_signature"]["published_sentence_contains"]
            # ``ensure_ascii=False`` because the citations carry em dashes,
            # and the default escape would make every fragment miss.
            assert fragment in json.dumps(baseline, ensure_ascii=False), entry["id"]
