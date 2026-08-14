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


def test_the_forced_restatements_are_criterion_4s_counted_residue(scan) -> None:
    """G5, pinned as a number rather than as a sentence in a report.

    These rows are the sites that really do state a committed baseline's shape
    count, each because another rule left no way not to.  The count is asserted
    so that adding one more is a failing test rather than a habit.

    It fell from sixteen across nine sources to eleven across six at the
    campaign-close coupled re-capture, and the cause is worth stating because
    it looks like a discharge and is not: the scan reads the *live* counts, so
    a receipt restating a figure a re-capture superseded stops being a site.
    The criterion binds a count of a **committed** baseline, and a superseded
    figure is no longer one.
    """
    block = scan.report()
    assert block["forced_restatements"] == 11
    allowances = scan.load_allowlist()
    forced = [row for row in allowances if row.kind == "forced_restatement"]
    assert len({row.source for row in forced}) == 6
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
