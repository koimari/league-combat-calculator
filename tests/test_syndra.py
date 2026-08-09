"""Tests for Syndra champion ability parsing and damage calculation.

Reference damage (raw, pre-mitigation, hand-computed from the wiki).
Anchors use splinters=60 so W's true damage is on but the 120-stack
+15% AP multiplier does not distort the AP the formulas see.
At level 18, rank 5/5/5/3, 600 total AP:
- Q rank 5: 230 + 70% AP = 650 magic; 7s static CD (Q-only R haste folded)
- W rank 5: 190 + 65% AP = 580 magic, plus at 60+ splinters bonus TRUE
  damage = (12% + 2% per 100 AP) x 580 = 0.24 x 580 = 139.2
- E rank 5: 200 + 60% AP = 560 magic, CD 15
- R rank 3: 80/120/160 + 20% AP PER SPHERE = 280 x sphere count
  (840 at the 3 base spheres, 1960 at the 7-sphere cap)
- P at 120 splinters: +15% TOTAL AP applied before all damage parses
  (at 100 AP pre-buff: Q rank 5 = 230 + 0.70 x 115 = 310.5)
"""

import pytest

from src.calculator.champions import parse_champion_abilities as parse_abilities
from src.calculator.damage import FightConfig, calculate_fight_damage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ALL_MAXED = {"Q": 5, "W": 5, "E": 5, "R": 3}


def _parse(syndra_data, level=18, ap=600.0, options=None, ranks=None, stats=None):
    """Parse Syndra at a level with explicit AP and champion options."""
    champion_stats = {
        "attack_damage": 100.0,
        "bonus_attack_damage": 0.0,
        "ability_power": ap,
    }
    if stats:
        champion_stats.update(stats)
    return parse_abilities(
        syndra_data,
        level,
        ap,
        ability_ranks=ranks if ranks is not None else dict(ALL_MAXED),
        champion_stats=champion_stats,
        champion_options=options if options is not None else {"splinters": 60},
    )


def _fight(stats, abilities, **overrides):
    """Unmitigated deterministic fight (0 resistances) for exact numbers."""
    config = {
        "target_health": 10000.0,
        "target_armor": 0.0,
        "target_magic_resistance": 0.0,
        "fight_duration_seconds": 8.0,
        "auto_attack_uptime": 0.0,
        "one_rotation": False,
        "deterministic": True,
    }
    config.update(overrides)
    return calculate_fight_damage(stats, abilities, [], FightConfig(**config))


# ---------------------------------------------------------------------------
# Slot coverage and damage types
# ---------------------------------------------------------------------------


class TestSlotMap:
    """Emitted slots track the splinter thresholds."""

    def test_full_splinters_slots(self, syndra_data) -> None:
        """At 120 splinters: passive AP buff row, Q + 2nd charge, W, E, R."""
        abilities = _parse(syndra_data, options={"splinters": 120})
        assert set(abilities) == {"passive", "Q", "Q2", "W", "E", "R"}

    def test_zero_splinters_slots(self, syndra_data) -> None:
        """Below every threshold only the four base casts exist."""
        abilities = _parse(syndra_data, options={"splinters": 0})
        assert set(abilities) == {"Q", "W", "E", "R"}

    @pytest.mark.parametrize("slot", ["Q", "Q2", "E", "R"])
    def test_magic_damage_types(self, syndra_data, slot) -> None:
        abilities = _parse(syndra_data, options={"splinters": 120})
        assert abilities[slot]["damage_type"] == "magic"

    def test_w_is_mixed_at_60_splinters(self, syndra_data) -> None:
        abilities = _parse(syndra_data, options={"splinters": 60})
        assert abilities["W"]["damage_type"] == "mixed"

    def test_w_is_magic_below_60_splinters(self, syndra_data) -> None:
        abilities = _parse(syndra_data, options={"splinters": 59})
        assert abilities["W"]["damage_type"] == "magic"

    def test_cooldowns(self, syndra_data) -> None:
        """W 8s / E 15s / R 80s at max rank; Q's is haste-folded (below)."""
        abilities = _parse(syndra_data)
        assert abilities["W"]["cooldown"] == 8.0
        assert abilities["E"]["cooldown"] == 15.0
        assert abilities["R"]["cooldown"] == 80.0


# ---------------------------------------------------------------------------
# Hand-validated ability damage (wiki anchors, splinters=60, 600 AP)
# ---------------------------------------------------------------------------


class TestAbilityDamage:
    """Raw values match the wiki at rank 5/5/5/3 with 600 AP."""

    def test_q_rank5(self, syndra_data) -> None:
        """Q rank 5: 230 + 70% AP = 650."""
        abilities = _parse(syndra_data)
        assert abilities["Q"]["total_raw"] == pytest.approx(650.0)

    def test_w_rank5_magic_plus_true(self, syndra_data) -> None:
        """W rank 5: 580 magic + (0.12 + 0.0002 x 600) x 580 = 139.2 true."""
        entry = _parse(syndra_data)["W"]
        assert entry["total_raw"] == pytest.approx(580.0 + 139.2)
        magic_part, true_part = entry["parts"]
        assert magic_part.damage_type == "magic"  # Horizon Focus trigger first
        assert magic_part.amount == pytest.approx(580.0)
        assert true_part.damage_type == "true"
        assert true_part.amount == pytest.approx(139.2)

    def test_w_below_threshold_is_base_magic_only(self, syndra_data) -> None:
        entry = _parse(syndra_data, options={"splinters": 0})["W"]
        assert entry["total_raw"] == pytest.approx(580.0)
        assert len(entry["parts"]) == 1

    def test_w_true_damage_is_quadratic_in_ap(self, syndra_data) -> None:
        """At 1000 AP: magic 840; true = (0.12 + 0.20) x 840 = 268.8 —
        the module formula, NOT the JSON's garbled effect[3] rows."""
        entry = _parse(syndra_data, ap=1000.0)["W"]
        assert entry["parts"][1].amount == pytest.approx(268.8)

    def test_e_rank5(self, syndra_data) -> None:
        """E rank 5: 200 + 60% AP = 560."""
        abilities = _parse(syndra_data)
        assert abilities["E"]["total_raw"] == pytest.approx(560.0)

    def test_r_rank3_default_spheres(self, syndra_data) -> None:
        """R rank 3 at 3 spheres: 3 x (160 + 20% AP) = 840."""
        entry = _parse(syndra_data)["R"]
        assert entry["total_raw"] == pytest.approx(840.0)
        (part,) = entry["parts"]
        assert part.amount == pytest.approx(280.0)
        assert part.count == 3


# ---------------------------------------------------------------------------
# Passive: 120-splinter +15% total AP (BUFF phase)
# ---------------------------------------------------------------------------


class TestTranscendentApBuff:
    """The 15% multiplier applies to total AP before all damage parses."""

    def test_buff_row_shape(self, syndra_data) -> None:
        entry = _parse(syndra_data, ap=100.0, options={"splinters": 120})["passive"]
        assert entry["total_raw"] == 0.0
        assert entry["parts"] == ()
        assert entry["stat_buff"] == {"ability_power": pytest.approx(15.0)}

    def test_damage_slots_see_multiplied_ap(self, syndra_data) -> None:
        """At 100 AP pre-buff, Q parses against 115 AP: 230 + 80.5."""
        abilities = _parse(syndra_data, ap=100.0, options={"splinters": 120})
        assert abilities["Q"]["total_raw"] == pytest.approx(310.5)
        assert abilities["E"]["total_raw"] == pytest.approx(260.0 + 9.0)

    def test_w_true_damage_uses_multiplied_ap(self, syndra_data) -> None:
        """Pre-buff 521.7391 AP -> 600 total: W = 580 magic + 139.2 true."""
        entry = _parse(syndra_data, ap=600.0 / 1.15, options={"splinters": 120})["W"]
        assert entry["parts"][0].amount == pytest.approx(580.0)
        assert entry["parts"][1].amount == pytest.approx(139.2)

    def test_no_buff_below_120(self, syndra_data) -> None:
        abilities = _parse(syndra_data, ap=100.0, options={"splinters": 119})
        assert "passive" not in abilities
        assert abilities["Q"]["total_raw"] == pytest.approx(300.0)

    def test_default_options_are_fully_stacked(self, syndra_data) -> None:
        """No options supplied -> splinters defaults to 120 (buff on)."""
        abilities = _parse(syndra_data, ap=100.0, options={})
        assert "passive" in abilities
        assert abilities["Q"]["total_raw"] == pytest.approx(310.5)


# ---------------------------------------------------------------------------
# Q: second charge (40+ splinters) and R's Q-only ability haste
# ---------------------------------------------------------------------------


class TestDarkSphereCharges:
    """40+ splinters adds ONE extra Q cast available at fight open."""

    def test_q2_matches_q_damage(self, syndra_data) -> None:
        abilities = _parse(syndra_data, options={"splinters": 40})
        assert abilities["Q2"]["total_raw"] == pytest.approx(
            abilities["Q"]["total_raw"]
        )
        assert abilities["Q2"]["damage_type"] == "magic"

    def test_q2_is_single_cast(self, syndra_data) -> None:
        """Cooldown 0 = the engine's cast-exactly-once idiom."""
        abilities = _parse(syndra_data, options={"splinters": 40})
        assert abilities["Q2"]["cooldown"] == 0.0

    def test_q2_absent_below_40(self, syndra_data) -> None:
        abilities = _parse(syndra_data, options={"splinters": 39})
        assert "Q2" not in abilities

    def test_timed_fight_gets_exactly_one_extra_q(
        self, syndra_data, attacker_stats
    ) -> None:
        """8s fight, Q only (7s CD, R unranked): 2 Q casts + 1 Q2 cast."""
        stats = attacker_stats()
        options = {"splinters": 40}
        ranks = {"Q": 5, "W": 0, "E": 0, "R": 0}
        abilities = parse_abilities(
            syndra_data,
            18,
            0.0,
            ability_ranks=ranks,
            champion_stats=stats,
            champion_options=options,
        )
        result = _fight(stats, abilities)
        assert result["breakdown"]["Q"]["casts"] == 2
        assert result["breakdown"]["Q2"]["casts"] == 1
        assert result["breakdown"]["Q2"]["total_damage"] == pytest.approx(230.0)


class TestQOnlyHaste:
    """R's 10/20/30 ability haste applies to Q's cooldown only."""

    def test_q_cd_without_r(self, syndra_data) -> None:
        abilities = _parse(syndra_data, ranks={"Q": 5, "W": 5, "E": 5, "R": 0})
        assert abilities["Q"]["cooldown"] == pytest.approx(7.0)

    def test_q_cd_with_r_rank3_no_item_haste(self, syndra_data) -> None:
        """7 x 100 / (100 + 30) = 5.3846."""
        abilities = _parse(syndra_data)
        assert abilities["Q"]["cooldown"] == pytest.approx(7.0 * 100.0 / 130.0)

    def test_q_cd_folds_against_global_haste(self, syndra_data) -> None:
        """With 70 global AH the emitted base must be 7 x 170/200, so the
        fight engine's own 100/(100+70) lands on 7 x 100/200 = 3.5."""
        abilities = _parse(syndra_data, stats={"ability_haste": 70.0})
        emitted = abilities["Q"]["cooldown"]
        assert emitted == pytest.approx(7.0 * 170.0 / 200.0)
        assert emitted * 100.0 / 170.0 == pytest.approx(3.5)

    def test_other_slots_unaffected_by_r_haste(self, syndra_data) -> None:
        """W/E keep their base cooldowns — the haste is Q-only."""
        abilities = _parse(syndra_data)
        assert abilities["W"]["cooldown"] == 8.0
        assert abilities["E"]["cooldown"] == 15.0


# ---------------------------------------------------------------------------
# R: sphere count option
# ---------------------------------------------------------------------------


class TestUnleashedPowerSpheres:
    """r_spheres multiplies the per-sphere damage, clamped to 3-7."""

    def test_seven_spheres(self, syndra_data) -> None:
        entry = _parse(syndra_data, options={"splinters": 60, "r_spheres": 7})["R"]
        assert entry["total_raw"] == pytest.approx(1960.0)
        assert entry["parts"][0].count == 7

    def test_sphere_count_clamped(self, syndra_data) -> None:
        low = _parse(syndra_data, options={"splinters": 60, "r_spheres": 1})["R"]
        high = _parse(syndra_data, options={"splinters": 60, "r_spheres": 12})["R"]
        assert low["parts"][0].count == 3
        assert high["parts"][0].count == 7

    def test_r_rank1(self, syndra_data) -> None:
        """Rank 1: 3 x (80 + 20% of 600 AP) = 600."""
        entry = _parse(
            syndra_data,
            ranks={"Q": 5, "W": 5, "E": 5, "R": 1},
            options={"splinters": 60},
        )["R"]
        assert entry["total_raw"] == pytest.approx(600.0)


# ---------------------------------------------------------------------------
# Rotation: Q must precede E (the stun consumes a sphere)
# ---------------------------------------------------------------------------


class TestRotationOrder:
    """E's stun exists only by scattering a Dark Sphere, so Q is E's setup —
    the reverse of the generic cc-setup-first ordering. The hand-verified
    COMBO_TABLE seed pins the QE combo and keeps W/R inside the stun."""

    def test_cast_order_is_qe_combo(self, syndra_data) -> None:
        from src.calculator.rotation_resolver import resolve_cast_order

        abilities = _parse(syndra_data)
        order, rule = resolve_cast_order("Syndra", abilities, champion_data=syndra_data)
        assert order == ["Q", "Q2", "E", "W", "R"]
        assert rule is not None and rule.derived is False
        assert "sphere" in rule.rationale.lower()


# ---------------------------------------------------------------------------
# E: Scatter the Weak's authored stun marker
# ---------------------------------------------------------------------------


class TestScatterTheWeakStun:
    """E carries the authored stun so CC-triggered item passives (Imperial
    Mandate's Command, Bandlepipes' Fanfare) can see it in the event ledger."""

    def test_e_part_carries_stun_marker(self, syndra_data) -> None:
        (part,) = _parse(syndra_data)["E"]["parts"]
        assert part.cc_kind == "stun"

    def test_e_fight_event_carries_stun_marker(
        self, syndra_data, attacker_stats
    ) -> None:
        """The marker must survive the fight engine into damage_events —
        that ledger is what item_support_effects scans for CC triggers."""
        stats = attacker_stats(ability_power=600.0)
        abilities = parse_abilities(
            syndra_data,
            18,
            600.0,
            ability_ranks={"Q": 0, "W": 0, "E": 5, "R": 0},
            champion_stats=stats,
            champion_options={"splinters": 60},
        )
        result = _fight(stats, abilities, one_rotation=True)
        e_events = [
            event
            for event in result["damage_events"]
            if event.get("source") == "E" or event.get("source_key") == "E"
        ]
        assert e_events
        assert all(event.get("cc_kind") == "stun" for event in e_events)

    def test_imperial_mandate_command_amps_post_stun_damage(
        self, syndra_data, attacker_stats
    ) -> None:
        """E stuns at t=0, R lands at t=0.25 inside Command's 4s window:
        7% of R's 840 = 58.8 bonus. E itself (the trigger) is not amped."""
        from src.calculator.data_fetcher import get_item_by_name

        items = [get_item_by_name("Imperial Mandate")]
        stats = attacker_stats(ability_power=600.0)
        abilities = parse_abilities(
            syndra_data,
            18,
            600.0,
            ability_ranks={"Q": 0, "W": 0, "E": 5, "R": 3},
            champion_stats=stats,
            champion_options={"splinters": 60},
        )
        result = calculate_fight_damage(
            stats,
            abilities,
            items,
            FightConfig(
                target_health=10000.0,
                target_armor=0.0,
                target_magic_resistance=0.0,
                fight_duration_seconds=8.0,
                auto_attack_uptime=0.0,
                one_rotation=False,
                deterministic=True,
            ),
        )
        row = result["breakdown"]["damage_amp_Imperial Mandate"]
        assert row["multiplier"] == pytest.approx(1.07)
        assert row["total_damage"] == pytest.approx(0.07 * 840.0)
        assert result["total_damage"] == pytest.approx(560.0 + 840.0 * 1.07)


# ---------------------------------------------------------------------------
# Fight-engine integration
# ---------------------------------------------------------------------------


class TestFightIntegration:
    """Mitigation semantics: W's bonus is TRUE damage, the base is magic."""

    def test_w_true_part_ignores_mr(self, syndra_data, attacker_stats) -> None:
        """100 MR halves W's magic 580 but not the 139.2 true bonus."""
        stats = attacker_stats(ability_power=600.0)
        abilities = parse_abilities(
            syndra_data,
            18,
            600.0,
            ability_ranks={"Q": 0, "W": 5, "E": 0, "R": 0},
            champion_stats=stats,
            champion_options={"splinters": 60},
        )
        result = _fight(
            stats,
            abilities,
            target_magic_resistance=100.0,
            one_rotation=True,
            fight_duration_seconds=5.0,
        )
        row = result["breakdown"]["W"]
        assert row["total_damage"] == pytest.approx(580.0 / 2.0 + 139.2)
        assert row["damage_by_type"]["magic"] == pytest.approx(290.0)
        assert row["damage_by_type"]["true"] == pytest.approx(139.2)

    def test_r_spheres_mitigated_per_hit(self, syndra_data, attacker_stats) -> None:
        """7 spheres into 100 MR: 1960 / 2 (flat magic per sphere)."""
        stats = attacker_stats(ability_power=600.0)
        abilities = parse_abilities(
            syndra_data,
            18,
            600.0,
            ability_ranks={"Q": 0, "W": 0, "E": 0, "R": 3},
            champion_stats=stats,
            champion_options={"splinters": 60, "r_spheres": 7},
        )
        result = _fight(
            stats,
            abilities,
            target_magic_resistance=100.0,
            one_rotation=True,
            fight_duration_seconds=5.0,
        )
        assert result["breakdown"]["R"]["total_damage"] == pytest.approx(980.0)


# ---------------------------------------------------------------------------
# Command window arithmetic (pure helpers in damage.py)
# ---------------------------------------------------------------------------


class TestCommandWindows:
    """The two pieces of _apply_command_amp most exposed to refactor drift:
    window merging (extend, not stack) and the strictly-after boundary."""

    def test_overlapping_immobilizes_extend_one_window(self) -> None:
        from src.calculator.damage import _merged_cc_windows

        assert _merged_cc_windows([0.0, 2.0], 4.0) == [(0.0, 6.0)]

    def test_separated_immobilizes_open_separate_windows(self) -> None:
        from src.calculator.damage import _merged_cc_windows

        assert _merged_cc_windows([0.0, 10.0], 4.0) == [(0.0, 4.0), (10.0, 14.0)]

    def test_boundary_is_strictly_after_start_inclusive_end(self) -> None:
        from src.calculator.damage import _in_cc_window, _merged_cc_windows

        windows = _merged_cc_windows([1.0], 4.0)
        assert not _in_cc_window(windows, 1.0)  # the trigger itself
        assert _in_cc_window(windows, 1.001)
        assert _in_cc_window(windows, 5.0)  # inclusive end
        assert not _in_cc_window(windows, 5.001)
