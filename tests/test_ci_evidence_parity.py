"""The evidence-reference tripwire, one test per discovered reference.

`scripts/ci_evidence_parity.py` owns the scanner and the prose that explains
every extraction and remedy rule; this drives it over the real corpus and
pins each rule against fabricated source text.
"""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import ci_evidence_parity as scanner

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "reference",
    scanner.ALL_REFERENCES,
    ids=[f"{ref.file}::{ref.path}" for ref in scanner.ALL_REFERENCES],
)
def test_evidence_reference_is_tracked_or_guarded(reference: scanner.Reference) -> None:
    """The tripwire: every discovered reference must be tracked or guarded."""
    if reference.path in scanner.TRACKED_PATHS:
        return
    assert scanner.has_guard(reference.file), scanner.remedy(reference)


def test_scanner_finds_the_known_reference_corpus() -> None:
    """Sanity check: the scanner must not silently find nothing.

    Names files known (by direct inspection while building this scanner)
    to carry a real, code-level, non-docstring evidence reference. If this
    fails, the extraction regex broke, not the corpus.
    """
    files = {ref.file for ref in scanner.ALL_REFERENCES}
    for expected in (
        "tests/test_gnar_mega_gamefile.py",
        "tests/test_dr_mundo_passive.py",
        "tests/test_ashe_focus_lifecycle.py",
        "tests/test_gunmetal_greaves_riot_branch.py",
        "tests/test_milio_fired_up_blocker.py",
    ):
        assert (
            expected in files
        ), f"scanner unexpectedly found no reference in {expected}"
    assert len(scanner.ALL_REFERENCES) >= 15


def test_scanner_resolves_join_chains_not_just_single_literals() -> None:
    """`Path(...) / "data" / "bin" / "x.json"` style joins must resolve.

    test_gunmetal_greaves_riot_branch.py builds BINARY_ITEMS_PATH from
    `Path(__file__).resolve().parent.parent / "data" / "bin" /
    "items.bin.json"` -- no single literal contains "data/bin/" as
    continuous text, only the join does.
    """
    paths = {
        ref.path
        for ref in scanner.ALL_REFERENCES
        if ref.file == "tests/test_gunmetal_greaves_riot_branch.py"
    }
    assert "data/bin/items.bin.json" in paths

    milio_paths = {
        ref.path
        for ref in scanner.ALL_REFERENCES
        if ref.file == "tests/test_milio_fired_up_blocker.py"
    }
    assert "data/gamefiles/ddragon/Milio.json" in milio_paths


def test_scanner_excludes_pure_docstring_citations() -> None:
    """Files that only cite an evidence path in prose must not be flagged.

    test_cleanse_eligibility.py and test_fimbulwinter_mana_gate_authority.py
    both cite `data/bin/items.bin.json` as evidence in a docstring only --
    neither ever opens it -- so neither can raise FileNotFoundError and
    neither should be forced to carry a guard.
    """
    files = {ref.file for ref in scanner.ALL_REFERENCES}
    assert "tests/test_cleanse_eligibility.py" not in files
    assert "tests/test_fimbulwinter_mana_gate_authority.py" not in files


def test_scanner_drops_directory_references_and_receipt_tag_fragments() -> None:
    """Bare directories and truncated receipt tags name no concrete file."""
    weekly_paths = {
        ref.path
        for ref in scanner.ALL_REFERENCES
        if ref.file == "tests/test_patch_update.py"
    }
    assert "data/gamefiles" not in weekly_paths
    assert "data/bin/characters" not in weekly_paths

    zeri_paths = {
        ref.path
        for ref in scanner.ALL_REFERENCES
        if ref.file == "tests/test_zeri_p_execute_range.py"
    }
    assert not any(path.startswith("data/bin/characters") for path in zeri_paths)


def test_guard_regex_recognizes_both_established_idioms() -> None:
    """Unit-tests `scanner._GUARD_RE` directly, independent of the live corpus.

    Uses a non-`data/` path on purpose: this test's own purpose is to pin
    the guard-detection mechanics, not to feed the path-reference scanner.
    """
    inline_skip = (
        'path = Path("some/other/evidence.json")\n'
        "if not path.exists():\n"
        '    pytest.skip("evidence unavailable")\n'
    )
    ternary = (
        '_X_PATH = Path("some/other/evidence.json")\n'
        "_X = (\n"
        "    json.loads(_X_PATH.read_text())\n"
        "    if _X_PATH.exists()\n"
        "    else None\n"
        ")\n"
    )
    os_path_skip = (
        'path = "some/other/evidence.json"\n'
        "if not os.path.exists(path):\n"
        '    pytest.skip("evidence unavailable")\n'
    )
    skipif_decorator = '@pytest.mark.skipif(not Path("x").exists(), reason="missing")\n'
    unguarded = 'path = Path("some/other/evidence.json")\ndata = path.read_text()\n'

    assert scanner._GUARD_RE.search(inline_skip)
    assert scanner._GUARD_RE.search(ternary)
    assert scanner._GUARD_RE.search(os_path_skip)
    assert scanner._GUARD_RE.search(skipif_decorator)
    assert not scanner._GUARD_RE.search(unguarded)


def test_concrete_path_extraction_requires_a_file_extension() -> None:
    """Directory-shaped candidates are dropped; file-shaped ones survive."""
    assert scanner._CONCRETE_RE.search("data/gamefiles") is None
    assert scanner._CONCRETE_RE.search("data/bin/characters") is None
    match = scanner._CONCRETE_RE.search("data/bin/characters/ashe.bin.json")
    assert match is not None
    assert match.group(1) == "data/bin/characters/ashe.bin.json"


def test_tracked_paths_lookup_matches_git_ls_files() -> None:
    """The cached scanner.TRACKED_PATHS set agrees with a fresh `git ls-files` run."""
    result = subprocess.run(
        [
            "git",
            "ls-files",
            *(prefix.rstrip("/") for prefix in scanner.WATCHED_PREFIXES),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    fresh = frozenset(
        line.strip() for line in result.stdout.splitlines() if line.strip()
    )
    assert fresh == scanner.TRACKED_PATHS
    assert "data/bin/characters/gnar.bin.json" in scanner.TRACKED_PATHS
    assert "data/gamefiles/ddragon/Milio.json" in scanner.TRACKED_PATHS
    # Every champion dump is tracked now (binary-rooted constants policy):
    # the runtime resolves priced values from data/bin/characters/, so an
    # untracked champion would 500 in production while passing locally.
    assert "data/bin/characters/ashe.bin.json" in scanner.TRACKED_PATHS
    assert "data/bin/characters/aurelionsol.bin.json" in scanner.TRACKED_PATHS


def test_the_locally_built_receipt_trees_are_watched() -> None:
    """``build_receipts.py``'s output is gitignored, so it is the same class.

    Driven over fabricated source text rather than over the corpus: the
    trees are rebuilt locally and a tree that happens to be empty here would
    otherwise let the widening pass by finding nothing.
    """
    assert "docs/receipts/champions/" in scanner.WATCHED_PREFIXES
    assert "docs/receipts/items/" in scanner.WATCHED_PREFIXES
    fabricated = "\n".join(  # noqa: FLY002 - one fabricated line per shape
        (
            '_R = Path("docs/receipts/champions/vladimir.json")',
            'ITEM = ROOT / "docs" / "receipts" / "items" / "1001.json"',
        )
    )
    found = scanner.scan_text("tests/fabricated.py", fabricated, is_python=True)
    assert {ref.path for ref in found} == {
        "docs/receipts/champions/vladimir.json",
        "docs/receipts/items/1001.json",
    }
    # The tree itself names no file, so it is not a reference.
    assert not scanner.scan_text(
        "tests/fabricated.py", '_D = Path("docs/receipts")', is_python=True
    )
