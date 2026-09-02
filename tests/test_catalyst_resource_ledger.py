"""P3 Package 3A — Catalyst of Aeons on the typed mana resource ledger.

Contract under test (binding for the coordinator's P3-3A integration):

* The typed mana resource ledger's ACCEPTED-SPEND RECEIPTS are the single
  authoritative source of Eternity's mana-spent heal: every accepted
  mana-spending cast produces a heal of 25% of spent mana, capped at 20
  per cast AND 20 per second (one-second floor buckets).
* Denied casts (insufficient mana) produce NO heal.
* Incoming PRE-MITIGATION champion damage restores mana at the hit
  timestamp (10% of raw_damage) through the SAME account, capped at max
  mana; a restore at the same timestamp as a cast applies BEFORE the
  cast's spend (restore tier 0 vs cast tier 1).
* Restores outside the fight window fail closed; zero-damage packets mint
  no mana; exactly one heal event per accepted spend and one restore per
  incoming hit (no duplicates).
* Public output exposes the applied restore/heal amount, time, and source,
  and the ledger receipts exist.
* The compiled/score path fails closed for Catalyst builds with the named
  ``item_mechanic=Catalyst of Aeons`` receipt (its owner's declared
  ``ReceiptOnly`` compilability in the survival-ledger scope).

This file is the focused matrix owner's file for P3-3A: it tests the
contract through the fight kernel (``calculate_fight_damage`` /
``run_fight`` / ``build_participant_timeline``) with Catalyst of Aeons in
the build, plus the two producer/consumer seams the contract rides
(``roster_composition.resource_restores`` and
``pipeline._item_self_healing_events``).

Asserted constants (0.10 / 0.25 / 20 / 20) are the typed accessors'
expected values; per AGENTS.md rule 5, tests may assert literals — source
must not.
"""

import math
from types import SimpleNamespace

import pytest

from src.calculator.champions import parse_champion_abilities
from src.calculator.damage import calculate_fight_damage
from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.defensive_effects import resolve_starting_defenses
from src.calculator.interpreters import (
    compilability_for,
    uncompilable_item_receipt,
)
from src.calculator.item_behavior import ReceiptOnly, ReceiptScope
from src.calculator.item_effects import sustain_effect_value
from src.calculator.participant_timeline import (
    CoupledSearchContext,
    build_participant_timeline,
)
from src.calculator.pipeline import (
    FightParams,
    _item_self_healing_events,
    run_fight,
)

# MERGE: the producer seam moved to ``roster_composition`` and dropped the
# item's name from its own -- it now asks the build for its declared
# mana-spent heal rule instead (CLAUDE.md rule 6).  Same signature, same
# ``(restores, complete)`` return.
from src.calculator.roster_composition import (
    resource_restores as _catalyst_resource_restores,
)
from src.calculator.scenario import ChampionLoadout
from src.calculator.stats import calculate_total_stats

CATALYST = "Catalyst of Aeons"
ETERNITY = "Catalyst of Aeons (Eternity)"

# Typed-accessor expected values (asserted literals are allowed in tests).
RATIO_RESTORE = 0.10
RATIO_HEAL = 0.25
CAP_PER_CAST = 20.0
CAP_PER_SECOND = 20.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _typed_values():
    return (
        sustain_effect_value(CATALYST, "damage_taken_to_mana_ratio"),
        sustain_effect_value(CATALYST, "mana_spent_heal_ratio"),
        sustain_effect_value(CATALYST, "mana_spent_heal_cap_per_cast"),
        sustain_effect_value(CATALYST, "mana_spent_heal_cap_per_second"),
    )


def _catalyst_params(**overrides):
    base = {
        "target_health": 10000.0,
        "target_bonus_health": 0.0,
        "target_armor": 0.0,
        "target_magic_resistance": 0.0,
        "fight_duration_seconds": 4.0,
        "auto_attack_uptime": 0.0,
        "one_rotation": False,
        "include_actives": True,
        "deterministic": True,
        "enforce_resource_limits": True,
    }
    base.update(overrides)
    return FightParams(**base)


def _modified_q_abilities(q_cost, cooldown):
    """Ahri's Q rewritten with an exact mana cost / cooldown (test fixture).

    The ability packet is rebuilt on the parsed real ability so the fight
    engine runs the standard mana admission walk with controlled spends.
    """
    champ = get_champion("Ahri")
    stats = calculate_total_stats(champ, 18, [get_item_by_name(CATALYST)])
    abilities = parse_champion_abilities(
        champ, 18, stats["ability_power"], champion_stats=stats
    )
    q = dict(abilities["Q"])
    q.update(
        {
            "resource_type": "MANA",
            "resource_cost": float(q_cost),
            "cooldown": float(cooldown),
        }
    )
    stats = dict(stats)
    stats.update({"max_mana": 500.0, "resource_regen_per_second": 0.0})
    return stats, {"Q": q}


def _catalyst_fight(
    q_cost,
    cooldown,
    duration,
    *,
    restore_events=(),
    max_mana=500.0,
    regen=0.0,
):
    """Run a one-ability Catalyst fight through the engine kernel.

    Returns (result, accepted_spend_receipts, denied_spend_receipts) where
    the spend receipts come from the ledger's own public receipt log.
    """
    stats, abilities = _modified_q_abilities(q_cost, cooldown)
    stats.update(
        {"max_mana": float(max_mana), "resource_regen_per_second": float(regen)}
    )
    result = calculate_fight_damage(
        stats,
        abilities,
        [get_item_by_name(CATALYST)],
        _catalyst_params(
            fight_duration_seconds=duration,
            cast_order=["Q"],
            resource_restore_events=tuple(restore_events),
        ),
    )
    spends = [
        r for r in result["resource_ledger"]["receipts"] if r["operation"] == "spend"
    ]
    accepted = [r for r in spends if r["accepted"]]
    denied = [r for r in spends if not r["accepted"]]
    return result, accepted, denied


def _catalyst_heal_packets(result, duration):
    """The Eternity heal packets a fight result produces (pipeline walk)."""
    return [
        e
        for e in _item_self_healing_events(
            result, [get_item_by_name(CATALYST)], duration
        )
        if e["source"] == ETERNITY
    ]


def _expected_heals(
    accepted_spends,
    *,
    ratio=RATIO_HEAL,
    per_cast=CAP_PER_CAST,
    per_second=CAP_PER_SECOND,
):
    """The contract heal stream as a deterministic function of the ledger's
    accepted-spend receipts: per cast min(per_cast, ratio * spent), clamped
    by the remaining one-second bucket budget (floor(time) buckets)."""
    healed_by_bucket: dict[int, float] = {}
    out = []
    for receipt in accepted_spends:
        amount = min(per_cast, ratio * receipt["amount"])
        bucket = math.floor(float(receipt["time"]) + 1e-9)
        remaining = max(0.0, per_second - healed_by_bucket.get(bucket, 0.0))
        amount = min(amount, remaining)
        if amount > 0.0:
            healed_by_bucket[bucket] = healed_by_bucket.get(bucket, 0.0) + amount
            out.append((float(receipt["time"]), round(amount, 9)))
    return out


def _catalyst_actor(participant_id="main", *, has_catalyst=True):
    items = ({"name": CATALYST},) if has_catalyst else ()
    return SimpleNamespace(participant_id=participant_id, items=items)


def _karthus_fixture(duration=20.0):
    """Karthus cast until his mana runs out — forces late denials.

    MERGE: the twenty-second window is what the module's own rotation needs
    to exhaust the pool now that the fixture runs as Karthus rather than
    under a renamed generic parser; ten seconds accepts every cast.
    """
    # MERGE: the fixture used to rename the champion so the generic parser
    # would take it.  There is no generic parser now -- an unknown name
    # fails closed -- so it runs as Karthus, whose named module is what the
    # mana ledger under test is fed by anyway.
    champ = get_champion("Karthus")
    params = _catalyst_params(
        target_health=2000.0,
        target_armor=50.0,
        target_magic_resistance=40.0,
        fight_duration_seconds=duration,
        # Karthus declares a certified alive-state order (W first, so the
        # wall reduction is established before the damage), and the module
        # is the authority on it -- a custom order is refused.
        cast_order=None,
    )
    # MERGE: there is no ``synthetic`` parser any more -- every attacker
    # resolves to a validated named champion module or fails closed.
    result = run_fight(champ, 18, [get_item_by_name(CATALYST)], params)
    spends = [
        r for r in result["resource_ledger"]["receipts"] if r["operation"] == "spend"
    ]
    accepted = [r for r in spends if r["accepted"]]
    denied = [r for r in spends if not r["accepted"]]
    heals = [e for e in result["self_healing_events"] if e["source"] == ETERNITY]
    return result, accepted, denied, heals


# ---------------------------------------------------------------------------
# 0. Typed accessor values (the asserted-constant foundation)
# ---------------------------------------------------------------------------


def test_typed_values_match_the_sourced_catalog():
    """Eternity's four typed values are 0.10 / 0.25 / 20 / 20 (wiki branch)."""
    assert _typed_values() == pytest.approx(
        (RATIO_RESTORE, RATIO_HEAL, CAP_PER_CAST, CAP_PER_SECOND)
    )


def test_item_name_exists_in_cached_catalog():
    """The exact cached item name resolves (AGENTS.md: verify before use)."""
    item = get_item_by_name(CATALYST)
    assert item.get("name") == CATALYST
    assert any(
        passive.get("name") == "Eternity" for passive in item.get("passives", [])
    )


# ---------------------------------------------------------------------------
# 1. Accepted mana-spending casts create the capped heal (25%, per-cast 20)
# ---------------------------------------------------------------------------


def test_accepted_spends_create_heals_at_25_percent_capped_at_20():
    """The heal stream equals the contract function of the accepted-spend
    receipts: 0.25 * spent per cast, per-cast cap 20.

    A 60-mana cast heals 15 (no cap binds); a 300-mana cast heals 20
    (0.25 * 300 = 75, capped at the per-cast 20).  Times are the cast
    times, never aggregated.
    """
    result, accepted, _denied = _catalyst_fight(60.0, 2.0, 6.0)
    assert [r["time"] for r in accepted] == [0.0, 2.25, 4.5]
    heals = _catalyst_heal_packets(result, 6.0)
    assert sorted((e["time"], e["amount"]) for e in heals) == [
        (0.0, 15.0),
        (2.25, 15.0),
        (4.5, 15.0),
    ]

    result2, accepted2, _ = _catalyst_fight(200.0, 2.0, 4.0)
    assert [r["time"] for r in accepted2] == [0.0, 2.25]
    assert [r["amount"] for r in accepted2] == [200.0, 200.0]
    heals2 = _catalyst_heal_packets(result2, 4.0)
    assert sorted((e["time"], e["amount"]) for e in heals2) == [
        (0.0, CAP_PER_CAST),
        (2.25, CAP_PER_CAST),
    ]


def test_heal_stream_is_exactly_the_receipt_derived_function():
    """Contract parity: for a real multi-cast fight the observed heal
    packets equal the deterministic function of the ledger's accepted-spend
    receipts (25% ratio, per-cast 20, per-second 20 in floor buckets)."""
    result, accepted, denied = _catalyst_fight(60.0, 0.25, 2.0)
    heals = _catalyst_heal_packets(result, 2.0)
    assert sorted((e["time"], e["amount"]) for e in heals) == _expected_heals(accepted)
    assert not denied


# ---------------------------------------------------------------------------
# 2. Denied casts create NO heal
# ---------------------------------------------------------------------------


def test_denied_casts_produce_no_heal():
    """A mana-poor fight denies late casts (insufficient_resource receipts);
    the heal stream never contains a denied cast's time, and the stream
    still equals the accepted-spend-derived function (denials contribute
    zero)."""
    _result, accepted, denied, heals = _karthus_fixture()
    assert denied, "fixture must actually deny casts"
    assert all(
        not r["accepted"] and r["reason"] == "insufficient_resource" for r in denied
    )

    denied_times = {r["time"] for r in denied}
    heal_keys = [(e["time"], e["amount"]) for e in heals]
    assert not any(time in denied_times for time, _ in heal_keys)
    assert sorted(heal_keys) == _expected_heals(accepted)

    # Every heal maps to an accepted spend at the same timestamp.
    accepted_times = {r["time"] for r in accepted}
    assert all(time in accepted_times for time, _ in heal_keys)


# ---------------------------------------------------------------------------
# 3. Per-second cap: 20 heal per one-second bucket
# ---------------------------------------------------------------------------


def test_per_second_cap_clamps_bucket_totals_to_20():
    """Casts at 0.0 / 0.5 / 1.0 / 1.5 / 2.0 (60 mana each -> 15 uncapped
    per cast) produce heal totals of 20 / 20 / 15 per floor-time bucket:
    the second cast inside one second is clamped to the bucket remainder."""
    result, _accepted, _ = _catalyst_fight(60.0, 0.25, 2.0)
    heals = _catalyst_heal_packets(result, 2.0)
    assert sorted((e["time"], e["amount"]) for e in heals) == [
        (0.0, 15.0),
        (0.5, 5.0),  # bucket 0 remainder after 15
        (1.0, 15.0),
        (1.5, 5.0),  # bucket 1 remainder
        (2.0, 15.0),
    ]
    buckets: dict[int, float] = {}
    for e in heals:
        buckets[math.floor(float(e["time"]) + 1e-9)] = (
            buckets.get(math.floor(float(e["time"]) + 1e-9), 0.0) + e["amount"]
        )
    assert buckets == {0: CAP_PER_SECOND, 1: CAP_PER_SECOND, 2: 15.0}


def test_per_second_cap_binds_even_when_no_single_cast_hits_20():
    """Each individual heal is only 15 (< 20 per-cast cap); the 20/s clamp
    is what suppresses the second heal inside one second — proving the
    per-second cap is a separate, bucket-scoped constraint."""
    result, _accepted, _ = _catalyst_fight(60.0, 0.25, 2.0)
    heals = _catalyst_heal_packets(result, 2.0)
    assert len(heals) == 5  # 5 casts, 5 packets, but two are clamped
    assert all(e["amount"] <= 15.0 for e in heals)
    total = sum(e["amount"] for e in heals)
    assert total == pytest.approx(3 * 15.0 + 2 * 5.0)  # 55, not 75


# ---------------------------------------------------------------------------
# 4. Incoming pre-mitigation damage restores mana at the hit timestamp
# ---------------------------------------------------------------------------


def test_restores_follow_pre_mitigation_damage_at_hit_timestamps():
    """Two incoming champion hits (raw_damage 200 at t=1.0, 100 at t=2.5)
    produce one restore per hit at the exact hit time, each 10% of raw
    damage (20.0 and 10.0)."""
    actor = _catalyst_actor()
    incoming = {
        "main": [
            {
                "time": 1.0,
                "raw_damage": 200.0,
                "attacker": "enemy:Zed",
                "damage": 150.0,
            },
            {"time": 2.5, "raw_damage": 100.0, "attacker": "enemy:Zed", "damage": 60.0},
        ]
    }
    restores, complete = _catalyst_resource_restores(actor, incoming, 10.0)
    assert complete is True
    assert restores == ((1.0, 20.0), (2.5, 10.0))


def test_restores_land_on_the_ledger_at_the_hit_timestamp():
    """The derived restore rows enter the SAME mana account as cast
    admission: one gain receipt per restore at the hit time, source
    Eternity, on the restore tier."""
    result, _accepted, _ = _catalyst_fight(
        60.0, 2.0, 6.0, restore_events=((1.0, 20.0), (2.5, 10.0))
    )
    gains = [
        r
        for r in result["resource_ledger"]["receipts"]
        if r["operation"] == "gain" and r["source"] == ETERNITY
    ]
    assert [(r["time"], r["amount"], r["tier"], r["accepted"]) for r in gains] == [
        (1.0, 20.0, 0.0, True),
        (2.5, 10.0, 0.0, True),
    ]


def test_restore_is_capped_at_max_mana():
    """A restore larger than the room left clamps at maximum mana (CAPPED
    receipt), never exceeding the account maximum."""
    result, _, _ = _catalyst_fight(60.0, 2.0, 4.0, restore_events=((1.0, 99999.0),))
    gains = [
        r
        for r in result["resource_ledger"]["receipts"]
        if r["operation"] == "gain" and r["source"] == ETERNITY
    ]
    assert len(gains) == 1
    gain = gains[0]
    assert gain["accepted"] is True
    assert gain["reason"] == "CAPPED"
    assert gain["current_after"] == pytest.approx(gain["maximum_after"])
    assert gain["maximum_after"] == pytest.approx(500.0)


# ---------------------------------------------------------------------------
# 5. Same-time order: restore (tier 0) before cast (tier 1)
# ---------------------------------------------------------------------------


def test_same_timestamp_restore_applies_before_cast():
    """A 300-mana cast at t=2.25 is accepted ONLY when a 200-mana restore
    lands at the same timestamp: the restore receipt sorts on tier 0.0
    before the spend's tier 1.0, so the cast sees the restored mana."""
    result, accepted, denied = _catalyst_fight(
        300.0, 2.0, 4.0, restore_events=((2.25, 200.0),)
    )
    assert [r["time"] for r in accepted] == [0.0, 2.25]
    assert not denied
    at_225 = [r for r in result["resource_ledger"]["receipts"] if r["time"] == 2.25]
    assert [(r["tier"], r["operation"], r["accepted"]) for r in at_225] == [
        (0.0, "gain", True),
        (1.0, "spend", True),
    ]
    # The gain applied first: the spend's current_before includes it.
    spend = at_225[1]
    assert spend["current_before"] == pytest.approx(400.0)


def test_without_same_timestamp_restore_the_cast_is_denied():
    """Control: the identical fight without the restore denies the t=2.25
    cast (insufficient_resource), so the same-time order is what enables
    it — and a denied cast produces no heal."""
    result, accepted, denied = _catalyst_fight(300.0, 2.0, 4.0)
    assert [r["time"] for r in accepted] == [0.0]
    assert [(r["time"], r["reason"]) for r in denied] == [
        (2.25, "insufficient_resource")
    ]
    heals = _catalyst_heal_packets(result, 4.0)
    assert [(e["time"], e["amount"]) for e in heals] == [(0.0, CAP_PER_CAST)]


# ---------------------------------------------------------------------------
# 6. Cap interplay: per-cast cap vs per-second cap
# ---------------------------------------------------------------------------


def test_per_cast_cap_and_per_second_cap_interplay():
    """100-mana casts (0.25 * 100 = 25 each) are individually capped to 20
    per cast; two casts in the same second then yield only 20 total (the
    second is fully suppressed by the bucket), and a cast in the next
    second gets its full 20 again."""
    result, accepted, _ = _catalyst_fight(100.0, 0.25, 2.0)
    assert len(accepted) == 5  # 500 mana / 100 per cast
    heals = _catalyst_heal_packets(result, 2.0)
    assert sorted((e["time"], e["amount"]) for e in heals) == [
        (0.0, CAP_PER_CAST),
        (1.0, CAP_PER_CAST),
        (2.0, CAP_PER_CAST),
    ]
    total = sum(e["amount"] for e in heals)
    assert total == pytest.approx(3 * CAP_PER_CAST)


# ---------------------------------------------------------------------------
# 7. Death / window boundaries
# ---------------------------------------------------------------------------


def test_restores_outside_the_fight_window_are_dropped_not_refused():
    """A hit past the end of the window is late, not unreadable.

    MERGE: the merged reader distinguishes the two.  A number the packet
    cannot state still refuses the whole ledger; a hit after ``duration``
    is something the survival walk already knows what to do with -- every
    action past the window is skipped ``outside_window`` -- so its restore
    is mana for damage the fight never takes, dropped here rather than
    clamped forward.  Refusing the packet for it would cap every authored
    ``time_offset`` at the fight length, and Aatrox's third Q strike lands
    at 8.85s in an eight-second roster fight on a sourced cadence.
    """
    actor = _catalyst_actor()
    incoming = {"main": [{"time": 11.0, "raw_damage": 100.0, "attacker": "enemy:Zed"}]}
    restores, complete = _catalyst_resource_restores(actor, incoming, 10.0)
    assert restores == ()
    assert complete is True


def test_zero_damage_packets_mint_no_mana():
    """Zero-damage / marker packets are not damage taken: they produce no
    restore row while the ledger stays complete."""
    actor = _catalyst_actor()
    incoming = {
        "main": [
            {"time": 1.0, "raw_damage": 0.0, "attacker": "enemy:Zed"},
            {"time": 2.0, "raw_damage": 100.0, "attacker": "enemy:Zed"},
        ]
    }
    restores, complete = _catalyst_resource_restores(actor, incoming, 10.0)
    assert complete is True
    assert restores == ((2.0, 10.0),)


def test_no_catalyst_holder_never_derives_restores():
    """A participant without Catalyst produces no restores and stays
    complete (the passive is opt-in per holder)."""
    actor = _catalyst_actor(has_catalyst=False)
    incoming = {"main": [{"time": 1.0, "raw_damage": 200.0, "attacker": "enemy:Zed"}]}
    assert _catalyst_resource_restores(actor, incoming, 10.0) == ((), True)


def test_engine_ignores_out_of_window_and_zero_restore_rows():
    """At the engine seam, restore rows outside the fight window or with
    non-positive amounts never mint a gain receipt (no mana, no crash)."""
    result, _, _ = _catalyst_fight(
        60.0, 2.0, 4.0, restore_events=((11.0, 200.0), (1.0, 0.0))
    )
    gains = [
        r
        for r in result["resource_ledger"]["receipts"]
        if r["operation"] == "gain" and r["source"] == ETERNITY
    ]
    assert gains == []


# ---------------------------------------------------------------------------
# 8. No duplicate restore/heal packets
# ---------------------------------------------------------------------------


def test_exactly_one_heal_per_accepted_spend_when_bucket_has_room():
    """Three accepted spends one per second produce exactly three heal
    packets, 1:1 by time — an accepted spend never mints two heals and the
    stream contains no duplicate (time, amount) keys."""
    result, accepted, _ = _catalyst_fight(60.0, 2.0, 6.0)
    assert [r["time"] for r in accepted] == [0.0, 2.25, 4.5]
    heals = _catalyst_heal_packets(result, 6.0)
    keys = [(e["time"], e["amount"]) for e in heals]
    assert len(keys) == len(accepted) == 3
    assert len(keys) == len(set(keys))
    assert [t for t, _ in keys] == [0.0, 2.25, 4.5]
    assert all(a == pytest.approx(RATIO_HEAL * 60.0) for _, a in keys)


def test_one_restore_per_incoming_hit_even_at_the_same_timestamp():
    """Two incoming hits at the same timestamp produce two restore rows and
    the ledger applies two distinct gain receipts (never coalesced)."""
    actor = _catalyst_actor()
    incoming = {
        "main": [
            {"time": 2.0, "raw_damage": 200.0, "attacker": "enemy:Zed"},
            {"time": 2.0, "raw_damage": 50.0, "attacker": "enemy:Zed"},
        ]
    }
    restores, complete = _catalyst_resource_restores(actor, incoming, 10.0)
    assert complete is True
    assert restores == ((2.0, 20.0), (2.0, 5.0))

    result, _, _ = _catalyst_fight(60.0, 2.0, 4.0, restore_events=restores)
    gains = [
        r
        for r in result["resource_ledger"]["receipts"]
        if r["operation"] == "gain" and r["source"] == ETERNITY
    ]
    assert [(r["time"], r["amount"]) for r in gains] == [(2.0, 20.0), (2.0, 5.0)]


# ---------------------------------------------------------------------------
# 9. Public receipts
# ---------------------------------------------------------------------------


def test_public_output_exposes_restore_heal_amount_time_and_source():
    """The fight result's public sections show the applied restore rows
    (time/amount/source), the Eternity gain receipts inside the ledger, and
    the heal packets with amount/time/source — all JSON-safe rows."""
    champ = get_champion("Ahri")
    items = [get_item_by_name(CATALYST)]
    result = run_fight(
        champ,
        18,
        items,
        _catalyst_params(
            target_health=2000.0,
            target_armor=50.0,
            target_magic_resistance=40.0,
            fight_duration_seconds=6.0,
            resource_restore_events=((3.0, 500.0),),
        ),
    )
    # Public restore rows.
    exposed = result.get("resource_restore_events")
    assert exposed == [{"time": 3.0, "amount": 500.0, "source": ETERNITY}]

    # Ledger receipts: the Eternity gain is present with amount/time/source.
    ledger = result["resource_ledger"]
    assert ledger["contract"] == "resource_ledger_v1"
    gains = [
        r
        for r in ledger["receipts"]
        if r["operation"] == "gain" and r["source"] == ETERNITY
    ]
    assert [(r["time"], r["amount"], r["tier"]) for r in gains] == [(3.0, 500.0, 0.0)]
    assert all(r["accepted"] for r in gains)

    # Heal packets carry amount/time/source.
    heals = [e for e in result["self_healing_events"] if e["source"] == ETERNITY]
    assert heals
    for heal in heals:
        assert math.isfinite(float(heal["time"]))
        assert math.isfinite(float(heal["amount"]))
        assert heal["amount"] > 0.0
        assert heal["amount"] <= CAP_PER_CAST
    # Every heal is tied to an accepted spend receipt (same timestamp).
    accepted_times = {
        r["time"]
        for r in ledger["receipts"]
        if r["operation"] == "spend" and r["accepted"]
    }
    assert all(float(e["time"]) in accepted_times for e in heals)


# ---------------------------------------------------------------------------
# 10. Compiled/score path: named fail-closed for Catalyst builds
# ---------------------------------------------------------------------------


def test_catalyst_is_reported_unrepresentable_by_the_compiled_score_walk():
    """The capability report names Catalyst (its Eternity resource-restore
    second pass is legacy-only), and the compiled score walk returns the
    named ``item_mechanic=Catalyst of Aeons`` receipt for any build that
    carries it."""
    assert isinstance(
        compilability_for(CATALYST, ReceiptScope.SURVIVAL_LEDGER_TRANSITION),
        ReceiptOnly,
    )
    assert (
        uncompilable_item_receipt([{"name": CATALYST}]) == f"item_mechanic={CATALYST}"
    )
    # A representable item is untouched (control).
    assert uncompilable_item_receipt([{"name": "Infinity Edge"}]) is None


def test_catalyst_main_candidate_falls_back_with_named_receipt():
    """A Catalyst main build in score mode fails closed inside the compiler:
    the compiled panel is never populated and the result deep-equals the
    authoritative receipt walk (per-candidate fallback, no silent drop)."""
    champion = get_champion("Ahri")
    params = FightParams.from_request(
        {"fight_mode": "one_rotation", "role": "mid"}, deterministic=True
    )
    enemies = [ChampionLoadout(champion="Aatrox", level=18, items=()).resolve()]
    items = [get_item_by_name(CATALYST)]
    stats = calculate_total_stats(champion, 18, items, role="mid")
    defenses = resolve_starting_defenses("Ahri", 18, stats, items)

    def timeline(**kwargs):
        return build_participant_timeline(
            champion,
            18,
            items,
            params,
            main_stats=stats,
            main_defenses=defenses,
            enemies=enemies,
            allies=[],
            **kwargs,
        )

    legacy = timeline(include_receipt=False)
    context = CoupledSearchContext()
    fast = timeline(
        pair_result_cache={},
        include_receipt=False,
        search_context=context,
    )
    assert fast == legacy
    # Candidate-local fallback: not poisoned, but the compiled path never
    # produced a panel (the named receipt stopped it before any staging).
    assert context.uncompilable is False
    assert context.panels == {}


def test_catalyst_roster_poisons_the_compiled_context():
    """A roster actor carrying Catalyst makes the compiled path
    search-invariant-unusable: the context is marked uncompilable, the
    score result still equals the receipt walk, and later evaluations skip
    the compiled path entirely (issue #137 semantics)."""
    champion = get_champion("Ahri")
    params = FightParams.from_request(
        {"fight_mode": "one_rotation", "role": "mid"}, deterministic=True
    )
    enemies = [
        ChampionLoadout(
            champion="Dr. Mundo",
            level=18,
            role="top",
            items=(CATALYST,),
        ).resolve()
    ]
    items = [get_item_by_name("Rabadon's Deathcap")]
    stats = calculate_total_stats(champion, 18, items, role="mid")
    defenses = resolve_starting_defenses("Ahri", 18, stats, items)

    def timeline(**kwargs):
        return build_participant_timeline(
            champion,
            18,
            items,
            params,
            main_stats=stats,
            main_defenses=defenses,
            enemies=enemies,
            allies=[],
            **kwargs,
        )

    legacy = timeline(include_receipt=False)
    context = CoupledSearchContext()
    fast = timeline(
        pair_result_cache={},
        include_receipt=False,
        search_context=context,
    )
    assert fast == legacy
    assert context.uncompilable is True
    assert context.panels == {}
    # Later evaluations are still correct: the poisoned context raises
    # inside the compiler, the caller catches the (candidate-local)
    # receipt, and the receipt walk serves the identical score.
    later = timeline(
        pair_result_cache={},
        include_receipt=False,
        search_context=context,
    )
    assert later == legacy
    assert context.panels == {}


# ---------------------------------------------------------------------------
# Ambiguity / contract notes for the coordinator (P3-3A)
# ---------------------------------------------------------------------------
# 1. "Exactly one heal event per accepted spend" (matrix item 8) interacts
#    with the per-second cap: under floor-bucket semantics an accepted
#    spend landing in an exhausted bucket produces NO heal packet (the
#    amount is zero and the pipeline skips it).  This file pins that
#    observable (test_per_second_cap_*).  If P3-3A intends zero-amount heal
#    rows to still be emitted for bookkeeping, that is an additive choice
#    and the per-second-cap tests will need a companion assertion.
#
# 2. ``_catalyst_resource_restores`` treats a packet with a MISSING
#    ``raw_damage`` key as a zero-damage packet (skipped, ledger stays
#    complete) even though its docstring promises "an explicit finite
#    raw_damage".  This file pins only the explicit-zero and out-of-window
#    cases; the coordinator must decide whether missing raw_damage should
#    fail closed (complete=False) instead.
#
# 3. The engine seam silently DROPS restore rows outside the fight window
#    or with non-positive amounts (no receipt), while the public
#    ``resource_restore_events`` list echoes the raw input rows including
#    dropped ones.  test_engine_ignores_out_of_window_and_zero_restore_rows
#    pins the ledger side; if P3-3A wants a named denial receipt for
#    dropped rows, that is additive.
#
# 4. Today the heal walk reads ``cast_timeline`` rows (which the ledger's
#    accepted spends build); P3-3A will derive the heal from the ledger's
#    spend receipts directly.  All heal tests here assert the observable
#    contract (amounts/times/caps) rather than the current mechanism, so
#    they hold across the rework.
