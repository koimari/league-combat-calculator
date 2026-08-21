"""P3 package 2 — Jayce W mana restore + Ezreal W-mark mana refund.

Acceptance matrix for the planned ResourceLedger mechanics (RLM-2 C, written
against the RLM-1 contract; the mechanics themselves land in a follow-up
implementation).  One ledger per fight (resource_ledger_v1 section); the cast
admission walk in ``damage._apply_mana_resource_limits`` is the only driver.

Coverage map (matrix numbers from the RLM-1 brief; S1/S2 are the two
additionally-required pins):

  M1  Jayce W restore per sourced trigger: per-auto gains at auto
      timestamps, amount = ranked atom value (two W ranks), CAPPED receipt
      when mana is near full, restore tier before a simultaneous cast.
  M2  Denied/insufficient interactions: restore keeps later casts
      affordable; spend denials still receipted insufficient_resource;
      denied casts never produce restore/refund.
  M3  Jayce: no autos -> zero restore events; manaless/energy regression
      (Garen no ledger; Akali legacy walk unchanged).
  M4  Ezreal refund per sourced trigger: amount = 60 + detonating ability
      cost (two different costs), time = detonating cast time, lands AFTER
      the detonating spend yet is available to later casts;
      w_mark_detonation="basic_attack" -> no refund.
  M5  Ezreal caps/ordering: CAPPED refund receipt; restore tier before a
      simultaneous later cast; last W with no following ability cast ->
      NO refund event (pinned: fail-closed by absence, no denial receipt —
      RLM-1 to confirm).
  M6  No duplicate state: receipts are the only resource rows (accounting
      identity over the public section), cast_timeline agrees with ledger
      spend receipts, no per-cast resource_restore field is used.
  M7  Receipt public shape: owner/kind/op/amount/time/source/tier/atoms/
      current_before/current_after/accepted/reason; atoms present on Jayce
      restore events.
  M8  Score/receipt parity: score_only=True vs False agree on cast
      acceptance rows, resource_spent/resource_remaining, and the full
      ledger receipt stream.
  M9  Regression: an ordinary mana champion (Ahri) keeps the exact
      existing receipt shape (spend/regen rows, resource_by_cast
      agreement); manaless/energy champions untouched.
  M10 Composition: Jayce restore + Tear, and Ezreal refund + Tear + Lost
      Chapter, share ONE account (one receipt stream, no duplicates).
  S1  Sourced atom: the walk's gain amounts equal the ranked value of the
      atom read via ability_atoms.required_ranked_attribute_atom.
  S2  Both stances: Jayce's restore applies with hammer_stance on AND off.

Contract notes / details left to RLM-1 (see docstrings of the individual
tests):
  - Jayce restore source string: exact final string TBD ("Jayce — W passive
    (Mana Restored)"); tests filter receipts by the sourced ATOM
    (ability.mana _restored / bfeb0d88945a263e), not the string, and pin
    only that the source starts with "Jayce".
  - Ezreal refund source string: TBD; tests filter gains whose source
    starts with "Ezreal".
  - The refund rides tier TIER_RESTORE (0) on its receipt, but the walk
    pushes it only AFTER the detonating cast is accepted (Tear
    push-after-pop pattern), so in the receipt STREAM it lands after the
    detonating spend and before any same-time later cast.  Tests pin the
    stream order (that is the observable contract).
  - Jayce restore count (RLM-1 contract, reconciled): ordinary basic
    attacks restore at the uniform ordinary rate outside the burst
    windows, and each Hyper Charge swing that lands in-window restores
    too (the swings ARE basic attacks); swings fired past the fight
    window are gated out.  Hammer has no burst, so its count is exactly
    floor(attack_speed * duration * uptime).
"""

import math

import pytest

from src.calculator.ability_atoms import required_ranked_attribute_atom
from src.calculator.champions import parse_champion_abilities as parse_abilities
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.pipeline import FightParams, run_fight

# The sourced atom behind Jayce's W-slot mana restore (verified against
# data/atoms/abilities.json: Jayce.W[0].effects[0].leveling[0].modifiers[0],
# "Mana Restored", values [15,17,19,21,23,25]).
JAYCE_RESTORE_ATOM = ("ability.mana _restored", "bfeb0d88945a263e")
# The in-game rule constant: Ezreal restores 60 mana plus the detonating
# ability's cost (wiki prose; effect[2] has no leveling values, so like
# Manaflow's cadence this is a rule declaration, not an atom).
EZREAL_REFUND_BASE = 60.0

_EPS = 1e-9


def _params(*, duration=12.0, one_rotation=False, item_options=None, **overrides):
    base = dict(
        target_health=2000.0,
        target_bonus_health=0.0,
        target_armor=50.0,
        target_magic_resistance=40.0,
        fight_duration_seconds=duration,
        auto_attack_uptime=0.0,
        one_rotation=one_rotation,
        include_actives=True,
        deterministic=True,
        item_options=item_options or {},
    )
    base.update(overrides)
    return FightParams(**base)


def _jayce_restores(receipts):
    """Jayce W passive restore receipts, identified by the sourced atom."""
    return [
        r
        for r in receipts
        if r["operation"] == "gain"
        and any(tuple(atom) == JAYCE_RESTORE_ATOM for atom in r["atoms"])
    ]


def _ezreal_refunds(receipts):
    """Ezreal W-mark refund receipts (source string prefix TBD — RLM-1)."""
    return [
        r
        for r in receipts
        if r["operation"] == "gain" and r["source"].startswith("Ezreal")
    ]


def _expected_ezreal_refunds(result):
    """(time, amount) pairs the plan promises for a fully-accepted fight.

    The detonating ability is the next cast after each W cast in the
    resolved schedule ((time, cast_order, ordinal) order, exactly the
    cast_timeline row order); a W with no following cast refunds nothing.
    Derived from the result itself so the test stays independent of the
    engine's exact cooldown arithmetic.
    """
    # The detonating ability is the next ACCEPTED cast after each W cast in
    # the resolved schedule (accepted-cast order == ledger spend order; a
    # denied cast never consumes a mark — FIFO persistence, pinned in M2).
    # Times come from the unrounded ledger spend receipts, not the rounded
    # cast_timeline display rows.
    spend_times = [
        r["time"]
        for r in result["resource_ledger"]["receipts"]
        if r["operation"] == "spend" and r["accepted"]
    ]
    accepted_casts = [(c["slot"], c["resource_cost"]) for c in result["cast_timeline"]]
    expected = []
    for index, (slot, cost) in enumerate(accepted_casts):
        if slot != "W":
            continue
        if index + 1 >= len(accepted_casts):
            continue  # last W cast: no detonator -> no refund (pinned: M5)
        # P1-13 (R1): the mark's 4s window is enforced — a detonation
        # landing more than 4s after the W's arm is receipted mark_expired
        # and refunds nothing (the in-game mark expired before the hit).
        if spend_times[index + 1] - spend_times[index] > 4.0 + 1e-9:
            continue
        detonator_slot, detonator_cost = accepted_casts[index + 1]
        expected.append((spend_times[index + 1], EZREAL_REFUND_BASE + detonator_cost))
    return expected


def _modeled_auto_times(result, duration, uptime=1.0):
    """The walk's modeled auto schedule: i / (attack_speed * uptime)."""
    rate = result["champion_stats"]["attack_speed"] * uptime
    count = math.floor(rate * duration)
    return count, [index / rate for index in range(count)]


def _assert_accounting_identity(result):
    """Receipts are the ONLY resource truth: public opening/closing must be
    exactly reproducible from the receipt stream (a hidden second
    accumulator would break this)."""
    ledger = result["resource_ledger"]
    opening_current = ledger["opening_current"]
    opening_maximum = ledger["opening_maximum"]
    current_delta = 0.0
    maximum_delta = 0.0
    for receipt in ledger["receipts"]:
        if receipt["accepted"]:
            current_delta += receipt["current_after"] - receipt["current_before"]
            maximum_delta += receipt["maximum_after"] - receipt["maximum_before"]
    assert ledger["closing_current"] == pytest.approx(
        opening_current + current_delta, abs=1e-6
    )
    assert ledger["closing_maximum"] == pytest.approx(
        opening_maximum + maximum_delta, abs=1e-6
    )


def _assert_cast_timeline_agrees_with_spend_receipts(result):
    """Existing consumer-test pattern: cast_timeline rows are projections of
    ledger spend receipts (per-cast resource_before/after)."""
    ledger = result["resource_ledger"]
    by_slot_ordinal = {
        (r["detail"]["slot"], r["detail"]["ordinal"]): r
        for r in ledger["receipts"]
        if r["operation"] == "spend"
    }
    for cast in result["cast_timeline"]:
        receipt = by_slot_ordinal[(cast["slot"], cast["ordinal"])]
        assert cast["resource_before"] == pytest.approx(receipt["current_before"])
        assert cast["resource_after"] == pytest.approx(receipt["current_after"])


# ---------------------------------------------------------------------------
# M1 — Jayce W restore per sourced trigger
# ---------------------------------------------------------------------------


def test_m1_jayce_restore_per_auto_amount_timing_and_rank():
    # M1 + S1 (rank 6): every modeled auto restores the ranked atom value at
    # its own timestamp, on the restore tier, identified by the sourced atom.
    champ = get_champion("Jayce")
    result = run_fight(
        champ,
        18,  # W rank 6 -> atom value 25
        [],
        _params(
            duration=12.0,
            auto_attack_uptime=1.0,
            auto_attack_uptime_mode="explicit",
            champion_options={"hammer_stance": True},
        ),
    )
    receipts = result["resource_ledger"]["receipts"]
    restores = _jayce_restores(receipts)
    expected_count, expected_times = _modeled_auto_times(result, 12.0, uptime=1.0)
    assert expected_count == 11  # the walk's modeled autos (12s @ 0.99358/s)
    assert len(restores) == expected_count
    assert all(r["amount"] == pytest.approx(25.0) for r in restores)
    assert all(r["tier"] == 0.0 for r in restores)  # restore tier
    assert [r["time"] for r in restores] == [
        pytest.approx(t, abs=1e-6) for t in expected_times
    ]
    # Every modeled swing that deals damage also restores (the auto row is
    # the walk schedule minus R's one empowered swing moved to R's row).
    auto_times = [
        event["time"] for event in result["breakdown"]["auto_attacks"]["damage_events"]
    ]
    restore_times = {r["time"] for r in restores}
    assert all(any(abs(t - rt) <= 1e-6 for rt in restore_times) for t in auto_times)
    # No other gain exists in a no-item fight: restores are the ONLY gains.
    gains = [r for r in receipts if r["operation"] == "gain"]
    assert len(gains) == len(restores)


def test_m1_jayce_restore_two_ranks_match_ranked_atom_values():
    # M1 + S1 (rank 1 vs rank 6): the amount is the ranked atom value, so
    # the two fights restore different per-auto amounts.
    champ = get_champion("Jayce")
    for level, expected in ((6, 15.0), (18, 25.0)):
        rank = 6 if level == 18 else 1
        atom_value, atom = required_ranked_attribute_atom(
            "Jayce", champ, "W", "Mana Restored", rank, entry_index=0
        )
        assert atom_value == expected
        assert atom["hash"] == JAYCE_RESTORE_ATOM[1]
        result = run_fight(
            champ,
            level,
            [],
            _params(
                duration=12.0,
                auto_attack_uptime=1.0,
                auto_attack_uptime_mode="explicit",
                champion_options={"hammer_stance": True},
            ),
        )
        restores = _jayce_restores(result["resource_ledger"]["receipts"])
        assert restores, f"no restore events at level {level}"
        assert all(r["amount"] == pytest.approx(expected) for r in restores)


def test_m1_jayce_restore_capped_when_mana_near_full():
    # M1: over-restoration is receipted CAPPED with the account pinned at
    # maximum.  The t=0 auto lands before the t=0 casts (restore tier), so
    # with a full opening pool the first restore is always CAPPED; regen
    # refills the pool during the fight, so later restores cap again.
    champ = get_champion("Jayce")
    result = run_fight(
        champ,
        18,
        [],
        _params(
            duration=12.0,
            auto_attack_uptime=1.0,
            auto_attack_uptime_mode="explicit",
            champion_options={"hammer_stance": True},
        ),
    )
    ledger = result["resource_ledger"]
    restores = _jayce_restores(ledger["receipts"])
    capped = [r for r in restores if r["reason"] == "CAPPED"]
    assert capped, "expected at least one CAPPED restore"
    # The first restore of the fight (t=0, before any spend) is CAPPED.
    assert restores[0]["time"] == 0.0
    assert restores[0]["reason"] == "CAPPED"
    assert restores[0]["current_before"] == pytest.approx(restores[0]["maximum_before"])
    # Every CAPPED restore pins current at maximum; accepted restores never
    # exceed it.
    for r in restores:
        assert r["current_after"] <= r["maximum_after"] + 1e-9
        if r["reason"] == "CAPPED":
            assert r["current_after"] == pytest.approx(r["maximum_after"])
        else:
            assert r["reason"] == "accepted"


def test_m1_jayce_restore_tier_before_simultaneous_cast():
    # M1: at one timestamp the restore applies before a simultaneous cast
    # (TIER_RESTORE before TIER_CAST); t=0 has an auto and the R/Q/W/E
    # spends, so the invariant is observable in the receipt stream.
    champ = get_champion("Jayce")
    result = run_fight(
        champ,
        18,
        [],
        _params(
            duration=12.0,
            auto_attack_uptime=1.0,
            auto_attack_uptime_mode="explicit",
            champion_options={"hammer_stance": True},
        ),
    )
    receipts = result["resource_ledger"]["receipts"]
    restores = _jayce_restores(receipts)
    spends = [r for r in receipts if r["operation"] == "spend"]
    assert any(abs(r["time"] - 0.0) <= _EPS for r in restores)
    for restore in restores:
        assert restore["tier"] == 0.0
        for spend in spends:
            if abs(spend["time"] - restore["time"]) > _EPS:
                continue
            assert spend["tier"] == 1.0
            assert receipts.index(restore) < receipts.index(spend)


# ---------------------------------------------------------------------------
# M2 — denied / insufficient interactions
# ---------------------------------------------------------------------------


def test_m2_jayce_restore_keeps_later_casts_affordable():
    # M2: without autos the fight runs out of mana and the late W casts are
    # denied with insufficient_resource receipts; with the same fight plus
    # the auto stream, the restores keep those exact later casts affordable.
    champ = get_champion("Jayce")
    kwargs = dict(
        duration=60.0,
        auto_attack_uptime_mode="explicit",
        champion_options={"hammer_stance": True},
    )
    without = run_fight(champ, 6, [], _params(auto_attack_uptime=0.0, **kwargs))
    with_autos = run_fight(champ, 6, [], _params(auto_attack_uptime=1.0, **kwargs))

    denied_without = [
        r for r in without["resource_ledger"]["receipts"] if not r["accepted"]
    ]
    assert denied_without, "baseline fight must run out of mana"
    assert all(r["reason"] == "insufficient_resource" for r in denied_without)
    denied_slots = {
        (r["detail"]["slot"], r["detail"]["ordinal"]) for r in denied_without
    }
    assert ("W", 6) in denied_slots and ("W", 7) in denied_slots  # 50s / 60s W casts

    restores = _jayce_restores(with_autos["resource_ledger"]["receipts"])
    assert restores
    assert not [
        r for r in with_autos["resource_ledger"]["receipts"] if not r["accepted"]
    ], "restores must keep every later cast affordable"
    spends = [
        r
        for r in with_autos["resource_ledger"]["receipts"]
        if r["operation"] == "spend" and r["accepted"]
    ]
    accepted_slots = {(r["detail"]["slot"], r["detail"]["ordinal"]) for r in spends}
    assert denied_slots <= accepted_slots  # the formerly-denied casts now land


def test_m2_denied_casts_never_produce_refund():
    # M2: a denied cast never refunds — the FIFO mark persists past it and
    # is detonated by the NEXT ACCEPTED cast.  Low-max-mana direct-engine
    # fixture: W@0 arms a mark; the next three scheduled casts (Q/E/R) are
    # all DENIED (insufficient_resource); Q's second cast at 3.5s is
    # accepted and detonates the mark — the only refund lands at 3.5s,
    # never at a denied timestamp.
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
        "attack_damage": 100.0,
        "base_attack_damage": 60.0,
        "bonus_attack_damage": 40.0,
        "attack_speed": 0.8,
        "attack_speed_ratio": 0.625,
        "bonus_attack_speed": 0.0,
        "max_mana": 85.0,
        "resource_regen_per_second": 10.0,
    }
    abilities = parse_abilities(
        get_champion("Ezreal"),
        18,
        0.0,
        champion_options={},
        champion_stats=dict(stats),
        target_stats={"target_max_health": 2000.0},
    )
    result = calculate_fight_damage(
        stats,
        abilities,
        [],
        FightConfig(
            target_health=2000,
            target_armor=50,
            target_magic_resistance=40,
            fight_duration_seconds=6.0,
            auto_attack_uptime=0.0,
            one_rotation=False,
            deterministic=True,
            enforce_resource_limits=True,
            cast_order=["W", "Q", "E", "R"],
        ),
    )
    receipts = result["resource_ledger"]["receipts"]
    refunds = _ezreal_refunds(receipts)
    denied = [r for r in receipts if not r["accepted"]]
    assert [r["time"] for r in denied] == [0.25, 0.5, 0.75]
    assert all(r["reason"] == "insufficient_resource" for r in denied)
    denied_times = {r["time"] for r in denied}
    # The mark was NOT consumed by a denied cast: the only refund lands at
    # the first ACCEPTED cast after the W (Q's ordinal-2 cast at 3.5s).
    assert [(r["time"], r["amount"]) for r in refunds] == [
        (pytest.approx(3.5, abs=1e-6), pytest.approx(100.0))
    ]
    assert not any(abs(r["time"] - t) <= _EPS for r in refunds for t in denied_times)
    accepted_spend_times = {
        r["time"] for r in receipts if r["operation"] == "spend" and r["accepted"]
    }
    assert all(
        any(abs(r["time"] - t) <= _EPS for t in accepted_spend_times) for r in refunds
    )
    # Public receipt: the consumed mark names the detonating cast and the
    # later armed mark is receipted undetonated (never guessed).
    marks = result["resource_ledger"]["mark_refunds"]["marks"]
    assert marks[0]["reason"] == "applied"
    assert marks[0]["detonating_slot"] == "Q"
    assert marks[0]["detonating_ordinal"] == 2
    assert marks[0]["detonating_cost"] == 40.0
    assert marks[1]["reason"] == "mark_undetonated"
    assert marks[1]["accepted"] is False


# ---------------------------------------------------------------------------
# M3 — no autos / manaless / energy
# ---------------------------------------------------------------------------


def test_m3_jayce_no_autos_means_no_restores():
    # M3: zero modeled autos -> zero restore events, in both fight modes.
    champ = get_champion("Jayce")
    one_rotation = run_fight(
        champ,
        18,
        [],
        _params(
            duration=5.0, one_rotation=True, champion_options={"hammer_stance": True}
        ),
    )
    assert one_rotation["auto_attack_schedule"]["expected_autos_total"] == 0
    assert _jayce_restores(one_rotation["resource_ledger"]["receipts"]) == []

    timed_no_autos = run_fight(
        champ,
        18,
        [],
        _params(
            duration=12.0,
            auto_attack_uptime=0.0,
            champion_options={"hammer_stance": True},
        ),
    )
    assert timed_no_autos["auto_attack_schedule"]["expected_autos_total"] == 0
    assert _jayce_restores(timed_no_autos["resource_ledger"]["receipts"]) == []


def test_m3_manaless_and_energy_regression():
    # M3 + M9: Garen (no resource) has no ledger and spends nothing; Akali
    # (ENERGY) keeps the legacy walk — no ledger, legacy resource_spent.
    garen = run_fight(get_champion("Garen"), 18, [], _params(duration=6.0))
    assert garen["resource_ledger"] is None
    assert garen["resource_spent"] == 0.0
    assert garen["resource_remaining"] == 0.0

    akali = run_fight(get_champion("Akali"), 18, [], _params(duration=6.0))
    assert akali["resource_ledger"] is None
    assert akali["resource_spent"] > 0.0  # legacy ENERGY admission walk


# ---------------------------------------------------------------------------
# M4 — Ezreal refund per sourced trigger
# ---------------------------------------------------------------------------


def test_m4_ezreal_refund_amount_timing_and_order():
    # M4: refund = 60 + the detonating ability's cost, at the detonating
    # cast's time, applied AFTER the detonating spend in the receipt
    # stream.  Two detonating abilities with different costs (Q=40, E=70).
    champ = get_champion("Ezreal")
    for cast_order, det_slots in ((["W", "Q"], {"Q"}), (["W", "E"], {"E"})):
        result = run_fight(champ, 18, [], _params(duration=12.0, cast_order=cast_order))
        receipts = result["resource_ledger"]["receipts"]
        refunds = _ezreal_refunds(receipts)
        expected = _expected_ezreal_refunds(result)
        assert expected, "fixture must produce detonations"
        assert len(refunds) == len(expected)
        assert all(r["source"].startswith("Ezreal") for r in refunds)
        for refund, (time, amount) in zip(refunds, expected):
            assert refund["time"] == pytest.approx(time, abs=1e-6)
            assert refund["amount"] == pytest.approx(amount)
            assert refund["tier"] == 0.0  # restore tier on the receipt
            # Lands AFTER the detonating cast's spend (same timestamp): the
            # unique spend receipt at this time appears earlier in the stream.
            spends_at_time = [
                r
                for r in receipts
                if r["operation"] == "spend" and abs(r["time"] - time) <= _EPS
            ]
            assert len(spends_at_time) == 1
            assert receipts.index(spends_at_time[0]) < receipts.index(refund)
    # Different detonating costs refund different amounts (Q 40 -> 100,
    # E 70 -> 130).
    q_refunds = _ezreal_refunds(
        run_fight(champ, 18, [], _params(duration=12.0, cast_order=["W", "Q"]))[
            "resource_ledger"
        ]["receipts"]
    )
    e_refunds = _ezreal_refunds(
        run_fight(champ, 18, [], _params(duration=12.0, cast_order=["W", "E"]))[
            "resource_ledger"
        ]["receipts"]
    )
    assert q_refunds and e_refunds
    assert all(r["amount"] == pytest.approx(100.0) for r in q_refunds)
    assert all(r["amount"] == pytest.approx(130.0) for r in e_refunds)


def test_m4_ezreal_refund_enables_later_casts_and_basic_attack_option():
    # M4: the refund lands after the detonating cast yet is available to
    # casts AFTER it — at level 6 a 45s W/Q/E fight without refunds denies
    # six late casts; with refunds (default "ability" detonation) every
    # cast is accepted.  With w_mark_detonation="basic_attack" the mark
    # refunds nothing, so the denials come back.
    champ = get_champion("Ezreal")
    kwargs = dict(duration=45.0, cast_order=["W", "Q", "E"])
    ability_detonation = run_fight(champ, 6, [], _params(**kwargs))
    basic_attack = run_fight(
        champ,
        6,
        [],
        _params(**kwargs, champion_options={"w_mark_detonation": "basic_attack"}),
    )

    refunds = _ezreal_refunds(ability_detonation["resource_ledger"]["receipts"])
    expected = _expected_ezreal_refunds(ability_detonation)
    assert len(refunds) == len(expected) >= 6
    assert [r["amount"] for r in refunds] == [
        pytest.approx(amount) for _, amount in expected
    ]
    assert not [
        r
        for r in ability_detonation["resource_ledger"]["receipts"]
        if not r["accepted"]
    ], "refunds must keep the late casts affordable"

    # The same casts are denied when the mechanic is switched off.
    basic_refunds = _ezreal_refunds(basic_attack["resource_ledger"]["receipts"])
    assert basic_refunds == []
    denied_basic = [
        r for r in basic_attack["resource_ledger"]["receipts"] if not r["accepted"]
    ]
    assert denied_basic
    assert all(r["reason"] == "insufficient_resource" for r in denied_basic)
    denied_times = {r["time"] for r in denied_basic}
    # The late casts the refund fight accepted (Q at ~30.45, E at ~37.4)
    # are exactly the ones denied without refunds.
    late = [c for c in ability_detonation["cast_timeline"] if c["time"] > 29.0]
    assert any(c["slot"] == "Q" and abs(c["time"] - 30.45) < 0.01 for c in late)
    assert any(c["slot"] == "E" and abs(c["time"] - 37.4) < 0.01 for c in late)
    # Every cast the refund fight was able to afford late is exactly the
    # superset of the casts denied without refunds (some late casts are
    # affordable either way; the refunds buy back the rest).
    late_times = {float(c["time"]) for c in late}
    assert denied_times <= late_times


# ---------------------------------------------------------------------------
# M5 — Ezreal caps / ordering / fail-closed last W
# ---------------------------------------------------------------------------


def test_m5_ezreal_refund_capped_and_restore_tier_before_later_cast():
    # M5: one-rotation W/Q/E casts all at t=0.  W spends, Q spends, the Q
    # detonation refunds 60+40=100 — which pushes current past maximum, so
    # the refund is receipted CAPPED — and the refund (restore tier) is
    # still applied before the simultaneous E cast, whose spend sees the
    # restored (capped) pool.
    champ = get_champion("Ezreal")
    result = run_fight(
        champ,
        18,
        [],
        _params(duration=5.0, one_rotation=True, cast_order=["W", "Q", "E"]),
    )
    receipts = result["resource_ledger"]["receipts"]
    refunds = _ezreal_refunds(receipts)
    assert len(refunds) == 1
    refund = refunds[0]
    assert refund["amount"] == pytest.approx(100.0)
    assert refund["reason"] == "CAPPED"
    assert refund["tier"] == 0.0
    assert refund["current_after"] == pytest.approx(refund["maximum_after"])

    spends = [r for r in receipts if r["operation"] == "spend"]
    by_slot = {r["detail"]["slot"]: r for r in spends}
    assert receipts.index(by_slot["W"]) < receipts.index(by_slot["Q"])
    assert receipts.index(by_slot["Q"]) < receipts.index(refund)
    assert receipts.index(refund) < receipts.index(by_slot["E"])
    # The refund (restore tier) precedes the simultaneous later cast, so
    # E's spend starts from the restored pool.
    assert by_slot["E"]["current_before"] == pytest.approx(refund["maximum_after"])


def test_m5_ezreal_last_w_with_no_following_cast_refunds_nothing():
    # M5 (pinned behavior): a W whose mark is never detonated produces NO
    # refund event and NO denial receipt — fail-closed by absence (RLM-1 to
    # confirm; Tear-style named denials were considered and rejected here
    # because the plan's driver has no "end of fight" pass).  Every W
    # except the last is detonated by the next cast (a second W counts).
    champ = get_champion("Ezreal")
    result = run_fight(champ, 18, [], _params(duration=12.0, cast_order=["W"]))
    casts = result["cast_timeline"]
    w_casts = [c for c in casts if c["slot"] == "W"]
    assert len(w_casts) == 3  # t=0, 5.583, 11.167
    # P1-13 (R1): the 4s mark window — every chain gap is 5.583s, so each
    # W's mark EXPIRES before the next W's hit: zero refunds, each
    # detonation receipted mark_expired, the last mark undetonated.  The
    # fail-closed-by-absence property (no denial receipts) is unchanged.
    refunds = _ezreal_refunds(result["resource_ledger"]["receipts"])
    assert len(refunds) == 0
    marks = result["resource_ledger"]["mark_refunds"]["marks"]
    assert [m["reason"] for m in marks] == [
        "mark_expired",
        "mark_expired",
        "mark_undetonated",
    ]
    assert all(m["refund_amount"] == pytest.approx(0.0) for m in marks)
    # The last W cast itself is still accepted and spent.
    spends = [
        r
        for r in result["resource_ledger"]["receipts"]
        if r["operation"] == "spend" and r["accepted"]
    ]
    assert any(
        r["detail"]["slot"] == "W" and r["detail"]["ordinal"] == 3 for r in spends
    )


# ---------------------------------------------------------------------------
# M6 — no duplicate mana state
# ---------------------------------------------------------------------------


def test_m6_no_duplicate_mana_state_jayce():
    # M6: the ledger receipts are the only resource rows (accounting
    # identity), cast_timeline rows agree with the spend receipts, and the
    # champion module does NOT smuggle the restore through the per-cast
    # resource_restore field.
    champ = get_champion("Jayce")
    result = run_fight(
        champ,
        18,
        [],
        _params(
            duration=12.0,
            auto_attack_uptime=1.0,
            auto_attack_uptime_mode="explicit",
            champion_options={"hammer_stance": True},
        ),
    )
    restores = _jayce_restores(result["resource_ledger"]["receipts"])
    assert restores  # the mechanic is active; the invariants below pin no duplicates
    _assert_accounting_identity(result)
    _assert_cast_timeline_agrees_with_spend_receipts(result)
    assert all(cast["resource_restored"] == 0.0 for cast in result["cast_timeline"])
    keys = [
        (r["time"], r["operation"], r["source"])
        for r in result["resource_ledger"]["receipts"]
    ]
    assert len(keys) == len(set(keys))  # one receipt per applied event


def test_m6_no_duplicate_mana_state_ezreal():
    # M6, Ezreal side: same invariants with the refund active.
    champ = get_champion("Ezreal")
    result = run_fight(champ, 18, [], _params(duration=12.0, cast_order=["W", "Q"]))
    assert _ezreal_refunds(result["resource_ledger"]["receipts"])
    _assert_accounting_identity(result)
    _assert_cast_timeline_agrees_with_spend_receipts(result)
    assert all(cast["resource_restored"] == 0.0 for cast in result["cast_timeline"])
    keys = [
        (r["time"], r["operation"], r["source"])
        for r in result["resource_ledger"]["receipts"]
    ]
    assert len(keys) == len(set(keys))


# ---------------------------------------------------------------------------
# M7 — receipt public shape
# ---------------------------------------------------------------------------


def test_m7_receipt_public_shape_and_atoms():
    # M7: public receipts carry the full typed row; Jayce restore receipts
    # carry the sourced atom (id + hash).
    champ = get_champion("Jayce")
    result = run_fight(
        champ,
        18,
        [],
        _params(
            duration=12.0,
            auto_attack_uptime=1.0,
            auto_attack_uptime_mode="explicit",
            champion_options={"hammer_stance": True},
        ),
    )
    restores = _jayce_restores(result["resource_ledger"]["receipts"])
    assert restores
    for r in restores:
        for key in (
            "owner",
            "kind",
            "operation",
            "amount",
            "time",
            "source",
            "tier",
            "atoms",
            "current_before",
            "current_after",
            "accepted",
            "reason",
        ):
            assert key in r, f"missing receipt key {key}"
        assert r["owner"] == "main"
        assert r["kind"] == "mana"
        assert r["operation"] == "gain"
        assert r["atoms"] == [list(JAYCE_RESTORE_ATOM)]
        assert r["source"].startswith("Jayce")
        assert r["accepted"] in (True, False)

    # Same shape on the Ezreal refund side (atoms empty — rule constant).
    ez = run_fight(
        get_champion("Ezreal"), 18, [], _params(duration=12.0, cast_order=["W", "Q"])
    )
    refunds = _ezreal_refunds(ez["resource_ledger"]["receipts"])
    assert refunds
    for r in refunds:
        for key in (
            "owner",
            "kind",
            "operation",
            "amount",
            "time",
            "source",
            "tier",
            "atoms",
            "current_before",
            "current_after",
            "accepted",
            "reason",
        ):
            assert key in r
        assert r["source"].startswith("Ezreal")


# ---------------------------------------------------------------------------
# M8 — score / receipt parity
# ---------------------------------------------------------------------------


def test_m8_score_parity_jayce():
    # M8: score_only must not change cast acceptance, resource totals, or
    # the ledger receipt stream (the score path either agrees or the
    # implementation fails closed with a named receipt — the receipt
    # stream equality is the pinned check).
    champ = get_champion("Jayce")
    kwargs = dict(
        duration=12.0,
        auto_attack_uptime=1.0,
        auto_attack_uptime_mode="explicit",
        champion_options={"hammer_stance": True},
    )
    full = run_fight(champ, 18, [], _params(**kwargs))
    score = run_fight(champ, 18, [], _params(**kwargs), score_only=True)
    assert full["resource_spent"] == pytest.approx(score["resource_spent"])
    assert full["resource_remaining"] == pytest.approx(score["resource_remaining"])
    assert full["resource_ledger"]["receipts"] == score["resource_ledger"]["receipts"]
    full_rows = [
        (c["time"], c["slot"], c["ordinal"], c["resource_cost"])
        for c in full["cast_timeline"]
    ]
    score_rows = [
        (c["time"], c["slot"], c["ordinal"], c["resource_cost"])
        for c in score["cast_timeline"]
    ]
    assert full_rows == score_rows
    assert _jayce_restores(score["resource_ledger"]["receipts"])


def test_m8_score_parity_ezreal():
    # M8, Ezreal side (refund active in both modes).
    champ = get_champion("Ezreal")
    kwargs = dict(duration=12.0, cast_order=["W", "Q"])
    full = run_fight(champ, 18, [], _params(**kwargs))
    score = run_fight(champ, 18, [], _params(**kwargs), score_only=True)
    assert full["resource_spent"] == pytest.approx(score["resource_spent"])
    assert full["resource_remaining"] == pytest.approx(score["resource_remaining"])
    assert full["resource_ledger"]["receipts"] == score["resource_ledger"]["receipts"]
    full_rows = [
        (c["time"], c["slot"], c["ordinal"], c["resource_cost"])
        for c in full["cast_timeline"]
    ]
    score_rows = [
        (c["time"], c["slot"], c["ordinal"], c["resource_cost"])
        for c in score["cast_timeline"]
    ]
    assert full_rows == score_rows
    assert _ezreal_refunds(score["resource_ledger"]["receipts"])


# ---------------------------------------------------------------------------
# M9 — regression of ordinary cast receipts
# ---------------------------------------------------------------------------


def test_m9_ordinary_mana_cast_receipts_unchanged():
    # M9: a mana champion with no restore/refund mechanic keeps the exact
    # existing receipt shape — spend/regen rows only, no gains, and
    # cast_timeline rows agreeing with the ledger spend receipts.
    champ = get_champion("Ahri")
    result = run_fight(champ, 18, [], _params(duration=6.0))
    receipts = result["resource_ledger"]["receipts"]
    assert receipts
    assert {r["operation"] for r in receipts} <= {"spend", "regen"}
    assert all(r["accepted"] for r in receipts)
    _assert_cast_timeline_agrees_with_spend_receipts(result)
    _assert_accounting_identity(result)
    for r in receipts:
        assert 0.0 <= r["current_after"] <= r["maximum_after"] + 1e-9


# ---------------------------------------------------------------------------
# M10 — composition on one account
# ---------------------------------------------------------------------------


def test_m10_jayce_restore_and_tear_share_one_account():
    # M10: Jayce's restore gains and Tear's max-mana growth ride the SAME
    # account; bonus maximum grows, restores land, spends spend, and the
    # accounting identity reproduces the public closing state.
    champ = get_champion("Jayce")
    result = run_fight(
        champ,
        18,
        [get_item_by_name("Tear of the Goddess")],
        _params(
            duration=12.0,
            auto_attack_uptime=1.0,
            auto_attack_uptime_mode="explicit",
            champion_options={"hammer_stance": True},
        ),
    )
    ledger = result["resource_ledger"]
    restores = _jayce_restores(ledger["receipts"])
    assert restores
    assert ledger["tear"]["use_count"] == 2  # R at t=0, W at t=10
    assert ledger["bonus_maximum"] == pytest.approx(12.0)
    assert ledger["closing_maximum"] == pytest.approx(ledger["opening_maximum"] + 12.0)
    max_increases = [r for r in ledger["receipts"] if r["operation"] == "max_increase"]
    assert len(max_increases) == 2
    assert all(r["source"] == "Tear of the Goddess — Manaflow" for r in max_increases)
    _assert_accounting_identity(result)
    keys = [(r["time"], r["operation"], r["source"]) for r in ledger["receipts"]]
    assert len(keys) == len(set(keys))


def test_m10_ezreal_refund_tear_and_lost_chapter_share_one_account():
    # M10: refunds (gains), Tear max-mana growth, Lost Chapter Enlighten
    # gains, and cast spends all flow through ONE receipt stream with no
    # duplicates, and the accounting identity reproduces the closing state.
    champ = get_champion("Ezreal")
    items = [
        get_item_by_name("Tear of the Goddess"),
        get_item_by_name("Lost Chapter"),
    ]
    result = run_fight(
        champ,
        18,
        items,
        _params(
            duration=24.0,
            cast_order=["W", "Q"],
            item_options={"Lost Chapter": {"enlighten_level_up_seconds": 2.0}},
        ),
    )
    ledger = result["resource_ledger"]
    refunds = _ezreal_refunds(ledger["receipts"])
    expected = _expected_ezreal_refunds(result)
    assert len(refunds) == len(expected) == 5  # five W casts, all detonated
    assert [r["amount"] for r in refunds] == [
        pytest.approx(amount) for _, amount in expected
    ]
    assert [r["time"] for r in refunds] == [
        pytest.approx(time, abs=1e-6) for time, _ in expected
    ]
    assert ledger["tear"]["use_count"] == 3
    assert ledger["bonus_maximum"] == pytest.approx(18.0)
    assert ledger["enlighten"]["triggered"] is True
    enlighten_gains = [
        r for r in ledger["receipts"] if r["source"] == "Lost Chapter — Enlighten"
    ]
    assert [r["time"] for r in enlighten_gains] == [3.0, 4.0, 5.0]
    _assert_accounting_identity(result)
    keys = [(r["time"], r["operation"], r["source"]) for r in ledger["receipts"]]
    assert len(keys) == len(set(keys))


# ---------------------------------------------------------------------------
# S1 — sourced-atom provenance
# ---------------------------------------------------------------------------


def test_s1_restore_values_come_from_the_sourced_atom():
    # S1: the walk's gain amounts equal the ranked value of the atom read
    # through required_ranked_attribute_atom against the cached Jayce data,
    # and the receipts carry that atom's id+hash.  (Ezreal's 60 mana is a
    # rule declaration — its W effect[2] has no leveling values, so no atom
    # exists by design, same as Manaflow's cadence.)
    champ = get_champion("Jayce")
    for level, rank in ((6, 1), (18, 6)):
        atom_value, atom = required_ranked_attribute_atom(
            "Jayce", champ, "W", "Mana Restored", rank, entry_index=0
        )
        assert atom["atom_id"] == JAYCE_RESTORE_ATOM[0]
        assert atom["hash"] == JAYCE_RESTORE_ATOM[1]
        assert atom["values"] == [15.0, 17.0, 19.0, 21.0, 23.0, 25.0]
        result = run_fight(
            champ,
            level,
            [],
            _params(
                duration=12.0,
                auto_attack_uptime=1.0,
                auto_attack_uptime_mode="explicit",
                champion_options={"hammer_stance": True},
            ),
        )
        restores = _jayce_restores(result["resource_ledger"]["receipts"])
        assert restores
        assert all(r["amount"] == pytest.approx(atom_value) for r in restores)


# ---------------------------------------------------------------------------
# S2 — both stances
# ---------------------------------------------------------------------------


def test_s2_jayce_restore_applies_in_both_stances():
    # S2: the restore fires in BOTH stances.  PROVENANCE NOTE: the cached
    # wiki data declares the passive only on the Hammer W entry
    # (Jayce.W[0] "Lightning Field" effect[0]: "basic attacks restore mana
    # on-hit") — the Cannon W entry (Hyper Charge) carries no such line,
    # and the game binary's ManaGain sits on the hammer spell only.  The
    # both-stances claim rests on W being one shared ranked slot (the atom
    # is keyed by W rank); it is an explicit module interpretation
    # (RLM-2 A: neither source states stance gating either way).
    #
    # COUNT SEMANTICS (RLM-1 contract): ordinary basic attacks restore at
    # the uniform ordinary rate outside the burst windows; each Hyper
    # Charge swing that LANDS IN-WINDOW (cast_time + (k+1)/burst_as <=
    # fight duration) restores too — the three swings of a cast fired just
    # before the window end land after it and are gated out.  The hammer
    # stance has no burst, so its count is exactly floor(rate*duration).
    champ = get_champion("Jayce")
    for hammer_stance in (False, True):
        result = run_fight(
            champ,
            18,
            [],
            _params(
                duration=12.0,
                auto_attack_uptime=1.0,
                auto_attack_uptime_mode="explicit",
                champion_options={"hammer_stance": hammer_stance},
            ),
        )
        restores = _jayce_restores(result["resource_ledger"]["receipts"])
        assert restores, f"no restores in hammer_stance={hammer_stance}"
        rate = result["champion_stats"]["attack_speed"]
        if hammer_stance:
            expected_count = math.floor(rate * 12.0)
            expected_times = [index / rate for index in range(expected_count)]
        else:
            w_casts = [c["time"] for c in result["cast_timeline"] if c["slot"] == "W"]
            burst_as = 3.003
            burst_seconds = 3.0 * len(w_casts) / burst_as
            ordinary = math.floor(rate * max(0.0, 12.0 - burst_seconds))
            expected_times = [index / rate for index in range(ordinary)]
            for cast_time in w_casts:
                expected_times.extend(
                    cast_time + (k + 1) / burst_as
                    for k in range(3)
                    if cast_time + (k + 1) / burst_as <= 12.0 + _EPS
                )
            expected_times.sort()
            expected_count = len(expected_times)
        assert len(restores) == expected_count
        assert [r["time"] for r in restores] == [
            pytest.approx(t, abs=1e-6) for t in expected_times
        ]
        assert all(r["amount"] == pytest.approx(25.0) for r in restores)
        assert all(r["tier"] == 0.0 for r in restores)
