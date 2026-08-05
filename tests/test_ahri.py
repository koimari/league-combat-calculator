"""Tests for the Ahri champion module.

Hand-derived ability values at specific AP breakpoints (values re-derived from
the 16.13.1 JSON), plus an Ahri fight-level check of the Actualizer ability amp
(the accessor itself is unit-tested in test_item_effects.py).
"""

import pytest

from src.calculator.ability_spec import parts_raw_total

from src.calculator.damage import FightConfig, calculate_fight_damage


class TestParseAhriAbilities:
    """Tests for Ahri ability parsing with specific AP values.

    The ahri_data fixture comes from tests/conftest.py.
    """

    def test_q_rank3_with_60ap(self, ahri_data: dict, parse_at) -> None:
        # JSON (16.13.1): Q "Damage Per Pass" rank 3 = 85 + 50% AP.
        # 85 + 0.5 * 60 = 115 for both the magic and true damage passes.
        _, abilities = parse_at(ahri_data, 6, ap=60)
        q = abilities["Q"]
        assert q["rank"] == 3
        assert abs(parts_raw_total(q["parts"], "magic") - 115.0) < 0.1
        assert abs(parts_raw_total(q["parts"], "true") - 115.0) < 0.1

    def test_w_rank1_with_60ap(self, ahri_data: dict, parse_at) -> None:
        _, abilities = parse_at(ahri_data, 6, ap=60)
        w = abilities["W"]
        assert w["rank"] == 1
        initial, subsequent = w["parts"]
        assert abs(initial.amount - 64.0) < 0.1
        assert abs(subsequent.amount - 25.6) < 0.1
        assert subsequent.count == 2

    def test_e_rank1_with_60ap(self, ahri_data: dict, parse_at) -> None:
        _, abilities = parse_at(ahri_data, 6, ap=60)
        e = abilities["E"]
        assert abs(parts_raw_total(e["parts"], "magic") - 131.0) < 0.1
        assert e["parts"][0].cc_kind == "immobilize"
        assert e["event_order_certified"] == "single_hit"

    def test_r_rank1_with_60ap(self, ahri_data: dict, parse_at) -> None:
        _, abilities = parse_at(ahri_data, 6, ap=60)
        r = abilities["R"]
        (dashes,) = r["parts"]
        assert abs(dashes.amount - 96.0) < 0.1
        assert dashes.count == 3
        assert r["cast_instances"] == 3
        assert "cooldown" not in r

    def test_q_rank5_with_215ap(self, ahri_data: dict, parse_at) -> None:
        # JSON (16.13.1): Q "Damage Per Pass" rank 5 = 135 + 50% AP.
        # 135 + 0.5 * 215 = 242.5.
        _, abilities = parse_at(ahri_data, 11, ap=215)
        q = abilities["Q"]
        assert q["rank"] == 5
        assert abs(parts_raw_total(q["parts"], "magic") - 242.5) < 0.1

    def test_w_rank5_with_572ap(self, ahri_data: dict, parse_at) -> None:
        _, abilities = parse_at(ahri_data, 18, ap=572)
        w = abilities["W"]
        assert w["rank"] == 5
        assert abs(w["parts"][0].amount - 348.8) < 0.1

    def test_e_rank5_with_572ap(self, ahri_data: dict, parse_at) -> None:
        _, abilities = parse_at(ahri_data, 18, ap=572)
        e = abilities["E"]
        assert abs(parts_raw_total(e["parts"], "magic") - 726.2) < 0.1

    def test_r_rank3_with_572ap(self, ahri_data: dict, parse_at) -> None:
        _, abilities = parse_at(ahri_data, 18, ap=572)
        r = abilities["R"]
        assert abs(r["parts"][0].amount - 375.2) < 0.1


class TestActualizerFightDamage:
    """Test Actualizer Q damage in a full fight calculation."""

    @pytest.fixture
    def actualizer(self) -> dict:
        from src.calculator.data_fetcher import get_item_by_name

        return get_item_by_name("Actualizer")

    def test_ahri_q_with_actualizer_active(
        self,
        ahri_data: dict,
        actualizer: dict,
        parse_at,
    ) -> None:
        """Ahri level 18, only Actualizer, Q vs 1000 HP / 100 MR / 100 Armor.

        JSON (16.13.1): Q rank 5 per pass = 135 + 0.5 * 90 AP = 180.
        Magic pass vs 100 MR = 90; true pass = 180; sum = 270.
        Actualizer amp = 1.15 + 0.005 * (300 bonus mana / 100) = 1.165.
        270 * 1.165 = 314.55 total Q damage.
        """
        items = [actualizer]
        stats, abilities = parse_at(
            ahri_data,
            18,
            items=items,
            ability_ranks={"Q": 5},
        )
        fight = calculate_fight_damage(
            stats,
            abilities,
            items,
            FightConfig(
                target_health=1000,
                target_armor=100,
                target_magic_resistance=100,
                fight_duration_seconds=1.0,
                auto_attack_uptime=0.0,
                one_rotation=True,
                include_actives=True,
            ),
        )
        q_damage = fight["breakdown"]["Q"]["total_damage"]
        assert abs(q_damage - 314.55) <= 2, f"Q damage {q_damage:.1f} expected ~314.55"
