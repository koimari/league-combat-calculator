"""The front door for the shared damage-formula evaluator.

Every strike family's number goes through here, so this is where the two
properties no individual family's test can see are pinned: that a basis with
no reading is a **stop** rather than a zero, and that the sum folds in the
declaration's term order — the property the whole "no number moved" claim
rests on, because floating-point addition is not associative.
"""

from types import SimpleNamespace

import pytest

from src.calculator.interpreters import damage_formula
from src.calculator.item_behavior import (
    AtLeast,
    Basis,
    BuildContext,
    DamageFormula,
    EngineLane,
    MeleeRangedSplit,
    NoFloor,
    Term,
)
from src.calculator.item_effects import DamageInputs
from src.calculator.value_ref import Const

CTX = BuildContext(
    level=10,
    owner="Test Item",
    data_version=0,
    fight_duration_seconds=5.0,
    target_bonus_health=0.0,
    holder_is_melee=True,
)

INPUTS = DamageInputs(
    champion_stats={
        "ability_power": 200.0,
        "attack_damage": 300.0,
        "base_attack_damage": 60.0,
        "bonus_attack_damage": 240.0,
        "lethality": 18.0,
        "health": 2000.0,
        "max_mana": 1500.0,
        "bonus_health": 800.0,
        "critical_strike_chance": 40.0,
    },
    level=10,
    is_melee=True,
    target_max_health=3000.0,
    target_current_health=1200.0,
)


_NO_FLOOR = NoFloor()


def _formula(*terms: Term, floor=_NO_FLOOR, scaling=None) -> DamageFormula:
    """A formula over *terms*, magic by default so the class is never the point."""
    from src.calculator.ability_spec import DamageClass
    from src.calculator.item_behavior import NoScaling

    return DamageFormula(
        terms=terms,
        scaling=NoScaling() if scaling is None else scaling,
        floor=floor,
        damage_class=DamageClass.MAGIC,
    )


def test_every_basis_has_a_reading() -> None:
    """A closed union is only closed if every member resolves to a number."""
    for basis in Basis:
        assert isinstance(damage_formula.basis_value(basis, INPUTS), float)


def test_the_holder_and_target_split_is_in_the_member_name() -> None:
    """ "A share of max health" is a different mechanic depending on whose."""
    assert damage_formula.basis_value(Basis.HOLDER_MAX_HEALTH, INPUTS) == 2000.0
    assert damage_formula.basis_value(Basis.TARGET_MAX_HEALTH, INPUTS) == 3000.0
    assert damage_formula.basis_value(Basis.TARGET_CURRENT_HEALTH, INPUTS) == 1200.0
    assert damage_formula.basis_value(Basis.TARGET_MISSING_HEALTH, INPUTS) == 1800.0


def test_a_flat_term_is_a_term_like_any_other() -> None:
    """The constant basis is what stops "flat" being a special case."""
    raw = damage_formula.compile_formula(
        _formula(Term(Const(30, "count"), Basis.FLAT)), CTX
    )
    assert raw(INPUTS) == 30.0


def test_terms_fold_in_the_declarations_order() -> None:
    """The property the no-number-moved claim rests on, stated as a test."""
    raw = damage_formula.compile_formula(
        _formula(
            Term(Const(30, "count"), Basis.FLAT),
            Term(Const(1, "unit_scale"), Basis.ABILITY_POWER),
        ),
        CTX,
    )
    assert raw(INPUTS) == 30.0 + 200.0


def test_a_range_split_coefficient_picks_at_event_time() -> None:
    """Both rates resolve at build time; the swing decides which one is paid."""
    raw = damage_formula.compile_formula(
        _formula(
            Term(
                MeleeRangedSplit(Const(2, "count"), Const(1, "count")),
                Basis.FLAT,
            )
        ),
        CTX,
    )
    import dataclasses

    assert raw(INPUTS) == 2.0
    assert raw(dataclasses.replace(INPUTS, is_melee=False)) == 1.0


def test_a_floor_is_its_own_axis_not_a_term() -> None:
    """ "At least this much" is a mechanic, and it clamps the sum, not a share."""
    raw = damage_formula.compile_formula(
        _formula(Term(Const(1, "count"), Basis.FLAT), floor=AtLeast(Const(5, "count"))),
        CTX,
    )
    assert raw(INPUTS) == 5.0


def test_a_formula_with_no_terms_is_refused_at_declaration_time() -> None:
    """A strike that is a sum of nothing is an item that quietly deals nothing."""
    from src.calculator.ability_spec import DamageClass
    from src.calculator.item_behavior import BehaviorRuleError, NoScaling

    with pytest.raises(BehaviorRuleError):
        DamageFormula(
            terms=(),
            scaling=NoScaling(),
            floor=NoFloor(),
            damage_class=DamageClass.MAGIC,
        )


def test_a_basis_with_no_reading_stops_the_build_not_the_fight() -> None:
    """A programming error must surface when the build is made, never on an event."""

    class _Unknown:  # pylint: disable=too-few-public-methods
        value = "unknown_basis"

    with pytest.raises(damage_formula.DamageFormulaError):
        damage_formula.basis_value(_Unknown(), INPUTS)  # type: ignore[arg-type]


def test_reading_the_targets_live_health_is_read_off_the_declaration() -> None:
    """It was a formula-name comparison; it is now a property of the terms."""
    live = _formula(Term(Const(1, "unit_scale"), Basis.TARGET_CURRENT_HEALTH))
    still = _formula(Term(Const(1, "unit_scale"), Basis.TARGET_MAX_HEALTH))
    assert damage_formula.reads_target_current_health(live)
    assert not damage_formula.reads_target_current_health(still)


def test_a_scaling_multiplies_the_whole_sum_and_not_a_share() -> None:
    """``(a + b) x k`` is one float and ``ka + kb`` is another."""
    from src.calculator.item_behavior import TimesValue
    from src.calculator.value_ref import Const

    scaled = _formula(
        Term(coefficient=Const(3.0, "count"), basis=Basis.FLAT),
        Term(coefficient=Const(2.0, "count"), basis=Basis.PER_LEVEL),
        scaling=TimesValue(Const(2.0, "count")),
    )
    unscaled = _formula(
        Term(coefficient=Const(3.0, "count"), basis=Basis.FLAT),
        Term(coefficient=Const(2.0, "count"), basis=Basis.PER_LEVEL),
    )
    raw_scaled = damage_formula.compile_formula(scaled, CTX)
    raw_plain = damage_formula.compile_formula(unscaled, CTX)
    assert raw_scaled(INPUTS) == pytest.approx(2.0 * raw_plain(INPUTS))


class TestFieldReading:
    """A family's whole compiled form when it is one clock."""

    @staticmethod
    def _payload(**attributes):
        return SimpleNamespace(
            formula=_formula(Term(coefficient=Const(3.0, "count"), basis=Basis.FLAT)),
            **attributes,
        )

    _RULE = SimpleNamespace(mechanic_id="test_item.active")

    def test_the_bound_reading_names_the_field_and_stamps_the_lane(self) -> None:
        read = damage_formula.field_reading(
            lambda rule: self._payload(cooldown=Const(9.0, "count")),
            "cooldown",
            "active_cooldown",
        )
        (field,) = read(self._RULE, CTX, EngineLane.PAIR_ENGINE)
        assert (field.name, field.value) == ("active_cooldown", 9.0)
        assert field.lane is EngineLane.PAIR_ENGINE
        assert field.rule_id == "test_item.active"

    def test_both_lanes_read_the_same_declaration(self) -> None:
        """The pair engine and the walk cannot drift over which field they read."""
        read = damage_formula.field_reading(
            lambda rule: self._payload(interval=Const(2.0, "count")),
            "interval",
            "periodic_interval",
        )
        pair = read(self._RULE, CTX, EngineLane.PAIR_ENGINE)
        walk = read(self._RULE, CTX, EngineLane.RECEIPT_WALK)
        assert pair[0].value == walk[0].value
        assert walk[0].lane is EngineLane.RECEIPT_WALK

    def test_a_payload_the_reader_refuses_is_not_swallowed(self) -> None:
        def payload_of(rule):
            raise ValueError(f"{rule.mechanic_id} is not an active rule")

        read = damage_formula.field_reading(payload_of, "cooldown", "active_cooldown")
        with pytest.raises(ValueError, match="not an active rule"):
            read(self._RULE, CTX, EngineLane.PAIR_ENGINE)

    def test_an_attribute_the_payload_does_not_carry_is_a_stop(self) -> None:
        """A misspelled field name fails at build time, not mid-fight."""
        read = damage_formula.field_reading(
            lambda rule: self._payload(cooldown=Const(9.0, "count")),
            "clock",
            "active_cooldown",
        )
        with pytest.raises(AttributeError):
            read(self._RULE, CTX, EngineLane.PAIR_ENGINE)
