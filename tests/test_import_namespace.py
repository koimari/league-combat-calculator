"""Issue #164 — one calculator package namespace + canonical math owners.

A Flask entry point that inserts ``src/`` on ``sys.path`` and imports
``calculator.*`` while tests and scripts import ``src.calculator.*`` loads
two distinct module trees in one process.  These tests pin the
single-namespace contract and guard against re-importing duplicate growth,
cooldown, and resistance formulas outside their canonical owners.
"""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import import_namespace

ROOT = Path(__file__).resolve().parent.parent

#: A guard against a wedged child, not a budget: importing the app costs 0.85 s
#: on an idle box and 5-15 s while ``pytest -n auto`` has all sixteen cores
#: busy, so a cap sized for the idle number fails under the suite that runs it
#: (issue #263).
HANG_GUARD_SECONDS = 120


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
        timeout=HANG_GUARD_SECONDS,
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
        timeout=HANG_GUARD_SECONDS,
    )
    assert result.returncode == 0, result.stderr
    assert "direct-entry ok" in result.stdout


# ---------------------------------------------------------------------------
# Canonical formula owners
# ---------------------------------------------------------------------------


def test_growth_multiplier_enforces_level_bound():
    from src.calculator import stat_formulas

    assert stat_formulas.growth_multiplier(1) == pytest.approx(0.7025)
    assert stat_formulas.growth_multiplier(18) == pytest.approx(0.7025 + 0.0175 * 17)
    for bad in (0, -1, 21):
        with pytest.raises(ValueError):
            stat_formulas.growth_multiplier(bad)


def test_the_tree_scans_find_nothing() -> None:
    """The four source rules `scripts/import_namespace.py` owns.

    The scans live beside the other tree lints so that a concurrent edit to
    `src/` cannot produce a phantom failure set here in the middle of a run.
    """
    assert import_namespace.bare_calculator_imports() == []
    assert import_namespace.sys_path_inserts() == []
    assert import_namespace.growth_formula_sites() == []
    assert import_namespace.cooldown_reimplementations() == []


def test_a_planted_bare_import_is_still_found(tmp_path) -> None:
    """The gate is driven by a real scan, not by an empty one."""
    (tmp_path / "planted.py").write_text(
        "from calculator import stats" + chr(10), encoding="utf-8"
    )
    (found,) = import_namespace.bare_calculator_imports(tmp_path)
    assert found.endswith("planted.py:1: from calculator import stats")
