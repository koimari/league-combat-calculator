"""Front-door tests for the rotation resolver.

The F2 and F3 suites keep the historical campaign cases and the broad
champion matrix.  These tests make the resolver easy to find by module name.
"""

import dataclasses

import pytest

from src.calculator.champions import parse_champion_abilities
from src.calculator.damage import DEFAULT_CAST_ORDER
from src.calculator.data_fetcher import fetch_champion_data
from src.calculator.rotation_resolver import (
    detect_setup_consume_edges,
    rank_ability_dps,
    resolve_cast_order,
)
from src.calculator.stats import calculate_total_stats


def test_unknown_empty_kit_uses_the_engine_default_order() -> None:
    order, rule = resolve_cast_order("Synthetic Fixture", {})

    assert order == list(DEFAULT_CAST_ORDER)
    assert rule is None


def test_dps_ranking_uses_the_effective_cooldown() -> None:
    ranked = rank_ability_dps(
        {
            "Q": {"total_raw": 100.0, "cooldown": 10.0},
            "W": {"total_raw": 100.0, "cooldown": 5.0},
        }
    )

    assert [slot for slot, *_ in ranked] == ["W", "Q"]


class TestAReviewedAbsenceOfControlOrdersNothing:
    """``cc_kind="none"`` is a reviewed absence, so it is not an apply atom.

    The detector fans a ``cc_setup`` edge from every slot that applies
    crowd control, out to every castable damage row.  Reading a reviewed
    *absence* as an application would rewrite a whole kit's derived cast
    order around a stun the module explicitly said does not exist — and
    the receipt would cite it in prose.
    """

    CHAMPION = "Corki"  # migrated cc-free, whole kit

    @pytest.fixture(scope="class")
    def champion_data(self):
        champions = fetch_champion_data()
        return next(
            data for data in champions.values() if data.get("name") == self.CHAMPION
        )

    @pytest.fixture(scope="class")
    def parsed(self, champion_data):
        stats = calculate_total_stats(champion_data, 18, [])
        return parse_champion_abilities(
            champion_data,
            18,
            stats["ability_power"],
            champion_stats=stats,
            target_stats={
                "target_max_health": 2000.0,
                "target_current_health": 2000.0,
                "target_missing_health": 0.0,
            },
        )

    @staticmethod
    def _edges(champion_name, parsed, champion_data):
        return detect_setup_consume_edges(champion_name, parsed, champion_data, {})

    def test_the_kit_is_actually_declared_cc_free(self, parsed) -> None:
        """The premise: every part of every slot carries the review."""
        kinds = {
            part.cc_kind for entry in parsed.values() for part in entry.get("parts", ())
        }
        assert kinds == {"none"}

    def test_no_cc_setup_edge_is_fanned(self, parsed, champion_data) -> None:
        edges = self._edges(self.CHAMPION, parsed, champion_data)
        assert [e for e in edges if e.kind == "cc_setup"] == []

    def test_no_derived_rationale_cites_crowd_control(
        self, parsed, champion_data
    ) -> None:
        _order, rule = resolve_cast_order(
            self.CHAMPION, parsed, champion_data=champion_data
        )
        assert "cc_kind" not in (rule.rationale if rule else "")
        assert "crowd control" not in (rule.rationale if rule else "")

    def test_a_real_kind_on_the_same_row_still_fans_edges(
        self, parsed, champion_data
    ) -> None:
        """The suppression is about the reviewed absence and nothing else:
        the same row carrying a real kind still orders the rotation."""
        stunned = dict(parsed)
        stunned["E"] = dict(parsed["E"])
        stunned["E"]["parts"] = tuple(
            dataclasses.replace(part, cc_kind="stun") for part in stunned["E"]["parts"]
        )
        edges = self._edges(self.CHAMPION, stunned, champion_data)
        assert [(e.setup, e.consume) for e in edges if e.kind == "cc_setup"]
