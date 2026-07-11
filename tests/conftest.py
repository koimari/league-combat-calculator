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


@pytest.fixture
def amumu_data() -> dict:
    """Load Amumu champion data from the cached JSON."""
    return get_champion("Amumu")


@pytest.fixture
def anivia_data() -> dict:
    """Load Anivia champion data from the cached JSON."""
    return get_champion("Anivia")


@pytest.fixture
def annie_data() -> dict:
    """Load Annie champion data from the cached JSON."""
    return get_champion("Annie")


@pytest.fixture
def ashe_data() -> dict:
    """Load Ashe champion data from the cached JSON."""
    return get_champion("Ashe")


@pytest.fixture
def kogmaw_data() -> dict:
    """Load Kog'Maw champion data from the cached JSON."""
    return get_champion("KogMaw")


@pytest.fixture
def vayne_data() -> dict:
    """Load Vayne champion data from the cached JSON."""
    return get_champion("Vayne")


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
        ap: float | None = None,
        **kwargs,
    ) -> tuple[dict, dict]:
        stats = calculate_total_stats(champion_data, level, items or [])
        # Use calculated AP from stats when not explicitly overridden
        effective_ap = ap if ap is not None else stats.get("ability_power", 0.0)
        abilities = _dispatch_parse(
            champion_data["name"],
            champion_data,
            level,
            effective_ap,
            champion_stats=stats,
            **kwargs,
        )
        return stats, abilities

    return _parse
