"""The shipped page holds no engine formula, and the lint can say so."""

from pathlib import Path

import pytest

from scripts import browser_formula_lint as lint


def test_the_shipped_page_recomputes_nothing() -> None:
    assert lint.findings() == []


@pytest.mark.parametrize(
    "line",
    [
        "const growth = base + g * (level - 1) * (0.7025 + 0.0175 * (level - 1));",
        "const taken = raw * 100 / (100 + armor);",
        "const share = crit / 100;",
    ],
)
def test_a_planted_formula_is_reported(tmp_path: Path, line: str) -> None:
    planted = tmp_path / "app.js"
    planted.write_text(f"render();\n{line}\n", encoding="utf-8")
    (found,) = lint.findings((planted,))
    assert found[1] == 2
