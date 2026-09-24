"""The property sweep's gate, held to a sample and to its acknowledgements.

``scripts/property_sweep.py`` sweeps every champion in CI; this sample keeps
the kits whose shreds once broke a property inside ``pytest``, and every
acknowledged violation must still reproduce, so a fixed one leaves the table.
"""

import pytest

from scripts import property_sweep as sweep

#: The shred kits that broke ``duration_monotone``, and two that read it.
SAMPLE = ("Sion", "Vi", "Karthus", "Garen", "Kog'Maw")


@pytest.mark.parametrize("champion", SAMPLE)
def test_the_sample_obeys_every_property(champion: str) -> None:
    unexplained = [
        violation
        for violation in sweep.sweep_champion(champion)
        if violation.key not in sweep.ACKNOWLEDGED
    ]
    assert unexplained == []


def test_every_acknowledgement_names_its_reason_and_still_reproduces() -> None:
    for (prop, champion, scenario), reason in sweep.ACKNOWLEDGED.items():
        assert reason.strip(), (prop, champion, scenario)
        found = {violation.key for violation in sweep.sweep_champion(champion)}
        assert (prop, champion, scenario) in found, "acknowledged but fixed"


def test_random_builds_are_legal_and_seeded() -> None:
    first = sweep.random_builds("Jinx", 3)
    assert first == sweep.random_builds("Jinx", 3)
    for boots, items in first:
        assert boots and len(items) == sweep.LEGENDARIES_PER_BUILD
