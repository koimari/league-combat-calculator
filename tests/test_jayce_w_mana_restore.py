"""P1 Slice 12 (RLM-2 C) — Jayce W per-basic-attack mana restore: TDD matrix.

Pins the P1-12 completion contract for Jayce's W-slot passive mana restore
(15-25 by W rank, per modeled basic attack, both stances) against the
CURRENT kernel:

  - ``src/calculator/champions/jayce.py`` — ``_w_mana_restore`` (the typed
    ``resource_restore_per_auto`` declaration + fail-closed rank-zero) and
    ``_hyper_charge`` (the empowered 3-swing burst).
  - ``src/calculator/damage.py`` — ``_auto_restore_decl`` (typed
    declaration + fail-closed validation), ``_auto_restore_schedule``
    (ordinary + burst-swing restore rows), and the consumption in
    ``_apply_mana_resource_limits``.
  - ``src/calculator/resource_ledger.py`` — the mana account and its
    receipts (gain/CAPPED/spend/denial).

This matrix is DISJOINT from ``tests/test_mana_restore_refund.py`` (the
RLM-1 M1-M10/S1/S2 package matrix): every test here is named
``test_p112_*`` and pins the P1-12 completion rules 1-15 directly.

Contract map (completion rule -> test):

  1  source evidence + typed values      test_p112_typed_atom_path_and_cached_row
  2  rank zero -> no restore             test_p112_rank_zero_no_w_no_restore
  3  ranks 1 and 6 amounts               test_p112_rank_one_and_rank_six_amounts
  4  both stances                        test_p112_both_stances_fire_restore
  5  ordinary autos per-swing identity   test_p112_ordinary_autos_restore_at_swing_times
  6  Hyper Charge burst autos            test_p112_hyper_charge_burst_swings_restore
  7  repeated casts                      test_p112_repeated_casts_restore_across_fight
  8  cap vs max mana                     test_p112_cap_behavior_restore_vs_max_mana
  9  denied bursts / fail-closed         test_p112_denied_burst_cast_never_mints_mana,
                                         test_p112_multi_declaration_fails_closed,
                                         test_p112_malformed_declarations_fail_closed,
                                         test_p112_unsupported_ledger_events_fail_closed
 10 atom receipts                        test_p112_atom_receipts_on_every_restore
 11 score parity                         test_p112_score_parity_resource_surface
 12 public ledger row shape              test_p112_public_restore_row_shape
 13 unchanged boundaries                 test_p112_damage_pricing_untouched_by_restore,
                                         test_p112_unrelated_refunds_and_champions_untouched
 14 existing regression surface          test_p112_existing_regression_surface_invariants
 15 HoB/LT-adjusted restore timing      test_p112_hail_of_blades_per_swing_restore_timing
"""

import math
from types import SimpleNamespace

import pytest

from src.calculator.ability_atoms import required_ranked_attribute_atom
from src.calculator.champions import parse_champion_abilities as parse_abilities
from src.calculator.damage import (
    FightConfig,
    _auto_restore_decl,
    calculate_fight_damage,
)
from src.calculator.data_fetcher import get_champion
from src.calculator.pipeline import FightParams, run_fight
from src.calculator.resource_ledger import (
    ResourceAccount,
    ResourceEvent,
    ResourceLedger,
)
from src.calculator.rune_effects import resolve_keystone

# The sourced atom behind Jayce's W-slot mana restore.  Source path:
# Jayce.W[0].effects[0].leveling[0].modifiers[0] ("Mana Restored",
# values [15, 17, 19, 21, 23, 25]) — see data/atoms/abilities.json.
JAYCE_RESTORE_ATOM = ("ability.mana _restored", "bfeb0d88945a263e")
JAYCE_RESTORE_VALUES = [15.0, 17.0, 19.0, 21.0, 23.0, 25.0]
JAYCE_RESTORE_SOURCE = "Jayce W passive (Mana Restored)"

_EPS = 1e-9


def _params(duration=12.0, **overrides):
    """Fight params with the auto stream EXPLICITLY on (uptime 1.0)."""
    base = dict(
        target_health=2000.0,
        target_bonus_health=0.0,
        target_armor=50.0,
        target_magic_resistance=40.0,
        fight_duration_seconds=duration,
        auto_attack_uptime=1.0,
        auto_attack_uptime_mode="explicit",
        one_rotation=False,
        include_actives=True,
        deterministic=True,
        item_options={},
    )
    base.update(overrides)
    return FightParams(**base)


def _jayce_restores(receipts):
    """Jayce W-passive restore receipts, identified by the sourced atom."""
    return [
        r
        for r in receipts
        if r["operation"] == "gain"
        and any(tuple(atom) == JAYCE_RESTORE_ATOM for atom in r["atoms"])
    ]


def _burst_attack_speed(result):
    """Hyper Charge's burst rate: base AS + 360% of the ratio, capped."""
    stats = result["champion_stats"]
    burst = stats["attack_speed"] + stats["attack_speed_ratio"] * 3.6
    return min(burst, 3.003)


def _expected_cannon_restore_times(result, duration):
    """The walk's modeled restore schedule for a Cannon (burst) fight.

    Independent derivation mirroring ``_auto_restore_schedule`` +
    ``_auto_restore_decl`` consumption: ordinary autos at i/rate over the
    leftover fight time (burst time subtracted for EVERY planned W cast,
    accepted or not), plus each Hyper Charge swing at cast_time + (k+1)/
    burst_as that lands inside the fight window.
    """
    rate = result["champion_stats"]["attack_speed"] * 1.0
    burst_as = _burst_attack_speed(result)
    w_casts = [c["time"] for c in result["cast_timeline"] if c["slot"] == "W"]
    burst_seconds = 3.0 * len(w_casts) / burst_as
    ordinary = math.floor(rate * max(0.0, duration - burst_seconds))
    times = [index / rate for index in range(ordinary)]
    for cast_time in w_casts:
        times.extend(
            cast_time + (k + 1) / burst_as
            for k in range(3)
            if cast_time + (k + 1) / burst_as <= duration + _EPS
        )
    times.sort()
    return times


# ---------------------------------------------------------------------------
# 1. Source evidence + typed values
# ---------------------------------------------------------------------------


def test_p112_typed_atom_path_and_cached_row():
    """Rule 1: the 15-25 values are discoverable through the typed path.

    ``required_ranked_attribute_atom`` reads the exact cached leveling row
    (Jayce.W[0] "Mana Restored") and validates it against the atom catalog
    (ability.mana _restored / bfeb0d88945a263e) before returning a number.
    """
    champ = get_champion("Jayce")
    for rank, expected in enumerate(JAYCE_RESTORE_VALUES, start=1):
        value, atom = required_ranked_attribute_atom(
            "Jayce", champ, "W", "Mana Restored", rank, entry_index=0
        )
        assert value == pytest.approx(expected)
        assert atom["atom_id"] == JAYCE_RESTORE_ATOM[0]
        assert atom["hash"] == JAYCE_RESTORE_ATOM[1]
        assert atom["values"] == JAYCE_RESTORE_VALUES
        assert atom["source"] == "Jayce.W[0].effects[0].leveling[0].modifiers[0]"
        assert atom["evidence"] == ["Mana Restored@effects[0]"]
    # The cached champions.json row behind the typed path (the wiki receipt):
    # the FIRST leveling entry of W[0] (Lightning Field) is the restore.
    w0 = champ["abilities"]["W"][0]
    first = w0["effects"][0]["leveling"][0]
    assert first["attribute"] == "Mana Restored"
    assert [float(v) for v in first["modifiers"][0]["values"]] == JAYCE_RESTORE_VALUES
    assert w0["effects"][0]["description"] == (
        "Passive: Jayce's basic attacks restore mana on-hit."
    )
    # The module cites the game binary's ManaGain (ranks 1-6, index 0 the
    # unleveled placeholder) as corroboration — the receipt is the docstring.
    jayce_src = (
        __import__("pathlib").Path("src/calculator/champions/jayce.py").read_text()
    )
    assert "ManaGain" in jayce_src
    assert "15/17/19/21/23/25" in jayce_src or "15-25" in jayce_src


# ---------------------------------------------------------------------------
# 2. Rank zero: no W -> no restore
# ---------------------------------------------------------------------------


def test_p112_rank_zero_no_w_no_restore():
    """Rule 2: at level 1 Jayce has W rank 0 -> the W entry is absent, so
    no declaration exists and the ledger never mints a restore."""
    champ = get_champion("Jayce")
    abilities = parse_abilities(
        champ,
        1,
        0.0,
        champion_options={"hammer_stance": True},
        champion_stats={"max_mana": 100.0, "resource_regen_per_second": 1.0},
        target_stats={"target_max_health": 2000.0},
    )
    assert "W" not in abilities  # rank zero fails closed at the module level
    result = run_fight(
        champ,
        1,
        [],
        _params(duration=8.0, champion_options={"hammer_stance": True}),
    )
    ledger = result["resource_ledger"]
    assert "auto_restore" not in ledger  # no declaration section at all
    assert _jayce_restores(ledger["receipts"]) == []
    assert {r["operation"] for r in ledger["receipts"]} <= {"spend", "regen"}
    assert result["total_damage"] > 0.0  # the fight itself is untouched


# ---------------------------------------------------------------------------
# 3. Ranks 1 and 6: 15 / 25 per basic attack
# ---------------------------------------------------------------------------


def test_p112_rank_one_and_rank_six_amounts():
    """Rule 3: every restore is 15 at W rank 1 and 25 at W rank 6."""
    champ = get_champion("Jayce")
    for level, rank, expected in ((2, 1, 15.0), (13, 6, 25.0)):
        result = run_fight(
            champ,
            level,
            [],
            _params(duration=8.0, champion_options={"hammer_stance": True}),
        )
        restores = _jayce_restores(result["resource_ledger"]["receipts"])
        assert restores, f"no restores at level {level} (W rank {rank})"
        assert all(r["amount"] == pytest.approx(expected) for r in restores)
        # The ranked atom value agrees (typed path).
        atom_value, atom = required_ranked_attribute_atom(
            "Jayce", champ, "W", "Mana Restored", rank, entry_index=0
        )
        assert atom_value == pytest.approx(expected)
        assert atom["hash"] == JAYCE_RESTORE_ATOM[1]


# ---------------------------------------------------------------------------
# 4. Both stances
# ---------------------------------------------------------------------------


def test_p112_both_stances_fire_restore():
    """Rule 4: the restore fires in Hammer AND Cannon (the module
    interpretation: the passive text lives on the hammer entry, but W is
    one shared ranked slot; neither the wiki cache nor the game binary
    states stance gating)."""
    champ = get_champion("Jayce")
    for hammer_stance in (True, False):
        result = run_fight(
            champ,
            18,
            [],
            _params(duration=8.0, champion_options={"hammer_stance": hammer_stance}),
        )
        restores = _jayce_restores(result["resource_ledger"]["receipts"])
        assert restores, f"no restores in hammer_stance={hammer_stance}"
        assert all(r["amount"] == pytest.approx(25.0) for r in restores)
        decl = result["resource_ledger"]["auto_restore"]["declaration"]
        assert decl["amount"] == 25.0
        assert decl["source"] == JAYCE_RESTORE_SOURCE
        assert decl["atoms"] == [list(JAYCE_RESTORE_ATOM)]


# ---------------------------------------------------------------------------
# 5. Ordinary autos restore at their swing times
# ---------------------------------------------------------------------------


def test_p112_ordinary_autos_restore_at_swing_times():
    """Rule 5: Hammer (no burst): every ordinary auto restores the amount
    AT its own swing time — one gain row per modeled swing, i/rate."""
    champ = get_champion("Jayce")
    result = run_fight(
        champ,
        18,
        [],
        _params(duration=12.0, champion_options={"hammer_stance": True}),
    )
    restores = _jayce_restores(result["resource_ledger"]["receipts"])
    rate = result["champion_stats"]["attack_speed"]
    expected_count = math.floor(rate * 12.0)
    expected_times = [index / rate for index in range(expected_count)]
    assert expected_count == len(restores)
    assert [r["time"] for r in restores] == [
        pytest.approx(t, abs=1e-6) for t in expected_times
    ]
    # Per-swing identity: auto_index is sequential and the kind is ordinary.
    for index, restore in enumerate(restores, start=1):
        assert restore["detail"]["kind"] == "ordinary"
        assert restore["detail"]["auto_index"] == index
        assert restore["detail"]["slot"] == "W"
        assert "arming_slot" not in restore["detail"]
    assert all(r["amount"] == pytest.approx(25.0) for r in restores)
    assert all(r["tier"] == 0.0 for r in restores)


# ---------------------------------------------------------------------------
# 6. Hyper Charge burst autos restore (in-window swings)
# ---------------------------------------------------------------------------


def test_p112_hyper_charge_burst_swings_restore():
    """Rule 6: the empowered Hyper Charge swings ARE basic attacks, so
    each in-window burst swing restores at its cast-relative time; swings
    that would land past the fight window are gated out."""
    champ = get_champion("Jayce")
    result = run_fight(
        champ,
        18,
        [],
        _params(duration=12.0, champion_options={"hammer_stance": False}),
    )
    restores = _jayce_restores(result["resource_ledger"]["receipts"])
    expected_times = _expected_cannon_restore_times(result, 12.0)
    assert [r["time"] for r in restores] == [
        pytest.approx(t, abs=1e-6) for t in expected_times
    ]
    swings = [r for r in restores if r["detail"]["kind"] == "swing"]
    ordinary = [r for r in restores if r["detail"]["kind"] == "ordinary"]
    # Two W casts land their 3 swings inside 12s; the third cast's swings
    # (12.33+) are gated out.
    assert len(swings) == 6
    assert len(ordinary) == len(restores) - 6
    burst_as = _burst_attack_speed(result)
    w_casts = [c["time"] for c in result["cast_timeline"] if c["slot"] == "W"]
    assert len(w_casts) == 3
    for swing in swings:
        detail = swing["detail"]
        assert detail["arming_slot"] == "W"
        assert detail["swing_index"] in (1, 2, 3)
        assert swing["amount"] == pytest.approx(25.0)
        expected = w_casts[detail["arming_ordinal"] - 1] + (
            detail["swing_index"] / burst_as
        )
        assert swing["time"] == pytest.approx(expected, abs=1e-6)
    # Every restore lands on the restore tier, before a simultaneous cast.
    assert all(r["tier"] == 0.0 for r in restores)


# ---------------------------------------------------------------------------
# 7. Repeated casts across the fight
# ---------------------------------------------------------------------------


def test_p112_repeated_casts_restore_across_fight():
    """Rule 7: every accepted W cast admits and its in-window swings mint
    restore rows; restore rows span the whole fight, one per modeled auto."""
    champ = get_champion("Jayce")
    result = run_fight(
        champ,
        18,
        [],
        _params(duration=12.0, champion_options={"hammer_stance": False}),
    )
    ledger = result["resource_ledger"]
    w_spends = [
        r
        for r in ledger["receipts"]
        if r["operation"] == "spend" and r["detail"]["slot"] == "W"
    ]
    assert len(w_spends) == 3  # all three W casts accepted
    assert [c["time"] for c in result["cast_timeline"] if c["slot"] == "W"] == [
        pytest.approx(0.0),
        pytest.approx(5.999, abs=1e-3),
        pytest.approx(11.998, abs=1e-3),
    ]
    restores = _jayce_restores(ledger["receipts"])
    # Restore rows cover the fight from t=0 (first auto) through the last
    # in-window swing; the count equals the modeled auto stream.
    expected_times = _expected_cannon_restore_times(result, 12.0)
    assert len(restores) == len(expected_times)
    assert restores[0]["time"] == pytest.approx(0.0)
    assert restores[-1]["time"] == pytest.approx(expected_times[-1], abs=1e-6)
    # No restore row is duplicated or shares a (time, source) key.
    keys = [(r["time"], r["source"], r["detail"]["auto_index"]) for r in restores]
    assert len(keys) == len(set(keys))


# ---------------------------------------------------------------------------
# 8. Cap behavior
# ---------------------------------------------------------------------------


def test_p112_cap_behavior_restore_vs_max_mana():
    """Rule 8: over-restoration is receipted CAPPED with current pinned at
    maximum; accepted restores never exceed it.  The t=0 auto (restore
    tier) lands before the t=0 spends on a full opening pool, so the first
    restore of the fight is always CAPPED."""
    champ = get_champion("Jayce")
    result = run_fight(
        champ,
        18,
        [],
        _params(duration=12.0, champion_options={"hammer_stance": True}),
    )
    restores = _jayce_restores(result["resource_ledger"]["receipts"])
    assert restores
    assert restores[0]["time"] == pytest.approx(0.0)
    assert restores[0]["reason"] == "CAPPED"
    assert restores[0]["current_before"] == pytest.approx(restores[0]["maximum_before"])
    capped = [r for r in restores if r["reason"] == "CAPPED"]
    assert capped  # regen refills the pool mid-fight, so later restores cap again
    for r in restores:
        assert r["current_after"] <= r["maximum_after"] + 1e-9
        assert r["current_after"] >= 0.0
        if r["reason"] == "CAPPED":
            assert r["current_after"] == pytest.approx(r["maximum_after"])
            assert r["maximum_after"] == r["maximum_before"]
        else:
            assert r["reason"] == "accepted"
            assert r["current_after"] == pytest.approx(
                r["current_before"] + r["amount"]
            )


# ---------------------------------------------------------------------------
# 9. Denied burst casts + fail-closed validation
# ---------------------------------------------------------------------------


def test_p112_denied_burst_cast_never_mints_mana():
    """Rule 9: a DENIED Hyper Charge cast never fires its swings, so its
    swing restore rows are denial receipts (arming_cast_denied), never
    gains.  Ordinary autos keep restoring."""
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
        "attack_speed_ratio": 0.658,
        "bonus_attack_speed": 0.0,
        "max_mana": 20.0,
        "resource_regen_per_second": 0.0,
    }
    abilities = parse_abilities(
        get_champion("Jayce"),
        18,
        0.0,
        champion_options={"hammer_stance": False},
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
            auto_attack_uptime=1.0,
            auto_attack_uptime_mode="explicit",
            one_rotation=False,
            deterministic=True,
            enforce_resource_limits=True,
            cast_order=["W"],
        ),
    )
    ledger = result["resource_ledger"]
    denied = [r for r in ledger["receipts"] if not r["accepted"]]
    assert any(
        r["operation"] == "spend" and r["reason"] == "insufficient_resource"
        for r in denied
    )
    # The denied cast's three swings are receipted as denials, not gains.
    denials = ledger["auto_restore"]["denials"]
    assert len(denials) == 3
    for denial in denials:
        assert denial["reason"] == "arming_cast_denied"
        assert denial["accepted"] is False
        assert denial["arming_slot"] == "W"
        assert denial["arming_ordinal"] == 1
        assert denial["source"] == JAYCE_RESTORE_SOURCE
        assert denial["swing_index"] in (1, 2, 3)
    assert [d["time"] for d in denials] == [
        pytest.approx(0.333000333, abs=1e-6),
        pytest.approx(0.666000666, abs=1e-6),
        pytest.approx(0.999000999, abs=1e-6),
    ]
    restores = _jayce_restores(ledger["receipts"])
    assert restores and all(r["detail"]["kind"] == "ordinary" for r in restores)
    # P1-12 (R1): a DENIED burst cast never fires its swings, so its
    # burst time returns to the ordinary budget — the uninterrupted
    # stream restores all 4 autos (0/1.25/2.5/3.75).
    assert len(restores) == 4


def test_p112_multi_declaration_fails_closed():
    """Rule 9: more than one per-auto restore declaration raises (the
    fight model supports one source)."""
    decl = {
        "amount": 15.0,
        "source": JAYCE_RESTORE_SOURCE,
        "atoms": (JAYCE_RESTORE_ATOM,),
    }
    state = SimpleNamespace(
        ability_damages={
            "W": {"resource_restore_per_auto": dict(decl)},
            "Q": {"resource_restore_per_auto": dict(decl)},
        }
    )
    with pytest.raises(ValueError, match="multiple resource_restore_per_auto"):
        _auto_restore_decl(state)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(amount=0.0),
        lambda d: d.update(amount=-1.0),
        lambda d: d.update(amount=True),
        lambda d: d.update(amount="x"),
        lambda d: d.update(amount=float("nan")),
        lambda d: d.update(source=""),
        lambda d: d.update(source="   "),
        lambda d: d.update(source=5),
        lambda d: d.update(atoms=()),
        lambda d: d.update(atoms=[("a",)]),
        lambda d: d.update(atoms=[("a", "b", "c")]),
        lambda d: d.update(atoms=[("a", 5)]),
    ],
)
def test_p112_malformed_declarations_fail_closed(mutate):
    """Rule 9: malformed declarations raise with the slot named."""
    decl = {
        "amount": 15.0,
        "source": JAYCE_RESTORE_SOURCE,
        "atoms": [list(JAYCE_RESTORE_ATOM)],
    }
    mutate(decl)
    state = SimpleNamespace(ability_damages={"W": {"resource_restore_per_auto": decl}})
    with pytest.raises(ValueError, match="resource_restore_per_auto"):
        _auto_restore_decl(state)


def test_p112_unsupported_ledger_events_fail_closed():
    """Rule 9: the mana account rejects unsupported events (unknown
    operation, unsupported resource kind) before any state changes."""
    with pytest.raises(ValueError, match="unknown resource operation"):
        ResourceLedger(owner="main", maximum=100.0).apply(
            ResourceEvent(owner="main", operation="bogus", amount=1.0)
        )
    with pytest.raises(ValueError, match="unsupported resource kind"):
        ResourceAccount(owner="main", kind="energy", maximum=100.0)
    # A spend beyond the pool is denied, not guessed.
    receipt = ResourceLedger(owner="main", maximum=10.0).apply(
        ResourceEvent(owner="main", operation="spend", amount=50.0)
    )
    assert receipt.accepted is False
    assert receipt.reason == "insufficient_resource"


# ---------------------------------------------------------------------------
# 10. Atom receipts
# ---------------------------------------------------------------------------


def test_p112_atom_receipts_on_every_restore():
    """Rule 10: every restore receipt carries the sourced atom id+hash and
    no other receipt does; the public auto_restore declaration mirrors it."""
    champ = get_champion("Jayce")
    result = run_fight(
        champ,
        18,
        [],
        _params(duration=12.0, champion_options={"hammer_stance": True}),
    )
    ledger = result["resource_ledger"]
    restores = _jayce_restores(ledger["receipts"])
    assert restores
    for r in restores:
        assert r["atoms"] == [list(JAYCE_RESTORE_ATOM)]
    others = [
        r for r in ledger["receipts"] if r["operation"] != "gain" or r not in restores
    ]
    for r in others:
        assert all(tuple(a) != JAYCE_RESTORE_ATOM for a in r["atoms"])
    assert ledger["auto_restore"]["declaration"] == {
        "amount": 25.0,
        "source": JAYCE_RESTORE_SOURCE,
        "atoms": [list(JAYCE_RESTORE_ATOM)],
    }


# ---------------------------------------------------------------------------
# 11. Score parity
# ---------------------------------------------------------------------------


def test_p112_score_parity_resource_surface():
    """Rule 11: score_only=True vs False agree byte-for-byte on the
    resource surface: the ledger section (receipts incl. every restore
    row), resource_spent/remaining, and cast acceptance.  Only the
    display-only per-cast resource_before/after rows are skipped in score
    mode (documented score_only contract)."""
    champ = get_champion("Jayce")
    kwargs = dict(duration=12.0, champion_options={"hammer_stance": False})
    full = run_fight(champ, 18, [], _params(**kwargs))
    score = run_fight(champ, 18, [], _params(**kwargs), score_only=True)
    assert full["resource_ledger"] == score["resource_ledger"]
    assert full["resource_spent"] == pytest.approx(score["resource_spent"])
    assert full["resource_remaining"] == pytest.approx(score["resource_remaining"])
    assert _jayce_restores(full["resource_ledger"]["receipts"]) == _jayce_restores(
        score["resource_ledger"]["receipts"]
    )
    assert (
        full["resource_ledger"]["auto_restore"]
        == score["resource_ledger"]["auto_restore"]
    )
    full_rows = [
        (c["time"], c["slot"], c["ordinal"], c["resource_cost"])
        for c in full["cast_timeline"]
    ]
    score_rows = [
        (c["time"], c["slot"], c["ordinal"], c["resource_cost"])
        for c in score["cast_timeline"]
    ]
    assert full_rows == score_rows
    assert "resource_before" in full["cast_timeline"][0]
    assert "resource_before" not in score["cast_timeline"][0]


# ---------------------------------------------------------------------------
# 12. Public ledger rows
# ---------------------------------------------------------------------------


def test_p112_public_restore_row_shape():
    """Rule 12: restore rows carry the full typed receipt shape; swing rows
    add the arming identity; the ledger section wraps them under
    resource_ledger_v1."""
    champ = get_champion("Jayce")
    result = run_fight(
        champ,
        18,
        [],
        _params(duration=12.0, champion_options={"hammer_stance": False}),
    )
    ledger = result["resource_ledger"]
    assert ledger["contract"] == "resource_ledger_v1"
    assert ledger["owner"] == "main"
    assert ledger["kind"] == "mana"
    restores = _jayce_restores(ledger["receipts"])
    assert restores
    required = {
        "owner",
        "kind",
        "operation",
        "amount",
        "time",
        "source",
        "sequence",
        "tier",
        "atoms",
        "current_before",
        "maximum_before",
        "current_after",
        "maximum_after",
        "accepted",
        "reason",
        "detail",
    }
    for r in restores:
        assert required <= set(r)
        assert r["owner"] == "main"
        assert r["kind"] == "mana"
        assert r["operation"] == "gain"
        assert r["source"] == JAYCE_RESTORE_SOURCE
        assert r["tier"] == 0.0
        assert set(r["detail"]) <= {
            "slot",
            "auto_index",
            "kind",
            "arming_slot",
            "arming_ordinal",
            "swing_index",
        }
        assert r["detail"]["slot"] == "W"
    swing = next(r for r in restores if r["detail"]["kind"] == "swing")
    assert swing["detail"]["arming_slot"] == "W"
    assert swing["detail"]["arming_ordinal"] == 1
    assert swing["detail"]["swing_index"] in (1, 2, 3)
    assert set(ledger["auto_restore"]) == {"declaration", "denials"}
    assert ledger["auto_restore"]["denials"] == []


# ---------------------------------------------------------------------------
# 13. Unchanged boundaries
# ---------------------------------------------------------------------------


def test_p112_damage_pricing_untouched_by_restore():
    """Rule 13: the restore is purely additive to the mana account — it
    never re-prices damage.  Q/R rows are byte-identical with and without
    the auto stream (restore active vs absent), and the W entry's own
    pricing is the module's (3 attacks x the ranked %AD ratio)."""
    champ = get_champion("Jayce")
    kw = dict(duration=8.0, champion_options={"hammer_stance": False})
    with_autos = run_fight(champ, 18, [], _params(**kw))
    no_autos = run_fight(champ, 18, [], _params(**{**kw, "auto_attack_uptime": 0.0}))
    assert _jayce_restores(with_autos["resource_ledger"]["receipts"])
    assert _jayce_restores(no_autos["resource_ledger"]["receipts"]) == []
    assert (
        with_autos["breakdown"]["Q"]["total_raw"]
        == no_autos["breakdown"]["Q"]["total_raw"]
    )
    assert (
        with_autos["breakdown"]["R"]["total_raw"]
        == no_autos["breakdown"]["R"]["total_raw"]
    )
    assert "E" not in with_autos["breakdown"]  # cannon gate emits nothing
    # W's authored pricing: 3 x rank-6 ratio (110% AD) x total AD.  The
    # parse entry is the same number the engine prices.
    parse = parse_abilities(
        champ,
        18,
        0.0,
        champion_options={"hammer_stance": False},
        champion_stats=dict(with_autos["champion_stats"]),
        target_stats={"target_max_health": 2000.0},
    )
    total_ad = with_autos["champion_stats"]["attack_damage"]
    assert parse["W"]["total_raw"] == pytest.approx(3 * 1.10 * total_ad)
    # The restore amount is a MANA number, never a damage part value.
    parts = parse["W"]["parts"]
    assert all(part.amount != pytest.approx(25.0) for part in parts)
    assert all(part.amount != pytest.approx(15.0) for part in parts)


def test_p112_unrelated_refunds_and_champions_untouched():
    """Rule 13: Ezreal's W-mark refunds, ordinary mana champions, and
    manaless/energy champions keep their exact surfaces; Jayce's own
    options (accelerated_q, hammer_stance) do not disturb the restore."""
    champ = get_champion("Jayce")
    # Ezreal refund receipts: their own source, no Jayce atom.
    ez = run_fight(
        get_champion("Ezreal"),
        18,
        [],
        _params(duration=12.0, cast_order=["W", "Q"], auto_attack_uptime=0.0),
    )
    ez_gains = [
        r for r in ez["resource_ledger"]["receipts"] if r["operation"] == "gain"
    ]
    assert ez_gains
    assert all(r["source"].startswith("Ezreal") for r in ez_gains)
    assert all(r["atoms"] == [] for r in ez_gains)
    assert not any(tuple(a) == JAYCE_RESTORE_ATOM for r in ez_gains for a in r["atoms"])
    # Ahri: spend/regen only.
    ahri = run_fight(
        get_champion("Ahri"), 18, [], _params(duration=6.0, auto_attack_uptime=0.0)
    )
    assert {r["operation"] for r in ahri["resource_ledger"]["receipts"]} <= {
        "spend",
        "regen",
    }
    # Garen (no resource) and Akali (energy): no typed ledger.
    assert (
        run_fight(get_champion("Garen"), 18, [], _params(duration=6.0))[
            "resource_ledger"
        ]
        is None
    )
    # Jayce options stay orthogonal: accelerated_q off still restores.
    aq = run_fight(
        champ,
        18,
        [],
        _params(
            duration=8.0,
            champion_options={"hammer_stance": False, "accelerated_q": False},
        ),
    )
    assert _jayce_restores(aq["resource_ledger"]["receipts"])
    assert (
        aq["breakdown"]["Q"]["total_raw"]
        < run_fight(
            champ,
            18,
            [],
            _params(duration=8.0, champion_options={"hammer_stance": False}),
        )["breakdown"]["Q"]["total_raw"]
    )


# ---------------------------------------------------------------------------
# 14. Existing regression surface (grep hits stay green)
# ---------------------------------------------------------------------------


def test_p112_existing_regression_surface_invariants():
    """Rule 14: the parse-level invariants the existing Jayce suite pins
    stay true alongside the restore: W resolves by stance, "Mana Restored"
    is never read as damage, and the burst rate is the 3.003 cap."""
    champ = get_champion("Jayce")
    hammer = parse_abilities(
        champ,
        18,
        0.0,
        champion_options={"hammer_stance": True},
        champion_stats={"max_mana": 100.0, "resource_regen_per_second": 1.0},
        target_stats={"target_max_health": 2000.0},
    )
    cannon = parse_abilities(
        champ,
        18,
        0.0,
        champion_options={"hammer_stance": False},
        champion_stats={"max_mana": 100.0, "resource_regen_per_second": 1.0},
        target_stats={"target_max_health": 2000.0},
    )
    assert hammer["W"]["name"] == "Lightning Field"
    assert cannon["W"]["name"] == "Hyper Charge"
    # "Mana Restored" (15-25) never leaks into any damage value.
    for stance in (hammer, cannon):
        for part in stance["W"]["parts"]:
            assert part.amount != pytest.approx(15.0)
            assert part.amount != pytest.approx(25.0)
    assert cannon["W"]["empowers_next_auto"]["hits"] == 3
    assert cannon["W"]["empowers_next_auto"]["cooldown_starts_after_hits"] is True
    # The 3.003 cap is pinned at fight level (real resolved stats) in
    # test_p112_hyper_charge_burst_swings_restore; a bare parse with no
    # attack-speed stats resolves 0.0, so it is not pinned here.
    assert cannon["W"]["resource_restore_per_auto"]["amount"] == 25.0
    assert hammer["W"]["resource_restore_per_auto"]["amount"] == 25.0


# ---------------------------------------------------------------------------
# 15. Keystone-adjusted (Hail of Blades) per-swing restore timing
# ---------------------------------------------------------------------------


def test_p112_hail_of_blades_per_swing_restore_timing():
    """Rule 15: the restore walk rides the HAIL-ADJUSTED swing schedule.

    ``_auto_restore_schedule`` runs before ``_prepare_hail_attack_schedule``
    installs Hail's stack-sensitive schedule on ``state.hail_attack_times``,
    so it used to fall back to the uniform base schedule.  It now goes
    through ``_restore_stream_attack_timestamps``
    (``src/calculator/damage.py``), which resolves that SAME schedule
    directly from the keystone effect, so every restore lands at its real
    swing time.

    Every expected timestamp below is derived from sourced values only:

      * ``attack_speed`` / ``attack_speed_ratio`` from the fight's own
        champion stats,
      * Hail's bonus attack speed, stack count, stack duration and
        cooldown from ``data/runes.json`` via
        ``rune_effects.resolve_keystone`` accessors.

    Jayce is RANGED in both stances (module ASSUMPTIONS: his JSON
    ``attackType`` is RANGED and the wiki classifies him that way), so the
    sourced ranged branch (60%) is the one that applies.
    """
    champ = get_champion("Jayce")
    result = run_fight(
        champ,
        18,
        [],
        _params(
            duration=12.0,
            keystone="Hail of Blades",
            champion_options={"hammer_stance": True},
        ),
    )

    # --- sourced inputs -------------------------------------------------
    effect = resolve_keystone("Hail of Blades")
    stats = result["champion_stats"]
    base_rate = stats["attack_speed"]  # uptime is 1.0 in _params
    ranged_percent = effect.bonus_attack_speed_percent(False)
    assert ranged_percent == 60.0  # data/runes.json melee/ranged = 90/60
    assert effect.initial_stacks == 2
    assert effect.stack_duration_seconds == 3.0
    assert effect.cooldown_seconds == 10.0
    # AS formula: base_AS + AS_ratio x (bonus_percent / 100)
    active_rate = base_rate + stats["attack_speed_ratio"] * ranged_percent / 100.0
    base_interval = 1.0 / base_rate
    active_interval = 1.0 / active_rate
    assert active_interval < base_interval

    # --- closed-form Hail swing schedule over the 12s window ------------
    # Window 1 opens on swing 0 (2 stacks, 3s). Swings 0 and 1 consume
    # them, so the only ACTIVE-rate gap is 0 -> 1.
    swing_0 = 0.0
    swing_1 = swing_0 + active_interval
    # Stacks are gone after swing 1, so the cooldown starts there and the
    # stream reverts to the base rate for swings 2..11.
    cooldown_ready = swing_1 + effect.cooldown_seconds
    mid_swings = [swing_1 + index * base_interval for index in range(1, 11)]
    # Window 2 opens on the first swing at/after the cooldown: swing 11,
    # not swing 10.
    assert mid_swings[-2] < cooldown_ready  # swing 10 is too early
    assert mid_swings[-1] >= cooldown_ready  # swing 11 re-arms Hail
    swing_12 = mid_swings[-1] + active_interval
    assert swing_12 < 12.0  # lands inside the fight window
    # Swings 11 and 12 consume the second window's 2 stacks, so the next
    # swing would be a base-rate one past the end of the fight.
    assert swing_12 + base_interval >= 12.0
    expected_swings = [swing_0, swing_1, *mid_swings, swing_12]
    assert len(expected_swings) == 13

    # --- the restore walk mirrors that schedule swing for swing --------
    restores = _jayce_restores(result["resource_ledger"]["receipts"])
    assert [r["time"] for r in restores] == [
        pytest.approx(t, abs=1e-6) for t in expected_swings
    ]
    assert all(r["amount"] == pytest.approx(25.0) for r in restores)

    # Hail's own damage row proves the ACTIVE swings are 0, 1, 11 and 12.
    hail_row = result["breakdown"]["keystone_Hail of Blades"]
    assert [event["time"] for event in hail_row["damage_events"]] == [
        pytest.approx(t, abs=1e-6) for t in (swing_0, swing_1, mid_swings[-1], swing_12)
    ]

    # The public ``auto_attacks`` row is one event SHORT of the modeled
    # basic-attack stream, and that is not a restore-walk defect: Jayce's
    # R (Transform Mercury Hammer) declares ``empowers_next_auto``, so one
    # swing is accounted for on the R row instead ("incl. basic attack").
    # The restore walk correctly rides all 13 basic attacks; the auto row
    # is the 12-swing prefix of them.
    auto_row = result["breakdown"]["auto_attacks"]
    auto_times = [event["time"] for event in auto_row["damage_events"]]
    assert auto_row["count"] == len(auto_times) == len(expected_swings) - 1
    assert auto_times == [
        pytest.approx(t, abs=1e-6) for t in expected_swings[: len(auto_times)]
    ]
    assert "incl. basic attack" in result["breakdown"]["R"]["detail"]
