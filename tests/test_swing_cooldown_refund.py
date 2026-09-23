"""The kit refund that pays other slots' cooldowns down per basic attack.

Sivir's On the Hunt is the first of its shape and the reason her R was one of
the slots ``docs/coverage-status.md`` recorded as having no engine axis at
all. It is NOT ``stack_scaled_cooldown``: that is a slot's rule about its own
cooldown, and this grant is authored on R and shortens Q, W and E.

Three things need holding, and a number alone holds none of them: that the
walk reads the WINDOW rather than applying a flat multiplier, that the two
reducers riding one attack are walked together rather than composed, and that
the engine refuses a second owner instead of inventing how two flat refunds
combine.
"""

import pytest

from src.calculator.binary_roots import data_value, spell_object
from src.calculator.champions.entry_shape import (
    _ALLOWED_SWING_REFUND_KEYS,
    EmittedSlot,
    validate_entry_keys,
)
from src.calculator.data_fetcher import get_champion
from src.calculator.fight.rotation.cast_schedule import _attack_paid_cooldown

_SIVIR = get_champion("Sivir")


def _fight(*, ranks: dict, duration: float = 20.0) -> dict:
    """One /api/calculate fight at level 18 through the real boundary."""
    from src import app as app_module

    response = app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Sivir",
            "level": 18,
            "items": [],
            "ability_ranks": ranks,
            "fight_mode": "time_based",
            "fight_duration": duration,
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
            "target_health": 2500.0,
            "target_armor": 100.0,
            "target_mr": 50.0,
        },
    )
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _cast_times(payload: dict, slot: str) -> list[float]:
    return [
        round(float(row["time"]), 3)
        for row in payload["cast_timeline"]
        if row["slot"] == slot
    ]


class TestTheNumberIsSourcedTwice:
    """Neither reading is a literal, and both still agree."""

    def test_the_binary_carries_the_refund_as_its_own_data_value(self):
        refund = data_value(spell_object("Sivir", "SivirR"), "AttackCooldownRefund")
        assert refund == pytest.approx(0.5)

    def test_the_cached_prose_states_the_same_half_second(self):
        text = " ".join(
            str(effect.get("description", ""))
            for ability in _SIVIR["abilities"]["R"]
            for effect in ability.get("effects", ())
        )
        assert "basic abilities' current cooldowns by 0.5 seconds each" in text

    def test_the_two_sources_are_read_and_never_pinned(self):
        """A constant would drift from the dump on the patch that moves it."""
        source = (
            __import__("pathlib")
            .Path("src/calculator/champions/sivir.py")
            .read_text(encoding="utf-8")
        )
        assert (
            'data_value(spell_object("Sivir", "SivirR"), "AttackCooldownRefund")'
            in (source)
        )


class TestTheWalkReadsTheWindow:
    """A flat multiplier and a window intersection disagree, and it matters."""

    def test_an_attack_inside_the_window_pays_the_cooldown_down(self):
        # 8s cooldown, 1 auto/s, 0.5s per attack, window covering the whole run.
        walked = _attack_paid_cooldown(
            8.0,
            1.0,
            flat_refund=0.5,
            refund_window=(0.0, 100.0),
            cooldown_start=0.0,
        )
        assert walked < 8.0
        assert walked == pytest.approx(16.0 / 3.0, abs=0.35)

    def test_an_attack_outside_the_window_pays_nothing(self):
        walked = _attack_paid_cooldown(
            8.0,
            1.0,
            flat_refund=0.5,
            refund_window=(50.0, 60.0),
            cooldown_start=0.0,
        )
        assert walked == pytest.approx(8.0)

    def test_a_cooldown_straddling_the_window_end_is_part_paid(self):
        """The case a flat multiplier gets wrong, and the whole reason the
        walk carries a start rather than a duration."""
        inside = _attack_paid_cooldown(
            8.0, 1.0, flat_refund=0.5, refund_window=(0.0, 100.0), cooldown_start=0.0
        )
        straddling = _attack_paid_cooldown(
            8.0, 1.0, flat_refund=0.5, refund_window=(0.0, 3.0), cooldown_start=0.0
        )
        assert inside < straddling < 8.0

    def test_no_window_is_no_grant(self):
        assert _attack_paid_cooldown(8.0, 1.0, flat_refund=0.5) == pytest.approx(8.0)

    def test_no_attacks_leaves_the_cooldown_alone(self):
        """Fail-closed: a rate of zero is the unrefunded reading, never a crash."""
        assert _attack_paid_cooldown(
            8.0, 0.0, flat_refund=0.5, refund_window=(0.0, 100.0)
        ) == pytest.approx(8.0)


class TestTheTwoReducersRideOneAttack:
    """Navori's share and a kit's flat seconds are one walk, not two."""

    def test_composing_two_walks_would_place_the_recast_late(self):
        together = _attack_paid_cooldown(
            8.0,
            1.0,
            refund_percent=0.15,
            flat_refund=0.5,
            refund_window=(0.0, 100.0),
            cooldown_start=0.0,
        )
        navori_only = _attack_paid_cooldown(8.0, 1.0, refund_percent=0.15)
        composed = _attack_paid_cooldown(
            navori_only,
            1.0,
            flat_refund=0.5,
            refund_window=(0.0, 100.0),
            cooldown_start=0.0,
        )
        # Both reducers land on the same attacks, so one walk is shorter than
        # a walk of a walk, which charges those attacks' elapsed time twice.
        assert together < navori_only
        assert together != pytest.approx(composed)

    def test_each_reducer_alone_still_answers_its_own_reading(self):
        flat = _attack_paid_cooldown(
            8.0, 1.0, flat_refund=0.5, refund_window=(0.0, 100.0)
        )
        share = _attack_paid_cooldown(8.0, 1.0, refund_percent=0.15)
        assert 0.0 < flat < 8.0
        assert 0.0 < share < 8.0
        assert flat != pytest.approx(share)


class TestTheRuleIsFullyDeclaredOrRefused:
    """Every number of the rule is the module's; none may be defaulted."""

    def test_the_sub_key_vocabulary_is_the_whole_rule(self):
        assert _ALLOWED_SWING_REFUND_KEYS == {
            "seconds_per_attack",
            "slots",
            "window_seconds",
        }

    @pytest.mark.parametrize("missing", sorted(_ALLOWED_SWING_REFUND_KEYS))
    def test_a_rule_missing_any_field_is_refused_by_name(self, missing):
        payload = {
            "seconds_per_attack": 0.5,
            "slots": ("Q",),
            "window_seconds": 10.0,
        }
        del payload[missing]
        with pytest.raises(ValueError, match=missing):
            validate_entry_keys(
                EmittedSlot("Sivir", "R"), {"swing_cooldown_refund": payload}
            )

    def test_a_misspelled_sub_key_is_refused_rather_than_ignored(self):
        """SR5's lesson: a ``.get`` that answers None is a silent no-op."""
        with pytest.raises(ValueError, match="swing_cooldown_refund"):
            validate_entry_keys(
                EmittedSlot("Sivir", "R"),
                {
                    "swing_cooldown_refund": {
                        "seconds_per_attack": 0.5,
                        "slots": ("Q",),
                        "window_seconds": 10.0,
                        "second_per_attack": 0.5,
                    }
                },
            )


class TestThroughTheRequestBoundary:
    """What a caller sees, with the control that makes it evidence."""

    def test_the_hunt_buys_an_extra_cast_of_every_basic(self):
        with_hunt = _fight(ranks={"Q": 5, "W": 5, "E": 5, "R": 3})
        assert _cast_times(with_hunt, "Q") == [0.0, 5.75, 11.5, 19.75]
        assert _cast_times(with_hunt, "W") == [0.25, 8.25, 18.25]
        assert _cast_times(with_hunt, "E") == [0.25, 12.25]

    def test_without_the_hunt_the_cadence_is_the_plain_cooldown(self):
        """The control. R unranked buys no window, so nothing is refunded and
        every gap is the hasted cooldown exactly."""
        without = _fight(ranks={"Q": 5, "W": 5, "E": 5, "R": 0})
        assert _cast_times(without, "Q") == [0.0, 8.25, 16.5]
        assert _cast_times(without, "W") == [0.25, 12.25]
        assert _cast_times(without, "E") == [0.25, 18.25]

    def test_the_last_gap_is_longer_because_the_hunt_expired(self):
        """The window intersection, read off the plan rather than asserted.

        Q's first two refunded gaps are 5.75s; the third is 8.25s, the plain
        hasted cooldown, because the hunt is over by then. A flat multiplier
        would have made all three equal.
        """
        casts = _cast_times(_fight(ranks={"Q": 5, "W": 5, "E": 5, "R": 3}), "Q")
        gaps = [round(b - a, 3) for a, b in zip(casts, casts[1:])]
        assert gaps[0] == pytest.approx(gaps[1], abs=1e-3)
        assert gaps[2] > gaps[1]

    def test_the_slot_closes_as_no_damage(self):
        from src.calculator.champions import sivir

        assert sivir.MODULE_COVERAGE["R"] == "no_damage"
