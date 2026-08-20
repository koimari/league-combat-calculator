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


def test_a_mana_refused_r_never_opens_hatefog():
    """R is priced, ordered first, in a casting window — and the budget refuses it.

    Only the accepted cast timeline knows this, so the served MR must come from
    the rotation's R outcome: the proc row is absent AND the MR is unshredded.
    The engine is driven directly because no cached champion's pool is small
    enough to refuse its own R at full mana; the pool is the fixture's knob.
    """
    from src.calculator.champions import parse_champion_abilities
    from src.calculator.damage import FightConfig, calculate_fight_damage
    from src.calculator.data_fetcher import get_champion, get_item_by_name
    from src.calculator.stats import calculate_total_stats

    annie = get_champion("Annie")
    malignance = get_item_by_name("Malignance")
    stats = calculate_total_stats(annie, 18, [malignance])
    abilities = parse_champion_abilities(
        annie, 18, stats["ability_power"], champion_stats=stats
    )

    def fight(items, max_mana):
        return calculate_fight_damage(
            {**stats, "max_mana": max_mana, "resource_regen_per_second": 0.0},
            abilities,
            items,
            FightConfig(
                target_health=3000.0,
                target_armor=60.0,
                target_magic_resistance=60.0,
                fight_duration_seconds=5.0,
                one_rotation=True,
                deterministic=True,
                enforce_resource_limits=True,
                cast_order=["R", "Q", "W", "E"],
            ),
        )

    r_cost = float(abilities["R"]["resource_cost"])
    assert r_cost > 0.0
    bare = fight([], stats["max_mana"])
    paid = fight([malignance], stats["max_mana"])
    refused = fight([malignance], r_cost - 1.0)

    # Control: the same build with the R paid for opens the zone and shreds.
    assert any(cast["slot"] == "R" for cast in paid["cast_timeline"])
    assert "ult_proc_Malignance" in paid["breakdown"]
    assert paid["effective_mr"] < bare["effective_mr"]

    assert not any(cast["slot"] == "R" for cast in refused["cast_timeline"])
    assert "ult_proc_Malignance" not in refused["breakdown"]
    assert refused["effective_mr"] == pytest.approx(bare["effective_mr"])


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
