"""P3 package 2 — champion mana restore/refund: driver-level integration (RLM-1 owned).

Complements tests/test_mana_restore_refund.py (RLM-2 C's acceptance matrix) with
the direct-engine low-mana scenarios the run_fight fixtures cannot reach:

- restored/refunded mana ENABLES a later cast (admission changes through the
  ONE ledger account);
- W-chain detonation (an ability W cast detonates the previous W's mark);
- the w_mark_detonation option's named receipts (zero gains);
- Hyper Charge swing restores are gated on their arming cast's acceptance;
- score/receipt parity for both mechanics;
- cast_timeline rows stay projections of ledger spend receipts when refunds
  are live (no duplicate state).
"""

import dataclasses

import pytest

from src.calculator.champions import parse_champion_abilities as parse_abilities
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.data_fetcher import get_champion
from src.calculator.pipeline import FightParams, run_fight

JAYCE_SOURCE = "Jayce W passive (Mana Restored)"
EZREAL_SOURCE = "Ezreal W (Essence Flux) mark refund"


def _ezreal_abilities(stats):
    return parse_abilities(
        get_champion("Ezreal"),
        18,
        0.0,
        champion_options={},
        champion_stats=dict(stats),
        target_stats={"target_max_health": 2000.0},
    )


def _jayce_abilities(stats, *, hammer=True):
    return parse_abilities(
        get_champion("Jayce"),
        18,
        0.0,
        champion_options={"hammer_stance": hammer},
        champion_stats=dict(stats),
        target_stats={"target_max_health": 2000.0},
    )


def _fight(stats, abilities, *, duration, cast_order, uptime=0.0, one_rotation=False):
    return calculate_fight_damage(
        stats,
        abilities,
        [],
        FightConfig(
            target_health=2000,
            target_armor=50,
            target_magic_resistance=40,
            fight_duration_seconds=duration,
            auto_attack_uptime=uptime,
            one_rotation=one_rotation,
            deterministic=True,
            enforce_resource_limits=True,
            cast_order=cast_order,
        ),
    )


_EZ_LOW = {
    "ability_haste": 0.0,
    "armor_penetration_bonus_percent": 0.0,
    "armor_penetration_percent": 0.0,
    "basic_ability_haste": 0.0,
    "bonus_health": 0.0,
    "bonus_mana": 0.0,
    "critical_strike_chance": 0.0,
    "flat_armor_penetration": 0.0,
    "health": 0.0,
    "is_melee": True,
    "lethality": 0.0,
    "level": 1,
    "magic_penetration_flat": 0.0,
    "magic_penetration_percent": 0.0,
    "move_speed": 0.0,
    "omnivamp_percent": 0.0,
    "ultimate_haste": 0.0,
    "ability_power": 0.0,
    "attack_damage": 100.0,
    "base_attack_damage": 60.0,
    "bonus_attack_damage": 40.0,
    "attack_speed": 0.8,
    "attack_speed_ratio": 0.625,
    "bonus_attack_speed": 0.0,
    "max_mana": 120.0,
    "resource_regen_per_second": 0.0,
}


def test_refunded_mana_enables_a_later_cast():
    # One-rotation W->Q->E->R with a 120-mana pool: without the refund, E
    # (70) is denied after W (50) + Q (40); with it, Q's hit refunds
    # 60+40=100 and E is admitted — admission changes ride the ONE ledger.
    stats = dict(_EZ_LOW)
    abilities = _ezreal_abilities(stats)
    order = ["W", "Q", "E", "R"]
    with_refund = _fight(
        stats, abilities, duration=6.0, cast_order=order, one_rotation=True
    )
    refunds = [
        r
        for r in with_refund["resource_ledger"]["receipts"]
        if r["source"] == EZREAL_SOURCE
    ]
    assert [(r["time"], r["amount"]) for r in refunds] == [
        (pytest.approx(0.0, abs=1e-9), pytest.approx(100.0))
    ]
    spends = [
        r
        for r in with_refund["resource_ledger"]["receipts"]
        if r["operation"] == "spend"
    ]
    # W, Q, E admitted; R (100) still denied; the refund enabled E.
    assert [r["detail"]["slot"] for r in spends if r["accepted"]] == ["W", "Q", "E"]
    assert [r["detail"]["slot"] for r in spends if not r["accepted"]] == ["R"]
    assert with_refund["resource_spent"] == pytest.approx(160.0)

    # Without the mechanic (basic_attack detonation) E is denied.
    abilities_ba = parse_abilities(
        get_champion("Ezreal"),
        18,
        0.0,
        champion_options={"w_mark_detonation": "basic_attack"},
        champion_stats=dict(stats),
        target_stats={"target_max_health": 2000.0},
    )
    without = _fight(
        stats, abilities_ba, duration=6.0, cast_order=order, one_rotation=True
    )
    spends_ba = [
        r for r in without["resource_ledger"]["receipts"] if r["operation"] == "spend"
    ]
    assert [r["detail"]["slot"] for r in spends_ba if r["accepted"]] == ["W", "Q"]
    # The option is receipted per W cast, with zero gains.
    marks = without["resource_ledger"]["mark_refunds"]["marks"]
    assert all(m["reason"] == "basic_attack_detonation" for m in marks)
    assert not [
        r
        for r in without["resource_ledger"]["receipts"]
        if r["source"] == EZREAL_SOURCE
    ]


def test_w_chain_detonation_refunds_with_w_cost():
    # A second W cast detonates the first W's mark ("his next basic attack
    # or ability against the target"), refunding 60 + W's own cost (50).
    stats = dict(_EZ_LOW)
    stats["max_mana"] = 500.0
    abilities = _ezreal_abilities(stats)
    result = _fight(stats, abilities, duration=12.0, cast_order=["W"])
    refunds = [
        r for r in result["resource_ledger"]["receipts"] if r["source"] == EZREAL_SOURCE
    ]
    # W casts at ~0, ~5.58, ~11.17.  P1-13 (R1): the mark's 4s window is
    # enforced, and every chain gap (5.583s) exceeds it — W#2 expires W#1's
    # mark, W#3 expires W#2's, W#3's own mark is receipted undetonated:
    # the pure W chain refunds NOTHING (in-game the marks expired before
    # the hits).  In-window detonation is pinned by the W->Q consumer
    # tests below.
    assert refunds == []
    marks = result["resource_ledger"]["mark_refunds"]["marks"]
    assert [m["reason"] for m in marks] == [
        "mark_expired",
        "mark_expired",
        "mark_undetonated",
    ]
    assert [m["detonating_slot"] for m in marks] == [None, None, None]


def test_jayce_restores_enable_later_casts():
    # Low-mana Jayce (hammer): with autos, each basic attack restores 25
    # mana on the ONE ledger, keeping the late casts affordable.
    stats = {
        "ability_haste": 0.0,
        "armor_penetration_bonus_percent": 0.0,
        "armor_penetration_percent": 0.0,
        "basic_ability_haste": 0.0,
        "bonus_health": 0.0,
        "bonus_mana": 0.0,
        "critical_strike_chance": 0.0,
        "flat_armor_penetration": 0.0,
        "health": 0.0,
        "is_melee": True,
        "lethality": 0.0,
        "level": 1,
        "magic_penetration_flat": 0.0,
        "magic_penetration_percent": 0.0,
        "move_speed": 0.0,
        "omnivamp_percent": 0.0,
        "ultimate_haste": 0.0,
        "ability_power": 0.0,
        "attack_damage": 120.0,
        "base_attack_damage": 60.0,
        "bonus_attack_damage": 60.0,
        "attack_speed": 1.0,
        "attack_speed_ratio": 0.658,
        "bonus_attack_speed": 0.0,
        "max_mana": 120.0,
        "resource_regen_per_second": 0.0,
    }
    abilities = _jayce_abilities(stats, hammer=True)
    order = ["R", "Q", "W", "E"]
    no_autos = _fight(stats, abilities, duration=20.0, cast_order=order, uptime=0.0)
    with_autos = _fight(stats, abilities, duration=20.0, cast_order=order, uptime=1.0)

    restores = [
        r
        for r in with_autos["resource_ledger"]["receipts"]
        if r["source"] == JAYCE_SOURCE
    ]
    assert restores  # 20 autos at 1.0 AS restore 25 each
    assert all(r["amount"] == pytest.approx(25.0) for r in restores)
    assert all(r["tier"] == 0.0 for r in restores)
    assert all(
        r["atoms"] == [["ability.mana _restored", "bfeb0d88945a263e"]] for r in restores
    )

    spent_without = sum(
        r["amount"]
        for r in no_autos["resource_ledger"]["receipts"]
        if r["operation"] == "spend" and r["accepted"]
    )
    spent_with = sum(
        r["amount"]
        for r in with_autos["resource_ledger"]["receipts"]
        if r["operation"] == "spend" and r["accepted"]
    )
    assert spent_with > spent_without
    assert (
        not [
            r
            for r in with_autos["resource_ledger"]["receipts"]
            if not r["accepted"] and r["operation"] == "spend"
        ]
        or spent_with > spent_without
    )


def test_hyper_charge_swing_restores_are_gated_on_acceptance():
    # Cannon stance: one restore per in-window Hyper Charge swing, each
    # gated on its arming cast.  With max_mana 39 the only W cast is
    # DENIED (39 < 40), so its three in-window swings (0.33/0.67/1.0) are
    # denial receipts — never gains — while the ordinary autos keep
    # restoring on the same account.
    stats = {
        "ability_haste": 0.0,
        "armor_penetration_bonus_percent": 0.0,
        "armor_penetration_percent": 0.0,
        "basic_ability_haste": 0.0,
        "bonus_health": 0.0,
        "bonus_mana": 0.0,
        "critical_strike_chance": 0.0,
        "flat_armor_penetration": 0.0,
        "health": 0.0,
        "is_melee": True,
        "lethality": 0.0,
        "level": 1,
        "magic_penetration_flat": 0.0,
        "magic_penetration_percent": 0.0,
        "move_speed": 0.0,
        "omnivamp_percent": 0.0,
        "ultimate_haste": 0.0,
        "ability_power": 0.0,
        "attack_damage": 120.0,
        "base_attack_damage": 60.0,
        "bonus_attack_damage": 60.0,
        "attack_speed": 1.0,
        "attack_speed_ratio": 0.658,
        "bonus_attack_speed": 0.0,
        "max_mana": 39.0,
        "resource_regen_per_second": 0.0,
    }
    abilities = _jayce_abilities(stats, hammer=False)
    # 3s window: exactly one W cast (cooldown 5), so exactly three swings.
    result = _fight(stats, abilities, duration=3.0, cast_order=["W"], uptime=1.0)
    ledger = result["resource_ledger"]
    section = ledger["auto_restore"]
    assert section["declaration"]["amount"] == pytest.approx(25.0)
    assert [r["accepted"] for r in ledger["receipts"] if r["operation"] == "spend"] == [
        False
    ]
    denials = section["denials"]
    assert len(denials) == 3
    assert all(d["reason"] == "arming_cast_denied" for d in denials)
    assert all(d["arming_slot"] == "W" for d in denials)
    assert all(d["accepted"] is False for d in denials)
    # No swing gain exists for the denied arming cast.
    swing_gains = [
        r
        for r in ledger["receipts"]
        if r["source"] == JAYCE_SOURCE and r["detail"]["kind"] == "swing"
    ]
    assert swing_gains == []
    # Ordinary autos still restore (the passive is not tied to W's cast).
    ordinary_gains = [
        r
        for r in ledger["receipts"]
        if r["source"] == JAYCE_SOURCE and r["detail"]["kind"] == "ordinary"
    ]
    assert ordinary_gains
    assert all(r["amount"] == pytest.approx(25.0) for r in ordinary_gains)


def test_score_parity_with_restore_and_refund():
    # score_only must not change admission, resource totals, or receipts.
    stats = dict(_EZ_LOW)
    abilities = _ezreal_abilities(stats)
    order = ["W", "Q", "E", "R"]
    full = _fight(stats, abilities, duration=6.0, cast_order=order, one_rotation=True)
    scored = calculate_fight_damage(
        stats,
        abilities,
        [],
        FightConfig(
            target_health=2000,
            target_armor=50,
            target_magic_resistance=40,
            fight_duration_seconds=6.0,
            auto_attack_uptime=0.0,
            one_rotation=True,
            deterministic=True,
            enforce_resource_limits=True,
            cast_order=order,
        ),
        score_only=True,
    )
    assert full["resource_spent"] == scored["resource_spent"]
    assert full["resource_remaining"] == pytest.approx(scored["resource_remaining"])
    assert full["resource_ledger"]["receipts"] == scored["resource_ledger"]["receipts"]
    assert (
        full["resource_ledger"]["mark_refunds"]
        == scored["resource_ledger"]["mark_refunds"]
    )

    stats_j = {
        "ability_haste": 0.0,
        "armor_penetration_bonus_percent": 0.0,
        "armor_penetration_percent": 0.0,
        "basic_ability_haste": 0.0,
        "bonus_health": 0.0,
        "bonus_mana": 0.0,
        "critical_strike_chance": 0.0,
        "flat_armor_penetration": 0.0,
        "health": 0.0,
        "is_melee": True,
        "lethality": 0.0,
        "level": 1,
        "magic_penetration_flat": 0.0,
        "magic_penetration_percent": 0.0,
        "move_speed": 0.0,
        "omnivamp_percent": 0.0,
        "ultimate_haste": 0.0,
        "ability_power": 0.0,
        "attack_damage": 120.0,
        "base_attack_damage": 60.0,
        "bonus_attack_damage": 60.0,
        "attack_speed": 1.0,
        "attack_speed_ratio": 0.658,
        "bonus_attack_speed": 0.0,
        "max_mana": 120.0,
        "resource_regen_per_second": 0.0,
    }
    abil_j = _jayce_abilities(stats_j, hammer=True)
    cfg = FightConfig(
        target_health=2000,
        target_armor=50,
        target_magic_resistance=40,
        fight_duration_seconds=12.0,
        auto_attack_uptime=1.0,
        one_rotation=False,
        deterministic=True,
        enforce_resource_limits=True,
        cast_order=["R", "Q", "W", "E"],
    )
    full_j = calculate_fight_damage(stats_j, abil_j, [], cfg)
    scored_j = calculate_fight_damage(stats_j, abil_j, [], cfg, score_only=True)
    assert full_j["resource_spent"] == scored_j["resource_spent"]
    assert full_j["resource_remaining"] == pytest.approx(scored_j["resource_remaining"])
    assert (
        full_j["resource_ledger"]["receipts"] == scored_j["resource_ledger"]["receipts"]
    )
    assert (
        full_j["resource_ledger"]["auto_restore"]
        == scored_j["resource_ledger"]["auto_restore"]
    )


def test_cast_timeline_rows_stay_ledger_projections_with_refunds():
    # With refunds live, the public cast_timeline rows must still agree
    # with the ledger's spend receipts (resource_before/after from the
    # same account; resource_restored stays the per-cast field = 0.0 for
    # Ezreal, whose refund rides its own receipt).
    stats = dict(_EZ_LOW)
    abilities = _ezreal_abilities(stats)
    result = _fight(
        stats,
        abilities,
        duration=6.0,
        cast_order=["W", "Q", "E", "R"],
        one_rotation=True,
    )
    ledger = result["resource_ledger"]
    spends = [r for r in ledger["receipts"] if r["operation"] == "spend"]
    by_slot_ordinal = {(r["detail"]["slot"], r["detail"]["ordinal"]): r for r in spends}
    for cast in result["cast_timeline"]:
        receipt = by_slot_ordinal[(cast["slot"], cast["ordinal"])]
        assert cast["resource_before"] == pytest.approx(receipt["current_before"])
        assert cast["resource_restored"] == pytest.approx(0.0)
        assert cast["resource_after"] == pytest.approx(receipt["current_after"])
    # No duplicate mana state: gains from the refund are the ONLY gains.
    gains = [r for r in ledger["receipts"] if r["operation"] == "gain"]
    assert [r["source"] for r in gains] == [EZREAL_SOURCE]
