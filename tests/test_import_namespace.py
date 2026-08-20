"""Issue #164 — one calculator package namespace + canonical math owners.

The Flask entry point used to insert ``src/`` on ``sys.path`` and import
``calculator.*`` while tests and scripts imported ``src.calculator.*``,
loading two distinct module trees in one process.  These tests pin the
single-namespace contract and guard against re-importing duplicate growth,
cooldown, and resistance formulas outside their canonical owners.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _src_text(relpath: str) -> str:
    return (ROOT / relpath).read_text(encoding="utf-8")


def _code_lines(text: str) -> list[str]:
    """Source lines with comments AND docstrings stripped (enough for the
    formula guards — prose may cite the formula, code may not)."""
    without_docstrings = re.sub(r'""".*?"""', "", text, flags=re.S)
    lines = []
    for raw in without_docstrings.splitlines():
        line = re.sub(r"\s*#.*$", "", raw).strip()
        if line:
            lines.append(line)
    return lines


# ---------------------------------------------------------------------------
# Single namespace (subprocess contract)
# ---------------------------------------------------------------------------


def test_flask_entry_imports_one_calculator_tree():
    """Importing the Flask app must not create a bare ``calculator`` package."""
    code = (
        "import sys\n"
        "import src.app\n"
        "bare = [m for m in sys.modules if m == 'calculator' or m.startswith('calculator.')]\n"
        "assert not bare, f'second calculator tree loaded: {bare}'\n"
        "import src.calculator.rotation_resolver as rr\n"
        "import src.calculator.pipeline as p\n"
        "assert rr is sys.modules['src.calculator.rotation_resolver']\n"
        "assert p is sys.modules['src.calculator.pipeline']\n"
        "print('single-namespace ok')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "single-namespace ok" in result.stdout


def test_direct_entrypoint_runs_without_second_namespace():
    """The documented direct entry point must also stay single-namespace."""
    code = (
        "import sys\n"
        "from flask import Flask\n"
        "Flask.run = lambda self, **kwargs: None\n"
        "import runpy\n"
        "runpy.run_path('src/app.py', run_name='__main__')\n"
        "bare = [m for m in sys.modules if m == 'calculator' or m.startswith('calculator.')]\n"
        "assert not bare, f'second calculator tree loaded: {bare}'\n"
        "print('direct-entry ok')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "direct-entry ok" in result.stdout


def test_no_bare_calculator_imports_in_source():
    """No ``calculator.*`` (non-``src``) import may appear anywhere."""
    offenders = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        if "__pycache__" in str(path):
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if re.match(r"\s*(?:from|import) calculator(?:\s|\.)", line):
                offenders.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()}")
    assert not offenders, "bare calculator imports:\n" + "\n".join(offenders)


def test_app_does_not_insert_src_dir_on_sys_path():
    """app.py must put the repo root (or nothing) on sys.path, never src/."""
    app = _src_text("src/app.py")
    for lineno, line in enumerate(app.splitlines(), 1):
        if "sys.path.insert" in line:
            assert (
                "resolve().parents[1]" in line
            ), f"src/app.py:{lineno} inserts a non-repo-root path: {line.strip()}"


# ---------------------------------------------------------------------------
# Canonical formula owners
# ---------------------------------------------------------------------------


def test_growth_formula_lives_only_in_stats():
    """The 0.7025/0.0175 growth term is owned by stats.growth_multiplier."""
    owners = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        if "__pycache__" in str(path) or path.name == "stats.py":
            continue
        for lineno, line in enumerate(_code_lines(path.read_text()), 1):
            if "0.7025" in line or "0.0175" in line:
                owners.append(f"{path.relative_to(ROOT)}:{lineno}: {line}")
    assert not owners, "duplicate growth formula:\n" + "\n".join(owners)
    stats_src = _src_text("src/calculator/stats.py")
    assert "def growth_multiplier" in stats_src


def test_growth_multiplier_enforces_level_bound():
    import src.calculator.stats as stats

    assert stats.growth_multiplier(1) == pytest.approx(0.7025)
    assert stats.growth_multiplier(18) == pytest.approx(0.7025 + 0.0175 * 17)
    for bad in (0, -1, 21):
        with pytest.raises(ValueError):
            stats.growth_multiplier(bad)


def test_cooldown_formula_lives_only_in_damage():
    """Ability-haste cooldown math is owned by damage.effective_cooldown."""
    rr = _src_text("src/calculator/rotation_resolver.py")
    import_line = next(
        line for line in rr.splitlines() if line.startswith("from .damage import")
    )
    assert "effective_cooldown" in import_line
    for lineno, line in enumerate(_code_lines(rr), 1):
        assert (
            "100.0 / (100.0" not in line
        ), f"rotation_resolver reimplements cooldown math at line {lineno}"

