"""P3 Package 3D — Bastionbreaker Shaped Charge packet certification.

This file is the focused test-matrix owner for Bastionbreaker's Shaped
Charge (``shaped_charge_Bastionbreaker``) packet contract.  It pins the
OBSERVABLES the coordinator's P3-3D completion must satisfy, and each test
runs against today's source: every behavior that already exists must pass
now; every assertion that targets a receipt the source does not emit yet
is marked ``# P3-3D contract`` and ``xfail`` with reason
``awaiting P3-3D ...``.

Scope note: ``tests/test_bastionbreaker_timeline.py`` owns the
engine-precision receipts (``_shaped_charge_proc_times``) this matrix
builds on; ``TestBastionbreakerShapedCharge`` in
``tests/test_item_damage.py`` owns the raw-formula pins; this file is
disjoint and pins only the acceptance observables below.

Contract under test (typed source-backed values: base 50/25 melee/ranged,
1.5/0.75 lethality ratio melee/ranged, 20s cooldown, TRUE damage):

* TYPED ACCESSORS: ``required_effect_value("Bastionbreaker", ...)``
  returns the sourced values; a missing key raises ``KeyError`` naming
  Bastionbreaker and the key (AGENTS.md rule 5: no silent stale
  fallbacks).  The compiled effect emits the ``shaped_charge_*`` row with
  ``damage_per_proc = base + ratio * lethality`` (melee and ranged) and
  ``damage_type "true"``.
* ABILITY-ONLY TRIGGER ELIGIBILITY: only DAMAGING ability casts trigger
  (non-damaging/stat abilities are skipped, basic attacks never trigger,
  item procs never trigger); one proc per damaging ability cast
  (next-instance semantics: the FIRST damaging cast after the cooldown
  consumes the charge).
* AUTHORED HIT TIMING: exact ability hit packets are preferred
  (``event_precision`` ``"hit"``/``"exact"``) over the cast boundary; a
  per-slot cursor prevents one authored packet being reused across
  repeated casts.
* COOLDOWN BOUNDARY: proc at t=0; the next damaging cast at t=19.9 is
  denied; exactly t=20 is allowed (inclusive); repeated casts after 20s
  each proc (deterministic count/times).
* TRUE-DAMAGE RECEIPTS: ``damage_events`` carry ``damage_type "true"``
  and the row is not mitigated (target armor/MR 0 vs high: identical
  damage).
* NO DUPLICATE PROCS: exactly one proc per damaging ability cast, one
  damage event per proc.
* NAMED COARSE FALLBACK / MALFORMED-LEDGER WITHHOLDING: a cast-boundary
  event carries ``event_precision "cast_boundary"`` when no authored hit
  exists; malformed cast receipts (non-finite time, missing slot, ...)
  yield NO row today and therefore no ``shaped_charge_Bastionbreaker``
  coverage source (pinned current observable).  The NAMED withheld
  receipt (row kept with ``withheld_reason`` per the Eclipse-3C
  precedent) is the P3-3D target and is xfailed below.
* SCORE/RECEIPT/PUBLIC PARITY: score-only and receipt fights produce the
  identical ``shaped_charge_Bastionbreaker`` row (count,
  damage_per_proc, damage_events, total_damage);
  ``shaped_charge_Bastionbreaker`` is in
  ``EXPLICIT_APPLICABILITY_EXCLUSION_SOURCES`` with the pure-source
  exclusion receipt (no mixed rescue).
* TARGET/INSTANCE BEHAVIOR: the engine is champion-only 1v1 — target
  separation is not applicable (no per-target fields on the row/events),
  and instance separation is per damaging cast.
* DETERMINISM: identical fights produce identical rows; no duplicate
  events.

Asserted constants (50.0/25.0/1.5/0.75/20.0) are the typed accessors'
expected values; per AGENTS.md rule 5 the source must read them from
``required_effect_value`` / the parser-owned registry, and this file pins
the fail-loud behavior for a missing key.
"""

import json
from types import SimpleNamespace

import pytest

from src.calculator.ability_spec import DamagePart
from src.calculator.damage import (
    FightConfig,
    RotationResult,
    _shaped_charge_proc_receipts,
    calculate_fight_damage,
)
from src.calculator.data_fetcher import get_item_by_name
from src.calculator.interpreters import charged_strike
from src.calculator.item_behavior import FightFacts
from src.calculator.item_effects import (
    DamageInputs,
    required_effect_value,
)
from src.calculator.timeline_coverage import (
    EXPLICIT_APPLICABILITY_EXCLUSION_SOURCES,
    applicability_exclusion_sources,
)

BASTION = "Bastionbreaker"
SC_ROW = "shaped_charge_Bastionbreaker"


def _shaped_charge():
    """The shaped charge Bastionbreaker declares.

    MERGE: the strike families left ``BuildDamageEffects`` -- a projection
    field that defaulted to an empty tuple would price a whole family at
    zero with nothing saying so -- so they resolve through their own
    interpreter instead.
    """
    return charged_strike.resolve_slots(
        (BASTION,),
        facts=FightFacts(
            level=18,
            fight_duration_seconds=5.0,
            target_bonus_health=0.0,
            holder_is_melee=True,
        ),
    ).shaped_charges[0]


def _stats(*, is_melee: bool = False, lethality: float = 22.0) -> dict:
    return {
        "ability_haste": 0.0,
        "armor_penetration_bonus_percent": 0.0,
        "basic_ability_haste": 0.0,
        "bonus_attack_damage": 0.0,
        "bonus_health": 0.0,
        "bonus_mana": 0.0,
        "health": 0.0,
        "max_mana": 0.0,
        "move_speed": 0.0,
        "omnivamp_percent": 0.0,
        "resource_regen_per_second": 0.0,
        "ultimate_haste": 0.0,
        "attack_damage": 100.0,
        "ability_power": 0.0,
        "base_attack_damage": 100.0,
        "attack_speed": 1.0,
        "attack_speed_ratio": 0.625,
        "magic_penetration_flat": 0.0,
        "magic_penetration_percent": 0.0,
        "armor_penetration_percent": 0.0,
        "flat_armor_penetration": 0.0,
        "critical_strike_chance": 0.0,
        "is_melee": is_melee,
        "level": 18,
        "lethality": lethality,
    }


def _ability(
    name: str,
    cooldown: float = 5.0,
    time_offset: float | None = None,
    amount: float = 100.0,
    **extra,
) -> dict:
    return {
        "name": name,
        "rank": 1,
        "cooldown": cooldown,
        "physical_damage": amount,
        "parts": (DamagePart("physical", amount, time_offset=time_offset),),
        "total_raw": amount,
        "damage_type": "physical",
        **extra,
    }


def _fight(
    stats: dict,
    abilities: dict,
    *,
    duration: float,
    score_only: bool = False,
    items: list[dict] | None = None,
    **kwargs,
) -> dict:
    kwargs.setdefault("auto_attack_uptime", 0.0)
    target_armor = float(kwargs.pop("target_armor", 0.0))
    target_magic_resistance = float(kwargs.pop("target_magic_resistance", 0.0))
    return calculate_fight_damage(
        stats,
        abilities,
        items if items is not None else [{"name": BASTION}],
        FightConfig(
            target_health=2000.0,
            target_armor=target_armor,
            target_magic_resistance=target_magic_resistance,
            fight_duration_seconds=duration,
            **kwargs,
        ),
        score_only=score_only,
    )


def _sc_row(result: dict) -> dict:
    return result["breakdown"][SC_ROW]


def _receipt_state(*, damage_events=None, ability_parts=None, cast_order=None):
    """A unit-level FightState stand-in for ``_shaped_charge_proc_receipts``.

    Matches the SimpleNamespace states ``tests/test_bastionbreaker_timeline.py``
    feeds ``_shaped_charge_proc_times``; a ``None`` ``cast_order`` is exactly
    the "no authored hit exists" condition that falls back to
    ``cast_boundary`` precision.
    """
    breakdown = {}
    if damage_events is not None:
        breakdown["Q"] = {"damage_events": damage_events}
    state = SimpleNamespace(
        ability_damages={
            "Q": {"parts": ability_parts or (DamagePart("physical", 100.0),)}
        },
        breakdown=breakdown,
    )
    state.cast_order = cast_order
    return state


# ---------------------------------------------------------------------------
# 1. Typed / source-backed contract
# ---------------------------------------------------------------------------


class TestTypedContract:
    def test_cached_item_name_resolves(self) -> None:
        item = get_item_by_name(BASTION)
        assert item.get("name") == BASTION
        assert any(
            passive.get("name") == "Shaped Charge"
            for passive in item.get("passives", [])
        )

    def test_typed_accessor_values_match_expected_constants(self) -> None:
        assert required_effect_value(BASTION, "base_melee") == 50.0
        assert required_effect_value(BASTION, "base_ranged") == 25.0
        assert required_effect_value(BASTION, "lethality_ratio_melee") == 1.5
        assert required_effect_value(BASTION, "lethality_ratio_ranged") == 0.75
        assert required_effect_value(BASTION, "cooldown") == 20.0

    def test_missing_typed_key_fails_loud_naming_item_and_key(self) -> None:
        with pytest.raises(KeyError, match=r"Bastionbreaker.*shaped_missing_key_3d"):
            required_effect_value(BASTION, "shaped_missing_key_3d")

    def test_compiled_effect_contract(self) -> None:
        effect = _shaped_charge()
        assert effect.source.item_name == BASTION
        assert effect.source.breakdown_key == SC_ROW
        assert effect.source.display_name == "Bastionbreaker (Shaped Charge)"
        assert effect.source.damage_type == "true"
        assert effect.cooldown == 20.0

    def test_compiled_formula_melee_and_ranged(self) -> None:
        effect = _shaped_charge()
        melee = DamageInputs(_stats(is_melee=True), 18, True, 1000.0, 1000.0)
        ranged = DamageInputs(_stats(is_melee=False), 18, False, 1000.0, 1000.0)
        # 50 + 1.5 * 22 = 83 ; 25 + 0.75 * 22 = 41.5
        assert effect.source.raw_damage(melee) == pytest.approx(83.0)
        assert effect.source.raw_damage(ranged) == pytest.approx(41.5)

    def test_compiled_row_prices_base_plus_ratio_times_lethality(self) -> None:
        # The fight row's damage_per_proc is the compiled formula, per
        # melee/ranged, and the row is a true-damage packet.
        melee = _sc_row(
            _fight(
                _stats(is_melee=True),
                {"Q": _ability("Q")},
                duration=1.0,
                one_rotation=True,
            )
        )
        ranged = _sc_row(
            _fight(
                _stats(is_melee=False),
                {"Q": _ability("Q")},
                duration=1.0,
                one_rotation=True,
            )
        )
        for row, expected in ((melee, 83.0), (ranged, 41.5)):
            assert row["damage_per_proc"] == pytest.approx(expected)
            assert row["total_damage"] == pytest.approx(expected)
            assert row["damage_type"] == "true"
            assert row["name"] == "Bastionbreaker (Shaped Charge)"
            assert set(row) == {
                "name",
                "count",
                "damage_per_proc",
                "total_damage",
                "damage_type",
                "damage_events",
                "event_phase",
                # MERGE: every item row now names the declaration it was
                # priced from (``declared``) and which pair preview it
                # descends from (``pair_preview_of``), so a number in the
                # breakdown traces to the rule that produced it.
                "declared",
                "pair_preview_of",
            }


# ---------------------------------------------------------------------------
# 2. Ability-only trigger eligibility
# ---------------------------------------------------------------------------


class TestAbilityTriggerEligibility:
    def test_non_damaging_ability_is_skipped(self) -> None:
        # A zero-damage ability (stat/utility cast) never consumes the
        # charge: the next damaging cast still procs at its own time.
        fight = _fight(
            _stats(),
            {
                "Q": _ability("Q", cooldown=20.0, amount=0.0),
                "W": _ability("W", cooldown=20.0, amount=0.0),
                "E": _ability("E", cooldown=20.0),
            },
            duration=1.0,
            one_rotation=True,
        )
        row = _sc_row(fight)
        assert row["count"] == 1
        # MERGE: the event carries its ``declared`` provenance tuple now
        # (rule id, amount, attack class, and the three unset slots), so
        # the shared fields are compared rather than the whole mapping.
        (event,) = row["damage_events"]
        assert {key: event[key] for key in ("time", "damage", "damage_type")} == {
            "time": 0.0,
            "damage": 41.5,
            "damage_type": "true",
        }
        assert event["event_precision"] == "exact"
        assert event["declared"][0] == "bastionbreaker.shaped_charge"

    def test_non_damaging_only_fight_authors_no_row(self) -> None:
        fight = _fight(
            _stats(),
            {"Q": _ability("Q", amount=0.0), "W": _ability("W", amount=0.0)},
            duration=5.0,
            one_rotation=True,
        )
        assert SC_ROW not in fight["breakdown"]

    def test_basic_attacks_never_trigger(self) -> None:
        # A fight with an auto stream but no damaging casts has no proc;
        # adding autos to a damaging fight does not add procs.
        fight = _fight(
            _stats(),
            {"Q": _ability("Q")},
            duration=5.0,
            auto_attacks_only=True,
            auto_attack_uptime=1.0,
        )
        assert SC_ROW not in fight["breakdown"]
        assert fight["breakdown"]["auto_attacks"]["count"] > 0

    def test_item_procs_never_trigger(self) -> None:
        # Liandry's burn fires during the fight but the proc count/times
        # are driven only by damaging ability casts.
        fight = _fight(
            _stats(),
            {"Q": _ability("Q", cooldown=20.0)},
            duration=21.0,
            one_rotation=False,
            items=[{"name": BASTION}, {"name": "Liandry's Torment"}],
        )
        assert "burn_Liandry's Torment" in fight["breakdown"]
        row = _sc_row(fight)
        assert row["count"] == 2
        assert [event["time"] for event in row["damage_events"]] == [0.0, 20.0]

    def test_one_proc_per_damaging_ability_cast_next_instance(self) -> None:
        # Two damaging casts at t=0 (one rotation): the FIRST damaging
        # ability consumes the charge; the second is inside the cooldown.
        fight = _fight(
            _stats(),
            {"Q": _ability("Q"), "W": _ability("W")},
            duration=1.0,
            one_rotation=True,
        )
        row = _sc_row(fight)
        assert row["count"] == 1
        assert [event["time"] for event in row["damage_events"]] == [0.0]

    def test_every_damaging_cast_after_cooldown_procs(self) -> None:
        # Q and W recast every 20s; every qualifying damaging cast procs
        # exactly once (next-instance semantics, no batching).
        fight = _fight(
            _stats(),
            {"Q": _ability("Q", cooldown=20.0), "W": _ability("W", cooldown=20.0)},
            duration=41.0,
            one_rotation=False,
        )
        row = _sc_row(fight)
        assert row["count"] == 3
        assert [event["time"] for event in row["damage_events"]] == [0.0, 20.0, 40.0]
        assert fight["breakdown"]["Q"]["casts"] == 3
        assert fight["breakdown"]["W"]["casts"] == 3


# ---------------------------------------------------------------------------
# 3. Authored hit timing
# ---------------------------------------------------------------------------


class TestAuthoredHitTiming:
    def test_authored_hit_packet_preferred_over_cast_boundary(self) -> None:
        # Q's authored hit lands at 0.25; the proc rides the hit packet
        # ('hit'), not the cast boundary (0.0).  The second cast at 20.0
        # hits at 20.25 — exactly ready_at — and procs there too.
        fight = _fight(
            _stats(),
            {"Q": _ability("Q", cooldown=20.0, time_offset=0.25)},
            duration=21.0,
            one_rotation=False,
        )
        row = _sc_row(fight)
        assert [(e["time"], e["event_precision"]) for e in row["damage_events"]] == [
            (0.25, "hit"),
            (20.25, "hit"),
        ]
        assert all(e["damage"] == pytest.approx(41.5) for e in row["damage_events"])

    def test_authored_hits_ride_repeated_casts(self) -> None:
        # Three casts at 0/20/40 with authored hits at +0.25: the proc
        # times are the hit times, each consumed once.
        fight = _fight(
            _stats(),
            {"Q": _ability("Q", cooldown=20.0, time_offset=0.25)},
            duration=41.0,
            one_rotation=False,
        )
        row = _sc_row(fight)
        assert [(e["time"], e["event_precision"]) for e in row["damage_events"]] == [
            (0.25, "hit"),
            (20.25, "hit"),
            (40.25, "hit"),
        ]
        # The row's events mirror the ability's own authored packets.
        q_hits = [
            (e["time"], e["event_precision"])
            for e in fight["breakdown"]["Q"]["damage_events"]
        ]
        assert [
            (e["time"], e["event_precision"]) for e in row["damage_events"]
        ] == q_hits

    def test_certified_single_hit_boundary_is_exact(self) -> None:
        # A module-certified single-hit ability has no sub-cast offset but
        # its cast boundary IS the authored hit: precision 'exact'.
        fight = _fight(
            _stats(),
            {"Q": _ability("Q", event_order_certified="single_hit")},
            duration=1.0,
            one_rotation=True,
        )
        row = _sc_row(fight)
        assert row["damage_events"][0]["time"] == 0.0
        assert row["damage_events"][0]["event_precision"] == "exact"

    def test_per_slot_cursor_prevents_authored_packet_reuse(self) -> None:
        # Two casts, two authored packets at 0.25 and 0.30.  The second
        # cast must consume the SECOND packet, not reuse the first one
        # (which would duplicate the 0.25 proc).
        state = _receipt_state(
            damage_events=[
                {"time": 0.25, "damage": 100.0, "event_precision": "exact"},
                {"time": 0.30, "damage": 100.0, "event_precision": "exact"},
            ]
        )
        rotation = RotationResult(
            cast_events=[{"slot": "Q", "time": 0.0}, {"slot": "Q", "time": 0.1}]
        )
        receipts = _shaped_charge_proc_receipts(state, rotation, 0.01)
        assert receipts == [
            {"time": 0.25, "event_precision": "exact"},
            {"time": 0.30, "event_precision": "exact"},
        ]

    def test_consumed_packet_falls_back_to_cast_boundary(self) -> None:
        # A single authored packet with two casts: the first cast consumes
        # it; the second cast cannot reuse it and falls back to its own
        # cast boundary (one receipt per cast, no duplicates).
        state = _receipt_state(
            damage_events=[{"time": 0.25, "damage": 100.0, "event_precision": "exact"}]
        )
        rotation = RotationResult(
            cast_events=[{"slot": "Q", "time": 0.0}, {"slot": "Q", "time": 21.0}]
        )
        receipts = _shaped_charge_proc_receipts(state, rotation, 20.0)
        assert receipts == [
            {"time": 0.25, "event_precision": "exact"},
            {"time": 21.0, "event_precision": "cast_boundary"},
        ]


# ---------------------------------------------------------------------------
# 4. 20s cooldown boundary
# ---------------------------------------------------------------------------


class TestCooldownBoundary:
    def test_next_damaging_ability_at_19_9_is_denied(self) -> None:
        # Casts at 0 and 19.9: the first procs at 0, the 19.9 cast lands
        # inside the 20s cooldown and is denied.
        fight = _fight(
            _stats(),
            {"Q": _ability("Q", cooldown=19.9)},
            duration=20.0,
            one_rotation=False,
        )
        row = _sc_row(fight)
        assert fight["breakdown"]["Q"]["casts"] == 2
        assert row["count"] == 1
        assert [event["time"] for event in row["damage_events"]] == [0.0]

    def test_exactly_twenty_seconds_is_inclusive(self) -> None:
        # Casts at 0 and exactly 20.0: the 20.0 cast procs (inclusive
        # boundary).
        fight = _fight(
            _stats(),
            {"Q": _ability("Q", cooldown=20.0)},
            duration=21.0,
            one_rotation=False,
        )
        row = _sc_row(fight)
        assert row["count"] == 2
        assert [event["time"] for event in row["damage_events"]] == [0.0, 20.0]

    def test_repeated_casts_after_20s_each_proc(self) -> None:
        # Casts at 0/20/40: three procs at exactly those cast times
        # (deterministic count and times).
        fight = _fight(
            _stats(),
            {"Q": _ability("Q", cooldown=20.0)},
            duration=41.0,
            one_rotation=False,
        )
        row = _sc_row(fight)
        assert row["count"] == 3
        assert [event["time"] for event in row["damage_events"]] == [0.0, 20.0, 40.0]
        assert row["total_damage"] == pytest.approx(3 * 41.5)

    def test_cooldown_receipt_is_strictly_next_instance(self) -> None:
        # The gate re-arms at proc_time + 20, not at cast_time + 20: an
        # authored hit at 0.25 delays the next allowed proc to 20.25, so a
        # cast at 19.9 whose hit lands at 20.15 is still denied.
        fight = _fight(
            _stats(),
            {"Q": _ability("Q", cooldown=19.9, time_offset=0.25)},
            duration=21.0,
            one_rotation=False,
        )
        row = _sc_row(fight)
        assert [event["time"] for event in row["damage_events"]] == [0.25]


# ---------------------------------------------------------------------------
# 5. True-damage receipts
# ---------------------------------------------------------------------------


class TestTrueDamageReceipts:
    def test_damage_events_carry_true_type_and_full_value(self) -> None:
        fight = _fight(
            _stats(),
            {"Q": _ability("Q")},
            duration=1.0,
            one_rotation=True,
        )
        row = _sc_row(fight)
        assert all(event["damage_type"] == "true" for event in row["damage_events"])
        assert row["damage_type"] == "true"
        assert all(
            event["damage"] == pytest.approx(41.5) for event in row["damage_events"]
        )

    def test_true_damage_is_not_mitigated_by_resistances(self) -> None:
        low = _fight(_stats(), {"Q": _ability("Q")}, duration=1.0, one_rotation=True)
        high = _fight(
            _stats(),
            {"Q": _ability("Q")},
            duration=1.0,
            one_rotation=True,
            target_armor=200.0,
            target_magic_resistance=200.0,
        )
        assert _sc_row(low) == _sc_row(high)
        assert _sc_row(high)["total_damage"] == pytest.approx(41.5)
        # The mitigation-invariant receipt also survives a shielded target.
        shielded = _fight(
            _stats(),
            {"Q": _ability("Q")},
            duration=1.0,
            one_rotation=True,
            target_general_shield=1000.0,
        )
        assert _sc_row(shielded)["total_damage"] == pytest.approx(41.5)


# ---------------------------------------------------------------------------
# 6. No duplicate procs
# ---------------------------------------------------------------------------


class TestNoDuplicateProcs:
    def test_exactly_one_event_per_proc(self) -> None:
        # Six damaging casts over 41s (Q+W at 0/20/40): three procs, one
        # event each, no duplicate times.
        fight = _fight(
            _stats(),
            {"Q": _ability("Q", cooldown=20.0), "W": _ability("W", cooldown=20.0)},
            duration=41.0,
            one_rotation=False,
        )
        row = _sc_row(fight)
        times = [event["time"] for event in row["damage_events"]]
        assert row["count"] == len(row["damage_events"]) == 3
        assert len(set(times)) == len(times)
        assert times == [0.0, 20.0, 40.0]
        # The ledger copies the row's events verbatim (one receipt per
        # proc in the public damage_events stream).
        ledger = [
            event
            for event in fight["damage_events"]
            if event.get("source_key") == SC_ROW
        ]
        assert len(ledger) == 3

    def test_zero_damage_packets_do_not_mint_procs(self) -> None:
        # An authored hit packet with zero damage (e.g. a shield/utility
        # instance) never mints a proc: the walk skips to the next
        # positive packet for the same cast, and the second cast (inside
        # the cooldown started by that proc) is denied.
        state = _receipt_state(
            damage_events=[
                {"time": 0.25, "damage": 0.0, "event_precision": "exact"},
                {"time": 1.25, "damage": 100.0, "event_precision": "exact"},
            ]
        )
        rotation = RotationResult(
            cast_events=[{"slot": "Q", "time": 0.0}, {"slot": "Q", "time": 1.0}]
        )
        receipts = _shaped_charge_proc_receipts(state, rotation, 0.5)
        assert receipts == [
            {"time": 1.25, "event_precision": "exact"},
        ]


# ---------------------------------------------------------------------------
# 7. Named coarse fallback / malformed-ledger withholding
# ---------------------------------------------------------------------------


class TestCoarseFallbackAndWithholding:
    def test_no_authored_hit_marks_cast_boundary_precision(self) -> None:
        # Without an authored hit packet (and without a certified
        # cast-order row) the proc rides the cast boundary and is marked
        # 'cast_boundary' — the named coarse fallback.
        state = _receipt_state()  # no breakdown events, no cast_order
        rotation = RotationResult(cast_events=[{"slot": "Q", "time": 0.0}])
        receipts = _shaped_charge_proc_receipts(state, rotation, 20.0)
        assert receipts == [{"time": 0.0, "event_precision": "cast_boundary"}]

    @pytest.mark.parametrize(
        "cast_events",
        [
            [{"slot": "Q", "time": float("nan")}],
            [{"slot": "Q", "time": "0"}],
            [{"time": 0.0}],
            [("Q", 0.0)],
            [{"slot": "Q", "time": -1.0}],
        ],
    )
    def test_malformed_cast_receipt_withholds_proc_receipts(self, cast_events) -> None:
        # A malformed cast ledger (non-finite/non-numeric time, missing
        # slot, non-mapping event, negative time) yields NO proc receipts:
        # no timestamp is invented.
        state = _receipt_state()
        assert (
            _shaped_charge_proc_receipts(
                state, RotationResult(cast_events=cast_events), 20.0
            )
            is None
        )

    def test_malformed_authored_packet_withholds_proc_receipts(self) -> None:
        # A malformed authored hit packet (non-finite time) withholds too.
        state = _receipt_state(damage_events=[{"time": float("nan"), "damage": 100.0}])
        rotation = RotationResult(cast_events=[{"slot": "Q", "time": 0.0}])
        assert _shaped_charge_proc_receipts(state, rotation, 20.0) is None

    def test_non_finite_cooldown_withholds_proc_receipts(self) -> None:
        state = _receipt_state()
        rotation = RotationResult(cast_events=[{"slot": "Q", "time": 0.0}])
        assert _shaped_charge_proc_receipts(state, rotation, float("nan")) is None
        assert _shaped_charge_proc_receipts(state, rotation, 0.0) is None

    def test_malformed_ledger_authors_named_withheld_row_and_coarse_source(
        self, monkeypatch
    ) -> None:
        # P3-3D: a malformed cast ledger keeps a NAMED zero-damage withheld
        # row (``withheld_reason`` + coarse event phase, per the Eclipse-3C
        # precedent) and the coverage classifier treats it as a coarse
        # source — callers can distinguish a malformed ledger from a
        # passive that never fired (which authors no row at all).
        monkeypatch.setattr(
            "src.calculator.damage._shaped_charge_proc_receipts",
            lambda *args, **kwargs: None,
        )
        fight = _fight(
            _stats(),
            {"Q": _ability("Q")},
            duration=1.0,
            one_rotation=True,
        )
        row = fight["breakdown"][SC_ROW]
        assert row["withheld_reason"] == "malformed_proc_receipt"
        assert row["event_phase"] == "coarse"
        assert row["count"] == 0
        assert row["total_damage"] == 0.0
        assert row["damage_type"] == "true"
        assert "damage_events" not in row
        coverage = fight["timeline_coverage"]
        assert SC_ROW in coverage["coarse_sources"]
        assert SC_ROW not in coverage["exact_sources"]

    def test_malformed_ledger_names_the_withheld_reason(self, monkeypatch) -> None:
        # P3-3D contract: the named withheld receipt is the row-level reason
        # (kept with ``withheld_reason`` + coarse event phase, per the
        # Eclipse-3C precedent) so callers can distinguish a malformed
        # ledger from a passive that never fired without re-deriving the
        # coverage.
        monkeypatch.setattr(
            "src.calculator.damage._shaped_charge_proc_receipts",
            lambda *args, **kwargs: None,
        )
        fight = _fight(
            _stats(),
            {"Q": _ability("Q")},
            duration=1.0,
            one_rotation=True,
        )
        row = _sc_row(fight)
        assert row["withheld_reason"] == "malformed_proc_receipt"
        assert row["event_phase"] == "coarse"
        assert SC_ROW in fight["timeline_coverage"]["coarse_sources"]


# ---------------------------------------------------------------------------
# 8. Score / receipt parity and optimizer exclusion
# ---------------------------------------------------------------------------


class TestParityAndOptimizer:
    def test_score_only_fight_matches_receipt_fight(self) -> None:
        abilities = {
            "Q": _ability("Q", cooldown=20.0),
            "W": _ability("W", cooldown=20.0),
        }
        receipt = _fight(_stats(), abilities, duration=41.0, one_rotation=False)
        score = _fight(
            _stats(), abilities, duration=41.0, one_rotation=False, score_only=True
        )
        left = _sc_row(receipt)
        right = _sc_row(score)
        assert right == left
        assert right["count"] == left["count"] == 3
        assert (
            right["damage_per_proc"] == left["damage_per_proc"] == pytest.approx(41.5)
        )
        assert right["damage_events"] == left["damage_events"]
        assert right["total_damage"] == left["total_damage"] == pytest.approx(124.5)

    def test_optimizer_exclusion_source_receipt_at_low_altitude(self) -> None:
        assert SC_ROW in EXPLICIT_APPLICABILITY_EXCLUSION_SOURCES
        # A candidate whose ONLY coarse source is the shaped-charge packet
        # is eligible for the applicability exclusion (the optimizer's
        # ``excluded_sources`` receipt).
        assert applicability_exclusion_sources({"coarse_sources": [SC_ROW]}) == [SC_ROW]
        # Mixing an un-audited coarse source must NOT be rescued.
        assert (
            applicability_exclusion_sources(
                {"coarse_sources": [SC_ROW, "periodic_Unending Despair"]}
            )
            == []
        )
        # Exact-only coverage has nothing to exclude.
        assert applicability_exclusion_sources({"coarse_sources": []}) == []


# ---------------------------------------------------------------------------
# 9. Target / instance behavior
# ---------------------------------------------------------------------------


class TestTargetInstanceBehavior:
    def test_single_target_engine_has_no_per_target_fields(self) -> None:
        # The engine is champion-only 1v1: target separation is not
        # applicable, so the row and its events carry no target fields —
        # the receipt is implicitly for the single fight target.
        fight = _fight(
            _stats(),
            {"Q": _ability("Q", cooldown=20.0)},
            duration=21.0,
            one_rotation=False,
        )
        row = _sc_row(fight)
        assert "target" not in row
        assert "target_scope" not in row
        assert all("target" not in event for event in row["damage_events"])

    def test_instance_separation_is_per_damaging_cast(self) -> None:
        # Each proc instance is one damaging cast; the events are one per
        # instance with strictly increasing proc times.
        fight = _fight(
            _stats(),
            {"Q": _ability("Q", cooldown=20.0), "W": _ability("W", cooldown=20.0)},
            duration=61.0,
            one_rotation=False,
        )
        row = _sc_row(fight)
        times = [event["time"] for event in row["damage_events"]]
        assert times == [0.0, 20.0, 40.0, 60.0]
        assert row["count"] == len(times)
        assert all(times[i] < times[i + 1] for i in range(len(times) - 1))


# ---------------------------------------------------------------------------
# 10. Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_identical_fights_produce_identical_rows(self) -> None:
        abilities = {
            "Q": _ability("Q", cooldown=20.0, time_offset=0.25),
            "W": _ability("W", cooldown=20.0),
        }
        first = _fight(_stats(), abilities, duration=41.0, one_rotation=False)
        second = _fight(_stats(), abilities, duration=41.0, one_rotation=False)
        assert _sc_row(first) == _sc_row(second)
        assert json.dumps(_sc_row(first), sort_keys=True) == json.dumps(
            _sc_row(second), sort_keys=True
        )

    def test_identical_receipt_walks_produce_identical_receipts(self) -> None:
        def run() -> list[dict]:
            state = _receipt_state(
                damage_events=[
                    {"time": 0.25, "damage": 100.0, "event_precision": "exact"},
                    {"time": 20.25, "damage": 100.0, "event_precision": "exact"},
                ]
            )
            rotation = RotationResult(
                cast_events=[
                    {"slot": "Q", "time": 0.0},
                    {"slot": "Q", "time": 20.0},
                    {"slot": "Q", "time": 40.0},
                ]
            )
            return _shaped_charge_proc_receipts(state, rotation, 20.0)

        assert (
            run()
            == run()
            == [
                {"time": 0.25, "event_precision": "exact"},
                {"time": 20.25, "event_precision": "exact"},
            ]
        )

    def test_no_duplicate_events_across_identical_fights(self) -> None:
        fights = [
            _fight(
                _stats(),
                {"Q": _ability("Q", cooldown=20.0), "W": _ability("W", cooldown=20.0)},
                duration=41.0,
                one_rotation=False,
            )
            for _ in range(2)
        ]
        for fight in fights:
            row = _sc_row(fight)
            times = [event["time"] for event in row["damage_events"]]
            assert len(times) == len(set(times))
        assert [e["time"] for e in _sc_row(fights[0])["damage_events"]] == [
            e["time"] for e in _sc_row(fights[1])["damage_events"]
        ]
