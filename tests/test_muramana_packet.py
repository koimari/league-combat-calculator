"""P3 Package 3E — Muramana Shock ability-timing packet certification.

This file is the focused test-matrix owner for Muramana's Shock (ability
branch 4% melee / 3% ranged max-mana physical damage per damaging ability
instance; on-hit branch 1.2% max mana per basic attack; Awe 2% max mana as
bonus AD; NO cooldown).  It pins the OBSERVABLES the coordinator's P3-3E
completion must satisfy, and each test runs against today's source: every
behavior that already exists must pass now; every assertion that targets a
receipt the source does not emit yet is marked ``# P3-3E contract`` and
``xfail`` with reason ``awaiting P3-3E ...``.

Scope note: ``tests/test_muramana_timeline.py`` owns the engine-precision
receipts (``_muramana_proc_events``) this matrix builds on; the Muramana
raw-formula pins live in ``tests/test_item_damage.py``
(``TestMuramanaMultiCastR``) and the Ezreal on-hit suppression pins in
``tests/test_ezreal.py`` (``TestAbilityItemOnHits``); this file is
disjoint and pins only the acceptance observables below.

Contract under test (typed source-backed values: 0.012 on-hit, 0.04 melee /
0.03 ranged ability, 0.02 Awe max-mana-to-AD, physical damage, no
cooldown):

* TYPED ACCESSORS: ``required_effect_value("Muramana", ...)`` returns the
  sourced values; a missing key raises ``KeyError`` naming Muramana and
  the key (AGENTS.md rule 5: no silent stale fallbacks).  The compiled
  effect contract: ``per_ability_hits`` entry with ``breakdown_key``
  ``muramana_ability``, display "Muramana (Shock - abilities)",
  ``damage_type`` physical; the ``per_hits`` on-hit entry carries
  ``superseded_by_ability_proc`` True.
* ABILITY BRANCH: one Shock receipt per DAMAGING ability instance —
  count 1 for a single-cast Q, count 3 for a 3-instance R at one
  timestamp (multi-cast counts each instance); formula melee
  0.04 * max_mana / ranged 0.03 * max_mana, mitigated by armor
  (physical); one ``damage_events`` entry per instance.
* AUTHORED HIT TIMING: authored ability-hit packets are preferred
  (``event_precision`` "hit"/"exact" at the packet time); the
  cast-boundary fallback is marked explicitly (``event_precision``
  "cast_boundary" and the row goes coarse); a per-slot cursor prevents
  one authored packet being reused across repeated casts.
* NAMED COARSE FALLBACK / MALFORMED-LEDGER WITHHOLDING: malformed cast
  receipts (non-finite time, missing slot) and count-mismatched ledgers
  (expected procs != built events) currently yield an aggregate-only row
  without ``damage_events`` — pinned current observable: the row exists
  with its aggregate price, has no events, carries NO named reason, and
  ``muramana_ability`` IS in ``coarse_sources``.  The NAMED
  ``withheld_reason`` receipt (per the Shaped-Charge-3D precedent) is
  the P3-3E target and is xfailed below.
* ON-HIT vs ABILITY NON-CONFLATION: real basic attacks apply the 1.2%
  on-hit (max_mana 1500, armor 0 -> 18 per auto); an ability that
  applies on-hit effects (Ezreal Q) deals ONLY the ability Shock once
  per cast and NO on-hit component; an autos-only fight applies the
  on-hit Shock with NO ability Shock damage (today's source still
  authors a zero-price ``muramana_ability`` row — pinned; the strict
  row-absence is the P3-3E target and is xfailed below); no double count
  when an ability both damages and applies on-hits.
* AWE SEPARATION: ``muramana_bonus_ad(items, max_mana) == 0.02 * max_mana``
  and the conversion lands in ``calculate_total_stats`` ``attack_damage``
  as bonus AD — never inside any Shock damage row.
* NO COOLDOWN: the Shock effect has no cooldown gate — repeated ability
  casts each proc, and a 3-instance R at one timestamp procs 3 times;
  the compiled effect exposes no cooldown field and the registry record
  has no ``cooldown`` key.
* SCORE/RECEIPT PARITY: score-only and receipt fights produce the
  identical ``muramana_ability`` row (events, total).
* OPTIMIZER/BIS EXCLUSION: ``muramana_ability`` is in
  ``EXPLICIT_APPLICABILITY_EXCLUSION_SOURCES``; the pure-source
  exclusion receipt works, a mixed coarse source is never rescued, and
  BIS carries no stale Muramana defensive entry.
* DETERMINISM: identical fights produce identical rows; exactly one
  damage event per proc instance (no duplicates).

Asserted constants (0.012/0.04/0.03/0.02) are the typed accessors'
expected values; per AGENTS.md rule 5 the source must read them from
``required_effect_value`` / the parser-owned registry, and this file pins
the fail-loud behavior for a missing key.
"""

import json
from types import SimpleNamespace

import pytest

from src.calculator.ability_spec import DamagePart
from src.calculator.bis import (
    BIS_CERTIFIED_DEFENSIVE_EFFECTS,
    BIS_UNMODELED_DEFENSIVE_EFFECTS,
    bis_defensive_effect_receipt,
)
from src.calculator.champions import parse_champion_abilities
from src.calculator.damage import (
    FightConfig,
    RotationResult,
    _muramana_proc_events,
    calculate_fight_damage,
)
from src.calculator.data_fetcher import get_item_by_name
from src.calculator.item_effects import (
    DamageInputs,
    ITEM_EFFECTS,
    muramana_bonus_ad,
    required_effect_value,
    resolve_damage_effects,
)
from src.calculator.stats import calculate_total_stats
from src.calculator.timeline_coverage import (
    EXPLICIT_APPLICABILITY_EXCLUSION_SOURCES,
    applicability_exclusion_sources,
)

MURAMANA = "Muramana"
ABILITY_ROW = "muramana_ability"
ON_HIT_ROW = "on_hit_Muramana"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stats(*, is_melee: bool = False, max_mana: float = 1500.0) -> dict:
    return {
        "attack_damage": 80.0,
        "base_attack_damage": 60.0,
        "attack_speed": 0.7,
        "attack_speed_ratio": 0.625,
        "critical_strike_chance": 0.0,
        "magic_penetration_flat": 0.0,
        "magic_penetration_percent": 0.0,
        "armor_penetration_flat": 0.0,
        "armor_penetration_percent": 0.0,
        "lethality": 0.0,
        "ability_power": 100.0,
        "max_mana": max_mana,
        "is_melee": is_melee,
        "level": 18,
    }


def _ability(
    name: str,
    cooldown: float = 7.0,
    time_offset: float | None = None,
    **extra,
) -> dict:
    return {
        "name": name,
        "rank": 1,
        "cooldown": cooldown,
        "parts": (DamagePart("magic", 200.0, time_offset=time_offset),),
        "total_raw": 200.0,
        "damage_type": "magic",
        **extra,
    }


def _fight(
    stats: dict,
    abilities: dict,
    *,
    duration: float,
    score_only: bool = False,
    cast_order: list[str] | None = None,
    **kwargs,
) -> dict:
    kwargs.setdefault("auto_attack_uptime", 0.0)
    target_armor = float(kwargs.pop("target_armor", 0.0))
    target_magic_resistance = float(kwargs.pop("target_magic_resistance", 0.0))
    return calculate_fight_damage(
        stats,
        abilities,
        [{"name": MURAMANA}],
        FightConfig(
            target_health=2000.0,
            target_armor=target_armor,
            target_magic_resistance=target_magic_resistance,
            fight_duration_seconds=duration,
            cast_order=cast_order,
            **kwargs,
        ),
        score_only=score_only,
    )


def _ability_row(result: dict) -> dict:
    return result["breakdown"][ABILITY_ROW]


def _proc_state(*, cast_instances: int = 1, damage_events=None):
    """A unit-level FightState stand-in for ``_muramana_proc_events``.

    Matches the SimpleNamespace states
    ``tests/test_muramana_timeline.py`` feeds the builder; omitting
    ``damage_events`` is the "no authored hit exists" condition that
    falls back to the cast boundary.
    """
    breakdown = {}
    if damage_events is not None:
        breakdown["Q"] = {"damage_events": damage_events}
    return SimpleNamespace(
        # A realistic ability packet carries its damage parts; Shock's
        # damaging-cast gate reads them (P3 package 3E).
        ability_damages={
            "Q": {
                "cast_instances": cast_instances,
                "parts": (DamagePart("magic", 100.0),),
            }
        },
        breakdown=breakdown,
    )


# ---------------------------------------------------------------------------
# 1. Typed / source-backed contract
# ---------------------------------------------------------------------------


class TestTypedContract:
    def test_cached_item_name_resolves(self) -> None:
        item = get_item_by_name(MURAMANA)
        assert item.get("name") == MURAMANA
        assert [passive.get("name") for passive in item.get("passives", [])] == [
            "Awe",
            "Shock",
        ]

    def test_typed_accessor_values_match_expected_constants(self) -> None:
        assert required_effect_value(MURAMANA, "max_mana_ratio_on_hit") == 0.012
        assert required_effect_value(MURAMANA, "max_mana_ratio_ability_melee") == 0.04
        assert required_effect_value(MURAMANA, "max_mana_ratio_ability_ranged") == 0.03
        assert required_effect_value(MURAMANA, "max_mana_to_ad_ratio") == 0.02
        assert required_effect_value(MURAMANA, "damage_type") == "physical"

    def test_missing_typed_key_fails_loud_naming_item_and_key(self) -> None:
        with pytest.raises(KeyError, match="Muramana.*shock_missing_key_3e"):
            required_effect_value(MURAMANA, "shock_missing_key_3e")

    def test_registry_carries_the_wiki_revision_receipt(self) -> None:
        # P3-3E: the Muramana registry record carries the code-owned wiki
        # revision receipt (docs/wiki-full-entry-audit.json page 747852,
        # rev 4005926), so a parser refresh cannot silently adopt new
        # Shock values without a pinned revision to diff.
        assert required_effect_value("Muramana", "source_url") == (
            "https://wiki.leagueoflegends.com/en-us/Muramana"
        )
        assert required_effect_value("Muramana", "source_revision_id") == 4005926

    def test_compiled_effect_contract_ability_branch(self) -> None:
        effect = resolve_damage_effects([{"name": MURAMANA}]).per_ability_hits[0]
        assert effect.item_name == MURAMANA
        assert effect.breakdown_key == ABILITY_ROW
        assert effect.display_name == "Muramana (Shock - abilities)"
        assert effect.damage_type == "physical"

    def test_compiled_effect_contract_on_hit_branch_superseded(self) -> None:
        per_hits = resolve_damage_effects([{"name": MURAMANA}]).per_hits
        assert len(per_hits) == 1
        effect = per_hits[0]
        assert effect.source.item_name == MURAMANA
        assert effect.source.breakdown_key == ON_HIT_ROW
        assert effect.superseded_by_ability_proc is True

    def test_compiled_formulas_ride_the_typed_accessors(self) -> None:
        effect = resolve_damage_effects([{"name": MURAMANA}])
        ability = effect.per_ability_hits[0]
        on_hit = effect.per_hits[0].source
        inputs = DamageInputs(_stats(), 18, False, 2000.0, 2000.0)
        melee = DamageInputs(_stats(is_melee=True), 18, True, 2000.0, 2000.0)
        assert ability.raw_damage(melee) == pytest.approx(0.04 * 1500.0)
        assert ability.raw_damage(inputs) == pytest.approx(0.03 * 1500.0)
        assert on_hit.raw_damage(inputs) == pytest.approx(0.012 * 1500.0)


# ---------------------------------------------------------------------------
# 2. Ability branch: one Shock per damaging ability instance
# ---------------------------------------------------------------------------


class TestAbilityBranch:
    def test_single_cast_ability_procs_once(self) -> None:
        fight = _fight(
            _stats(),
            {"Q": _ability("Q")},
            duration=1.0,
            one_rotation=True,
            cast_order=["Q"],
            target_armor=100.0,
        )
        row = _ability_row(fight)
        assert len(row["damage_events"]) == 1
        assert row["event_phase"] == "ability"
        # Ranged 0.03 * 1500 = 45 raw, mitigated by 100 armor (50%) = 22.5.
        assert row["total_damage"] == pytest.approx(22.5)
        assert row["damage_events"][0]["damage"] == pytest.approx(22.5)

    def test_three_instance_r_procs_three_times_at_one_timestamp(self) -> None:
        fight = _fight(
            _stats(),
            {
                "R": {
                    "name": "Spirit Rush",
                    "parts": (DamagePart("magic", 200.0, count=3),),
                    "cast_instances": 3,
                    "total_raw": 600.0,
                    "damage_type": "magic",
                    "cooldown": 90.0,
                }
            },
            duration=1.0,
            one_rotation=True,
            cast_order=["R"],
            target_armor=100.0,
        )
        row = _ability_row(fight)
        assert len(row["damage_events"]) == 3
        assert [event["time"] for event in row["damage_events"]] == [0.0, 0.0, 0.0]
        # Three per-instance events, one per instance, each 22.5 mitigated.
        assert all(
            event["damage"] == pytest.approx(22.5) for event in row["damage_events"]
        )
        assert row["total_damage"] == pytest.approx(67.5)

    def test_melee_formula_is_4_percent_max_mana(self) -> None:
        fight = _fight(
            _stats(is_melee=True),
            {"Q": _ability("Q")},
            duration=1.0,
            one_rotation=True,
            cast_order=["Q"],
            target_armor=100.0,
        )
        row = _ability_row(fight)
        # Melee 0.04 * 1500 = 60 raw, mitigated by 100 armor (50%) = 30.
        assert row["total_damage"] == pytest.approx(30.0)

    def test_ranged_formula_is_3_percent_max_mana(self) -> None:
        fight = _fight(
            _stats(is_melee=False),
            {"Q": _ability("Q")},
            duration=1.0,
            one_rotation=True,
            cast_order=["Q"],
            target_armor=100.0,
        )
        row = _ability_row(fight)
        # Ranged 0.03 * 1500 = 45 raw, mitigated by 100 armor (50%) = 22.5.
        assert row["total_damage"] == pytest.approx(22.5)

    def test_shock_is_physical_and_armor_mitigated_only(self) -> None:
        armor = _fight(
            _stats(),
            {"Q": _ability("Q")},
            duration=1.0,
            one_rotation=True,
            cast_order=["Q"],
            target_armor=100.0,
            target_magic_resistance=100.0,
        )
        no_armor = _fight(
            _stats(),
            {"Q": _ability("Q")},
            duration=1.0,
            one_rotation=True,
            cast_order=["Q"],
            target_armor=0.0,
            target_magic_resistance=100.0,
        )
        assert _ability_row(armor)["total_damage"] == pytest.approx(22.5)
        assert _ability_row(no_armor)["total_damage"] == pytest.approx(45.0)
        assert _ability_row(armor)["damage_type"] == "physical"
        assert all(
            event["damage_type"] == "physical"
            for event in _ability_row(armor)["damage_events"]
        )

    def test_damage_events_are_one_per_instance_in_the_ledger(self) -> None:
        fight = _fight(
            _stats(),
            {
                "R": {
                    "name": "Spirit Rush",
                    "parts": (DamagePart("magic", 200.0, count=3),),
                    "cast_instances": 3,
                    "total_raw": 600.0,
                    "damage_type": "magic",
                    "cooldown": 90.0,
                }
            },
            duration=1.0,
            one_rotation=True,
            cast_order=["R"],
            target_armor=100.0,
        )
        ledger = [
            event
            for event in fight["damage_events"]
            if event.get("source_key") == ABILITY_ROW
        ]
        assert len(ledger) == 3
        assert all(event["damage"] == pytest.approx(22.5) for event in ledger)

    def _zero_damage_ability(self, name: str) -> dict:
        return {
            "name": name,
            "rank": 1,
            "cooldown": 7.0,
            "parts": (DamagePart("magic", 0.0),),
            "total_raw": 0.0,
            "damage_type": "magic",
        }

    def test_zero_damage_casts_never_proc_shock(self) -> None:
        # P3-3E (runtime-audit finding): Shock is gated on "Dealing ability
        # damage to champions" — a cast that deals zero damage (spell-shield
        # slots, rank-0 leftovers, stat-buff ultimates) never procs.  A
        # fight with only zero-damage abilities authors no ability row.
        fight = _fight(
            _stats(),
            {
                "E": self._zero_damage_ability("E"),
                "R": self._zero_damage_ability("R"),
            },
            duration=1.0,
            one_rotation=True,
            cast_order=["E", "R"],
        )
        assert ABILITY_ROW not in fight["breakdown"]

    def test_mixed_damaging_and_zero_damage_casts_count_only_damaging(
        self,
    ) -> None:
        # A damaging Q plus a zero-damage E/R: exactly ONE Shock proc per
        # damaging cast — the zero-damage slots never mint events.
        fight = _fight(
            _stats(),
            {
                "Q": _ability("Q"),
                "E": self._zero_damage_ability("E"),
                "R": self._zero_damage_ability("R"),
            },
            duration=1.0,
            one_rotation=True,
            cast_order=["Q", "E", "R"],
            target_armor=0.0,
        )
        row = _ability_row(fight)
        assert row["total_damage"] == pytest.approx(0.03 * 1500.0)
        assert len(row["damage_events"]) == 1


# ---------------------------------------------------------------------------
# 3. Authored hit timing / cast-boundary fallback / per-slot cursor
# ---------------------------------------------------------------------------


class TestAuthoredHitTiming:
    def test_authored_ability_hit_packet_preferred(self) -> None:
        # Q's authored hit lands at 0.25; the Shock event rides THAT
        # packet's time and precision instead of the cast boundary.
        fight = _fight(
            _stats(),
            {"Q": _ability("Q", time_offset=0.25, event_order_certified="single_hit")},
            duration=1.0,
            one_rotation=True,
            cast_order=["Q"],
            target_armor=100.0,
        )
        event = _ability_row(fight)["damage_events"][0]
        assert event["time"] == 0.25
        assert event["event_precision"] == "exact"

    def test_generic_authored_hit_rides_the_packet_precision(self) -> None:
        # A generic (uncertified) ability with an authored hit packet
        # still rides the packet: precision "hit" at 0.25.
        fight = _fight(
            _stats(),
            {"Q": _ability("Q", time_offset=0.25)},
            duration=1.0,
            one_rotation=True,
            cast_order=["Q"],
            target_armor=100.0,
        )
        event = _ability_row(fight)["damage_events"][0]
        assert event["time"] == 0.25
        assert event["event_precision"] == "hit"

    def test_cast_boundary_fallback_is_marked_explicitly(self) -> None:
        # A DoT cast has no authored sub-hit packet: the Shock rides the
        # cast boundary at t=0 and is explicitly marked "cast_boundary",
        # which the coverage classifier treats as coarse.
        fight = _fight(
            _stats(),
            {"Q": _ability("Q", dot_duration=3.0)},
            duration=1.0,
            one_rotation=True,
            cast_order=["Q"],
            target_armor=100.0,
        )
        row = _ability_row(fight)
        assert row["damage_events"] == [
            {
                "time": 0.0,
                "damage": 22.5,
                "event_precision": "cast_boundary",
                "cast_id": "Q:1",
                "target_id": "target:0",
                "damage_type": "physical",
            }
        ]
        assert ABILITY_ROW in fight["timeline_coverage"]["coarse_sources"]
        assert ABILITY_ROW not in fight["timeline_coverage"]["exact_sources"]

    def test_per_slot_cursor_prevents_authored_packet_reuse(self) -> None:
        # Two casts, two authored packets at 0.25 and 0.30: the second
        # cast must consume the SECOND packet, not reuse the first one
        # (which would duplicate the 0.25 proc).
        state = _proc_state(
            damage_events=[
                {"time": 0.25, "damage": 100.0, "event_precision": "exact"},
                {"time": 0.30, "damage": 100.0, "event_precision": "exact"},
            ]
        )
        rotation = RotationResult(
            total_muramana_procs=2,
            cast_events=[{"slot": "Q", "time": 0.0}, {"slot": "Q", "time": 0.1}],
        )
        events = _muramana_proc_events(state, rotation)
        assert [(event["time"], event["event_precision"]) for event in events] == [
            (0.25, "exact"),
            (0.30, "exact"),
        ]


# ---------------------------------------------------------------------------
# 4. Named coarse fallback / malformed-ledger withholding
# ---------------------------------------------------------------------------


class TestMalformedLedgerWithholding:
    @pytest.mark.parametrize(
        "cast_events",
        [
            [{"slot": "Q", "time": float("nan")}],
            [{"slot": "Q", "time": "0"}],
            [{"slot": "Q", "time": -1.0}],
            [{"time": 0.0}],
            [("Q", 0.0)],
        ],
    )
    def test_malformed_cast_receipt_withholds_proc_events(self, cast_events) -> None:
        # A malformed cast ledger (non-finite/non-numeric time, missing
        # slot, negative time, non-mapping event) withholds the event
        # list: no timestamp is invented.
        state = _proc_state()
        assert (
            _muramana_proc_events(
                state, RotationResult(total_muramana_procs=1, cast_events=cast_events)
            )
            is None
        )

    def test_count_mismatch_withholds_proc_events(self) -> None:
        # Expected procs (1) disagree with the built events (2 from a
        # 2-instance ability): the ledger is incomplete, so the event
        # list is withheld rather than half-priced.
        state = _proc_state(cast_instances=2)
        rotation = RotationResult(
            total_muramana_procs=1, cast_events=[{"slot": "Q", "time": 0.0}]
        )
        assert _muramana_proc_events(state, rotation) is None

    def test_malformed_ledger_yields_aggregate_only_row_without_events(
        self, monkeypatch
    ) -> None:
        # With the proc ledger withheld, the row keeps its aggregate price
        # (per-proc mitigated damage x expected procs) but authors NO
        # damage_events; it is stamped with the NAMED withheld reason and
        # the coverage classifier marks it coarse.
        monkeypatch.setattr(
            "src.calculator.damage._muramana_proc_events",
            lambda *args, **kwargs: None,
        )
        fight = _fight(
            _stats(),
            {"Q": _ability("Q")},
            duration=1.0,
            one_rotation=True,
            cast_order=["Q"],
            target_armor=100.0,
        )
        row = _ability_row(fight)
        assert row["name"] == "Muramana (Shock - abilities)"
        assert row["total_damage"] == pytest.approx(22.5)
        assert row["damage_type"] == "physical"
        assert "damage_events" not in row
        assert row["event_phase"] == "coarse"
        assert row["withheld_reason"] == "malformed_proc_receipt"
        coverage = fight["timeline_coverage"]
        assert ABILITY_ROW in coverage["coarse_sources"]
        assert ABILITY_ROW not in coverage["exact_sources"]

    def test_malformed_ledger_names_the_withheld_reason(self, monkeypatch) -> None:
        # P3-3E contract: the named withheld receipt is the row-level
        # reason (kept with ``withheld_reason`` + coarse event phase, per
        # the Shaped-Charge-3D precedent) so callers can distinguish a
        # malformed ledger from a passive that never fired without
        # re-deriving the coverage.  The aggregate price is preserved (the
        # proc count is the trusted cast receipt) but the events are
        # withheld with the named reason.
        monkeypatch.setattr(
            "src.calculator.damage._muramana_proc_events",
            lambda *args, **kwargs: None,
        )
        fight = _fight(
            _stats(),
            {"Q": _ability("Q")},
            duration=1.0,
            one_rotation=True,
            cast_order=["Q"],
            target_armor=100.0,
        )
        row = _ability_row(fight)
        assert row["withheld_reason"] == "malformed_proc_receipt"
        assert row["event_phase"] == "coarse"
        assert row["total_damage"] > 0.0  # aggregate price preserved
        assert "damage_events" not in row
        assert ABILITY_ROW in fight["timeline_coverage"]["coarse_sources"]


# ---------------------------------------------------------------------------
# 5. On-hit vs ability non-conflation
# ---------------------------------------------------------------------------


class TestOnHitVsAbilityNonConflation:
    def test_real_autos_apply_1_2_percent_on_hit(self) -> None:
        # Autos-only fight, max_mana 1500, armor 0: 0.012 * 1500 = 18 per
        # auto, one application per auto.
        fight = _fight(
            _stats(),
            {},
            duration=5.0,
            one_rotation=False,
            auto_attack_uptime=1.0,
            target_armor=0.0,
        )
        autos = fight["breakdown"]["auto_attacks"]
        row = fight["breakdown"][ON_HIT_ROW]
        assert autos["count"] > 0
        assert row["count"] == autos["count"]
        assert row["damage_per_hit"] == pytest.approx(18.0)
        assert row["total_damage"] == pytest.approx(18.0 * autos["count"])
        assert len(row["damage_events"]) == autos["count"]

    def test_autos_only_fight_has_no_ability_shock_damage(self) -> None:
        # An autos-only fight deals the on-hit Shock but NO ability Shock
        # damage: the passive never fired, so no ``muramana_ability`` row
        # is authored at all (P3-3E; the Shaped-Charge never-fired
        # precedent).
        fight = _fight(
            _stats(),
            {},
            duration=5.0,
            one_rotation=False,
            auto_attack_uptime=1.0,
            target_armor=0.0,
        )
        assert ABILITY_ROW not in fight["breakdown"]
        coverage = fight["timeline_coverage"]
        assert ABILITY_ROW not in coverage["coarse_sources"]
        assert ABILITY_ROW not in coverage["exact_sources"]

    def test_autos_only_fight_authors_no_ability_row(self) -> None:
        # P3-3E contract: a fight with zero ability casts never fires the
        # ability Shock, so no ``muramana_ability`` row is authored (the
        # Shaped-Charge precedent authors no row for a passive that never
        # fired).
        fight = _fight(
            _stats(),
            {},
            duration=5.0,
            one_rotation=False,
            auto_attack_uptime=1.0,
            target_armor=0.0,
        )
        assert ABILITY_ROW not in fight["breakdown"]

    def test_ezreal_q_deals_only_the_ability_shock_per_cast(self, ezreal_data) -> None:
        # End-to-end: Ezreal Q applies item on-hits, but Muramana's on-hit
        # component is superseded by the per-cast ability Shock.  One Q
        # cast -> exactly one ability Shock event (0.03 * 1500 = 45 at
        # armor 0) and NO on-hit row for the ability application.
        abilities = parse_champion_abilities(
            ezreal_data,
            18,
            0.0,
            ability_ranks={"Q": 5, "W": 0, "E": 0, "R": 0},
            champion_stats=_stats(max_mana=1500.0),
            target_stats={"target_max_health": 2000.0},
        )
        assert abilities["Q"]["applies_item_on_hits"] == {
            "effectiveness": 1.0,
            "hits": 1,
            "triggers": ("on_hit", "on_attack"),
        }
        fight = _fight(
            _stats(),
            abilities,
            duration=4.0,
            one_rotation=True,
            auto_attack_uptime=0.0,
            target_armor=0.0,
        )
        row = _ability_row(fight)
        assert len(row["damage_events"]) == 1
        assert row["total_damage"] == pytest.approx(45.0)
        assert "on_hit_items_Q" not in fight["breakdown"]
        on_hit = fight["breakdown"][ON_HIT_ROW]
        assert on_hit["total_damage"] == 0.0
        assert on_hit["count"] == 0

    def test_no_double_count_when_ability_damages_and_applies_on_hits(
        self, ezreal_data
    ) -> None:
        # Q + autos in one fight: the ability Shock fires once per Q cast
        # and the on-hit Shock once per REAL auto — Q's application never
        # stacks a second on-hit copy.
        abilities = parse_champion_abilities(
            ezreal_data,
            18,
            0.0,
            ability_ranks={"Q": 5, "W": 0, "E": 0, "R": 0},
            champion_stats=_stats(max_mana=1500.0),
            target_stats={"target_max_health": 2000.0},
        )
        fight = _fight(
            _stats(),
            abilities,
            duration=4.0,
            one_rotation=False,
            auto_attack_uptime=1.0,
            target_armor=0.0,
        )
        q_casts = fight["breakdown"]["Q"]["casts"]
        autos = fight["breakdown"]["auto_attacks"]["count"]
        assert q_casts == 2
        ability = _ability_row(fight)
        assert len(ability["damage_events"]) == q_casts
        assert ability["total_damage"] == pytest.approx(45.0 * q_casts)
        on_hit = fight["breakdown"][ON_HIT_ROW]
        assert on_hit["count"] == autos
        assert on_hit["total_damage"] == pytest.approx(18.0 * autos)


# ---------------------------------------------------------------------------
# 6. Awe separation: 2% max mana as bonus AD in stats, never in Shock rows
# ---------------------------------------------------------------------------


class TestAweSeparation:
    def test_muramana_bonus_ad_formula_is_typed(self) -> None:
        items = [{"name": MURAMANA}]
        assert muramana_bonus_ad(items, 1500.0) == pytest.approx(0.02 * 1500.0)
        assert muramana_bonus_ad(items, 1843.0) == pytest.approx(0.02 * 1843.0)
        assert muramana_bonus_ad([], 1500.0) == 0.0

    def test_awe_lands_in_total_stats_as_bonus_ad(self, ahri_data) -> None:
        mura = get_item_by_name(MURAMANA)
        with_item = calculate_total_stats(ahri_data, 18, [mura])
        without_item = calculate_total_stats(ahri_data, 18, [])
        max_mana = with_item["max_mana"]
        # Item flat AD (35) + Awe 2% of TOTAL max mana (includes the
        # item's own 1000 mana), all as bonus AD inside attack_damage.
        # stats.py rounds the bonus-AD bundle (``round(final_bonus_ad)``).
        expected_bonus = 35.0 + muramana_bonus_ad([mura], max_mana)
        assert with_item["bonus_attack_damage"] == round(expected_bonus)
        assert with_item["attack_damage"] == without_item["attack_damage"] + round(
            expected_bonus
        )

    def test_awe_is_absent_from_shock_damage_rows(self) -> None:
        # Shock formulas read max_mana only: identical max_mana with
        # different bonus AD produces byte-identical Shock rows.
        low_ad = _stats(max_mana=1500.0)
        low_ad["bonus_attack_damage"] = 0.0
        high_ad = _stats(max_mana=1500.0)
        high_ad["bonus_attack_damage"] = 200.0
        abilities = {"Q": _ability("Q")}
        fight_low = _fight(
            low_ad,
            abilities,
            duration=1.0,
            one_rotation=True,
            cast_order=["Q"],
            target_armor=0.0,
        )
        fight_high = _fight(
            high_ad,
            abilities,
            duration=1.0,
            one_rotation=True,
            cast_order=["Q"],
            target_armor=0.0,
        )
        assert _ability_row(fight_low) == _ability_row(fight_high)


# ---------------------------------------------------------------------------
# 7. No cooldown
# ---------------------------------------------------------------------------


class TestNoCooldown:
    def test_registry_record_has_no_cooldown_key(self) -> None:
        assert "cooldown" not in ITEM_EFFECTS[MURAMANA]

    def test_compiled_ability_source_exposes_no_cooldown(self) -> None:
        effect = resolve_damage_effects([{"name": MURAMANA}]).per_ability_hits[0]
        assert not hasattr(effect, "cooldown")

    def test_repeated_ability_casts_each_proc(self) -> None:
        # Q with a 0.5s cooldown over 2.1s casts 5 times; every cast
        # procs — no internal Shock cooldown gate.
        fight = _fight(
            _stats(),
            {"Q": _ability("Q", cooldown=0.5)},
            duration=2.1,
            one_rotation=False,
            cast_order=["Q"],
            target_armor=100.0,
        )
        row = _ability_row(fight)
        assert fight["breakdown"]["Q"]["casts"] == 5
        assert len(row["damage_events"]) == 5
        assert [event["time"] for event in row["damage_events"]] == [
            0.0,
            0.5,
            1.0,
            1.5,
            2.0,
        ]
        assert row["total_damage"] == pytest.approx(5 * 22.5)

    def test_three_instance_r_at_one_timestamp_procs_three_times(self) -> None:
        # No cooldown means a single 3-instance cast at t=0 fires all
        # three Shock instances at that same timestamp.
        fight = _fight(
            _stats(),
            {
                "R": {
                    "name": "Spirit Rush",
                    "parts": (DamagePart("magic", 200.0, count=3),),
                    "cast_instances": 3,
                    "total_raw": 600.0,
                    "damage_type": "magic",
                    "cooldown": 90.0,
                }
            },
            duration=1.0,
            one_rotation=True,
            cast_order=["R"],
            target_armor=0.0,
        )
        row = _ability_row(fight)
        assert len(row["damage_events"]) == 3
        assert [event["time"] for event in row["damage_events"]] == [0.0, 0.0, 0.0]
        assert row["total_damage"] == pytest.approx(3 * 45.0)


# ---------------------------------------------------------------------------
# 8. Score / receipt parity
# ---------------------------------------------------------------------------


class TestScoreReceiptParity:
    def test_score_only_fight_matches_receipt_fight(self) -> None:
        abilities = {
            "Q": _ability("Q", time_offset=0.25, event_order_certified="single_hit")
        }
        receipt = _fight(
            _stats(),
            abilities,
            duration=1.0,
            one_rotation=True,
            cast_order=["Q"],
            target_armor=100.0,
        )
        score = _fight(
            _stats(),
            abilities,
            duration=1.0,
            one_rotation=True,
            cast_order=["Q"],
            target_armor=100.0,
            score_only=True,
        )
        assert _ability_row(score) == _ability_row(receipt)
        assert (
            _ability_row(score)["damage_events"]
            == _ability_row(receipt)["damage_events"]
        )
        assert _ability_row(score)["total_damage"] == pytest.approx(22.5)

    def test_score_only_parity_for_multi_instance_r(self) -> None:
        abilities = {
            "R": {
                "name": "Spirit Rush",
                "parts": (DamagePart("magic", 200.0, count=3),),
                "cast_instances": 3,
                "total_raw": 600.0,
                "damage_type": "magic",
                "cooldown": 90.0,
            }
        }
        receipt = _fight(
            _stats(),
            abilities,
            duration=1.0,
            one_rotation=True,
            cast_order=["R"],
            target_armor=100.0,
        )
        score = _fight(
            _stats(),
            abilities,
            duration=1.0,
            one_rotation=True,
            cast_order=["R"],
            target_armor=100.0,
            score_only=True,
        )
        assert _ability_row(score) == _ability_row(receipt)
        assert len(_ability_row(score)["damage_events"]) == 3


# ---------------------------------------------------------------------------
# 9. Optimizer / BIS exclusion
# ---------------------------------------------------------------------------


class TestOptimizerExclusion:
    def test_ability_row_is_an_explicit_applicability_exclusion_source(self) -> None:
        assert ABILITY_ROW in EXPLICIT_APPLICABILITY_EXCLUSION_SOURCES

    def test_pure_source_exclusion_receipt(self) -> None:
        # A candidate whose ONLY coarse source is the ability Shock
        # packet is eligible for the applicability exclusion (the
        # optimizer's ``excluded_sources`` receipt).
        assert applicability_exclusion_sources({"coarse_sources": [ABILITY_ROW]}) == [
            ABILITY_ROW
        ]

    def test_mixed_coarse_source_is_never_rescued(self) -> None:
        assert (
            applicability_exclusion_sources(
                {"coarse_sources": [ABILITY_ROW, "periodic_Unending Despair"]}
            )
            == []
        )

    def test_exact_only_coverage_has_nothing_to_exclude(self) -> None:
        assert applicability_exclusion_sources({"coarse_sources": []}) == []

    def test_bis_has_no_stale_muramana_defensive_entry(self) -> None:
        # Muramana is a damage item: it must never appear as a certified
        # or unmodeled defensive effect, and the BIS receipt says so.
        assert MURAMANA not in BIS_CERTIFIED_DEFENSIVE_EFFECTS
        assert MURAMANA not in BIS_UNMODELED_DEFENSIVE_EFFECTS
        assert bis_defensive_effect_receipt(MURAMANA, {}) == {
            "status": "no_special_defensive_effect",
            "sources": [],
        }


# ---------------------------------------------------------------------------
# 10. Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_identical_fights_produce_identical_rows(self) -> None:
        abilities = {"Q": _ability("Q", time_offset=0.25)}
        first = _fight(
            _stats(),
            abilities,
            duration=1.0,
            one_rotation=True,
            cast_order=["Q"],
            target_armor=100.0,
        )
        second = _fight(
            _stats(),
            abilities,
            duration=1.0,
            one_rotation=True,
            cast_order=["Q"],
            target_armor=100.0,
        )
        assert _ability_row(first) == _ability_row(second)
        assert json.dumps(_ability_row(first), sort_keys=True) == json.dumps(
            _ability_row(second), sort_keys=True
        )

    def test_no_duplicate_events_for_multi_instance_cast(self) -> None:
        # Three instances at one timestamp -> exactly three events, one
        # per instance (never two copies of the same instance).
        fight = _fight(
            _stats(),
            {
                "R": {
                    "name": "Spirit Rush",
                    "parts": (DamagePart("magic", 200.0, count=3),),
                    "cast_instances": 3,
                    "total_raw": 600.0,
                    "damage_type": "magic",
                    "cooldown": 90.0,
                }
            },
            duration=1.0,
            one_rotation=True,
            cast_order=["R"],
            target_armor=0.0,
        )
        row = _ability_row(fight)
        assert len(row["damage_events"]) == 3
        ledger = [
            event
            for event in fight["damage_events"]
            if event.get("source_key") == ABILITY_ROW
        ]
        assert len(ledger) == 3
