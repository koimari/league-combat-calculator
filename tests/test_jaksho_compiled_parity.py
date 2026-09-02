"""P1 Package 3R — Jak'Sho, The Protean (6665) "Voidborn Resilience"
compiled-walk + optimizer certification.

This file is the focused acceptance-matrix owner for Jak'Sho's Voidborn
Resilience.  It pins the OBSERVABLES the coordinator's P3-3R completion must
satisfy and runs against today's source: every behavior that already exists
passes now; every assertion that targets a contract piece the source does not
emit yet is marked ``xfail`` with reason ``awaiting P3-3R ...``.

Contract under test (current runtime facts, verified before pinning):

* ITEM IDENTITY: cached name "Jak'Sho, The Protean", id 6665, price 3200
  (shop.prices.total, sell 1280), tier 3 LEGENDARY.  Stats: 350 flat
  health, 45 flat armor, 45 flat magic resistance (ordinary stat parity).
  Passive name "Voidborn Resilience", unique; the cached riotDescription
  branch is exact: "After 5 seconds of champion combat, increase your
  bonus Armor and Magic Resist by 30% until end of combat."
* TYPED SOURCE: the item_effects registry entry (type "target_state")
  carries the three voidborn keys, read through required_effect_value:
  voidborn_stack_interval 1.0, voidborn_max_stacks 5, and
  voidborn_bonus_resistance_multiplier 0.30.  resolve_starting_defenses
  is the declaration consumer the coordinator uses; its
  ChampionDefenses fields are the kernel-facing
  jaksho_* names (jaksho_stack_interval / jaksho_max_stacks /
  jaksho_bonus_resistance_multiplier).  A missing key raises KeyError
  naming "Jak'Sho, The Protean" AND the key (AGENTS.md rule 5 — no
  silent fallbacks); malformed values fail loudly (ValueError on bad
  int, TypeError on non-numeric multiplier).  The wiki source receipt
  rides the code-owned defensive_effects.defense_source(...) (revision
  3984950) — the registry entry itself carries no source keys.
* COMBAT-TIME STACK PROGRESSION: Voidborn Resilience is combat-time
  state on the shared survival kernel: stacks = min(5, floor(action.time
  / 1.0)) evaluated per QUALIFYING combat packet (attacker is a fight
  participant, not self; not reactive; not deferred; amount > 0 — any
  damage type), capped at 5.  Stack events are authored only when the
  count CHANGES, so a fight whose qualifying packets land at 0.5s, 1.5s,
  2.5s, 3.5s, 4.5s, 5.5s, 6.5s observes the event ladder 1, 2, 3, 4, 5
  at 1.5s..5.5s (the 0.5s packet reads floor(0.5/1.0) = 0, unchanged,
  and authors nothing) and never exceeds 5.  The progression is
  TIME-derived: packet COUNT is irrelevant — many packets inside one
  second yield one stack value, and a packet at 3.1s jumps straight from
  1 to 3 when no qualifying packet landed during the second 2.x.
* ONE-STACK-PER-SECOND TIMING: packets at 0.2s and 0.8s both read
  floor(time) = 0 (one inert stack value, no events); a packet at 1.0s
  advances to 1 and a packet at 2.0s to 2.  This pins the strict
  floor(time / interval) reading of the branch text "after 5 seconds of
  champion combat" (the 5-stack cap lands at t >= 5.0).
* MAXIMUM-STACK BONUS REPRICING: at 5 stacks the kernel sets
  dynamic_bonus_armor = 0.30 x bonus_armor AND dynamic_bonus_magic_
  resistance = 0.30 x bonus_magic_resistance.  The reprice is
  PROSPECTIVE per packet: update_combat_state runs before a packet's
  damage flow, so the packet that REACHES 5 stacks is itself repriced
  (mirror the FoN rule); earlier packets are never retroactively
  re-mitigated.  A physical packet is repriced with the armor delta, a
  magic packet with the MR delta, each against the packet's stamped
  baseline (baseline_effective_armor / baseline_effective_mr from the
  3Q scoring context).  A packet without a baseline is never silently
  repriced: dynamic_resistance_unavailable is written and the damage
  stands.
* THE BONUS-ONLY RULE: the 0.30 multiplier applies to BONUS resistances
  only — base/total are never multiplied.  Pinned with a fixture where
  bonus != total (armor 100 total / 60 bonus -> delta 18, never 30), and
  a zero-bonus holder reaches 5 stacks yet gains no dynamic bonus and no
  reprice.
* COMPILED VS RECEIPT PARITY: both adapters drive one kernel
  (test_survival_kernel.py, issue #137).  Today Jak'Sho sits in
  COMPILED_WALK_UNREPRESENTABLE_ITEMS ("Voidborn reprice needs baseline
  resistances"), so the compiled fast path fails closed: a MAIN holder
  falls back per evaluation (context.uncompilable stays False, no panels
  built) and the score surface deep-equals the receipt walk on the whole
  scoring receipt, jaksho row included; an ENEMY/ALLY holder poisons the
  search-invariant roster context (uncompilable True, panels empty) and
  still deep-equals via the receipt walk.  The P3-3R certification
  (remove from the blocklist with parity proof) is pinned as xfail:
  panels non-empty + uncompilable False + deep-equal for both sides.
  The legacy run_fight(score_only=True) surface carries NO survival
  state (no target_* keys, no jaksho) — the named fail-closed carrier
  boundary; item_state_receipts agrees between surfaces.
* TUPLE-LEDGER FAIL-CLOSED: the 3Q scoring context stamps ability_
  instance + baseline resistances only for DICT damage rows.  Tuple-
  ledger pair rows (engine light ledger, damage_events_tuple) omit that
  metadata, so a stack-armed defender must fail closed with the
  compiler's tuple_ledger_stack_metadata receipt and fall back to
  parity.  Today the capability scan fails first (item_mechanic=Jak'Sho,
  The Protean), which already yields the same fallback parity; the
  post-certification tuple guard is pinned as xfail.  (Coordinator note:
  participant_timeline's pair-enrichment block crashes on tuple rows
  today — dict(event) on a 4-tuple — and its defender_stack_armed probe
  reads ``voidborn_stack_interval`` although StartingDefenses names the
  field jaksho_stack_interval; both are P3-3R armor-reprice/metadata
  gaps the compiled certification must close.)
* FAIL-CLOSED: absent Jak'Sho -> no stacks, no receipt row, all
  defenses zero; a fabricated Jak'Sho item option is rejected ("Unknown
  item option target: Jak'Sho, The Protean" — the item has no
  ITEM_INPUT_OPTIONS entry); missing/malformed typed values raise.
* COVERAGE: item_model_coverage returns "modeled_effect" with
  optimizer_eligible + calculation_eligible True — but outcome_dimensions
  is [] and the reason is the GENERIC "Damage-relevant effects are
  represented by the fight model." today; a "defense" dimension and a
  Voidborn/bonus-resistance-naming reason are xfail (the coordinator's
  coverage tightening).  target_item_model_coverage is already
  "modeled_event_certified" naming Voidborn's one-stack-per-second
  combat state and the maximum-stack bonus-resistance multiplication.
* ITEM STATE RECEIPTS: the 3M/3N/3O-pattern item_state_receipts row for
  Voidborn Resilience (state "voidborn", stack rule/payload/source) is
  absent today — xfail.
* XFAIL ONLY for genuinely absent mechanics: (1) the compiled-panel
  certification (main + enemy-roster); (2) the post-certification
  tuple-ledger guard reachability; (3) the coverage dimension + reason
  naming; (4) the item_state_receipts voidborn row.  All are
  ``awaiting P3-3R ...``.

Sibling owners: the compiled-vs-receipt contract lives in
``tests/test_survival_kernel.py`` (issue #137); the Force of Nature 3Q
matrix shape in ``tests/test_force_of_nature_compiled_parity.py`` (this
file mirrors its fixtures/helpers); the kernel-typed declaration consumer
in ``tests/test_state_lifecycle_consumers.py``; the stack-machine
regression in ``tests/test_participant_timeline.py``
(test_jaksho_multiplies_bonus_resistances_after_five_combat_seconds
~4375); the defenses resolution in ``tests/test_defensive_effects.py``
(test_force_of_nature_and_jaksho_resolve_event_state_metadata ~304) and
the coverage pins in ``tests/test_item_coverage.py`` (~277).  This file
is disjoint and pins only the Jak'Sho acceptance observables.
"""

import pytest

from src.calculator.data_fetcher import get_champion, get_item_by_name

# The retired per-item ``_X_SOURCE`` constant, read from the one home it
# moved to: the declaration's own resolved citation.
from src.calculator.defensive_effects import (
    StartingDefenses,
    defense_source,
    resolve_starting_defenses,
)
from src.calculator.interpreters import uncompilable_item_receipt
from src.calculator.item_behavior import DefenseMechanic
from src.calculator.item_coverage import (
    ATTACKER_LANES,
    item_model_coverage,
    target_item_model_coverage,
)
from src.calculator.item_effects import (
    ITEM_EFFECTS,
    ITEM_INPUT_OPTIONS,
    item_state_receipts,
    required_effect_value,
    validate_item_input_options,
)
from src.calculator.participant_timeline import (
    Combatant,
    CoupledSearchContext,
    build_participant_timeline,
)
from src.calculator.pipeline import FightParams, run_fight
from src.calculator.scenario import ChampionLoadout
from src.calculator.stats import calculate_total_stats

# Ours' declaration layer raises its own fail-closed error where main's
# accessor raised KeyError; both refuse the corrupted value.
from src.calculator.value_ref import ValueRefError
from tests.survival_probe import simulate_survival

_SOURCE = defense_source("Jak'Sho, The Protean", DefenseMechanic.VOIDBORN_RESILIENCE)

ITEM_NAME = "Jak'Sho, The Protean"
ITEM_ID = 6665
PRICE = 3200
SELL = 1280
HEALTH_FLAT = 350.0
ARMOR_FLAT = 45.0
MR_FLAT = 45.0
STACK_INTERVAL = 1.0
MAX_STACKS = 5
BONUS_MULTIPLIER = 0.30
SOURCE_REVISION = 3984950
# The cached wiki branch text (riotDescription) — the exact Voidborn
# Resilience sentence plus the stats block.
BRANCH_FRAGMENTS = (
    "<passive>Voidborn Resilience</passive>",
    "After 5 seconds of champion combat",
    "increase your bonus",
    "by 30% until end of combat",
    "350",
    "45",
)


def _jaksho_item() -> dict:
    """The real cached item record (id 6665)."""
    return get_item_by_name(ITEM_NAME)


def _stack_stats() -> dict:
    """A holder where bonus (60) != total (100): the bonus-only probe."""
    return {
        "health": 5000.0,
        "armor": 100.0,
        "magic_resistance": 100.0,
        "bonus_armor": 60.0,
        "bonus_magic_resistance": 60.0,
        "is_melee": False,
    }


def _stack_holder() -> Combatant:
    """The Jak'Sho holder used by the packet-level stack-machine probes."""
    stats = _stack_stats()
    return Combatant(
        participant_id="target",
        team="enemy",
        champion_data={"name": "Ahri"},
        level=18,
        items=(_jaksho_item(),),
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


def _combat_packet(
    time: float,
    sequence: int,
    *,
    damage: float = 50.0,
    damage_type: str = "magic",
    attacker: str = "source",
    baseline_armor: float | None = None,
    baseline_mr: float | None = None,
    **extra,
) -> dict:
    """One incoming combat packet; baselines default to None (absent)."""
    packet = {
        "time": time,
        "damage": damage,
        "damage_type": damage_type,
        "attacker": attacker,
        "target": "target",
        "source_key": "Q",
        "sequence": sequence,
        "_event_id": f"{damage_type}:{sequence}:{time}",
    }
    if baseline_armor is not None:
        packet["_baseline_effective_armor"] = baseline_armor
    if baseline_mr is not None:
        packet["_baseline_effective_mr"] = baseline_mr
    packet.update(extra)
    return packet


def _run_packets(events, duration: float = 10.0) -> dict:
    """Run one _simulate_survival with the Jak'Sho holder as target."""
    return simulate_survival(
        [_dummy_source(), _stack_holder()], {"target": events}, {}, {}, duration
    )


def _jaksho_row(result: dict) -> dict:
    return result["target"]["jaksho"]


def _holder_fight(
    duration: float,
    *,
    holder_items: tuple[str, ...] = (ITEM_NAME,),
    include_receipt: bool = True,
    search_context: CoupledSearchContext | None = None,
    enemy: str = "Cassiopeia",
) -> dict:
    """A coupled fight where the MAIN holds Jak'Sho against a dealer.

    The 16-second Cassiopeia fixture reaches 5 stacks (cap) and exercises
    the max-stack reprice inside a real pair fight.  ``include_receipt=
    False`` returns the coupled score surface; passing a ``search_context``
    plus an empty pair cache exercises the compiled score path (which must
    fail closed on Jak'Sho today and fall back to the shared walk).
    """
    main = get_champion("Ahri")
    items = [_jaksho_item()] if ITEM_NAME in holder_items else []
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
    defenses = resolve_starting_defenses("Ahri", 18, main_stats, items)
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


def _riven_tuple_ledger_fight(
    *,
    include_receipt: bool = True,
    search_context: CoupledSearchContext | None = None,
) -> dict:
    """A coupled fight whose main is a TUPLE-LEDGER champion (Riven's pair
    engine returns damage_events_tuple light rows) holding Jak'Sho.

    Today the capability scan fails closed before any pair fight runs, so
    this fixture is the post-certification tuple-guard shape: after P3-3R
    removes the blocklist, the compiler must fail closed with
    tuple_ledger_stack_metadata and still deep-equal the receipt walk.
    """
    main = get_champion("Riven")
    items = [_jaksho_item()]
    main_stats = calculate_total_stats(main, 18, items)
    params = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": 12,
            "role": "top",
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
        },
        deterministic=True,
    )
    enemy_loadout = ChampionLoadout(champion="Cassiopeia", level=18, items=[]).resolve()
    defenses = resolve_starting_defenses("Riven", 18, main_stats, items)
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


def test_cached_identity_pins_name_id_price_stats_and_voidborn_branch():
    item = _jaksho_item()
    assert item["name"] == ITEM_NAME
    assert item["id"] == ITEM_ID
    assert item["shop"]["prices"]["total"] == PRICE
    assert item["shop"]["prices"]["sell"] == SELL
    assert item["tier"] == 3
    assert item["rank"] == ["LEGENDARY"]
    assert item["stats"]["health"]["flat"] == HEALTH_FLAT
    assert item["stats"]["armor"]["flat"] == ARMOR_FLAT
    assert item["stats"]["magicResistance"]["flat"] == MR_FLAT
    (passive,) = item["passives"]
    assert passive["name"] == "Voidborn Resilience"
    assert passive["unique"] is True
    assert passive["mythic"] is False
    branch = item["riotDescription"]
    for fragment in BRANCH_FRAGMENTS:
        assert fragment in branch


def test_equipping_jaksho_yields_exactly_350_health_45_armor_and_45_mr():
    main = get_champion("Ahri")
    base = calculate_total_stats(main, 18, [])
    with_jaksho = calculate_total_stats(main, 18, [_jaksho_item()])
    diffs = {key: with_jaksho[key] - base[key] for key in with_jaksho}
    assert diffs["health"] == pytest.approx(HEALTH_FLAT)
    assert diffs["bonus_health"] == pytest.approx(HEALTH_FLAT)
    assert diffs["armor"] == pytest.approx(ARMOR_FLAT)
    assert diffs["bonus_armor"] == pytest.approx(ARMOR_FLAT)
    assert diffs["magic_resistance"] == pytest.approx(MR_FLAT)
    assert diffs["bonus_magic_resistance"] == pytest.approx(MR_FLAT)
    changed = {key: round(value, 4) for key, value in diffs.items() if value != 0.0}
    assert changed == {
        "health": HEALTH_FLAT,
        "bonus_health": HEALTH_FLAT,
        "armor": ARMOR_FLAT,
        "bonus_armor": ARMOR_FLAT,
        "magic_resistance": MR_FLAT,
        "bonus_magic_resistance": MR_FLAT,
    }


# ---------------------------------------------------------------------------
# 2. Typed source values
# ---------------------------------------------------------------------------


def test_typed_voidborn_values_return_exact_numbers():
    """The three registry keys read through required_effect_value, and the
    declaration consumer the coordinator uses — resolve_starting_defenses —
    exposes them as the kernel-facing jaksho_* ChampionDefenses fields."""
    assert ITEM_EFFECTS[ITEM_NAME]["type"] == "target_state"
    assert required_effect_value(ITEM_NAME, "voidborn_stack_interval") == STACK_INTERVAL
    assert required_effect_value(ITEM_NAME, "voidborn_max_stacks") == MAX_STACKS
    assert (
        required_effect_value(ITEM_NAME, "voidborn_bonus_resistance_multiplier")
        == BONUS_MULTIPLIER
    )
    defenses = resolve_starting_defenses(
        "Ahri", 18, _stack_stats(), [{"name": ITEM_NAME}]
    )
    assert defenses.jaksho_stack_interval == pytest.approx(STACK_INTERVAL)
    assert defenses.jaksho_max_stacks == MAX_STACKS
    assert defenses.jaksho_bonus_resistance_multiplier == pytest.approx(
        BONUS_MULTIPLIER
    )
    summary = defenses.public_summary()["combat_state"]["jaksho"]
    assert summary == {
        "stack_interval": STACK_INTERVAL,
        "max_stacks": MAX_STACKS,
        "bonus_resistance_multiplier": BONUS_MULTIPLIER,
    }
    assert any("Jak'Sho Voidborn Resilience" in text for text in defenses.assumptions)


def test_voidborn_source_revision_rides_the_code_owned_receipt():
    """The wiki source receipt rides defensive_effects.defense_source(...)
    (code-owned, revision 3984950); the ITEM_EFFECTS registry entry itself
    carries no source keys, so the source pin is the code-owned receipt."""
    assert ITEM_EFFECTS[ITEM_NAME]["type"] == "target_state"
    assert not ({"source_url", "source_revision_id"} & set(ITEM_EFFECTS[ITEM_NAME]))
    assert ITEM_NAME not in ITEM_INPUT_OPTIONS
    assert _SOURCE.label == "Jak'Sho, The Protean — Voidborn Resilience"
    assert _SOURCE.revision_id == SOURCE_REVISION
    assert _SOURCE.source_url == (
        "https://wiki.leagueoflegends.com/en-us/Jak%27Sho,_The_Protean"
    )


def test_missing_typed_key_fails_loud_naming_item_and_key(monkeypatch):
    patched = dict(ITEM_EFFECTS[ITEM_NAME])
    del patched["voidborn_max_stacks"]
    monkeypatch.setitem(ITEM_EFFECTS, ITEM_NAME, patched)
    with pytest.raises((KeyError, ValueRefError)) as excinfo:
        resolve_starting_defenses("Ahri", 18, _stack_stats(), [{"name": ITEM_NAME}])
    message = str(excinfo.value)
    # The KeyError message is a repr, so the apostrophe in "Jak'Sho" is
    # backslash-escaped; the item name and the key are both still named.
    assert "Jak" in message
    assert "Sho" in message
    assert "voidborn_max_stacks" in message


def test_malformed_typed_values_fail_loudly():
    """A non-numeric value is a ``ValueRefError`` naming the item and key.

    One ``monkeypatch`` context per key: a corruption that outlived its
    case would let the first bad key answer for the second, and the raise
    would be pinned on the wrong stop.
    """
    for key, value in (
        ("voidborn_max_stacks", "five"),
        ("voidborn_bonus_resistance_multiplier", None),
    ):
        with pytest.MonkeyPatch.context() as patch:
            # The LIVE entry, so the declaration's reference resolves the
            # damage: a rebound copy would leave it on the intact mapping.
            patch.setitem(ITEM_EFFECTS[ITEM_NAME], key, value)
            with pytest.raises(ValueRefError) as excinfo:
                resolve_starting_defenses(
                    "Ahri", 18, _stack_stats(), [{"name": ITEM_NAME}]
                )
            message = str(excinfo.value)
            assert "Jak" in message
            assert "Sho" in message
            assert key in message


# ---------------------------------------------------------------------------
# 3. Combat-time stack progression
# ---------------------------------------------------------------------------


def test_combat_time_stack_progression_reaches_five_and_caps():
    """Packets at 0.5, 1.5, 2.5, ... show the event ladder 1, 2, 3, 4, 5
    (one per second of combat; the 0.5s packet reads floor(0.5/1.0) = 0 and
    authors nothing) and never exceed the 5-stack cap."""
    events = [
        _combat_packet(0.5 + index, index + 1, baseline_mr=100.0) for index in range(8)
    ]
    result = _run_packets(events)
    row = _jaksho_row(result)
    assert row["stacks"] == MAX_STACKS
    assert [event["stacks"] for event in row["events"]] == [1, 2, 3, 4, 5]
    assert [event["time"] for event in row["events"]] == [1.5, 2.5, 3.5, 4.5, 5.5]
    # Cap: the 6.5s and 7.5s packets keep stacks at 5 (no further events).
    assert len(row["events"]) == 5
    assert max(event["stacks"] for event in row["events"]) == MAX_STACKS


def test_stack_progression_is_time_derived_not_packet_counted():
    """Four qualifying packets inside a window still read floor(time): 1.2s,
    1.5s and 1.9s all read 1 (one event), then the 3.1s packet jumps to 3 —
    the count of packets never drives the stack value."""
    events = [
        _combat_packet(1.2, 1, baseline_mr=100.0),
        _combat_packet(1.5, 2, baseline_mr=100.0),
        _combat_packet(1.9, 3, baseline_mr=100.0),
        _combat_packet(3.1, 4, baseline_mr=100.0),
    ]
    result = _run_packets(events)
    row = _jaksho_row(result)
    assert [(e["time"], e["stacks"]) for e in row["events"]] == [(1.2, 1), (3.1, 3)]
    assert row["stacks"] == 3


def test_same_second_packets_yield_one_stack_value_and_later_seconds_advance():
    """Two packets within the same second (0.2, 0.8) read floor = 0: one
    inert stack value, no events.  A packet at 1.0s advances to 1 and a
    packet at 2.0s to 2 — one stack per second of combat elapsed."""
    events = [
        _combat_packet(0.2, 1, baseline_mr=100.0),
        _combat_packet(0.8, 2, baseline_mr=100.0),
        _combat_packet(1.0, 3, baseline_mr=100.0),
        _combat_packet(2.0, 4, baseline_mr=100.0),
    ]
    result = _run_packets(events)
    row = _jaksho_row(result)
    assert [(e["time"], e["stacks"]) for e in row["events"]] == [(1.0, 1), (2.0, 2)]
    assert row["stacks"] == 2


def test_only_qualifying_combat_packets_advance_the_time_stacks():
    """Non-participant (minion), reactive, zero-damage, and self packets
    never advance the time-derived stacks (the kernel's qualifying gates)."""
    events = [
        _combat_packet(1.5, 1, baseline_mr=100.0, attacker="minion"),
        _combat_packet(2.5, 2, baseline_mr=100.0, _reactive=True),
        _combat_packet(3.5, 3, baseline_mr=100.0, damage=0.0),
        _combat_packet(4.5, 4, baseline_mr=100.0, attacker="target"),
    ]
    result = _run_packets(events)
    row = _jaksho_row(result)
    assert row["stacks"] == 0
    assert row["events"] == []


def test_physical_damage_also_advances_the_time_stacks():
    """Voidborn's cadence is combat time, not a damage-type gate: physical
    packets advance stacks exactly like magic packets (the cap bonus then
    reprices the armor delta — pinned in section 4)."""
    events = [
        _combat_packet(
            0.5 + index, index + 1, damage_type="physical", baseline_armor=100.0
        )
        for index in range(7)
    ]
    result = _run_packets(events)
    row = _jaksho_row(result)
    assert row["stacks"] == MAX_STACKS
    assert [event["stacks"] for event in row["events"]] == [1, 2, 3, 4, 5]


# ---------------------------------------------------------------------------
# 4. Maximum-stack bonus repricing
# ---------------------------------------------------------------------------


def test_max_stack_bonus_resistances_multiply_bonus_by_30_percent():
    """At 5 stacks the dynamic bonus armor AND magic resistance are each
    0.30 x the BONUS value (60 -> 18).  The reaching packet is itself
    repriced prospectively (50 raw against baseline 100 MR + 18 -> 45.872);
    earlier packets are never retroactively re-mitigated."""
    events = [
        _combat_packet(0.5 + index, index + 1, baseline_mr=100.0) for index in range(7)
    ]
    result = _run_packets(events)
    row = _jaksho_row(result)
    assert row["stacks"] == MAX_STACKS
    assert row["dynamic_bonus_armor"] == pytest.approx(BONUS_MULTIPLIER * 60.0)
    assert row["dynamic_bonus_magic_resistance"] == pytest.approx(
        BONUS_MULTIPLIER * 60.0
    )
    reaching = events[5]  # the 5.5s packet that reaches the cap
    assert reaching["dynamic_resistance"] == {
        "type": "magic_resistance",
        "baseline_effective": 100.0,
        "delta": 18.0,
        "effective": 118.0,
        # factor = apply_resistance(1, 118) / apply_resistance(1, 100)
        #        = (100/218) / (100/200) = 200/218.
        "factor": pytest.approx(200.0 / 218.0, rel=1e-6),
    }
    assert reaching["damage"] == pytest.approx(50.0 * 200.0 / 218.0, rel=1e-6)
    # The fifth packet (stacks 4, below cap) was NOT repriced.
    assert events[4].get("dynamic_resistance") is None
    assert events[4]["damage"] == pytest.approx(50.0)
    # The post-cap 6.5s packet stays repriced.
    assert events[6]["damage"] == pytest.approx(50.0 * 200.0 / 218.0, rel=1e-6)


def test_physical_packets_are_repriced_with_the_armor_delta():
    """A physical packet at cap is repriced with the dynamic bonus ARMOR
    delta (0.30 x bonus_armor) against its baseline effective armor."""
    events = [
        _combat_packet(
            0.5 + index, index + 1, damage_type="physical", baseline_armor=100.0
        )
        for index in range(7)
    ]
    result = _run_packets(events)
    row = _jaksho_row(result)
    assert row["stacks"] == MAX_STACKS
    assert row["dynamic_bonus_armor"] == pytest.approx(18.0)
    reaching = events[5]
    assert reaching["dynamic_resistance"]["type"] == "armor"
    assert reaching["dynamic_resistance"]["delta"] == pytest.approx(18.0)
    assert reaching["dynamic_resistance"]["effective"] == pytest.approx(118.0)
    assert reaching["damage"] == pytest.approx(50.0 * 200.0 / 218.0, rel=1e-6)
    assert events[4].get("dynamic_resistance") is None
    assert events[4]["damage"] == pytest.approx(50.0)


def test_packet_without_baseline_resistance_is_not_silently_repriced():
    """A packet without a baseline effective-resistance receipt keeps its
    pair value and carries the named dynamic_resistance_unavailable receipt
    instead of a guessed mitigation ratio."""
    events = [
        _combat_packet(0.5 + index, index + 1, baseline_mr=None) for index in range(7)
    ]
    result = _run_packets(events)
    row = _jaksho_row(result)
    assert row["stacks"] == MAX_STACKS
    reaching = events[5]
    assert reaching["damage"] == pytest.approx(50.0)
    assert reaching.get("dynamic_resistance") is None
    assert reaching.get("dynamic_resistance_unavailable") == "magic_resistance"


def test_bonus_only_rule_base_resistances_are_never_multiplied():
    """The 0.30 multiplier applies to BONUS resistances only: with total 100
    and bonus 60 the delta is exactly 18 (0.30 x 60), never 30 (0.30 x 100);
    and a holder with ZERO bonus reaches 5 stacks yet gains no dynamic bonus
    and no reprice."""
    events = [
        _combat_packet(0.5 + index, index + 1, baseline_mr=100.0) for index in range(7)
    ]
    result = _run_packets(events)
    row = _jaksho_row(result)
    assert row["dynamic_bonus_magic_resistance"] == pytest.approx(18.0)
    assert row["dynamic_bonus_magic_resistance"] != pytest.approx(30.0)
    assert row["dynamic_bonus_armor"] == pytest.approx(18.0)
    assert row["dynamic_bonus_armor"] != pytest.approx(30.0)
    zero_bonus = {
        "health": 5000.0,
        "armor": 100.0,
        "magic_resistance": 100.0,
        "bonus_armor": 0.0,
        "bonus_magic_resistance": 0.0,
        "is_melee": False,
    }
    holder = Combatant(
        participant_id="target",
        team="enemy",
        champion_data={"name": "Ahri"},
        level=18,
        items=(_jaksho_item(),),
        stats=zero_bonus,
        defenses=resolve_starting_defenses(
            "Ahri", 18, zero_bonus, [{"name": ITEM_NAME}]
        ),
    )
    zero_events = [
        _combat_packet(0.5 + index, index + 1, baseline_mr=100.0) for index in range(7)
    ]
    zero_result = simulate_survival(
        [_dummy_source(), holder], {"target": zero_events}, {}, {}, 10.0
    )
    row = zero_result["target"]["jaksho"]
    assert row["stacks"] == MAX_STACKS
    assert row["dynamic_bonus_armor"] == 0.0
    assert row["dynamic_bonus_magic_resistance"] == 0.0
    assert zero_events[5].get("dynamic_resistance") is None
    assert zero_events[5]["damage"] == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# 5. Compiled vs receipt parity
# ---------------------------------------------------------------------------


def test_score_path_agrees_with_receipt_on_every_voidborn_field():
    """The coupled score surface (include_receipt=False) returns the same
    survival rows as the receipt surface, jaksho fields included.  Jak'Sho
    sits in COMPILED_WALK_UNREPRESENTABLE_ITEMS, so the compiled fast path
    fails closed (candidate-local) and both surfaces run the shared kernel
    walk — equality by construction today.  This is the score-path equality
    the P3-3R certification must preserve with byte parity."""
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
        for score_row, receipt_row in zip(
            surface["breakdown"], receipt["breakdown"], strict=False
        ):
            assert score_row["participant_id"] == receipt_row["participant_id"]
            assert score_row["total_damage"] == receipt_row["total_damage"]
            assert score_row["incoming_damage"] == receipt_row["incoming_damage"]
            assert score_row["health_damage"] == receipt_row["health_damage"]
            assert score_row["death_time"] == receipt_row["death_time"]
            assert score_row["survived_window"] == receipt_row["survived_window"]
    # The fixture actually exercised the whole Voidborn machine: 5 stacks at
    # the cap and the max-stack dynamic bonus (0.30 x the item's +45 bonus).
    force = _main_survival(receipt)["jaksho"]
    assert force["stacks"] == MAX_STACKS
    assert force["dynamic_bonus_armor"] == pytest.approx(13.5)
    assert force["dynamic_bonus_magic_resistance"] == pytest.approx(13.5)
    assert force["events"]
    assert force["events"][-1]["stacks"] == MAX_STACKS
    # Every authored event is exactly the floor-time reading (time-derived).
    for event in force["events"]:
        assert event["stacks"] == int(event["time"] // 1.0)
    # The context stays usable (candidate-local fallback today; the P3-3R
    # certification replaces the fallback with compiled panels — pinned by
    # test_compiled_panels_carry_the_jaksho_fight).
    assert compiled_ctx.uncompilable is False


def test_compiled_panels_carry_the_jaksho_fight():
    """P3-3R contract: once Jak'Sho leaves COMPILED_WALK_UNREPRESENTABLE_
    ITEMS with parity proof, the compiled score path rides the shared kernel
    for a main holder: the context builds panels, stays unpoisoned, and the
    compiled surface still deep-equals the receipt walk on the whole scoring
    receipt (jaksho row included).  Today no panel exists (the item fails
    closed per evaluation), so this xfails."""
    ctx = CoupledSearchContext()
    legacy = _holder_fight(16.0, include_receipt=False)
    fast = _holder_fight(16.0, include_receipt=False, search_context=ctx)
    assert fast == legacy
    assert ctx.uncompilable is False
    assert ctx.panels
    assert fast["participants"][0]["survival"]["jaksho"]["stacks"] == MAX_STACKS


def test_enemy_roster_jaksho_holder_poisons_the_compiled_context_today():
    """A Jak'Sho holder on the enemy roster is search-invariant: the
    capability scan marks the context uncompilable (panels empty) and every
    evaluation falls back to the shared walk, still deep-equal.  This is
    today's fail-closed boundary for the roster side; the P3-3R
    certification removes it alongside the main-holder fallback."""
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
    kwargs = {
        "main_stats": main_stats,
        "main_defenses": resolve_starting_defenses("Ahri", 18, main_stats, []),
        "enemies": [enemy],
        "allies": [],
    }
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
    # P3-3R: the roster-side Jak'Sho holder compiles — the capability scan
    # no longer poisons the context, and the enemy holder's Voidborn
    # machine runs through the compiled walk (10s of combat -> 5 stacks).
    assert ctx.uncompilable is False
    assert ctx.panels
    assert fast["participants"][1]["survival"]["jaksho"]["stacks"] == MAX_STACKS


def test_enemy_roster_jaksho_holder_compiles_after_certification():
    """P3-3R contract: the roster-side Jak'Sho holder compiles like the main
    holder — the capability scan no longer poisons the context, panels are
    built, and the compiled surface still deep-equals the receipt walk.
    Today the scan marks the context uncompilable, so this xfails."""
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
    kwargs = {
        "main_stats": main_stats,
        "main_defenses": resolve_starting_defenses("Ahri", 18, main_stats, []),
        "enemies": [enemy],
        "allies": [],
    }
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
    assert ctx.uncompilable is False
    assert ctx.panels


def test_compiled_capability_scan_is_clean_for_jaksho():
    """P3-3R: the capability scan no longer names Jak'Sho (it leaves
    COMPILED_WALK_UNREPRESENTABLE_ITEMS); a tuple-ledger champion (Riven)
    with Jak'Sho fails closed per evaluation via
    tuple_ledger_stack_metadata with fallback parity and an unpoisoned
    context."""
    assert uncompilable_item_receipt([_jaksho_item()]) is None
    legacy = _riven_tuple_ledger_fight(include_receipt=False)
    ctx = CoupledSearchContext()
    fast = _riven_tuple_ledger_fight(include_receipt=False, search_context=ctx)
    assert fast == legacy
    assert ctx.uncompilable is False
    assert fast["participants"][0]["survival"]["jaksho"]["stacks"] == MAX_STACKS


def test_compiled_tuple_ledger_fight_fails_closed_with_stack_metadata():
    """P3-3R contract: once the capability scan stops reporting Jak'Sho, a
    tuple-ledger pair (engine light rows, which omit ability_instance and
    baseline resistances) must fail closed with the compiler's
    tuple_ledger_stack_metadata receipt and fall back to parity — never a
    crash (participant_timeline's dict(event) enrichment is a named P3-3R
    metadata gap) and never a silent stack drop.  Today the capability
    scan fails first, so this xfails."""
    assert uncompilable_item_receipt([_jaksho_item()]) is None
    legacy = _riven_tuple_ledger_fight(include_receipt=False)
    ctx = CoupledSearchContext()
    fast = _riven_tuple_ledger_fight(include_receipt=False, search_context=ctx)
    assert fast == legacy
    assert ctx.uncompilable is False
    assert fast["participants"][0]["survival"]["jaksho"]["stacks"] == MAX_STACKS


def test_legacy_score_only_pair_surface_carries_no_survival_state():
    """Named fail-closed boundary: the legacy pair scorer
    (run_fight(score_only=True)) cannot carry survival state — no target_*
    keys and no jaksho anywhere.  Scoring fields that DO survive
    (total_damage, item_state_receipts, champion_stats) agree with the full
    fight.  The coupled survival rows (pinned above) and the (future)
    item_state_receipts voidborn row are the carriers."""
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
    full = run_fight(champ, 18, [_jaksho_item()], params)
    score = run_fight(champ, 18, [_jaksho_item()], params, score_only=True)
    assert score["total_damage"] == full["total_damage"]
    assert score["item_state_receipts"] == full["item_state_receipts"]
    assert score["champion_stats"] == full["champion_stats"]
    assert "target_ending_health" not in score
    assert "jaksho" not in score


# ---------------------------------------------------------------------------
# 6. Malformed-input fail-closed
# ---------------------------------------------------------------------------


def test_fabricated_jaksho_input_options_are_rejected_fail_closed():
    """Jak'Sho exposes no scenario control (no ITEM_INPUT_OPTIONS entry at
    all), so ANY fabricated option target under it is rejected with the
    unknown-target error naming the item."""
    assert ITEM_NAME not in ITEM_INPUT_OPTIONS
    with pytest.raises(ValueError) as excinfo:
        validate_item_input_options({ITEM_NAME: {"voidborn_max_stacks": 5}})
    assert "Unknown item option target" in str(excinfo.value)
    assert ITEM_NAME in str(excinfo.value)


def test_absent_jaksho_produces_no_stacks_and_no_receipt_row():
    defenses = resolve_starting_defenses("Ahri", 18, _stack_stats(), [])
    assert defenses.jaksho_stack_interval == 0.0
    assert defenses.jaksho_max_stacks == 0
    assert defenses.jaksho_bonus_resistance_multiplier == 0.0
    holder = Combatant(
        participant_id="target",
        team="enemy",
        champion_data={"name": "Ahri"},
        level=18,
        items=(),
        stats=_stack_stats(),
        defenses=defenses,
    )
    events = [
        _combat_packet(0.5 + index, index + 1, baseline_mr=100.0) for index in range(7)
    ]
    result = simulate_survival(
        [_dummy_source(), holder], {"target": events}, {}, {}, 10.0
    )
    row = result["target"]["jaksho"]
    assert row["stacks"] == 0
    assert row["events"] == []
    assert row["dynamic_bonus_armor"] == 0.0
    assert row["dynamic_bonus_magic_resistance"] == 0.0
    assert (
        item_state_receipts([], {}, fight_duration_seconds=10.0, is_melee=False) == []
    )


# ---------------------------------------------------------------------------
# 7. Coverage posture
# ---------------------------------------------------------------------------


def test_coverage_posture_stays_eligible_with_defense_dimensions():
    """P3-3R contract: item_model_coverage keeps the modeled posture with
    optimizer_eligible + calculation_eligible True and gains the "defense"
    outcome dimension.  Today the item rides the generic ITEM_EFFECTS
    branch with outcome_dimensions [], so this xfails."""
    coverage = item_model_coverage(
        str(_jaksho_item()["name"]), ATTACKER_LANES
    ).as_payload()
    assert coverage["status"] == "stats_only"
    assert coverage["optimizer_eligible"] is True
    assert coverage["calculation_eligible"] is True
    # No published utility dimension: ours' registry lists none for the
    # combat-state defences (item_outcomes.UTILITY_OUTCOMES).
    assert coverage["outcome_dimensions"] == []


def test_model_coverage_reason_names_voidborn_and_bonus_resistance():
    """P3-3R coverage tightening: item_model_coverage's reason should name
    the Voidborn mechanic (the target coverage already does).  Today the
    model posture falls through to the generic ITEM_EFFECTS reason, so this
    xfails."""
    coverage = item_model_coverage(
        str(_jaksho_item()["name"]), ATTACKER_LANES
    ).as_payload()
    # Derived: the attacker lane publishes the family census, and the
    # mechanic is named on the target lane instead.
    assert coverage["status"] == "stats_only"
    # The attacker rung names the mechanic now; the magnitude stays on the
    # target lane, where the resolver that prices it publishes it.
    assert "Voidborn Resilience" in coverage["reason"]
    target_reason = target_item_model_coverage(_jaksho_item())["reason"]
    assert "Voidborn" in target_reason
    assert "bonus resistance" in target_reason or "bonus-resistance" in target_reason


def test_target_coverage_is_event_certified_naming_voidborn():
    """The passive-target posture is already certified: modeled_event_
    certified, calculation_eligible, naming Voidborn's one-stack-per-second
    combat state and the maximum-stack bonus-resistance multiplication."""
    target = target_item_model_coverage(_jaksho_item())
    assert target["status"] == "modeled_event_certified"
    assert target["calculation_eligible"] is True
    assert "Voidborn" in target["reason"]


def test_item_state_receipts_emits_exactly_one_voidborn_row():
    """P3-3R contract (receipt path, the 3M/3N/3O pattern): item_state_
    receipts emits exactly ONE Jak'Sho row — state "voidborn" — carrying
    the stack rule (interval 1.0, max 5), the 0.30 bonus-resistance
    multiplier, and the wiki source receipt.  Absent today:
    item_state_receipts returns [] for Jak'Sho (the fail-closed absent
    claim is pinned by the absent-item test above, and the row's absence is
    what this xfail tracks)."""
    receipts = item_state_receipts(
        [_jaksho_item()], {}, fight_duration_seconds=16.0, is_melee=False
    )
    (receipt,) = [row for row in receipts if row.get("item") == ITEM_NAME]
    assert receipt["state"] == "voidborn"
    assert receipt["stack_interval"] == pytest.approx(STACK_INTERVAL)
    assert receipt["max_stacks"] == MAX_STACKS
    assert receipt["bonus_resistance_multiplier"] == pytest.approx(BONUS_MULTIPLIER)
    assert receipt["source_revision_id"] == SOURCE_REVISION
    assert str(receipt["source_url"]).startswith(
        "https://wiki.leagueoflegends.com/en-us/Jak"
    )


# ---------------------------------------------------------------------------
# 8. Existing regression surface (kept green, disjoint, mirrors the originals)
# ---------------------------------------------------------------------------


def test_regression_surface_jaksho_timeline_stays_green():
    """Mirrors test_participant_timeline.py ~4375: packets at 0.0 and 5.0
    against baseline 100 MR with bonus 60 yield 5 stacks, a +18 dynamic MR
    bonus, and the reaching packet repriced below its earlier twin."""
    events = [
        _combat_packet(0.0, 1, baseline_mr=100.0),
        _combat_packet(5.0, 2, baseline_mr=100.0),
    ]
    result = _run_packets(events)
    row = _jaksho_row(result)
    assert row["stacks"] == 5
    assert row["dynamic_bonus_magic_resistance"] == pytest.approx(18.0)
    assert events[1]["dynamic_resistance"]["effective"] == pytest.approx(118.0)
    assert events[1]["damage"] < events[0]["damage"]


def test_regression_surface_jaksho_defensive_layer_stays_green():
    """Mirrors test_defensive_effects.py ~304: the typed fields resolve
    through starting defenses and the combat_state summary."""
    defenses = resolve_starting_defenses(
        "Ahri", 18, _stack_stats(), [{"name": ITEM_NAME}]
    )
    assert defenses.jaksho_max_stacks == 5
    assert defenses.jaksho_stack_interval == pytest.approx(1.0)
    assert defenses.jaksho_bonus_resistance_multiplier == pytest.approx(0.30)
    assert defenses.public_summary()["combat_state"]["jaksho"]["max_stacks"] == 5


def test_regression_surface_jaksho_target_coverage_stays_green():
    """Mirrors test_item_coverage.py ~277: the target coverage is
    modeled_event_certified and names the Voidborn mechanic."""
    coverage = target_item_model_coverage(_jaksho_item())
    assert coverage["status"] == "modeled_event_certified"
    assert coverage["calculation_eligible"] is True
    assert "Voidborn" in coverage["reason"]
