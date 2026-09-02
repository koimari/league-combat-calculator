"""The documented direct Flask entry point must remain importable."""

import subprocess
import sys
from pathlib import Path

#: A guard against a wedged child, not a budget: the import costs 0.85 s on an
#: idle box and 5-15 s while ``pytest -n auto`` has all sixteen cores busy, so a
#: cap sized for the idle number fails under the suite that runs it (issue #263).
HANG_GUARD_SECONDS = 120


def test_app_script_reaches_flask_run_without_import_errors():
    code = """
from flask import Flask
Flask.run = lambda self, **kwargs: None
import runpy
runpy.run_path('src/app.py', run_name='__main__')
"""

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
        check=False,
        timeout=HANG_GUARD_SECONDS,
    )

    assert result.returncode == 0, result.stderr
