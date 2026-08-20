"""A trigger-gated item mechanic whose trigger never happens contributes nothing.

Horizon Focus arms on an ability hit; Malignance's Hatefog and Zeke's
Convergence open on an R cast.  A window with no such cast — ``auto_only``,
or a custom cast order without R — must price the item at exactly zero and
leave the fight's certification alone: a row that never fired cannot be a
coarse source.  The same items in a window that casts still fire, and a
mechanic that fires but cannot be placed on the ledger still reads coarse.
"""

import pytest

from src.calculator.calculate import calculate_payload

_BASE = {"champion": "Ahri", "level": 18, "target_mr": 60.0}


def _fight(items, fight_mode, **extra):
    return calculate_payload(
        {
            **_BASE,
            "items": items,
            "fight_mode": fight_mode,
            "include_auto_attacks": True,
            **extra,
        }
    )


@pytest.mark.parametrize(
    ("item", "row"),
    [
        ("Horizon Focus", "damage_amp_Horizon Focus"),
        ("Malignance", "ult_proc_Malignance"),
        ("Zeke's Convergence", "ult_proc_Zeke's Convergence"),
    ],
)
def test_an_untriggered_mechanic_prices_zero_and_certifies(item, row):
    """Autos only: no ability hit, no R cast — the item row does not exist."""
    bare = _fight([], "auto_only")
    held = _fight([item], "auto_only")

    assert row not in held["breakdown"]
    assert held["total_damage"] == pytest.approx(bare["total_damage"])
    assert held["timeline_coverage"]["complete"] is True
    assert held["timeline_coverage"]["coarse_sources"] == []


def test_hatefog_never_shreds_a_target_it_never_reaches():
    """Malignance's MR reduction is Hatefog's, so it needs the R cast too."""
    bare = _fight([], "auto_only")
    held = _fight(["Malignance"], "auto_only")

    assert held["effective_mr"] == pytest.approx(bare["effective_mr"])


def test_a_cast_order_without_r_never_opens_hatefog():
    held = _fight(["Malignance"], "timed", cast_order=["Q", "W", "E"])

    assert "ult_proc_Malignance" not in held["breakdown"]
    assert held["timeline_coverage"]["coarse_sources"] == []


@pytest.mark.parametrize(
    ("item", "row"),
    [
        ("Horizon Focus", "damage_amp_Horizon Focus"),
        ("Malignance", "ult_proc_Malignance"),
        ("Zeke's Convergence", "ult_proc_Zeke's Convergence"),
    ],
)
def test_the_same_mechanic_fires_once_its_trigger_is_cast(item, row):
    """Control: a timed window casts the kit, and the row is priced exactly."""
    bare = _fight([], "timed")
    held = _fight([item], "timed")

    assert held["breakdown"][row]["total_damage"] > 0.0
    assert held["total_damage"] > bare["total_damage"]
    assert row in held["timeline_coverage"]["exact_sources"]


def test_a_mechanic_that_fires_but_cannot_be_placed_stays_coarse():
    """The reverse trap: Expose Weakness arms on Vayne's forced attack, the
    last event of a one-rotation ledger, so its amplified pool has no event
    to ride.  It fired, it is priced, and it is honestly coarse."""
    fight = calculate_payload(
        {
            "champion": "Vayne",
            "level": 18,
            "items": ["Bloodsong"],
            "role": "support",
            "role_quest_complete": True,
            "fight_mode": "one_rotation",
            "include_auto_attacks": True,
        }
    )

    assert fight["breakdown"]["expose_weakness_Bloodsong"]["total_damage"] > 0.0
    assert fight["timeline_coverage"]["coarse_sources"] == ["expose_weakness_Bloodsong"]
