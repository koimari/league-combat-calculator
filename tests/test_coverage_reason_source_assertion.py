"""The published all-defence coverage reason, checked on the payload it rides.

An item whose declared families are all defence families publishes

    "<subject> is a defence: the represented mechanic changes
     durability, not outgoing TDD."

on its attacker-lane coverage reason, where ``<subject>`` names the mechanics
the item declares ("Plating", "Unmake") and falls back to the universal
"Every declared family on this item" when the rule set names none.

The check below is the sentence read off ``item_model_coverage`` for every
cached item, in both directions: the sentence is published exactly where
``declares_only_defence`` holds and no more specific receipt outranks it.
``gated_state_reason`` is the one thing that does, for an item whose defence
is armed by a bounded scenario input.

Both directions matter.  Forwards alone would let the sentence quietly stop
being the answer; backwards alone would let it be published somewhere new.
"""

from __future__ import annotations

import pytest

from src.calculator import item_coverage
from src.calculator.data_fetcher import fetch_item_data
from src.calculator.item_coverage import (
    ATTACKER_LANES,
    declares_only_defence,
    gated_state_reason,
    item_model_coverage,
)

#: The published sentence, pinned here rather than imported: importing it from
#: the module under test would make the binding true by construction.
CENSUS_CLAIM = (
    " is a defence: the represented mechanic changes durability, " "not outgoing TDD."
)


def _cached_item_names() -> tuple[str, ...]:
    """Every cached item name, in one order, for the parametrize axis."""
    return tuple(
        sorted(
            str(record["name"])
            for record in fetch_item_data().values()
            if isinstance(record, dict) and record.get("name")
        )
    )


@pytest.fixture(name="published", scope="module")
def _published() -> dict[str, str]:
    """Every cached item's attacker-lane coverage reason, by item name."""
    return {
        name: item_model_coverage(name, ATTACKER_LANES).reason
        for name in _cached_item_names()
    }


@pytest.mark.parametrize("name", _cached_item_names())
def test_the_sentence_rides_exactly_the_declarations_that_make_it(
    name: str, published: dict[str, str]
) -> None:
    """Published if and only if every declared family is a defence family."""
    claimed = published[name].endswith(CENSUS_CLAIM)
    assert claimed is (
        declares_only_defence(name) and gated_state_reason(name) is None
    ), name
    if claimed:
        families = item_coverage._declared_families(name)
        assert families, name
        assert families <= item_coverage._DEFENCE_FAMILIES, name


def test_the_population_the_sentence_quantifies_over_is_not_empty(
    published: dict[str, str],
) -> None:
    """A universal over nothing is green by vacuity, which is not a check."""
    assert [name for name, reason in published.items() if reason.endswith(CENSUS_CLAIM)]
