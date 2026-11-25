"""An ``hp_scaled_damage`` lambda takes the missing-health ratio and nothing else
positional.

The walk calls ``raw_formula(missing_ratio, target_max_health)`` first and falls
back to one argument only on ``TypeError``. A lambda that captures a value as a
defaulted positional parameter (``lambda missing, base=base: ...``) therefore
receives the target's maximum health in place of the captured value: Seraphine's
High Note and Kayn's Umbral health part were priced that way. Captured values
must be keyword-only (``lambda missing, *, base=base: ...``).
"""

import ast
from pathlib import Path

from src.calculator.survival.transitions import evaluate_live_raw_formula

SRC = Path(__file__).resolve().parents[1] / "src"


def _hp_scaled_lambdas():
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "hp_scaled_damage":
                if isinstance(node.value, ast.Lambda):
                    yield path, node.value


def test_no_hp_scaled_lambda_takes_a_second_positional():
    offenders = [
        f"{path.relative_to(SRC.parent)}:{lam.lineno}"
        for path, lam in _hp_scaled_lambdas()
        if len(lam.args.posonlyargs) + len(lam.args.args) > 1
    ]
    assert offenders == []


def test_the_scan_sees_the_roster_lambdas():
    assert sum(1 for _ in _hp_scaled_lambdas()) >= 8


def test_a_keyword_only_capture_survives_the_live_call():
    base = 80.0
    formula = lambda missing, *, base=base: base * missing  # noqa: E731
    assert evaluate_live_raw_formula(formula, 0.5, 2500.0) == 40.0
