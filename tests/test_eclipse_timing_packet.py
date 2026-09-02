"""P3 Package 3C — Eclipse Ever Rising Moon stack/proc/shield packet certification.

This file is the focused test-matrix owner for Eclipse's Ever Rising Moon
(``proc_Eclipse``) stack/proc/shield contract.  It pins the OBSERVABLES the
coordinator's P3-3C completion must satisfy, and each test runs against
today's source: every behavior that already exists must pass now; every
assertion that targets a receipt the source does not emit yet is marked
``# P3-3C contract`` and ``xfail`` with reason ``awaiting P3-3C ...``.

Scope note: ``tests/test_eclipse_timeline.py`` owns the engine-precision
receipts and ``TestEclipseConsumer`` in
``tests/test_state_lifecycle_consumers.py`` owns the kernel-rule receipts
this matrix builds on; this file is disjoint and pins only the acceptance
observables below.

Contract under test (typed source-backed values: 6% melee / 4% ranged
max-HP damage, 2 stacks within 2s, 6s per-target cooldown, shield
160/80 + 40%/20% bonus AD for 2s):

* TYPED ACCESSORS: ``required_effect_value("Eclipse", ...)`` returns the
  sourced values; a missing key raises ``KeyError`` naming Eclipse and the
  key (AGENTS.md rule 5: no silent stale fallbacks).
* STACK GAIN: two distinct damaging ability casts inside 2s complete one
  pair -> ``proc_Eclipse`` count 1; a third hit inside the same window does
  NOT create a second pair until the cooldown; a window lapse (2nd hit >
  2s after the 1st) restarts the window (kernel transitions
  gain/expire/proc/cooldown_start; engine: no proc row).
* TRIGGER TIMING: the pair lands at the SECOND hit's timestamp (cast
  boundary -> ``event_precision`` "exact"; authored hit time -> "hit");
  two casts at t=0 -> one pair at t=0; the self shield rides the proc
  event at the same time (participant timeline ``support_events`` shield
  declaring ``LATE_BARRIER`` and ``_trigger_event_id`` linking to the proc
  event).
* PER-TARGET COOLDOWN: pair at t=0 completes; a next qualifying pair
  before t=6 is denied (kernel ``trigger_skipped`` reason
  ``per_target_cooldown``; engine: no proc); exactly t=6 is allowed
  (inclusive boundary); the engine is 1v1-only (procs carry
  ``target == "target:0"`` from the pair cast receipt) and the
  kernel gate's per-target clocks are pinned directly.
* SHIELD PACKET: amount = base + bonus_ad_ratio * bonus AD (melee
  160 + 0.4*AD, ranged 80 + 0.2*AD), duration 2s, ``target_scope`` self,
  exactly one packet per completed pair; survival receives/absorbs/expires
  in order, and a shield whose trigger event is absent is skipped
  (fail-closed trigger linkage).
* SCORE/RECEIPT/PUBLIC PARITY: score-only fights and receipt fights
  produce the same proc count/times/damage; ``proc_Eclipse`` is in
  ``EXPLICIT_APPLICABILITY_EXCLUSION_SOURCES`` with the pure-source
  exclusion receipt (no mixed rescue); the compiled score walk fails
  closed for Eclipse holders (the declared ``ReceiptOnly`` compilability)
  with the named ``item_mechanic=Eclipse`` receipt.
* FAIL-CLOSED METADATA: a malformed proc receipt (non-finite hit time /
  missing slot) withholds event precision — the row keeps a duration-scaled
  coarse price but authors no ``damage_events`` / ``self_shield_events`` /
  ``state_transitions`` and the coverage goes coarse — WITHOUT a named
  reason today (the NAMED reason is the P3-3C target); a ``self_shield``
  payload with non-numeric amount/duration produces no shield packet.
* DETERMINISM: identical fights produce identical ``state_transitions``
  receipts (full row equality); one completed pair authors exactly one
  damage event (no duplicates).

Asserted constants (0.06/0.04/2/2.0/6.0/160.0/80.0/0.40/0.20/2.0) are the
typed accessors' expected values; per AGENTS.md rule 5 the source must
read them from ``required_effect_value`` / the parser-owned registry, and
this file pins the fail-loud behavior for a missing key.
"""

import pytest

from src.app import _load_public_champion
from src.calculator import participant_timeline
from src.calculator.ability_spec import DamagePart
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.data_fetcher import get_item_by_name
from src.calculator.defensive_effects import StartingDefenses, resolve_starting_defenses
from src.calculator.interpreters import (
    cast_proc,
    compilability_for,
    uncompilable_item_receipt,
)
from src.calculator.item_behavior import FightFacts, ReceiptOnly, ReceiptScope
from src.calculator.item_effects import (
    eclipse_trigger_gate,
    required_effect_value,
)
from src.calculator.participant_timeline import Combatant, build_participant_timeline
from src.calculator.pipeline import FightParams, run_fight
from src.calculator.scenario import ChampionLoadout
from src.calculator.stats import calculate_total_stats
from src.calculator.survival.actions import SUPPORT_RANK_KEY, TransitionRank
from src.calculator.timeline_coverage import (
    EXPLICIT_APPLICABILITY_EXCLUSION_SOURCES,
    applicability_exclusion_sources,
)
from tests.survival_probe import simulate_survival

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stats(*, is_melee: bool = False, bonus_ad: float = 0.0) -> dict:
    return {
        "ability_haste": 0.0,
        "armor_penetration_bonus_percent": 0.0,
        "basic_ability_haste": 0.0,
        "bonus_health": 0.0,
        "bonus_mana": 0.0,
        "health": 0.0,
        "lethality": 0.0,
        "max_mana": 0.0,
        "move_speed": 0.0,
        "omnivamp_percent": 0.0,
        "resource_regen_per_second": 0.0,
        "ultimate_haste": 0.0,
        "attack_damage": 100.0 + bonus_ad,
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
        "bonus_attack_damage": bonus_ad,
    }


def _ability(
    name: str, cooldown: float = 5.0, time_offset: float | None = None
) -> dict:
    return {
        "name": name,
        "rank": 1,
        "cooldown": cooldown,
        "physical_damage": 100.0,
        "parts": (DamagePart("physical", 100.0, time_offset=time_offset),),
        "total_raw": 100.0,
        "damage_type": "physical",
    }


def _fight(
    stats: dict,
    abilities: dict,
    *,
    duration: float,
    score_only: bool = False,
    **kwargs,
) -> dict:
    kwargs.setdefault("auto_attack_uptime", 0.0)
    return calculate_fight_damage(
        stats,
        abilities,
        [{"name": "Eclipse"}],
        FightConfig(
            target_health=2000.0,
            target_armor=0.0,
            target_magic_resistance=0.0,
            fight_duration_seconds=duration,
            **kwargs,
        ),
        score_only=score_only,
    )


def _eclipse_proc():
    """Eclipse's cast-triggered proc, resolved through its own rule.

    MERGE: the proc families left ``BuildDamageEffects`` -- a projection
    field that defaulted to an empty tuple would price a whole family at
    zero with nothing saying so -- so they come off their interpreter.
    """
    return next(
        proc
        for proc in cast_proc.resolve_slots(
            ("Eclipse",),
            facts=FightFacts(
                level=11,
                fight_duration_seconds=5.0,
                target_bonus_health=0.0,
                holder_is_melee=True,
            ),
        ).cooldown_procs
        if proc.source.item_name == "Eclipse"
    )


def _eclipse_gate():
    """The typed, source-backed Eclipse pair gate (parser-owned values)."""
    return eclipse_trigger_gate(_eclipse_proc())


def _ziggs_params(*, duration: float = 4.0, ranks: dict | None = None) -> FightParams:
    """The deterministic Ziggs fight params used by every timeline build."""
    ranks = ranks or {"Q": 1, "W": 1, "E": 1}
    return FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": duration,
            "rotations": 1,
            "include_auto_attacks": False,
            "auto_attack_uptime": 0,
            "ability_ranks": ranks,
            "role": "mid",
            "role_quest_complete": True,
        },
        deterministic=True,
    )


def _ziggs_timeline(*, duration: float = 4.0, ranks: dict | None = None) -> dict:
    """One coupled participant-timeline build: Ziggs holds Eclipse."""
    main = _load_public_champion("Ziggs")
    item = get_item_by_name("Eclipse")
    params = _ziggs_params(duration=duration, ranks=ranks)
    enemy = ChampionLoadout(champion="Aatrox", level=18, items=()).resolve()
    stats = calculate_total_stats(main, 12, [item])
    return build_participant_timeline(
        main,
        12,
        [item],
        params,
        main_stats=stats,
        main_defenses=resolve_starting_defenses("Ziggs", 12, stats, [item]),
        enemies=[enemy],
        allies=[],
    )


def _proc_event_id(result: dict) -> str:
    """The public event id of the proc_Eclipse damage event."""
    proc_events = [
        event
        for event in result["events"]
        if event.get("source") == "proc_Eclipse" and event.get("event_id")
    ]
    assert len(proc_events) == 1
    return str(proc_events[0]["event_id"])


def _dummy_combatant(
    participant_id: str, team: str, health: float = 1000.0
) -> Combatant:
    defenses = StartingDefenses(
        magic_shield=0.0,
        physical_shield=0.0,
        general_shield=0.0,
        healing_received_multiplier=1.0,
    )
    return Combatant(
        participant_id=participant_id,
        team=team,
        champion_data={"name": participant_id},
        level=1,
        items=(),
        stats={"health": health},
        defenses=defenses,
    )


def _eclipse_support_event(
    *, time: float = 1.0, amount: float = 50.0, duration: float = 2.0
) -> dict:
    """The internal support packet shape the builder emits for a proc."""
    return {
        "time": time,
        "kind": "shield",
        "amount": amount,
        "duration": duration,
        "attacker": "source",
        "target": "source",
        "source": "Eclipse (Ever Rising Moon)",
        "_event_id": "proc:shield",
        "_trigger_event_id": "proc",
        SUPPORT_RANK_KEY: TransitionRank.LATE_BARRIER,
    }


def _hit(time: float, damage: float, event_id: str = "h1") -> dict:
    return {
        "time": time,
        "damage": damage,
        "damage_type": "true",
        "attacker": "target",
        "target": "source",
        "sequence": 0,
        "_event_id": event_id,
    }


def _survival(
    hits: list[dict],
    *,
    with_trigger: bool = True,
    shield_time: float = 1.0,
    amount: float = 50.0,
    duration: float = 2.0,
) -> dict:
    """Run the survival kernel with one Eclipse-shaped shield packet.

    The shield arms only when its ``_trigger_event_id`` ("proc") is present
    in the incoming stream — the walk's trigger-linkage gate — so the
    harness always authors the matching proc packet on the other
    participant unless ``with_trigger=False``.
    """
    support = {
        "source": [
            _eclipse_support_event(time=shield_time, amount=amount, duration=duration)
        ]
    }
    incoming = {"source": hits}
    if with_trigger:
        incoming["target"] = [
            {
                "time": shield_time,
                "damage": 1.0,
                "damage_type": "true",
                "attacker": "source",
                "target": "target",
                "sequence": 0,
                "_event_id": "proc",
            }
        ]
    result = simulate_survival(
        [_dummy_combatant("source", "main"), _dummy_combatant("target", "enemy")],
        incoming,
        {},
        support,
        4.0,
    )
    return result["source"]


# ---------------------------------------------------------------------------
# 1. Typed / source-backed contract
# ---------------------------------------------------------------------------


class TestTypedContract:
    def test_typed_accessor_values_match_expected_constants(self) -> None:
        assert required_effect_value("Eclipse", "target_max_hp_ratio_melee") == 0.08
        assert required_effect_value("Eclipse", "target_max_hp_ratio_ranged") == 0.05
        assert required_effect_value("Eclipse", "stack_required") == 2
        assert required_effect_value("Eclipse", "stack_window") == 2.0
        assert required_effect_value("Eclipse", "cooldown") == 6.0
        assert required_effect_value("Eclipse", "shield_melee_base") == 150.0
        assert required_effect_value("Eclipse", "shield_ranged_base") == 75.0
        assert required_effect_value("Eclipse", "shield_melee_bonus_ad_ratio") == 0.40
        assert required_effect_value("Eclipse", "shield_ranged_bonus_ad_ratio") == 0.20
        assert required_effect_value("Eclipse", "shield_duration") == 2.0

    def test_missing_typed_key_fails_loud_naming_item_and_key(self) -> None:
        with pytest.raises(KeyError, match=r"Eclipse.*shield_missing_key_3c"):
            required_effect_value("Eclipse", "shield_missing_key_3c")

    def test_trigger_gate_rule_is_typed_and_source_backed(self) -> None:
        rule = _eclipse_gate().rule
        assert rule.stacks_required == 2
        assert rule.window_seconds == 2.0
        assert rule.cooldown_seconds == 6.0
        assert rule.per_target is True
        assert rule.source is not None
        assert rule.source.url.endswith("/Eclipse")


# ---------------------------------------------------------------------------
# 2. Stack gain: pair within 2s, third-hit skip, window lapse
# ---------------------------------------------------------------------------


class TestStackGain:
    def test_two_distinct_damaging_casts_complete_one_pair(self) -> None:
        # Q's authored hit (0.3) and W's cast boundary (0.0): the pair lands
        # at the LATER hit, still inside the 2s window.
        fight = _fight(
            _stats(),
            {"Q": _ability("Q", time_offset=0.3), "W": _ability("W")},
            duration=1.0,
            one_rotation=True,
        )
        row = fight["breakdown"]["proc_Eclipse"]
        assert row["count"] == 1
        assert row["damage_events"] == [
            {
                "time": 0.3,
                "damage": 100.0,
                "damage_type": "physical",
                "event_precision": "hit",
                "target_id": "target:0",
                # The retired family's declaration rides its own packet:
                # (mechanic_id, pre-mitigation magnitude, attack class).
                "declared": ("eclipse.proc", 100.0, "other", None, None, None),
            }
        ]

    def test_third_hit_inside_window_does_not_create_second_pair(self) -> None:
        # Q and W pair at t=0; E's authored hit at 0.5 is still inside the
        # 2s window but the per-target cooldown has started, so it is
        # receipted as trigger_skipped, not as a new pair.
        fight = _fight(
            _stats(),
            {
                "Q": _ability("Q"),
                "W": _ability("W"),
                "E": _ability("E", time_offset=0.5),
            },
            duration=1.0,
            one_rotation=True,
        )
        row = fight["breakdown"]["proc_Eclipse"]
        assert row["count"] == 1
        assert len(row["damage_events"]) == 1
        kinds = [t["kind"] for t in row["state_transitions"]["transitions"]]
        assert kinds == ["gain", "proc", "cooldown_start", "trigger_skipped"]
        skipped = row["state_transitions"]["transitions"][-1]["detail"]
        assert skipped["reason"] == "per_target_cooldown"
        assert skipped["cooldown_until"] == pytest.approx(6.0)

    def test_window_lapse_restarts_window_engine_level(self) -> None:
        # W's authored hit at 2.5 is more than 2s after Q's hit at 0: the
        # first stack expires and no pair completes (no proc row), then a
        # later E hit at 3.0 pairs with W inside a fresh window.
        fight = _fight(
            _stats(),
            {
                "Q": _ability("Q"),
                "W": _ability("W", time_offset=2.5),
                "E": _ability("E", time_offset=3.0),
            },
            duration=4.0,
            one_rotation=True,
        )
        row = fight["breakdown"]["proc_Eclipse"]
        assert row["damage_events"] == [
            {
                "time": 3.0,
                "damage": 100.0,
                "damage_type": "physical",
                "event_precision": "hit",
                "target_id": "target:0",
                # The retired family's declaration rides its own packet:
                # (mechanic_id, pre-mitigation magnitude, attack class).
                "declared": ("eclipse.proc", 100.0, "other", None, None, None),
            }
        ]

    def test_window_lapse_alone_authors_no_proc_row(self) -> None:
        # Q at 0, W at 2.5: no pair ever completes, so the engine authors
        # no proc row (and no aggregate substitute).
        fight = _fight(
            _stats(),
            {"Q": _ability("Q"), "W": _ability("W", time_offset=2.5)},
            duration=3.0,
            one_rotation=True,
        )
        assert "proc_Eclipse" not in fight["breakdown"]

    def test_window_lapse_transitions_kernel_level(self) -> None:
        gate = _eclipse_gate()
        assert gate.feed(0.0, sequence=0) == []
        assert gate.feed(2.5, sequence=1) == []  # lapse: expire + restart
        procs = gate.feed(3.0, sequence=2)
        assert len(procs) == 1
        assert procs[0].time == 3.0
        kinds = [t.kind for t in gate.timeline.transitions()]
        assert kinds == ["gain", "expire", "gain", "proc", "cooldown_start"]
        expiry = gate.timeline.transitions()[1]
        assert expiry.detail["reason"] == "window_lapse"
        assert expiry.detail["expires_at"] == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# 3. Proc threshold / trigger timing
# ---------------------------------------------------------------------------


class TestTriggerTiming:
    def test_pair_lands_at_second_hit_timestamp(self) -> None:
        # W (cast boundary, t=0) then Q (authored hit, t=0.3): the pair
        # event rides the SECOND hit's time and precision.
        fight = _fight(
            _stats(),
            {"Q": _ability("Q", time_offset=0.3), "W": _ability("W")},
            duration=1.0,
            one_rotation=True,
        )
        event = fight["breakdown"]["proc_Eclipse"]["damage_events"][0]
        assert event["time"] == 0.3
        assert event["event_precision"] == "hit"

    def test_two_casts_at_same_time_complete_one_pair_at_zero(self) -> None:
        fight = _fight(
            _stats(),
            {"Q": _ability("Q"), "W": _ability("W")},
            duration=1.0,
            one_rotation=True,
        )
        row = fight["breakdown"]["proc_Eclipse"]
        assert row["count"] == 1
        assert row["damage_events"][0]["time"] == 0.0
        assert row["damage_events"][0]["event_precision"] == "exact"
        proc = row["state_transitions"]["procs"][0]
        # The proc is sequenced on the SECOND trigger of the same instant.
        assert proc == {
            "time": 0.0,
            "sequence": 1,
            "precision": "exact",
            "target": "target:0",
        }

    def test_kernel_proc_precision_propagates_from_feed(self) -> None:
        gate = _eclipse_gate()
        gate.feed(0.0, sequence=0, precision="exact")
        procs = gate.feed(0.5, sequence=1, precision="hit")
        assert len(procs) == 1
        assert procs[0].time == 0.5
        assert procs[0].precision == "hit"
        assert procs[0].sequence == 1

    def test_shield_rides_each_proc_event_at_the_same_time(self) -> None:
        # Two completed pairs author two damage events and two self-shield
        # entries, each aligned to its own proc event (ledger payload).
        fight = _fight(
            _stats(),
            {"Q": _ability("Q", cooldown=1.0), "W": _ability("W", cooldown=5.0)},
            duration=7.0,
            one_rotation=False,
        )
        row = fight["breakdown"]["proc_Eclipse"]
        assert len(row["damage_events"]) == 2
        assert len(row["self_shield_events"]) == 2
        ledger = [
            event
            for event in fight["damage_events"]
            if event.get("source_key") == "proc_Eclipse"
        ]
        assert [event["time"] for event in ledger] == [0.0, 7.0]
        assert all(event["self_shield"]["amount"] == 75.0 for event in ledger)
        assert all(event["self_shield"]["duration"] == 2.0 for event in ledger)
        # This rider states no re-bind: Ever Rising Moon arms on the proc
        # event it rides, so a blocked proc is a shield the fight did not
        # earn.  Only ``slotlib.attach_self_shield`` declares the ability-hit
        # re-bind the walk applies (``transitions._rebind_self_shields``).
        assert all(
            "rebind_on_ability_hit" not in event["self_shield"] for event in ledger
        )


# ---------------------------------------------------------------------------
# 4. Per-target cooldown: denied before 6, inclusive at 6, per-target clocks
# ---------------------------------------------------------------------------


class TestPerTargetCooldown:
    def test_qualifying_pair_before_six_is_denied_engine_level(self) -> None:
        # W recasts at 5.0 (inside the cooldown): the second pair can never
        # complete before 6, so only the t=0 proc fires and every later
        # trigger carries the per_target_cooldown skip receipt.
        fight = _fight(
            _stats(),
            {"Q": _ability("Q", cooldown=1.0), "W": _ability("W", cooldown=5.0)},
            duration=5.9,
            one_rotation=False,
        )
        row = fight["breakdown"]["proc_Eclipse"]
        assert [event["time"] for event in row["damage_events"]] == [0.0]
        skips = [
            t
            for t in row["state_transitions"]["transitions"]
            if t["kind"] == "trigger_skipped"
        ]
        assert skips
        assert all(t["detail"]["reason"] == "per_target_cooldown" for t in skips)
        assert all(t["detail"]["cooldown_until"] == pytest.approx(6.0) for t in skips)

    def test_exactly_six_is_inclusive_engine_level(self) -> None:
        # W recasts at 3 and 6: the W hit at exactly 6.0 (cooldown_until)
        # pairs with the Q hit at 6.0 — inclusive boundary.
        fight = _fight(
            _stats(),
            {"Q": _ability("Q", cooldown=1.0), "W": _ability("W", cooldown=3.0)},
            duration=7.0,
            one_rotation=False,
        )
        row = fight["breakdown"]["proc_Eclipse"]
        assert [event["time"] for event in row["damage_events"]] == [0.0, 6.0]

    def test_kernel_per_target_clocks_are_independent(self) -> None:
        gate = _eclipse_gate()
        gate.feed(0.0, sequence=0, target="A")
        assert [p.time for p in gate.feed(0.5, sequence=1, target="A")] == [0.5]
        # B's clock is untouched: a pair at 1.5 procs immediately.
        gate.feed(1.0, sequence=2, target="B")
        assert [p.time for p in gate.feed(1.5, sequence=3, target="B")] == [1.5]
        # A is denied at 5.0 / 5.5 and even exactly 6.0 (its cooldown_until
        # is 6.5, set by the 0.5 proc).
        for t in (5.0, 5.5, 6.0):
            assert gate.feed(t, sequence=4, target="A") == []
        skips = [
            t
            for t in gate.timeline.transitions()
            if t.kind == "trigger_skipped" and t.detail["target"] == "A"
        ]
        assert len(skips) == 3
        assert all(t.detail["reason"] == "per_target_cooldown" for t in skips)
        assert all(t.detail["cooldown_until"] == pytest.approx(6.5) for t in skips)
        # A re-arms at exactly 6.5 and completes a pair at 7.0.
        gate.feed(6.5, sequence=5, target="A")
        assert [p.time for p in gate.feed(7.0, sequence=6, target="A")] == [7.0]

    def test_engine_uses_the_one_v_one_target_identity(self) -> None:
        fight = _fight(
            _stats(),
            {"Q": _ability("Q"), "W": _ability("W")},
            duration=1.0,
            one_rotation=True,
        )
        row = fight["breakdown"]["proc_Eclipse"]
        # The cast receipt identifies the selected 1v1 target.  The same
        # identity keys the per-target cooldown receipt.
        assert row["state_transitions"]["procs"] == [
            {
                "time": 0.0,
                "sequence": 1,
                "precision": "exact",
                "target": "target:0",
            }
        ]
        assert row["state_transitions"]["rule"]["per_target"] is True


# ---------------------------------------------------------------------------
# 5. Shield packet: amount, duration, scope, one per pair, survival order
# ---------------------------------------------------------------------------


class TestShieldPacket:
    def test_melee_and_ranged_shield_amounts_with_bonus_ad(self) -> None:
        for is_melee, expected in ((True, 176.0), (False, 88.0)):
            fight = _fight(
                _stats(is_melee=is_melee, bonus_ad=65.0),
                {"Q": _ability("Q"), "W": _ability("W")},
                duration=1.0,
                one_rotation=True,
            )
            row = fight["breakdown"]["proc_Eclipse"]
            assert row["self_shield_events"] == [
                {
                    "amount": expected,
                    "duration": 2.0,
                    "source": "Eclipse (Ever Rising Moon)",
                    # P3-3C: the shield receipt carries the pair event's
                    # time and precision.
                    "time": 0.0,
                    "event_precision": "exact",
                }
            ]

    def test_exactly_one_shield_entry_per_completed_pair(self) -> None:
        fight = _fight(
            _stats(),
            {"Q": _ability("Q", cooldown=1.0), "W": _ability("W", cooldown=5.0)},
            duration=7.0,
            one_rotation=False,
        )
        row = fight["breakdown"]["proc_Eclipse"]
        assert row["count"] == 2
        assert len(row["damage_events"]) == 2
        assert len(row["self_shield_events"]) == 2

    def test_participant_support_event_links_to_the_proc_event(self) -> None:
        result = _ziggs_timeline()
        shields = [
            event
            for event in result["support_events"]
            if event.get("kind") == "shield"
            and event.get("source") == "Eclipse (Ever Rising Moon)"
        ]
        assert len(shields) == 1  # one completed pair -> exactly one packet
        shield = shields[0]
        proc_id = _proc_event_id(result)
        proc_event = next(
            event for event in result["events"] if event.get("source") == "proc_Eclipse"
        )
        assert shield["time"] == pytest.approx(proc_event["time"])
        assert shield["trigger_event_id"] == proc_id
        assert shield["event_id"] == f"{proc_id}:shield"
        assert shield["target_scope"] == "self"
        assert shield["target_policy"] == "self"
        assert shield["duration"] == 2.0
        # The amount is the typed formula priced at the fight engine's own
        # bonus AD (the timeline recomputes stats with the role quest, so
        # re-derive the expectation from the same fight, not from the raw
        # loadout stats).
        engine = run_fight(
            _load_public_champion("Ziggs"),
            12,
            [get_item_by_name("Eclipse")],
            _ziggs_params(),
        )
        expected = engine["breakdown"]["proc_Eclipse"]["self_shield_events"][0][
            "amount"
        ]
        assert expected == pytest.approx(
            75.0 + 0.20 * float(engine["champion_stats"]["bonus_attack_damage"])
        )
        assert shield["amount"] == pytest.approx(expected)
        assert shield["expires_at"] == pytest.approx(float(proc_event["time"]) + 2.0)

    def test_internal_support_event_priority_and_trigger_link(
        self, monkeypatch
    ) -> None:
        captured: list[dict] = []
        real = participant_timeline._simulate_survival

        def capture(combatants, incoming, healing, support_effects, duration, **kwargs):
            for events in support_effects.values():
                captured.extend(dict(event) for event in events)
            return real(
                combatants, incoming, healing, support_effects, duration, **kwargs
            )

        monkeypatch.setattr(participant_timeline, "_simulate_survival", capture)
        result = _ziggs_timeline()
        shield = [
            event
            for event in captured
            if event.get("kind") == "shield"
            and event.get("source_key") == "shield_Eclipse"
        ]
        assert len(shield) == 1
        shield = shield[0]
        proc_id = _proc_event_id(result)
        # MERGE: the retired float priority 0.5 is the declared
        # ``LATE_BARRIER`` rank - a barrier placed AFTER the damage that
        # triggered it, which is the same statement the number made.
        assert shield[SUPPORT_RANK_KEY] is TransitionRank.LATE_BARRIER
        assert shield["_trigger_event_id"] == proc_id
        assert shield["_event_id"] == f"{proc_id}:shield"
        assert shield["target_scope"] == "self"
        assert shield["time"] == pytest.approx(
            float(
                next(
                    event
                    for event in result["events"]
                    if event.get("source") == "proc_Eclipse"
                )["time"]
            )
        )

    def test_survival_receives_absorbs_expires_in_order(self) -> None:
        # In-window hit larger than the shield: absorbed up to the shield,
        # the remainder passes to health, nothing expires unused.
        state = _survival([_hit(2.0, 80.0)])
        assert state["support_shield_received"] == pytest.approx(50.0)
        assert state["shield_absorbed"] == pytest.approx(50.0)
        assert state["health_damage"] == pytest.approx(30.0)
        assert state["support_shield_expired"] == pytest.approx(0.0)
        # In-window hit smaller than the shield: fully absorbed, the
        # leftover shield expires at time + duration.
        state = _survival([_hit(2.0, 30.0)])
        assert state["support_shield_received"] == pytest.approx(50.0)
        assert state["shield_absorbed"] == pytest.approx(30.0)
        assert state["health_damage"] == pytest.approx(0.0)
        assert state["support_shield_expired"] == pytest.approx(20.0)

    def test_survival_expiry_boundary_is_exclusive_and_same_time_is_damage_first(
        self,
    ) -> None:
        # A hit at exactly time + duration (3.0) is NOT absorbed: the timed
        # shield ends before the boundary (expired in full).
        state = _survival([_hit(3.0, 80.0)])
        assert state["shield_absorbed"] == pytest.approx(0.0)
        assert state["health_damage"] == pytest.approx(80.0)
        assert state["support_shield_expired"] == pytest.approx(50.0)
        # A hit at the shield's own timestamp resolves BEFORE the shield
        # arms: the declared ``LATE_BARRIER`` sorts after ``DAMAGE`` at
        # the same time.  Pinned observable — the proc damage
        # and its shield are same-time but the shield does not intercept
        # the proc's own damage.
        state = _survival([_hit(1.0, 80.0)])
        assert state["shield_absorbed"] == pytest.approx(0.0)
        assert state["health_damage"] == pytest.approx(80.0)
        assert state["support_shield_received"] == pytest.approx(50.0)
        assert state["support_shield_expired"] == pytest.approx(50.0)

    def test_survival_skips_shield_without_its_trigger_event(self) -> None:
        # Fail-closed trigger linkage: the shield packet carries
        # ``_trigger_event_id`` and is skipped when no incoming event with
        # that id is present in the fight stream.
        state = _survival([_hit(2.0, 80.0)], with_trigger=False)
        assert state["support_shield_received"] == pytest.approx(0.0)
        assert state["shield_absorbed"] == pytest.approx(0.0)
        assert state["health_damage"] == pytest.approx(80.0)


# ---------------------------------------------------------------------------
# 6. Score / receipt / optimizer / public parity
# ---------------------------------------------------------------------------


class TestParityAndOptimizer:
    def test_score_only_fight_matches_receipt_fight(self) -> None:
        abilities = {
            "Q": _ability("Q", cooldown=1.0),
            "W": _ability("W", cooldown=5.0),
        }
        receipt = _fight(_stats(), abilities, duration=7.0, one_rotation=False)
        score = _fight(
            _stats(), abilities, duration=7.0, one_rotation=False, score_only=True
        )
        left = receipt["breakdown"]["proc_Eclipse"]
        right = score["breakdown"]["proc_Eclipse"]
        assert right["count"] == left["count"] == 2
        assert right["damage_events"] == left["damage_events"]
        assert right["total_damage"] == left["total_damage"]
        assert right["self_shield_events"] == left["self_shield_events"]
        assert right["state_transitions"] == left["state_transitions"]

    def test_optimizer_exclusion_source_receipt_at_low_altitude(self) -> None:
        assert "proc_Eclipse" in EXPLICIT_APPLICABILITY_EXCLUSION_SOURCES
        # A candidate whose ONLY coarse source is proc_Eclipse is eligible
        # for the applicability exclusion (the optimizer's
        # ``excluded_sources`` receipt).
        assert applicability_exclusion_sources(
            {"coarse_sources": ["proc_Eclipse"]}
        ) == ["proc_Eclipse"]
        # Mixing an un-audited coarse source must NOT be rescued.
        assert (
            applicability_exclusion_sources(
                {"coarse_sources": ["proc_Eclipse", "periodic_Unending Despair"]}
            )
            == []
        )
        # Exact-only coverage has nothing to exclude.
        assert applicability_exclusion_sources({"coarse_sources": []}) == []

    def test_compiled_score_walk_fails_closed_with_named_receipt(self) -> None:
        assert isinstance(
            compilability_for("Eclipse", ReceiptScope.SURVIVAL_LEDGER_TRANSITION),
            ReceiptOnly,
        )
        assert uncompilable_item_receipt([{"name": "Eclipse"}]) == (
            "item_mechanic=Eclipse"
        )
        assert uncompilable_item_receipt([]) is None


# ---------------------------------------------------------------------------
# 7. Missing / ambiguous metadata fails closed
# ---------------------------------------------------------------------------


class TestFailClosedMetadata:
    def test_non_finite_hit_time_withholds_proc_event_precision(self) -> None:
        # A malformed hit ledger (non-finite authored hit time) makes the
        # stack walk return None: the row keeps a duration-scaled coarse
        # price but authors no damage events, no shield, and no kernel
        # receipt; the coverage goes coarse.
        fight = _fight(
            _stats(),
            {
                "Q": _ability("Q", time_offset=float("nan")),
                "W": _ability("W", time_offset=float("nan")),
            },
            duration=3.0,
            one_rotation=True,
        )
        row = fight["breakdown"]["proc_Eclipse"]
        assert row["count"] == 1  # 1 + int(3 / 6), the preserved aggregate
        assert row["total_damage"] == pytest.approx(100.0)
        assert "damage_events" not in row
        assert "self_shield_events" not in row
        assert "state_transitions" not in row
        coverage = fight["timeline_coverage"]
        assert coverage["complete"] is False
        assert "proc_Eclipse" in coverage["coarse_sources"]

    def test_missing_slot_branch_withholds_proc_event_precision(
        self, monkeypatch
    ) -> None:
        # The missing-slot / non-mapping cast-event branch returns None
        # exactly like the non-finite time branch; pin the caller's
        # withheld handling through that branch.
        monkeypatch.setattr(
            "src.calculator.damage._stacked_champion_proc_times",
            lambda *args, **kwargs: None,
        )
        fight = _fight(
            _stats(),
            {"Q": _ability("Q"), "W": _ability("W")},
            duration=3.0,
            one_rotation=True,
        )
        row = fight["breakdown"]["proc_Eclipse"]
        assert row["count"] == 1
        assert "damage_events" not in row
        assert "self_shield_events" not in row
        assert "state_transitions" not in row
        assert "proc_Eclipse" in fight["timeline_coverage"]["coarse_sources"]

    def test_malformed_proc_row_names_the_withheld_reason(self) -> None:
        # P3-3C contract: a malformed proc ledger (non-finite hit time)
        # keeps its duration-scaled coarse price but the row is stamped
        # with a NAMED withheld reason and the shield loss is receipted —
        # callers can distinguish a malformed ledger from a passive that
        # never fired without re-deriving the coverage.
        fight = _fight(
            _stats(),
            {"Q": _ability("Q", time_offset=float("nan"))},
            duration=3.0,
            one_rotation=True,
        )
        row = fight["breakdown"]["proc_Eclipse"]
        assert row["withheld_reason"] == "malformed_proc_receipt"
        assert row["event_phase"] == "coarse"
        assert (
            row["shield_withheld_reason"]
            == "self_shield_attached_only_to_certified_proc_events"
        )
        assert "self_shield_events" not in row
        assert "state_transitions" not in row

    def test_non_numeric_shield_amount_produces_no_packet(self, monkeypatch) -> None:
        result = _ziggs_timeline_with_broken_shield(
            monkeypatch, {"amount": "not-a-number", "duration": 2.0}
        )
        shields = [
            event for event in result["support_events"] if event.get("kind") == "shield"
        ]
        assert shields == []
        survival = result["participants"][0]["survival"]
        assert survival["support_shield_received"] == pytest.approx(0.0)
        assert survival["health_damage"] > 0.0  # damage still flows

    def test_non_numeric_shield_duration_produces_no_packet(self, monkeypatch) -> None:
        result = _ziggs_timeline_with_broken_shield(
            monkeypatch, {"amount": 93.0, "duration": "two-seconds"}
        )
        shields = [
            event for event in result["support_events"] if event.get("kind") == "shield"
        ]
        assert shields == []
        survival = result["participants"][0]["survival"]
        assert survival["support_shield_received"] == pytest.approx(0.0)

    def test_unreadable_shield_payload_is_receipted_not_silent(
        self, monkeypatch
    ) -> None:
        # P3-3C: an unreadable self_shield payload drops the shield but the
        # loss is a NAMED denial receipt in the timeline's public section.
        result = _ziggs_timeline_with_broken_shield(
            monkeypatch, {"amount": "not-a-number", "duration": 2.0}
        )
        denials = [
            row
            for row in result["item_denial_receipts"]
            if row["source"] == "Eclipse (Ever Rising Moon)"
        ]
        assert len(denials) == 1
        assert denials[0]["reason"] == "self_shield_payload_unreadable"
        assert denials[0]["time"] > 0.0


# ---------------------------------------------------------------------------
# 8. Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_identical_fights_produce_identical_full_receipts(self) -> None:
        abilities = {
            "Q": _ability("Q", cooldown=1.0),
            "W": _ability("W", cooldown=5.0),
        }
        first = _fight(_stats(), abilities, duration=7.0, one_rotation=False)
        second = _fight(_stats(), abilities, duration=7.0, one_rotation=False)
        assert first["breakdown"]["proc_Eclipse"] == second["breakdown"]["proc_Eclipse"]
        assert (
            first["breakdown"]["proc_Eclipse"]["state_transitions"]
            == second["breakdown"]["proc_Eclipse"]["state_transitions"]
        )

    def test_identical_kernel_feed_sequences_produce_identical_receipts(
        self,
    ) -> None:
        def run() -> dict:
            gate = _eclipse_gate()
            gate.feed(0.0, sequence=0)
            gate.feed(0.5, sequence=1)
            gate.feed(7.0, sequence=2)
            gate.feed(7.5, sequence=3)
            return gate.public_receipt()

        assert run() == run()

    def test_no_duplicate_damage_events_per_completed_pair(self) -> None:
        # Three hits, one pair: exactly one damage event.
        fight = _fight(
            _stats(),
            {
                "Q": _ability("Q"),
                "W": _ability("W"),
                "E": _ability("E", time_offset=0.5),
            },
            duration=1.0,
            one_rotation=True,
        )
        row = fight["breakdown"]["proc_Eclipse"]
        assert len(row["damage_events"]) == 1
        # Two pairs: exactly two events at distinct times.
        fight = _fight(
            _stats(),
            {"Q": _ability("Q", cooldown=1.0), "W": _ability("W", cooldown=5.0)},
            duration=7.0,
            one_rotation=False,
        )
        row = fight["breakdown"]["proc_Eclipse"]
        times = [event["time"] for event in row["damage_events"]]
        assert times == [0.0, 7.0]
        assert len(set(times)) == len(times)
        assert len(row["self_shield_events"]) == len(times)


# ---------------------------------------------------------------------------
# Broken-self-shield harness (fail-closed payload conversion)
# ---------------------------------------------------------------------------


def _ziggs_timeline_with_broken_shield(monkeypatch, payload: dict) -> dict:
    """Build the Ziggs timeline with a malformed ``self_shield`` payload.

    The participant timeline converts each damage event's ``self_shield``
    payload into a support packet; a non-numeric amount/duration must fail
    closed (no shield packet) instead of guessing a number.
    """
    real = participant_timeline.run_fight

    def wrapper(champion_data, level, items, fparams, **kwargs):
        result = real(champion_data, level, items, fparams, **kwargs)
        if any(item.get("name") == "Eclipse" for item in items):
            for event in result.get("damage_events", []):
                if event.get("source_key") == "proc_Eclipse" and "self_shield" in event:
                    event["self_shield"] = payload
        return result

    monkeypatch.setattr(participant_timeline, "run_fight", wrapper)
    return _ziggs_timeline()
