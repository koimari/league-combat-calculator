"""Ziggs module tests — hand-validated against the LoL wiki.

Sanity anchors (magic damage, pre-mitigation, 500 AP, all ranks maxed):
- Q rank 5: 280 + 80% AP                      = 680
- W rank 5: 210 + 50% AP                      = 460
- E rank 5, 4 mines: (190 + 45% AP) + 3 x (76 + 18% AP)
                     = 415 + 3 x 166          = 913
- E rank 5, 11 mines: 415 + 10 x 166 = 2075 — exactly the cap row
  (950 + 225% AP = 2075); the cap row IS 1 full + 10 reduced mines.
- R rank 3: epicenter 700 + 100% AP = 1200; outer ring 455 + 65% AP = 780
- Short Fuse per proc, level 18: 160 base + 50% AP (hardcoded) = 410
"""

import pytest

from src.calculator.champions.slotlib import extract_named

TARGET = {"target_max_health": 3000.0}


class TestZiggsAbilities:
    """Direct ability reads at fixed ranks (level 18 = all maxed)."""

    def test_q_rank5_damage(self, ziggs_data, parse_at):
        _, abilities = parse_at(ziggs_data, 18, ap=500.0, target_stats=TARGET)
        assert abilities["Q"]["damage_type"] == "magic"
        assert abilities["Q"]["total_raw"] == pytest.approx(680.0)

    def test_w_rank5_damage(self, ziggs_data, parse_at):
        """W reads only 'Magic Damage' — the turret-only 'Demolition
        Threshold' row must never leak into champion damage."""
        _, abilities = parse_at(ziggs_data, 18, ap=500.0, target_stats=TARGET)
        assert abilities["W"]["damage_type"] == "magic"
        assert abilities["W"]["total_raw"] == pytest.approx(460.0)

    def test_e_rank5_default_mines(self, ziggs_data, parse_at):
        """Default 4 mines: 1 full (415) + 3 reduced (166 each) = 913."""
        _, abilities = parse_at(ziggs_data, 18, ap=500.0, target_stats=TARGET)
        assert abilities["E"]["damage_type"] == "magic"
        assert abilities["E"]["total_raw"] == pytest.approx(913.0)

    def test_r_rank3_default_epicenter(self, ziggs_data, parse_at):
        _, abilities = parse_at(ziggs_data, 18, ap=500.0, target_stats=TARGET)
        assert abilities["R"]["damage_type"] == "magic"
        assert abilities["R"]["total_raw"] == pytest.approx(1200.0)

    def test_cooldowns_present(self, ziggs_data, parse_at):
        _, abilities = parse_at(ziggs_data, 18, ap=500.0, target_stats=TARGET)
        assert abilities["Q"]["cooldown"] == pytest.approx(4.0)
        assert abilities["W"]["cooldown"] == pytest.approx(12.0)
        assert abilities["E"]["cooldown"] == pytest.approx(16.0)
        assert abilities["R"]["cooldown"] == pytest.approx(70.0)


class TestEMinesOption:
    """mines_hit: 1 full mine + (N-1) reduced, clamped at the cap row."""

    def test_single_mine(self, ziggs_data, parse_at):
        _, abilities = parse_at(
            ziggs_data,
            18,
            ap=500.0,
            target_stats=TARGET,
            champion_options={"mines_hit": 1},
        )
        assert abilities["E"]["total_raw"] == pytest.approx(415.0)

    def test_eleven_mines_hits_cap_exactly(self, ziggs_data, parse_at):
        """11 mines uncapped (415 + 10 x 166 = 2075) equals the cap row —
        the cap must clamp, and the result must equal the JSON's
        'Maximum Total Magic Damage' extracted independently."""
        stats, abilities = parse_at(
            ziggs_data,
            18,
            ap=500.0,
            target_stats=TARGET,
            champion_options={"mines_hit": 11},
        )
        cap = extract_named(
            ziggs_data["abilities"]["E"][0],
            "Maximum Total Magic Damage",
            5,
            {**stats, "ability_power": 500.0},
            TARGET,
        )
        assert cap == pytest.approx(2075.0)
        assert abilities["E"]["total_raw"] == pytest.approx(cap)

    def test_cap_clamps_above_eleven_mines(self, ziggs_data, parse_at):
        """Beyond the UI's max the clamp genuinely binds: 12 mines
        uncapped would be 2241, but the cap holds it at 2075."""
        _, abilities = parse_at(
            ziggs_data,
            18,
            ap=500.0,
            target_stats=TARGET,
            champion_options={"mines_hit": 12},
        )
        assert abilities["E"]["total_raw"] == pytest.approx(2075.0)


class TestRSweetSpotOption:
    """r_sweet_spot toggles epicenter vs outer-ring values."""

    def test_sweet_spot_on(self, ziggs_data, parse_at):
        _, abilities = parse_at(
            ziggs_data,
            18,
            ap=500.0,
            target_stats=TARGET,
            champion_options={"r_sweet_spot": True},
        )
        assert abilities["R"]["total_raw"] == pytest.approx(1200.0)

    def test_sweet_spot_off(self, ziggs_data, parse_at):
        _, abilities = parse_at(
            ziggs_data,
            18,
            ap=500.0,
            target_stats=TARGET,
            champion_options={"r_sweet_spot": False},
        )
        assert abilities["R"]["total_raw"] == pytest.approx(780.0)
        assert abilities["R"]["damage_type"] == "magic"


class TestShortFusePassive:
    """Short Fuse: per-level base from JSON + hardcoded 50% AP ratio,
    proc count from the passive_procs option (default 2)."""

    def test_default_two_procs(self, ziggs_data, parse_at):
        """Level 18: (160 + 250) per proc x 2 procs = 820."""
        _, abilities = parse_at(ziggs_data, 18, ap=500.0, target_stats=TARGET)
        passive = abilities["passive"]
        assert passive["damage_type"] == "magic"
        assert passive["proc_count"] == 2
        assert passive["total_raw"] == pytest.approx(820.0)

    def test_zero_procs_omits_passive(self, ziggs_data, parse_at):
        _, abilities = parse_at(
            ziggs_data,
            18,
            ap=500.0,
            target_stats=TARGET,
            champion_options={"passive_procs": 0},
        )
        assert "passive" not in abilities

    def test_five_procs(self, ziggs_data, parse_at):
        _, abilities = parse_at(
            ziggs_data,
            18,
            ap=500.0,
            target_stats=TARGET,
            champion_options={"passive_procs": 5},
        )
        assert abilities["passive"]["proc_count"] == 5
        assert abilities["passive"]["total_raw"] == pytest.approx(5 * 410.0)

    def test_hardcoded_ap_ratio_is_half(self, ziggs_data, parse_at):
        """The JSON leveling carries no AP modifier — the module's
        hardcoded 0.5 ratio must add exactly 250 per proc at 500 AP."""
        _, at_zero = parse_at(ziggs_data, 18, ap=0.0, target_stats=TARGET)
        _, at_500 = parse_at(ziggs_data, 18, ap=500.0, target_stats=TARGET)
        per_proc_zero = at_zero["passive"]["parts"][0].amount
        per_proc_500 = at_500["passive"]["parts"][0].amount
        assert per_proc_zero == pytest.approx(160.0)  # pure per-level base
        assert per_proc_500 - per_proc_zero == pytest.approx(250.0)

    def test_base_scales_per_level(self, ziggs_data, parse_at):
        """Level 1 base is 20 (wiki range 20-184 by level)."""
        _, abilities = parse_at(ziggs_data, 1, ap=0.0, target_stats=TARGET)
        assert abilities["passive"]["parts"][0].amount == pytest.approx(20.0)


class TestZiggsFightIntegration:
    """The proc-counted passive flows through the fight engine."""

    def test_one_rotation_includes_passive_procs(
        self, ziggs_data, parse_at, attacker_stats, fight
    ):
        _, abilities = parse_at(
            ziggs_data,
            18,
            ap=500.0,
            target_stats={"target_max_health": 1000.0},
        )
        stats = attacker_stats(ability_power=500.0, is_melee=False)
        result = fight(stats, abilities)
        passive = result["breakdown"]["passive"]
        assert passive["count"] == 2
        # Raw 410 per proc; 100 MR halves it.
        assert passive["total_damage"] == pytest.approx(410.0)
        assert result["total_damage"] > 0
