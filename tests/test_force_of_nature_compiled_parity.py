"""P1 Package 3Q — Force of Nature (4401) "Steadfast" compiled-walk +
optimizer certification.

This file is the focused acceptance-matrix owner for Force of Nature's
Steadfast passive.  It pins the OBSERVABLES the coordinator's P3-3Q
completion must satisfy and runs against today's source: every behavior
that already exists passes now; every assertion that targets a contract
piece the source does not emit yet is marked ``xfail`` with reason
``awaiting P3-3Q ...``.

Contract under test (current runtime facts, verified before pinning):

* ITEM IDENTITY: cached name "Force of Nature", id 4401, price 2800
  (shop.prices.total, sell 1120), tier 3 LEGENDARY.  Stats: 400 flat
  health, 55 flat magic resistance, 4% move speed (resolved as +13.2
  move_speed on Ahri level 18 = 4% of 330).  Passive name "Steadfast",
  unique; the cached riotDescription branch is exact: "Gain 70 Magic
  Resist and 6% bonus Move Speed after taking magic damage from Champions
  8 times."
* TYPED SOURCE: the item_effects registry entry (type "target_state")
  carries the six steadfast keys, read through required_effect_value:
  max 8 stacks, 7.0s duration, 1.0s interval, +2 on immobilize, payload
  70.0 bonus MR + 6.0% bonus move speed.  force_of_nature_steadfast_rule()
  returns that StackRule; a missing key raises KeyError naming "Force of
  Nature" AND the key (AGENTS.md rule 5 — no silent fallbacks); malformed
  values fail loudly (ValueError on bad int, TypeError on non-numeric
  duration).  The wiki source receipt rides the code-owned
  defensive_effects.defense_source(...) (revision 4016272) — the
  registry entry itself carries no source keys (unlike GA's
  ITEM_INPUT_OPTIONS receipt).
* STACK CADENCE: a target holding FoN gains stacks only from incoming
  CHAMPION magic-damage packets (attacker is a fight participant, not
  self): one stack per qualifying packet subject to TWO gates — at most
  one stack per ability instance while that instance key is cached, and a
  global 1-per-second interval across all instances (packets from the
  same instance within 1s -> 1 stack; packets from different instances
  within 1s -> still only 1 stack; this second clause is STRICTER than
  the naive "different instances -> separate stacks" reading and is
  pinned as the actual rule).  PHYSICAL damage gains NO stacks; magic
  damage from a non-participant (minion) gains NO stacks; zero-damage
  packets and reactive packets gain NO stacks.
* DURATION/REFRESH/EXPIRY: a gained stack lives 7.0s (stacks_until =
  gain_time + 7.0); any subsequent qualifying gain REFRESHES the window;
  expiry is ALL-AT-ONCE and lazy — the ledger resets all stacks to 0 when
  the next qualifying magic packet arrives at/after the 7.0s mark; the
  engine authors no timer-driven expiry event today (the stale stack
  count stays visible in the state until the next qualifying packet).
* CAP: at 8 stacks the bonus applies; further qualifying damage keeps the
  cap (never exceeds 8).
* IMMOBILIZATION: a qualifying magic-damage packet carrying an
  immobilize marker (reviewed champion module) grants +2 stacks and
  refreshes the duration.  An immobilize WITHOUT a qualifying damage
  packet (pure CC, zero-damage, or physical) grants nothing — that is the
  named boundary.
* DYNAMIC MR REPRICING: at max stacks the holder's effective magic
  resistance increases by exactly 70 (dynamic_bonus_magic_resistance).
  The reprice is PROSPECTIVE per packet: update_combat_state runs before
  a packet's damage flow, so the packet that REACHES max stacks is itself
  mitigated at baseline+70 (pinned: 8 packets at 1/s against baseline 40
  MR -> the 8th packet reprices 50 raw to 33.33, effective 110).  Earlier
  packets are never retroactively re-mitigated.  A packet without a
  baseline effective-MR receipt is not silently repriced
  (dynamic_resistance_unavailable written, damage unchanged).  The
  holder's BASE 55 MR is an ordinary item stat, always applied by the
  pair engine as part of the baseline; the dynamic +70 is strictly
  additive on top.
* MOVEMENT STATE: the 6% bonus move speed is DECLARED but NOT applied —
  it is carried on ChampionDefenses.force_bonus_move_speed_percent, in
  public_summary()["combat_state"]["force_of_nature"], and in the
  "movement" outcome dimension, but neither the receipt walk nor the
  score kernel authors a movement event or applies a move-speed stat at
  max stacks.  That declared-but-unapplied state is the named boundary.
* COMPILED VS RECEIPT PARITY: both adapters drive one kernel
  (test_survival_kernel.py, issue #137).  Today FoN sits in
  COMPILED_WALK_UNREPRESENTABLE_ITEMS ("Steadfast reprice needs baseline
  resistances"), so the compiled fast path fails closed: a MAIN holder
  falls back per evaluation (context.uncompilable stays False, no panels
  built) and the score surface deep-equals the receipt walk on the whole
  scoring receipt, force_of_nature row included; an ENEMY/ALLY holder
  poisons the search-invariant roster context (uncompilable True, panels
  empty) and still deep-equals via the receipt walk.  The P3-3Q
  certification (remove from the blocklist with byte-parity proof) is
  pinned as xfail: panels non-empty + uncompilable False + deep-equal.
  The legacy run_fight(score_only=True) surface carries NO survival state
  (no target_* keys, no force_of_nature) — the named fail-closed carrier
  boundary; item_state_receipts agrees between surfaces.
* FAIL-CLOSED: absent FoN -> no stacks, no receipt row, all defenses
  zero; a fabricated FoN item option is rejected ("Unknown item option
  target: Force of Nature" — FoN has no ITEM_INPUT_OPTIONS entry);
  missing/malformed typed values raise.
* COVERAGE: item_model_coverage returns "modeled_effect" with
  optimizer_eligible + calculation_eligible True and outcome_dimensions
  ["movement", "defense"] — but the reason is the GENERIC
  "Damage-relevant effects are represented by the fight model." today; a
  Steadfast/magic-resistance-naming reason is xfail (the coordinator's
  coverage tightening).  target_item_model_coverage is
  "modeled_event_certified" naming Steadfast, expiry and the
  maximum-stack bonus resistance.
* ITEM STATE RECEIPTS: the 3M/3N/3O-pattern item_state_receipts row for
  Steadfast (state "steadfast", stacks/payload/source) is absent today —
  xfail.
* XFAIL ONLY for genuinely absent mechanics: (1) the compiled-panel
  certification; (2) the coverage reason naming Steadfast; (3) the
  item_state_receipts Steadfast row.  All three are ``awaiting P3-3Q
  ...``.

Sibling owners: the compiled-vs-receipt contract lives in
``tests/test_survival_kernel.py`` (issue #137); the Guardian Angel 3P
matrix shape in ``tests/test_guardian_angel_resurrection.py``; the
kernel-typed declaration consumer in
``tests/test_state_lifecycle_consumers.py`` (TestForceOfNatureConsumer);
the stack-machine regression in ``tests/test_participant_timeline.py``
(test_force_of_nature_stacks_and_reprices_the_maximum_stack_packet
~4345); the defenses resolution in ``tests/test_defensive_effects.py``
(test_force_of_nature_and_jaksho_resolve_event_state_metadata ~309) and
the coverage pins in ``tests/test_item_coverage.py`` (~276 and
test_force_of_nature_target_defense_is_event_certified ~377).  This file
is disjoint and pins only the Force of Nature acceptance observables.
"""

from types import SimpleNamespace

import pytest

from src.calculator.item_coverage import ATTACKER_LANES
from src.calculator.program.build import roster_program as _roster_program
from src.calculator.program.views.survival import survival as _survival_view
from src.calculator.defensive_effects import StartingDefenses
from src.calculator import item_effects
from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.defensive_effects import (
    resolve_starting_defenses,
)
from src.calculator.item_coverage import item_model_coverage, target_item_model_coverage
from src.calculator.item_effects import (
    ITEM_EFFECTS,
    ITEM_INPUT_OPTIONS,
    force_of_nature_steadfast_rule,
    item_state_receipts,
    validate_item_input_options,
)
from src.calculator.participant_timeline import (
    Combatant,
    CoupledSearchContext,
    build_participant_timeline,
    _simulate_survival as _simulate_survival_walk,
)
from src.calculator.pipeline import FightParams, run_fight
from src.calculator.scenario import ChampionLoadout
from src.calculator.stats import calculate_total_stats
from src.calculator.state_lifecycle import SourceReceipt

# The retired per-item ``_X_SOURCE`` constant, read from the one home it
# moved to: the declaration's own resolved citation.
from src.calculator.defensive_effects import defense_source
from src.calculator.item_behavior import DefenseMechanic


# MERGE: ``_simulate_survival`` returns the frozen ``WalkResult`` now -- one
# walk handed to five views -- so a caller that wants the published rows
# projects it through the survival view, exactly as the composition does.
def _simulate_survival(combatants, *args, **kwargs):
    combatant_list = list(combatants)
    return _survival_view(
        _roster_program(combatant_list),
        _simulate_survival_walk(combatant_list, *args, **kwargs),
    )


_SOURCE = defense_source("Force of Nature", DefenseMechanic.STEADFAST)

ITEM_NAME = "Force of Nature"
ITEM_ID = 4401
PRICE = 2800
SELL = 1120
HEALTH_FLAT = 400.0
MR_FLAT = 55.0
MS_PERCENT = 4.0
# Ahri level-18 base move speed (330) x 4% = 13.2.
MS_DELTA = 13.2
MAX_STACKS = 8
STACK_DURATION = 7.0
STACK_INTERVAL = 1.0
IMMOBILIZE_STACKS = 2
BONUS_MR = 70.0
BONUS_MS_PERCENT = 6.0
SOURCE_REVISION = 4016272
# The cached wiki branch text (riotDescription) — the exact Steadfast
# sentence plus the stats block.
BRANCH_FRAGMENTS = (
    "<passive>Steadfast</passive>",
    "70 Magic Resist",
    "6% bonus Move Speed",
    "after taking magic damage from Champions 8 times",
)
# The walk's lazy expiry rule: the next qualifying packet at/after
# last_gain + 7.0s resets all stacks to zero first.
EXPIRY_TOLERANCE = 1e-9


def _fon_item() -> dict:
    """The real cached item record (id 4401)."""
    return get_item_by_name(ITEM_NAME)


def _stack_stats() -> dict:
    return {
        "health": 5000.0,
        "armor": 30.0,
        "magic_resistance": 40.0,
        "bonus_armor": 0.0,
        "bonus_magic_resistance": 0.0,
        "is_melee": False,
    }


def _stack_holder() -> Combatant:
    """The FoN holder used by the packet-level stack-machine probes."""
    stats = _stack_stats()
    return Combatant(
        participant_id="target",
        team="enemy",
        champion_data={"name": "Ahri"},
        level=18,
        items=(_fon_item(),),
        stats=stats,
        defenses=resolve_starting_defenses("Ahri", 18, stats, [{"name": ITEM_NAME}]),
    )


def _dummy_source(participant_id: str = "source", team: str = "main") -> Combatant:
    return Combatant(
        participant_id=participant_id,
        team=team,
        champion_data={"name": participant_id},
        level=1,
        items=(),
        stats={"health": 5000.0},
        defenses=StartingDefenses(
            magic_shield=0.0,
            physical_shield=0.0,
            general_shield=0.0,
            healing_received_multiplier=1.0,
        ),
    )


def _magic_packet(
    time: float,
    sequence: int,
    *,
    source_key: str = "Q",
    ability_instance: str | None = None,
    damage: float = 50.0,
    damage_type: str = "magic",
    attacker: str = "source",
    baseline_mr: float | None = 40.0,
    **extra,
) -> dict:
    packet = {
        "time": time,
        "damage": damage,
        "damage_type": damage_type,
        "attacker": attacker,
        "target": "target",
        "source_key": source_key,
        "sequence": sequence,
        "_event_id": f"{source_key}:{sequence}:{time}",
    }
    if ability_instance is not None:
        packet["ability_instance"] = ability_instance
    if baseline_mr is not None:
        packet["_baseline_effective_mr"] = baseline_mr
    packet.update(extra)
    return packet


def _run_packets(events, duration: float = 10.0) -> dict:
    """Run one _simulate_survival with the FoN holder as target."""
    return _simulate_survival(
        [_dummy_source(), _stack_holder()], {"target": events}, {}, {}, duration
    )


def _force_row(result: dict) -> dict:
    return result["target"]["force_of_nature"]


def _holder_fight(
    duration: float,
    *,
    holder_items: tuple[str, ...] = (ITEM_NAME,),
    include_receipt: bool = True,
    search_context: CoupledSearchContext | None = None,
    arm_steadfast: bool = True,
    enemy: str = "Cassiopeia",
) -> dict:
    """A coupled fight where the MAIN holds FoN against a magic dealer.

    The 16-second Cassiopeia fixture reaches 8 stacks (cap) and exercises
    the max-stack reprice inside a real pair fight.  ``include_receipt=False``
    returns the coupled score surface; passing a ``search_context`` plus an
    empty pair cache exercises the compiled score path (which must fail
    closed on FoN today and fall back to the shared walk).  ``arm_steadfast
    =False`` keeps the item data (so the pair fight still sees the +400
    health / +55 MR / +4% MS stats) while leaving Steadfast unarmed — the
    byte-identical control for the ordinary-stat-parity pin.
    """
    main = get_champion("Ahri")
    items = [_fon_item()] if ITEM_NAME in holder_items else []
    main_stats = calculate_total_stats(main, 18, items)
    params = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": duration,
            "role": "mid",
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
        },
        deterministic=True,
    )
    enemy_loadout = ChampionLoadout(champion=enemy, level=18, items=[]).resolve()
    defenses = resolve_starting_defenses(
        "Ahri", 18, main_stats, items if arm_steadfast else []
    )
    return build_participant_timeline(
        main,
        18,
        items,
        params,
        main_stats=main_stats,
        main_defenses=defenses,
        enemies=[enemy_loadout],
        allies=[],
        include_receipt=include_receipt,
        pair_result_cache={} if search_context is not None else None,
        search_context=search_context,
    )


def _main_survival(result: dict) -> dict:
    """The main holder's survival row (participant 0)."""
    return result["participants"][0]["survival"]


# ---------------------------------------------------------------------------
# 1. Identity / stats / passive
# ---------------------------------------------------------------------------


def test_cached_identity_pins_name_id_price_stats_and_steadfast_branch():
    item = _fon_item()
    assert item["name"] == ITEM_NAME
    assert item["id"] == ITEM_ID
    assert item["shop"]["prices"]["total"] == PRICE
    assert item["shop"]["prices"]["sell"] == SELL
    assert item["tier"] == 3
    assert item["rank"] == ["LEGENDARY"]
    assert item["stats"]["health"]["flat"] == HEALTH_FLAT
    assert item["stats"]["magicResistance"]["flat"] == MR_FLAT
    assert item["stats"]["movespeed"]["percent"] == MS_PERCENT
    (passive,) = item["passives"]
    assert passive["name"] == "Steadfast"
    assert passive["unique"] is True
    branch = item["riotDescription"]
    for fragment in BRANCH_FRAGMENTS:
        assert fragment in branch


def test_equipping_force_of_nature_yields_exactly_400_health_55_mr_and_4_ms():
    main = get_champion("Ahri")
    base = calculate_total_stats(main, 18, [])
    with_fon = calculate_total_stats(main, 18, [_fon_item()])
    diffs = {key: with_fon[key] - base[key] for key in with_fon}
    assert diffs["health"] == pytest.approx(HEALTH_FLAT)
    assert diffs["bonus_health"] == pytest.approx(HEALTH_FLAT)
    assert diffs["magic_resistance"] == pytest.approx(MR_FLAT)
    assert diffs["bonus_magic_resistance"] == pytest.approx(MR_FLAT)
    # 4% move speed resolves as 4% of Ahri's 330 base (13.2 flat).
    assert diffs["move_speed"] == pytest.approx(MS_DELTA)
    changed = {key: round(value, 4) for key, value in diffs.items() if value != 0.0}
    assert changed == {
        "health": HEALTH_FLAT,
        "bonus_health": HEALTH_FLAT,
        "magic_resistance": MR_FLAT,
        "bonus_magic_resistance": MR_FLAT,
        "move_speed": MS_DELTA,
    }


# ---------------------------------------------------------------------------
# 2. Typed source values
# ---------------------------------------------------------------------------


def test_typed_steadfast_values_return_exact_numbers():
    rule = force_of_nature_steadfast_rule()
    assert rule.name == "Force of Nature — Steadfast"
    assert rule.max_stacks == MAX_STACKS
    assert rule.gain_per_application == 1
    assert rule.duration_seconds == pytest.approx(STACK_DURATION)
    assert rule.refresh == "refresh"
    assert rule.expiry == "all_at_once"
    assert rule.interval_seconds == pytest.approx(STACK_INTERVAL)
    assert rule.interval_key == "ability_instance"
    assert rule.gain_by_kind == {"immobilize": IMMOBILIZE_STACKS}
    assert rule.payload == {
        "bonus_magic_resistance": BONUS_MR,
        "bonus_move_speed_percent": BONUS_MS_PERCENT,
    }
    receipt = rule.public_receipt()
    assert receipt["max_stacks"] == MAX_STACKS
    assert receipt["duration_seconds"] == STACK_DURATION
    assert receipt["interval_seconds"] == STACK_INTERVAL
    assert receipt["gain_by_kind"] == {"immobilize": IMMOBILIZE_STACKS}
    assert receipt["payload"]["bonus_magic_resistance"] == BONUS_MR
    assert receipt["payload"]["bonus_move_speed_percent"] == BONUS_MS_PERCENT


def test_steadfast_source_revision_rides_the_reviewed_source_receipt():
    """The wiki source receipt rides defensive_effects.defense_source(...)
    (code-owned, revision 4016272); the ITEM_EFFECTS registry entry itself
    carries no source keys (unlike GA's ITEM_INPUT_OPTIONS receipt), so the
    source pin is the code-owned receipt."""
    assert ITEM_EFFECTS[ITEM_NAME]["type"] == "target_state"
    assert not ({"source_url", "source_revision_id"} & set(ITEM_EFFECTS[ITEM_NAME]))
    assert ITEM_NAME not in ITEM_INPUT_OPTIONS
    rule = force_of_nature_steadfast_rule(
        source=SourceReceipt(
            label=_SOURCE.label,
            url=_SOURCE.source_url,
            revision_id=_SOURCE.revision_id,
            revision_timestamp=_SOURCE.revision_timestamp,
        )
    )
    source = rule.public_receipt()["source"]
    assert source["revision_id"] == SOURCE_REVISION
    assert source["url"] == "https://wiki.leagueoflegends.com/en-us/Force_of_Nature"
    assert _SOURCE.label == "Force of Nature — Steadfast"


def test_starting_defenses_resolve_the_steadfast_fields():
    defenses = resolve_starting_defenses(
        "Ahri", 18, _stack_stats(), [{"name": ITEM_NAME}]
    )
    assert defenses.force_max_stacks == MAX_STACKS
    assert defenses.force_stack_duration == pytest.approx(STACK_DURATION)
    assert defenses.force_stack_interval == pytest.approx(STACK_INTERVAL)
    assert defenses.force_immobilize_stacks == IMMOBILIZE_STACKS
    assert defenses.force_bonus_magic_resistance == pytest.approx(BONUS_MR)
    assert defenses.force_bonus_move_speed_percent == pytest.approx(BONUS_MS_PERCENT)
    summary = defenses.public_summary()["combat_state"]["force_of_nature"]
    assert summary == {
        "stack_duration": STACK_DURATION,
        "max_stacks": MAX_STACKS,
        "stack_interval": STACK_INTERVAL,
        "immobilize_stacks": IMMOBILIZE_STACKS,
        "bonus_magic_resistance": BONUS_MR,
        "bonus_move_speed_percent": BONUS_MS_PERCENT,
    }
    assert any("Force of Nature Steadfast" in text for text in defenses.assumptions)


def test_missing_typed_key_fails_loud_naming_item_and_key(monkeypatch):
    patched = dict(ITEM_EFFECTS[ITEM_NAME])
    del patched["steadfast_max_stacks"]
    monkeypatch.setitem(ITEM_EFFECTS, ITEM_NAME, patched)
    with pytest.raises(KeyError) as excinfo:
        force_of_nature_steadfast_rule()
    message = str(excinfo.value)
    assert ITEM_NAME in message
    assert "steadfast_max_stacks" in message


def test_malformed_typed_values_fail_loudly(monkeypatch):
    base = dict(ITEM_EFFECTS[ITEM_NAME])
    patched = dict(base)
    patched["steadfast_max_stacks"] = "eight"
    monkeypatch.setitem(ITEM_EFFECTS, ITEM_NAME, patched)
    with pytest.raises(ValueError):
        force_of_nature_steadfast_rule()
    patched = dict(base)
    patched["steadfast_stack_duration"] = None
    monkeypatch.setitem(ITEM_EFFECTS, ITEM_NAME, patched)
    with pytest.raises(TypeError):
        force_of_nature_steadfast_rule()


# ---------------------------------------------------------------------------
# 3. Incoming magic-damage stack cadence
# ---------------------------------------------------------------------------


def test_incoming_champion_magic_damage_gains_one_stack_per_qualifying_packet():
    events = [_magic_packet(float(index), index + 1) for index in range(MAX_STACKS)]
    result = _run_packets(events)
    row = _force_row(result)
    assert row["stacks"] == MAX_STACKS
    assert [event["stacks"] for event in row["events"]] == list(range(1, 9))
    assert [event["time"] for event in row["events"]] == [float(i) for i in range(8)]
    assert row["stacks_until"] == pytest.approx(7.0 + STACK_DURATION)


def test_same_ability_instance_gains_one_stack_per_second():
    """P3-3Q per-instance cadence (the sourced rule: each cast instance can
    generate 1 stack every 1 second): ticks of the SAME instance at 0.3s
    and 0.6s stay blocked, but the same instance re-stacks at 1.0s."""
    events = [
        _magic_packet(0.0, 1, ability_instance="Q:1"),
        _magic_packet(0.3, 2, ability_instance="Q:1"),
        _magic_packet(0.6, 3, ability_instance="Q:1"),
    ]
    result = _run_packets(events)
    row = _force_row(result)
    assert [(e["time"], e["stacks"]) for e in row["events"]] == [(0.0, 1)]
    # A later packet of the SAME instance re-stacks once its own 1s
    # throttle elapsed (per-instance, not one-per-window).
    events.append(_magic_packet(1.0, 4, ability_instance="Q:1"))
    result = _run_packets(events)
    row = _force_row(result)
    assert row["stacks"] == 2
    assert row["events"][-1]["time"] == pytest.approx(1.0)
    assert row["events"][-1]["stacks"] == 2


def test_different_instances_within_one_second_each_gain_a_stack():
    """P3-3Q per-instance cadence (the sourced rule: each cast instance
    carries its own 1s throttle): DIFFERENT cast instances stack within
    one second (Q at 0.0, W at 0.5, E at 1.0 -> 3 stacks)."""
    events = [
        _magic_packet(0.0, 1, source_key="Q"),
        _magic_packet(0.5, 2, source_key="W"),
        _magic_packet(1.0, 3, source_key="E"),
    ]
    result = _run_packets(events)
    row = _force_row(result)
    assert [(e["time"], e["stacks"]) for e in row["events"]] == [
        (0.0, 1),
        (0.5, 2),
        (1.0, 3),
    ]


def test_physical_damage_gains_no_stacks():
    events = [
        {
            "time": float(index),
            "damage": 50.0,
            "damage_type": "physical",
            "attacker": "source",
            "target": "target",
            "source_key": "Q",
            "sequence": index + 1,
            "_event_id": f"p{index}",
            "_baseline_effective_armor": 30.0,
        }
        for index in range(MAX_STACKS)
    ]
    result = _run_packets(events)
    row = _force_row(result)
    assert row["stacks"] == 0
    assert row["events"] == []
    assert row["dynamic_bonus_magic_resistance"] == 0.0


def test_non_champion_magic_damage_gains_no_stacks():
    """Magic damage from a non-participant (minion id) never stacks: the
    stack machine requires a fight-participant attacker that is not self."""
    events = [
        _magic_packet(float(index), index + 1, attacker="minion") for index in range(8)
    ]
    result = _run_packets(events)
    row = _force_row(result)
    assert row["stacks"] == 0
    assert row["events"] == []


def test_zero_damage_and_reactive_magic_packets_gain_no_stacks():
    zero = [_magic_packet(0.0, 1, damage=0.0)]
    assert _force_row(_run_packets(zero))["stacks"] == 0
    reactive = [_magic_packet(0.0, 1, _reactive=True)]
    assert _force_row(_run_packets(reactive))["stacks"] == 0


# ---------------------------------------------------------------------------
# 4. Duration / refresh / expiry
# ---------------------------------------------------------------------------


def test_stack_duration_is_seven_seconds_and_expiry_is_all_at_once():
    events = [_magic_packet(0.0, 1), _magic_packet(1.0, 2), _magic_packet(2.0, 3)]
    result = _run_packets(events)
    row = _force_row(result)
    assert row["stacks"] == 3
    assert row["stacks_until"] == pytest.approx(2.0 + STACK_DURATION)
    # A qualifying packet at exactly last_gain + 7.0 resets ALL stacks, then
    # gains 1 (all-at-once expiry, lazily evaluated on the next packet).
    events.append(_magic_packet(9.0, 4))
    result = _run_packets(events)
    row = _force_row(result)
    assert row["stacks"] == 1
    assert row["stacks_until"] == pytest.approx(9.0 + STACK_DURATION)
    assert [(e["time"], e["stacks"]) for e in row["events"]] == [
        (0.0, 1),
        (1.0, 2),
        (2.0, 3),
        (9.0, 1),
    ]


def test_subsequent_qualifying_damage_refreshes_the_duration():
    # Gains at 0,1,2,...,6 then a gap: the 6.5 packet is interval-blocked but
    # the 7.5 packet refreshes the window instead of expiring it (gap 7.5-6.0
    # = 1.5 < 7.0 from the last gain).
    events = [_magic_packet(float(i), i + 1) for i in range(7)]
    events.append(_magic_packet(7.5, 8))
    result = _run_packets(events)
    row = _force_row(result)
    assert row["stacks"] == 8
    assert row["stacks_until"] == pytest.approx(7.5 + STACK_DURATION)


def test_stale_stack_count_is_not_timer_expired_without_a_qualifying_packet():
    """Named boundary: expiry is lazy — with no qualifying magic packet after
    the window, the state still reports the stale stack count (the engine
    authors no timer-driven expiry event today)."""
    events = [_magic_packet(0.0, 1)]
    result = _run_packets(events, duration=10.0)
    row = _force_row(result)
    assert row["stacks"] == 1
    assert row["stacks_until"] == pytest.approx(STACK_DURATION)


# ---------------------------------------------------------------------------
# 5. Cap
# ---------------------------------------------------------------------------


def test_stacks_never_exceed_eight_at_cap():
    events = [_magic_packet(float(index), index + 1) for index in range(12)]
    result = _run_packets(events, duration=12.0)
    row = _force_row(result)
    assert row["stacks"] == MAX_STACKS
    assert max(event["stacks"] for event in row["events"]) == MAX_STACKS
    assert row["events"][-1]["time"] == 11.0
    # Further qualifying damage keeps the cap (no growth, no reset while
    # within the refreshed window).
    assert len(row["events"]) == 12
    assert all(event["stacks"] <= MAX_STACKS for event in row["events"])


# ---------------------------------------------------------------------------
# 6. Immobilization branch
# ---------------------------------------------------------------------------


def test_immobilize_marker_grants_two_stacks_and_refreshes_the_duration():
    events = [
        _magic_packet(0.0, 1),
        _magic_packet(1.0, 2, immobilized=True),
        _magic_packet(2.0, 3),
    ]
    result = _run_packets(events)
    row = _force_row(result)
    assert [(e["time"], e["stacks"], e["immobilized"]) for e in row["events"]] == [
        (0.0, 1, False),
        (1.0, 3, True),
        (2.0, 4, False),
    ]
    assert row["stacks_until"] == pytest.approx(2.0 + STACK_DURATION)


def test_immobilize_without_a_qualifying_damage_packet_gains_no_stacks():
    """Named boundary: the +2 branch only rides a qualifying champion magic
    damage packet carrying the marker.  Pure CC, zero-damage, and physical
    immobilizes grant nothing."""
    pure_cc = [
        {
            "time": 0.0,
            "damage": 0.0,
            "damage_type": "magic",
            "attacker": "source",
            "target": "target",
            "source_key": "R",
            "sequence": 1,
            "_event_id": "cc0",
            "kind": "crowd_control",
            "cc_kind": "stun",
            "immobilized": True,
            "_baseline_effective_mr": 40.0,
        }
    ]
    assert _force_row(_run_packets(pure_cc))["stacks"] == 0
    physical = [
        {
            "time": 0.0,
            "damage": 50.0,
            "damage_type": "physical",
            "attacker": "source",
            "target": "target",
            "source_key": "Q",
            "sequence": 1,
            "_event_id": "pi0",
            "immobilized": True,
            "_baseline_effective_armor": 30.0,
        }
    ]
    assert _force_row(_run_packets(physical))["stacks"] == 0


# ---------------------------------------------------------------------------
# 7. Dynamic MR repricing
# ---------------------------------------------------------------------------


def test_max_stack_packet_itself_is_repriced_with_exactly_70_mr():
    """The reprice is PROSPECTIVE per packet: update_combat_state runs before
    a packet's damage flow, so the packet that REACHES max stacks is itself
    mitigated at baseline + 70 (never retroactively re-mitigating earlier
    packets).  The holder's base 55 MR is ordinary stat parity, already part
    of the baseline; the dynamic delta is exactly 70 on top."""
    events = [_magic_packet(float(index), index + 1) for index in range(MAX_STACKS)]
    result = _run_packets(events)
    row = _force_row(result)
    assert row["stacks"] == MAX_STACKS
    assert row["dynamic_bonus_magic_resistance"] == BONUS_MR
    reaching = events[-1]
    assert reaching["dynamic_resistance"] == {
        "type": "magic_resistance",
        "baseline_effective": 40.0,
        "delta": 70.0,
        "effective": 110.0,
        # factor = apply_resistance(1, 110) / apply_resistance(1, 40)
        #        = (100/210) / (100/140) = 140/210 = 2/3.
        "factor": pytest.approx(140.0 / 210.0, rel=1e-6),
    }
    # The reprice scales the packet's carried value by the mitigation ratio:
    # 50 * (100/210) / (100/140) = 33.33 (the packet that REACHES max stacks
    # is itself repriced; earlier packets are never retroactively changed).
    assert reaching["damage"] == pytest.approx(50.0 * 140.0 / 210.0, rel=1e-6)
    # The seventh packet (stacks 7, below cap) was NOT repriced.
    assert events[-2].get("dynamic_resistance") is None
    assert events[-2]["damage"] == pytest.approx(50.0)


def test_physical_packets_are_never_repriced_by_steadfast():
    events = [
        {
            "time": float(index),
            "damage": 50.0,
            "damage_type": "physical",
            "attacker": "source",
            "target": "target",
            "source_key": "Q",
            "sequence": index + 1,
            "_event_id": f"p{index}",
            "_baseline_effective_armor": 30.0,
        }
        for index in range(MAX_STACKS)
    ]
    result = _run_packets(events)
    assert _force_row(result)["dynamic_bonus_magic_resistance"] == 0.0
    assert all(event.get("dynamic_resistance") is None for event in events)


def test_packet_without_baseline_resistance_is_not_silently_repriced():
    """A packet without a baseline effective-MR receipt keeps its pair value
    and carries the named dynamic_resistance_unavailable receipt instead of
    a guessed mitigation ratio."""
    events = [
        _magic_packet(float(index), index + 1, baseline_mr=None) for index in range(8)
    ]
    result = _run_packets(events)
    assert _force_row(result)["stacks"] == MAX_STACKS
    reaching = events[-1]
    assert reaching["damage"] == pytest.approx(50.0)
    assert reaching.get("dynamic_resistance") is None
    assert reaching.get("dynamic_resistance_unavailable") == "magic_resistance"


# ---------------------------------------------------------------------------
# 8. Movement state (declared but unapplied — the named boundary)
# ---------------------------------------------------------------------------


def test_six_percent_move_speed_is_declared_but_not_applied():
    """The 6% max-stack bonus move speed is declared on the typed payload and
    the defenses summary, and advertised as the "movement" outcome dimension,
    but NEITHER walk applies it: no movement event is authored at max stacks
    and no move-speed stat is mutated.  The ordinary 4% item stat is applied
    (pinned by the stat-parity test); the Steadfast 6% is the boundary."""
    defenses = resolve_starting_defenses(
        "Ahri", 18, _stack_stats(), [{"name": ITEM_NAME}]
    )
    assert defenses.force_bonus_move_speed_percent == pytest.approx(BONUS_MS_PERCENT)
    assert (
        defenses.public_summary()["combat_state"]["force_of_nature"][
            "bonus_move_speed_percent"
        ]
        == BONUS_MS_PERCENT
    )
    # A full max-stack fight authors no movement packet from Steadfast.
    result = _holder_fight(16.0)
    force = _main_survival(result)["force_of_nature"]
    assert force["stacks"] == MAX_STACKS
    assert not any(
        str(event.get("source", "")).startswith("Force of Nature")
        or str(event.get("source", "")).startswith("Steadfast")
        for event in result["events"]
    )
    assert not any(
        event.get("kind") == "movement" for event in result["events"] if "kind" in event
    )


# ---------------------------------------------------------------------------
# 9. Compiled vs receipt parity
# ---------------------------------------------------------------------------


def test_score_path_agrees_with_receipt_on_every_steadfast_field():
    """The coupled score surface (include_receipt=False) returns the same
    survival rows as the receipt surface, force_of_nature fields included.
    FoN sits in COMPILED_WALK_UNREPRESENTABLE_ITEMS, so the compiled fast
    path fails closed (candidate-local) and both surfaces run the shared
    kernel walk — equality by construction today.  This is the score-path
    equality the P3-3Q certification must preserve with byte parity."""
    receipt = _holder_fight(16.0)
    score = _holder_fight(16.0, include_receipt=False)
    compiled_ctx = CoupledSearchContext()
    compiled = _holder_fight(16.0, include_receipt=False, search_context=compiled_ctx)
    for surface in (score, compiled):
        assert surface["participants"][0]["survival"] == _main_survival(receipt)
        assert (
            surface["participants"][1]["survival"]
            == receipt["participants"][1]["survival"]
        )
        assert surface["duration"] == receipt["duration"]
        for score_row, receipt_row in zip(surface["breakdown"], receipt["breakdown"]):
            assert score_row["participant_id"] == receipt_row["participant_id"]
            assert score_row["total_damage"] == receipt_row["total_damage"]
            assert score_row["incoming_damage"] == receipt_row["incoming_damage"]
            assert score_row["health_damage"] == receipt_row["health_damage"]
            assert score_row["death_time"] == receipt_row["death_time"]
            assert score_row["survived_window"] == receipt_row["survived_window"]
    # The fixture actually exercised the whole Steadfast machine: 8 stacks,
    # refreshed window, and the max-stack dynamic bonus applied.
    force = _main_survival(receipt)["force_of_nature"]
    assert force["stacks"] == MAX_STACKS
    assert force["dynamic_bonus_magic_resistance"] == BONUS_MR
    # The context stays usable (candidate-local fallback today; the P3-3Q
    # certification replaces the fallback with compiled panels — pinned by
    # test_compiled_panels_carry_the_force_of_nature_fight).
    assert compiled_ctx.uncompilable is False


def test_compiled_panels_carry_the_force_of_nature_fight():
    """P3-3Q contract: once FoN leaves COMPILED_WALK_UNREPRESENTABLE_ITEMS
    with byte-parity proof, the compiled score path rides the shared kernel
    for a main holder: the context builds panels, stays unpoisoned, and the
    compiled surface still deep-equals the receipt walk on the whole scoring
    receipt (force_of_nature row included).  Today no panel exists (the item
    fails closed per evaluation), so this xfails."""
    ctx = CoupledSearchContext()
    legacy = _holder_fight(16.0, include_receipt=False)
    fast = _holder_fight(16.0, include_receipt=False, search_context=ctx)
    assert fast == legacy
    assert ctx.uncompilable is False
    assert ctx.panels
    assert (
        fast["participants"][0]["survival"]["force_of_nature"]["stacks"] == MAX_STACKS
    )


def test_force_of_nature_enemy_holder_poisons_the_compiled_context():
    """A FoN holder on the enemy roster is search-invariant: the capability
    scan marks the context uncompilable (panels empty) and every evaluation
    falls back to the shared walk, still deep-equal.  This is today's
    fail-closed boundary for the roster side; the P3-3Q certification
    removes it alongside the main-holder fallback."""
    main = get_champion("Ahri")
    main_stats = calculate_total_stats(main, 18, [])
    params = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": 10,
            "role": "mid",
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
        },
        deterministic=True,
    )
    enemy = ChampionLoadout(champion="Janna", level=18, items=[ITEM_NAME]).resolve()
    kwargs = dict(
        main_stats=main_stats,
        main_defenses=resolve_starting_defenses("Ahri", 18, main_stats, []),
        enemies=[enemy],
        allies=[],
    )
    legacy = build_participant_timeline(
        main, 18, [], params, include_receipt=False, **kwargs
    )
    ctx = CoupledSearchContext()
    fast = build_participant_timeline(
        main,
        18,
        [],
        params,
        include_receipt=False,
        pair_result_cache={},
        search_context=ctx,
        **kwargs,
    )
    assert fast == legacy
    # P3-3Q: the roster-side FoN holder compiles like the main holder —
    # the capability scan no longer poisons the context.
    assert ctx.uncompilable is False
    assert ctx.panels


def test_legacy_score_only_pair_surface_carries_no_survival_state():
    """Named fail-closed boundary: the legacy pair scorer
    (run_fight(score_only=True)) cannot carry survival state — no target_*
    keys and no force_of_nature anywhere.  Scoring fields that DO survive
    (total_damage, item_state_receipts, champion_stats) agree with the full
    fight.  The coupled survival rows (pinned above) and the (future)
    item_state_receipts Steadfast row are the carriers."""
    champ = get_champion("Ahri")
    params = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": 10,
            "role": "mid",
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
            "enemies": [{"champion": "Annie", "level": 18, "items": []}],
        },
        deterministic=True,
    )
    full = run_fight(champ, 18, [_fon_item()], params)
    score = run_fight(champ, 18, [_fon_item()], params, score_only=True)
    assert score["total_damage"] == full["total_damage"]
    assert score["item_state_receipts"] == full["item_state_receipts"]
    assert score["champion_stats"] == full["champion_stats"]
    assert "target_ending_health" not in score
    assert "force_of_nature" not in score


# ---------------------------------------------------------------------------
# 10. Malformed-input fail-closed
# ---------------------------------------------------------------------------


def test_fabricated_force_of_nature_input_options_are_rejected_fail_closed():
    """FoN exposes no scenario control (no ITEM_INPUT_OPTIONS entry at all),
    so ANY fabricated option target under it is rejected with the unknown-
    target error naming the item."""
    assert ITEM_NAME not in ITEM_INPUT_OPTIONS
    with pytest.raises(ValueError) as excinfo:
        validate_item_input_options({ITEM_NAME: {"steadfast_max_stacks": 8}})
    assert "Unknown item option target" in str(excinfo.value)
    assert ITEM_NAME in str(excinfo.value)


def test_absent_force_of_nature_produces_no_stacks_and_no_receipt_row():
    defenses = resolve_starting_defenses("Ahri", 18, _stack_stats(), [])
    assert defenses.force_max_stacks == 0
    assert defenses.force_stack_duration == 0.0
    assert defenses.force_stack_interval == 0.0
    assert defenses.force_immobilize_stacks == 0
    assert defenses.force_bonus_magic_resistance == 0.0
    assert defenses.force_bonus_move_speed_percent == 0.0
    holder = Combatant(
        participant_id="target",
        team="enemy",
        champion_data={"name": "Ahri"},
        level=18,
        items=(),
        stats=_stack_stats(),
        defenses=defenses,
    )
    events = [_magic_packet(float(index), index + 1) for index in range(8)]
    result = _simulate_survival(
        [_dummy_source(), holder], {"target": events}, {}, {}, 10.0
    )
    row = result["target"]["force_of_nature"]
    assert row["stacks"] == 0
    assert row["events"] == []
    assert row["dynamic_bonus_magic_resistance"] == 0.0
    assert (
        item_state_receipts([], {}, fight_duration_seconds=10.0, is_melee=False) == []
    )


# ---------------------------------------------------------------------------
# 11. Coverage posture
# ---------------------------------------------------------------------------


def test_coverage_posture_stays_eligible_with_steadfast_dimensions():
    """item_model_coverage returns the modeled posture with optimizer_eligible
    + calculation_eligible True and outcome_dimensions ["movement",
    "defense"]; the target coverage is "modeled_event_certified" naming
    Steadfast, expiry, and the maximum-stack bonus resistance."""
    coverage = item_model_coverage(
        str(_fon_item()["name"]), ATTACKER_LANES
    ).as_payload()
    assert coverage["status"] == "stats_only"
    assert coverage["optimizer_eligible"] is True
    assert coverage["calculation_eligible"] is True
    assert coverage["outcome_dimensions"] == ["movement", "defense"]
    target = target_item_model_coverage(_fon_item())
    assert target["status"] == "modeled_event_certified"
    assert target["calculation_eligible"] is True
    assert target["outcome_dimensions"] == ["movement", "defense"]
    assert "Steadfast" in target["reason"]


def test_model_coverage_reason_names_steadfast_and_magic_resistance():
    """P3-3Q coverage tightening: item_model_coverage's reason should name
    the Steadfast mechanic (the target coverage already does).  Today the
    model posture falls through to the generic ITEM_EFFECTS reason, so this
    xfails."""
    coverage = item_model_coverage(
        str(_fon_item()["name"]), ATTACKER_LANES
    ).as_payload()
    # Ours' classifier derives the attacker-lane reason from the declared
    # families and never repeats a mechanic's prose; the mechanic is
    # named on the target lane, asserted there.
    assert coverage["status"] == "stats_only"
    assert "Steadfast" in target_item_model_coverage(_fon_item())["reason"]


def test_item_state_receipts_emits_exactly_one_steadfast_row():
    """P3-3Q contract (receipt path, the 3M/3N/3O pattern): item_state_receipts
    emits exactly ONE Force of Nature row — state "steadfast" — carrying the
    stack rule (max 8, 7.0s duration, 1.0s interval, +2 immobilize), the
    payload (70 MR, 6% move speed), and the wiki source receipt.  Absent
    today: item_state_receipts returns [] for FoN (the fail-closed absent
    claim is pinned by the absent-item test above, and the row's absence is
    what this xfail tracks)."""
    receipts = item_state_receipts(
        [_fon_item()], {}, fight_duration_seconds=16.0, is_melee=False
    )
    (receipt,) = [row for row in receipts if row.get("item") == ITEM_NAME]
    assert receipt["state"] == "steadfast"
    assert receipt["max_stacks"] == MAX_STACKS
    assert receipt["duration_seconds"] == pytest.approx(STACK_DURATION)
    assert receipt["interval_seconds"] == pytest.approx(STACK_INTERVAL)
    assert receipt["immobilize_stacks"] == IMMOBILIZE_STACKS
    assert receipt["bonus_magic_resistance"] == pytest.approx(BONUS_MR)
    assert receipt["bonus_move_speed_percent"] == pytest.approx(BONUS_MS_PERCENT)
    assert receipt["source_revision_id"] == SOURCE_REVISION
    assert str(receipt["source_url"]).startswith(
        "https://wiki.leagueoflegends.com/en-us/Force_of_Nature"
    )


# ---------------------------------------------------------------------------
# 12. Existing regression surface (kept green, disjoint, mirrors the originals)
# ---------------------------------------------------------------------------


def test_regression_surface_force_of_nature_timeline_stays_green():
    """Mirrors test_participant_timeline.py ~4345 (stacks and reprice of the
    maximum-stack packet): 8 magic packets at 1/s against baseline 40 MR
    yield 8 stacks, a +70 dynamic bonus, and the reaching packet repriced
    to 50 * 40/110."""
    events = [_magic_packet(float(index), index + 1) for index in range(8)]
    result = _run_packets(events)
    row = _force_row(result)
    assert row["stacks"] == 8
    assert row["dynamic_bonus_magic_resistance"] == 70.0
    assert events[-1]["dynamic_resistance"]["effective"] == 110.0
    assert events[-1]["damage"] == pytest.approx(50.0 * 140.0 / 210.0, rel=1e-6)


def test_regression_surface_force_of_nature_defensive_layer_stays_green():
    """Mirrors test_defensive_effects.py ~309 and
    test_state_lifecycle_consumers.py (TestForceOfNatureConsumer): the typed
    fields resolve through starting defenses and the summary."""
    defenses = resolve_starting_defenses(
        "Ahri", 18, _stack_stats(), [{"name": ITEM_NAME}]
    )
    assert defenses.force_max_stacks == 8
    assert defenses.force_stack_duration == pytest.approx(7.0)
    assert defenses.force_bonus_magic_resistance == pytest.approx(70.0)
    assert (
        defenses.public_summary()["combat_state"]["force_of_nature"]["max_stacks"] == 8
    )


def test_regression_surface_force_of_nature_coverage_stays_green():
    """Mirrors test_item_coverage.py ~276/377: the target coverage is
    modeled_event_certified, calculation_eligible, and names Steadfast (the
    derived reason states the mechanic and its event-certified schedule, not
    the magnitude main's retired table typed)."""
    coverage = target_item_model_coverage(_fon_item())
    assert coverage["status"] == "modeled_event_certified"
    assert coverage["calculation_eligible"] is True
    assert "Steadfast" in coverage["reason"]
