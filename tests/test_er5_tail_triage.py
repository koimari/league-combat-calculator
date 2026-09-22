"""The ER5 tail, split by what the evidence already decides about it.

A raw count of ``x.get(key, <literal>)`` reads says the tail is that many
defects. The measured finding is the opposite: most are
contracts. ``scripts/tail_site_triage.py`` makes that checkable by
answering the two clauses a machine can, and this pins the split so the
count cannot be quoted as a debt figure again.

The ratio is the point. Three fifths of the tail reads keys that are not row
fields at all, a quarter sits in modules whose suites pin them tolerating
malformed input, and what is left is small enough for a person to read.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import tail_site_triage as triage


def _committed() -> dict:
    return json.loads(triage.RECEIPT.read_text(encoding="utf-8"))


def test_the_triage_receipt_matches_the_tree():
    """Derived, not written: a site moving class turns this red."""
    assert _committed() == triage.triage()


def test_the_tail_is_mostly_not_convertible_at_all():
    """The headline the raw count hides.

    Asserted as a share rather than a number so it survives the tail
    shrinking, and asserted in both directions so neither an empty scan nor
    a runaway one passes.

    The floor is on the scan and not on the debt: a module joining the
    covered roots takes its whole site count out of this population, so a
    fixed total would turn red for the work it is measuring.
    """
    totals = _committed()["totals"]
    total = sum(totals.values())
    assert total > 100
    unconvertible = sum(
        totals[bucket]
        for bucket in ("NOT_A_ROW_FIELD", "NOT_A_ROW_RECEIVER", "TOLERANCE_CONTRACT")
    )
    assert totals["NOT_A_ROW_FIELD"] / total > 0.4
    assert unconvertible / total > 0.9


def test_no_tail_site_is_unexamined():
    """The tail is fully classified: every site has evidence behind it.

    CANDIDATE means UNEXAMINED, so an empty class is the finish line rather
    than a shrug. It is only meaningful beside the negative below, which
    proves the classifier still produces one when a site deserves it.
    """
    receipt = _committed()
    assert receipt["totals"].get("CANDIDATE", 0) == 0
    assert receipt["candidates_by_module"] == {}


def test_a_new_unexamined_site_would_still_be_reported():
    """Why zero means done rather than broken.

    A classifier that silently stopped producing CANDIDATE would report the
    same zero as a finished tail. This drives the same predicate over a
    fabricated site that clears every filter, and requires it back.
    """
    censused = sorted(triage._censused_keys())
    assert censused, "no censused keys; the corpora are not loading"
    key = censused[0]
    receiver = "event"
    assert receiver not in triage.NON_ROW_RECEIVERS
    expression = f'{receiver}.get("{key}", 0.0)'
    assert triage._receiver(expression) == receiver
    # Not adjudicated anywhere, and its receiver and key both pass: the only
    # class left for it is CANDIDATE.
    assert all(expression not in sites for sites in triage.ADJUDICATED.values())


def test_every_reported_class_is_populated():
    """A class in the receipt with no members is a classifier half-working."""
    for bucket, count in _committed()["totals"].items():
        assert count > 0, bucket


def test_a_censused_key_on_a_non_row_receiver_is_not_a_candidate():
    """The classifier's own false-positive guard.

    ``name`` is universal on three published streams AND on every cached
    champion and item dict, so matching the key alone called dozens of
    ``champion_data.get("name", "")`` reads convertible. Receiver-blind
    triage over-reports the work by roughly a factor of two.
    """
    assert triage._receiver('champion_data.get("name", "")') == "champion_data"
    assert (
        triage._receiver('pair.attacker.champion_data.get("name", "")')
        == "champion_data"
    )
    assert triage._receiver('getattr(action, "time", 0.0)') is None
    assert "champion_data" in triage.NON_ROW_RECEIVERS
    assert _committed()["totals"]["NOT_A_ROW_RECEIVER"] > 50


def test_the_tolerance_signal_finds_the_modules_it_was_built_from():
    """The two readers clause 5 was written for must land there.

    Without this the signal could silently degrade to matching nothing and
    the split would quietly become optimistic.
    """
    tolerant = triage._tolerance_modules()
    assert "public_response.py" in tolerant
    assert "bis_objective.py" in tolerant


def test_every_adjudication_states_the_measurement_that_decided_it():
    """An adjudication without a number is a suppression.

    This class exists so the candidate count falls for sites examined and
    deliberately kept. That only works if each entry carries the evidence,
    otherwise it is a quiet allowlist and the count becomes a claim rather
    than a measurement.
    """
    for module, sites in triage.ADJUDICATED.items():
        assert sites, module
        for expression, reason in sites.items():
            assert reason.strip(), f"{module}: {expression}"
            assert any(
                char.isdigit() for char in reason
            ), f"{module}: {expression} is kept with no measurement behind it"


def test_an_adjudicated_site_still_exists_in_the_tree():
    """A stale entry would shrink the count for work the tree does not hold."""
    from pathlib import Path

    import literal_defaults

    for module, sites in triage.ADJUDICATED.items():
        path = Path("src/calculator") / module
        assert path.is_file(), module
        live = {finding.expression for finding in literal_defaults.scan([path])}
        assert set(sites) <= live, f"{module}: {sorted(set(sites) - live)}"


def test_the_unexamined_remainder_is_what_the_count_reports():
    """CANDIDATE means unexamined, not unconverted.

    The distinction is the point: 20 of the 28 sites this class held were
    already measured and kept for a stated reason, and reporting them as
    outstanding work overstated what was left by two and a half times.
    """
    totals = _committed()["totals"]
    assert totals["ADJUDICATED"] > 0
    assert totals.get("CANDIDATE", 0) == 0
