"""The evidence codemod rewrites the paths the resolver reads, and only those."""

import subprocess
import sys
from pathlib import Path

import pytest

from scripts.rename_evidence import EVIDENCE_HOMES, rewrite

ROOT = Path(__file__).resolve().parents[1]

#: One path each home authors today.  A home that stops authoring any is a home
#: the codemod would rewrite nothing in, which is the silence it exists to stop.
LIVE_PATH_PER_HOME = {
    "src/calculator/item_coverage.py": "fight.items.burns._add_burn_damage",
    "src/calculator/ledger_projection.py": (
        "fight.after.shield_outcome._resolve_starting_shield_outcome"
    ),
    "src/calculator/trigger_stream.py": (
        "fight.items.ultimate_procs._add_ultimate_proc_damage"
    ),
}


def test_only_the_whole_quoted_path_is_rewritten():
    text = '"fight.items.burns._add_burn_damage", "damage._add_burn_damage_extra", add_burn\n'
    rewritten, count = rewrite(
        text, "fight.items.burns._add_burn_damage", "damage._add_burn"
    )
    assert count == 1
    assert (
        rewritten == '"damage._add_burn", "damage._add_burn_damage_extra", add_burn\n'
    )


def test_every_authoring_home_exists():
    """A home that moved makes the codemod silently rewrite nothing."""
    for relative in EVIDENCE_HOMES:
        assert (ROOT / relative).is_file(), relative


@pytest.mark.parametrize("relative", EVIDENCE_HOMES, ids=lambda p: p.stem)
def test_each_home_authors_a_path_the_codemod_reaches(relative):
    """Every listed home carries at least one dotted path this rewrite finds."""
    text = (ROOT / relative).read_text(encoding="utf-8")
    live = LIVE_PATH_PER_HOME[relative.as_posix()]
    assert rewrite(text, live, "damage._renamed")[1] >= 1


def test_a_dry_run_reports_the_live_paths_and_writes_nothing():
    home = ROOT / EVIDENCE_HOMES[0]
    before = home.read_bytes()
    result = subprocess.run(
        [
            sys.executable,
            "scripts/rename_evidence.py",
            "--check",
            "fight.items.burns._add_burn_damage",
            "damage._renamed",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "would rewrite" in result.stdout
    assert home.read_bytes() == before


def test_an_unknown_path_is_a_failure_and_not_a_silent_no_op():
    result = subprocess.run(
        [
            sys.executable,
            "scripts/rename_evidence.py",
            "--check",
            "damage.no_such_symbol_anywhere",
            "damage.other",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "no evidence path names" in result.stderr
