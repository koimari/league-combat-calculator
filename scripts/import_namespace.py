"""One `src.calculator` namespace, and one owner per shared formula.

A Flask entry point that puts `src/` on `sys.path` and imports `calculator.*`
while tests and scripts import `src.calculator.*` loads two module trees in
one process, each with its own singletons.  The same class of duplication
reaches the math: a growth or cooldown term written a second time drifts from
the first with nothing to show for it.  Four rules, all read off the source
text rather than from an import:

* no `src/` module imports the bare `calculator` package;
* `src/app.py` puts the repo root on `sys.path`, never `src/`;
* the `0.7025` / `0.0175` growth term appears only in `stat_formulas.py`;
* `ability_dps_matrix.py` imports `effective_cooldown` and writes no
  `100.0 / (100.0 + ...)` of its own.

    python scripts/import_namespace.py

`tests/test_import_namespace.py` calls this and keeps the two subprocess
contracts, which are not scans.  Reading the tree from a script rather than
from a test is also what keeps a concurrent edit from producing a phantom
failure set in the middle of a suite run.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lint_report import report

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

#: The growth term, owned by `stat_formulas.growth_multiplier`.
GROWTH_TERMS = ("0.7025", "0.0175")
GROWTH_OWNER = "stat_formulas.py"

#: The cooldown term, owned by `stats.effective_cooldown`.
COOLDOWN_TERM = "100.0 / (100.0"
COOLDOWN_BORROWER = "src/calculator/ability_dps_matrix.py"

_BARE_IMPORT = re.compile(r"\s*(?:from|import) calculator(?:\s|\.)")
_DOCSTRING = re.compile(r'""".*?"""', re.DOTALL)


def _modules(root: Path = SRC) -> list[Path]:
    """Every `.py` under the source root, in tree order."""
    return [
        path for path in sorted(root.rglob("*.py")) if "__pycache__" not in path.parts
    ]


def _named(path: Path) -> str:
    """A module's path under the repo, or its own path when it is elsewhere."""
    return (
        path.relative_to(ROOT).as_posix()
        if path.is_relative_to(ROOT)
        else path.as_posix()
    )


def _code_lines(text: str) -> list[str]:
    """Source lines with comments and docstrings stripped.

    Prose may cite a formula; code may not, and that is the whole of the
    distinction the two formula rules below need.
    """
    lines = []
    for raw in _DOCSTRING.sub("", text).splitlines():
        line = re.sub(r"\s*#.*$", "", raw).strip()
        if line:
            lines.append(line)
    return lines


def bare_calculator_imports(root: Path = SRC) -> list[str]:
    """Every `calculator.*` import that does not go through `src`."""
    return [
        f"{_named(path)}:{lineno}: {line.strip()}"
        for path in _modules(root)
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if _BARE_IMPORT.match(line)
    ]


def sys_path_inserts(app: Path | None = None) -> list[str]:
    """Every `sys.path.insert` in the app that names something but the root."""
    path = app or SRC / "app.py"
    return [
        f"{_named(path)}:{lineno} inserts a " f"non-repo-root path: {line.strip()}"
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if "sys.path.insert" in line and "resolve().parents[1]" not in line
    ]


def growth_formula_sites(root: Path = SRC) -> list[str]:
    """Every module but the owner that writes the growth term in code."""
    return [
        f"{_named(path)}:{lineno}: {line}"
        for path in _modules(root)
        if path.name != GROWTH_OWNER
        for lineno, line in enumerate(_code_lines(path.read_text(encoding="utf-8")), 1)
        if any(term in line for term in GROWTH_TERMS)
    ]


def cooldown_reimplementations(root: Path = ROOT) -> list[str]:
    """The DPS matrix taking the cooldown helper rather than writing it again."""
    source = (root / COOLDOWN_BORROWER).read_text(encoding="utf-8")
    imported = next(
        (line for line in source.splitlines() if line.startswith("from .stats import")),
        "",
    )
    findings = []
    if "effective_cooldown" not in imported:
        findings.append(f"{COOLDOWN_BORROWER} does not import effective_cooldown")
    findings.extend(
        f"{COOLDOWN_BORROWER} reimplements cooldown math at line {lineno}"
        for lineno, line in enumerate(_code_lines(source), 1)
        if COOLDOWN_TERM in line
    )
    return findings


def check() -> list[str]:
    """Every finding across the four rules."""
    return [
        *bare_calculator_imports(),
        *sys_path_inserts(),
        *growth_formula_sites(),
        *cooldown_reimplementations(),
    ]


if __name__ == "__main__":
    raise SystemExit(report(check(), "OK: one namespace, one owner per formula"))
