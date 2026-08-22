"""E5-3: Wukong Q armor-reduction debuff (Crushing Blow).

Wukong's Q (Crushing Blow) empowers the next basic attack to deal bonus
physical damage AND inflict armor reduction for 3 seconds. The debuff was
unmodeled: the module emitted only the bonus-damage packet, so every
post-Q hit (R ticks, E follow-ups, later Q casts) was priced against
unshredded armor even though the Kog'Maw/Jarvan Q infrastructure for
``target_debuff`` existed.

Fix: Q now emits a ``target_debuff`` with ``armor_reduction_percent``
read from the "Armor Reduction" leveling row (10/15/20/25/30% of the
target's armor by rank) and a 3-second duration pinned from the wiki
prose ("inflict armor reduction for 3 seconds"). damage.py applies the
shred AFTER the ability's own damage — the empowered swing itself lands
at full target armor (matching in-game), while everything after it sees
the reduced armor.

Every expected number in this file is recomputed from
``data/champions.json`` leveling rows plus the fight's own
``champion_stats`` (never literal values); the only prose-pinned value
is the 3s shred duration, imported from the module constant that cites
the wiki.

Fight scenario: /api/calculate, level 18, basic abilities rank 5,
R rank 3, no items (the E5 audit standard).
"""

import json
from pathlib import Path

import pytest

from src import app as app_module
from src.calculator.champions import parse_champion_abilities
from src.calculator.champions import wukong
from src.calculator.data_fetcher import get_champion
from src.calculator.stats import calculate_total_stats
from src.calculator.champions.slotlib import find_named_leveling

_CHAMPION_DATA = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))
_FULL_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_CACHE_KEY = "MonkeyKing"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fight(
    *, options: dict | None = None, mode: str = "one_rotation", armor: float = 100.0
) -> dict:
    """One /api/calculate fight at level 18, rank 5 / R rank 3, no items."""
    payload = {
        "champion": "Wukong",
        "level": 18,
        "items": [],
        "role": "top",
        "ability_ranks": dict(_FULL_RANKS),
        "fight_mode": mode,
        "fight_duration": 10.0,
        "include_auto_attacks": False,
        "champion_options": options or {},
        "target_health": 2000.0,
        "target_armor": armor,
        "target_mr": 0,
    }
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _leveling(slot: str, attribute: str, occurrence: int = 0) -> dict:
    """Return the N-th leveling entry with this attribute from the cache."""
    ability = _CHAMPION_DATA[_CACHE_KEY]["abilities"][slot][0]
    leveling = find_named_leveling(ability, attribute, occurrence=occurrence)
    if leveling is None:
        raise AssertionError(
            f"MonkeyKing {slot} has no leveling attribute {attribute!r} "
            f"(occurrence {occurrence})"
        )
    return leveling


def _resolve(
    slot: str, attribute: str, rank: int, stats: dict, target_max_health: float
) -> float:
    """Sum one leveling entry at rank against the fight's own stats.

    Handles exactly the unit vocabulary Wukong's tested rows use; an
    unexpected unit fails loudly so the test cannot silently pass with a
    dropped term.
    """
    total = 0.0
    for modifier in _leveling(slot, attribute).get("modifiers", []):
        values = modifier.get("values", [])
        units = modifier.get("units", [])
        if not values:
            continue
        idx = min(max(rank, 1) - 1, len(values) - 1)
        value = float(values[idx])
        unit = units[idx] if idx < len(units) else ""
        if unit in ("", "%"):
            total += value
        elif unit == "% AP":
            total += value / 100.0 * float(stats.get("ability_power", 0.0))
        elif unit == "% AD":
            total += value / 100.0 * float(stats.get("attack_damage", 0.0))
        elif unit == "% bonus AD":
            total += value / 100.0 * float(stats.get("bonus_attack_damage", 0.0))
        elif unit == "% of target's maximum health":
            total += value / 100.0 * target_max_health
        else:
            raise AssertionError(
                f"unhandled unit {unit!r} for MonkeyKing {slot} {attribute}"
            )
    return total


def _effective_armor(armor: float, shred_percent: float, coverage: float) -> float:
    """Armor after the shred: percent reduction, never below 0."""
    return armor * (1.0 - shred_percent / 100.0 * coverage)


def _mitigate(raw: float, armor: float) -> float:
    """Resistance math: raw * 100 / (100 + armor)."""
    return raw * 100.0 / (100.0 + armor)


# ---------------------------------------------------------------------------
# Parse level: Q emits the armor-reduction debuff
# ---------------------------------------------------------------------------


class TestQArmorReductionParse:
    """Crushing Blow now carries the 3s %-armor target_debuff."""

    def test_q_shred_present_at_rank_5(self) -> None:
        data = get_champion(_CACHE_KEY)
        stats = calculate_total_stats(data, 18, [])
        abilities = parse_champion_abilities(
            data,
            18,
            0.0,
            ability_ranks=dict(_FULL_RANKS),
            champion_stats=stats,
        )
        assert abilities["Q"]["target_debuff"] == {
            "armor_reduction_percent": pytest.approx(30.0),
            "duration": pytest.approx(wukong.Q_SHRED_DURATION),
        }

    def test_q_shred_scales_with_rank(self) -> None:
        """Armor Reduction leveling row: 10/15/20/25/30 by rank."""
        data = get_champion(_CACHE_KEY)
        stats = calculate_total_stats(data, 18, [])
        expected = {1: 10.0, 2: 15.0, 3: 20.0, 4: 25.0, 5: 30.0}
        for rank, pct in expected.items():
            abilities = parse_champion_abilities(
                data,
                18,
                0.0,
                ability_ranks={"Q": rank, "W": 5, "E": 5, "R": 3},
                champion_stats=stats,
            )
            debuff = abilities["Q"]["target_debuff"]
            assert debuff["armor_reduction_percent"] == pytest.approx(pct)
            # Every rank of the leveling row declares the same %-of-armor unit.
            unit = _leveling("Q", "Armor Reduction")["modifiers"][0]["units"][rank - 1]
            assert unit == "% of target's armor"

    def test_q_shred_duration_is_wiki_pinned_constant(self) -> None:
        """3s, from the wiki prose 'inflict armor reduction for 3 seconds'."""
        assert wukong.Q_SHRED_DURATION == pytest.approx(3.0)

    def test_q_shred_disabled_by_option(self) -> None:
        data = get_champion(_CACHE_KEY)
        stats = calculate_total_stats(data, 18, [])
        abilities = parse_champion_abilities(
            data,
            18,
            0.0,
            ability_ranks=dict(_FULL_RANKS),
            champion_stats=stats,
            champion_options={"q_armor_reduction": False},
        )
        assert "target_debuff" not in abilities["Q"]

    def test_q_bonus_damage_still_reads_leveling(self) -> None:
        """Q's own packet is untouched: 120 + 50% bonus AD at rank 5."""
        data = get_champion(_CACHE_KEY)
        stats = calculate_total_stats(data, 18, [])
        abilities = parse_champion_abilities(
            data,
            18,
            0.0,
            ability_ranks=dict(_FULL_RANKS),
            champion_stats=stats,
        )
        expected = _resolve("Q", "Bonus Physical Damage", 5, stats, 2000.0)
        assert abilities["Q"]["total_raw"] == pytest.approx(expected)


# ---------------------------------------------------------------------------
# /api/calculate: corrected damage with the shred active
# ---------------------------------------------------------------------------


class TestFightCorrectedDamage:
    """Level 18, rank 5 / R rank 3, no items — the shred changes post-Q
    damage while leaving Q's own swing untouched."""

    def test_one_rotation_shred_applies_to_post_q_damage(self) -> None:
        """One-rotation burst vs 100 armor: Q's shred (30%) lowers armor to
        70 before R ticks land. Q itself lands at full armor.

        R rank 3 per tick = 2% max HP + 34.375% AD (leveling rows) ->
        8 ticks x per_tick x 100/(100+70).
        """
        data = _fight(mode="one_rotation", armor=100.0)
        stats = data["champion_stats"]
        assert data["effective_armor"] == pytest.approx(
            _effective_armor(100.0, 30.0, 1.0)
        )

        q_per_cast = _resolve("Q", "Bonus Physical Damage", 5, stats, 2000.0) + float(
            stats.get("attack_damage", 0.0)
        )
        assert data["breakdown"]["Q"]["total_damage"] == pytest.approx(
            _mitigate(q_per_cast, 100.0), abs=0.06
        )
        assert data["breakdown"]["E"]["total_damage"] == pytest.approx(
            _resolve("E", "Magic Damage", 5, stats, 2000.0), abs=0.06
        )
        r_per_tick = _resolve("R", "Physical Damage Per Tick", 3, stats, 2000.0)
        r_expected = 8 * _mitigate(r_per_tick, _effective_armor(100.0, 30.0, 1.0))
        assert data["breakdown"]["R"]["total_damage"] == pytest.approx(
            r_expected, abs=0.06
        )

        expected_total = (
            _mitigate(q_per_cast, 100.0)
            + _resolve("E", "Magic Damage", 5, stats, 2000.0)
            + r_expected
        )
        assert data["total_damage"] == pytest.approx(expected_total, abs=0.5)

    def test_shred_off_leaves_armor_untouched(self) -> None:
        """q_armor_reduction=False restores the pre-fix behavior: R ticks
        mitigate against the full 100 armor, and the total strictly drops."""
        data_off = _fight(
            mode="one_rotation", armor=100.0, options={"q_armor_reduction": False}
        )
        data_on = _fight(mode="one_rotation", armor=100.0)
        assert data_off["effective_armor"] == pytest.approx(100.0)
        assert data_off["breakdown"]["R"]["total_damage"] == pytest.approx(
            8 * _mitigate(83.3125, 100.0), abs=0.06
        )
        assert data_on["total_damage"] > data_off["total_damage"]

    def test_q_own_swing_never_benefits_from_its_own_shred(self) -> None:
        """The empowered attack lands before the debuff: Q's row is
        identical with the shred on and off."""
        on = _fight(mode="one_rotation", armor=100.0)
        off = _fight(
            mode="one_rotation", armor=100.0, options={"q_armor_reduction": False}
        )
        assert on["breakdown"]["Q"]["total_damage"] == pytest.approx(
            off["breakdown"]["Q"]["total_damage"]
        )

    def test_time_based_coverage_weights_the_shred(self) -> None:
        """10s fight, Q rank-5 CD 6s -> casts at t=0 and t=6; the 3s debuff
        covers [0,3] and [6,9] = 6/10 of the fight, so the applied shred is
        30% * 0.6 = 18%: effective armor 100 -> 82."""
        data = _fight(mode="time_based", armor=100.0)
        coverage = 6.0 / 10.0
        assert data["effective_armor"] == pytest.approx(
            _effective_armor(100.0, 30.0, coverage)
        )
        stats = data["champion_stats"]
        r_per_tick = _resolve("R", "Physical Damage Per Tick", 3, stats, 2000.0)
        r_expected = 8 * _mitigate(r_per_tick, _effective_armor(100.0, 30.0, coverage))
        assert data["breakdown"]["R"]["total_damage"] == pytest.approx(
            r_expected, abs=0.06
        )
        # Two Q casts in 10s (rank-5 CD 6s), both priced at pre-shred armor.
        q_per_cast = _resolve("Q", "Bonus Physical Damage", 5, stats, 2000.0) + float(
            stats.get("attack_damage", 0.0)
        )
        assert data["breakdown"]["Q"]["total_damage"] == pytest.approx(
            2 * _mitigate(q_per_cast, 100.0), abs=0.06
        )
