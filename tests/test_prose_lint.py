"""D7's counters: docstrings and comments in src/ and scripts/ hold current state."""

import pytest

from scripts.prose_lint import FAILING, REPORTING, scan

#: Files exempt from the counters. Empty, and a new exemption needs a reason.
PENDING: tuple[str, ...] = ()

#: A reporting rule's ceiling and the fix it asks for.  Lower a ceiling to what
#: a run prints; never raise it.  At zero the rule joins ``FAILING`` and its
#: row goes away.
CEILINGS = {
    "pointer": (583, "state the fact instead of citing a campaign document"),
    "unsourced_constant": (69, "cite the cached field, the source or the composition"),
}

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


# ---------------------------------------------------------------------------
# A section with nothing under it
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# The section that kept its code
# ---------------------------------------------------------------------------


def _kept():
    return 4
'''


CONSTANTS = '''"""Seed."""

# Sourced: data/champions.json Seed Q castTime.
_NOTED = 0.25
_IN_THE_SAME_BLOCK = 0.5

_BARE = 1.0
_TRAILING = 2.0  # 1.5 cast + 0.5 recovery
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
    assert hits == [], "\n".join([f"{len(hits)} {kind}:", *hits])


def test_every_reporting_rule_carries_a_ceiling():
    """A rule added without one would report into nothing."""
    assert set(CEILINGS) == set(REPORTING)


@pytest.mark.parametrize("kind", sorted(CEILINGS))
def test_the_reported_count_only_falls(findings, kind):
    hits = findings[kind]
    ceiling, fix = CEILINGS[kind]
    assert (
        len(hits) <= ceiling
    ), f"{len(hits)} {kind} findings against a ceiling of {ceiling}; {fix}"


@pytest.mark.parametrize("kind", FAILING)
def test_the_counter_fires_on_a_seeded_offender(tmp_path, kind):
    (tmp_path / "src").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "src" / "seed.py").write_text(SEEDED, encoding="utf-8")
    assert len(scan(root=tmp_path)[kind]) == 1


def test_a_number_answers_to_the_note_beside_it_or_over_its_block(tmp_path):
    """A note heads the run it documents, and a trailing note covers its line."""
    champions = tmp_path / "src" / "calculator" / "champions"
    champions.mkdir(parents=True)
    (tmp_path / "scripts").mkdir()
    (champions / "seed.py").write_text(CONSTANTS, encoding="utf-8")
    (tmp_path / "src" / "outside.py").write_text(CONSTANTS, encoding="utf-8")
    assert scan(root=tmp_path)["unsourced_constant"] == [
        "src/calculator/champions/seed.py:7: _BARE = 1.0"
    ]


def test_a_preamble_answers_to_the_definition_it_introduces(tmp_path):
    """Touching the ``def`` bounds a run; a blank line heads a section."""
    (tmp_path / "src").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "src" / "seed.py").write_text(PREAMBLES, encoding="utf-8")
    assert scan(root=tmp_path)["long_comment"] == ["src/seed.py:4: 4 lines"]
