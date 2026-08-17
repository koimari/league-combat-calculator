"""Criterion 4's second half is a gate, and it can fail on demand.

The first half — ``docs/plans/*.md`` — has ridden ``pytest`` since R-37.  The
second — ``docs/receipts/`` and the campaign's commit bodies — was specified
as an agent reading at every barrier, and the campaign's own closing report
found nine sources by doing exactly that by hand.  Nothing in the tree would
have caught a tenth.

So this file is the half that was missing, in the M1–M9 idiom: the predicate
is a pure function over measured sites and committed allowances, and the
injection is at the predicate, so the red needs neither a fabricated receipt
on disk nor a fabricated commit.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _scan():
    """The instrument, imported by path exactly as the other gates import theirs."""
    spec = importlib.util.spec_from_file_location(
        "sole_home_scan", ROOT / "scripts" / "sole_home_scan.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("sole_home_scan", module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(name="scan", scope="module")
def _scan_fixture():
    return _scan()


def test_the_scan_has_figures_to_look_for(scan) -> None:
    """A vacuous count table would make every assertion below pass by emptiness."""
    counts = scan.live_counts(
        json.loads(scan.FINGERPRINTS_PATH.read_text(encoding="utf-8"))
    )
    assert counts
    assert any(value > 1000 for value in counts)


def test_every_site_in_the_tree_is_explained(scan) -> None:
    """The gate itself: receipts and commit bodies over the campaign range."""
    block = scan.report()
    assert block["unexplained"] == []


def test_no_allowance_outlives_the_site_it_excuses(scan) -> None:
    """An exception list nobody re-reads is the shape this campaign refuses."""
    assert scan.report()["stale_allowances"] == []


def test_the_forced_restatements_are_criterion_4s_counted_carve_out(scan) -> None:
    """Amendment H's carve-out, pinned as a number rather than as a sentence.

    These rows are the sites that really do state a committed baseline's shape
    count, each because another rule left no way not to.  The count is asserted
    so that adding one more is a failing test rather than a habit.

    It fell from sixteen across nine sources to eleven across six at the
    campaign-close coupled re-capture — the scan reads the *live* counts, so a
    receipt restating a figure a re-capture superseded stops being a site — and
    rose by one when the disposition slice's allowlist claimed the shape
    counter its own thirty-eight added keys move.  That rise is the carve-out
    working rather than widening: R-17 obliges an allowlist to state both sides
    of every path it claims, and Amendment H admits exactly that shape, inside
    the artifact adjudicating that leaf and agreeing with the committed
    receipt.  It then fell by two when the bench rosters joined the exact
    capture and superseded the old exact leaf count three rows were stating.
    And it fell by one more at the campaign-close boundary re-capture, in the
    two directions this file's own rule describes: H2's row retired because
    the figure it states is now two captures old, and the disposition
    allowlist's row was re-keyed to the figure that capture made live, because
    an allowlist states both sides of the move it claims.

    It then fell by two, across one source, at the charge-price pin
    re-capture — the first capture since the 0B boundary to move the *pair*
    snapshot's two censuses, which retired the 0B capture commit's own R-34
    line of cause and the 0A.2 oracle receipt's numeric-leaf figure together.
    Neither could be re-keyed the way an allowlist can: a commit body is
    history and a superseded oracle receipt is never edited, so a row whose
    figure a capture supersedes simply stops having a site.

    And it fell to two, across two sources, at the deferral-coverage capture —
    the widest supersession the campaign has had, because that capture moved
    every coupled census at once, so every row still keyed to one of them
    stopped having a site together.  What is left is the pair snapshot's entry
    count in the oracle receipt that adjudicates it, which no capture since
    0A.2 has superseded, and that capture's own allowlist, which claims the
    coupled leaf counter in order to supersede the boundary pin on it and so
    cannot make the claim without stating the figure.  A residue this small is
    not the criterion being discharged: the number is what it is because a
    capture moved, and the next forced restatement will raise it again.

    It did, the same day and by three, when the RW-scenarios pass filed
    verdicts on three of the counters that capture moved: R-19 says an oracle
    receipt carries the two values of the leaf it adjudicates, and a leaf that
    IS a shape counter cannot be adjudicated without the figure being written
    down.  The rise is the carve-out working exactly as the fall was — the
    same three conditions hold of each row, so what the number records is
    that three more artifacts now adjudicate a counter, not that the criterion
    slipped.

    And it fell to two, across two sources, at the amp-armed coverage capture,
    which moved every coupled census again: all four rows keyed to the
    deferral capture's figures — its own allowlist row and the three
    RW-scenarios verdicts on the counters it moved — stopped having a site
    together, and one arrived, this capture's allowlist claiming the coupled
    leaf counter in order to supersede the claim before it.  What is left is
    that row and the pair snapshot's entry count in the oracle receipt that
    adjudicates it, which no capture since 0A.2 has superseded.  The same
    capture opened the campaign's first *coincidence* row, which is counted
    apart from these on purpose: a coincidence says the integer is not the
    figure at all — an event ordinal in an older allowlist that became visible
    the moment ``coupled_golden.entries`` moved onto the same small integer —
    so admitting one is not the carve-out widening.

    The window-armed coverage capture of 2026-08-16 moved every coupled census
    again, and this time the number does not move at all — which is the case
    worth writing down, because an unchanged count is exactly what a stale
    allowlist would also produce.  Both of the previous two rows' fates are
    visible in the sources rather than in the total: the amp-armed capture's
    allowlist row stopped having a site, this capture's allowlist arrived
    claiming the same counter in order to supersede it, and the pair snapshot's
    entry count in the 0A.2 oracle receipt stands where it has stood since.
    The coincidence fell to zero in the same commit, its event ordinal having
    been a site only while ``coupled_golden.entries`` sat on that integer —
    which is what a coincidence row is supposed to do, since it never said the
    integer was the figure.

    And it rose to five, across five sources, the same day, when the
    RW-window-scenarios oracle pass filed verdicts on three of the counters
    that capture moved.  This is the second time the pattern has run --- a
    capture moves every coupled census, the rows keyed to the previous figures
    retire together, and then the oracle pass on that capture's own leaves
    raises the count by one row per counter it adjudicates --- so the number
    moving is the mechanism being legible rather than the criterion slipping.
    Each of the three meets Amendment H's three conditions against the figure
    the capture made live.  The fourth counter that capture moved drew a
    verdict too and is *not* among these rows: ``/metadata/scenario_count`` is
    not a ``/metadata/fingerprint/`` leaf, so no shape context puts its integer
    in the scan's reach --- the detection rule holding the jurisdiction its own
    docstring states, which is why the residue is five and not six.

    And it fell to two, across two sources, at the swing-term coverage capture
    of 2026-08-16, which moved every coupled census a seventh time: all four
    rows keyed to the window-armed capture's figures --- its own allowlist row
    and the three RW-window-scenarios verdicts on the counters it moved ---
    stopped having a site together, and one arrived, this capture's allowlist
    claiming the coupled leaf counter in order to supersede the claim before
    it.  What is left is that row and the pair snapshot's entry count in the
    0A.2 oracle receipt, which no capture since has superseded.  The
    *coincidence* count rose from zero to one in the same commit, and it is
    the one worth reading twice: the Phase 4 boundary capture's own R-34 line
    of cause states a leaf delta of the same small integer
    ``coupled_golden.entries`` has now moved onto, in a sentence about ten
    containers and about no fingerprint at all.  That is the second time an
    entry counter passing through the small integers has lit up such a
    sentence, so it is a recurring event rather than an anomaly --- and it is
    counted apart from the carve-out on purpose, because a coincidence says
    the integer is not the figure.

    And it rose to four, across four sources, the same day, when the
    RW-swing-scenarios oracle pass filed verdicts on two of the counters that
    capture moved.  This is the third run of the pattern, and the first time
    the rise has been *smaller* than the fall it answers --- which is the case
    worth writing down, because a short rise is also what a pass that quietly
    skipped a counter would produce.  It is not that: the pass filed three
    verdicts, one per qualifying occurrence the capture's own allowlist
    declared, and only two of the three adjudicate a leaf that IS a shape
    counter.  The third, on
    ``/coupled_scenarios/swing_term_armed_carry_roster``, is a scenario
    membership rather than a count, so it states no figure for the scan to
    see and could not have been a row.  The two that are rows meet Amendment
    H's three conditions against the figure this capture made live, and the
    *coincidence* stands at one where the same capture put it, its event
    ordinal still colliding with ``coupled_golden.entries``.
    """
    block = scan.report()
    assert block["forced_restatements"] == 4
    assert block["coincidences"] == 1
    allowances = scan.load_allowlist()
    forced = [row for row in allowances if row.kind == "forced_restatement"]
    assert len({row.source for row in forced}) == 4
    assert all(
        row.reason.startswith("R-1") or row.reason.startswith("R-3") for row in forced
    )


def test_an_unexplained_site_turns_the_check_red(scan) -> None:
    """The permanent negative (R-05), injected at the predicate."""
    allowances = scan.load_allowlist()
    fabricated = scan.Site(
        source="a-receipt-nobody-allowed.json", value=99991, fields=("golden.leaves",)
    )
    assert scan.unexplained((fabricated,), allowances) == (fabricated,)
    # ...and an allowed one is not reported, so the red above is the injection
    # rather than the predicate rejecting everything it is handed.
    allowed = next(row for row in allowances)
    admitted = scan.Site(
        source=allowed.source, value=allowed.value, fields=("coupled_golden.leaves",)
    )
    assert scan.unexplained((admitted,), allowances) == ()


def test_a_shape_count_outside_a_shape_context_is_not_a_site(scan) -> None:
    """The detection rule, in both directions.

    Without the negative half, "the scan reports nothing" would be equally
    consistent with a scan that reports everything having been switched off.
    """
    counts = {23308: ("coupled_golden.leaves",)}
    assert scan.scan_text("x", "the roster walked 23308 actions today", counts) == ()
    hit = scan.scan_text("x", '"/metadata/fingerprint/leaves": 23308', counts)
    assert [site.value for site in hit] == [23308]


def test_a_cited_figure_is_not_a_site(scan) -> None:
    """The escape hatch the plans half already has: cite the receipt."""
    counts = {23308: ("coupled_golden.leaves",)}
    cited = "/metadata/fingerprint/leaves is 23308 (fingerprint: coupled_golden.leaves)"
    assert scan.scan_text("x", cited, counts) == ()


def test_the_range_is_read_from_git_and_fails_closed(scan) -> None:
    """A scan that silently reads no commits would reproduce the gap it closes."""
    assert scan.commit_bodies()
    with pytest.raises(RuntimeError):
        scan.commit_bodies("no-such-ref-000000")
