"""P5 spatial primitives — unit tests for pos, distance, and range counting."""

import math

import pytest

from src.calculator.spatial import (
    SPATIAL_UNAVAILABLE,
    _position_of,
    enemies_within_range,
    euclidean,
)


def _actor(name, team, position=None):
    """Build a minimal actor-like namespace for spatial tests."""
    from types import SimpleNamespace

    stats = {}
    if position is not None:
        stats["position"] = position
    return SimpleNamespace(participant_id=name, team=team, stats=stats)


class TestPositionOf:
    def test_extracts_valid_tuple(self):
        actor = _actor("Ahri", "main", (100.0, 200.0))
        assert _position_of(actor) == (100.0, 200.0)

    def test_none_when_stats_missing(self):
        from types import SimpleNamespace

        actor = SimpleNamespace(participant_id="Ahri", team="main")
        # No stats attribute
        assert _position_of(actor) is None

    def test_none_when_position_missing(self):
        actor = _actor("Ahri", "main", None)
        assert _position_of(actor) is None

    def test_none_when_non_tuple(self):
        actor = _actor("Ahri", "main", [100, 200])  # list, not tuple
        assert _position_of(actor) is None

    def test_none_when_wrong_length(self):
        actor = _actor("Ahri", "main", (1, 2, 3))
        assert _position_of(actor) is None

    def test_none_when_non_finite(self):
        actor = _actor("Ahri", "main", (float("nan"), 0.0))
        assert _position_of(actor) is None

    def test_none_when_non_numeric(self):
        actor = _actor("Ahri", "main", ("bad", 0.0))
        assert _position_of(actor) is None

    def test_stats_not_a_mapping(self):
        from types import SimpleNamespace

        actor = SimpleNamespace(participant_id="Ahri", team="main", stats=42)
        assert _position_of(actor) is None


class TestEuclidean:
    def test_origin_to_point(self):
        assert euclidean((0, 0), (3, 4)) == pytest.approx(5.0)

    def test_zero_distance(self):
        assert euclidean((1, 1), (1, 1)) == pytest.approx(0.0)

    def test_large_values(self):
        d = euclidean((0, 0), (1200, 0))
        assert d == pytest.approx(1200.0)
        assert d <= 1200.0


class TestEnemiesWithinRange:
    def test_zero_enemies_in_range_all_outside(self):
        holder = _actor("main", "main", (0.0, 0.0))
        enemies = [
            _actor("e1", "enemy", (2000.0, 0.0)),
            _actor("e2", "enemy", (-2000.0, 0.0)),
        ]
        count, reason = enemies_within_range(holder, enemies, 1200.0)
        assert count == 0
        assert reason is None

    def test_one_enemy_in_range(self):
        holder = _actor("main", "main", (0.0, 0.0))
        enemies = [
            _actor("e1", "enemy", (600.0, 0.0)),
            _actor("e2", "enemy", (1500.0, 0.0)),
        ]
        count, reason = enemies_within_range(holder, enemies, 1200.0)
        assert count == 1
        assert reason is None

    def test_two_enemies_in_range(self):
        holder = _actor("main", "main", (0.0, 0.0))
        enemies = [
            _actor("e1", "enemy", (300.0, 400.0)),
            _actor("e2", "enemy", (0.0, 1100.0)),
            _actor("e3", "enemy", (2000.0, 0.0)),
        ]
        count, reason = enemies_within_range(holder, enemies, 1200.0)
        assert count == 2
        assert reason is None

    def test_exact_boundary_inclusive(self):
        holder = _actor("main", "main", (0.0, 0.0))
        enemies = [_actor("e1", "enemy", (1200.0, 0.0))]
        count, reason = enemies_within_range(holder, enemies, 1200.0)
        assert count == 1
        assert reason is None

    def test_missing_holder_position(self):
        holder = _actor("main", "main", None)  # no position
        enemies = [_actor("e1", "enemy", (600.0, 0.0))]
        count, reason = enemies_within_range(holder, enemies, 1200.0)
        assert count == 0
        assert reason == "missing_holder_position"

    def test_missing_holder_identity(self):
        from types import SimpleNamespace

        holder = SimpleNamespace(team="main", stats={"position": (0.0, 0.0)})
        # No participant_id
        enemies = [_actor("e1", "enemy", (600.0, 0.0))]
        count, reason = enemies_within_range(holder, enemies, 1200.0)
        assert count == 0
        assert reason == "missing_holder_identity"

    def test_enemy_missing_position(self):
        holder = _actor("main", "main", (0.0, 0.0))
        enemies = [
            _actor("e1", "enemy", None),  # missing position
            _actor("e2", "enemy", (600.0, 0.0)),
        ]
        count, reason = enemies_within_range(holder, enemies, 1200.0)
        assert count == 0
        assert reason == SPATIAL_UNAVAILABLE

    def test_enemy_malformed_position(self):
        holder = _actor("main", "main", (0.0, 0.0))
        enemies = [_actor("e1", "enemy", (float("nan"), 0.0))]
        count, reason = enemies_within_range(holder, enemies, 1200.0)
        assert count == 0
        assert reason == SPATIAL_UNAVAILABLE

    def test_skips_teammates(self):
        holder = _actor("main", "main", (0.0, 0.0))
        allies = [_actor("ally1", "main", (600.0, 0.0))]
        count, reason = enemies_within_range(holder, allies, 1200.0)
        assert count == 0
        assert reason is None

    def test_skips_holder_by_id(self):
        holder = _actor("main", "main", (0.0, 0.0))
        # Same team, same id — should skip
        count, reason = enemies_within_range(holder, [holder], 1200.0)
        assert count == 0
        assert reason is None

    def test_no_actors(self):
        holder = _actor("main", "main", (0.0, 0.0))
        count, reason = enemies_within_range(holder, [], 1200.0)
        assert count == 0
        assert reason is None

    def test_holder_position_none_dominates(self):
        holder = _actor("main", "main", None)
        enemies = [
            _actor("e1", "enemy", None),  # also missing
        ]
        count, reason = enemies_within_range(holder, enemies, 1200.0)
        assert count == 0
        assert reason == "missing_holder_position"
