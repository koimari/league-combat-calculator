"""D7's counters: docstrings and comments in src/ and scripts/ hold current state."""

import pytest

from scripts.prose_lint import FAILING, scan

#: Files exempt from the counters. Empty, and a new exemption needs a reason.
PENDING: tuple[str, ...] = ()

SEEDED = '''"""Seed."""


def public():
    """One.

    Two.
    """
    return 1


def _held():
    # one
    # two
    # three
    return 2


def _history():
    """The rank used to be re-derived here."""
    return 3
'''


PREAMBLES = '''"""Seed."""


# one
# two
# three
# four
def _introduced():
    """Doc."""
    return 1


# five
# six
# seven
# eight

def _headed():
    """Doc."""
    return 2
'''


@pytest.fixture(name="findings", scope="module")
def _findings():
    return scan(exclude=PENDING)


@pytest.mark.parametrize("kind", FAILING)
def test_the_tree_carries_no_prose_of_this_kind(findings, kind):
    hits = findings[kind]
    assert hits == [], "\n".join([f"{len(hits)} {kind}:"] + hits)


@pytest.mark.parametrize("kind", FAILING)
def test_the_counter_fires_on_a_seeded_offender(tmp_path, kind):
    (tmp_path / "src").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "src" / "seed.py").write_text(SEEDED, encoding="utf-8")
    assert len(scan(root=tmp_path)[kind]) == 1


def test_a_preamble_answers_to_the_definition_it_introduces(tmp_path):
    """Touching the ``def`` bounds a run; a blank line heads a section."""
    (tmp_path / "src").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "src" / "seed.py").write_text(PREAMBLES, encoding="utf-8")
    assert scan(root=tmp_path)["long_comment"] == ["src/seed.py:4: 4 lines"]
