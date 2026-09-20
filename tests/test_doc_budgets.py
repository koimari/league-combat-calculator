"""Word budgets for the three root docs, so a trap cannot grow back into CLAUDE.md.

Each budget is a ceiling with headroom for one entry, not a target. Passing one
means the entry belongs in another file: an invariant in ``architecture.md``, a
gotcha in ``TRAPS.md``, and neither in ``CLAUDE.md``, which holds the rules,
domain facts and gates a session reads every time.
"""

import re
from pathlib import Path

import pytest

#: ``TRAPS.md`` accretes: a wave's worth of new findings must fit without the
#: budget forcing a trap out, so its ceiling is today's file plus one measured
#: wave. Wave B's findings are 767 words compressed to the house form, against
#: the 633 the previous ceiling left, which is what that number is measured
#: from. The other two hold a fixed subject and their ceilings do not move.
BUDGETS = {"CLAUDE.md": 1_600, "TRAPS.md": 6_900, "architecture.md": 7_400}

#: Where a citation of a root doc must resolve, each root named so no walk can
#: reach ``.claude/worktrees``. ``docs/`` is left out while the docs unit
#: retires files there.
CITING = (
    ("src", "*.py"),
    ("tests", "*.py"),
    ("scripts", "*.py"),
    (".claude/skills", "*.md"),
)

#: The two shapes the tree writes a section citation in. What each captures is
#: read as text that must *begin* with a heading, so a section name holding a
#: capital past its first word needs no second spelling here.
BEFORE = re.compile(r"\bthe ([A-Z][A-Za-z ]{0,40}?) section of `{0,2}(\w+\.md)`{0,2}")
AFTER = re.compile(r"`{0,2}(\w+\.md)`{0,2}, ([A-Z][^.;)]{0,40})")

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


def _headings(name: str) -> set[str]:
    return {
        line.lstrip("#").strip()
        for line in _read(name).splitlines()
        if line.startswith("#")
    }


def _resolves(cited: str, headings: set[str]) -> bool:
    """Whether cited text names a section, which it does by starting with one."""
    return any(cited.startswith(heading) for heading in headings)


def _cited_sections(text: str) -> list[tuple[str, str]]:
    """Every ``(document, cited text)`` pair the text names, citations unwrapped."""
    flat = " ".join(text.split())
    return [(doc, cited) for cited, doc in BEFORE.findall(flat)] + AFTER.findall(flat)


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


def test_the_citation_check_reads_both_shapes():
    """The shape a moved entry leaves behind is the one it has to catch."""
    traps = _headings("TRAPS.md")
    wrapped = "see the Goldens and receipts\nsection of ``TRAPS.md``"
    assert _resolves(_cited_sections(wrapped)[0][1], traps)
    assert not _resolves(_cited_sections("(TRAPS.md, Known Quirks)")[0][1], traps)


def test_every_cited_section_of_a_root_doc_exists():
    """A citation resolves, so moving an entry between the three is not silent."""
    headings = {name: _headings(name) for name in BUDGETS}
    files = [Path(name) for name in BUDGETS] + [
        path
        for root, glob in CITING
        for path in Path(root).rglob(glob)
        if path.name != Path(__file__).name  # holds the seeded citations above
    ]
    for path in files:
        for doc, cited in _cited_sections(path.read_text(encoding="utf-8")):
            if doc in headings:
                assert _resolves(cited, headings[doc]), f"{path}: {doc}, {cited!r}"
