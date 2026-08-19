"""Issue #159 — contract tests for the one shield/health transition kernel.

``shield_ledger.absorb`` is the single owner of absorption order and state
mutation.  These tests exercise it directly, independently of the walks that
drive it, so a semantic change has to be made here first.
"""

from src.calculator.shield_ledger import (
    ShieldPools,
    ThresholdHealth,
    ThresholdShield,
    TimedShield,
    absorb,
    expire_temporary_max_health,
    expire_threshold_health,
    expire_timed,
    is_inert,
)


def _pools(health: float = 2000.0, **overrides) -> ShieldPools:
    """A 2000-max-HP defender with no shields unless the test grants some."""
    return ShieldPools(health=health, max_health=2000.0, **overrides)


class TestHealthDamage:
    """Damage with no shield in play lands on health and floors at zero."""

    def test_plain_damage_reduces_health(self):
        pools = _pools()
        outcome = absorb(pools, 300.0, "physical", 0.0)
        assert pools.health == 1700.0
        assert outcome.applied_to_health == 300.0
        assert outcome.absorbed == 0.0
        assert outcome.overkill == 0.0

    def test_damage_beyond_health_is_overkill_not_effective_hp(self):
        pools = _pools()
        outcome = absorb(pools, 2500.0, "physical", 0.0)
        assert pools.health == 0.0
        assert outcome.applied_to_health == 2000.0
        assert outcome.overkill == 500.0
        assert pools.overkill == 500.0
        assert pools.health_damage == 2000.0

    def test_damage_taken_records_the_pre_absorption_amount(self):
        pools = _pools(general_shield=100.0)
        absorb(pools, 300.0, "magic", 0.0)
        assert pools.damage_taken == 300.0


class TestTypedShields:
    """A typed pool absorbs only its own damage type, before the general pool."""

    def test_magic_shield_absorbs_magic_damage_first(self):
        pools = _pools(magic_shield=100.0, general_shield=50.0)
        outcome = absorb(pools, 300.0, "magic", 0.0)
        assert pools.magic_shield == 0.0
        assert pools.general_shield == 0.0
        assert outcome.absorbed == 150.0
        assert outcome.applied_to_health == 150.0
        assert pools.health == 1850.0

    def test_physical_shield_absorbs_physical_damage_first(self):
        pools = _pools(physical_shield=100.0, general_shield=50.0)
        outcome = absorb(pools, 120.0, "physical", 0.0)
        assert pools.physical_shield == 0.0
        assert pools.general_shield == 30.0
        assert outcome.absorbed == 120.0
        assert outcome.applied_to_health == 0.0

    def test_magic_shield_does_not_absorb_physical_damage(self):
        pools = _pools(magic_shield=500.0)
        outcome = absorb(pools, 300.0, "physical", 0.0)
        assert pools.magic_shield == 500.0
        assert outcome.absorbed == 0.0
        assert outcome.applied_to_health == 300.0

    def test_true_damage_ignores_typed_pools_but_not_the_general_pool(self):
        pools = _pools(magic_shield=500.0, physical_shield=500.0, general_shield=100.0)
        outcome = absorb(pools, 300.0, "true", 0.0)
        assert pools.magic_shield == 500.0
        assert pools.physical_shield == 500.0
        assert pools.general_shield == 0.0
        assert outcome.absorbed == 100.0
        assert outcome.applied_to_health == 200.0

    def test_shield_absorbed_total_accumulates_typed_and_general(self):
        pools = _pools(magic_shield=100.0, general_shield=50.0)
        absorb(pools, 300.0, "magic", 0.0)
        assert pools.shield_absorbed == 150.0

    def test_zero_shield_pools_leave_the_walk_at_plain_subtraction(self):
        pools = _pools()
        absorb(pools, 300.0, "magic", 0.0)
        assert pools.shield_absorbed == 0.0
        assert pools.health == 1700.0

    def test_each_pool_reports_its_own_absorbed_total(self):
        pools = _pools(magic_shield=100.0, physical_shield=40.0, general_shield=50.0)
        absorb(pools, 300.0, "magic", 0.0)
        absorb(pools, 30.0, "physical", 0.0)
        assert pools.magic_absorbed == 100.0
        assert pools.general_absorbed == 50.0
        assert pools.physical_absorbed == 30.0


class TestTimedShields:
    """Timed grants expire on their sourced duration and drain first."""

    def test_expiry_removes_the_unused_amount_from_its_pool(self):
        pools = _pools(general_shield=200.0)
        pools.timed.append(TimedShield(amount=200.0, expires_at=3.0))
        expire_timed(pools, 3.0)
        assert pools.general_shield == 0.0
        assert pools.shield_expired == 200.0
        assert pools.timed == []

    def test_a_shield_still_inside_its_window_survives(self):
        pools = _pools(general_shield=200.0)
        pools.timed.append(TimedShield(amount=200.0, expires_at=3.0))
        expire_timed(pools, 2.0)
        assert pools.general_shield == 200.0
        assert pools.shield_expired == 0.0

    def test_absorb_expires_lapsed_shields_before_absorbing(self):
        pools = _pools(general_shield=200.0)
        pools.timed.append(TimedShield(amount=200.0, expires_at=3.0))
        outcome = absorb(pools, 100.0, "physical", 4.0)
        assert outcome.absorbed == 0.0
        assert outcome.applied_to_health == 100.0
        assert pools.shield_expired == 200.0

    def test_earliest_expiring_timed_shield_drains_before_later_ones(self):
        pools = _pools(general_shield=300.0)
        pools.timed.append(TimedShield(amount=200.0, expires_at=9.0, source="late"))
        pools.timed.append(TimedShield(amount=100.0, expires_at=2.0, source="early"))
        absorb(pools, 100.0, "physical", 1.0)
        assert [shield.source for shield in pools.timed] == ["late"]
        assert pools.general_shield == 200.0

    def test_timed_shields_drain_before_the_untimed_remainder(self):
        pools = _pools(general_shield=300.0)
        pools.timed.append(TimedShield(amount=100.0, expires_at=9.0))
        absorb(pools, 250.0, "physical", 1.0)
        # The 100 timed grant went first, so 150 came out of the untimed pool.
        assert pools.general_shield == 50.0
        assert pools.timed == []

    def test_a_timed_shield_belongs_to_the_pool_it_names(self):
        pools = _pools(magic_shield=150.0)
        pools.timed.append(TimedShield(amount=150.0, expires_at=9.0, pool="magic"))
        absorb(pools, 100.0, "physical", 1.0)
        assert pools.magic_shield == 150.0
        assert pools.timed[0].amount == 150.0


def _steraks(amount: float = 600.0) -> ThresholdShield:
    """Sterak's-style Lifeline: any damage type, 30% of a 2000-HP defender."""
    return ThresholdShield(
        amount=amount, health_threshold=600.0, duration=4.5, damage_type="all"
    )


class TestThresholdShield:
    """Lifeline arms before the damage that would cross its threshold."""

    def test_it_does_not_arm_above_the_threshold(self):
        pools = _pools(threshold_shield=_steraks())
        absorb(pools, 100.0, "physical", 0.0)
        assert pools.threshold_shield.triggered is False
        assert pools.general_shield == 0.0
        assert pools.health == 1900.0

    def test_it_arms_and_blocks_the_very_hit_that_crossed(self):
        pools = _pools(threshold_shield=_steraks())
        outcome = absorb(pools, 1500.0, "physical", 0.0)
        assert pools.threshold_shield.triggered is True
        assert outcome.threshold_shield_triggered is True
        # 600 of the 1500 was eaten by the shield it just armed.
        assert outcome.absorbed == 600.0
        assert outcome.applied_to_health == 900.0
        assert pools.health == 1100.0

    def test_it_arms_only_once(self):
        pools = _pools(threshold_shield=_steraks())
        absorb(pools, 1500.0, "physical", 0.0)
        absorb(pools, 400.0, "physical", 1.0)
        assert pools.general_shield == 0.0
        assert pools.health == 700.0

    def test_the_armed_shield_expires_on_its_sourced_duration(self):
        pools = _pools(health=700.0, threshold_shield=_steraks())
        absorb(pools, 150.0, "physical", 0.0)
        assert pools.general_shield == 450.0
        outcome = absorb(pools, 100.0, "physical", 5.0)
        assert pools.shield_expired == 450.0
        assert outcome.absorbed == 0.0

    def test_a_magic_lifeline_absorbs_only_magic_damage(self):
        """Maw of Malmortius' sourced shield absorbs magic damage only."""
        maw = ThresholdShield(
            amount=400.0, health_threshold=600.0, duration=3.0, damage_type="magic"
        )
        pools = _pools(health=700.0, threshold_shield=maw)
        outcome = absorb(pools, 150.0, "magic", 0.0)
        assert maw.triggered is True
        assert outcome.absorbed == 150.0
        assert pools.magic_shield == 250.0
        assert pools.health == 700.0
        # A later physical hit cannot touch a magic Lifeline.
        outcome = absorb(pools, 100.0, "physical", 1.0)
        assert outcome.absorbed == 0.0
        assert pools.magic_shield == 250.0
        assert pools.health == 600.0

    def test_a_magic_lifeline_never_arms_on_physical_damage(self):
        maw = ThresholdShield(
            amount=400.0, health_threshold=600.0, duration=3.0, damage_type="magic"
        )
        pools = _pools(threshold_shield=maw)
        absorb(pools, 1500.0, "physical", 0.0)
        assert maw.triggered is False
        assert pools.health == 500.0

    def test_venom_cuts_the_granted_non_magic_shield(self):
        pools = _pools(threshold_shield=_steraks(), venom_factor=0.5)
        absorb(pools, 1450.0, "physical", 0.0)
        # 600 * 0.5 granted, all of it consumed by the same hit.
        assert pools.health == 2000.0 - 1450.0 + 300.0

    def test_damage_landing_exactly_on_the_threshold_does_not_arm(self):
        """Sourced as damage that would reduce you *below* the threshold."""
        pools = _pools(threshold_shield=_steraks())
        absorb(pools, 1400.0, "physical", 0.0)
        assert pools.threshold_shield.triggered is False
        assert pools.health == 600.0

    def test_lifeline_absorption_is_reported_apart_from_its_pool(self):
        """The public receipt splits threshold from general absorption."""
        pools = _pools(health=700.0, general_shield=100.0, threshold_shield=_steraks())
        outcome = absorb(pools, 700.0, "physical", 0.0)
        # The armed grant is timed, so it drains before the untimed pool.
        assert pools.threshold_absorbed == 600.0
        assert pools.general_absorbed == 100.0
        # Each absorbed unit is counted exactly once in the grand total.
        assert pools.shield_absorbed == 700.0
        assert outcome.applied_to_health == 0.0

    def test_a_general_shield_does_not_stop_the_threshold_from_arming(self):
        """Arming is judged on the damage surviving the damage type's pool."""
        pools = _pools(general_shield=1000.0, threshold_shield=_steraks())
        absorb(pools, 1500.0, "physical", 0.0)
        assert pools.threshold_shield.triggered is True


class TestThresholdHealth:
    """Protoplasm-style Lifeline grants bonus health before the damage."""

    def _protoplasm(self) -> ThresholdHealth:
        return ThresholdHealth(bonus=300.0, heal=400.0, health_ratio=0.3, duration=5.0)

    def test_it_does_not_arm_above_the_threshold(self):
        pools = _pools(threshold_health=self._protoplasm())
        outcome = absorb(pools, 100.0, "magic", 0.0)
        assert outcome.threshold_health_triggered is False
        assert outcome.threshold_health_heal == 0.0
        assert pools.max_health == 2000.0

    def test_it_grants_bonus_health_before_the_crossing_damage_lands(self):
        pools = _pools(threshold_health=self._protoplasm())
        outcome = absorb(pools, 1500.0, "magic", 0.0)
        assert outcome.threshold_health_triggered is True
        assert pools.max_health == 2300.0
        assert pools.health == 2300.0 - 1500.0

    def test_the_sourced_heal_is_reported_for_the_caller_to_deliver(self):
        """Delivery differs by consumer (instant vs over-time), amount does not."""
        pools = _pools(threshold_health=self._protoplasm())
        outcome = absorb(pools, 1500.0, "magic", 0.0)
        assert outcome.threshold_health_heal == 400.0
        # Only the bonus health landed; the kernel never delivers the heal.
        assert pools.health == 2300.0 - 1500.0

    def test_it_arms_only_once(self):
        pools = _pools(threshold_health=self._protoplasm())
        absorb(pools, 1500.0, "magic", 0.0)
        second = absorb(pools, 100.0, "magic", 1.0)
        assert second.threshold_health_triggered is False
        assert pools.max_health == 2300.0

    def test_arming_stamps_the_window_the_grant_ends_at(self):
        pools = _pools(threshold_health=self._protoplasm())
        absorb(pools, 1500.0, "magic", 2.0)
        assert pools.threshold_health.expires_at == 7.0


def _protoplasm_health() -> ThresholdHealth:
    """The Protoplasm-shaped threshold health the expiry tests arm."""
    return ThresholdHealth(bonus=300.0, heal=400.0, health_ratio=0.3, duration=5.0)


class TestTemporaryMaximumExpiry:
    """The Wiki's maximum-health-decrease rule, and its one implementation.

    https://wiki.leagueoflegends.com/en-us/Health — "A decrease in maximum
    health does not change current health (unless it would exceed the new
    maximum health)", whose worked example is Protoplasm Harness itself.
    Cached by ``python scripts/decompose_wiki.py --fetch "Health"``.
    """

    def test_the_wiki_worked_example_verbatim(self):
        """300/1000 -> +200 max -> heal 200 -> expiry: 700 out of 1000."""
        pools = ShieldPools(health=300.0, max_health=1000.0)
        pools.max_health += 200.0
        pools.health += 200.0
        assert (pools.health, pools.max_health) == (500.0, 1200.0)
        pools.health += 200.0  # the passive's heal
        assert pools.health == 700.0

        removed = expire_temporary_max_health(pools, 200.0)

        assert removed == 200.0
        assert pools.max_health == 1000.0
        assert pools.health == 700.0

    def test_only_the_overhang_above_the_new_maximum_is_clamped(self):
        """A defender that never spent the grant loses exactly the overhang."""
        pools = ShieldPools(health=1200.0, max_health=1200.0)

        expire_temporary_max_health(pools, 200.0)

        assert (pools.health, pools.max_health) == (1000.0, 1000.0)

    def test_a_grant_larger_than_the_maximum_floors_at_zero(self):
        pools = ShieldPools(health=40.0, max_health=50.0)

        assert expire_temporary_max_health(pools, 500.0) == 50.0
        assert (pools.health, pools.max_health) == (0.0, 0.0)

    def test_the_lifeline_expires_at_its_window_and_not_before(self):
        pools = _pools(
            threshold_health=ThresholdHealth(
                bonus=300.0, heal=0.0, health_ratio=0.3, duration=5.0
            )
        )
        absorb(pools, 1500.0, "magic", 0.0)
        assert pools.max_health == 2300.0

        assert expire_threshold_health(pools, 4.999) == 0.0
        assert pools.max_health == 2300.0

        assert expire_threshold_health(pools, 5.0) == 300.0
        assert pools.max_health == 2000.0
        # Health was 800 of the raised 2300 and stays exactly where it was.
        assert pools.health == 800.0

    def test_an_unarmed_or_already_expired_lifeline_removes_nothing_twice(self):
        pools = _pools(threshold_health=_protoplasm_health())
        assert expire_threshold_health(pools, 99.0) == 0.0

        absorb(pools, 1500.0, "magic", 0.0)
        assert expire_threshold_health(pools, 99.0) == 300.0
        assert expire_threshold_health(pools, 99.0) == 0.0
        assert pools.max_health == 2000.0


class TestMixedMechanics:
    """Typed, general, timed, and both thresholds in one instance."""

    def test_full_order_is_typed_then_threshold_then_general_then_health(self):
        pools = _pools(
            magic_shield=100.0,
            general_shield=200.0,
            threshold_shield=_steraks(amount=500.0),
            threshold_health=ThresholdHealth(
                bonus=300.0, heal=400.0, health_ratio=0.3, duration=5.0
            ),
        )
        pools.timed.append(TimedShield(amount=200.0, expires_at=9.0))
        outcome = absorb(pools, 2000.0, "magic", 1.0)
        # 100 magic + 500 Lifeline + 200 general absorbed = 800.
        assert outcome.absorbed == 800.0
        assert pools.max_health == 2300.0
        assert outcome.threshold_health_heal == 400.0
        assert outcome.applied_to_health == 1200.0
        assert pools.health == 2300.0 - 1200.0
        assert outcome.overkill == 0.0


class TestInertPools:
    """Callers shortcut an inert defender; the ledger decides who is inert."""

    def test_a_defender_with_nothing_staged_is_inert(self):
        assert is_inert(_pools()) is True

    def test_any_pool_with_an_amount_is_not_inert(self):
        assert is_inert(_pools(general_shield=1.0)) is False
        assert is_inert(_pools(magic_shield=1.0)) is False
        assert is_inert(_pools(physical_shield=1.0)) is False

    def test_a_timed_grant_alone_is_not_inert(self):
        pools = _pools()
        pools.timed.append(TimedShield(amount=50.0, expires_at=3.0))
        assert is_inert(pools) is False

    def test_an_armable_lifeline_is_not_inert(self):
        assert is_inert(_pools(threshold_shield=_steraks())) is False
        assert (
            is_inert(
                _pools(
                    threshold_health=ThresholdHealth(
                        bonus=300.0, heal=400.0, health_ratio=0.3, duration=5.0
                    )
                )
            )
            is False
        )

    def test_a_lifeline_that_can_never_arm_stays_inert(self):
        never = ThresholdShield(
            amount=600.0, health_threshold=0.0, duration=4.5, damage_type="all"
        )
        assert is_inert(_pools(threshold_shield=never)) is True
