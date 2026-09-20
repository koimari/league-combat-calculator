"""Rule-5 lint: the scanned files read no cached data behind a literal default.

`scripts/literal_defaults.py` flags `.get("key", <literal>)`, `<get> or
<literal>` and `getattr(o, "attr", <literal>)`, exempting an index into a
local accumulator and a None-coalesce by shape.  What survives is frozen in
`scripts/literal_defaults_baseline.txt` beside the scanner, one line per site,
keyed by module, enclosing function, key and occurrence count.  This is the
gate that holds a fresh scan against that file; the file itself says what each
bucket licenses and which roots are covered.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import literal_defaults

FROZEN = literal_defaults.load_baseline()
CALCULATOR = literal_defaults.PACKAGE


def test_no_ability_payload_read_carries_a_literal_default():
    """Bucket A is zero: every payload field goes through ability_atoms."""
    offenders = [
        f"{finding.path}:{finding.line}: {finding.expression}"
        for finding in literal_defaults.scan(FROZEN.covered_files(FROZEN.payload_scope))
        if finding.expression.startswith(FROZEN.payload_receivers)
    ]
    assert offenders == []


def test_the_surviving_literal_defaults_are_the_frozen_ones():
    """Nothing new joins a bucket, and a retired row leaves it."""
    found = literal_defaults.scanned_rows(FROZEN.covered_files())
    unfrozen = sorted(found - FROZEN.frozen_rows())
    assert unfrozen == [], (
        "sites with no baseline row; either convert them or add "
        "`<BUCKET>|<module>|<enclosing>|<kind>|<key> <count>` to "
        f"{literal_defaults.BASELINE.name}"
    )
    stale = sorted(site.line() for site in FROZEN.sites if site[1:] not in found)
    assert stale == [], f"baseline rows no site answers; drop them from {stale}"


def test_every_covered_root_exists():
    """A root renamed out from under the pin fails here, not silently."""
    missing = [root for root in FROZEN.roots if not (CALCULATOR / root).exists()]
    assert missing == []


def test_every_bucket_states_what_it_licenses():
    """A bucket is a licence, so the file must say what it licences."""
    used = {site.bucket for site in FROZEN.sites}
    assert used - set(FROZEN.reasons) == set()
    assert set(FROZEN.reasons) - used == set()
    assert all(FROZEN.reasons.values())


def test_the_frontier_only_ever_moves_towards_the_covered_set():
    """The uncovered tail is derived, and its count may only fall.

    A module joins the roots and the count drops; a covered module demoted
    out of them, or a module new to the package, pushes it over the ceiling
    and fails closed until somebody decides which side it is on.
    """
    tail = FROZEN.er5_tail()
    assert len(tail) <= FROZEN.er5_tail_ceiling, sorted(tail)


def test_the_scanner_still_finds_a_planted_cached_data_default(tmp_path):
    """The gate is driven by a real scan, not by an empty one."""
    planted = tmp_path / "planted.py"
    planted.write_text(
        "def f(info):" + chr(10) + "    return info.get('dot_duration', 0.0)" + chr(10),
        encoding="utf-8",
    )
    assert [f.key for f in literal_defaults.scan([planted])] == ["'dot_duration'"]


def test_an_accumulator_index_and_a_none_coalesce_stay_exempt(tmp_path):
    """Both exemptions are shape rules, so a planted pair proves them."""
    planted = tmp_path / "exempt.py"
    planted.write_text(
        "def f(by_type, dtype, maybe):"
        + chr(10)
        + "    return by_type.get(dtype, 0.0), (maybe or 0.0)"
        + chr(10),
        encoding="utf-8",
    )
    assert literal_defaults.scan([planted]) == []
