"""The documented direct Flask entry point must remain importable."""

from pathlib import Path
import subprocess
import sys


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
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
