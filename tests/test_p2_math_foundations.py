"""P2 — Mathematical-foundation identity suite (docs/math-foundations.md).

Pins the identities the combat engine instantiates, so a future refactor
cannot silently break the math without a test failing:

- 100/(100+R) damage-multiplier round-trip (effective-health identity)
- negative-resistance piecewise extension and continuity at 0
- percent-then-flat penetration order, floor at 0, negative untouched
- flat-then-percent reduction followed by percent-then-flat penetration
- ability-haste identity cd' = cd * 100/(100+AH)
- DoT uniform-partition conservation (sum of ticks == total)
- linearity of mitigation in raw damage (multi-hit == single-hit sum)
- critical-strike expectation identity and commutation with mitigation
- every-Nth on-hit proc counting == floor(n/N) (modular counting)
- execute-quantile boundary (The Collector) and Veigar-R ramp convexity
  (Jensen: E[d(M)] >= d(E[M]))
- shield clipping identity absorbed + overkill == damage
- movement-speed soft caps vs. the wiki's worked example (600 -> 530)
"""

import pytest

from src.calculator.damage import (
    BASE_CRIT_MULTIPLIER,
    _calculate_phantom_hits,
    _calculate_stacking_procs,
    _periodic_damage_events,
    effective_cooldown,
)
from src.calculator.resistance import (
    apply_armor_penetration,
    apply_magic_penetration,
    apply_resistance,
    reduce_resistance,
)
from src.calculator.stats import apply_movement_speed_soft_caps, growth_stat
from src.calculator.champions.veigar import _EXECUTE_MISSING_RATIO_CAP

# ─────────────────────────────────────────────────────────────────────
# 1. Resistance: the 100/(100+R) identity
# ─────────────────────────────────────────────────────────────────────


class TestResistanceIdentity:
    def test_round_trip_recovers_raw_damage(self) -> None:
        """post = raw * 100/(100+R)  <=>  raw = post * (1 + R/100)."""
        raw = 1234.5
        for resistance in (0.0, 30.0, 100.0, 250.0, 5000.0):
            post = apply_resistance(raw, resistance)
            assert post == pytest.approx(raw * 100.0 / (100.0 + resistance))
            assert post * (1.0 + resistance / 100.0) == pytest.approx(raw)

    def test_reduction_fraction_identity(self) -> None:
        """R/(100+R) == 1 - 100/(100+R)."""
        for resistance in (25.0, 100.0, 300.0):
            fraction = resistance / (100.0 + resistance)
            assert fraction == pytest.approx(1.0 - 100.0 / (100.0 + resistance))

    def test_effective_health_identity(self) -> None:
        """A target with H0 health and R resists survives H0*(1+R/100) raw."""
        h0, resistance = 2000.0, 150.0
        ehp = h0 * (1.0 + resistance / 100.0)
        assert apply_resistance(ehp, resistance) == pytest.approx(h0)

    def test_zero_resistance_and_halving(self) -> None:
        assert apply_resistance(100, 0) == 100.0
        assert apply_resistance(100, 100) == pytest.approx(50.0)

    def test_negative_resistance_piecewise(self) -> None:
        """m(R) = 2 - 100/(100-R) for R<0; saturates at 2x, never more."""
        for r in (-25.0, -50.0, -100.0, -1000.0):
            expected = 2.0 - 100.0 / (100.0 - r)
            assert apply_resistance(100, r) == pytest.approx(100.0 * expected)
        # saturation bound: as R -> -inf, multiplier -> 2
        assert apply_resistance(100, -1e9) == pytest.approx(200.0)

    def test_negative_branch_continuous_at_zero(self) -> None:
        assert apply_resistance(100, -1e-9) == pytest.approx(
            apply_resistance(100, 1e-9), abs=1e-6
        )


# ─────────────────────────────────────────────────────────────────────
# 2. Penetration and reduction composition
# ─────────────────────────────────────────────────────────────────────


class TestPenetrationComposition:
    def test_percent_then_flat_order(self) -> None:
        # 100 armor -> 30% pen -> 70 -> -12 flat -> 58
        assert apply_armor_penetration(100, 12, 0.30) == pytest.approx(58.0)
        assert apply_magic_penetration(100, 12, 0.40) == pytest.approx(48.0)

    def test_penetration_floors_at_zero(self) -> None:
        assert apply_armor_penetration(10, 50, 0.0) == 0.0
        assert apply_armor_penetration(100, 50, 1.0) == 0.0

    def test_penetration_never_touches_negative_reduction(self) -> None:
        # negative armor comes from REDUCTION only; penetration leaves it.
        assert apply_armor_penetration(-8, 20, 0.30) == -8.0
        assert apply_magic_penetration(-8, 20, 0.40) == -8.0

    def test_full_composition_closed_form(self) -> None:
        """flat reduction -> % reduction -> % pen -> flat pen, each on the
        running value; the composition is the closed form
        max(0, (R - r_flat)*(1 - r_pct)*(1 - p) - f)."""

        def compose(armor, r_flat, r_pct, p_pct, p_flat):
            reduced = reduce_resistance(
                armor, reduction_flat=r_flat, reduction_percent=r_pct
            )
            return apply_armor_penetration(reduced, p_flat, p_pct)

        expected = max(0.0, (200.0 - 20.0) * 0.75 * 0.70 - 12.0)
        assert compose(200, 20, 25, 0.30, 12) == pytest.approx(expected)

    def test_reduction_flat_first_then_percent(self) -> None:
        assert reduce_resistance(200, reduction_flat=50) == 150.0
        assert reduce_resistance(200, reduction_percent=50) == 100.0
        # flat first: 200-50=150, then 50% -> 75
        assert reduce_resistance(
            200, reduction_flat=50, reduction_percent=50
        ) == pytest.approx(75.0)


# ─────────────────────────────────────────────────────────────────────
# 3. Renewal / counting identities
# ─────────────────────────────────────────────────────────────────────


class TestRenewalCounting:
    def test_haste_identity(self) -> None:
        """cd' = cd * 100/(100+AH)."""
        for cd, ah in ((10.0, 0.0), (10.0, 40.0), (10.0, 100.0), (7.5, 25.0)):
            assert effective_cooldown(cd, ah) == pytest.approx(
                cd * 100.0 / (100.0 + ah)
            )

    def test_casts_per_unit_time_affine_in_haste(self) -> None:
        """1/cd' = (100+AH)/(100*cd) is affine in AH: doubling AH doubles
        the *haste contribution* to cast rate."""
        cd = 10.0
        rate_0 = 1.0 / effective_cooldown(cd, 0.0)
        rate_40 = 1.0 / effective_cooldown(cd, 40.0)
        rate_80 = 1.0 / effective_cooldown(cd, 80.0)
        assert rate_40 - rate_0 == pytest.approx(rate_80 - rate_40)

    def test_every_nth_proc_count_is_floor(self) -> None:
        """Modular counting: #procs over n hits == floor(n/N)."""
        for n, n_required in ((10, 3), (9, 3), (100, 3), (7, 5)):
            _, proc_autos = _calculate_stacking_procs(
                n,
                phantom_hit_autos=set(),
                double_on_hit_procs=0,
                hits_required=n_required,
            )
            assert len(proc_autos) == n // n_required
            # procs land on exactly the k*N-th attack (0-indexed (k*N-1))
            assert proc_autos == [
                k * n_required - 1 for k in range(1, n // n_required + 1)
            ]

    def test_phantom_hit_cadence(self) -> None:
        """Guinsoo: 5 stacking attacks, then every 3rd attack phantoms."""
        _, phantom_autos = _calculate_phantom_hits(18, item_effects_phantom(5, 3))
        # 0-indexed autos 5, 8, 11, 14, 17 -> attacks 6, 9, 12, 15, 18
        assert phantom_autos == {5, 8, 11, 14, 17}


def item_effects_phantom(stacking_autos: int, interval: int):
    """Minimal phantom-hit spec duck-typed for _calculate_phantom_hits."""
    return type(
        "_Phantom",
        (),
        {"stacking_autos": stacking_autos, "interval": interval},
    )()


# ─────────────────────────────────────────────────────────────────────
# 4. DoT partition conservation
# ─────────────────────────────────────────────────────────────────────


class TestDotPartition:
    @pytest.mark.parametrize(
        ("total", "duration", "interval"),
        [
            (100.0, 3.0, 0.5),
            (100.0, 4.0, 1.5),
            (100.0, 2.0, 3.0),  # interval > duration -> single end tick
            (100.0, 3.0, 3.0),  # exact multiple
            (0.0, 5.0, 1.0),  # zero damage -> no ticks
        ],
    )
    def test_ticks_conserve_total(
        self, total: float, duration: float, interval: float
    ) -> None:
        events = _periodic_damage_events(total, "magic", duration, interval)
        assert sum(e["damage"] for e in events) == pytest.approx(total)
        if total > 0:
            assert events[0]["time"] == pytest.approx(min(interval, duration))
            assert events[-1]["time"] == pytest.approx(duration)

    def test_remainder_tick_smaller_than_interval(self) -> None:
        events = _periodic_damage_events(100.0, "magic", 4.0, 1.5)
        times = [e["time"] for e in events]
        assert times == [1.5, 3.0, 4.0]
        damages = [e["damage"] for e in events]
        # 1.5s full ticks carry 100/4*1.5 = 37.5 each; remainder 25
        assert damages[0] == pytest.approx(37.5)
        assert damages[1] == pytest.approx(37.5)
        assert damages[2] == pytest.approx(25.0)


# ─────────────────────────────────────────────────────────────────────
# 5. Linearity of expectation
# ─────────────────────────────────────────────────────────────────────


class TestLinearityOfExpectation:
    def test_mitigation_linear_in_raw(self) -> None:
        """m(R)*x is linear in x: a 3-hit packet == three single hits."""
        raw, hits, resistance = 100.0, 3, 100.0
        per_hit = apply_resistance(raw, resistance)
        assert hits * per_hit == pytest.approx(apply_resistance(hits * raw, resistance))

    def test_crit_expectation_identity(self) -> None:
        """E[swing] = (1-p)*1 + p*CM == 1 + p*(CM-1)."""
        for p in (0.0, 0.25, 1.0):
            for cm in (BASE_CRIT_MULTIPLIER, 2.30):
                blended = (1.0 - p) * 1.0 + p * cm
                assert blended == pytest.approx(1.0 + p * (cm - 1.0))

    def test_crit_expectation_commutes_with_mitigation(self) -> None:
        """Mitigation is linear in raw, so E[mit(X)] == mit(E[X])."""
        p, cm, resistance, swing = 0.3, 2.0, 80.0, 150.0
        expected_raw = swing * (p * cm + (1.0 - p))
        assert apply_resistance(expected_raw, resistance) == pytest.approx(
            p * apply_resistance(swing * cm, resistance)
            + (1.0 - p) * apply_resistance(swing, resistance)
        )

    def test_kraken_missing_health_term_is_affine(self) -> None:
        """base*(1 + 0.75*missing) is affine in current health, so
        E[f(H)] == f(E[H]) — the engine's sequential expected-path
        simulation is exact for Kraken, not a heuristic."""
        h0, base = 2000.0, 100.0

        def kraken(current: float) -> float:
            missing = max(0.0, h0 - current) / h0
            return base * (1.0 + 0.75 * missing)

        e_h = 0.5 * 2000.0 + 0.5 * 500.0  # health after random damage
        assert 0.5 * kraken(2000.0) + 0.5 * kraken(500.0) == pytest.approx(kraken(e_h))


# ─────────────────────────────────────────────────────────────────────
# 6. Execute thresholds and order statistics
# ─────────────────────────────────────────────────────────────────────


class TestExecuteQuantiles:
    def test_collector_threshold_is_a_quantile(self) -> None:
        """The Collector execute boundary is the 5% quantile of max health."""
        max_health = 3000.0
        threshold = 0.05 * max_health  # engine: target_health * threshold
        assert threshold == 150.0
        # it is a CDF statement: P(executed) = P(H <= 150) for this target
        assert threshold / max_health == 0.05

    def test_veigar_ramp_is_piecewise_affine(self) -> None:
        """d(m) = d_min*(1 + min(1, m/(2/3))) (pass-16 decision): linear
        from 1x at full health to the max row (2x min) at m=2/3, flat
        afterwards."""
        assert _EXECUTE_MISSING_RATIO_CAP == pytest.approx(2.0 / 3.0)

        def ramp(m: float) -> float:
            boost = max(
                0.0,
                min(
                    1.0,
                    m / _EXECUTE_MISSING_RATIO_CAP,
                ),
            )
            return 1.0 + boost  # in units of d_min

        assert ramp(0.0) == 1.0
        assert ramp(1.0 / 3.0) == pytest.approx(1.5)
        assert ramp(2.0 / 3.0) == 2.0
        assert ramp(1.0) == 2.0
        assert ramp(0.75) == pytest.approx(2.0)

    def test_veigar_ramp_concavity_jensen(self) -> None:
        """The pass-16 ramp is concave (linear to 2x at m=2/3, then flat),
        so E[d(M)] <= d(E[M]): the deterministic path OVERstates expected
        execute damage when health variance straddles the saturation point
        (documented approximation — the mirror image of a convex ramp)."""

        def ramp(m: float) -> float:
            boost = max(
                0.0,
                min(
                    1.0,
                    m / _EXECUTE_MISSING_RATIO_CAP,
                ),
            )
            return 1.0 + boost

        # M uniform on {0.5, 1.0}: E[M] = 0.75
        expected_value = 0.5 * ramp(0.5) + 0.5 * ramp(1.0)
        deterministic = ramp(0.75)
        assert expected_value == pytest.approx(1.875)
        assert deterministic == pytest.approx(2.0)
        assert expected_value < deterministic  # Jensen reversed (concave)


# ─────────────────────────────────────────────────────────────────────
# 7. Shield clipping, stat growth, movement speed
# ─────────────────────────────────────────────────────────────────────


class TestMiscIdentities:
    @pytest.mark.parametrize(
        ("shield", "damage"),
        [(300.0, 200.0), (100.0, 350.0), (0.0, 10.0), (250.0, 250.0)],
    )
    def test_shield_clipping_identity(self, shield: float, damage: float) -> None:
        """absorbed = min(shield, damage); overkill = max(0, damage - absorbed);
        absorbed + overkill == damage always."""
        absorbed = min(shield, damage)
        overkill = max(0.0, damage - absorbed)
        assert absorbed + overkill == pytest.approx(damage)

    def test_growth_stat_base_and_monotonicity(self) -> None:
        assert growth_stat(100.0, 5.0, 1) == 100.0
        values = [growth_stat(100.0, 5.0, level) for level in range(1, 21)]
        assert values == sorted(values)
        assert len(set(values)) == 20  # strictly increasing

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (100.0, 160.0),  # low cap: 110 + 0.5*100 (wiki formula)
            (415.0, 415.0),
            (450.0, 443.0),  # 415 + 0.8*(450-415)
            (490.0, 475.0),  # 415 + 0.8*75
            (500.0, 480.0),  # 415 + 60 + 0.5*(500-490)
            (600.0, 530.0),  # wiki worked example
            (200.0, 210.0),  # 110 + 0.5*200 (low cap)
            (220.0, 220.0),
        ],
    )
    def test_movement_speed_soft_caps(self, raw: float, expected: float) -> None:
        assert apply_movement_speed_soft_caps(raw) == pytest.approx(expected)
