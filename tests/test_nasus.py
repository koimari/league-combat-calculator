"""Tests for the Nasus champion module."""

from functools import partial

import pytest

from src.calculator.champions import nasus
from src.calculator.data_fetcher import get_champion
from src.calculator.stats import calculate_total_stats
from tests import cc_review
from tests import champion_closure as closure


class TestReviewedCrowdControl:
    """Nasus' reviewed crowd control, and what declaring it clears.

    The roster-wide half of this review lives in ``test_module_cc_census.py``.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Nasus")
        # A cc-only slot states its kind in MODULE_CC like any other and
        # publishes the sourced interval as a ControlEvent (CF8).
        assert nasus.MODULE_CC == {
            "Q": "none",
            "W": "slow",
            "E": "none",
            "R": "none",
            "P": "none",
        }
        for slot in ("Q", "E", "R"):
            assert cc_review.control_words(cc_review.slot_text(data, slot)) == []
        # Wither is the kit's one control and deals no damage, so the
        # answer rides its entry as a sourced ControlEvent.  P is
        # lifesteal and damages nothing.
        assert "slowing them by 35%" in cc_review.slot_text(data, "W")
        assert nasus.MODULE_CC["P"] == "none"
        assert cc_review.control_words(cc_review.slot_text(data, "P")) == []


def test_p_is_modeled_through_the_soul_eater_lifesteal() -> None:
    """P emits a row with no enemy damage; the heal rule prices the slot.

    A level-18 itemless timed fight with autos pays Soul Eater 104.4 — the
    receipt behind P's ``modeled`` label.  Seven physical hits at the
    level-18 24% share: five Siphoning Strikes on the 1.75-second cadence
    (14.4 each) and the two ordinary autos left beside them (16.2 each).
    The Siphoning Strike payments are the ones a rule reading only the
    ``auto_attacks`` row misses — Q rides a basic attack rather than
    replacing one, so the engine attributes that swing to the Q row —
    which is why ``derive_self_healing`` reads both rows.  W is a cast
    slot emitting the pinned packet's sourced zero-damage row, so it is
    ``no_damage`` rather than a gap; only its slow/cripple magnitude stays
    unpriced.
    """
    import pytest

    from src.calculator.calculate import calculate_payload
    from src.calculator.champions import get_champion_module_contract

    contract = get_champion_module_contract("Nasus")
    assert contract.coverage["P"] == "modeled"
    assert contract.coverage["W"] == "no_damage"
    assert contract.coverage_channels["P"] == ("self_healing_rule",)

    payload = calculate_payload(
        {
            "champion": "Nasus",
            "level": 18,
            "fight_mode": "timed",
            "include_auto_attacks": True,
        }
    )
    paid = sum(
        float(event["amount"])
        for event in payload["self_healing_events"]
        if event["source"] == "Soul Eater"
    )
    assert paid == pytest.approx(104.4, abs=0.1)


# Level 18, ranks Q5/W5/E5/R3, no items, six seconds of autos at full uptime
# into a 3000-HP Aatrox whose own resistances mitigate.
_closure_fight = partial(
    closure.combat,
    mode="time_based",
    duration=6.0,
    include_autos=True,
    auto_uptime=1.0,
    target_health=3000.0,
    enemy=closure.AATROX,
)
_closure_parse = partial(closure.parse, target=closure.TARGET_3000)


# ---------------------------------------------------------------------------
# Nasus — P Soul Eater lifesteal
# ---------------------------------------------------------------------------


def _assert_soul_eater_heals(combat, *, level, ratio):
    """Soul Eater heals 12/18/24% of each post-mitigation PHYSICAL hit.

    MERGE: the payments are per damaging physical hit, not per basic
    attack.  Siphoning Strike (Q) is a modified basic attack and pays at
    ITS post-mitigation damage (54.5 at level 18 against 120 armor), while
    a plain auto pays at its own (61.4) -- so the heals come out at two
    magnitudes and one expected value could only ever have matched one of
    them.  That is the wiki's Soul Eater: life steal on physical damage,
    not a per-swing rider.  The level breakpoint (12 / 18 / 24%) is
    unchanged, and it is what the auto-sized heal below still pins.
    """
    heals = list(closure.main_heals(combat, "Soul Eater"))
    assert heals, "Soul Eater heal missing"
    enemy_stats = closure.enemy_stats(combat)
    nasus_stats = calculate_total_stats(get_champion("Nasus"), level, [])
    per_auto = nasus_stats["attack_damage"] * 100.0 / (100.0 + enemy_stats["armor"])

    physical = [
        event["damage"]
        for event in combat["events"]
        if event.get("attacker") == "main"
        and event.get("damage_type") == "physical"
        and float(event.get("damage", 0.0)) > 0.0
    ]
    assert physical, "no physical hit for Soul Eater to ride"
    for heal in heals:
        assert any(
            heal["amount"] == pytest.approx(ratio * damage, abs=0.06)
            for damage in physical
        ), heal
    # The plain auto's share is the one the level breakpoint names.
    assert any(
        heal["amount"] == pytest.approx(ratio * per_auto, abs=0.06) for heal in heals
    )

    survival = closure.main_survival(combat)
    if survival["death_time"] is None:
        # The survival walk applies the receipts only while the fighter is
        # alive and missing health: a dead-by-first-swing level-6 Nasus
        # still emits the sourced receipts but applies none, and a heal
        # landing before the enemy's first hit (its windup) restores nothing.
        first_hit = min(
            float(event["time"])
            for event in combat["events"]
            if event.get("target") == "main" and float(event.get("damage", 0.0)) > 0.0
        )
        assert survival["healing_received"] == pytest.approx(
            sum(heal["amount"] for heal in heals if heal["time"] >= first_hit),
            abs=0.25,
        )


def test_nasus_soul_eater_heals_twenty_four_percent_at_level_18():
    _assert_soul_eater_heals(_closure_fight("Nasus"), level=18, ratio=0.24)


def test_nasus_soul_eater_heals_twelve_percent_below_level_7():
    # Game-file breakpoints: 12% at levels 1-6, 18% at 7-12, 24% at 13+.
    combat = _closure_fight("Nasus", level=6, ranks={"Q": 2, "W": 1, "E": 2, "R": 1})
    _assert_soul_eater_heals(combat, level=6, ratio=0.12)
