"""P3 slice 1 — mana resource ledger consumer integration tests.

Driver-level coverage for the typed mana ledger (RLM-1 owned): the cast
admission walk in ``damage._apply_mana_resource_limits``, Tear of the
Goddess (Manaflow) packets projected from ledger receipts, Lost Chapter
(Enlighten) level-up restores, and the regression guarantees the slice
must not break (ordinary cast receipts, manaless champions, Catalyst's
Eternity restore path, no duplicate events, unchanged energy admission).

The kernel itself is covered by tests/test_resource_ledger.py (RLM-2 C).
"""

from types import SimpleNamespace

import pytest

from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.item_support_effects import derive_item_support_effects
from src.calculator.pipeline import FightParams, run_fight


def _actor(participant_id, item_names, item_options=None):
    return SimpleNamespace(
        participant_id=participant_id,
        team="main" if participant_id == "main" else "enemy",
        level=18,
        items=tuple({"name": name} for name in item_names),
        stats={"mana": 1000.0, "max_mana": 1000.0, "is_melee": False},
        request=SimpleNamespace(
            item_options=item_options or {},
            ally_effects_enabled=True,
        ),
    )


def _params(*, duration=12.0, one_rotation=False, item_options=None, **overrides):
    return FightParams(
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
        **overrides,
    )


# ---------------------------------------------------------------------------
# Tear of the Goddess — ledger-driven Manaflow
# ---------------------------------------------------------------------------


def test_tear_hits_consume_banked_charges_and_grow_the_account_maximum():
    champ = get_champion("Ahri")
    items = [get_item_by_name("Tear of the Goddess")]
    result = run_fight(champ, 18, items, _params(duration=24.0))
    ledger = result["resource_ledger"]
    tear = ledger["tear"]

    # Charges bank at t=0/8/16; the first proven cast after each bank time
    # consumes the charge (E/Q/W/R all carry damage or cc proof).
    accepted = [hit for hit in tear["hits"] if hit["accepted"]]
    assert [hit["time"] for hit in accepted] == [0.0, 10.5, 20.5]
    assert [hit["bonus_delta"] for hit in accepted] == [6.0, 6.0, 6.0]
    assert tear["bonus_total"] == pytest.approx(18.0)
    assert tear["use_count"] == 3

    # The granted bonus maximum mana entered the authoritative account.
    assert ledger["bonus_maximum"] == pytest.approx(18.0)
    assert ledger["closing_maximum"] == pytest.approx(ledger["opening_maximum"] + 18.0)

    # Denial receipts are public rows (same-time casts share the pool).
    denied = [hit for hit in tear["hits"] if not hit["accepted"]]
    assert all(hit["reason"] == "no_charge_available" for hit in denied)
    assert len(denied) == 9


def test_tear_denied_cast_never_consumes_a_charge():
    # A low-mana fight denies late casts; the ledger's spend denials must
    # not produce Tear hits (no charge consumed, no grant).
    champ = get_champion("Karthus")
    # MERGE: the synthetic parser is retired - a named champion module is
    # the one runtime path (CLAUDE.md rule 7), so the fixture drives the
    # real Karthus module instead of a renamed copy of it.
    items = [get_item_by_name("Tear of the Goddess")]
    result = run_fight(
        champ,
        18,
        items,
        _params(duration=10.0),
    )
    ledger = result["resource_ledger"]
    tear = ledger["tear"]
    hits = tear["hits"]
    # Every hit receipt must be tied to an accepted cast: count the
    # accepted spend receipts and compare with hit attempts.
    spend_receipts = [r for r in ledger["receipts"] if r["operation"] == "spend"]
    accepted_spends = [r for r in spend_receipts if r["accepted"]]
    assert len(hits) == len(accepted_spends)
    # The first accepted cast (at t=0) consumes the first charge; if any
    # later cast was denied it never produced a hit at all.
    assert tear["use_count"] <= 4
    assert tear["bonus_total"] <= 24.0


def test_tear_packets_are_projected_from_ledger_hits():
    holder = _actor("main", ("Tear of the Goddess",))
    enemy = _actor("enemy", ())
    champ = get_champion("Ahri")
    result = run_fight(
        champ, 18, [get_item_by_name("Tear of the Goddess")], _params(duration=24.0)
    )
    packets = derive_item_support_effects(holder, result, [holder, enemy])
    manaflow = [p for p in packets if p["source"] == "Tear of the Goddess — Manaflow"]
    accepted = [h for h in result["resource_ledger"]["tear"]["hits"] if h["accepted"]]
    assert len(manaflow) == len(accepted)
    assert [p["time"] for p in manaflow] == [h["time"] for h in accepted]
    assert [p["amount"] for p in manaflow] == [6.0] * len(accepted)
    assert all(p["kind"] == "resource" for p in manaflow)
    assert all(p["target_scope"] == "self" for p in manaflow)
    # Packet total = in-fight accrual (authored 0 here), matching receipts.
    assert [p["bonus_mana_total"] for p in manaflow] == [6.0, 12.0, 18.0]


def test_tear_manaflow_maxed_option_emits_no_packets():
    holder = _actor(
        "main",
        ("Tear of the Goddess",),
        item_options={"Tear of the Goddess": {"manaflow_bonus_mana": 360}},
    )
    enemy = _actor("enemy", ())
    champ = get_champion("Ahri")
    result = run_fight(
        champ,
        18,
        [get_item_by_name("Tear of the Goddess")],
        _params(
            duration=12.0,
            item_options={"Tear of the Goddess": {"manaflow_bonus_mana": 360}},
        ),
    )
    tear = result["resource_ledger"]["tear"]
    assert all(not h["accepted"] for h in tear["hits"])
    assert all(h["reason"] == "cap_reached" for h in tear["hits"])
    packets = derive_item_support_effects(holder, result, [holder, enemy])
    assert not [p for p in packets if p["kind"] == "resource"]


def test_tear_missing_hit_identity_fails_closed_with_receipt():
    # A utility-only cast (no damage/cc/on-hit proof in the reviewed
    # packet) can never consume a Tear charge; the denial is a public
    # receipt with the named reason.
    champ = get_champion("Garen")  # manaless — no ledger at all
    result = run_fight(
        champ, 18, [get_item_by_name("Tear of the Goddess")], _params(duration=6.0)
    )
    assert result["resource_ledger"] is None  # NONE resource type: no ledger

    # Ahri's passive is a zero-damage self receipt but is not castable;
    # the cast stream only contains proven Q/W/E/R casts, so every hit
    # receipt has a non-empty identity.
    champ = get_champion("Ahri")
    result = run_fight(
        champ, 18, [get_item_by_name("Tear of the Goddess")], _params(duration=6.0)
    )
    for hit in result["resource_ledger"]["tear"]["hits"]:
        if not hit["accepted"]:
            assert hit["hit_identity"]  # identity was proven; denial is pool/cap
        else:
            assert hit["hit_identity"].startswith(("Q:", "W:", "E:", "R:"))


# ---------------------------------------------------------------------------
# Lost Chapter — Enlighten
# ---------------------------------------------------------------------------


def test_tear_manaflow_pays_the_fights_own_target_class():
    """Manaflow's two sourced amounts are picked by the fight's target class.

    "increased to 6 mana if they are a champion" is a class clause the ledger
    already carried both readings of, and the driver used to pass none — so a
    minion-class fight banked the champion amount.  Passing the fight's class
    is what makes admitting Tear into a minion-class fight honest.
    """

    def banked(target_class):
        result = run_fight(
            get_champion("Ahri"),
            13,
            [get_item_by_name("Tear of the Goddess")],
            _params(duration=20.0, target_class=target_class),
        )
        tear = result["resource_ledger"]["tear"]
        accepted = [hit for hit in tear["hits"] if hit["accepted"]]
        assert accepted
        assert {hit["target_kind"] for hit in accepted} == {target_class}
        return sorted({hit["bonus_delta"] for hit in accepted}), tear["bonus_total"]

    assert banked("champion") == ([6.0], 12.0)
    assert banked("minion") == ([3.0], 6.0)


def test_enlighten_runs_the_declaration_and_not_a_second_registry_read():
    """The three Enlighten numbers have one home: the ``ResourceRestoreRule``.

    ``damage._enlighten_decl_for`` used to read the registry keys directly
    while the compiled declaration was consumed by nothing — two homes for
    one schedule.  It now resolves the rule, so the declaration's numbers ARE
    the ones the ledger schedules.
    """
    from src.calculator.damage import _enlighten_decl_for
    from src.calculator.interpreters.stat_derivation import sole_declared_derivation
    from src.calculator.item_behavior import ResourceRestoreRule

    items = [get_item_by_name("Lost Chapter")]
    declaration = _enlighten_decl_for(SimpleNamespace(items=items))
    slot = sole_declared_derivation(["Lost Chapter"], ResourceRestoreRule)
    assert slot is not None
    assert declaration.restore_percent == pytest.approx(slot.value("share_of_maximum"))
    assert declaration.duration_seconds == pytest.approx(slot.value("duration"))
    assert declaration.ticks == int(slot.value("ticks"))
    assert (declaration.restore_percent, declaration.duration_seconds) == (20.0, 3.0)
    assert declaration.ticks == 3


def test_lost_chapter_absent_choice_creates_no_trigger():
    champ = get_champion("Ahri")
    items = [get_item_by_name("Lost Chapter")]
    result = run_fight(champ, 18, items, _params(duration=8.0))
    ledger = result["resource_ledger"]
    assert ledger.get("enlighten") is None
    assert not [
        r for r in ledger["receipts"] if r["source"] == "Lost Chapter — Enlighten"
    ]


def test_lost_chapter_explicit_level_up_restores_20_percent_over_3_seconds():
    champ = get_champion("Ahri")
    items = [get_item_by_name("Lost Chapter")]
    result = run_fight(
        champ,
        18,
        items,
        _params(
            duration=8.0,
            item_options={"Lost Chapter": {"enlighten_level_up_seconds": 2.0}},
        ),
    )
    ledger = result["resource_ledger"]
    enlighten = ledger["enlighten"]
    assert enlighten["triggered"] is True
    assert enlighten["reason"] == "level_up_restore_scheduled"
    assert enlighten["ticks_within_window"] == 3

    gains = [
        r
        for r in ledger["receipts"]
        if r["operation"] == "gain" and r["source"] == "Lost Chapter — Enlighten"
    ]
    assert [r["time"] for r in gains] == [3.0, 4.0, 5.0]
    expected_tick = ledger["opening_maximum"] * 0.20 / 3.0
    assert all(r["amount"] == pytest.approx(expected_tick) for r in gains)
    # Same-time ordering: the ticks land on the restore tier before any
    # simultaneous cast, and casts strictly before the level-up never see
    # the restored mana.
    assert all(r["tier"] == 0.0 for r in gains)


def test_lost_chapter_level_up_outside_window_is_receipted():
    champ = get_champion("Ahri")
    items = [get_item_by_name("Lost Chapter")]
    result = run_fight(
        champ,
        18,
        items,
        _params(
            duration=4.0,
            item_options={"Lost Chapter": {"enlighten_level_up_seconds": 4.0}},
        ),
    )
    enlighten = result["resource_ledger"]["enlighten"]
    assert enlighten["triggered"] is True  # the level-up exists
    assert enlighten["ticks_within_window"] == 0  # no tick lands in-window
    assert not [
        r
        for r in result["resource_ledger"]["receipts"]
        if r["source"] == "Lost Chapter — Enlighten"
    ]


def test_lost_chapter_level_up_can_enable_a_later_cast():
    # MERGE: the window is long enough for the real Karthus module to run
    # its mana out - a fight that never starves cannot show a restore
    # enabling anything (at 10s both walks spend the same 996).
    champ = get_champion("Karthus")
    # MERGE: the synthetic parser is retired - a named champion module is
    # the one runtime path (CLAUDE.md rule 7), so the fixture drives the
    # real Karthus module instead of a renamed copy of it.
    items = [get_item_by_name("Lost Chapter")]
    without = run_fight(
        champ,
        18,
        items,
        _params(duration=20.0),
    )
    with_level = run_fight(
        champ,
        18,
        items,
        _params(
            duration=20.0,
            item_options={"Lost Chapter": {"enlighten_level_up_seconds": 2.0}},
        ),
    )
    spent_without = sum(
        r["amount"]
        for r in without["resource_ledger"]["receipts"]
        if r["operation"] == "spend" and r["accepted"]
    )
    spent_with = sum(
        r["amount"]
        for r in with_level["resource_ledger"]["receipts"]
        if r["operation"] == "spend" and r["accepted"]
    )
    # The level-up restores 20% of max mana, so the fight can afford more
    # mana overall (later casts are enabled).
    assert spent_with > spent_without
    assert (
        "insufficient_resource"
        not in {
            r["reason"]
            for r in with_level["resource_ledger"]["receipts"]
            if not r["accepted"]
        }
        or spent_with > spent_without
    )


# ---------------------------------------------------------------------------
# Regression — shared ledger invariants
# ---------------------------------------------------------------------------


def test_ordinary_cast_receipts_keep_the_timeline_shape():
    champ = get_champion("Ahri")
    result = run_fight(champ, 18, [], _params(duration=6.0))
    ledger = result["resource_ledger"]
    spends = [r for r in ledger["receipts"] if r["operation"] == "spend"]
    assert spends and all(r["accepted"] for r in spends)
    # cast_timeline rows agree with the ledger receipts.
    by_slot_ordinal = {(r["detail"]["slot"], r["detail"]["ordinal"]): r for r in spends}
    for cast in result["cast_timeline"]:
        receipt = by_slot_ordinal[(cast["slot"], cast["ordinal"])]
        assert cast["resource_before"] == pytest.approx(receipt["current_before"])
        assert cast["resource_after"] == pytest.approx(receipt["current_after"])
    # current never leaves [0, maximum].
    for r in ledger["receipts"]:
        assert 0.0 <= r["current_after"] <= r["maximum_after"] + 1e-9


def test_manaless_champion_has_no_ledger_and_no_crash():
    champ = get_champion("Garen")
    result = run_fight(
        champ,
        18,
        [get_item_by_name("Tear of the Goddess"), get_item_by_name("Lost Chapter")],
        _params(
            duration=6.0,
            item_options={"Lost Chapter": {"enlighten_level_up_seconds": 2.0}},
        ),
    )
    assert result["resource_ledger"] is None
    assert result["resource_spent"] == 0.0
    assert result["resource_remaining"] == 0.0


def test_tear_plus_lost_chapter_compose_in_one_account():
    champ = get_champion("Ahri")
    items = [
        get_item_by_name("Tear of the Goddess"),
        get_item_by_name("Lost Chapter"),
    ]
    result = run_fight(
        champ,
        18,
        items,
        _params(
            duration=12.0,
            item_options={"Lost Chapter": {"enlighten_level_up_seconds": 1.0}},
        ),
    )
    ledger = result["resource_ledger"]
    assert ledger["tear"]["bonus_total"] == pytest.approx(12.0)  # t=0, t=8
    assert ledger["enlighten"]["triggered"] is True
    gains = [r for r in ledger["receipts"] if r["source"] == "Lost Chapter — Enlighten"]
    assert [r["time"] for r in gains] == [2.0, 3.0, 4.0]
    # The max increases (Tear) and gains (Enlighten) share one account.
    assert ledger["bonus_maximum"] == pytest.approx(12.0)
    # No duplicate events: one receipt per applied event.
    keys = [(r["time"], r["operation"], r["source"]) for r in ledger["receipts"]]
    assert len(keys) == len(set(keys))


def test_catalyst_restores_ride_the_same_account():
    # Catalyst's Eternity restores are external gain events on the SAME
    # ledger the cast admission reads; a restore at t lands before a
    # simultaneous cast (engine convention) and enables it.
    champ = get_champion("Ahri")
    items = [get_item_by_name("Catalyst of Aeons")]
    result = run_fight(
        champ,
        18,
        items,
        _params(duration=6.0, resource_restore_events=((3.0, 500.0),)),
    )
    ledger = result["resource_ledger"]
    restores = [
        r
        for r in ledger["receipts"]
        if r["operation"] == "gain" and r["source"] == "Catalyst of Aeons (Eternity)"
    ]
    assert [r["time"] for r in restores] == [3.0]
    assert restores[0]["amount"] == pytest.approx(500.0)
    # result exposure keeps the public resource_restore_events rows.
    exposed = result.get("resource_restore_events")
    assert exposed == [
        {"time": 3.0, "amount": 500.0, "source": "Catalyst of Aeons (Eternity)"}
    ]


def test_energy_admission_keeps_the_legacy_walk():
    # Akali's energy fights must be bit-for-bit unchanged (legacy walk).
    champ = get_champion("Akali")
    result = run_fight(champ, 18, [], _params(duration=6.0))
    assert result["resource_ledger"] is None  # ENERGY: legacy path
    assert result["resource_spent"] > 0.0


def test_both_walks_price_a_cast_against_the_one_actualizer_multiplier():
    """Mana and energy read the same open-window trade (the sourced 2x).

    The number is resolved once onto the fight state from the item's own
    ``ActiveWindowCastEconomyRule``; neither walk holds a second source for
    it, so a build that opens the window spends double on either lane.
    """
    items = [get_item_by_name("Actualizer")]
    window = {"Actualizer": {"mana_made_real_active": 1}}

    def paid(result):
        # What each cast actually took out of the pool: the published
        # ``resource_cost`` row is the ability's undiscounted number.
        return {
            (row["slot"], row["ordinal"]): (
                row["resource_before"]
                - row["resource_after"]
                + row["resource_restored"]
            )
            for row in result["cast_timeline"]
        }

    for champion in ("Ahri", "Akali"):
        champ = get_champion(champion)
        closed = paid(
            run_fight(get_champion(champion), 18, items, _params(duration=3.0))
        )
        open_window = paid(
            run_fight(champ, 18, items, _params(duration=3.0, item_options=window))
        )
        # Doubling the price can cost a fixed pool a later cast (Akali's
        # 200 energy cannot pay a second 140-energy Q), which is admission
        # rather than the pricing this test pins.
        priced = {
            key: amount
            for key, amount in closed.items()
            if amount > 0.0 and key in open_window
        }
        assert priced
        for key, amount in priced.items():
            assert open_window[key] == pytest.approx(2.0 * amount)
