#!/usr/bin/env python3
"""The browser renders the engine's numbers and never recomputes them.

A second copy of a damage formula in ``static/js/`` drifts from the one in
``src/calculator/`` in silence, because nothing compares the two.  This names
the spellings that would mean a page had started computing: the stat-growth
coefficients, the resistance curve, and a crit chance divided into a share.
``tests/test_browser_formula_lint.py`` holds it at zero.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = (ROOT / "static" / "js" / "app.js",)
#: One spelling per engine formula, with the module that owns it.
FORMULAS = {
    r"0\.7025|0\.0175": "the stat growth curve (calculator.stats)",
    r"100\s*/\s*\(\s*100\s*\+": "the resistance curve (calculator.damage)",
    r"crit(?:Chance)?\s*/\s*100": "a crit share (fight.autos)",
}


def findings(paths: tuple[Path, ...] = SCRIPTS) -> list[tuple[Path, int, str]]:
    """Every (file, line number, formula) a shipped script spells."""
    return [
        (path, number, owner)
        for path in paths
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        for pattern, owner in FORMULAS.items()
        if re.search(pattern, line)
    ]


def main() -> int:
    """Print one line per finding; exit 1 on any."""
    found = findings()
    for path, number, owner in found:
        print(f"{path.relative_to(ROOT).as_posix()}:{number}: recomputes {owner}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
