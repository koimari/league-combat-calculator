"""The ER5 tail, split by what the evidence already decides about it.

A raw count of ``x.get(key, <literal>)`` reads says the tail is about 1,278
defects. The campaign's repeated finding is the opposite: most are
contracts. ``scripts/tail_site_triage.py`` makes that checkable by
answering the two clauses a machine can, and this pins the split so the
count cannot be quoted as a debt figure again.

The ratio is the point. Roughly half the tail reads keys that are not row
fields at all, a third sits in modules whose suites pin them tolerating
malformed input, and what is left is small enough for a person to read.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import tail_site_triage as triage  # noqa: E402


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
    """
    totals = _committed()["totals"]
    total = sum(totals.values())
    assert total > 1000
    unconvertible = sum(
        totals[bucket]
        for bucket in ("NOT_A_ROW_FIELD", "NOT_A_ROW_RECEIVER", "TOLERANCE_CONTRACT")
    )
    assert totals["NOT_A_ROW_FIELD"] / total > 0.4
    assert unconvertible / total > 0.9


def test_the_actionable_remainder_is_small_and_named():
    """What a person should actually read, and where it lives."""
    receipt = _committed()
    candidates = receipt["totals"]["CANDIDATE"]
    total = sum(receipt["totals"].values())
    assert 0 < candidates < total * 0.15
    by_module = receipt["candidates_by_module"]
    assert sum(by_module.values()) == candidates
    assert all(count > 0 for count in by_module.values())


def test_every_class_is_populated():
    """A split with an empty class is a classifier that stopped working."""
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
    assert triage._receiver('getattr(action, "time", 0.0)') is None
    assert "champion_data" in triage.NON_ROW_RECEIVERS
    assert _committed()["totals"]["NOT_A_ROW_RECEIVER"] > 50


def test_the_tolerance_signal_finds_the_modules_it_was_built_from():
    """The two readers that taught the campaign clause 5 must land there.

    Without this the signal could silently degrade to matching nothing and
    the split would quietly become optimistic.
    """
    tolerant = triage._tolerance_modules()
    assert "public_response.py" in tolerant
    assert "bis_objective.py" in tolerant
