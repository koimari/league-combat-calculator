"""Sivir W (Ricochet) — the bounce row, re-pointed and per-bounce.

The reviewed packet's ``ad`` ratio was ``[0.20 ... 0.40]``, which is the
cached **Bonus Attack Speed** row, not **Bounce Damage** ``[40 ... 50]%
AD``: the two rows sit side by side in the same ``leveling`` block and
the packet took the wrong one, pricing 40.8 raw at rank 5 / 102 AD where
the damage row gives 51.0.  ``TestBounceDamageRow`` pins the row the
module now reads through the atom accessor, and pins the neighbouring
attack-speed row as a distinct atom so the two can never be confused
again.

The row is also no longer one lump.  The cached bounce sentence caps a
swing at 8 bounces across enemies AND allows each enemy "up to one
additional time per empowered attack", so one priced target takes
exactly one bounce per empowered swing and the 8 never binds in a pair
fight.  ``TestPerBounceStructure`` pins that the count is the fight's own
auto cadence across the sourced 4-second window, floored at one swing by
the cached attack-timer reset.
"""

import copy

import pytest

from src.calculator.ability_atoms import required_ranked_attribute_atom
from src.calculator.champions import parse_champion_abilities
from src.calculator.champions.sivir import ASSUMPTIONS
from src.calculator.data_fetcher import get_champion
from src.calculator.stats import calculate_total_stats

_SIVIR = get_champion("Sivir")
_TARGET = {
    "armor": 100.0,
    "magic_resist": 50.0,
    "magic_resistance": 50.0,
    "target_max_health": 2500.0,
    "target_current_health": 2500.0,
    "target_missing_health": 0.0,
}


def _parse(*, level: int = 18, rank: int = 5, options: dict | None = None):
    """Parse Sivir at *level*, mirroring the pipeline."""
    data = copy.deepcopy(_SIVIR)
    champion_stats = dict(calculate_total_stats(data, level, []))
    abilities = parse_champion_abilities(
        data,
        level,
        champion_stats["ability_power"],
        ability_ranks={"Q": 5, "W": rank, "E": 5, "R": 3},
        champion_stats=champion_stats,
        target_stats=dict(_TARGET),
        champion_options=options,
    )
    return champion_stats, abilities


def _fight(mode: str, *, duration: float = 10.0, uptime: float = 1.0) -> dict:
    """One /api/calculate fight at level 18, no items — the real boundary."""
    from src import app as app_module

    payload = {
        "champion": "Sivir",
        "level": 18,
        "items": [],
        "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
        "fight_mode": mode,
        "fight_duration": duration,
        "include_auto_attacks": True,
        "auto_attack_uptime": uptime,
        "target_health": 2500.0,
        "target_armor": 100.0,
        "target_mr": 50.0,
        "deterministic": True,
    }
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


class TestBounceDamageRow:
    """SC3: the packet priced the attack-speed row."""

    @pytest.mark.parametrize(
        "rank,ratio", [(1, 40.0), (2, 42.5), (3, 45.0), (4, 47.5), (5, 50.0)]
    )
    def test_cached_bounce_damage_is_the_ad_row(self, rank, ratio):
        value, atom = required_ranked_attribute_atom(
            "Sivir", _SIVIR, "W", "Bounce Damage", rank, modifier_index=0
        )
        assert value == pytest.approx(ratio)
        assert atom["units"] == ["% AD"] * 5

    def test_the_attack_speed_row_is_a_different_atom(self):
        """The row the packet had matched: same block, percent not % AD."""
        value, atom = required_ranked_attribute_atom(
            "Sivir", _SIVIR, "W", "Bonus Attack Speed", 5, modifier_index=0
        )
        assert value == pytest.approx(40.0)
        assert atom["units"] == ["%"] * 5

    def test_one_bounce_prices_the_damage_row_not_the_steroid(self):
        stats, abilities = _parse()
        assert stats["attack_damage"] == pytest.approx(102.0)
        (part,) = abilities["W"]["parts"]
        # 50% AD, not the 40% the Bonus Attack Speed row would have given.
        assert part.amount == pytest.approx(51.0)
        assert part.amount != pytest.approx(40.8)

    def test_bounce_crits_at_full_effectiveness(self):
        """Cached: Bounce Critical Damage is exactly 2x Bounce Damage."""
        (part,) = _parse()[1]["W"]["parts"]
        assert part.crit_effectiveness == pytest.approx(1.0)
        for rank in range(1, 6):
            damage, _ = required_ranked_attribute_atom(
                "Sivir", _SIVIR, "W", "Bounce Damage", rank, modifier_index=0
            )
            crit, _ = required_ranked_attribute_atom(
                "Sivir", _SIVIR, "W", "Bounce Critical Damage", rank, modifier_index=0
            )
            assert crit == pytest.approx(2.0 * damage)

    def test_receipt_names_the_row_it_refused(self):
        assumption = next(a for a in ASSUMPTIONS if "W (Ricochet)" in a)
        assert "'Bounce Damage'" in assumption
        assert "'Bonus Attack Speed'" in assumption


class TestPerBounceStructure:
    """ER2: one bounce per empowered swing, not one lump."""

    def test_no_auto_stream_still_earns_the_reset_swing(self):
        """One rotation: the cached attack-timer reset floors it at one."""
        (part,) = _parse()[1]["W"]["parts"]
        assert part.count == 1

    @pytest.mark.parametrize("uptime,expected", [(0.0, 1), (0.5, 1), (1.0, 3)])
    def test_count_is_the_fight_auto_cadence_over_the_window(self, uptime, expected):
        """0.795 attacks/s x uptime x the sourced 4s window, floored at 1."""
        _, abilities = _parse(
            options={"fight_duration_seconds": 10.0, "auto_attack_uptime": uptime}
        )
        (part,) = abilities["W"]["parts"]
        assert part.count == expected
        assert abilities["W"]["total_raw"] == pytest.approx(51.0 * expected)

    def test_the_window_is_the_cached_four_second_atom(self):
        entry = _SIVIR["abilities"]["W"][0]
        assert "for the next 4 seconds" in entry["effects"][0]["description"]

    def test_the_cap_sentence_is_per_swing_and_per_enemy(self):
        """Why one target takes one bounce per swing, not eight."""
        text = _SIVIR["abilities"]["W"][0]["effects"][1]["description"]
        assert "Bounces occur only up to 8 times" in text
        assert "each enemy up to one additional time per empowered attack" in text
        # The load-bearing half: with no new target the bounce still lands.
        assert "then the nearest target if no new targets are available" in text

    def test_the_bounces_carry_no_authored_sub_cast_timing(self):
        """The count is sourced; the cadence inside the window is not."""
        (part,) = _parse()[1]["W"]["parts"]
        assert part.time_offset is None
        assert part.hit_interval is None

    def test_receipt_names_the_unmodeled_attack_speed_steroid(self):
        assumption = next(a for a in ASSUMPTIONS if "W (Ricochet)" in a)
        assert "the swing count is a floor" in assumption


class TestThroughTheRequestBoundary:
    """The numbers a caller sees, not the ones the parser holds.

    100 target armor halves physical damage, so a 51.0 raw bounce is 25.5
    mitigated — the row was 20.4 while the packet priced the 40.8 the
    attack-speed ratio gave.
    """

    def test_one_rotation_prices_one_bounce(self):
        row = _fight("one_rotation")["breakdown"]["W"]
        assert row["total_damage"] == pytest.approx(25.5)

    def test_a_ten_second_fight_prices_the_swing_stream(self):
        row = _fight("time_based")["breakdown"]["W"]
        assert row["total_damage"] == pytest.approx(76.5)
        assert "3 bounce(s)" in row["detail"]
