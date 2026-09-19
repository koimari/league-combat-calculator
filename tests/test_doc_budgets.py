"""Word budgets for the three root docs, so a trap cannot grow back into CLAUDE.md.

Each budget is a ceiling with headroom for one entry, not a target. Passing one
means the entry belongs in another file: an invariant in ``architecture.md``, a
gotcha in ``TRAPS.md``, and neither in ``CLAUDE.md``, which holds the rules,
domain facts and gates a session reads every time.
"""

from pathlib import Path

import pytest

BUDGETS = {"CLAUDE.md": 1_600, "TRAPS.md": 5_000, "architecture.md": 7_400}

TRAP_SECTIONS = (
    "## Tests and CI",
    "## Goldens and receipts",
    "## Engine and pricing",
    "## Platform and tooling",
    "## Frontend and vision",
    "## Champions",
)


def _read(name: str) -> str:
    return Path(name).read_text(encoding="utf-8")


@pytest.mark.parametrize(("name", "budget"), BUDGETS.items())
def test_the_doc_is_inside_its_word_budget(name, budget):
    words = len(_read(name).split())
    assert words <= budget, (
        f"{name} holds {words} words against a budget of {budget}. "
        "Move the entry to the file that owns its kind rather than raising this."
    )


def test_traps_keeps_its_six_sections():
    traps = _read("TRAPS.md")
    for heading in TRAP_SECTIONS:
        assert heading in traps, heading


def test_claude_md_points_at_the_other_two_homes():
    claude = _read("CLAUDE.md")
    for home in ("architecture.md", "TRAPS.md", "benchmarks.md"):
        assert home in claude, home
    # Traps live in TRAPS.md, so the heading that collects them here is gone.
    assert "Known Quirks" not in claude
