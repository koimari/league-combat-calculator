"""Tests for Cassiopeia champion ability parsing and damage calculation.

Reference damage (wiki: https://wiki.leagueoflegends.com/en-us/Cassiopeia),
all raw pre-resistance magic damage at exactly 100 AP:
- Q (Noxious Blast) rank 5: 215 + 65% AP = 280 (full 3s poison).
- W (Miasma) rank 5: 200 + 50% AP = 250 (full 5s zone duration).
- E (Twin Fang) rank 5, level 18, poisoned: 120 + 120 + 65% AP = 305;
  unpoisoned: 120 + 10% AP = 130. The level base is a 40-entry per-level
  array (+4/level past 18): level 20 poisoned = 128 + 120 + 65 = 313.
- R (Petrifying Gaze) rank 3: 350 + 50% AP = 400.
Against 100 MR (no pen) each is halved.
"""

import pytest

from src.calculator.champions import (
    get_champion_options_meta,
    parse_champion_abilities as parse_abilities,
)
from src.calculator.champions.skill_orders import get_ability_rank

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ALL_MAXED = {"Q": 5, "W": 5, "E": 5, "R": 3}


def _parse(data, ranks, level=18, ap=100.0, options=None):
    """Parse at explicit ranks with the reference 100 AP statline."""
    return parse_abilities(
        data,
        level,
        ap,
        ability_ranks=ranks,
        champion_options=options,
        champion_stats={"attack_damage": 100.0, "bonus_attack_damage": 0.0},
        target_stats={"target_max_health": 3000.0},
    )


# ---------------------------------------------------------------------------
# Q: Noxious Blast
# ---------------------------------------------------------------------------


class TestQNoxiousBlast:
    """Q: full-poison total, not the per-tick breakdown."""

    def test_q_is_magic(self, cassiopeia_data) -> None:
        abilities = _parse(cassiopeia_data, ALL_MAXED)
        assert abilities["Q"]["damage_type"] == "magic"

    def test_q_rank5_total(self, cassiopeia_data) -> None:
        """215 + 65% x 100 AP = 280 — the per-tick attribute would give 40."""
        abilities = _parse(cassiopeia_data, ALL_MAXED)
        assert abilities["Q"]["total_raw"] == pytest.approx(280.0)

    def test_q_rank1_total(self, cassiopeia_data) -> None:
        """75 + 65 = 140."""
        abilities = _parse(cassiopeia_data, {"Q": 1, "W": 0, "E": 0, "R": 0})
        assert abilities["Q"]["total_raw"] == pytest.approx(140.0)

    def test_q_cooldown_flat(self, cassiopeia_data) -> None:
        """3.5s at every rank."""
        r1 = _parse(cassiopeia_data, {"Q": 1, "W": 0, "E": 0, "R": 0})
        r5 = _parse(cassiopeia_data, ALL_MAXED)
        assert r1["Q"]["cooldown"] == pytest.approx(3.5)
        assert r5["Q"]["cooldown"] == pytest.approx(3.5)


# ---------------------------------------------------------------------------
# W: Miasma
# ---------------------------------------------------------------------------


class TestWMiasma:
    """W: full 5-second zone total, not the per-second attribute."""

    def test_w_is_magic(self, cassiopeia_data) -> None:
        abilities = _parse(cassiopeia_data, ALL_MAXED)
        assert abilities["W"]["damage_type"] == "magic"

    def test_w_rank5_total(self, cassiopeia_data) -> None:
        """200 + 50% x 100 AP = 250 — the per-second attribute would give 50."""
        abilities = _parse(cassiopeia_data, ALL_MAXED)
        assert abilities["W"]["total_raw"] == pytest.approx(250.0)

    def test_w_rank1_total(self, cassiopeia_data) -> None:
        """100 + 50 = 150."""
        abilities = _parse(cassiopeia_data, {"Q": 0, "W": 1, "E": 0, "R": 0})
        assert abilities["W"]["total_raw"] == pytest.approx(150.0)

    def test_w_cooldown(self, cassiopeia_data) -> None:
        """24/22/20/18/16."""
        r1 = _parse(cassiopeia_data, {"Q": 0, "W": 1, "E": 0, "R": 0})
        r5 = _parse(cassiopeia_data, ALL_MAXED)
        assert r1["W"]["cooldown"] == pytest.approx(24.0)
        assert r5["W"]["cooldown"] == pytest.approx(16.0)


# ---------------------------------------------------------------------------
# E: Twin Fang
# ---------------------------------------------------------------------------


class TestETwinFang:
    """E: per-level base + 10% AP; poisoned adds rank bonus + 55% AP."""

    def test_e_is_magic(self, cassiopeia_data) -> None:
        abilities = _parse(cassiopeia_data, ALL_MAXED)
        assert abilities["E"]["damage_type"] == "magic"

    def test_e_poisoned_default_rank5_level18(self, cassiopeia_data) -> None:
        """Default (no options dict) is poisoned: 120 + 120 + 65 = 305."""
        abilities = _parse(cassiopeia_data, ALL_MAXED)
        assert abilities["E"]["total_raw"] == pytest.approx(305.0)

    def test_e_poisoned_option_true(self, cassiopeia_data) -> None:
        abilities = _parse(
            cassiopeia_data, ALL_MAXED, options={"target_poisoned": True}
        )
        assert abilities["E"]["total_raw"] == pytest.approx(305.0)

    def test_e_unpoisoned_rank5_level18(self, cassiopeia_data) -> None:
        """Unpoisoned: level base 120 + 10% AP = 130."""
        abilities = _parse(
            cassiopeia_data, ALL_MAXED, options={"target_poisoned": False}
        )
        assert abilities["E"]["total_raw"] == pytest.approx(130.0)

    def test_e_poisoned_level20_uses_per_level_array(self, cassiopeia_data) -> None:
        """Level 20 (the cap): base 128 + 120 + 65 = 313 — checks the
        40-entry per-level array past the 18-entry pre-summed attribute."""
        abilities = _parse(cassiopeia_data, ALL_MAXED, level=20)
        assert abilities["E"]["total_raw"] == pytest.approx(313.0)

    def test_e_unpoisoned_level20(self, cassiopeia_data) -> None:
        """Level 20 unpoisoned: 128 + 10 = 138."""
        abilities = _parse(
            cassiopeia_data,
            ALL_MAXED,
            level=20,
            options={"target_poisoned": False},
        )
        assert abilities["E"]["total_raw"] == pytest.approx(138.0)

    def test_e_level1_rank1(self, cassiopeia_data) -> None:
        """Level 1: base 52; poisoned rank 1 adds 20 + 55% AP -> 137;
        unpoisoned 52 + 10 = 62."""
        ranks = {"Q": 0, "W": 0, "E": 1, "R": 0}
        poisoned = _parse(cassiopeia_data, ranks, level=1)
        unpoisoned = _parse(
            cassiopeia_data, ranks, level=1, options={"target_poisoned": False}
        )
        assert poisoned["E"]["total_raw"] == pytest.approx(137.0)
        assert unpoisoned["E"]["total_raw"] == pytest.approx(62.0)

    def test_e_cooldown_flat(self, cassiopeia_data) -> None:
        """0.75s at every rank — the fight engine derives cast count."""
        r1 = _parse(cassiopeia_data, {"Q": 0, "W": 0, "E": 1, "R": 0})
        r5 = _parse(cassiopeia_data, ALL_MAXED)
        assert r1["E"]["cooldown"] == pytest.approx(0.75)
        assert r5["E"]["cooldown"] == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# R: Petrifying Gaze
# ---------------------------------------------------------------------------


class TestRPetrifyingGaze:
    """R: simple cone nuke; CC facing condition never changes damage."""

    def test_r_is_magic(self, cassiopeia_data) -> None:
        abilities = _parse(cassiopeia_data, ALL_MAXED)
        assert abilities["R"]["damage_type"] == "magic"

    def test_r_rank3_total(self, cassiopeia_data) -> None:
        """350 + 50% x 100 AP = 400."""
        abilities = _parse(cassiopeia_data, ALL_MAXED)
        assert abilities["R"]["total_raw"] == pytest.approx(400.0)

    def test_r_rank1_total(self, cassiopeia_data) -> None:
        """150 + 50 = 200."""
        abilities = _parse(cassiopeia_data, {"Q": 0, "W": 0, "E": 0, "R": 1})
        assert abilities["R"]["total_raw"] == pytest.approx(200.0)

    def test_r_cooldown(self, cassiopeia_data) -> None:
        """120/100/80."""
        r1 = _parse(cassiopeia_data, {"Q": 0, "W": 0, "E": 0, "R": 1})
        r3 = _parse(cassiopeia_data, ALL_MAXED)
        assert r1["R"]["cooldown"] == pytest.approx(120.0)
        assert r3["R"]["cooldown"] == pytest.approx(80.0)


# ---------------------------------------------------------------------------
# Fight integration: 100 MR halves everything
# ---------------------------------------------------------------------------


class TestFightIntegration:
    """One-rotation vs 100 MR (no pen): every raw value is halved."""

    def test_rotation_vs_100_mr(self, cassiopeia_data, attacker_stats, fight) -> None:
        stats = attacker_stats(ability_power=100.0, ability_haste=0.0)
        abilities = _parse(cassiopeia_data, ALL_MAXED)
        result = fight(
            stats,
            abilities,
            target_health=10000.0,
            target_magic_resistance=100.0,
        )
        breakdown = result["breakdown"]
        assert breakdown["Q"]["total_damage"] == pytest.approx(140.0)
        assert breakdown["W"]["total_damage"] == pytest.approx(125.0)
        assert breakdown["E"]["total_damage"] == pytest.approx(152.5)
        assert breakdown["R"]["total_damage"] == pytest.approx(200.0)


# ---------------------------------------------------------------------------
# Cast times: stamped from the wiki JSON, honored on the shared timeline
# ---------------------------------------------------------------------------


class TestCastTimes:
    """Her E-spam is bounded by cast time + cooldown on one shared
    timeline — the old cd-only count showed 5 E casts in 3s vs ~3
    in-game."""

    def test_entries_carry_wiki_cast_times(self, cassiopeia_data) -> None:
        abilities = _parse(cassiopeia_data, ALL_MAXED)
        assert abilities["Q"]["cast_time"] == pytest.approx(0.25)
        assert abilities["W"]["cast_time"] == pytest.approx(0.25)
        assert abilities["E"]["cast_time"] == pytest.approx(0.125)
        assert abilities["R"]["cast_time"] == pytest.approx(0.5)

    def test_three_second_fight_fits_three_twin_fangs(
        self, cassiopeia_data, attacker_stats, fight
    ) -> None:
        """Q(0.25) W(0.25) E(0.125) R(0.5) fill the first ~1.1s; E then
        cycles every 0.875s (0.75 cd from cast end + 0.125 cast): starts
        at 0.5/1.375/2.25 -> 3 casts, matching in-game."""
        abilities = _parse(cassiopeia_data, ALL_MAXED)
        stats = attacker_stats(ability_power=100.0)
        result = fight(stats, abilities, one_rotation=False, fight_duration_seconds=3.0)
        breakdown = result["breakdown"]
        assert breakdown["E"]["casts"] == 3
        assert breakdown["Q"]["casts"] == 1
        assert breakdown["W"]["casts"] == 1
        assert breakdown["R"]["casts"] == 1


# ---------------------------------------------------------------------------
# Poison DoT tail: item burns stay refreshed while the poison ticks
# ---------------------------------------------------------------------------


class TestPoisonBurnInteraction:
    """Q/W poison ticks are ability damage past the cast instant, so item
    burns (Liandry's, Blackfire) stay refreshed for the DoT tail after the
    last cast — same mechanism as Brand's Blaze (``dot_duration``).
    """

    def test_q_and_w_declare_dot_tails(self, cassiopeia_data) -> None:
        """Q poisons for 3s; W ticks for its full 5s zone duration."""
        abilities = _parse(cassiopeia_data, ALL_MAXED)
        assert abilities["Q"]["dot_duration"] == pytest.approx(3.0)
        assert abilities["W"]["dot_duration"] == pytest.approx(5.0)

    def test_poison_tail_extends_liandrys_window(
        self, cassiopeia_data, attacker_stats, fight, liandrys
    ) -> None:
        abilities = _parse(cassiopeia_data, ALL_MAXED)
        stats = attacker_stats(ability_power=100.0, is_melee=False)
        with_tail = fight(stats, abilities, items=[liandrys])

        no_tail = {k: dict(v) for k, v in abilities.items()}
        no_tail["Q"].pop("dot_duration")
        no_tail["W"].pop("dot_duration")
        without = fight(stats, no_tail, items=[liandrys])

        burn_key = next(k for k in with_tail["breakdown"] if k.startswith("burn_"))
        with_burn = with_tail["breakdown"][burn_key]["total_damage"]
        without_burn = without["breakdown"][burn_key]["total_damage"]

        # Q/W/E/R = 4 casts -> 1.5s spread; W's 5s zone is the longest
        # tail: the burn window grows from (1.5 + 3) to (1.5 + 5 + 3) s.
        assert with_burn / without_burn == pytest.approx(9.5 / 4.5)


# ---------------------------------------------------------------------------
# Passive / skill order / options metadata
# ---------------------------------------------------------------------------


class TestPassiveAndMeta:
    """P (Serpentine Grace) is movement-speed only — absent from results."""

    def test_passive_not_in_results(self, cassiopeia_data, parse_at) -> None:
        _, abilities = parse_at(cassiopeia_data, 9)
        assert "passive" not in abilities
        assert "P" not in abilities

    def test_slot_keys(self, cassiopeia_data) -> None:
        abilities = _parse(cassiopeia_data, ALL_MAXED)
        assert set(abilities) == {"Q", "W", "E", "R"}

    def test_skill_order_maxes_e_first(self) -> None:
        """Cassiopeia maxes E > Q > W: E rank 5 by level 9, W last."""
        assert get_ability_rank("E", 9, "Cassiopeia") == 5
        assert get_ability_rank("Q", 13, "Cassiopeia") == 5
        assert get_ability_rank("W", 13, "Cassiopeia") == 1

    def test_options_meta(self) -> None:
        meta = get_champion_options_meta("Cassiopeia")
        keys = {opt["key"] for opt in meta["options"]}
        assert keys == {"target_poisoned"}
        (opt,) = meta["options"]
        assert opt["type"] == "bool"
        assert opt["default"] is True
        assert meta["assumptions"]
