"""Phase 4 S4 — a cache key is a value, and every cache says what stales it.

``program/caches`` is the front door for the layer's cache discipline.  The
two properties under test are the ones an ``id()``-keyed memo cannot have: a
key that *moves* when the object it stands for is mutated, and a declaration
naming ``data_version`` so a patch-day refresh cannot leave a derived number
cached behind it.
"""

import pytest

from src.calculator.data_registry import data_version
from src.calculator.program import caches


class Actor:
    """A stand-in for a combatant: an identity plus a mutable stat dict."""

    def __init__(self, participant_id: str, **stats: float) -> None:
        self.participant_id = participant_id
        self.stats = dict(stats)


class TestAKeyIsDerivedFromTheValue:
    """The property ``id()`` cannot have, stated as a mutation test."""

    def test_mutating_an_actor_moves_its_fingerprint(self) -> None:
        actor = Actor("main", ability_power=100.0)
        before = caches.actor_fingerprint(actor, ("ability_power",))
        actor.stats["ability_power"] = 140.0
        assert caches.actor_fingerprint(actor, ("ability_power",)) != before

    def test_two_actors_with_equal_stats_share_a_fingerprint(self) -> None:
        """Equality is structural, so two equal inputs are one cache entry."""
        first = Actor("main", ability_power=100.0)
        second = Actor("main", ability_power=100.0)
        fields = ("ability_power",)
        assert caches.actor_fingerprint(first, fields) == caches.actor_fingerprint(
            second, fields
        )

    def test_the_declared_field_set_bounds_the_key(self) -> None:
        """A key over "every attribute" would grow whenever the actor did."""
        actor = Actor("main", ability_power=100.0, armor=50.0)
        narrow = caches.actor_fingerprint(actor, ("ability_power",))
        actor.stats["armor"] = 90.0
        assert caches.actor_fingerprint(actor, ("ability_power",)) == narrow

    def test_the_roster_key_is_order_sensitive(self) -> None:
        """Two orders are two index spaces; one's actions are not the other's."""
        assert caches.roster_fingerprint(
            ("main", "ally:1")
        ) != caches.roster_fingerprint(("ally:1", "main"))

    def test_the_roster_key_carries_the_data_version(self) -> None:
        assert caches.roster_fingerprint(("main",))[0] == data_version()

    def test_two_passes_are_two_program_keys(self) -> None:
        """A patch that a cache could not see would be silently discarded."""
        roster = caches.roster_fingerprint(("main",))
        first = caches.program_fingerprint(roster, (), (), 0)
        second = caches.program_fingerprint(roster, (), (), 1)
        assert first != second


class TestEveryCacheDeclaresWhatStalesIt:
    """The registry half — a property something can iterate."""

    def test_every_declaration_names_the_data_version(self) -> None:
        for name, declaration in caches.CACHES.items():
            assert caches.Invalidator.DATA_VERSION in declaration.invalidated_by, name

    def test_a_declaration_without_it_cannot_be_constructed(self) -> None:
        with pytest.raises(ValueError, match="DATA_VERSION"):
            caches.CacheDeclaration(
                name="forgetful",
                key_fields=("roster",),
                invalidated_by=frozenset({caches.Invalidator.ROSTER}),
            )

    def test_a_declaration_with_no_key_fields_cannot_be_constructed(self) -> None:
        with pytest.raises(ValueError, match="no key fields"):
            caches.CacheDeclaration(
                name="keyless",
                key_fields=(),
                invalidated_by=frozenset({caches.Invalidator.DATA_VERSION}),
            )

    def test_the_compiled_action_cache_declares_the_projection(self) -> None:
        """Score-mode and receipt-mode actions are not interchangeable."""
        declaration = caches.CACHES["compiled_actions"]
        assert caches.Invalidator.PROJECTION in declaration.invalidated_by
