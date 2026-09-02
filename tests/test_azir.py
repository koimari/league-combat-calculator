"""Tests for Azir champion module.

Hand-validated against the wiki (see /add-champion spec):
- Soldier attack, level 11 / W rank 5 / 100 AP: 72*10/17 + 110 + 65 = ~217.4
- Soldier attack, level 6 / W rank 3 / 100 AP: 21.18 + 80 + 50 = ~151.2
- Q rank 5 / 100 AP: 195; E rank 5 / 100 AP: 290; R rank 3 / 100 AP: 675
"""

import pytest

from src.calculator.champions import azir
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.data_fetcher import get_item_by_name
from tests import cc_review


def _auto_fight(stats, abilities, items=None, **overrides):
    """Deterministic autos-only fight against a 100/100 resist target."""
    config = {
        "target_health": 5000.0,
        "target_armor": 100.0,
        "target_magic_resistance": 100.0,
        "fight_duration_seconds": 5.0,
        "auto_attack_uptime": 1.0,
        "auto_attacks_only": True,
        "deterministic": True,
    }
    config.update(overrides)
    return calculate_fight_damage(stats, abilities, items or [], FightConfig(**config))


class TestPassiveSkipped:
    """P (Shurima's Legacy) is out of scope: separate turret entity."""

    def test_passive_absent(self, azir_data, parse_at) -> None:
        _, abilities = parse_at(azir_data, 18, ap=100.0)
        assert "passive" not in abilities


class TestQConqueringSands:
    """Q: one magic instance per cast, regardless of soldier count."""

    def test_q_is_magic(self, azir_data, parse_at) -> None:
        _, abilities = parse_at(azir_data, 5)
        assert abilities["Q"]["damage_type"] == "magic"

    def test_q_rank5_100ap(self, azir_data, parse_at) -> None:
        """Q rank 5 with 100 AP: 155 + 55% * 100 = 210."""
        _, abilities = parse_at(
            azir_data, 18, ap=100.0, ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3}
        )
        assert abilities["Q"]["total_raw"] == pytest.approx(210.0)

    def test_q_cooldown_rank5(self, azir_data, parse_at) -> None:
        _, abilities = parse_at(
            azir_data, 18, ap=100.0, ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3}
        )
        assert abilities["Q"]["cooldown"] == pytest.approx(6.0)

    def test_q_not_multiplied_by_soldier_count(self, azir_data, parse_at) -> None:
        """In-game rule: multiple soldiers hitting one target deal one Q
        instance. soldier_count must never scale Q."""
        _, one = parse_at(
            azir_data, 11, ap=100.0, champion_options={"soldier_count": 1}
        )
        _, three = parse_at(
            azir_data, 11, ap=100.0, champion_options={"soldier_count": 3}
        )
        assert three["Q"]["total_raw"] == one["Q"]["total_raw"]


class TestWArise:
    """W: Sand Soldier attacks replace Azir's autos via auto_attack_override."""

    def test_w_entry_is_zero_direct_damage(self, azir_data, parse_at) -> None:
        """All soldier damage rides the auto stream — never a cast row too."""
        _, abilities = parse_at(azir_data, 11, ap=100.0)
        assert abilities["W"]["total_raw"] == 0.0
        assert abilities["W"]["parts"] == ()

    def test_w_uses_recharge_rate_as_cooldown(self, azir_data, parse_at) -> None:
        """Charge ability: rechargeRate (12->6), not the 1.5s inter-cast CD."""
        _, abilities = parse_at(azir_data, 11, ap=100.0)  # W rank 5
        assert abilities["W"]["cooldown"] == pytest.approx(6.0)
        _, abilities = parse_at(azir_data, 1, ap=0.0)  # W rank 1
        assert abilities["W"]["cooldown"] == pytest.approx(12.0)

    def test_soldier_damage_level11_rank5(self, azir_data, parse_at) -> None:
        """Level 11, W rank 5, 100 AP: 72*10/17 + 110 + 65% * 100 = ~217.4."""
        _, abilities = parse_at(azir_data, 11, ap=100.0)
        assert abilities["W"]["rank"] == 5  # W-max skill order
        override = abilities["W"]["auto_attack_override"]
        assert override["replace_raw"] == pytest.approx(217.35, abs=0.01)
        assert override["damage_type"] == "magic"

    def test_soldier_damage_level6_rank3(self, azir_data, parse_at) -> None:
        """Level 6, W rank 3, 100 AP: 72*5/17 + 80 + 50% * 100 = ~151.2."""
        _, abilities = parse_at(azir_data, 6, ap=100.0)
        assert abilities["W"]["rank"] == 3
        override = abilities["W"]["auto_attack_override"]
        assert override["replace_raw"] == pytest.approx(151.18, abs=0.01)

    def test_soldier_on_hit_effectiveness_declared(self, azir_data, parse_at) -> None:
        _, abilities = parse_at(azir_data, 11, ap=100.0)
        override = abilities["W"]["auto_attack_override"]
        assert override["on_hit_effectiveness"] == pytest.approx(0.5)

    def test_three_soldiers_multiply_by_1_5(self, azir_data, parse_at) -> None:
        """N soldiers: full damage * (1 + 0.25 * (N - 1))."""
        _, one = parse_at(
            azir_data, 11, ap=100.0, champion_options={"soldier_count": 1}
        )
        _, three = parse_at(
            azir_data, 11, ap=100.0, champion_options={"soldier_count": 3}
        )
        assert three["W"]["auto_attack_override"]["replace_raw"] == pytest.approx(
            1.5 * one["W"]["auto_attack_override"]["replace_raw"]
        )

    def test_soldier_autos_off_drops_w(self, azir_data, parse_at) -> None:
        _, abilities = parse_at(
            azir_data, 11, ap=100.0, champion_options={"soldier_autos": False}
        )
        assert "W" not in abilities

    def test_no_attack_speed_buff(self, azir_data, parse_at) -> None:
        """The old W attack-speed steroid was removed in V13.5."""
        _, abilities = parse_at(azir_data, 11, ap=100.0)
        assert "stat_buff" not in abilities["W"]


class TestEShiftingSands:
    """E: one damage row from the Magic Damage attribute (shield skipped)."""

    def test_e_is_magic(self, azir_data, parse_at) -> None:
        _, abilities = parse_at(azir_data, 5)
        assert abilities["E"]["damage_type"] == "magic"

    def test_e_rank5_100ap(self, azir_data, parse_at) -> None:
        """E rank 5 with 100 AP: 230 + 60% * 100 = 290."""
        _, abilities = parse_at(
            azir_data, 18, ap=100.0, ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3}
        )
        assert abilities["E"]["total_raw"] == pytest.approx(290.0)
        assert abilities["E"]["cooldown"] == pytest.approx(16.0)

    def test_e_single_damage_part(self, azir_data, parse_at) -> None:
        """The identical Shield Strength values must not double the row."""
        _, abilities = parse_at(azir_data, 18, ap=100.0)
        assert len(abilities["E"]["parts"]) == 1


class TestREmperorsDivide:
    """R: magic damage; geometry rows ("Width" in soldiers) never parse."""

    def test_r_is_magic(self, azir_data, parse_at) -> None:
        _, abilities = parse_at(azir_data, 6)
        assert abilities["R"]["damage_type"] == "magic"

    def test_r_rank3_100ap(self, azir_data, parse_at) -> None:
        """R rank 3 with 100 AP: 600 + 75% * 100 = 675."""
        _, abilities = parse_at(
            azir_data, 18, ap=100.0, ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3}
        )
        assert abilities["R"]["total_raw"] == pytest.approx(675.0)
        assert abilities["R"]["cooldown"] == pytest.approx(90.0)

    def test_r_rank1_geometry_not_damage(self, azir_data, parse_at) -> None:
        """R rank 1 at 0 AP is exactly 200 — not 6/620/750 geometry values."""
        _, abilities = parse_at(azir_data, 6, ap=0.0)
        assert abilities["R"]["total_raw"] == pytest.approx(200.0)


class TestFightEngineIntegration:
    """Soldier autos through the fight engine: replacement, no crit,
    halved on-hit items, normal physical autos when toggled off."""

    def test_soldier_autos_are_magic_and_mitigated_by_mr(
        self, azir_data, parse_at
    ) -> None:
        """217.35 raw vs 100 MR -> ~108.7 per attack; row renamed."""
        stats, abilities = parse_at(azir_data, 11, ap=100.0)
        result = _auto_fight(stats, abilities)
        auto = result["breakdown"]["auto_attacks"]
        assert auto["name"] == "Sand Soldier Attacks"
        assert auto["damage_type"] == "magic"
        assert auto["damage_per_hit"] == pytest.approx(217.35 * 0.5, abs=0.1)

    def test_soldier_autos_cannot_crit(self, azir_data, parse_at) -> None:
        """100% crit chance changes nothing on soldier attacks."""
        stats, abilities = parse_at(azir_data, 11, ap=100.0)
        no_crit = _auto_fight(dict(stats), abilities)
        stats["critical_strike_chance"] = 100.0
        full_crit = _auto_fight(stats, abilities)
        assert full_crit["breakdown"]["auto_attacks"][
            "damage_per_hit"
        ] == pytest.approx(no_crit["breakdown"]["auto_attacks"]["damage_per_hit"])

    def test_on_hit_items_halved(self, azir_data, parse_at) -> None:
        """Nashor's on-hit deals exactly half with soldier autos on vs off."""
        nashors = get_item_by_name("Nashor's Tooth")
        stats, soldier_abilities = parse_at(azir_data, 11, ap=100.0)
        _, normal_abilities = parse_at(
            azir_data, 11, ap=100.0, champion_options={"soldier_autos": False}
        )
        with_soldiers = _auto_fight(dict(stats), soldier_abilities, [nashors])
        without = _auto_fight(dict(stats), normal_abilities, [nashors])

        def nashors_total(result):
            for entry in result["breakdown"].values():
                if "Nashor" in entry.get("name", ""):
                    return entry["total_damage"]
            raise AssertionError("Nashor's on-hit row missing from breakdown")

        assert nashors_total(with_soldiers) == pytest.approx(
            0.5 * nashors_total(without)
        )

    def test_extra_soldiers_do_not_add_on_hit(self, azir_data, parse_at) -> None:
        """soldier_count=3 scales soldier damage 1.5x but on-hit items still
        apply once at 50% — identical on-hit totals for 1 vs 3 soldiers."""
        nashors = get_item_by_name("Nashor's Tooth")
        stats, one = parse_at(
            azir_data, 11, ap=100.0, champion_options={"soldier_count": 1}
        )
        _, three = parse_at(
            azir_data, 11, ap=100.0, champion_options={"soldier_count": 3}
        )
        result_one = _auto_fight(dict(stats), one, [nashors])
        result_three = _auto_fight(dict(stats), three, [nashors])

        autos_one = result_one["breakdown"]["auto_attacks"]
        autos_three = result_three["breakdown"]["auto_attacks"]
        assert autos_three["damage_per_hit"] == pytest.approx(
            1.5 * autos_one["damage_per_hit"]
        )

        def nashors_total(result):
            for entry in result["breakdown"].values():
                if "Nashor" in entry.get("name", ""):
                    return entry["total_damage"]
            raise AssertionError("Nashor's on-hit row missing from breakdown")

        assert nashors_total(result_three) == pytest.approx(nashors_total(result_one))

    def test_soldier_autos_off_normal_physical(self, azir_data, parse_at) -> None:
        """soldier_autos off: plain physical autos at Azir's AD, normal crit."""
        stats, abilities = parse_at(
            azir_data, 11, ap=100.0, champion_options={"soldier_autos": False}
        )
        result = _auto_fight(dict(stats), abilities)
        auto = result["breakdown"]["auto_attacks"]
        assert auto["name"] == "Auto Attacks"
        assert auto["damage_type"] == "physical"
        # AD mitigated by 100 armor (deterministic, 0% crit) -> AD * 0.5
        assert auto["damage_per_hit"] == pytest.approx(
            stats["attack_damage"] * 0.5, rel=0.001
        )
        # Crits work normally: 100% crit doubles the per-hit damage.
        stats["critical_strike_chance"] = 100.0
        crit_result = _auto_fight(stats, abilities)
        assert crit_result["breakdown"]["auto_attacks"][
            "damage_per_hit"
        ] == pytest.approx(2.0 * auto["damage_per_hit"], rel=0.001)

    def test_w_cast_row_adds_no_damage(self, azir_data, parse_at) -> None:
        """The W breakdown row exists but contributes zero (no double count)."""
        stats, abilities = parse_at(azir_data, 11, ap=100.0)
        result = calculate_fight_damage(
            stats,
            abilities,
            [],
            FightConfig(
                target_health=5000.0,
                target_armor=100.0,
                target_magic_resistance=100.0,
                fight_duration_seconds=5.0,
                auto_attack_uptime=1.0,
                deterministic=True,
            ),
        )
        assert result["breakdown"]["W"]["total_damage"] == 0.0


class TestProcItemEffects:
    """Game-verified soldier interactions with proc-style items: spellblade,
    energized, and stack-counter procs apply at 50%; Sundered Sky never."""

    @staticmethod
    def _row_total(result, name_fragment):
        for entry in result["breakdown"].values():
            if name_fragment in entry.get("name", ""):
                return entry
        return None

    def test_lich_bane_spellblade_halved(self, azir_data, parse_at) -> None:
        """Spellblade procs on soldier attacks at 50% damage per proc."""
        lich_bane = get_item_by_name("Lich Bane")
        stats, soldier_abilities = parse_at(azir_data, 11, ap=100.0)
        _, normal_abilities = parse_at(
            azir_data, 11, ap=100.0, champion_options={"soldier_autos": False}
        )
        config = {"auto_attacks_only": False}  # spellblade needs ability casts
        with_soldiers = _auto_fight(
            dict(stats), soldier_abilities, [lich_bane], **config
        )
        without = _auto_fight(dict(stats), normal_abilities, [lich_bane], **config)

        row_on = self._row_total(with_soldiers, "Lich Bane")
        row_off = self._row_total(without, "Lich Bane")
        assert row_on is not None
        assert row_on["count"] > 0
        assert row_on["damage_per_hit"] == pytest.approx(
            0.5 * row_off["damage_per_hit"]
        )

    def test_energized_shiv_consumed_and_halved(self, azir_data, parse_at) -> None:
        """Energized (Statikk Shiv) is consumed by soldier attacks at 50%."""
        shiv = get_item_by_name("Statikk Shiv")
        stats, soldier_abilities = parse_at(azir_data, 11, ap=100.0)
        _, normal_abilities = parse_at(
            azir_data, 11, ap=100.0, champion_options={"soldier_autos": False}
        )
        with_soldiers = _auto_fight(dict(stats), soldier_abilities, [shiv])
        without = _auto_fight(dict(stats), normal_abilities, [shiv])

        row_on = self._row_total(with_soldiers, "Statikk Shiv")
        row_off = self._row_total(without, "Statikk Shiv")
        assert row_on is not None
        assert row_on["count"] == row_off["count"]
        assert row_on["total_damage"] == pytest.approx(0.5 * row_off["total_damage"])

    def test_kraken_third_attack_proc_halved(self, azir_data, parse_at) -> None:
        """Kraken procs every 3rd soldier attack with proc damage halved.

        Huge target HP keeps the missing-HP bonus ~0 so the runs compare
        cleanly despite different auto damage trajectories.
        """
        kraken = get_item_by_name("Kraken Slayer")
        stats, soldier_abilities = parse_at(azir_data, 11, ap=100.0)
        _, normal_abilities = parse_at(
            azir_data, 11, ap=100.0, champion_options={"soldier_autos": False}
        )
        config = {"target_health": 100000.0, "fight_duration_seconds": 10.0}
        with_soldiers = _auto_fight(dict(stats), soldier_abilities, [kraken], **config)
        without = _auto_fight(dict(stats), normal_abilities, [kraken], **config)

        row_on = self._row_total(with_soldiers, "Kraken")
        row_off = self._row_total(without, "Kraken")
        assert row_on is not None
        assert row_on["count"] > 0
        assert row_on["count"] == row_off["count"]
        assert row_on["total_damage"] == pytest.approx(
            0.5 * row_off["total_damage"], rel=0.01
        )

    def test_sundered_sky_not_applied(self, azir_data, parse_at) -> None:
        """Sundered Sky is not consumed by soldier attacks at all: no
        breakdown row and zero damage contribution."""
        sundered = get_item_by_name("Sundered Sky")
        stats, soldier_abilities = parse_at(azir_data, 11, ap=100.0)
        with_item = _auto_fight(dict(stats), soldier_abilities, [sundered])
        without_item = _auto_fight(dict(stats), soldier_abilities, [])

        assert "sundered_sky" not in with_item["breakdown"]
        assert with_item["breakdown"]["auto_attacks"]["total_damage"] == pytest.approx(
            without_item["breakdown"]["auto_attacks"]["total_damage"]
        )

        # Sanity: with normal autos the item still registers its row.
        _, normal_abilities = parse_at(
            azir_data, 11, ap=100.0, champion_options={"soldier_autos": False}
        )
        normal = _auto_fight(dict(stats), normal_abilities, [sundered])
        assert "sundered_sky" in normal["breakdown"]


class TestBaseStats:
    """Azir's auto baseline when soldiers are off (spec: 56 + 3.5 growth)."""

    def test_base_ad_level1(self, azir_data, parse_at) -> None:
        stats, _ = parse_at(azir_data, 1)
        assert stats["attack_damage"] == pytest.approx(56.0)


class TestReviewedCrowdControl:
    """Azir's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Azir")
        assert azir.MODULE_CC == {
            "Q": "slow",
            "E": "none",
            "R": "knockback",
            "W": "none",
        }
        assert "slowing them by 25%" in " ".join(cc_review.slot_text(data, "Q").split())
        assert "knocked away over 1 second" in " ".join(
            cc_review.slot_text(data, "R").split()
        )
        assert cc_review.control_words(cc_review.slot_text(data, "E")) == []

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Azir") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Azir")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
