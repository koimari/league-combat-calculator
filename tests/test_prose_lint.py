"""The prose counters: what src/, scripts/ and tests/ may say about themselves."""

import pytest

from scripts.prose_lint import (
    ASSUMPTION_CAP,
    FAILING,
    MODULE_DOCSTRING_CAP,
    REPO_PATH,
    REPORTING,
    scan,
)

#: Files exempt from the counters. Empty, and a new exemption needs a reason.
PENDING: tuple[str, ...] = ()

#: A reporting rule's ceiling and the fix it asks for.  Lower a ceiling to what
#: a run prints; never raise it.  At zero the rule joins ``FAILING`` and its
#: row goes away.
CEILINGS = {
    "unsourced_constant": (69, "cite the cached field, the source or the composition"),
}

#: One assumption at the cap and one a character past it, so the champion-tree
#: counter fires once on the same seed as the other four.
AT_CAP = "a" * ASSUMPTION_CAP
PAST_CAP = "b" * (ASSUMPTION_CAP + 1)
ASSUMPTIONS_BLOCK = f'\nASSUMPTIONS = [\n    "{AT_CAP}",\n    "{PAST_CAP}",\n]\n'

#: Every door a module publishes assumption text through, each holding one
#: string past the cap: a binding, ``extend``, ``+=``, a rebinding that carries
#: an element no literal answers for, and a call's assumption keyword beside an
#: argument that is not assumption text.
ASSUMPTION_SHAPES = f'''"""Seed."""

_TAIL = "{PAST_CAP}"

ASSUMPTIONS = ["{AT_CAP}", "{PAST_CAP}"]
ASSUMPTIONS.extend(["{PAST_CAP}"])
ASSUMPTIONS += ["{PAST_CAP}"]
ASSUMPTIONS = [*list(ASSUMPTIONS), "one fact, " + _TAIL]
parse_abilities, SLOTS, ASSUMPTIONS, SOURCES = build_packet_module(
    "Seed",
    assumption_overrides=("{PAST_CAP}",),
    cc_kinds={{"{PAST_CAP}": "slow"}},
)
'''

#: One module header a line past the cap, so the champion-tree counter fires on
#: the same seed as the other four.
OVER_THE_CAP = '"""Seed.\n' + "Over the cap.\n" * (MODULE_DOCSTRING_CAP - 1) + '"""'

SEEDED = OVER_THE_CAP + '''


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


def _pointer():
    """What Phase 4 ruled about this rank."""
    return 5


# ---------------------------------------------------------------------------
# A section with nothing under it
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# The section that kept its code
# ---------------------------------------------------------------------------


def _kept():
    return 4
''' + ASSUMPTIONS_BLOCK


CONSTANTS = '''"""Seed."""

# Sourced: data/champions.json Seed Q castTime.
_NOTED = 0.25
_IN_THE_SAME_BLOCK = 0.5

_BARE = 1.0
_TRAILING = 2.0  # 1.5 cast + 0.5 recovery
'''


#: One pointer beside the path that holds it, one beside nothing, one beside
#: a path that resolves and answers for something else, and one beside
#: evidence, which answers for a tense and not for a citation.
POINTERS = '''"""Seed."""

# The stages are recorded in docs/campaign-stages.json.
# Phase 4 ruled it.
# Phase 4 ruled it, and docs/stages.json records something else.
# The wiki row Phase 4 priced.
# The wiki row used to be priced here.
_KEPT = 1
'''


#: The three citations that are not a work id: a closed issue, a pull
#: request, a commit.  Every open issue is closed, so none of them resolves.
CITATIONS = '''"""Seed."""

# Fixed by issue #12.
# The shape PR #7 landed.
# b03bbad9 rewrote the set.
_KEPT = 1
'''


#: The three doors beside a docstring that publish prose: the note under a
#: constant, a command's help text, and an assumption string.
BESIDE_THE_DOCSTRING = '''"""Seed."""

RANK = 1
"""What Phase 2 ruled about this rank."""

ASSUMPTIONS = ["Phase 3 priced this slot"]

parser = argparse.ArgumentParser(description="the Phase 4 frontier")
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
    champions = tmp_path / "src" / "calculator" / "champions"
    champions.mkdir(parents=True)
    (tmp_path / "scripts").mkdir()
    (champions / "seed.py").write_text(SEEDED, encoding="utf-8")
    assert len(scan(root=tmp_path)[kind]) == 1


def test_a_champion_header_at_the_cap_passes_and_a_header_outside_never_counts(
    tmp_path,
):
    """The cap is the boundary, and it is the champion tree's alone."""
    champions = tmp_path / "src" / "calculator" / "champions"
    champions.mkdir(parents=True)
    (tmp_path / "scripts").mkdir()
    at_cap = '"""Seed.\n' + "At the cap.\n" * (MODULE_DOCSTRING_CAP - 2) + '"""\n'
    (champions / "seed.py").write_text(at_cap, encoding="utf-8")
    (tmp_path / "src" / "outside.py").write_text(SEEDED, encoding="utf-8")
    assert scan(root=tmp_path)["long_module_docstring"] == []


def test_only_the_assumption_past_the_cap_is_reported(tmp_path):
    """The cap is the boundary, and it is the champion tree's alone."""
    champions = tmp_path / "src" / "calculator" / "champions"
    champions.mkdir(parents=True)
    (tmp_path / "scripts").mkdir()
    (champions / "seed.py").write_text(SEEDED, encoding="utf-8")
    (tmp_path / "src" / "outside.py").write_text(SEEDED, encoding="utf-8")
    hits = scan(root=tmp_path)["long_assumption"]
    assert len(hits) == 1, hits
    assert hits[0].startswith("src/calculator/champions/seed.py:")
    assert hits[0].endswith(f"{ASSUMPTION_CAP + 1} characters over {ASSUMPTION_CAP}")


def test_every_door_assumption_text_arrives_through_is_read(tmp_path):
    """A binding, ``extend``, ``+=``, a concatenation and a call keyword."""
    champions = tmp_path / "src" / "calculator" / "champions"
    champions.mkdir(parents=True)
    (tmp_path / "scripts").mkdir()
    (champions / "seed.py").write_text(ASSUMPTION_SHAPES, encoding="utf-8")
    hits = scan(root=tmp_path)["long_assumption"]
    past = f"{ASSUMPTION_CAP + 1} characters over {ASSUMPTION_CAP}"
    assert [hit.rsplit(": ", 1)[1] for hit in hits] == [
        past,
        past,
        past,
        "'one fact, ' + _TAIL",
        past,
    ], hits


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


def test_a_pointer_beside_a_path_that_resolves_is_not_reported(tmp_path):
    """The one exemption: the path resolves and it holds the citation."""
    (tmp_path / "src").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "src" / "seed.py").write_text(POINTERS, encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "campaign-stages.json").write_text("{}", encoding="utf-8")
    (tmp_path / "docs" / "stages.json").write_text("{}", encoding="utf-8")
    found = scan(root=tmp_path)
    hits = found["pointer"]
    assert [hit.split(":")[1] for hit in hits] == ["4", "5", "6"], hits
    assert found["history"] == []


def test_a_path_ending_a_sentence_leaves_the_full_stop_out():
    """Windows resolves ``stages.json.`` as ``stages.json``; POSIX does not."""
    assert REPO_PATH.findall("recorded in docs/stages.json.") == ["docs/stages.json"]


def test_prose_beside_a_docstring_answers_to_the_pointer_rule(tmp_path):
    """A constant's note, a command's help text and an assumption string."""
    (tmp_path / "src").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "src" / "seed.py").write_text(BESIDE_THE_DOCSTRING, encoding="utf-8")
    hits = scan(root=tmp_path)["pointer"]
    assert [hit.split(":")[1] for hit in hits] == ["4", "6", "8"], hits


def test_a_test_file_answers_to_the_pointer_rule_and_to_nothing_else(tmp_path):
    """``tests/`` carries this rule, and never the other six."""
    (tmp_path / "src").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_seed.py").write_text(SEEDED, encoding="utf-8")
    found = scan(root=tmp_path)
    assert len(found["pointer"]) == 1
    assert all(found[kind] == [] for kind in FAILING if kind != "pointer")


@pytest.mark.parametrize("scope", ["src", "scripts", "tests"])
def test_an_issue_a_pull_request_and_a_commit_are_pointers_in_every_scope(
    tmp_path, scope
):
    """A citation answers to the rule that reaches ``tests/``, not to a tense."""
    for name in ("src", "scripts", "tests"):
        (tmp_path / name).mkdir()
    (tmp_path / scope / "seed.py").write_text(CITATIONS, encoding="utf-8")
    found = scan(root=tmp_path)
    assert [hit.split(":")[1] for hit in found["pointer"]] == ["3", "4", "5"]
    assert found["history"] == []
