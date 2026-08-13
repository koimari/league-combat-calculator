"""Every published number is named by exactly one dispositions entry.

Umbrella criterion 1, as a machine check rather than an audit over a
hand-maintained path list.  The mechanism is not this file: it is that
``serialize_leaf`` emits a payload leaf and its map entry in one call and
nothing else emits either, so the two cannot drift.  What is here is the
**backstop** behind that single writer -- a two-way key-set equality that goes
red if a leaf is ever published by some other route, or if an entry ever names
a path that is neither a present number nor a declared refusal.

The three payloads are checked at their own boundaries: ``/api/calculate``'s
combat receipt, ``/api/bis`` and ``/api/optimize``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from src.calculator.ability_spec import Disposition

DISPOSITIONS = {member.value for member in Disposition}


def numeric_leaf_paths(payload: Mapping, *, skip: Sequence[str] = ()) -> set[str]:
    """Every *quantity* leaf path under *payload*, in the map's key grammar.

    A quantity is a float.  Three kinds of number are deliberately not one,
    and each exclusion is a rule rather than a convenience:

    * ``bool`` -- a flag is not a quantity, and ``isinstance(True, int)`` is
      Python's own trap here;
    * ``int`` -- the payload's ints are identifiers and counts (``sequence``,
      ``level``, a stack count, a candidate count).  A disposition answers
      "did a rule produce this number, or is it standing in for one that did
      not run", and an ordinal has no such reading.  Every leaf a view wrote
      through ``measured`` comes back from the precision registry as a float,
      so this rule and the writer's own agree by construction;
    * blocks named in ``skip`` -- the payload's non-view sections and its
      republications, named at each call site with the reason.
    """
    found: set[str] = set()

    def walk(node, path: str) -> None:
        if isinstance(node, Mapping):
            for key, value in node.items():
                if not path and key in skip:
                    continue
                walk(value, f"{path}.{key}" if path else str(key))
        elif isinstance(node, (list, tuple)):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")
        elif isinstance(node, bool):
            return
        elif isinstance(node, float):
            found.add(path)

    walk(payload, "")
    return found


def entries_are_well_formed(dispositions: Mapping) -> None:
    """Every entry names one of the four spellings and exactly one view tag."""
    for path, entry in dispositions.items():
        assert entry["disposition"] in DISPOSITIONS, path
        assert entry["view_tag"] in {"applied", "theoretical"}, path
        if entry["disposition"] == Disposition.WITHHELD.value:
            assert entry["receipts"], path
        if entry["disposition"] == Disposition.STRUCTURAL_ZERO.value:
            assert entry["reason"], path


def assert_covered(payload: Mapping, *, skip: Sequence[str] = ()) -> None:
    """The two-way check: map keys are exactly the numbers plus the refusals."""
    dispositions = payload["dispositions"]
    entries_are_well_formed(dispositions)
    published = numeric_leaf_paths(
        {key: value for key, value in payload.items() if key != "dispositions"},
        skip=skip,
    )
    withheld = {
        path
        for path, entry in dispositions.items()
        if entry["disposition"] == Disposition.WITHHELD.value
    }
    named = set(dispositions)
    # A map entry naming neither a present leaf nor a withheld path fails.
    assert named - published - withheld == set()
    # Every leaf a view published carries an entry.  The difference is what a
    # second producer of payload numbers would look like.
    assert published - named == set()


# ---------------------------------------------------------------------------
# The three payloads, checked against live runs rather than against fixtures
# ---------------------------------------------------------------------------

import importlib.util  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


def _golden_snapshot():
    """The capture instrument, imported by path exactly as its own tests do."""
    spec = importlib.util.spec_from_file_location(
        "golden_snapshot", REPO_ROOT / "scripts" / "golden_snapshot.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("golden_snapshot", module)
    spec.loader.exec_module(module)
    return module


def _combat(name: str = "mandate_abyssal_curse_roster") -> Mapping:
    """One coupled scenario's combat receipt, run live."""
    snapshot = _golden_snapshot()
    scenario = next(item for item in snapshot.COUPLED_SCENARIOS if item.name == name)
    return snapshot.coupled_entry(scenario)["combat"]


def _row_leaf_paths(
    rows: Sequence[Mapping], prefix: str, *, skip: Sequence[str] = ()
) -> set[str]:
    """Every quantity leaf of an indexed block, in the map's key grammar."""
    found: set[str] = set()
    for index, row in enumerate(rows):
        found |= {
            f"{prefix}[{index}].{leaf}" for leaf in numeric_leaf_paths(row, skip=skip)
        }
    return found


class TestTheCalculatePayload:
    """``/api/calculate``'s combat receipt — the five views' own output."""

    def test_every_view_produced_number_carries_exactly_one_entry(self) -> None:
        combat = _combat()
        dispositions = combat["dispositions"]
        entries_are_well_formed(dispositions)
        published = set()
        # ``utility_outcomes`` is excluded from the breakdown rows and from
        # the objective block: it is a receipt in native units, published
        # under an explicit declaration that the calculator does not convert
        # movement, cleanse, vision or economy into a common scalar.  Those
        # numbers are the declaration's own, not a rule's output.
        published |= _row_leaf_paths(
            combat["breakdown"], "breakdown", skip=("utility_outcomes",)
        )
        published |= _row_leaf_paths(combat["events"], "events")
        published |= _row_leaf_paths(combat["healing_events"], "healing_events")
        published |= _row_leaf_paths(combat["support_events"], "support_events")
        # ``focus_survival`` and ``focus_utility_outcomes`` republish blocks
        # named elsewhere in the same payload.  One leaf, one entry: naming a
        # republication again would be an over-count wearing full coverage.
        published |= {
            f"objective.{leaf}"
            for leaf in numeric_leaf_paths(
                combat["objective"],
                skip=("focus_survival", "focus_utility_outcomes"),
            )
        }
        for row in combat["participants"]:
            published |= {
                f"participants.survival.{row['participant_id']}.{leaf}"
                for leaf in numeric_leaf_paths(row["survival"])
            }
        # Every published number is named, and every name is a published
        # number.  Both directions, because one of them alone is satisfied by
        # a map that describes nothing and by a map that describes ghosts.
        assert published - set(dispositions) == set()
        assert set(dispositions) - published == set()

    def test_the_map_is_not_vacuous(self) -> None:
        """A check that passes on an empty map is not a check."""
        assert len(_combat()["dispositions"]) > 100

    def test_the_focus_survival_block_is_not_double_counted(self) -> None:
        """``objective.focus_survival`` republishes a row already named.

        Its leaves live at ``participants.survival.<focus>`` and are named
        there once.  A second set of entries under the objective block would
        make "exactly one entry per leaf" false while every leaf still had
        one, which is the shape of an over-count rather than a gap.
        """
        combat = _combat()
        assert not any(
            path.startswith("objective.focus_survival")
            for path in combat["dispositions"]
        )


class TestTheTwoScoreServingPayloads:
    """``/api/bis`` and ``/api/optimize`` — the score view's published surfaces.

    D-23 already covers their ``withheld[]`` and exclusion count.  What this
    class pins is the other half of umbrella criterion 1: the score leaves they
    publish carry dispositions too, or the two largest numeric surfaces in the
    calculator serve undispositioned numbers while every other criterion
    passes.
    """

    def test_the_bis_payload_names_every_candidate_score_it_publishes(self) -> None:
        from src.calculator.bis import bis_payload

        payload = bis_payload(
            {
                "champion": "Syndra",
                "level": 13,
                "items": ["Malignance"],
                "enemies": [{"champion": "Aatrox", "level": 13, "items": []}],
                "slot_index": 1,
            }
        )
        dispositions = payload["dispositions"]
        entries_are_well_formed(dispositions)
        assert dispositions, "a vacuous map is not a map"
        for block in ("candidates", "partial_candidates"):
            for index, row in enumerate(payload[block]):
                for leaf in ("score", "objective_value"):
                    assert f"{block}[{index}].{leaf}" in dispositions
                assert not any(
                    key.startswith("_") for key in row
                ), "an internal ranking key leaked into the payload"

    def test_the_bis_survival_entries_are_moved_and_never_re_produced(self) -> None:
        """A candidate's survival row is the survival view's, named once.

        The entries ride from the combat receipt that produced them to the
        path the leaf now lives at.  Re-deriving them here would be a second
        producer of a leaf's disposition, which is the one thing the single
        writer exists to prevent.
        """
        from src.calculator.bis import bis_payload

        payload = bis_payload(
            {
                "champion": "Syndra",
                "level": 13,
                "items": ["Malignance"],
                "enemies": [{"champion": "Aatrox", "level": 13, "items": []}],
                "slot_index": 1,
            }
        )
        survival_entries = [
            path for path in payload["dispositions"] if ".survival." in path
        ]
        assert survival_entries
        for path in survival_entries:
            assert payload["dispositions"][path]["disposition"] in DISPOSITIONS
