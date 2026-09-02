"""Systemic tripwire for the "gitignored local evidence file referenced by
a CI test" failure class.

Three times now a test that references a gitignored local cache path
(``data/bin/characters/*.bin.json``, ``data/bin/items.bin.json``,
``data/gamefiles/ddragon/*.json`` -- see ``data/bin/README.md`` and
``data/README.md``) passed on a machine that happened to have the local
cache and errored with ``FileNotFoundError`` on CI, which does not.  The
locally-built receipt trees ``docs/receipts/champions/`` and
``docs/receipts/items/`` (``scripts/build_receipts.py``) are the same class
and are watched too; :data:`WATCHED_PREFIXES` is the one list. Each
occurrence was fixed one-off by force-tracking the missing evidence file
(commits ``58ce29e``, ``5784e68``, ``712184b``). This module is the
systemic guard so the next occurrence is caught here instead of in CI.

Scanner design
---------------
For every file under ``tests/`` (this module excluded -- see below) the
scanner:

1. Parses the file with ``ast`` (Python files only) and records the line
   ranges of every module/class/function *docstring*. Text inside those
   ranges is excluded from reference detection: a docstring citing
   ``data/bin/items.bin.json`` as evidence (several files do this, purely
   as prose) can never raise ``FileNotFoundError`` -- it is never passed
   to ``Path``/``open``. Treating it as "referenced" would force busywork
   guards on files that do not open anything. Verified against the
   current tree: ``test_cleanse_eligibility.py`` and
   ``test_fimbulwinter_mana_gate_authority.py`` cite
   ``data/bin/items.bin.json`` only in docstrings and are correctly
   excluded (see ``test_scanner_excludes_pure_docstring_citations``).
2. Scans the remaining (non-docstring) text line by line for:
   - single quoted string literals containing one of
     :data:`WATCHED_PREFIXES` (``_LITERAL_RE``), and
   - chains of 2+ string literals joined with the ``pathlib`` ``/``
     operator, e.g. ``ROOT / "data" / "bin" / "characters" /
     "gnar.bin.json"`` or ``Path(__file__).resolve().parent.parent /
     "data" / "bin" / "items.bin.json"`` (``_JOIN_CHAIN_RE``), which are
     joined back into one candidate string.
3. Keeps only candidates that resolve to a *concrete file* -- the joined
   text must start at a watched prefix and end in a dotted extension
   (``_CONCRETE_RE``). This drops bare directory
   references (``data/gamefiles``, ``data/bin/characters`` -- used in
   ``test_patch_update.py`` for tree-wide stat fingerprinting, not to
   open one named file) and receipt-tag fragments that merely *mention*
   the prefix without naming a file (``test_vladimir_e_charge_time.py``
   and ``test_zeri_p_execute_range.py`` embed
   ``f"...;data/bin/characters"`` as a manifest ``source_ref`` tag, not a
   path to open).
4. Drops any candidate whose containing literal/chain contains ``{``
   (an f-string interpolation) -- these are dynamic and cannot be
   resolved to one concrete path from source text alone (documented
   limitation, not silently ignored: see "Limitations" below).

Remedy check (for every surviving concrete path)
-------------------------------------------------
A reference passes if EITHER:

  (a) the path is git-tracked (``git ls-files`` over the watched trees,
      subprocess run once and cached at module scope), OR
  (b) the *referencing file* contains one of the two absence-guard
      idioms this codebase already uses across its 20+ evidence tests
      (``_GUARD_RE``):

        - ``if not <expr>.exists(): ... pytest.skip(...)`` (the function
          -local form used by e.g. ``test_dr_mundo_passive.py``,
          ``test_rengar_w_cleanse.py``, ``test_olaf_r_cleanse.py``,
          ``test_milio_r_cleanse.py``, ``test_renata_w_bailout.py``,
          ``test_gunmetal_greaves_riot_branch.py``), or
        - the module-level ternary ``X = (... if <expr>.exists() else
          None)`` (used by e.g. ``test_ashe_focus_lifecycle.py``,
          ``test_ashe_q_active_window.py``, ``test_aurelion_sol_stardust.py``,
          ``test_quinn_p_crit.py``, ``test_senna_relic_cannon.py``,
          ``test_gnar_mega_gamefile.py``), or
        - ``os.path.exists(...): ... pytest.skip(...)``, or
        - a ``pytest.mark.skipif(...)`` decorator (named in the task
          brief; not currently used by any file, supported for
          forward-compatibility).

Failure names the referencing file, the unresolved path, and both
remedies (track the file, precedent commits 58ce29e/5784e68/712184b; or
add one of the guard idioms above).

Limitations (deliberately not "fixed" by widening the regex further --
each is a documented, low-risk trade-off)
------------------------------------------------------------------------
- Guard detection is **file-scoped, not line-proximity-scoped**: it
  checks whether the referencing file contains a recognized guard idiom
  ANYWHERE, not whether that idiom specifically wraps the one flagged
  literal. This is necessary because at least one real case
  (``test_renata_w_bailout.py``) guards a path built from a dict lookup
  (``renata_glasc.BAILOUT_AUTHORITY["gamefile_path"]``) rather than from
  the literal string itself, so the literal and its guard are not
  textually adjacent. Every current evidence-test file is single-subject
  (one gitignored evidence file per module), so file-scoping is sound
  today; a future file that references two DIFFERENT untracked evidence
  paths where only one is guarded would false-pass. Flagged here rather
  than silently accepted.
- Candidates spanning multiple physical source lines are not resolved
  (every current join-chain and literal in the corpus fits on one
  line -- verified by inspection while building this scanner).
- f-string interpolations are treated as unresolvable and dropped, not
  guessed at (fail-closed: they are excluded from the "must be
  tracked-or-guarded" requirement rather than silently assumed safe or
  falsely demanded to match a made-up literal).
- Does not distinguish a real repo-rooted path (``ROOT / "data" / ...``,
  ``Path(__file__).resolve().parent.parent / "data" / ...``) from a
  synthetic path built under a ``tmp_path``-derived variable
  (``test_patch_update.py`` builds ``repo / "data" / "bin" /
  "characters"`` against a scratch git repo in several tests). This is
  harmless today: the only synthetic-repo literal that also names a
  concrete file (``"data/bin/characters/gnarbig.bin.json"``, asserted as
  a *return value*, not opened) happens to name a file that IS tracked
  in the real repo, so it passes via the tracked-path check regardless.
- This module excludes itself from the scan: its own source text
  necessarily contains the guard-idiom substrings it searches for (as
  regex literals and, previously, as test fixture strings), which would
  otherwise create a confusing self-referential match. The unit test for
  ``_GUARD_RE`` below deliberately uses a non-``data/`` path so it does
  not depend on this exclusion either.
"""

from __future__ import annotations

import ast
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parent
_SELF = Path(__file__).resolve()

# Every tree whose contents are gitignored, locally-built evidence.  One home:
# the extraction regexes and the tracked-path query below both read it, so a
# new locally-built tree is watched by adding it here and nowhere else.
WATCHED_PREFIXES = (
    "data/bin/",
    "data/gamefiles/",
    "docs/receipts/champions/",
    "docs/receipts/items/",
)
_PREFIX_ALTERNATION = "|".join(re.escape(prefix) for prefix in WATCHED_PREFIXES)
# The cheap substring gate the per-line scan opens with, derived from the same
# list so a new watched tree is not silently skipped by a stale literal.
_PREFIX_HINTS = tuple(sorted({prefix.split("/", 1)[0] for prefix in WATCHED_PREFIXES}))

# ---------------------------------------------------------------------------
# Reference extraction
# ---------------------------------------------------------------------------

# A quoted string literal (single or double quoted) whose content contains
# one of the watched prefixes anywhere inside it.
_LITERAL_RE = re.compile(
    r"""(?P<quote>["'])"""
    r"""(?P<body>(?:(?!(?P=quote)).)*?(?:"""
    + _PREFIX_ALTERNATION
    + r""")(?:(?!(?P=quote)).)*?)"""
    r"""(?P=quote)"""
)

# A chain of 2+ quoted segments joined by the pathlib `/` operator, e.g.
# `ROOT / "data" / "bin" / "characters" / "gnar.bin.json"`.
_JOIN_CHAIN_RE = re.compile(r"""(?:["'][^"']*["']\s*/\s*){1,}["'][^"']*["']""")
_SEGMENT_RE = re.compile(r"""["']([^"']*)["']""")

# A resolved candidate must start at the watched prefix and end in a dotted
# extension to count as a concrete FILE (excludes bare directory refs like
# "data/gamefiles" or "data/bin/characters", and truncated receipt-tag
# fragments like "data/bin/characters" that name no file).
_CONCRETE_RE = re.compile(
    r"((?:" + _PREFIX_ALTERNATION + r")[A-Za-z0-9_.\-/]*\.[A-Za-z0-9]+)"
)

# The two established absence-guard idioms (plus os.path.exists and
# pytest.mark.skipif, named in the task brief for forward-compatibility).
_GUARD_RE = re.compile(
    r"\.exists\(\)\s*:\s*\n\s*(?:#[^\n]*\n\s*)*pytest\.skip\("
    r"|\.exists\(\)\s*\n?\s*else\b"
    r"|os\.path\.exists\([^)\n]*\)\s*:\s*\n\s*(?:#[^\n]*\n\s*)*pytest\.skip\("
    r"|pytest\.mark\.skipif\("
)


@dataclass(frozen=True)
class Reference:
    """One concrete gitignored-evidence path referenced by one test file."""

    file: str
    path: str
    line: int


def _iter_statement_containers(root: ast.AST):
    """Yield ``root`` and every nested statement-container node.

    Deliberately narrower than ``ast.walk``: it only descends through
    ``body``/``orelse``/``finalbody``/``handlers`` (the only fields that
    can hold a nested docstring-bearing ``ClassDef``/``FunctionDef``), and
    never descends into expression subtrees. ``ast.walk`` visits every
    node including deep ``assert``/``Call`` expression trees, which is
    the dominant cost on this suite's larger files (multi-thousand-line
    acceptance-matrix modules) -- profiling showed it accounted for most
    of this scanner's runtime with no benefit, since docstrings can only
    live in a statement list.
    """
    stack = [root]
    while stack:
        current = stack.pop()
        yield current
        for field_name in ("body", "orelse", "finalbody"):
            value = getattr(current, field_name, None)
            if value:
                stack.extend(value)
        stack.extend(getattr(current, "handlers", None) or ())


def _docstring_excluded_lines(source: str) -> frozenset[int]:
    """Line numbers covered by a module/class/function docstring.

    Fails open (returns no exclusions, i.e. scans everything) if the file
    does not parse -- a syntax error here is not this scanner's problem to
    hide, and scanning too much is the safe failure direction.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return frozenset()
    excluded: set[int] = set()
    for node in _iter_statement_containers(tree):
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr):
                value = body[0].value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    start = value.lineno
                    end = getattr(value, "end_lineno", start)
                    excluded.update(range(start, end + 1))
    return frozenset(excluded)


def _raw_candidates(source: str) -> dict[str, int]:
    """Regex-only pass: (concrete path -> first line) ignoring docstrings.

    Cheap and run on every file; ``ast.parse`` is only paid for by files
    this finds at least one candidate in (see ``_scan_text``), since the
    parse itself -- not the traversal -- dominates cost on this suite's
    largest files and most lines mention no watched tree at all.
    """
    found: dict[str, int] = {}
    for lineno, line in enumerate(source.splitlines(), start=1):
        if not any(hint in line for hint in _PREFIX_HINTS):
            continue
        for match in _LITERAL_RE.finditer(line):
            body = match.group("body")
            if "{" in body:
                continue  # dynamic f-string interpolation -- unresolvable
            concrete = _CONCRETE_RE.search(body)
            if concrete:
                found.setdefault(concrete.group(1), lineno)
        for match in _JOIN_CHAIN_RE.finditer(line):
            chain_text = match.group(0)
            if "{" in chain_text:
                continue
            joined = "/".join(_SEGMENT_RE.findall(chain_text))
            concrete = _CONCRETE_RE.search(joined)
            if concrete:
                found.setdefault(concrete.group(1), lineno)
    return found


def _scan_text(rel_file: str, source: str, *, is_python: bool) -> list[Reference]:
    candidates = _raw_candidates(source)
    if not candidates:
        return []
    if is_python:
        excluded = _docstring_excluded_lines(source)
        candidates = {
            path: lineno
            for path, lineno in candidates.items()
            if lineno not in excluded
        }
    return [
        Reference(rel_file, path, line) for path, line in sorted(candidates.items())
    ]


def _discover() -> tuple[list[Reference], dict[str, str]]:
    references: list[Reference] = []
    texts: dict[str, str] = {}
    for path in sorted(TESTS_DIR.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path == _SELF:
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(ROOT).as_posix()
        texts[rel] = source
        references.extend(_scan_text(rel, source, is_python=path.suffix == ".py"))
    return references, texts


def _tracked_evidence_paths() -> frozenset[str]:
    result = subprocess.run(
        ["git", "ls-files", *(prefix.rstrip("/") for prefix in WATCHED_PREFIXES)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return frozenset(
        line.strip() for line in result.stdout.splitlines() if line.strip()
    )


ALL_REFERENCES, _FILE_TEXT = _discover()
TRACKED_PATHS = _tracked_evidence_paths()


def _has_guard(rel_file: str) -> bool:
    return bool(_GUARD_RE.search(_FILE_TEXT.get(rel_file, "")))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reference",
    ALL_REFERENCES,
    ids=[f"{ref.file}::{ref.path}" for ref in ALL_REFERENCES],
)
def test_evidence_reference_is_tracked_or_guarded(reference: Reference) -> None:
    """The tripwire: every discovered reference must be tracked or guarded."""
    if reference.path in TRACKED_PATHS:
        return
    assert _has_guard(reference.file), (
        f"{reference.file}:{reference.line} references the gitignored "
        f"evidence path {reference.path!r}, which is neither git-tracked "
        f"(`git ls-files {reference.path}` finds nothing) nor guarded by a "
        "recognized absence-guard idiom in that file (`if not "
        "<Path>.exists(): pytest.skip(...)`, the `... if <Path>.exists() "
        "else ...` ternary, `os.path.exists(...)` + `pytest.skip(...)`, or "
        "`pytest.mark.skipif`). This is the failure class fixed one-off in "
        "58ce29e/5784e68/712184b -- it passes locally and errors on CI. "
        "Remedy: EITHER force-track the evidence file (`git add -f "
        f"{reference.path}`, matching that precedent) OR add one of the "
        "guard idioms above so the test skips instead of erroring when "
        "the local cache is absent."
    )


def test_scanner_finds_the_known_reference_corpus() -> None:
    """Sanity check: the scanner must not silently find nothing.

    Names files known (by direct inspection while building this scanner)
    to carry a real, code-level, non-docstring evidence reference. If this
    fails, the extraction regex broke, not the corpus.
    """
    files = {ref.file for ref in ALL_REFERENCES}
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
    assert len(ALL_REFERENCES) >= 15


def test_scanner_resolves_join_chains_not_just_single_literals() -> None:
    """`Path(...) / "data" / "bin" / "x.json"` style joins must resolve.

    test_gunmetal_greaves_riot_branch.py builds BINARY_ITEMS_PATH from
    `Path(__file__).resolve().parent.parent / "data" / "bin" /
    "items.bin.json"` -- no single literal contains "data/bin/" as
    continuous text, only the join does.
    """
    paths = {
        ref.path
        for ref in ALL_REFERENCES
        if ref.file == "tests/test_gunmetal_greaves_riot_branch.py"
    }
    assert "data/bin/items.bin.json" in paths

    milio_paths = {
        ref.path
        for ref in ALL_REFERENCES
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
    files = {ref.file for ref in ALL_REFERENCES}
    assert "tests/test_cleanse_eligibility.py" not in files
    assert "tests/test_fimbulwinter_mana_gate_authority.py" not in files


def test_scanner_drops_directory_references_and_receipt_tag_fragments() -> None:
    """Bare directories and truncated receipt tags name no concrete file."""
    weekly_paths = {
        ref.path for ref in ALL_REFERENCES if ref.file == "tests/test_patch_update.py"
    }
    assert "data/gamefiles" not in weekly_paths
    assert "data/bin/characters" not in weekly_paths

    zeri_paths = {
        ref.path
        for ref in ALL_REFERENCES
        if ref.file == "tests/test_zeri_p_execute_range.py"
    }
    assert not any(path.startswith("data/bin/characters") for path in zeri_paths)


def test_guard_regex_recognizes_both_established_idioms() -> None:
    """Unit-tests `_GUARD_RE` directly, independent of the live corpus.

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

    assert _GUARD_RE.search(inline_skip)
    assert _GUARD_RE.search(ternary)
    assert _GUARD_RE.search(os_path_skip)
    assert _GUARD_RE.search(skipif_decorator)
    assert not _GUARD_RE.search(unguarded)


def test_concrete_path_extraction_requires_a_file_extension() -> None:
    """Directory-shaped candidates are dropped; file-shaped ones survive."""
    assert _CONCRETE_RE.search("data/gamefiles") is None
    assert _CONCRETE_RE.search("data/bin/characters") is None
    match = _CONCRETE_RE.search("data/bin/characters/ashe.bin.json")
    assert match is not None
    assert match.group(1) == "data/bin/characters/ashe.bin.json"


def test_tracked_paths_lookup_matches_git_ls_files() -> None:
    """The cached TRACKED_PATHS set agrees with a fresh `git ls-files` run."""
    result = subprocess.run(
        ["git", "ls-files", *(prefix.rstrip("/") for prefix in WATCHED_PREFIXES)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    fresh = frozenset(
        line.strip() for line in result.stdout.splitlines() if line.strip()
    )
    assert fresh == TRACKED_PATHS
    assert "data/bin/characters/gnar.bin.json" in TRACKED_PATHS
    assert "data/gamefiles/ddragon/Milio.json" in TRACKED_PATHS
    # Every champion dump is tracked now (binary-rooted constants policy):
    # the runtime resolves priced values from data/bin/characters/, so an
    # untracked champion would 500 in production while passing locally.
    assert "data/bin/characters/ashe.bin.json" in TRACKED_PATHS
    assert "data/bin/characters/aurelionsol.bin.json" in TRACKED_PATHS


def test_the_locally_built_receipt_trees_are_watched() -> None:
    """``build_receipts.py``'s output is gitignored, so it is the same class.

    Driven over fabricated source text rather than over the corpus: the
    trees are rebuilt locally and a tree that happens to be empty here would
    otherwise let the widening pass by finding nothing.
    """
    assert "docs/receipts/champions/" in WATCHED_PREFIXES
    assert "docs/receipts/items/" in WATCHED_PREFIXES
    fabricated = "\n".join(  # noqa: FLY002 - one fabricated line per shape
        (
            '_R = Path("docs/receipts/champions/vladimir.json")',
            'ITEM = ROOT / "docs" / "receipts" / "items" / "1001.json"',
        )
    )
    found = _scan_text("tests/fabricated.py", fabricated, is_python=True)
    assert {ref.path for ref in found} == {
        "docs/receipts/champions/vladimir.json",
        "docs/receipts/items/1001.json",
    }
    # The tree itself names no file, so it is not a reference.
    assert not _scan_text(
        "tests/fabricated.py", '_D = Path("docs/receipts")', is_python=True
    )
