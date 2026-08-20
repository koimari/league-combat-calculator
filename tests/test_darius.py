"""Tests for the Darius champion module.

Hand-validated against the wiki and the champion JSON's 40-entry
per-level arrays at level 20 (this project's cap) with 100 bonus AD from
items, so base AD = 162.325 and total AD = 262.325:

    Q rank 5 blade   = 170 + 1.40 x 262.325 = 537.255 physical
    W rank 5 bonus   = 0.60 x 262.325       = 157.395 physical
    P one stack      = 32 + 0.30 x 100      = 62.0 over 5s (4 ticks)
    P five stacks    = 160 + 1.50 x 100     = 310.0
    R rank 3 @ 0 stk = 375 + 0.75 x 100     = 450.0 true
    R rank 3 @ 5 stk = 750 + 1.50 x 100     = 900.0 true

With Noxian Might active (+280 bonus AD at level 20 -> bonus AD 380):

    Q = 929.255, W = 325.395, P five stacks = 730.0, R @ 5 stk = 1320.0
"""

import copy

import pytest

from src.calculator.champions import parse_champion_abilities
from src.calculator.champions.darius import P_BLEED_MAX_STACKS
from src.calculator.champions.slotlib import extract_named, extract_value
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.pipeline import FightParams, run_fight
from src.calculator.champions import darius
from tests import cc_review

LEVEL = 20
BONUS_AD = 100.0
BASE_AD = 162.325


def _stats(bonus_ad: float = BONUS_AD) -> dict[str, float]:
    """Champion stats matching the module docstring's reference build."""
    return {
        "level": float(LEVEL),
        "base_attack_damage": BASE_AD,
        "bonus_attack_damage": bonus_ad,
        "attack_damage": BASE_AD + bonus_ad,
        "attack_speed": 1.0,
        "attack_speed_ratio": 0.625,
        "critical_strike_chance": 0.0,
        "ability_haste": 0.0,
        "basic_ability_haste": 0.0,
        "armor_penetration_percent": 0.0,
        "flat_armor_penetration": 0.0,
        "magic_penetration_flat": 0.0,
        "magic_penetration_percent": 0.0,
        "is_melee": True,
    }


def _abilities(darius_data, **options) -> dict:
    """Parse Darius at the reference build, with optional champion options."""
    return parse_champion_abilities(
        darius_data,
        LEVEL,
        0.0,
        champion_stats=_stats(),
        target_stats={"target_max_health": 2500.0},
        champion_options=options or None,
    )


class TestParsedValues:
    """Hand-validated damage against the wiki and the JSON arrays."""

    def test_q_reads_the_outer_blade(self, darius_data) -> None:
        """Q must read "Physical Damage (Blade)", not the 35% handle."""
        q = _abilities(darius_data)["Q"]
        assert q["rank"] == 5
        assert q["damage_type"] == "physical"
        assert q["total_raw"] == pytest.approx(537.255)
        assert q["cooldown"] == pytest.approx(5.0)

    def test_w_bonus_damage(self, darius_data) -> None:
        w = _abilities(darius_data)["W"]
        assert w["damage_type"] == "physical"
        assert w["total_raw"] == pytest.approx(157.395)
        assert w["cooldown"] == pytest.approx(5.0)

    def test_passive_single_stack_bleed(self, darius_data) -> None:
        passive = _abilities(darius_data)["passive"]
        assert passive["damage_type"] == "physical"
        assert passive["total_raw"] == pytest.approx(62.0)
        dot = passive["stacking_dot"]
        assert dot["single_stack_raw"] == pytest.approx(62.0)
        assert dot["single_stack_raw"] * P_BLEED_MAX_STACKS == pytest.approx(310.0)

    def test_r_base_and_per_stack(self, darius_data) -> None:
        """R is base true damage plus a per-stack instance, never the
        JSON's "Maximum True Damage" (correct only at 5 stacks)."""
        r = _abilities(darius_data)["R"]
        assert r["rank"] == 3
        assert r["damage_type"] == "true"
        base, per_stack = r["parts"]
        assert base.amount == pytest.approx(450.0)
        assert per_stack.amount == pytest.approx(90.0)
        assert base.amount + per_stack.amount * P_BLEED_MAX_STACKS == pytest.approx(
            900.0
        )

    def test_e_grants_armor_penetration_and_no_damage(self, darius_data) -> None:
        e = _abilities(darius_data)["E"]
        assert e["total_raw"] == pytest.approx(0.0)
        assert e["stat_buff"] == {"armor_penetration_percent": 40.0}

    def test_every_castable_carries_a_cooldown(self, darius_data) -> None:
        abilities = _abilities(darius_data)
        for key in ("Q", "W", "E", "R"):
            assert abilities[key]["cooldown"] > 0


class TestJsonCrossChecks:
    """The passive's positionally-indexed arrays must stay self-consistent
    on patch updates, and R's trap attribute must reconcile."""

    def test_per_tick_arrays_are_quarters_of_their_totals(self, darius_data) -> None:
        """Each stack ticks 4 times over 5s (every 1.25s)."""
        effects = darius_data["abilities"]["P"][0]["effects"]
        bleed = effects[1]["leveling"]
        index = LEVEL - 1
        per_stack = bleed[0]["modifiers"][0]["values"][index]
        per_tick = bleed[1]["modifiers"][0]["values"][index]
        five_stack = bleed[2]["modifiers"][0]["values"][index]
        five_per_tick = bleed[3]["modifiers"][0]["values"][index]
        assert (per_stack, per_tick, five_stack, five_per_tick) == (32, 8, 160, 40)
        assert per_tick * 4 == per_stack
        assert five_stack == per_stack * P_BLEED_MAX_STACKS
        assert five_per_tick * 4 == five_stack

    def test_noxian_might_ramp_is_non_linear(self, darius_data) -> None:
        """The wiki's "30 - 230" is the LEVEL-18 endpoint; the array keeps
        climbing +25/level, so level 20 is 280 — never interpolate."""
        might = darius_data["abilities"]["P"][0]["effects"][3]["leveling"][0]
        values = might["modifiers"][0]["values"]
        assert values[:10] == [30, 35, 40, 45, 50, 55, 60, 65, 70, 75]
        assert values[10:13] == [85, 95, 105]
        assert values[17] == 230  # level 18
        assert values[19] == 280  # level 20 — this project's cap
        buff = _abilities(darius_data)["passive"]["stack_triggered_buff"]
        assert buff["bonus_attack_damage"] == pytest.approx(280.0)

    def test_r_maximum_attribute_reconciles_with_base_plus_five(
        self, darius_data
    ) -> None:
        ability = darius_data["abilities"]["R"][0]
        stats = _stats()
        base = extract_named(ability, "True Damage", 3, stats)
        per_stack = extract_named(ability, "Bonus Damage Per Stack", 3, stats)
        maximum = extract_named(ability, "Maximum True Damage", 3, stats)
        assert base + per_stack * P_BLEED_MAX_STACKS == pytest.approx(maximum)

    def test_bonus_ad_ratios_come_from_the_json(self, darius_data) -> None:
        """Each part's declared derivative in bonus AD must match the JSON
        modifier that produced its damage."""
        abilities = _abilities(darius_data)
        q_ability = darius_data["abilities"]["Q"][0]
        w_ability = darius_data["abilities"]["W"][0]
        r_ability = darius_data["abilities"]["R"][0]
        assert abilities["Q"]["parts"][0].bonus_ad_ratio == pytest.approx(
            extract_value(q_ability, "Physical Damage (Blade)", 5, 1) / 100.0
        )
        assert abilities["W"]["parts"][0].bonus_ad_ratio == pytest.approx(
            extract_value(w_ability, "Bonus Physical Damage", 5) / 100.0
        )
        assert abilities["R"]["parts"][0].bonus_ad_ratio == pytest.approx(
            extract_value(r_ability, "True Damage", 3, 1) / 100.0
        )
        assert abilities["R"]["parts"][1].bonus_ad_ratio == pytest.approx(
            extract_value(r_ability, "Bonus Damage Per Stack", 3, 1) / 100.0
        )


class TestSlotFlags:
    """The kit's non-damage mechanics: stack application, empowered
    autos, crit effectiveness, and cast-time overrides."""

    def test_e_applies_no_hemorrhage_stack(self, darius_data) -> None:
        """Apprehend deals no damage, so it applies no stack — a real
        mechanic, not an oversight."""
        assert "applies_dot_stack" not in _abilities(darius_data)["E"]

    def test_damaging_slots_apply_a_stack(self, darius_data) -> None:
        abilities = _abilities(darius_data)
        for key in ("Q", "W", "R"):
            assert abilities[key]["applies_dot_stack"] is True

    def test_w_empowers_the_next_auto_and_crits_fully(self, darius_data) -> None:
        w = _abilities(darius_data)["W"]
        assert w["empowers_next_auto"] is True
        assert w["parts"][0].crit_effectiveness == 1.0

    def test_cast_times_override_the_json(self, darius_data) -> None:
        """Q's JSON castTime is the string "none" (-> 0.0s), but Decimate
        winds up for 0.75s; E and R also lock Darius out longer than the
        JSON field says."""
        abilities = _abilities(darius_data)
        assert darius_data["abilities"]["Q"][0]["castTime"] == "none"
        assert abilities["Q"]["cast_time"] == pytest.approx(0.75)
        assert abilities["E"]["cast_time"] == pytest.approx(0.65)
        assert abilities["R"]["cast_time"] == pytest.approx(0.6167)

    def test_passive_declares_its_dot_tail(self, darius_data) -> None:
        """Item burns must stay refreshed through the bleed's 5s tail."""
        assert _abilities(darius_data)["passive"]["dot_duration"] == 5.0

    def test_bleed_declares_its_sourced_tick_cadence(self, darius_data) -> None:
        """The JSON's per-tick arrays are quarters of the 5s totals
        (test-locked above), so the bleed ticks every 1.25 seconds —
        the cadence the engine uses to author bleed tick events."""
        dot = _abilities(darius_data)["passive"]["stacking_dot"]
        assert dot["tick_interval"] == pytest.approx(1.25)


class TestStartingHemorrhageStacks:
    """``starting_hemorrhage_stacks`` seeds ONE fight state.

    The target's stack count and Noxian Might are not two inputs:
    applying the 5th stack IS what grants the steroid, so the option has
    to drive R's scaling, the bleed's rate and the buff window together.
    """

    def test_default_opens_on_a_stacked_target(self, darius_data) -> None:
        dot = _abilities(darius_data)["passive"]["stacking_dot"]
        assert dot["starting_stacks"] == P_BLEED_MAX_STACKS

    def test_option_seeds_the_timeline(self, darius_data) -> None:
        abilities = _abilities(darius_data, starting_hemorrhage_stacks=2)
        assert abilities["passive"]["stacking_dot"]["starting_stacks"] == 2

    def test_option_is_clamped_to_the_stack_range(self, darius_data) -> None:
        for given, expected in ((99, P_BLEED_MAX_STACKS), (-3, 0)):
            abilities = _abilities(darius_data, starting_hemorrhage_stacks=given)
            assert abilities["passive"]["stacking_dot"]["starting_stacks"] == expected

    def test_r_always_defers_to_the_timeline(self, darius_data) -> None:
        """R never pins its own count at parse time, at any option value.

        This is the invariant that makes the two states inseparable: if R
        could carry a stack count of its own, it could out-vote the
        timeline that also decides whether Noxian Might is up.
        """
        for stacks in range(P_BLEED_MAX_STACKS + 1):
            r = _abilities(darius_data, starting_hemorrhage_stacks=stacks)["R"]
            assert r["parts"][1].dot_stack_scaled is True


class TestStackedOpenerGrantsNoxianMight:
    """Regression: 5 stacks on the target implies Might is up.

    Reported from in-game testing: the only way to get a target to 5
    Hemorrhage stacks is to apply them, and applying the 5th grants
    Noxian Might. A one-rotation fight that scaled R off 5 stacks while
    pricing every ability at unbuffed AD described a state the game
    cannot reach, understating Q/W/R by the steroid's whole +280 AD at
    level 20.
    """

    @staticmethod
    def _one_rotation(darius_data, **options) -> dict:
        stats = _stats()
        abilities = parse_champion_abilities(
            copy.deepcopy(darius_data),
            LEVEL,
            0.0,
            champion_stats=dict(stats),
            target_stats={"target_max_health": 1e9},
            champion_options=options,
        )
        return calculate_fight_damage(
            dict(stats),
            abilities,
            [],
            FightConfig(
                target_health=1e9,
                target_armor=0.0,
                target_magic_resistance=0.0,
                fight_duration_seconds=5.0,
                auto_attack_uptime=0.0,
                one_rotation=True,
                deterministic=True,
            ),
        )

    def test_default_opener_prices_every_ability_buffed(self, darius_data) -> None:
        breakdown = self._one_rotation(darius_data)["breakdown"]
        # R: 5 stacks AND the steroid its 5th stack granted.
        assert breakdown["R"]["total_damage"] == pytest.approx(1320.0)
        assert breakdown["Q"]["total_damage"] == pytest.approx(929.255)

    def test_unstacked_opener_gets_no_steroid(self, darius_data) -> None:
        breakdown = self._one_rotation(darius_data, starting_hemorrhage_stacks=0)[
            "breakdown"
        ]
        assert breakdown["Q"]["total_damage"] == pytest.approx(537.255)
        assert breakdown["R"]["total_damage"] < 1320.0

    def test_stacked_opener_strictly_beats_the_unstacked_one(self, darius_data) -> None:
        """Monotonicity: more starting stacks never means less damage."""
        totals = [
            self._one_rotation(darius_data, starting_hemorrhage_stacks=stacks)[
                "total_damage"
            ]
            for stacks in range(P_BLEED_MAX_STACKS + 1)
        ]
        assert totals == sorted(totals)
        assert totals[-1] > totals[0]


# ---------------------------------------------------------------------------
# Fight integration
# ---------------------------------------------------------------------------


def _fight(darius_data, **overrides) -> dict:
    """Run Darius through the whole pipeline at the reference target."""
    params = {
        "target_health": 2500.0,
        "target_bonus_health": 0.0,
        "target_armor": 100.0,
        "target_magic_resistance": 50.0,
        "fight_duration_seconds": 10.0,
        "auto_attack_uptime": 1.0,
        "one_rotation": False,
        "include_actives": True,
        "cast_order": None,
        "auto_attacks_only": False,
        "ability_ranks": None,
        "champion_options": None,
        "deterministic": True,
    }
    params.update(overrides)
    return run_fight(copy.deepcopy(darius_data), LEVEL, [], FightParams(**params))


def _engine_fight(
    darius_data,
    *,
    suppress_might: bool,
    duration: float,
    attack_speed: float = 1.0,
    starting_stacks: int = 0,
) -> dict:
    """Fight the parsed kit directly, optionally without Noxian Might.

    The suppression path is the engine's own control: dropping the
    ``stack_triggered_buff`` key leaves every other input identical.

    Opens UNSTACKED by default, unlike the shipped option: every test
    below probes how stacks accrue during the fight, which a pre-stacked
    target (already at the cap) would flatten out.
    """
    stats = _stats(bonus_ad=0.0)
    stats["attack_speed"] = attack_speed
    abilities = parse_champion_abilities(
        copy.deepcopy(darius_data),
        LEVEL,
        0.0,
        champion_stats=stats,
        target_stats={"target_max_health": 2500.0},
        champion_options={"starting_hemorrhage_stacks": starting_stacks},
    )
    if suppress_might:
        abilities["passive"].pop("stack_triggered_buff")
    return calculate_fight_damage(
        dict(stats),
        abilities,
        [],
        FightConfig(
            target_health=2500.0,
            target_armor=100.0,
            target_magic_resistance=50.0,
            fight_duration_seconds=duration,
            auto_attack_uptime=1.0,
            one_rotation=False,
            deterministic=True,
        ),
    )


class TestFightIntegration:
    """Every fight mode: one-rotation, timed, timed with autos off, and
    autos-only (where nothing but the E passive may fire)."""

    def test_one_rotation_casts_everything_once(self, darius_data) -> None:
        result = _fight(
            darius_data,
            one_rotation=True,
            auto_attack_uptime=0.0,
            fight_duration_seconds=5.0,
        )
        breakdown = result["breakdown"]
        for key in ("Q", "W", "E", "R"):
            assert breakdown[key]["casts"] == 1
        # Q, W's forced swing and R each apply one stack, all at t=0.
        assert breakdown["stacking_dot_passive"]["count"] == 3

    def test_one_rotation_w_carries_its_forced_swing(self, darius_data) -> None:
        """With no auto stream, W's row must carry the consumed basic
        attack, not just the bonus (the Blitzcrank/Caitlyn rule).

        Opened unstacked so no Noxian Might window distorts the swing:
        the steroid is priced per cast, so it is deliberately absent from
        the ``champion_stats`` AD this expectation is built from.
        """
        result = _fight(
            darius_data,
            one_rotation=True,
            auto_attack_uptime=0.0,
            fight_duration_seconds=5.0,
            champion_options={"starting_hemorrhage_stacks": 0},
        )
        assert result["breakdown"]["auto_attacks"]["count"] == 0
        # 0.6 x AD bonus + a full AD swing, mitigated by 60 effective armor.
        attack_damage = result["champion_stats"]["attack_damage"]
        expected = (0.6 * attack_damage + attack_damage) * 100.0 / 160.0
        assert result["breakdown"]["W"]["total_damage"] == pytest.approx(expected)

    def test_timed_zero_uptime_still_forces_the_w_swing(self, darius_data) -> None:
        """The Caitlyn/Vayne/Blitzcrank hole: autos off must not zero W."""
        result = _fight(darius_data, auto_attack_uptime=0.0)
        assert result["breakdown"]["auto_attacks"]["count"] == 0
        assert result["breakdown"]["W"]["casts"] > 0
        assert result["breakdown"]["W"]["total_damage"] > 0

    def test_autos_only_fires_nothing_but_the_e_passive(self, darius_data) -> None:
        """The Corki zero-cast hole: no spell that was never cast may act,
        but E's armor pen is a passive and still applies."""
        result = _fight(darius_data, auto_attacks_only=True)
        breakdown = result["breakdown"]
        for key in ("Q", "W", "E", "R"):
            assert breakdown[key]["casts"] == 0
            assert breakdown[key]["total_damage"] == pytest.approx(0.0)
        assert result["champion_stats"]["armor_penetration_percent"] == 40.0
        assert result["effective_armor"] == pytest.approx(60.0)
        # Autos alone still apply Hemorrhage, so the bleed runs.
        assert (
            breakdown["stacking_dot_passive"]["count"]
            == breakdown["auto_attacks"]["count"]
        )

    def test_e_armor_pen_reaches_physical_damage_but_not_r(self, darius_data) -> None:
        """40% armor pen takes 100 armor to 60 for Q/W/autos; R is true
        damage and must be completely unaffected.

        Opened unstacked to isolate penetration from the Noxian Might
        window, which would otherwise move both numbers at once.
        """
        result = _fight(
            darius_data,
            one_rotation=True,
            auto_attack_uptime=0.0,
            fight_duration_seconds=5.0,
            champion_options={"starting_hemorrhage_stacks": 0},
        )
        assert result["champion_stats"]["armor_penetration_percent"] == 40.0
        assert result["effective_armor"] == pytest.approx(60.0)
        attack_damage = result["champion_stats"]["attack_damage"]
        q_raw = 170.0 + 1.4 * attack_damage
        assert result["breakdown"]["Q"]["total_damage"] == pytest.approx(
            q_raw * 100.0 / 160.0
        )
        # R at the derived 2 stacks, undiminished by armor or its pen.
        assert result["breakdown"]["R"]["total_damage"] == pytest.approx(
            375.0 + 2 * 75.0
        )


class TestNoxianMightPricing:
    """Hand-validated damage with Noxian Might active (+280 bonus AD at
    level 20, so bonus AD 100 -> 380 and total AD -> 542.325)."""

    @staticmethod
    def _might(abilities: dict) -> float:
        return abilities["passive"]["stack_triggered_buff"]["bonus_attack_damage"]

    def test_q_and_w_repriced_by_their_declared_ratios(self, darius_data) -> None:
        abilities = _abilities(darius_data)
        might = self._might(abilities)
        q, w = abilities["Q"]["parts"][0], abilities["W"]["parts"][0]
        assert q.amount + q.bonus_ad_ratio * might == pytest.approx(929.255)
        assert w.amount + w.bonus_ad_ratio * might == pytest.approx(325.395)

    def test_five_stack_bleed_under_might(self, darius_data) -> None:
        """Every stack's rate rises: (32 + 0.30 x 380) x 5 = 730 over 5s."""
        abilities = _abilities(darius_data)
        dot = abilities["passive"]["stacking_dot"]
        buffed_single = dot["single_stack_raw"] + dot[
            "single_stack_bonus_ad_ratio"
        ] * self._might(abilities)
        assert buffed_single == pytest.approx(146.0)
        assert buffed_single * P_BLEED_MAX_STACKS == pytest.approx(730.0)

    def test_r_at_five_stacks_inside_a_window(self, darius_data) -> None:
        """End-to-end: opening unstacked, a fast auto stream reaches 5
        stacks before R, which then prices at 750 + 1.50 x 380 = 1320
        true — the count derived, not asserted by the option."""
        stats = _stats()
        stats["attack_speed"] = 5.0
        abilities = parse_champion_abilities(
            copy.deepcopy(darius_data),
            LEVEL,
            0.0,
            champion_stats=dict(stats),
            target_stats={"target_max_health": 1e9},
            champion_options={"starting_hemorrhage_stacks": 0},
        )
        result = calculate_fight_damage(
            dict(stats),
            abilities,
            [],
            FightConfig(
                target_health=1e9,
                target_armor=0.0,
                target_magic_resistance=0.0,
                fight_duration_seconds=12.0,
                auto_attack_uptime=1.0,
                one_rotation=False,
                deterministic=True,
            ),
        )
        assert result["breakdown"]["R"]["total_damage"] == pytest.approx(1320.0)
        # Q's first cast lands before the window, the next two inside it.
        assert result["breakdown"]["Q"]["casts"] == 3
        assert result["breakdown"]["Q"]["total_damage"] == pytest.approx(
            537.255 + 2 * 929.255
        )


class TestNoxianMight:
    """Might is derived from the hit timeline, not toggled."""

    def test_sustained_fight_triggers_a_window(self, darius_data) -> None:
        result = _fight(darius_data)
        assert any(note.startswith("Noxian Might:") for note in result["notes"])

    def test_might_strictly_increases_damage(self, darius_data) -> None:
        """A fight long enough to reach 5 stacks must beat the same fight
        with Might suppressed."""
        with_might = _engine_fight(darius_data, suppress_might=False, duration=10.0)
        without = _engine_fight(darius_data, suppress_might=True, duration=10.0)
        assert with_might["total_damage"] > without["total_damage"]

    def test_short_fight_never_reaches_five_stacks(self, darius_data) -> None:
        """Below the trigger the two models must agree exactly — Might
        may never leak damage into a fight that never earned it."""
        with_might = _engine_fight(darius_data, suppress_might=False, duration=1.0)
        without = _engine_fight(darius_data, suppress_might=True, duration=1.0)
        assert with_might["total_damage"] == pytest.approx(without["total_damage"])

    def test_might_lifts_autos_bleed_and_casts(self, darius_data) -> None:
        """Every timeline-priced row grows, not just the ability rows."""
        with_might = _engine_fight(darius_data, suppress_might=False, duration=10.0)
        without = _engine_fight(darius_data, suppress_might=True, duration=10.0)
        for key in ("auto_attacks", "stacking_dot_passive"):
            assert (
                with_might["breakdown"][key]["total_damage"]
                > without["breakdown"][key]["total_damage"]
            )


class TestDerivedStackMonotonicity:
    """Property, not a pinned number (the Corki lesson): the Hemorrhage
    stack count R sees can only grow as the fight gets longer."""

    @staticmethod
    def _r_stacks(result: dict) -> int | None:
        """Recover R's stack count from its row, or None if R never cast.

        With Might suppressed and no bonus AD, R = 375 + N x 75 at rank 3.
        """
        row = result["breakdown"]["R"]
        if row["casts"] == 0:
            return None
        stacks = (row["total_damage"] - 375.0) / 75.0
        assert stacks == pytest.approx(round(stacks))
        return round(stacks)

    def test_stacks_are_non_decreasing_in_fight_length(self, darius_data) -> None:
        """R's cast time is fixed, so the count climbs as the fight gets
        long enough to fit the autos before it, then holds — it must
        never fall back."""
        counts = [
            self._r_stacks(
                _engine_fight(darius_data, suppress_might=True, duration=duration)
            )
            for duration in (1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 10.0, 15.0)
        ]
        # A 1s fight ends before R's 1.4s cast slot: no cast, no count.
        assert counts[0] is None
        cast = [count for count in counts if count is not None]
        assert cast == sorted(cast)
        assert all(0 <= count <= P_BLEED_MAX_STACKS for count in cast)

    def test_stacks_are_non_decreasing_in_auto_density(self, darius_data) -> None:
        """More autos landing before R means more stacks on the target,
        up to the 5-stack cap — the derivation really reads the
        timeline rather than reporting a constant."""
        counts = [
            self._r_stacks(
                _engine_fight(
                    darius_data,
                    suppress_might=True,
                    duration=10.0,
                    attack_speed=attack_speed,
                )
            )
            for attack_speed in (0.2, 0.5, 1.0, 2.0, 4.0, 8.0)
        ]
        assert counts == sorted(counts)
        assert counts[0] < counts[-1]  # the sweep moves
        assert counts[-1] == P_BLEED_MAX_STACKS  # and saturates at the cap

    def test_total_damage_is_non_decreasing_in_fight_length(self, darius_data) -> None:
        totals = [
            _engine_fight(darius_data, suppress_might=False, duration=duration)[
                "total_damage"
            ]
            for duration in (1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 10.0, 15.0)
        ]
        assert totals == sorted(totals)


class TestReviewedCrowdControl:
    """Darius' reviewed crowd control, and the slot that still withholds.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Darius")
        assert darius.MODULE_CC == {"Q": "none", "W": "slow"}
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert "slow the target by 90% for 1 second" in cc_review.slot_text(data, "W")

    def test_noxian_guillotines_fear_never_reaches_the_champion_it_damages(self):
        """R's fear is a kill trigger on minions and monsters, not the target."""
        text = cc_review.slot_text(cc_review.kit("Darius"), "R")
        assert "darius fears nearby minions and monsters for 3 seconds" in text
        assert "R" not in darius.MODULE_CC

    def test_r_withholds_because_its_stack_term_repeats(self, darius_data):
        """A two-part row is certifiable now; a repeated part is not.

        R's second part hits once per Hemorrhage stack, and a part that
        repeats is a schedule the cache gives no cadence for - the stacks
        land together, which no ``count``-based part can state.
        """
        base, per_stack = _abilities(darius_data)["R"]["parts"]

        assert base.count == 1
        assert per_stack.dot_stack_scaled is True
        assert per_stack.count == P_BLEED_MAX_STACKS

    def test_the_unreviewable_slot_keeps_the_fight_coarse(self):
        assert cc_review.unreviewed_ability_slots("Darius") == ["R"]
        coverage = cc_review.fimbulwinter_coverage("Darius")
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]
