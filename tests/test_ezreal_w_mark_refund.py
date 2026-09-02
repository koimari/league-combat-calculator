"""P1 Slice 13 — Ezreal W (Essence Flux) mark-refund certification (RLM-2 C).

Contract under test: the mark-detonation mana refund declared by
``src/calculator/champions/ezreal.py`` (``mark_refund`` on the W slot) and
executed by ``src/calculator/damage.py`` (``_mark_refund_decl`` + the FIFO
``pending_marks`` walk + the detonation block).  This matrix pins the
CONTRACT.  The 4s mark expiry IS modeled (see the mark-window tests below).
Genuinely absent mechanics (target-side spell shields, multi-target mark
attribution) are named documented-boundary tests asserting the actual
current fail-closed receipts — not xfails — since no coordinator input
exists to deny a mark or attribute one to a second target, and no such
input is being added here.

Runtime facts pinned here (verified against the current sources before
writing):

- ezreal.py declares ``mark_refund`` on W: flat 60.0, source
  "Ezreal W (Essence Flux) mark refund", atoms (), detonation from the
  ``w_mark_detonation`` option ("ability" default / "basic_attack").
- damage.py: ``_mark_refund_decl`` validates the declaration (line ~4158);
  ``pending_marks`` is a FIFO of one row per accepted W cast (~4392);
  the detonation block (~4631) pops the OLDEST pending mark on every
  accepted ability cast, refunds ``flat + cost`` (the ACTUAL paid cost,
  Actualizer discount included) on the restore tier AFTER the detonating
  spend at the same timestamp, then arms the fresh mark.  Denied casts
  never consume or arm.  Undetonated marks at fight end are receipted
  ``mark_undetonated`` (fail closed, never guessed).
- Wiki prose (cached): effects[0] "marks ... for 4 seconds"; effects[1]
  "His next basic attack or ability against the target detonates the
  mark ..."; effects[2] "If the mark was detonated with an ability,
  Ezreal restores 60 mana plus the mana cost of that ability."  W cost is
  flat 50 at every rank; Q cost scales with rank ([28, 31, 34, 37, 40]).
- The atom catalog holds NO refund atom (effects[2] has no leveling row);
  the W damage atoms are the three ``ability.bonus _magic _damage`` rows
  (modifier_0 flat, modifier_1 % bonus AD, modifier_2 % AP) plus the 4s
  ``timing.active_duration`` and the 8s ``timing.cooldown``.

Fixture schedule facts (level 18, no items, haste 0): Q entry cooldown
3.0 = 4.5 - 1.5 (the Q refund stream), W 5.333 = 8 / 1.5, E 9.333,
R 60; cast times add the 0.25 cast time, so W#2 lands at 5.583 (> 4s after
W#1 — the expiry is NOT modeled) and Q#2 at 3.5.  Costs: Q rank 5 = 40,
W = 50, E = 70, R = 100.  At level 6: W rank 1 (damage 80), Q rank 3
(cost 34).
"""

import json
import re
from pathlib import Path

import pytest

from src.calculator.ability_atoms import required_ranked_attribute_atom
from src.calculator.atomizer_domains import atomize_abilities
from src.calculator.champions import get_champion_options_meta, parse_champion_abilities
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.data_fetcher import get_champion
from src.calculator.pipeline import FightParams, run_fight

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "data" / "atoms" / "abilities.json"

EZREAL = "Ezreal"
REFUND_SOURCE = "Ezreal W (Essence Flux) mark refund"
REFUND_FLAT = 60.0
# Cached W data: flat cost 50 at every rank, flat cooldown 8s, flat 4s mark
# ("marks ... for 4 seconds"; the binary DetonationTimeout 4.0; the atom
# timing.active_duration b32849b968950b8e).
W_COST = 50.0
WINDOW_SECONDS = 4.0
# Q cost scales with rank ([28, 31, 34, 37, 40]): rank 5 = 40, rank 3 = 34.
Q_COST_R5 = 40.0
Q_COST_R3 = 34.0
E_COST = 70.0

# The W damage atoms (data/atoms/abilities.json + live atomization agree).
W_DAMAGE_ATOMS = {
    0: (
        "ability.bonus _magic _damage.modifier_0",
        "fc2ec4c0d15236fc",
        [80.0, 135.0, 190.0, 245.0, 300.0],
    ),
    1: ("ability.bonus _magic _damage.modifier_1", "3bf51f22202c5058", [100.0] * 5),
    2: ("ability.bonus _magic _damage.modifier_2", "2779b25f0ed1e9de", [90.0] * 5),
}
W_MARK_WINDOW_ATOM = ("timing.active_duration", "b32849b968950b8e", [4.0])

_EPS = 1e-9


def _params(*, duration=12.0, one_rotation=False, item_options=None, **overrides):
    base = {
        "target_health": 2000.0,
        "target_bonus_health": 0.0,
        "target_armor": 50.0,
        "target_magic_resistance": 40.0,
        "fight_duration_seconds": duration,
        "auto_attack_uptime": 0.0,
        "one_rotation": one_rotation,
        "include_actives": True,
        "deterministic": True,
        "item_options": item_options or {},
    }
    base.update(overrides)
    return FightParams(**base)


def _fight(
    *,
    level=18,
    cast_order,
    duration=12.0,
    champion_options=None,
    score_only=False,
    **overrides,
):
    return run_fight(
        get_champion(EZREAL),
        level,
        [],
        _params(
            fight_duration_seconds=duration,
            cast_order=cast_order,
            champion_options=champion_options or {},
            **overrides,
        ),
        score_only=score_only,
    )


def _refunds(result):
    """Refund gain receipts, identified by the exact source string."""
    return [
        r
        for r in result["resource_ledger"]["receipts"]
        if r["operation"] == "gain" and r["source"] == REFUND_SOURCE
    ]


def _direct_fight(stats, *, duration, cast_order):
    """Direct-engine fixture (no items, explicit stats) for low-mana cases."""
    abilities = parse_champion_abilities(
        get_champion(EZREAL),
        18,
        0.0,
        champion_options={},
        champion_stats=dict(stats),
        target_stats={"target_max_health": 2000.0},
    )
    return calculate_fight_damage(
        stats,
        abilities,
        [],
        FightConfig(
            target_health=2000,
            target_armor=50,
            target_magic_resistance=40,
            fight_duration_seconds=duration,
            auto_attack_uptime=0.0,
            one_rotation=False,
            deterministic=True,
            enforce_resource_limits=True,
            cast_order=cast_order,
        ),
    )


def _assert_gain_receipt_shape(receipt):
    """The public refund receipt carries the full typed row + refund detail."""
    for key in (
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
    ):
        assert key in receipt, f"missing refund receipt key {key!r}"
    assert receipt["owner"] == "main"
    assert receipt["kind"] == "mana"
    assert receipt["operation"] == "gain"
    assert receipt["tier"] == 0.0  # restore tier
    assert receipt["atoms"] == []  # the flat 60 is atom-free
    assert receipt["source"] == REFUND_SOURCE
    detail = receipt["detail"]
    assert set(detail) == {
        "mark_slot",
        "mark_ordinal",
        "detonating_slot",
        "detonating_ordinal",
        "detonating_cost",
        "flat",
    }
    assert detail["flat"] == pytest.approx(REFUND_FLAT)


# ---------------------------------------------------------------------------
# 1 — source evidence (wiki prose, cost, 4s window; atom absence; W atoms)
# ---------------------------------------------------------------------------


def test_source_evidence_refund_clause_cost_and_mark_window():
    """The cached W data carries the wiki prose verbatim: the 4s mark, the
    basic-attack-or-ability detonation, the ability-only 60 + cost refund
    clause, and a flat rank-independent cost of 50."""
    w = get_champion(EZREAL)["abilities"]["W"][0]
    effects = w["effects"]
    assert "for 4 seconds" in effects[0]["description"]
    assert "marks" in effects[0]["description"]
    assert "basic attack or ability" in effects[1]["description"]
    assert effects[1]["leveling"]  # the bonus magic damage leveling exists
    assert effects[2]["description"] == (
        "If the mark was detonated with an ability, Ezreal restores 60 mana "
        "plus the mana cost of that ability."
    )
    assert effects[2]["leveling"] == []  # no leveling -> no atom (see below)
    cost = w["cost"]["modifiers"][0]["values"]
    assert cost == [50.0, 50.0, 50.0, 50.0, 50.0]
    cooldown = w["cooldown"]["modifiers"][0]["values"]
    assert cooldown == [8.0, 8.0, 8.0, 8.0, 8.0]


def test_source_evidence_no_refund_atom_and_w_atom_hashes():
    """The atom catalog (and the live atomization) hold NO refund atom: the
    refund clause lives in effects[2], which has no leveling row, so no atom
    exists by design.  The W damage atoms and the 4s mark window atom are
    pinned by exact id + hash + values."""
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    catalog_rows = catalog["objects"][EZREAL]
    live_rows = atomize_abilities(EZREAL, get_champion(EZREAL))["W"]

    # The two sources agree exactly on the W rows.
    catalog_w = sorted(
        (r["atom_id"], r["hash"], [float(v) for v in r["values"]])
        for r in catalog_rows
        if r["source"].startswith(f"{EZREAL}.W[")
    )
    live_w = sorted(
        (r["atom_id"], r["hash"], [float(v) for v in r["values"]]) for r in live_rows
    )
    assert catalog_w == live_w

    # Exactly five W atoms: three damage modifiers + the 4s window + the 8s cd.
    assert len(catalog_w) == 5
    for atom_id, hash_, values in catalog_w:
        if atom_id.startswith("ability.bonus _magic _damage"):
            modifier = int(atom_id.rsplit("_", 1)[1])
            expected_id, expected_hash, expected_values = W_DAMAGE_ATOMS[modifier]
            assert atom_id == expected_id
            assert hash_ == expected_hash
            assert values == expected_values
        elif atom_id == "timing.active_duration":
            assert hash_ == W_MARK_WINDOW_ATOM[1]
            assert values == W_MARK_WINDOW_ATOM[2]
        else:
            assert atom_id == "timing.cooldown"
            assert hash_ == "b794a6fc0b95a03b"
            assert values == [8.0] * 5

    # Atom absence: nothing in the Ezreal catalog is a mana/refund atom and
    # nothing is sourced from the refund clause (effects[2]).
    for row in catalog_rows:
        assert "mana" not in row["atom_id"]
        assert "effects[2]" not in row["source"]
        assert "effects[2]" not in " ".join(row.get("evidence", []))


def test_source_evidence_refund_flat_is_a_typed_rule_declaration():
    """The module declares the flat 60 through the public options meta and
    the parsed W entry carries the typed mark_refund rule; the W damage rank
    value comes from the atom (via required_ranked_attribute_atom) while the
    flat 60 has no atom to read (the query fails closed)."""
    meta = get_champion_options_meta(EZREAL)
    options = {o["key"]: o for o in meta["options"]}
    assert set(options) == {"w_mark_detonation", "passive_stacks"}
    assert options["w_mark_detonation"]["default"] == "ability"
    assert [c["value"] for c in options["w_mark_detonation"]["choices"]] == [
        "ability",
        "basic_attack",
    ]

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
        "max_mana": 1565.0,
        "resource_regen_per_second": 8.5,
    }
    w_entry = parse_champion_abilities(
        get_champion(EZREAL),
        18,
        0.0,
        champion_options={},
        champion_stats=dict(stats),
        target_stats={"target_max_health": 2000.0},
    )["W"]
    assert w_entry["mark_refund"] == {
        "flat": REFUND_FLAT,
        "window_seconds": WINDOW_SECONDS,
        "source": REFUND_SOURCE,
        "atoms": (),
        "detonation": "ability",
    }
    assert w_entry["resource_cost"] == W_COST

    # Ranked W damage atom values (modifier_0 = flat bonus magic damage).
    for rank, expected in ((1, 80.0), (5, 300.0)):
        value, atom = required_ranked_attribute_atom(
            EZREAL,
            get_champion(EZREAL),
            "W",
            "Bonus Magic Damage",
            rank,
            modifier_index=0,
        )
        assert value == expected
        assert atom["hash"] == W_DAMAGE_ATOMS[0][1]
        # A refund/mana attribute has no leveling row -> the typed query
        # fails closed (no atom exists to read the flat 60 from).
        with pytest.raises(KeyError):
            required_ranked_attribute_atom(
                EZREAL,
                get_champion(EZREAL),
                "W",
                "Mana Restored",
                rank,
                modifier_index=0,
            )


# ---------------------------------------------------------------------------
# 2 — rank zero: no W -> no marks, no refunds
# ---------------------------------------------------------------------------


def test_rank_zero_unranked_w_never_arms_or_refunds():
    """At level 1 W is unranked: the module emits no W entry (rank < 1 fails
    closed), the fight casts no W, the ledger has no mark_refunds section and
    no refund gain exists."""
    result = _fight(level=1, cast_order=["W", "Q"])
    assert "W" not in result["breakdown"]
    assert all(c["slot"] != "W" for c in result["cast_timeline"])
    ledger = result["resource_ledger"]
    assert "mark_refunds" not in ledger
    assert _refunds(result) == []
    assert all(
        r["operation"] != "gain"
        for r in ledger["receipts"]
        if r["source"] == REFUND_SOURCE
    )


def test_rank_zero_cast_order_without_w():
    """At level 18 with a W-less rotation the same holds: no marks section,
    no refund gains, and the Q/E spends carry no refund detail."""
    result = _fight(level=18, cast_order=["Q", "E"])
    ledger = result["resource_ledger"]
    assert "mark_refunds" not in ledger
    assert _refunds(result) == []
    assert all("mark_slot" not in r.get("detail", {}) for r in ledger["receipts"])


# ---------------------------------------------------------------------------
# 3 — W damage rank values + rank-flat refund (ranks 1 and max)
# ---------------------------------------------------------------------------
# NOTE for the coordinator: Ezreal's W has FIVE ranks (the atom values array
# is length 5); the brief's "rank 6" is not reachable for W (Jayce-style six
# ranks do not exist here).  Rank 1 and rank 5 (max) are pinned instead.


def test_w_damage_rank_values_and_refund_flat_at_rank_1_and_5():
    """W damage prices at the ranked modifier_0 value (80 at rank 1, 300 at
    rank 5 with zero AP/bonus AD) while the refund flat stays 60.0 at both
    ranks (rank-flat).  The refund amount itself uses the DETONATING
    ability's rank cost: Q rank 3 costs 34 at level 6, Q rank 5 costs 40 at
    level 18, so the refunds are 94 and 100."""
    for level, _rank, w_raw, q_cost, expected_refund in (
        (6, 1, 80.0, Q_COST_R3, 94.0),
        (18, 5, 300.0, Q_COST_R5, 100.0),
    ):
        result = _fight(level=level, cast_order=["W", "Q"])
        assert result["breakdown"]["W"]["total_raw"] == pytest.approx(w_raw)
        refunds = _refunds(result)
        assert len(refunds) == 2
        assert all(r["detail"]["flat"] == pytest.approx(REFUND_FLAT) for r in refunds)
        assert all(r["amount"] == pytest.approx(expected_refund) for r in refunds)
        assert all(
            r["detail"]["detonating_cost"] == pytest.approx(q_cost) for r in refunds
        )
        # The W cost is rank-flat too: every W spend costs 50.
        w_spends = [
            r
            for r in result["resource_ledger"]["receipts"]
            if r["operation"] == "spend" and r["detail"]["slot"] == "W"
        ]
        assert w_spends
        assert all(r["amount"] == pytest.approx(W_COST) for r in w_spends)


# ---------------------------------------------------------------------------
# 4 — ability detonation: refund = 60 + the detonating ability's rank cost
# ---------------------------------------------------------------------------


def test_ability_detonation_amount_receipt_shape_and_stream_order():
    """An accepted ability cast after the W detonates the mark: the refund is
    60 + that ability's ACTUAL paid cost (Q rank 5 = 40 -> 100; E = 70 ->
    130), lands at the detonating cast's timestamp on the restore tier, and
    the receipt stream places it AFTER the detonating spend (cast, hit,
    refund) yet BEFORE any later same-time cast (see the cap/order test)."""
    get_champion(EZREAL)
    for cast_order, det_slot, det_cost, expected, expected_count in (
        (["W", "Q"], "Q", Q_COST_R5, 100.0, 2),
        (["W", "E"], "E", E_COST, 130.0, 1),
    ):
        # The [W, E] chain refunds ONCE: E#2 at 9.833s lands 4.25s after
        # W#2's arm (5.583) — past the 4s mark window (P1-13) — so W#2's
        # mark expires and the second refund never mints.
        result = _fight(level=18, cast_order=cast_order)
        receipts = result["resource_ledger"]["receipts"]
        refunds = _refunds(result)
        assert len(refunds) == expected_count
        for refund in refunds:
            _assert_gain_receipt_shape(refund)
            assert refund["amount"] == pytest.approx(expected)
            assert refund["detail"]["detonating_slot"] == det_slot
            assert refund["detail"]["detonating_cost"] == pytest.approx(det_cost)
        # Refund time == the detonating cast's time (Q#1 at 0.25 for W->Q;
        # the first cast of each slot is staggered by the 0.25 cast time).
        first_other = next(
            c for c in result["cast_timeline"] if c["slot"] != "W" and c["ordinal"] == 1
        )
        assert refunds[0]["time"] == pytest.approx(first_other["time"], abs=1e-6)
        # Stream order: the unique spend at that timestamp precedes the gain.
        spends_at = [
            r
            for r in receipts
            if r["operation"] == "spend" and abs(r["time"] - refunds[0]["time"]) <= _EPS
        ]
        assert len(spends_at) == 1
        assert receipts.index(spends_at[0]) < receipts.index(refunds[0])
        # The refund's pool arithmetic matches the ledger: current_after of
        # the detonating spend + amount (capped at maximum).
        spend = spends_at[0]
        assert refunds[0]["current_before"] == pytest.approx(spend["current_after"])
        assert refunds[0]["current_after"] == pytest.approx(
            min(spend["current_after"] + expected, refunds[0]["maximum_after"])
        )
        # The W entry carries no refund of its own; the gain is the only gain.
        assert all(
            r["operation"] != "gain" or r["source"] == REFUND_SOURCE for r in receipts
        )


# ---------------------------------------------------------------------------
# 5 — basic-attack detonation (option): refund is ability-only
# ---------------------------------------------------------------------------


def test_basic_attack_detonation_never_refunds_and_never_arms():
    """w_mark_detonation="basic_attack" disables the refund ENTIRELY: no
    mark is ever armed, so a later W cannot chain-consume anything and a
    later Q refunds nothing.  Every W cast is receipted with the named
    reason basic_attack_detonation (accepted False, refund 0)."""
    for cast_order in (["W", "Q"], ["W"]):
        result = _fight(
            level=18,
            cast_order=cast_order,
            champion_options={"w_mark_detonation": "basic_attack"},
        )
        assert _refunds(result) == []
        section = result["resource_ledger"]["mark_refunds"]
        assert section["declaration"]["detonation"] == "basic_attack"
        assert section["declaration"]["atoms"] == []
        marks = section["marks"]
        assert marks
        assert all(m["reason"] == "basic_attack_detonation" for m in marks)
        assert all(m["accepted"] is False for m in marks)
        assert all(m["refund_amount"] == 0.0 for m in marks)
        assert all(m["detonating_slot"] is None for m in marks)
        assert all(m["atoms"] == [] for m in marks)
        # The W-chain under basic attack: mark 2 does NOT consume mark 1
        # (no mark is ever pending), so no refund exists anywhere.
        assert not any(
            r["operation"] == "gain" and r["source"] == REFUND_SOURCE
            for r in result["resource_ledger"]["receipts"]
        )


def test_basic_attack_detonation_keeps_w_damage_pricing():
    """The option changes ONLY the refund path: the W damage entry is
    identical under both detonation means (the mark damage is modeled as
    always-triggered; the wiki's basic-attack detonation deals the same
    bonus magic damage)."""
    ability = _fight(level=18, cast_order=["W", "Q"])
    basic = _fight(
        level=18,
        cast_order=["W", "Q"],
        champion_options={"w_mark_detonation": "basic_attack"},
    )
    assert ability["breakdown"]["W"]["total_raw"] == pytest.approx(
        basic["breakdown"]["W"]["total_raw"]
    )
    assert ability["breakdown"]["W"]["total_damage"] == pytest.approx(
        basic["breakdown"]["W"]["total_damage"]
    )
    assert ability["breakdown"]["W"]["casts"] == basic["breakdown"]["W"]["casts"]
    assert ability["breakdown"]["W"]["total_raw"] == pytest.approx(300.0)


# ---------------------------------------------------------------------------
# 6 — W-chain detonation (FIFO; the detonating W's cost is used)
# ---------------------------------------------------------------------------


def test_w_chain_detonation_fifo_and_detonating_cost():
    """A second W cast detonates the FIRST W's mark (the wiki: his next
    ability against the target — every cast is assumed to hit): the refund
    uses the DETONATING W's cost, 60 + 50 = 110, at the second W's
    timestamp.  A pure W chain's casts are 5.583s apart — past the mark's
    4s window (P1-13), so each W expires its predecessor's mark and the
    chain refunds NOTHING; the last mark stays undetonated.  Consume
    happens BEFORE the fresh arm at the same cast, so a W never detonates
    its own freshly armed mark (detonating_ordinal > mark_ordinal always).
    In-window FIFO is pinned by the interleaved W -> Q chain below."""
    result = _fight(level=18, cast_order=["W"])
    marks = result["resource_ledger"]["mark_refunds"]["marks"]
    assert [m["reason"] for m in marks] == [
        "mark_expired",
        "mark_expired",
        "mark_undetonated",
    ]
    assert [m["mark_ordinal"] for m in marks] == [1, 2, 3]
    assert [m["detonating_slot"] for m in marks] == [None, None, None]
    assert [m["detonating_ordinal"] for m in marks] == [None, None, None]
    assert [m["detonating_cost"] for m in marks] == [0.0, 0.0, 0.0]
    assert [m["refund_amount"] for m in marks] == [0.0, 0.0, 0.0]
    assert all(m["refund_time"] is None for m in marks)
    # Each W#(k+1) at 5.583s lands 1.583s past W#k's mark window.
    assert marks[0]["time"] + WINDOW_SECONDS + 1.0 < 5.583333333333333

    refunds = _refunds(result)
    assert refunds == []

    # FIFO across the interleaved chain (W -> Q): the mark consumed at each
    # detonation is the OLDEST pending one — W#1's mark is consumed by Q#1
    # (0.25s later, in-window), W#2's mark (armed later) by Q#3; Q#2 finds
    # nothing pending.  Each refund is priced from the DETONATING cast
    # (Q rank-5 cost -> 100), and the consumed mark is always the last
    # accepted W's.
    interleaved = _fight(level=18, cast_order=["W", "Q"])
    i_marks = interleaved["resource_ledger"]["mark_refunds"]["marks"]
    assert [m["detonating_ordinal"] for m in i_marks] == [1, 3, None]
    assert [
        (r["amount"], r["detail"]["detonating_slot"]) for r in _refunds(interleaved)
    ] == [(100.0, "Q"), (100.0, "Q")]


# ---------------------------------------------------------------------------
# 7 — missing mark: an ability cast with no pending mark refunds nothing
# ---------------------------------------------------------------------------


def test_missing_mark_no_refund():
    """Q-only: no mark was ever armed, so no Q cast refunds anything and the
    ledger has no mark_refunds section.  W-Q-Q: Q#1 detonates W#1's mark;
    Q#2 and Q#4 find no pending mark and produce NO gain — only marks that
    exist refund."""
    q_only = _fight(level=18, cast_order=["Q"])
    assert "mark_refunds" not in q_only["resource_ledger"]
    assert _refunds(q_only) == []

    result = _fight(level=18, cast_order=["W", "Q", "Q"])
    marks = result["resource_ledger"]["mark_refunds"]["marks"]
    assert [m["reason"] for m in marks] == ["applied", "applied", "mark_undetonated"]
    assert [m["detonating_ordinal"] for m in marks] == [1, 3, None]
    refunds = _refunds(result)
    assert [(r["time"], r["amount"]) for r in refunds] == [
        (pytest.approx(0.25, abs=1e-6), pytest.approx(100.0)),
        (pytest.approx(6.75, abs=1e-6), pytest.approx(100.0)),
    ]
    # Q#2 (3.5s) and Q#4 (10.0s) carry no refund at their timestamps.
    assert not any(abs(r["time"] - 3.5) <= _EPS for r in refunds)
    assert not any(abs(r["time"] - 10.0) <= _EPS for r in refunds)
    # Every refund maps to an applied mark and vice versa (one per mark).
    assert len(refunds) == sum(1 for m in marks if m["reason"] == "applied")


# ---------------------------------------------------------------------------
# 8 — wrong target / target assumptions: every cast is assumed to hit
# ---------------------------------------------------------------------------


def test_target_assumptions_every_cast_hits():
    """The mark attaches to 'the first enemy champion, epic monster, or
    structure hit' in the wiki, but the model assumes ONE target and every
    cast hitting it: the refund stream is byte-identical across wildly
    different target health/armor/MR, and the option surface exposes no
    miss/target-choice input (the module's ASSUMPTIONS state the boundary)."""
    baseline = _fight(level=18, cast_order=["W", "Q"])
    baseline_refunds = [(r["time"], r["amount"]) for r in _refunds(baseline)]
    assert baseline_refunds

    for target_health, target_armor, target_mr in (
        (10_000.0, 300.0, 200.0),
        (100.0, 0.0, 0.0),
    ):
        result = _fight(
            level=18,
            cast_order=["W", "Q"],
            target_health=target_health,
            target_armor=target_armor,
            target_magic_resistance=target_mr,
        )
        assert [(r["time"], r["amount"]) for r in _refunds(result)] == (
            baseline_refunds
        )

    # No input exists to model a missed W or a target switch.
    options = {o["key"] for o in get_champion_options_meta(EZREAL)["options"]}
    assert "w_miss" not in options
    assert "w_target" not in options
    assert options == {"w_mark_detonation", "passive_stacks"}
    assumptions = get_champion_options_meta(EZREAL)["assumptions"]
    assert any("every cast is assumed to hit" in a for a in assumptions)
    assert any("4s mark window" in a and "not modeled" in a for a in assumptions)


# ---------------------------------------------------------------------------
# 9 — one refund per mark: FIFO consumption, exactly once
# ---------------------------------------------------------------------------


def test_one_refund_per_mark_fifo_consumption():
    """Applied marks and refund gains are in exact 1:1 correspondence: each
    applied mark's (mark_slot, mark_ordinal) appears in exactly one gain
    receipt's detail, each gain's detail names an applied mark, and the
    amounts agree (flat + detonating_cost).  A mark never refunds twice."""
    result = _fight(level=18, cast_order=["W", "Q"], duration=12.0)
    marks = result["resource_ledger"]["mark_refunds"]["marks"]
    refunds = _refunds(result)
    applied = [m for m in marks if m["reason"] == "applied"]
    assert applied
    assert len(applied) == len(refunds)

    seen: set[tuple[str, int]] = set()
    for refund in refunds:
        key = (refund["detail"]["mark_slot"], refund["detail"]["mark_ordinal"])
        assert key not in seen, f"mark {key} refunded more than once"
        seen.add(key)
        match = [
            m for m in marks if m["mark_slot"] == key[0] and m["mark_ordinal"] == key[1]
        ]
        assert len(match) == 1
        assert match[0]["reason"] == "applied"
        assert refund["amount"] == pytest.approx(match[0]["refund_amount"])
        assert refund["amount"] == pytest.approx(
            REFUND_FLAT + refund["detail"]["detonating_cost"]
        )
        assert refund["detail"]["detonating_slot"] == match[0]["detonating_slot"]
        assert refund["detail"]["detonating_ordinal"] == match[0]["detonating_ordinal"]
        assert refund["time"] == pytest.approx(match[0]["refund_time"], abs=1e-6)
        # FIFO: the consumed mark was armed by a strictly EARLIER accepted
        # cast than the detonating one (per-slot ordinals are not comparable
        # across slots; cast times are).
        mark_time = match[0]["time"]
        detonator = next(
            c
            for c in result["cast_timeline"]
            if c["slot"] == match[0]["detonating_slot"]
            and c["ordinal"] == match[0]["detonating_ordinal"]
        )
        assert mark_time < detonator["time"] - _EPS
    assert seen == {(m["mark_slot"], m["mark_ordinal"]) for m in applied}


# ---------------------------------------------------------------------------
# 10 — insufficient mana / denied casts
# ---------------------------------------------------------------------------


def test_denied_cast_never_detonates_or_arms():
    """A denied cast (insufficient_resource) never consumes the pending mark
    and never arms one: the FIFO mark persists past every denied cast and is
    detonated by the first ACCEPTED ability cast after it.  No refund gain
    ever lands at a denied timestamp."""
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
    result = _direct_fight(stats, duration=6.0, cast_order=["W", "Q", "E", "R"])
    receipts = result["resource_ledger"]["receipts"]
    refunds = _refunds(result)
    denied = [r for r in receipts if not r["accepted"]]
    assert [r["time"] for r in denied] == [0.25, 0.5, 0.75]
    assert all(r["reason"] == "insufficient_resource" for r in denied)
    assert all(r["operation"] == "spend" for r in denied)

    # Exactly one refund, at the first accepted cast after the W (Q#2, 3.5s),
    # with the full receipt shape; its amount is 60 + the paid Q cost (40).
    assert [(r["time"], r["amount"]) for r in refunds] == [
        (pytest.approx(3.5, abs=1e-6), pytest.approx(100.0))
    ]
    _assert_gain_receipt_shape(refunds[0])
    assert refunds[0]["detail"]["detonating_slot"] == "Q"
    assert refunds[0]["detail"]["detonating_ordinal"] == 2
    assert refunds[0]["detail"]["detonating_cost"] == pytest.approx(40.0)
    denied_times = {r["time"] for r in denied}
    assert not any(abs(r["time"] - t) <= _EPS for r in refunds for t in denied_times)

    marks = result["resource_ledger"]["mark_refunds"]["marks"]
    assert [m["reason"] for m in marks] == ["applied", "mark_undetonated"]
    assert marks[0]["detonating_slot"] == "Q"
    assert marks[0]["detonating_ordinal"] == 2
    assert marks[1]["accepted"] is False
    # The denied cast never arms: no mark row exists at a denied timestamp.
    assert all(m["time"] not in denied_times for m in marks)
    # The refund rides the SAME account as admission: it enables nothing
    # before its own timestamp, and the ledger accounting identity holds.
    ledger = result["resource_ledger"]
    current_delta = sum(
        r["current_after"] - r["current_before"] for r in receipts if r["accepted"]
    )
    assert ledger["closing_current"] == pytest.approx(
        ledger["opening_current"] + current_delta, abs=1e-6
    )


# ---------------------------------------------------------------------------
# 11 — cap and ordering: the refund lands AFTER the detonating spend
# ---------------------------------------------------------------------------
# The brief asked "the refund lands BEFORE the spend?" — NO.  In-game
# sequence is cast, hit, refund: the walk emits the detonating spend, then
# the refund gain, at the same timestamp.  Because the refund (60 + cost)
# always exceeds the spend pair (W's 50 + that cost) by 10, a refund against
# an opening-full pool is ALWAYS receipted CAPPED; the restore tier only
# orders it before a SIMULTANEOUS LATER cast's spend, which sees the refund.


def test_capped_refund_and_tier_ordering():
    """One-rotation W-Q-E (all at t=0): W spends, Q spends, the Q detonation
    refunds 100 which overshoots the full pool -> receipted CAPPED with
    current pinned at maximum; the refund (restore tier 0) then precedes the
    simultaneous E spend (cast tier 1), whose current_before is the restored
    pool.  Stream order: W < Q < refund < E."""
    result = _fight(
        level=18,
        cast_order=["W", "Q", "E"],
        one_rotation=True,
    )
    receipts = result["resource_ledger"]["receipts"]
    refunds = _refunds(result)
    assert len(refunds) == 1  # W#1's mark only; E detonates nothing
    refund = refunds[0]
    _assert_gain_receipt_shape(refund)
    assert refund["amount"] == pytest.approx(100.0)
    assert refund["reason"] == "CAPPED"
    assert refund["current_after"] == pytest.approx(refund["maximum_after"])
    assert refund["current_before"] < refund["maximum_after"]
    assert refund["tier"] == 0.0

    spends = [r for r in receipts if r["operation"] == "spend"]
    assert [r["tier"] for r in spends] == [1.0, 1.0, 1.0]
    by_slot = {r["detail"]["slot"]: r for r in spends}
    # After the detonating spend (in-game: cast, hit, refund)...
    assert receipts.index(by_slot["W"]) < receipts.index(by_slot["Q"])
    assert receipts.index(by_slot["Q"]) < receipts.index(refund)
    # ...but before the simultaneous LATER cast, which sees the restored pool.
    assert receipts.index(refund) < receipts.index(by_slot["E"])
    assert by_slot["E"]["current_before"] == pytest.approx(refund["current_after"])
    # The refund can therefore never enable the detonating cast itself.
    assert by_slot["Q"]["current_before"] == pytest.approx(
        by_slot["W"]["current_after"]
    )


def test_long_fight_refunds_interleave_capped_and_accepted():
    """Over a long fight the pool drains below maximum, so refunds switch
    between CAPPED and accepted on the same receipt surface; both reasons
    are pinned with their exact timestamps (40s W-Q rotation).  The first
    refund of a fresh full pool is always CAPPED (refund > preceding spend
    pair)."""
    result = _fight(level=18, cast_order=["W", "Q"], duration=40.0)
    refunds = _refunds(result)
    reasons = [r["reason"] for r in refunds]
    assert reasons == [
        "CAPPED",
        "accepted",
        "accepted",
        "accepted",
        "CAPPED",
        "accepted",
        "accepted",
        "CAPPED",
    ]
    assert [round(r["time"], 3) for r in refunds] == [
        0.25,
        6.75,
        13.25,
        19.75,
        23.0,
        29.5,
        36.0,
        39.333,
    ]
    assert all(r["amount"] == pytest.approx(100.0) for r in refunds)
    for refund in refunds:
        _assert_gain_receipt_shape(refund)
        assert refund["current_after"] <= refund["maximum_after"] + 1e-9
        if refund["reason"] == "CAPPED":
            assert refund["current_after"] == pytest.approx(refund["maximum_after"])


# ---------------------------------------------------------------------------
# 12 — the 4s mark window: expiry is NOT modeled
# ---------------------------------------------------------------------------


def test_mark_window_expiry_enforced():
    """The wiki mark lasts 4 seconds (the binary DetonationTimeout 4.0; the
    atom timing.active_duration b32849b968950b8e).  P1-13 enforces the
    window: a mark armed at t=0 and 'detonated' by W#2 at 5.583s — 1.583s
    past the window — is receipted ``mark_expired`` and refunds NOTHING
    (the in-game mark expired before the hit)."""
    result = _fight(level=18, cast_order=["W"])
    marks = result["resource_ledger"]["mark_refunds"]["marks"]
    assert marks[0]["reason"] == "mark_expired"
    assert marks[0]["time"] == pytest.approx(0.0)
    assert marks[0]["refund_time"] is None
    assert marks[0]["refund_amount"] == pytest.approx(0.0)
    assert marks[0]["accepted"] is False
    assert marks[0]["detonating_slot"] is None
    assert marks[0]["detonating_cost"] == pytest.approx(0.0)
    assert _refunds(result) == []
    # The 4s value itself is sourced (atom + prose): see
    # test_source_evidence_no_refund_atom_and_w_atom_hashes.


def test_mark_expired_at_fight_end_receipted_not_guessed():
    """A mark still pending at the fight end whose window elapsed before the
    end is ``mark_expired`` (not ``mark_undetonated``): a single W at t=0
    in a 5s fight with no detonator — the 4s window ends at 4s < 5s.  A
    short fight (window outlives it) keeps the undetonated reason."""
    result = _fight(level=18, cast_order=["W"], duration=5.0)
    marks = result["resource_ledger"]["mark_refunds"]["marks"]
    assert [m["reason"] for m in marks] == ["mark_expired"]
    assert _refunds(result) == []
    result = _fight(level=18, cast_order=["W"], duration=2.0)
    marks = result["resource_ledger"]["mark_refunds"]["marks"]
    assert [m["reason"] for m in marks] == ["mark_undetonated"]


def test_spell_shield_denial_is_not_modeled_the_option_is_silently_ignored():
    """Documented boundary (module ASSUMPTIONS): the wiki notes 'Spell
    shield prevents the mark from being triggered by an ability', but no
    input exists to express a spell-shielded target.  Today's actual
    fail-closed behavior is NOT a denial — ``target_spell_shield`` is an
    unrecognized champion_options key, so ``ctx.options.get(...)`` never
    reads it and the fight proceeds exactly as if the key were absent: the
    refund stream is byte-identical with and without the (inert) flag.
    This pins the real current receipt rather than the mechanic the
    coordinator would need to add (a genuine denial path, which does not
    exist)."""
    baseline = _fight(level=18, cast_order=["W", "Q"])
    with_flag = _fight(
        level=18,
        cast_order=["W", "Q"],
        champion_options={"w_mark_detonation": "ability", "target_spell_shield": True},
    )
    baseline_refunds = [(r["time"], r["amount"]) for r in _refunds(baseline)]
    flagged_refunds = [(r["time"], r["amount"]) for r in _refunds(with_flag)]
    assert baseline_refunds  # the refund stream is non-empty (no denial)
    assert flagged_refunds == baseline_refunds
    assert (
        baseline["resource_ledger"]["receipts"]
        == with_flag["resource_ledger"]["receipts"]
    )
    # No input exists to model a spell-shield denial today.
    options = {o["key"] for o in get_champion_options_meta(EZREAL)["options"]}
    assert "target_spell_shield" not in options
    assert options == {"w_mark_detonation", "passive_stacks"}


def test_multi_target_mark_attribution_is_not_modeled():
    """Documented boundary: the mark hits 'the first enemy champion, epic
    monster, or structure' — a per-target mark state the 1v1 model cannot
    express.  The fight prices ONE target; the only multi-target knob the
    engine exposes (``roster_target_index`` / ``roster_target_count``,
    used to split a single ability's shared AoE charges across a roster)
    has NO effect on which mark gets consumed or refunded — the refund
    stream stays byte-identical no matter which roster slot/count is
    supplied, proving no per-target mark surface exists to attribute a
    second target's marks to."""
    baseline = _fight(level=18, cast_order=["W", "Q"])
    baseline_refunds = [(r["time"], r["amount"]) for r in _refunds(baseline)]
    assert baseline_refunds
    for roster_target_index, roster_target_count in (
        (1, 2),
        (0, 3),
        (2, 3),
    ):
        result = _fight(
            level=18,
            cast_order=["W", "Q"],
            roster_target_index=roster_target_index,
            roster_target_count=roster_target_count,
        )
        result_refunds = [(r["time"], r["amount"]) for r in _refunds(result)]
        assert result_refunds == baseline_refunds, (
            roster_target_index,
            roster_target_count,
        )


# ---------------------------------------------------------------------------
# 13 — atom receipts: refund atom-free + W damage atoms
# ---------------------------------------------------------------------------


def test_refund_atom_free_and_w_damage_atom_priced():
    """The refund's flat is a typed rule declaration, NOT an atom: gain
    receipts, mark rows, and the public declaration all carry atoms == [].
    The W damage is priced from the ranked atom values (modifier_0 = 80 /
    300 at ranks 1 / 5 with no AP and no bonus AD)."""
    result = _fight(level=18, cast_order=["W", "Q"])
    refunds = _refunds(result)
    assert refunds
    assert all(r["atoms"] == [] for r in refunds)
    marks = result["resource_ledger"]["mark_refunds"]["marks"]
    assert all(m["atoms"] == [] for m in marks)
    assert result["resource_ledger"]["mark_refunds"]["declaration"]["atoms"] == []

    # Ranked W damage values through the typed atom accessor.
    for rank, expected in ((1, 80.0), (5, 300.0)):
        value, atom = required_ranked_attribute_atom(
            EZREAL,
            get_champion(EZREAL),
            "W",
            "Bonus Magic Damage",
            rank,
            modifier_index=0,
        )
        assert value == expected
        assert atom["hash"] == W_DAMAGE_ATOMS[0][1]
    # Bonus-AD and AP ratio rows are the other two damage atoms.
    for modifier in (1, 2):
        _, atom = required_ranked_attribute_atom(
            EZREAL,
            get_champion(EZREAL),
            "W",
            "Bonus Magic Damage",
            1,
            modifier_index=modifier,
        )
        assert atom["hash"] == W_DAMAGE_ATOMS[modifier][1]
    # The fight prices exactly the ranked flat (0 AP / 0 bonus AD).
    assert result["breakdown"]["W"]["total_raw"] == pytest.approx(300.0)


# ---------------------------------------------------------------------------
# 14 — score parity: full vs score_only on the refund surface
# ---------------------------------------------------------------------------


def test_score_parity_full_vs_score_only_refund_surface():
    """score_only must not change cast acceptance, resource totals, the
    ledger receipt stream (refunds included), or the mark_refunds section."""
    for cast_order in (["W", "Q"], ["W"]):
        kwargs = {"level": 18, "cast_order": cast_order}
        full = _fight(**kwargs)
        score = _fight(**kwargs, score_only=True)
        assert full["resource_spent"] == pytest.approx(score["resource_spent"])
        assert full["resource_remaining"] == pytest.approx(score["resource_remaining"])
        assert (
            full["resource_ledger"]["receipts"] == score["resource_ledger"]["receipts"]
        )
        assert (
            full["resource_ledger"]["mark_refunds"]
            == score["resource_ledger"]["mark_refunds"]
        )
        assert _refunds(full) == _refunds(score)
        # score_only truncates the per-cast resource_before/after columns;
        # the score surface (time/slot/ordinal/cost) and the full ledger
        # receipt stream (the refunds) must match byte-for-byte.
        full_rows = [
            (c["time"], c["slot"], c["ordinal"], c["resource_cost"])
            for c in full["cast_timeline"]
        ]
        score_rows = [
            (c["time"], c["slot"], c["ordinal"], c["resource_cost"])
            for c in score["cast_timeline"]
        ]
        assert full_rows == score_rows
        # The refund surface is live in score mode for the in-window chain;
        # the pure W chain refunds nothing under the 4s window (P1-13), so
        # its parity is the empty-stream equality above.
        if cast_order == ["W", "Q"]:
            assert _refunds(score), "the refund surface must be live in score mode"


def test_multi_declaration_fails_closed():
    """P1-13 (R2): more than one slot declaring mark_refund raises — the
    resource walk supports one authored mark-refund rule per fight
    (mirrors the auto-restore declaration's multi-declaration raise)."""
    from src.calculator.champions import parse_champion_abilities
    from src.calculator.damage import FightConfig, calculate_fight_damage

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
        "attack_speed": 1.0,
        "attack_speed_ratio": 0.625,
        "bonus_attack_speed": 0.0,
        "max_mana": 400.0,
        "resource_regen_per_second": 8.0,
    }
    abilities = parse_champion_abilities(
        get_champion(EZREAL),
        18,
        0.0,
        champion_options={},
        champion_stats=dict(stats),
        target_stats={"target_max_health": 2000.0},
    )
    # Author a second declaration on the Q slot (W's is real).
    abilities["Q"]["mark_refund"] = dict(abilities["W"]["mark_refund"])
    with pytest.raises(ValueError, match="multiple mark_refund declarations"):
        calculate_fight_damage(
            stats,
            abilities,
            [],
            FightConfig(
                target_health=2000,
                target_armor=50,
                target_magic_resistance=40,
                fight_duration_seconds=6.0,
                auto_attack_uptime=0.0,
                auto_attack_uptime_mode="explicit",
                one_rotation=False,
                deterministic=True,
                enforce_resource_limits=True,
            ),
        )
    # A malformed declaration on a NON-declaring slot still raises the
    # authoring error (validated before the uniqueness guard).
    del abilities["Q"]["mark_refund"]
    abilities["Q"]["mark_refund"] = {"flat": -1.0, "source": "x", "atoms": ()}
    with pytest.raises(ValueError, match=re.escape("mark_refund.flat")):
        calculate_fight_damage(
            stats,
            abilities,
            [],
            FightConfig(
                target_health=2000,
                target_armor=50,
                target_magic_resistance=40,
                fight_duration_seconds=6.0,
                auto_attack_uptime=0.0,
                auto_attack_uptime_mode="explicit",
                one_rotation=False,
                deterministic=True,
                enforce_resource_limits=True,
            ),
        )


# ---------------------------------------------------------------------------
# 15 — public ledger rows: refund receipt + mark row shapes
# ---------------------------------------------------------------------------


def test_public_ledger_row_shapes():
    """The public mark_refunds section: the declaration (flat, source, atoms,
    detonation) and one mark row per W cast with the exact applied /
    undetonated / basic-attack receipt fields.  Cast_timeline rows stay
    projections of ledger spend receipts; the per-cast resource_restored
    field stays 0.0 (the refund rides its own receipt — no duplicate state)."""
    result = _fight(level=18, cast_order=["W", "Q"])
    section = result["resource_ledger"]["mark_refunds"]
    assert set(section) == {"declaration", "marks"}
    declaration = section["declaration"]
    assert set(declaration) == {
        "flat",
        "window_seconds",
        "source",
        "atoms",
        "detonation",
    }
    assert declaration["flat"] == REFUND_FLAT
    assert declaration["window_seconds"] == WINDOW_SECONDS
    assert declaration["source"] == REFUND_SOURCE
    assert declaration["atoms"] == []
    assert declaration["detonation"] == "ability"

    marks = section["marks"]
    assert len(marks) == 3
    applied = marks[0]
    assert set(applied) == {
        "time",
        "source",
        "flat",
        "window_seconds",
        "atoms",
        "accepted",
        "reason",
        "mark_slot",
        "mark_ordinal",
        "detonating_slot",
        "detonating_ordinal",
        "detonating_cost",
        "refund_amount",
        "refund_time",
    }
    assert applied["time"] == pytest.approx(0.0)
    assert applied["source"] == REFUND_SOURCE
    assert applied["flat"] == REFUND_FLAT
    assert applied["accepted"] is True
    assert applied["reason"] == "applied"
    assert applied["mark_slot"] == "W"
    assert applied["mark_ordinal"] == 1
    assert applied["detonating_slot"] == "Q"
    assert applied["detonating_ordinal"] == 1
    assert applied["detonating_cost"] == pytest.approx(40.0)
    assert applied["refund_amount"] == pytest.approx(100.0)
    assert applied["refund_time"] == pytest.approx(0.25, abs=1e-6)

    undetonated = marks[-1]
    assert undetonated["reason"] == "mark_undetonated"
    assert undetonated["accepted"] is False
    assert undetonated["detonating_slot"] is None
    assert undetonated["refund_amount"] == 0.0
    assert undetonated["refund_time"] is None

    # cast_timeline rows agree with the spend receipts; no per-cast restore.
    spends = {
        (r["detail"]["slot"], r["detail"]["ordinal"]): r
        for r in result["resource_ledger"]["receipts"]
        if r["operation"] == "spend"
    }
    for cast in result["cast_timeline"]:
        receipt = spends[(cast["slot"], cast["ordinal"])]
        assert cast["resource_before"] == pytest.approx(receipt["current_before"])
        assert cast["resource_after"] == pytest.approx(receipt["current_after"])
        assert cast["resource_restored"] == 0.0


# ---------------------------------------------------------------------------
# 16 — unchanged boundaries: Q refund, W damage pricing, E/R, other champions
# ---------------------------------------------------------------------------


def test_unchanged_boundaries_q_refund_w_pricing_er_and_other_champions():
    """The mark-refund seam changes nothing else: the Q cooldown refund
    stream still prices Q at hasted CD - 1.5s (3.0 at level 18, 3.5 at level
    6) and divides W/E/R cooldowns by the same rate factor (5.333 / 9.333 /
    60 at level 18); E and R carry no mark_refund key; W damage pricing is
    the ranked atom value; and ordinary mana champions keep their receipt
    shape (Garen has no ledger at all)."""
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
        "max_mana": 1565.0,
        "resource_regen_per_second": 8.5,
    }
    target = {"target_max_health": 2000.0}
    for level, q_cd, w_cd, e_cd, r_cd in (
        # Level 6: Q rank 3 (base 5.0), W rank 1 (8.0), E rank 1 (26.0),
        # R rank 1 (120.0); rate factor 1 + 1.5 / 3.5 = 10/7.
        (6, 3.5, 5.6, 18.2, 84.0),
        # Level 18: Q rank 5 (4.5), W rank 5 (8.0), E rank 5 (14.0),
        # R rank 3 (90.0); rate factor 1.5.
        (18, 3.0, 5.333333333333333, 9.333333333333334, 60.0),
    ):
        entries = parse_champion_abilities(
            get_champion(EZREAL),
            level,
            0.0,
            champion_options={},
            champion_stats=dict(stats),
            target_stats=target,
        )
        assert entries["Q"]["cooldown"] == pytest.approx(q_cd)
        assert entries["W"]["cooldown"] == pytest.approx(w_cd)
        assert entries["E"]["cooldown"] == pytest.approx(e_cd)
        assert entries["R"]["cooldown"] == pytest.approx(r_cd)
        assert "mark_refund" not in entries["E"]
        assert "mark_refund" not in entries["R"]
        assert "mark_refund" in entries["W"]

    # W damage pricing is identical with the refund active vs disabled.
    ability = _fight(level=18, cast_order=["W", "Q"])
    basic = _fight(
        level=18,
        cast_order=["W", "Q"],
        champion_options={"w_mark_detonation": "basic_attack"},
    )
    for slot in ("W", "Q"):
        assert ability["breakdown"][slot]["total_raw"] == pytest.approx(
            basic["breakdown"][slot]["total_raw"]
        )

    # Other champions: Garen (manaless) has no ledger; Ahri keeps the plain
    # spend/regen receipt surface with no gains.
    garen = run_fight(get_champion("Garen"), 18, [], _params(duration=6.0))
    assert garen["resource_ledger"] is None
    ahri = run_fight(get_champion("Ahri"), 18, [], _params(duration=6.0))
    ahri_ops = {r["operation"] for r in ahri["resource_ledger"]["receipts"]}
    assert ahri_ops <= {"spend", "regen"}
    assert not [
        r
        for r in ahri["resource_ledger"]["receipts"]
        if r["operation"] == "gain" and r["source"] == REFUND_SOURCE
    ]


# ---------------------------------------------------------------------------
# 17 — existing regression surface (run set, see the module docstring of the
# companion matrix tests): test_mana_restore_refund.py M4/M5/M10,
# test_resource_ledger_champion_consumers.py, test_jayce_w_mana_restore.py
# and test_jayce.py must all stay green — executed separately with pytest.
# ---------------------------------------------------------------------------
