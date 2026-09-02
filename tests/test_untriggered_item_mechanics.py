"""A trigger-gated item mechanic whose trigger never happens contributes nothing.

Horizon Focus arms on an ability hit, as do the three item burns; Malignance's
Hatefog and Zeke's Convergence open on an R cast.  A window with no such cast —
``auto_only``, or a custom cast order without R — must price the item at exactly
zero and leave the fight's certification alone: a row that never fired cannot be
a coarse source.  The same items in a window that casts still fire, and an amp
whose pool is empty prices nothing rather than pricing a number its own ledger
cannot show (Bloodsong's Expose Weakness).
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


@pytest.mark.parametrize(
    ("item", "row", "was"),
    [
        ("Fated Ashes", "burn_Fated Ashes", 10.9),
        ("Liandry's Torment", "burn_Liandry's Torment", 43.8),
        ("Blackfire Torch", "burn_Blackfire Torch", 47.4),
    ],
)
def test_a_burn_needs_an_ability_hit_to_light_it(item, row, was):
    """Autos light no burn; *was* is the figure an ungated window would price."""
    bare = _fight([], "auto_only")
    held = _fight([item], "auto_only")

    assert was > 0.0  # the ungated figure, kept as the regression's marker
    assert row not in held["breakdown"]
    assert held["timeline_coverage"]["coarse_sources"] == []
    # Liandry's Suffering is an in-combat time ramp, not an ability trigger,
    # so its amp row survives the autos-only window and its burn does not.
    assert held["total_damage"] == pytest.approx(
        bare["total_damage"]
        + held["breakdown"].get(f"damage_amp_{item}", {}).get("total_damage", 0.0)
    )


@pytest.mark.parametrize(
    "item", ["Fated Ashes", "Liandry's Torment", "Blackfire Torch"]
)
def test_the_same_burn_lights_once_an_ability_lands(item):
    """Control: a casting window arms every burn, exactly on the ledger."""
    held = _fight([item], "timed")

    assert held["breakdown"][f"burn_{item}"]["total_damage"] > 0.0
    assert held["timeline_coverage"]["coarse_sources"] == []


def test_the_hatefog_burn_tail_keys_off_the_accepted_r_cast():
    """Hatefog refreshes a burn only where the rotation accepted the R.

    Ahri L18, one rotation, Liandry's + Malignance: a Q-only order prices
    37.5 — exactly what the same window prices without Malignance — not the
    75.0 of a burn window stretched by Hatefog's whole duration off the mere
    presence of an ``R`` in the priced kit, which is the R's own tail with no
    R cast.  The full order casts R and the tail is real.
    """
    q_only = _fight(
        ["Liandry's Torment", "Malignance"], "one_rotation", cast_order=["Q"]
    )
    q_only_bare = _fight(["Liandry's Torment"], "one_rotation", cast_order=["Q"])
    full = _fight(["Liandry's Torment", "Malignance"], "one_rotation")
    full_bare = _fight(["Liandry's Torment"], "one_rotation")

    burn = "burn_Liandry's Torment"
    assert q_only["breakdown"][burn]["total_damage"] == pytest.approx(37.5)
    assert q_only["breakdown"][burn]["total_damage"] == pytest.approx(
        q_only_bare["breakdown"][burn]["total_damage"]
    )
    assert full["breakdown"][burn]["total_damage"] == pytest.approx(100.0)
    assert (
        full["breakdown"][burn]["total_damage"]
        > full_bare["breakdown"][burn]["total_damage"]
    )


def _vayne(fight_mode):
    return calculate_payload(
        {
            "champion": "Vayne",
            "level": 18,
            "items": ["Bloodsong"],
            "role": "support",
            "role_quest_complete": True,
            "fight_mode": fight_mode,
            "include_auto_attacks": True,
        }
    )


def test_expose_weakness_prices_its_own_pool_and_nothing_else():
    """Expose Weakness arms on Vayne's forced attack, the last event of a
    one-rotation ledger, so its amplified pool is empty: no pool, no row.
    The ungated rule charged the rate against ``total_damage`` minus a
    reconstructed arming sequence and priced 22.8 on that empty pool."""
    fight = _vayne("one_rotation")

    assert "expose_weakness_Bloodsong" not in fight["breakdown"]
    assert fight["timeline_coverage"]["coarse_sources"] == []
    assert fight["total_damage"] == pytest.approx(505.5)


def test_expose_weakness_number_equals_the_rate_over_its_authored_events():
    """A window with a pool prices it, and the row's events sum to the row.

    Vayne timed: 14 ledger events land after the arming proc, 956.2 damage,
    and the 5% rate over exactly those is 47.8 — the row, and the sum of the
    deltas it authors onto them.  Pricing off ``total_damage`` instead swept
    in the 756.2 that landed before the proc and charged 79.0.
    """
    fight = _vayne("timed")
    row = fight["breakdown"]["expose_weakness_Bloodsong"]

    assert row["total_damage"] == pytest.approx(47.8, abs=0.05)
    # Priced off the pool it authors onto, so the row can never read coarse.
    assert "expose_weakness_Bloodsong" in fight["timeline_coverage"]["exact_sources"]
    assert fight["timeline_coverage"]["coarse_sources"] == []
