"""Shared fixtures and helpers for champion test files.

Centralizes champion data loading and the common three-step test setup
pattern (load data → calculate stats → parse abilities) so individual
test files can focus on champion-specific assertions.
"""

import pytest

from src.calculator.data_fetcher import get_champion
from src.calculator.stats import calculate_total_stats
from src.calculator.champions import parse_abilities as _dispatch_parse


# ---------------------------------------------------------------------------
# Champion data fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def aatrox_data() -> dict:
    """Load Aatrox champion data from the cached JSON."""
    return get_champion("Aatrox")


@pytest.fixture
def akali_data() -> dict:
    """Load Akali champion data from the cached JSON."""
    return get_champion("Akali")


@pytest.fixture
def akshan_data() -> dict:
    """Load Akshan champion data from the cached JSON."""
    return get_champion("Akshan")


@pytest.fixture
def alistar_data() -> dict:
    """Load Alistar champion data from the cached JSON."""
    return get_champion("Alistar")


@pytest.fixture
def ambessa_data() -> dict:
    """Load Ambessa champion data from the cached JSON."""
    return get_champion("Ambessa")


# ---------------------------------------------------------------------------
# Shared helper fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def parse_at():
    """Factory fixture: calculate stats and parse abilities in one call.

    Returns a callable with signature::

        (champion_data, level, *, items=None, ap=0.0, **kwargs)
            -> (stats, abilities)

    ``kwargs`` are forwarded to ``parse_abilities`` (e.g.
    ``champion_options``, ``target_stats``, ``ability_ranks``).

    Example usage in a test::

        def test_q_type(self, aatrox_data, parse_at):
            _, abilities = parse_at(aatrox_data, 9)
            assert abilities["Q"]["damage_type"] == "physical"
    """

    def _parse(
        champion_data: dict,
        level: int,
        *,
        items: list | None = None,
        ap: float = 0.0,
        **kwargs,
    ) -> tuple[dict, dict]:
        stats = calculate_total_stats(champion_data, level, items or [])
        abilities = _dispatch_parse(
            champion_data["name"],
            champion_data,
            level,
            ap,
            champion_stats=stats,
            **kwargs,
        )
        return stats, abilities

    return _parse
