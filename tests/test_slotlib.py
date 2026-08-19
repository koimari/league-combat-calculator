"""Tests for the champion tree's one JSON extraction core.

A cached leveling row can hold two different axes at once — one value per
ability rank beside one value per champion level — and each array says
which it is by its own length. These tests pin that rule against the cache
rather than against remembered numbers, so a patch that moves a row moves
both sides of every assertion together.
"""

import pytest

from src.calculator.champions.slotlib import (
    _axis_index,
    extract_cooldown,
    extract_named,
    find_named_leveling,
    sum_modifiers,
)
from src.calculator.scenario import load_public_champion

LEVEL = 18
AP = 200.0
STATS = {"ability_power": AP}


def _row(champion: str, slot: str, attribute: str, entry: int = 0):
    ability = load_public_champion(champion)["abilities"][slot][entry]
    leveling = find_named_leveling(ability, attribute)
    assert leveling is not None, f"{champion} {slot} has no {attribute!r} row"
    return ability, leveling


def _values(leveling, index: int) -> list:
    return leveling["modifiers"][index]["values"]


class TestAxisIndex:
    """Which axis an array is on is a property of the array."""

    @pytest.mark.parametrize("length", [1, 3, 5, 6, 13, 17])
    def test_short_arrays_stay_on_the_rank_axis(self, length: int) -> None:
        """Six is the longest rank axis in the cache (Jayce's dual forms),
        and the 7-to-17 band is level *brackets* with their own domains —
        neither is readable at a champion level."""
        values = list(range(length))
        assert _axis_index(values, rank=3, level=LEVEL) == min(2, length - 1)

    @pytest.mark.parametrize("length", [18, 19, 20, 40])
    def test_long_arrays_move_to_the_level_axis(self, length: int) -> None:
        values = list(range(length))
        assert _axis_index(values, rank=3, level=LEVEL) == LEVEL - 1

    def test_without_a_level_every_array_reads_by_rank(self) -> None:
        """A caller that does not know the level gets what it always got."""
        assert _axis_index(list(range(40)), rank=3, level=None) == 2

    def test_the_level_axis_clamps_to_the_array(self) -> None:
        assert _axis_index(list(range(18)), rank=1, level=20) == 17


class TestMixedRowSummation:
    """One row, two axes: Zoe Q carries both and must price both."""

    def test_each_term_is_read_on_its_own_axis(self) -> None:
        _, leveling = _row("Zoe", "Q", "Maximum Magic Damage")
        per_level, per_rank, ap_ratio = (_values(leveling, i) for i in range(3))
        assert len(per_level) >= 18 and len(per_rank) == 5

        total = sum_modifiers(leveling, 5, dict(STATS), level=LEVEL)

        assert total == pytest.approx(
            float(per_level[LEVEL - 1])
            + float(per_rank[4])
            + float(ap_ratio[4]) / 100.0 * AP
        )

    def test_the_level_term_is_what_moves(self) -> None:
        """Without the level the row prices its per-level term at rank 5."""
        _, leveling = _row("Zoe", "Q", "Maximum Magic Damage")
        per_level = _values(leveling, 0)
        priced_at_rank = sum_modifiers(leveling, 5, dict(STATS))
        priced_at_level = sum_modifiers(leveling, 5, dict(STATS), level=LEVEL)
        assert priced_at_level - priced_at_rank == pytest.approx(
            float(per_level[LEVEL - 1]) - float(per_level[4])
        )

    @pytest.mark.parametrize(
        "champion,slot,attribute",
        [
            ("Mordekaiser", "Q", "Magic Damage"),
            ("Tahm Kench", "Q", "Magic Damage"),
            ("Malzahar", "W", "Magic Damage"),
            ("Azir", "W", "Magic Damage"),
        ],
    )
    def test_other_mixed_rows_price_their_level_term_at_the_level(
        self, champion: str, slot: str, attribute: str
    ) -> None:
        ability, leveling = _row(champion, slot, attribute)
        per_level = next(
            modifier["values"]
            for modifier in leveling["modifiers"]
            if len(modifier.get("values") or []) >= 18
        )
        rank = 3 if slot == "R" else 5
        moved = extract_named(
            ability, attribute, rank, dict(STATS), level=LEVEL
        ) - extract_named(ability, attribute, rank, dict(STATS))
        assert moved == pytest.approx(
            float(per_level[LEVEL - 1]) - float(per_level[rank - 1])
        )

    def test_a_pure_rank_row_is_unmoved_by_the_level(self) -> None:
        """Aatrox Q is five values per rank and nothing else."""
        attribute = "First Cast Damage"
        ability, leveling = _row("Aatrox", "Q", attribute)
        assert max(len(m.get("values") or []) for m in leveling["modifiers"]) == 5
        assert extract_named(
            ability, attribute, 5, dict(STATS), level=LEVEL
        ) == extract_named(ability, attribute, 5, dict(STATS))


class TestCooldownAxis:
    """A cooldown row obeys the same rule as a damage row."""

    def test_a_per_level_cooldown_is_read_at_the_level(self) -> None:
        ability = load_public_champion("Aphelios")["abilities"]["Q"][1]
        values = ability["cooldown"]["modifiers"][0]["values"]
        assert len(values) >= 18
        assert extract_cooldown(ability, 1, level=LEVEL) == pytest.approx(
            float(values[LEVEL - 1])
        )

    def test_a_six_rank_cooldown_stays_on_the_rank_axis(self) -> None:
        """Jayce's abilities really do have six ranks — the guard case."""
        ability = load_public_champion("Jayce")["abilities"]["Q"][0]
        values = ability["cooldown"]["modifiers"][0]["values"]
        assert len(values) == 6
        assert extract_cooldown(ability, 6, level=LEVEL) == pytest.approx(
            float(values[5])
        )

    def test_a_rank_cooldown_falls_with_rank(self) -> None:
        ability = load_public_champion("Thresh")["abilities"]["Q"][0]
        values = ability["cooldown"]["modifiers"][0]["values"]
        assert extract_cooldown(ability, 5, level=LEVEL) == pytest.approx(
            float(values[4])
        )
