"""Mechanics packets — charges/channels, recasts, executes, secondary targets.

Each packet was audited against HANDOVER 8.6/8.7 and the module's existing
assumptions before implementation (a generic path already covered several
listed candidates — see the per-champion audit in the mission reply).  Every
number asserted here traces to a cached ``data/champions.json`` leveling row
or to the cached description prose the module reads with a fail-closed regex
(the Ziggs Short-Fuse precedent).  Default option values reproduce the
pre-existing module numbers exactly, so no existing test moved.
"""

import pytest

from src.calculator.champions import parse_champion_abilities as parse_abilities
from src.calculator.data_fetcher import get_champion

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FULL_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}

TARGET_2000 = {"target_max_health": 2000.0}


def _stats(
    *,
    ad=100.0,
    bonus_ad=0.0,
    ap=0.0,
    health=0.0,
    crit=0.0,
):
    return {
        "armor_penetration_bonus_percent": 0.0,
        "bonus_mana": 0.0,
        "lethality": 0.0,
        "level": 1,
        "max_mana": 0.0,
        "move_speed": 0.0,
        "omnivamp_percent": 0.0,
        "resource_regen_per_second": 0.0,
        "ultimate_haste": 0.0,
        "attack_damage": ad,
        "base_attack_damage": ad - bonus_ad,
        "bonus_attack_damage": bonus_ad,
        "ability_power": ap,
        "health": health,
        "bonus_health": 0.0,
        "critical_strike_chance": crit,
        "attack_speed": 1.0,
        "attack_speed_ratio": 0.625,
        "ability_haste": 0.0,
        "basic_ability_haste": 0.0,
        "armor_penetration_percent": 0.0,
        "flat_armor_penetration": 0.0,
        "magic_penetration_flat": 0.0,
        "magic_penetration_percent": 0.0,
        "is_melee": True,
    }


def _parse(
    champion_key,
    level=18,
    stats=None,
    options=None,
    ranks=None,
    target=None,
):
    """Parse one champion's kit at level 18 with explicit stats/options."""
    return parse_abilities(
        get_champion(champion_key),
        level,
        (stats or {}).get("ability_power", 0.0),
        ability_ranks=ranks if ranks is not None else dict(FULL_RANKS),
        champion_stats=stats or _stats(),
        champion_options=options or {},
        target_stats=target or TARGET_2000,
    )


# ---------------------------------------------------------------------------
# Charges / channel windows
# ---------------------------------------------------------------------------


class TestVarusQCharge:
    """q_charge_fraction interpolates the sourced Minimum/Maximum rows."""

    def test_default_is_fully_charged_maximum_row(self) -> None:
        abilities = _parse("Varus", options={"w_active_empower": False})
        # Rank-5 Q: Maximum 360 (+120% bonus AD, 0 bonus AD) + the 3-stack
        # detonation at the test-locked minimum per-stack row (5% x 2000).
        assert abilities["Q"]["parts"][0].amount == pytest.approx(360.0)
        assert abilities["Q"]["total_raw"] == pytest.approx(360.0 + 300.0)

    def test_zero_charge_prices_the_minimum_row(self) -> None:
        abilities = _parse(
            "Varus",
            options={"q_charge_fraction": 0.0, "w_active_empower": False},
        )
        # Minimum Physical Damage rank 5: 240 (+120% bonus AD).
        assert abilities["Q"]["parts"][0].amount == pytest.approx(240.0)
        assert "charge" in abilities["Q"].get("detail", "")

    def test_half_charge_interpolates_between_the_rows(self) -> None:
        abilities = _parse(
            "Varus",
            options={"q_charge_fraction": 0.5, "w_active_empower": False},
        )
        # 240 + (360 - 240) x 0.5 = 300; detonation unchanged (300).
        assert abilities["Q"]["parts"][0].amount == pytest.approx(300.0)
        assert abilities["Q"]["total_raw"] == pytest.approx(600.0)

    def test_charge_fraction_clamps(self) -> None:
        abilities = _parse(
            "Varus",
            options={"q_charge_fraction": 2.0, "w_active_empower": False},
        )
        assert abilities["Q"]["parts"][0].amount == pytest.approx(360.0)


class TestVladimirECharge:
    """e_charge_fraction interpolates each sourced modifier min -> max."""

    def test_default_fully_charged_matches_the_packet_max_rows(self) -> None:
        abilities = _parse(
            "Vladimir",
            stats=_stats(ap=100.0, health=2500.0),
            options={"r_hemoplague_debuff": False},
        )
        # Max rows at E rank 5: 180 + 6% x 2500 + 80% x 100 = 410.
        assert abilities["E"]["total_raw"] == pytest.approx(410.0)

    def test_zero_charge_prices_the_minimum_rows(self) -> None:
        abilities = _parse(
            "Vladimir",
            stats=_stats(ap=100.0, health=2500.0),
            options={"e_charge_fraction": 0.0, "r_hemoplague_debuff": False},
        )
        # Min rows: 90 + 1.5% x 2500 + 35% x 100 = 162.5.
        assert abilities["E"]["total_raw"] == pytest.approx(162.5)

    def test_half_charge_interpolates_each_modifier(self) -> None:
        abilities = _parse(
            "Vladimir",
            stats=_stats(ap=100.0, health=2500.0),
            options={"e_charge_fraction": 0.5, "r_hemoplague_debuff": False},
        )
        # flat 135 + maxhp 93.75 + AP 57.5 = 286.25.
        assert abilities["E"]["total_raw"] == pytest.approx(286.25)


# ---------------------------------------------------------------------------
# Resets / recasts
# ---------------------------------------------------------------------------


class TestDariusRExecuteRecast:
    """r_execute_recast prices the sourced free recast after an execute."""

    def test_default_is_a_single_cast(self) -> None:
        abilities = _parse("Darius")
        assert abilities["R"]["total_raw"] == pytest.approx(375.0 + 5 * 75.0)
        assert "recast" not in abilities["R"].get("detail", "")

    def test_execute_recast_doubles_r_with_offset_parts(self) -> None:
        abilities = _parse("Darius", options={"r_execute_recast": True})
        parts = abilities["R"]["parts"]
        assert len(parts) == 4  # base + per-stack, twice
        assert abilities["R"]["total_raw"] == pytest.approx(2 * (375.0 + 5 * 75.0))
        # The recast pair is offset past the 0.15s kill check + two casts.
        assert parts[2].time_offset == pytest.approx(0.6167 + 0.15 + 0.6167)
        assert parts[2].dot_stack_scaled is False
        assert parts[3].dot_stack_scaled is True
        assert parts[3].count == 5
        assert "execute recast" in abilities["R"].get("detail", "")

    def test_recast_off_by_default_keeps_one_cast(self) -> None:
        abilities = _parse("Darius", options={"starting_hemorrhage_stacks": 0})
        assert len(abilities["R"]["parts"]) == 2


class TestNasusRQCooldownHalving:
    """R halves Siphoning Strike's cooldown while active (sourced prose)."""

    def test_q_cooldown_halved_with_r_ranked_by_default(self) -> None:
        abilities = _parse("Nasus")
        base = 3.5  # Q rank 5 static cooldown (cached JSON)
        assert abilities["Q"]["cooldown"] == pytest.approx(base * 0.5)

    def test_option_off_keeps_the_plain_cooldown(self) -> None:
        abilities = _parse("Nasus", options={"r_q_cooldown_halved": False})
        assert abilities["Q"]["cooldown"] == pytest.approx(3.5)

    def test_unranked_r_does_not_halve_q(self) -> None:
        abilities = _parse("Nasus", ranks={"Q": 5, "W": 5, "E": 5, "R": 0})
        assert abilities["Q"]["cooldown"] == pytest.approx(3.5)
        assert "R" not in abilities


# ---------------------------------------------------------------------------
# Secondary-target / splash
# ---------------------------------------------------------------------------


class TestAurelionSolQSecondaryBeam:
    """q_secondary_targets prices the sourced 50%-strength beam."""

    def test_default_is_primary_only(self) -> None:
        abilities = _parse("AurelionSol")
        # 26 ticks x 13.125 + 3 bursts x 100 = 641.25 (AP 0, W off).
        assert abilities["Q"]["total_raw"] == pytest.approx(641.25)
        assert len(abilities["Q"]["parts"]) == 2

    def test_two_secondary_targets_add_the_sourced_half_beam(self) -> None:
        abilities = _parse("AurelionSol", options={"q_secondary_targets": 2})
        # Secondary per second 52.5 (= 50% of 105) x 2 targets x 3.25s.
        assert abilities["Q"]["total_raw"] == pytest.approx(641.25 + 341.25)
        secondary = abilities["Q"]["parts"][0]
        assert secondary.amount == pytest.approx(6.5625 * 2)  # per tick
        assert secondary.count == 26
        assert "secondary target(s)" in abilities["Q"].get("detail", "")


class TestAuroraQSubsequentBolts:
    """q_marked_enemies prices each extra expunge bolt at 20%."""

    def test_default_single_target_no_bolts(self) -> None:
        abilities = _parse("Aurora", stats=_stats(ap=100.0))
        # first 185 + recast-min 185 (full-HP bound).
        assert abilities["Q"]["total_raw"] == pytest.approx(370.0)
        assert len(abilities["Q"]["parts"]) == 2

    def test_extra_marks_add_subsequent_bolt_hits(self) -> None:
        abilities = _parse(
            "Aurora", stats=_stats(ap=100.0), options={"q_marked_enemies": 2}
        )
        # bolt min = 29 + 8 = 37; bound adds 2 x 37.
        assert abilities["Q"]["total_raw"] == pytest.approx(370.0 + 74.0)
        bolt = abilities["Q"]["parts"][2]
        assert bolt.count == 2
        assert bolt.amount == pytest.approx(37.0)
        assert bolt.hp_scaled_damage is not None
        assert "20% of the recast" in abilities["Q"].get("detail", "")


class TestCaitlynQSecondaryTargets:
    """q_secondary_targets prices the sourced 60% Reduced Damage row."""

    def test_default_primary_only(self) -> None:
        abilities = _parse("Caitlyn", stats=_stats(ad=100.0))
        # 210 + 205% x 100 = 415.
        assert abilities["Q"]["total_raw"] == pytest.approx(415.0)

    def test_secondary_targets_take_the_reduced_row(self) -> None:
        abilities = _parse(
            "Caitlyn", stats=_stats(ad=100.0), options={"q_secondary_targets": 2}
        )
        # reduced = 126 + 123% x 100 = 249; total 415 + 2 x 249.
        assert abilities["Q"]["total_raw"] == pytest.approx(913.0)
        reduced = abilities["Q"]["parts"][1]
        assert reduced.count == 2
        assert reduced.amount == pytest.approx(249.0)


class TestOriannaQSecondaryTargets:
    """q_secondary_targets prices the sourced 70% Reduced Damage row."""

    def test_default_primary_only(self) -> None:
        abilities = _parse("Orianna", stats=_stats(ap=100.0))
        # 180 + 55 = 235.
        assert abilities["Q"]["total_raw"] == pytest.approx(235.0)

    def test_secondary_targets_take_the_reduced_row(self) -> None:
        abilities = _parse(
            "Orianna", stats=_stats(ap=100.0), options={"q_secondary_targets": 2}
        )
        # reduced = 126 + 38.5 = 164.5; total 235 + 2 x 164.5.
        assert abilities["Q"]["total_raw"] == pytest.approx(564.0)
        assert abilities["Q"]["parts"][1].count == 2


class TestGnarQMiniSecondaryTargets:
    """Mini Q return-pass targets take the sourced 50% Reduced Damage row."""

    def test_mini_default_primary_only(self) -> None:
        abilities = _parse("Gnar", stats=_stats(ad=100.0))
        # Mini Q rank 5: 165 + 125% x 100 = 290.
        assert abilities["Q"]["total_raw"] == pytest.approx(290.0)

    def test_mini_secondary_targets_on_the_return_pass(self) -> None:
        abilities = _parse(
            "Gnar", stats=_stats(ad=100.0), options={"q_secondary_targets": 2}
        )
        # reduced = 82.5 + 62.5 = 145; total 290 + 2 x 145.
        assert abilities["Q"]["total_raw"] == pytest.approx(580.0)
        assert abilities["Q"]["parts"][1].count == 2

    def test_mega_boulder_ignores_the_option(self) -> None:
        from src.calculator.champions import gnar
        from src.calculator.stats import growth_stat

        abilities = _parse(
            "Gnar",
            stats=_stats(ad=100.0),
            options={"mega": True, "q_secondary_targets": 2},
        )
        # Mega Rage Gene raises BASE AD by the game-file delta (+45.1 at
        # 18): boulder = 225 + 140% x (100 + 45.1) = 428.14; Mega has no
        # Reduced Damage row, so the option adds nothing.
        mega_ad = 100.0 + growth_stat(*gnar.MEGA_BONUS_AD, 18)
        assert abilities["Q"]["total_raw"] == pytest.approx(225.0 + 1.40 * mega_ad)
        assert len(abilities["Q"]["parts"]) == 1


class TestXayahCleanCutsSecondaryFeathers:
    """Feathers hit other enemies at the level-scaled 35/45/55% AD."""

    def test_default_has_no_secondary_feather_on_hit(self) -> None:
        abilities = _parse("Xayah", stats=_stats(ad=100.0))
        assert "on_hit" not in abilities["passive"]

    def test_secondary_targets_price_the_level_ratio(self) -> None:
        abilities = _parse(
            "Xayah",
            stats=_stats(ad=100.0),
            options={"clean_cuts_secondary_targets": 2},
        )
        # Level 18 -> 55% AD; 2 targets x 0.55 x 100 = 110 per auto.
        on_hit = abilities["passive"]["on_hit"]
        assert on_hit["damage_per_hit"] == pytest.approx(110.0)
        assert on_hit["damage_type"] == "physical"

    def test_crit_rider_scales_with_crit_chance(self) -> None:
        abilities = _parse(
            "Xayah",
            stats=_stats(ad=100.0, crit=100.0),
            options={"clean_cuts_secondary_targets": 2},
        )
        # (200% + 30%) crit expectation: 110 x (1 + 0.30 x 1.0) = 143.
        assert abilities["passive"]["on_hit"]["damage_per_hit"] == pytest.approx(143.0)


# ---------------------------------------------------------------------------
# Utility / special scaling
# ---------------------------------------------------------------------------


class TestApheliosMoonlightVigilFollowups:
    """r_followup_targets prices the 100% AD follow-up attacks."""

    def test_default_initial_blast_only(self) -> None:
        abilities = _parse("Aphelios", stats=_stats(ap=100.0))
        # R rank 3: 225 + 20% x 0 bonus AD + 100% x 100 AP = 325.
        assert abilities["R"]["total_raw"] == pytest.approx(325.0)
        assert "applies_item_on_hits" not in abilities["R"]

    def test_followup_attacks_at_100_ad_with_on_hits(self) -> None:
        abilities = _parse(
            "Aphelios",
            stats=_stats(ad=100.0, ap=100.0),
            options={"r_followup_targets": 2},
        )
        # 0% crit -> follow-up expected multiplier 1.0: 2 x 100 = 200.
        assert abilities["R"]["total_raw"] == pytest.approx(325.0 + 200.0)
        followup = abilities["R"]["parts"][1]
        assert followup.count == 2
        assert followup.amount == pytest.approx(100.0)
        assert followup.time_offset == pytest.approx(0.3)
        assert followup.basic_damage is True
        declared = abilities["R"]["applies_item_on_hits"]
        assert declared["effectiveness"] == pytest.approx(1.0)
        assert declared["hits"] == 2

    def test_followup_special_crit_scaling(self) -> None:
        abilities = _parse(
            "Aphelios",
            stats=_stats(ad=100.0, ap=100.0, crit=100.0),
            options={"r_followup_targets": 2},
        )
        # 100% crit: E = 1 + (0.30 + 0.09) x 1.0^2 = 1.39 -> 139 per attack.
        assert abilities["R"]["total_raw"] == pytest.approx(325.0 + 2 * 139.0)
        assert abilities["R"]["parts"][1].amount == pytest.approx(139.0)


# ---------------------------------------------------------------------------
# Fight-engine integration (unmitigated deterministic fights)
# ---------------------------------------------------------------------------


def _fight(abilities, stats, **overrides):
    """Unmitigated one-rotation fight (0 resistances) for exact numbers."""
    from src.calculator.damage import FightConfig, calculate_fight_damage

    config = {
        "target_health": 10000.0,
        "target_armor": 0.0,
        "target_magic_resistance": 0.0,
        "fight_duration_seconds": 8.0,
        "auto_attack_uptime": 0.0,
        "one_rotation": True,
        "deterministic": True,
    }
    config.update(overrides)
    return calculate_fight_damage(stats, abilities, [], FightConfig(**config))


class TestFightIntegration:
    """The packets reach the fight engine's breakdown rows."""

    def test_darius_execute_recast_doubles_r_damage(self) -> None:
        from src.calculator.champions import darius as darius_module

        base = _parse("Darius")
        recast = _parse("Darius", options={"r_execute_recast": True})
        stats = _stats(ad=100.0, bonus_ad=0.0, health=0.0)
        base_fight = _fight(base, stats)
        recast_fight = _fight(recast, stats)
        assert recast_fight["breakdown"]["R"]["total_damage"] == pytest.approx(
            2.0 * base_fight["breakdown"]["R"]["total_damage"]
        )

    def test_varus_charge_fraction_lowers_q_in_fight(self) -> None:
        full = _parse("Varus", options={"w_active_empower": False})
        none = _parse(
            "Varus",
            options={"q_charge_fraction": 0.0, "w_active_empower": False},
        )
        stats = _stats(ad=100.0)
        full_fight = _fight(full, stats)
        none_fight = _fight(none, stats)
        # Arrow only: 360 -> 240; the detonation (300) is unchanged.
        assert none_fight["breakdown"]["Q"]["total_damage"] == pytest.approx(
            full_fight["breakdown"]["Q"]["total_damage"] - 120.0
        )

    def test_xayah_secondary_feathers_price_per_auto(self) -> None:
        plain = _parse("Xayah", stats=_stats(ad=100.0))
        feathered = _parse(
            "Xayah",
            stats=_stats(ad=100.0),
            options={"clean_cuts_secondary_targets": 2},
        )
        stats = _stats(ad=100.0, bonus_ad=0.0)
        # One rotation at zero auto uptime has no autos, so the on-hit
        # rider must not fire (conservative; feathers ride autos only).
        plain_fight = _fight(plain, stats)
        feathered_fight = _fight(feathered, stats)
        assert feathered_fight["breakdown"]["Q"]["total_damage"] == pytest.approx(
            plain_fight["breakdown"]["Q"]["total_damage"]
        )

    def test_aphelios_followups_land_in_the_r_row(self) -> None:
        blast = _parse("Aphelios", stats=_stats(ap=100.0))
        followups = _parse(
            "Aphelios",
            stats=_stats(ad=100.0, ap=100.0),
            options={"r_followup_targets": 2},
        )
        stats = _stats(ad=100.0, ap=100.0)
        blast_fight = _fight(blast, stats)
        followup_fight = _fight(followups, stats)
        assert followup_fight["breakdown"]["R"]["total_damage"] == pytest.approx(
            blast_fight["breakdown"]["R"]["total_damage"] + 2.0 * 100.0
        )
