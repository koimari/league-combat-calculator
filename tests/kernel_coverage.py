"""Which keys the fixture registry owes a fixture, and which it reaches."""

from functools import cache

from src.calculator.ally_packet_shape import _declared_authorities, producer_item
from src.calculator.trigger_stream import tuple_incapable_items

from .kernel_fixtures import REGISTRY_FIXTURES, KernelFixture


def required_coverage_keys() -> frozenset[str]:
    """Every key this suite owes a fixture, read from the registries.

    ``tuple_incapable_items()`` is the tuple-incapable set the pipeline's
    tuple gate consults, and contributes item names;
    ``_declared_authorities()`` is the ``damage_modifier`` producer
    table, and contributes ``source`` literals — one key per packet, not per
    item, so a second packet on an already-equipped item is its own
    requirement.  Neither registry is restated here, so a new event-view
    holder or a seventh producer becomes a required key on the commit that
    adds it — and fails this suite until it has a fixture.

    Both now project one declaration table.  The item half read the hand set
    ``item_support_effects.EVENT_VIEW_SUPPORT_ITEMS`` until Phase 2's P2c
    deleted it, and the producer half read that module's ``ast`` derivation
    over its own call sites until the same commit; both are
    ``trigger_stream.CAPABILITIES`` projections now.
    """
    return tuple_incapable_items() | frozenset(_declared_authorities())


@cache
def _reached_keys(fixture: KernelFixture) -> tuple[frozenset[str], frozenset[str]]:
    """``(candidate-authored, ally-authored)`` keys this fixture really fires.

    Read off the receipt's public ``support_events`` rows and attributed by
    each packet's own ``attacker``, so a fixture that equips an item without
    ever reaching its packet contributes no coverage.  Each row credits both
    granularities the registries use: the packet's own ``source`` literal and
    the item that source names.
    """
    candidate: set[str] = set()
    ally: set[str] = set()
    for event in fixture.receipt().get("support_events", ()):
        source = str(event.get("source", ""))
        keys = {source, producer_item(source)}
        attacker = str(event.get("attacker", ""))
        if attacker == "main":
            candidate |= keys
        elif attacker.startswith("ally:"):
            ally |= keys
    return frozenset(candidate), frozenset(ally)


@cache
def _fixture_coverage() -> tuple[frozenset[str], frozenset[str]]:
    """``(candidate, ally)`` keys the whole fixture set reaches between them."""
    candidate: frozenset[str] = frozenset()
    ally: frozenset[str] = frozenset()
    for fixture in REGISTRY_FIXTURES:
        reached_candidate, reached_ally = _reached_keys(fixture)
        candidate |= reached_candidate
        ally |= reached_ally
    return candidate, ally


def missing_fixtures(
    required: frozenset[str],
    candidate_reached: frozenset[str],
    ally_reached: frozenset[str],
) -> tuple[tuple[str, str], ...]:
    """Every ``(key, side)`` a required key is owed and does not have.

    One pure function over three sets, so the check's own red is reproducible
    on demand instead of being a claim about the past (R-05).
    """
    return tuple(
        sorted(
            (key, side)
            for key in required
            for side, reached in (
                ("candidate", candidate_reached),
                ("ally", ally_reached),
            )
            if key not in reached
        )
    )
