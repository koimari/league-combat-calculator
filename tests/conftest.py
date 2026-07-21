"""Shared fixtures and helpers for champion test files.

Centralizes champion data loading and the common three-step test setup
pattern (load data → calculate stats → parse abilities) so individual
test files can focus on champion-specific assertions.

Full-roster test strategy
-------------------------
The roster has 170+ champions but only ~12 registered custom modules; the
rest run through the generic slot-archetype path. Coverage is sized
accordingly:

- **Generic champions (160+):** the primary net is the golden snapshot
  (``scripts/golden_snapshot.py`` — all-champion stats/abilities, fights,
  item sweep) plus the generic-path coverage tests in
  ``test_generic_path.py`` (all champions parse without error; ≥95% with
  damage) and the engine/archetype unit tests in ``test_engine.py``.
  There are deliberately NO per-champion test files for these.
- **Registered champions:** a per-champion test file (``test_ahri.py``,
  ``test_kogmaw.py``, ...) exists only for champions with a custom slot
  map, asserting hand-derived ability values and any custom slot-fn
  behavior.
- **Adding a champion:** no new tests are needed while it rides the
  generic path; write a test file only when the champion gets a custom
  module (see the /add-champion skill).
"""

import pytest

from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.stats import calculate_total_stats
from src.calculator.champions import parse_champion_abilities
from src.calculator.damage import FightConfig, calculate_fight_damage

# ---------------------------------------------------------------------------
# Champion data fixtures
# ---------------------------------------------------------------------------


def _champion_fixture(data_key: str):
    """Create a named champion-data fixture from one cache key."""

    @pytest.fixture
    def _load() -> dict:
        return get_champion(data_key)

    return _load


aatrox_data = _champion_fixture("Aatrox")
ahri_data = _champion_fixture("Ahri")
akali_data = _champion_fixture("Akali")
akshan_data = _champion_fixture("Akshan")
alistar_data = _champion_fixture("Alistar")
ambessa_data = _champion_fixture("Ambessa")
amumu_data = _champion_fixture("Amumu")
anivia_data = _champion_fixture("Anivia")
annie_data = _champion_fixture("Annie")
ashe_data = _champion_fixture("Ashe")
# Data key differs from the display/dispatcher name "Aurelion Sol".
aurelion_sol_data = _champion_fixture("AurelionSol")
aurora_data = _champion_fixture("Aurora")
azir_data = _champion_fixture("Azir")
bard_data = _champion_fixture("Bard")
gnar_data = _champion_fixture("Gnar")
# Data key differs from the display/dispatcher name "Jarvan IV".
jarvan_iv_data = _champion_fixture("JarvanIV")
# Data key differs from the display/dispatcher name "Kog'Maw".
kogmaw_data = _champion_fixture("KogMaw")
vayne_data = _champion_fixture("Vayne")


# ---------------------------------------------------------------------------
# Item fixtures (the recurring Ahri mage build used across test files)
# ---------------------------------------------------------------------------


@pytest.fixture
def liandrys() -> dict:
    """Liandry's Torment item data."""
    return get_item_by_name("Liandry's Torment")


@pytest.fixture
def malignance() -> dict:
    """Malignance item data."""
    return get_item_by_name("Malignance")


@pytest.fixture
def rylais() -> dict:
    """Rylai's Crystal Scepter item data."""
    return get_item_by_name("Rylai's Crystal Scepter")


@pytest.fixture
def sorc_shoes() -> dict:
    """Sorcerer's Shoes item data."""
    return get_item_by_name("Sorcerer's Shoes")


@pytest.fixture
def void_staff() -> dict:
    """Void Staff item data."""
    return get_item_by_name("Void Staff")


@pytest.fixture
def rabadons() -> dict:
    """Rabadon's Deathcap item data."""
    return get_item_by_name("Rabadon's Deathcap")


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
        abilities = parse_champion_abilities(
            champion_data,
            level,
            effective_ap,
            champion_stats=stats,
            **kwargs,
        )
        return stats, abilities

    return _parse


@pytest.fixture
def attacker_stats():
    """Build the complete minimal attacker shape used by engine tests."""

    def _build(**overrides: float) -> dict[str, float]:
        stats = {
            "health": 2000.0,
            "bonus_health": 0.0,
            "attack_damage": 100.0,
            "base_attack_damage": 100.0,
            "bonus_attack_damage": 0.0,
            "ability_power": 0.0,
            "armor": 50.0,
            "magic_resistance": 50.0,
            "attack_speed": 1.0,
            "attack_speed_ratio": 0.625,
            "critical_strike_chance": 0.0,
            "magic_penetration_flat": 0.0,
            "magic_penetration_percent": 0.0,
            "flat_armor_penetration": 0.0,
            "armor_penetration_percent": 0.0,
            "lethality": 0.0,
            "ability_haste": 0.0,
            "max_mana": 500.0,
            "bonus_mana": 0.0,
            "basic_ability_haste": 0.0,
            "is_melee": True,
            "level": 18,
        }
        stats.update(overrides)
        return stats

    return _build


@pytest.fixture
def fight():
    """Run a compact default one-rotation fight with explicit overrides."""

    def _run(
        stats: dict[str, float],
        abilities: dict | None = None,
        **overrides,
    ) -> dict:
        config = {
            "target_health": 1000.0,
            "target_armor": 100.0,
            "target_magic_resistance": 100.0,
            "fight_duration_seconds": 5.0,
            "auto_attack_uptime": 0.0,
            "one_rotation": True,
            "deterministic": True,
        }
        config.update(overrides)
        items = config.pop("items", [])
        return calculate_fight_damage(
            stats, abilities or {}, items, FightConfig(**config)
        )

    return _run
