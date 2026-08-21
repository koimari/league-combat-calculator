"""The evidence codemod rewrites the paths the resolver reads, and only those."""

import subprocess
import sys
from pathlib import Path

from scripts.rename_evidence import EVIDENCE_HOMES, rewrite

ROOT = Path(__file__).resolve().parents[1]


def test_only_the_whole_quoted_path_is_rewritten():
    text = '"damage._add_burn_damage", "damage._add_burn_damage_extra", add_burn\n'
    rewritten, count = rewrite(text, "damage._add_burn_damage", "damage._add_burn")
    assert count == 1
    assert (
        rewritten == '"damage._add_burn", "damage._add_burn_damage_extra", add_burn\n'
    )


def test_every_authoring_home_exists():
    """A home that moved makes the codemod silently rewrite nothing."""
    for relative in EVIDENCE_HOMES:
        assert (ROOT / relative).is_file(), relative


def test_a_dry_run_reports_the_live_paths_and_writes_nothing():
    home = ROOT / EVIDENCE_HOMES[0]
    before = home.read_bytes()
    result = subprocess.run(
        [
            sys.executable,
            "scripts/rename_evidence.py",
            "--check",
            "damage._add_burn_damage",
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
