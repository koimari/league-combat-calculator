"""A test that needs a local resource is deselected, never skipped green.

`scripts/resource_markers.py` finds every test whose body, or a helper or
fixture it reaches, guards on a locally built game file or on `node`.
`tests/conftest.py` deselects those nodes when the machine does not have the
resource and names the count in the terminal summary, because a skip
reports success for work that did not happen.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import resource_markers

from tests import conftest, resource_gate

#: The one resource git tracks, so every checkout and CI has it.
TRACKED_RESOURCE = "needs_game_files"


def test_every_guarded_test_carries_its_resource_marker() -> None:
    """A guard with no marker still skips green on a machine without it."""
    assert resource_markers.check() == []


def test_the_scanner_and_the_hook_name_the_same_resources() -> None:
    """One vocabulary: a marker the hook cannot answer deselects nothing."""
    assert set(resource_markers.RESOURCES) == set(resource_gate.RESOURCES)


def test_every_resource_states_what_it_is_and_how_to_ask_for_it() -> None:
    """A marker is a receipt, so each names its resource and its probe."""
    for marker, (description, present) in resource_gate.RESOURCES.items():
        assert description.strip(), marker
        assert isinstance(present(), bool), marker


def test_the_tracked_resource_answers_present_on_this_checkout() -> None:
    """A probe nothing can satisfy deselects its nodes on every machine.

    ``data/bin/characters/*.bin.json`` is git-tracked (``.gitignore`` names
    the exception), so a checkout always has it and the 64 nodes that read
    it always run.  A probe that also demanded a gitignored tree would be
    false everywhere, which is a hidden suite, not a reported one.
    """
    description, present = resource_gate.RESOURCES[TRACKED_RESOURCE]
    assert present() is True, description
    assert any((resource_gate.ROOT / "data/bin/characters").glob("*.bin.json"))


def test_no_skip_reason_can_name_two_resources() -> None:
    """Overlapping phrases would pick a marker by dict order, silently."""
    phrases = [
        (marker, phrase)
        for marker, group in resource_markers.RESOURCES.items()
        for phrase in group
    ]
    for marker, phrase in phrases:
        for other, candidate in phrases:
            assert other == marker or phrase not in candidate, (marker, other)


def test_a_worker_hands_its_counts_to_the_xdist_controller() -> None:
    """The controller never collects, so the wire is the only report there.

    Every worker collects the whole set and deselects the same nodes, so
    the controller takes the largest count rather than a sum.
    """
    node = SimpleNamespace(
        workeroutput={resource_gate.NOT_RUN_WIRE: {TRACKED_RESOURCE: 78}},
        config=SimpleNamespace(stash=pytest.Stash()),
    )
    conftest.pytest_testnodedown(node, None)
    conftest.pytest_testnodedown(node, None)
    assert node.config.stash[resource_gate.NOT_RUN] == {TRACKED_RESOURCE: 78}


def test_a_planted_guard_is_still_found(tmp_path) -> None:
    """The gate is driven by a real scan, not by an empty one.

    The planted module reaches the guard the long way, through a fixture
    and a helper, because that is the shape the scan exists to follow.
    """
    planted = tmp_path / "test_planted.py"
    planted.write_text(
        "import pytest"
        + chr(10) * 2
        + chr(10).join(
            (
                "def _evidence():",
                "    pytest.skip('local Ashe game-file evidence is unavailable')",
                "",
                "",
                "@pytest.fixture",
                "def corpus():",
                "    return _evidence()",
                "",
                "",
                "def test_reads_the_corpus(corpus):",
                "    assert corpus",
                "",
            )
        ),
        encoding="utf-8",
    )
    assert resource_markers.guarded_tests(planted) == {
        "test_reads_the_corpus": "needs_game_files"
    }
    assert len(resource_markers.check(tmp_path)) == 1


def test_a_skip_about_something_else_is_not_this_rule(tmp_path) -> None:
    """The reason vocabulary is closed, so an unrelated skip stays a skip."""
    planted = tmp_path / "test_other.py"
    planted.write_text(
        "import pytest"
        + chr(10) * 2
        + chr(10).join(
            (
                "def test_needs_a_clean_directory():",
                "    pytest.skip('tmp_path lives inside a git repository')",
                "",
            )
        ),
        encoding="utf-8",
    )
    assert resource_markers.guarded_tests(planted) == {}


@pytest.mark.parametrize("marker", sorted(resource_gate.RESOURCES))
def test_each_marker_is_registered(marker: str, pytestconfig) -> None:
    """An unregistered marker is a typo pytest answers with a warning."""
    registered = {
        line.split(":", 1)[0] for line in pytestconfig.getini("markers") if line
    }
    assert marker in registered
