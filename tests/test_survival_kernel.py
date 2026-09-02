"""Issue #137 Phase 2 — one survival kernel, two ledger adapters.

Contract tests: the optimizer score path (``search_context`` +
:class:`ScoreLedger`) must deep-equal the authoritative receipt walk
(:class:`ReceiptLedger`) for every scenario, across the mechanics the
kernel implements.  Before Phase 2 the two walks were hand-synchronized
mirror implementations that drifted silently (Aphelios Severum); now both
adapters drive one :func:`run_survival_walk` kernel and these tests pin the
adapters.

Every scenario asserts the *full* scoring receipt (participants +
breakdown + duration) equality, plus which path served it:

* ``compiled`` — the score adapter ran the shared kernel (the scenario is
  staged by the compiler);
* ``fallback`` — compilation failed closed with a named receipt and the
  caller fell back to the receipt walk (never a silent drop);
* ``invariant`` — the failure poisoned the context so later evaluations
  skip the compiled path entirely.

Which builds the suite must cover is not a judgement call: the last section
derives the required coverage keys from the registries themselves — every
tuple-incapable event-view holder at *item* granularity and every
cross-participant ``damage_modifier`` producer at *source* granularity, each
reached once from the candidate and once from a roster ally — so a seventh
producer without a fixture fails here on the commit that adds it, including
when that producer is a second packet on an item some fixture already equips
(slice 0A.9).
"""

import math
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import bench_coupled_optimizer as bench
import golden_snapshot as gs

from src.calculator import damage as pair_engine
from src.calculator import shield_ledger
from src.calculator.ability_spec import AttackClass
from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.defensive_effects import StartingDefenses, resolve_starting_defenses
from src.calculator.interpreters import (
    INTERPRETERS,
    active_cast,
    cast_proc,
    delta_amp,
    secondary_target,
)
from src.calculator.interpreters.reactive import thorns_effects
from src.calculator.interpreters.spellblade import (
    resolve_slot as resolve_spellblade_slot,
)
from src.calculator.item_behavior import DefenseField, EngineLane, RuleFamily
from src.calculator.item_behavior_catalog import behavior_rules, rule_owners
from src.calculator.item_effects import DamageInputs, required_effect_value
from src.calculator.item_support_effects import (
    _declared_authorities,
    producer_item,
)
from src.calculator.participant_timeline import (
    Combatant,
    CoupledSearchContext,
    build_participant_timeline,
)
from src.calculator.pipeline import FightParams, run_fight
from src.calculator.program.build import (
    pair_preview_mechanics,
    walk_repriced_mechanics,
)
from src.calculator.program.compile import action_from_event, declared_packet_of
from src.calculator.resistance import apply_magic_penetration, apply_resistance
from src.calculator.scenario import (
    ChampionLoadout,
    parse_scenario_request,
    resolve_scenario,
)
from src.calculator.stats import calculate_total_stats
from src.calculator.survival import (
    EVENT_SLOTS,
    ActionKind,
    ReceiptLedger,
    SurvivalAction,
    TransitionContext,
    TransitionRank,
    build_states,
    run_survival_walk,
    transitions,
)
from src.calculator.survival.compile import thorns_return_damage
from src.calculator.survival.pricing import (
    MITIGATED_DAMAGE_TYPES,
    NO_RESISTANCE_PUBLISHED,
    UNPRICEABLE_DAMAGE_TYPE,
    AuthoredDeclaration,
    BasicAttackSwing,
    DeclaredPacket,
    RoutingProvenance,
    mitigate_declared,
    price_declared_packet,
    route_declared_packet,
    unroute_declared_packet,
)
from src.calculator.trigger_stream import (
    CAPABILITIES,
    Engine,
    ViewTag,
    tuple_incapable_items,
)


def _timeline(
    champion_name,
    level,
    items,
    params,
    enemies,
    allies=(),
    *,
    role="mid",
    **kwargs,
):
    champion = get_champion(champion_name)
    stats = calculate_total_stats(champion, level, items, role=role)
    # The production seam wires item_options into the starting defenses
    # (calculate.py:_combat_receipt); the parity harness must do the same
    # or an explicit active input (Zhonya Time Stop) would be priced by
    # neither walk and the comparison would be trivially equal (P3-3F).
    defenses = resolve_starting_defenses(
        champion_name,
        level,
        stats,
        items,
        item_options=params.item_options,
    )
    return build_participant_timeline(
        champion,
        level,
        items,
        params,
        main_stats=stats,
        main_defenses=defenses,
        enemies=list(enemies),
        allies=list(allies),
        **kwargs,
    )


def _walk_both(champion_name, items, params, enemies, allies, *, level, role):
    """The same fight down both walks: ``(receipt, score, search_context)``.

    Both runs take the scoring subset (``include_receipt=False``) — the
    receipt walk's is the authority the score adapter must reproduce — and
    the context records which path the score adapter actually took."""
    legacy = _timeline(
        champion_name,
        level,
        items,
        params,
        enemies,
        allies,
        role=role,
        include_receipt=False,
    )
    context = CoupledSearchContext()
    fast = _timeline(
        champion_name,
        level,
        items,
        params,
        enemies,
        allies,
        role=role,
        include_receipt=False,
        pair_result_cache={},
        search_context=context,
    )
    return legacy, fast, context


def _assert_rung(name, context, *, compiled, invariant):
    """The score adapter took the documented rung — compiled, fallback or
    poisoned.

    Its own function because the rung is a property of every scenario,
    including one whose two walks are pinned as *disagreeing*: a divergence
    that moved to a different rung is a different divergence."""
    assert (
        context.uncompilable is invariant
    ), f"{name}: expected invariant={invariant}, got {context.uncompilable}"
    if invariant:
        # The failure poisoned the context: no panel may be reused later.
        assert not context.panels, f"{name}: expected no panels after poisoning"
    elif compiled:
        assert context.panels, f"{name}: expected the compiled path to be used"
    else:
        # Candidate-local fallback: the panel may exist (it is built before
        # the fresh compile raises); the context must not be poisoned.
        assert not context.uncompilable


def _assert_contract(
    name,
    champion_name,
    items,
    params,
    enemies,
    allies=(),
    *,
    level=18,
    role="mid",
    compiled=True,
    invariant=False,
    _kv_total_delta=False,
):
    """The score path must deep-equal the receipt path on the whole scoring
    receipt, and must have taken the documented path."""
    legacy, fast, context = _walk_both(
        champion_name, items, params, enemies, allies, level=level, role=role
    )
    if _kv_total_delta:
        # P3 package 3S: the compiled total_damage is the applied-based
        # sum; the legacy total is the outgoing event ledger sum (CC-
        # blocked packets included at full event values).  The CC-blocked
        # attacker's total is the named delta; everything else stays
        # byte-equal.
        for fast_row, legacy_row in zip(
            fast["breakdown"], legacy["breakdown"], strict=False
        ):
            assert fast_row["participant_id"] == legacy_row["participant_id"], name
            assert fast_row["health_damage"] == legacy_row["health_damage"], name
            assert fast_row["healing_received"] == legacy_row["healing_received"], name
            assert fast_row["death_time"] == legacy_row["death_time"], name
            assert fast_row["survived_window"] == legacy_row["survived_window"], name
        assert fast["participants"] == legacy["participants"], name
        assert fast["duration"] == legacy["duration"], name
    else:
        assert fast == legacy, f"{name}: score path diverged from the receipt walk"
    _assert_rung(name, context, compiled=compiled, invariant=invariant)


@cache
def _item(name):
    """One cached item record by name.

    Deliberately *not* a fixed vocabulary: the suite's required item set is
    derived from the registries below, so a scenario reaching a new item may
    not have to extend a hand list to name it (slice 0A.9)."""
    return get_item_by_name(name)


def _roster(champion, level=18, items=(), role="mid", quest=False, ally_effects=False):
    """One roster participant's resolved loadout.

    ``ally_effects`` is load-bearing, not cosmetic: ``derive_item_support_effects``
    early-returns ``[]`` for a participant on the ally team whose request does
    not enable them, so an ally fixture that leaves this False equips its items
    and fires nothing at all.  Every ally-holder fixture below sets it, and it
    is the sole reason any ally-side packet exists to be counted."""
    return ChampionLoadout(
        champion=champion,
        level=level,
        role=role,
        items=items,
        role_quest_complete=quest,
        ally_effects_enabled=ally_effects,
    ).resolve()


# ---------------------------------------------------------------------------
# Compiled scenarios — the score adapter drives the shared kernel
# ---------------------------------------------------------------------------


def test_plain_ad_fight_compiled_walk_equals_receipt_walk():
    """A plain six-item AD fight (no stateful mechanics) rides the compiled
    walk and deep-equals the receipt walk."""
    _assert_contract(
        "plain-AD",
        "Ahri",
        [
            _item(n)
            for n in (
                "Infinity Edge",
                "Rapid Firecannon",
                "Phantom Dancer",
                "Essence Reaver",
                "Lord Dominik's Regards",
                "Berserker's Greaves",
            )
        ],
        FightParams.from_request(
            {
                "fight_mode": "time_based",
                "fight_duration": 10,
                "role": "mid",
                "include_auto_attacks": True,
                "auto_attack_uptime": 1.0,
            },
            deterministic=True,
        ),
        [_roster("Janna")],
    )


def test_taric_1v1_compiled_walk_equals_receipt_walk():
    _assert_contract(
        "taric-1v1",
        "Taric",
        [],
        FightParams.from_request(
            {
                "fight_mode": "time_based",
                "fight_duration": 8,
                "role": "support",
                "include_auto_attacks": True,
                "auto_attack_uptime": 0.5,
            },
            deterministic=True,
        ),
        [_roster("Draven", role="bottom")],
        role="support",
    )


def test_taric_roster_compiled_walk_equals_receipt_walk():
    """Taric with a selected ally: his sourced heals fan out to the roster,
    and the compiled walk must reproduce the receipt exactly."""
    _assert_contract(
        "taric-roster",
        "Taric",
        [],
        FightParams.from_request(
            {
                "fight_mode": "time_based",
                "fight_duration": 8,
                "role": "support",
                "include_auto_attacks": True,
                "auto_attack_uptime": 0.5,
            },
            deterministic=True,
        ),
        [_roster("Draven", role="bottom")],
        [_roster("Ashe", role="bottom")],
        role="support",
    )


def test_support_fan_out_heals_compiled_walk_equals_receipt_walk():
    """Sona/Janna/Milio fan-out heals (caster + selected ally) ride the
    compiled walk and deep-equal the receipt."""
    params = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": 8,
            "role": "support",
            "include_auto_attacks": False,
            "auto_attack_uptime": 0.0,
        },
        deterministic=True,
    )
    for champion in ("Sona", "Janna", "Milio"):
        _assert_contract(
            f"{champion}-fanout",
            champion,
            [],
            params,
            [_roster("Draven", role="bottom")],
            [_roster("Ashe", role="bottom")],
            role="support",
        )


def test_volibear_w_compiled_walk_equals_receipt_walk():
    """Volibear W's mark heal rides the compiled walk."""
    _assert_contract(
        "volibear-W",
        "Volibear",
        [],
        FightParams.from_request(
            {
                "fight_mode": "time_based",
                "fight_duration": 8,
                "role": "top",
                "include_auto_attacks": True,
                "auto_attack_uptime": 0.5,
            },
            deterministic=True,
        ),
        [_roster("Ahri")],
        [_roster("Ashe", role="bottom")],
        role="top",
    )


def test_rakan_q_compiled_walk_equals_receipt_walk():
    """Rakan Q's self + ally heal fan-out rides the compiled walk."""
    _assert_contract(
        "rakan-Q",
        "Rakan",
        [],
        FightParams.from_request(
            {
                "fight_mode": "time_based",
                "fight_duration": 8,
                "role": "support",
                "include_auto_attacks": True,
                "auto_attack_uptime": 0.5,
            },
            deterministic=True,
        ),
        [_roster("Draven", role="bottom")],
        [_roster("Ashe", role="bottom")],
        role="support",
    )


def test_threshold_shield_compiled_walk_equals_receipt_walk():
    """A defense-armed threshold lifeline (Sterak's Gage) is kernel state in
    both adapters: the compiled walk applies it exactly like the receipt."""
    _assert_contract(
        "steraks-threshold",
        "Ahri",
        [_item("Infinity Edge")],
        FightParams.from_request(
            {
                "fight_mode": "time_based",
                "fight_duration": 12,
                "role": "mid",
                "include_auto_attacks": True,
                "auto_attack_uptime": 1.0,
            },
            deterministic=True,
        ),
        [_roster("Janna", items=("Sterak's Gage",))],
    )


def test_starting_stasis_compiled_walk_equals_receipt_walk():
    """Zhonya's explicit Time Stop input is kernel state in both adapters."""
    params = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": 12,
            "role": "mid",
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
            "item_options": {"Zhonya's Hourglass": {"stasis_active_seconds": 2.0}},
        },
        deterministic=True,
    )
    _assert_contract(
        "zhonya-stasis",
        "Ahri",
        [_item("Infinity Edge")],
        params,
        [_roster("Janna")],
    )


def test_taric_invulnerability_compiled_walk_equals_receipt_walk():
    """Taric R's delayed ally state uses the shared kernel in both walks."""
    _assert_contract(
        "taric-r-invulnerability",
        "Taric",
        [],
        FightParams.from_request(
            {
                "fight_mode": "time_based",
                "fight_duration": 8,
                "role": "support",
                "include_auto_attacks": False,
            },
            deterministic=True,
        ),
        [_roster("Janna")],
        allies=[_roster("Jinx", role="bottom")],
        role="support",
    )


def test_champion_revive_compiled_walk_equals_receipt_walk():
    """A champion-passive revive (Zac Cell Division) authors one candidate
    per incoming damaging packet in both adapters; the compiled walk applies
    the kernel's revive transition exactly like the receipt."""
    _assert_contract(
        "zac-revive",
        "Zac",
        [],
        FightParams.from_request(
            {
                "fight_mode": "time_based",
                "fight_duration": 12,
                "role": "top",
                "include_auto_attacks": True,
                "auto_attack_uptime": 1.0,
            },
            deterministic=True,
        ),
        [_roster("Janna")],
        role="top",
    )


# ---------------------------------------------------------------------------
# Fail-closed scenarios — compilation raises a named receipt, the caller
# falls back to the receipt walk, and the receipts still agree
# ---------------------------------------------------------------------------


def test_aphelios_severum_score_path_matches_receipt():
    """Severum's overheal-to-shield is a champion-authored transition: the
    compiler raises per evaluation and the caller falls back — the score
    receipt still deep-equals the receipt walk (the Phase 1 drift case)."""
    params = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": 20,
            "role": "bottom",
            "champion_options": {"aphelios_main_weapon": "severum"},
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
            "cast_order": ["R", "Q", "W", "E"],
        },
        deterministic=True,
    )
    for items in (
        [],
        [
            _item(n)
            for n in (
                "Infinity Edge",
                "Rapid Firecannon",
                "Phantom Dancer",
                "Essence Reaver",
                "Lord Dominik's Regards",
                "Berserker's Greaves",
            )
        ],
    ):
        _assert_contract(
            "aphelios-severum",
            "Aphelios",
            items,
            params,
            [_roster("Janna", role="support")],
            level=18,
            role="bottom",
            compiled=False,
        )


def test_roster_warmog_heart_rides_compiled_walk():
    """A roster actor's active Warmog's Heart compiles once per search
    (issue #169): the base panel authors the same gated, live max-health
    ticks the receipt walk authors, and the score receipt deep-equals it.
    Constant pressure keeps every tick behind the damage-free gate; a
    sparse-caster window lets later ticks through it."""
    warmog_mundo = _roster(
        "Dr. Mundo",
        level=18,
        items=("Warmog's Armor", "Heartsteel", "Randuin's Omen"),
        role="top",
    )
    _assert_contract(
        "warmog-roster-gated",
        "Cassiopeia",
        [_item("Rabadon's Deathcap")],
        FightParams.from_request(
            {"fight_mode": "one_rotation", "role": "mid"}, deterministic=True
        ),
        [warmog_mundo],
        level=13,
    )
    _assert_contract(
        "warmog-roster-tick-mix",
        "Janna",
        [],
        FightParams.from_request(
            {
                "fight_mode": "time_based",
                "fight_duration": 20,
                "role": "support",
                "include_auto_attacks": False,
                "auto_attack_uptime": 0.0,
            },
            deterministic=True,
        ),
        [warmog_mundo],
        role="support",
    )


def test_enemy_actor_wide_heal_keeps_main_pair_copy_with_allies():
    """An enemy attacker's actor-wide heal copies may be priced differently
    per pair fight (Dr. Mundo's Maximum Dosage); the legacy dedup keeps the
    main-pair copy because an enemy's ordered defenders are [main, *allies].
    The compiled walk must replicate that precedence — the ally-pair copies
    are suppressed in the base panel — and deep-equal the receipt (issue
    #169's five-champion regression shape)."""
    _assert_contract(
        "enemy-actor-wide-precedence",
        "Cassiopeia",
        [_item("Rabadon's Deathcap")],
        FightParams.from_request(
            {"fight_mode": "one_rotation", "role": "mid"}, deterministic=True
        ),
        [
            _roster(
                "Alistar",
                level=13,
                items=("Randuin's Omen", "Bramble Vest"),
                role="support",
            ),
            _roster(
                "Dr. Mundo",
                level=13,
                items=("Kaenic Rookern", "Warmog's Armor", "Spirit Visage"),
                role="top",
            ),
        ],
        [_roster("Alistar", level=13, items=("Dead Man's Plate",), role="support")],
        level=13,
    )


def test_secondary_target_allocation_matches_receipt_composition():
    """Every compiled pair fight must carry the same ordered roster-target
    allocation the receipt composition sets (issue #169): a cleave item's
    secondary-target branch prices against the second enemy identically on
    both paths.  Ravenous Hydra also holds omnivamp, so this pins the
    allocation together with compiled vamp healing."""
    _assert_contract(
        "cleave-secondary-target",
        "Dr. Mundo",
        [get_item_by_name("Ravenous Hydra")],
        FightParams.from_request(
            {"fight_mode": "one_rotation", "role": "top"}, deterministic=True
        ),
        [
            _roster(
                "Cassiopeia",
                level=13,
                items=("Rabadon's Deathcap", "Void Staff"),
                role="mid",
            ),
            _roster(
                "Vayne",
                level=13,
                items=("Kraken Slayer", "Phantom Dancer"),
                role="bottom",
            ),
        ],
        level=13,
        role="top",
    )


def test_vamp_candidate_rides_compiled_walk():
    """Lifesteal/omnivamp builds compile (issue #169): compiled heal actions
    carry ``healing_category`` so the vamp carve-outs — the received-healing
    multiplier exemption and Bloodthirster's ichor conversion — match the
    receipt walk exactly."""
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
    # Full-health lifesteal converts its overheal into the ichor shield.
    _assert_contract(
        "bloodthirster-ichor",
        "Ahri",
        [_item("Bloodthirster"), _item("Infinity Edge")],
        params,
        [_roster("Cassiopeia")],
    )
    # Omnivamp beside Spirit Visage: the received-healing multiplier must
    # keep exempting vamp heals on the compiled path.
    _assert_contract(
        "omnivamp-spirit-visage",
        "Ahri",
        [_item("Hextech Gunblade"), _item("Spirit Visage")],
        params,
        [_roster("Cassiopeia")],
    )


def test_grievous_builds_ride_compiled_walk():
    """Grievous Wounds builds compile end-to-end (issue #169, replacing the
    routing hint): the candidate's own wound pack prices enemy healing, and a
    roster wound prices the candidate's vamp healing."""
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
    # Candidate Morellonomicon wounds a self-healing enemy.
    _assert_contract(
        "morello-candidate",
        "Ahri",
        [_item("Morellonomicon"), _item("Rabadon's Deathcap")],
        params,
        [_roster("Dr. Mundo", items=("Spirit Visage", "Kaenic Rookern"), role="top")],
    )
    # Roster Morellonomicon + Vampiric Scepter: the enemy's wound reduces the
    # vamp candidate's healing, and the enemy's own vamp heals compile too.
    _assert_contract(
        "morello-roster",
        "Ahri",
        [_item("Bloodthirster"), _item("Infinity Edge")],
        params,
        [_roster("Cassiopeia", items=("Morellonomicon", "Vampiric Scepter"))],
    )


def test_collector_execute_falls_back():
    """The Collector's execute threshold is an authored terminal transition;
    the compiler raises per evaluation and the score receipt deep-equals the
    receipt."""
    _assert_contract(
        "collector-execute",
        "Ahri",
        [_item("The Collector"), _item("Infinity Edge"), _item("Rapid Firecannon")],
        FightParams.from_request(
            {
                "fight_mode": "time_based",
                "fight_duration": 10,
                "role": "mid",
                "include_auto_attacks": True,
                "auto_attack_uptime": 1.0,
            },
            deterministic=True,
        ),
        [_roster("Janna")],
        compiled=False,
    )


def test_deaths_dance_deferral_falls_back():
    """Death's Dance Ignore Pain ticks and Defy are authored by the receipt
    walk; the capability report routes the build to the receipt path and the
    score receipt deep-equals it."""
    _assert_contract(
        "deaths-dance-defer",
        "Ahri",
        [_item("Death's Dance"), _item("Infinity Edge")],
        FightParams.from_request(
            {
                "fight_mode": "time_based",
                "fight_duration": 10,
                "role": "mid",
                "include_auto_attacks": True,
                "auto_attack_uptime": 1.0,
            },
            deterministic=True,
        ),
        [_roster("Janna")],
        compiled=False,
    )


def test_knights_vow_redirect_compiles_and_stays_byte_parity():
    """Knight's Vow's Worthy redirect is staged by the compiled path (P3
    package 3S): the roster capability report does not poison the
    context, the compiled panels ride the shared kernel, and the survival
    rows stay byte-equal to the legacy walk.  The CC-blocked attacker's
    total_damage is the documented delta (the receipt/legacy totals are
    the outgoing event ledger sum; the compiled total is the applied-based
    sum)."""
    _assert_contract(
        "knights-vow-redirect",
        "Ahri",
        [_item("Infinity Edge")],
        FightParams.from_request(
            {
                "fight_mode": "time_based",
                "fight_duration": 12,
                "role": "mid",
                "include_auto_attacks": True,
                "auto_attack_uptime": 1.0,
            },
            deterministic=True,
        ),
        [_roster("Janna")],
        [_roster("Ashe", role="bottom", items=("Knight's Vow",))],
        compiled=True,
        invariant=False,
        _kv_total_delta=True,
    )


def test_receipt_and_score_adapters_share_one_kernel():
    """Unit-level pin: the same typed action applied through the receipt
    ledger and the score ledger produces identical survival rows."""

    from src.calculator.participant_timeline import Combatant
    from src.calculator.program.build import roster_program
    from src.calculator.program.compile import action_from_event
    from src.calculator.program.views.survival import survival
    from src.calculator.program.walk import walk as run_one_walk
    from src.calculator.survival import (
        EVENT_SLOTS,
        ActionKind,
        ReceiptLedger,
        ScoreLedger,
        SurvivalAction,
        TransitionContext,
        TransitionRank,
        build_states,
    )

    combatant = Combatant(
        participant_id="target",
        team="enemy",
        champion_data={"name": "target"},
        level=1,
        items=(),
        stats={"health": 100.0, "is_melee": True},
        defenses=StartingDefenses(
            magic_shield=0.0,
            physical_shield=0.0,
            general_shield=0.0,
            healing_received_multiplier=1.0,
        ),
    )
    actions = [
        SurvivalAction(
            sort_key=(0.0, TransitionRank.DAMAGE, 0, 0, 0, "target", "hit", "auto"),
            time=0.0,
            phase=TransitionRank.DAMAGE,
            kind=ActionKind.PLAIN_DAMAGE,
            subject=0,
            attacker=0,
            aidx=0,
            amount=60.0,
            damage_type="physical",
            source_key="auto_attacks",
            source="auto_attacks",
            event_slot=EVENT_SLOTS.slot("hit"),
            sequence=0,
        ),
        SurvivalAction(
            sort_key=(
                1.0,
                TransitionRank.DEBUFF_ARM,
                0,
                0,
                0,
                "target",
                "heal",
                "heal",
            ),
            time=1.0,
            phase=TransitionRank.RECOVERY,
            kind=ActionKind.HEAL,
            subject=0,
            attacker=0,
            aidx=1,
            amount=50.0,
            source_key="heal",
            source="heal",
            event_slot=EVENT_SLOTS.slot("heal"),
            sequence=0,
        ),
    ]

    def _walk(ledger_cls, annotate):
        states = build_states([combatant], (0.0,))
        if ledger_cls is ReceiptLedger:
            ledger = ledger_cls(
                actions=[a._replace(event={}) for a in actions],
                index_of={"target": 0},
                compile_event=action_from_event,
                annotating=annotate,
            )
        else:
            ledger = ledger_cls(len(actions))
        ctx = TransitionContext(
            duration=5.0,
            states=states,
            combatants=[combatant],
            index_of={"target": 0},
            ledger=ledger,
            regeneration_windows=(None,),
        )
        result = run_one_walk(
            (
                actions
                if ledger_cls is ScoreLedger
                else [a._replace(event={}) for a in actions]
            ),
            ctx,
        )
        return survival(roster_program([combatant]), result)["target"]

    receipt_row = _walk(ReceiptLedger, annotate=False)
    score_row = _walk(ScoreLedger, annotate=False)
    assert score_row == receipt_row
    assert score_row["ending_health"] == 90.0
    assert score_row["healing_received"] == 50.0


def test_compiled_support_arms_at_the_rank_the_walk_reads():
    """The compiled support branch reads the walk's classifier, not a kind.

    A shield whose author declares ``LATE_BARRIER`` (the rank Eclipse's
    self-shield and Fimbulwinter's Everlasting use for a barrier placed
    *after* the damage that triggered it) is representable: it has no
    duration, no amount formula and no trigger link, so
    ``unrepresentable_template_receipt`` returns ``None`` and it compiles.
    While the compiled branch classified by kind alone it armed such a
    packet before damage while the receipt walk armed it after — a desync
    no equality gate could see, because every ``LATE_BARRIER`` author in
    the tree today is excluded by one of the other three receipts.
    """
    from src.calculator.program.compile import WalkCompiler
    from src.calculator.survival import (
        EVENT_SLOTS,
        SUPPORT_RANK_KEY,
        TransitionRank,
        support_transition_rank,
    )
    from src.calculator.survival.actions import ordering_slot
    from src.calculator.survival.compile import unrepresentable_template_receipt

    declared = {
        "target": "main",
        "kind": "shield",
        "amount": 40.0,
        "duration": 0.0,
        "time": 1.0,
        "source": "Declared Late Barrier",
        "source_key": "declared_late_barrier",
        "_event_id": "declared:late",
        SUPPORT_RANK_KEY: TransitionRank.LATE_BARRIER,
    }
    plain = {**declared, "_event_id": "plain:barrier"}
    del plain[SUPPORT_RANK_KEY]

    # Both are compilable, so neither is protected by a fail-closed receipt.
    assert unrepresentable_template_receipt(declared) is None
    assert unrepresentable_template_receipt(plain) is None

    compiler = WalkCompiler()
    compiler.add_support_templates([declared, plain], 0, {"main": 0})
    by_event = {
        EVENT_SLOTS.text(action.event_slot): action for action in compiler.actions
    }

    for template in (declared, plain):
        expected = support_transition_rank(template)
        action = by_event[template["_event_id"]]
        assert action.phase is expected
        assert action.sort_key[1] is ordering_slot(expected)

    # The declaration is what separates them: same kind, different arming.
    assert by_event["declared:late"].phase is TransitionRank.LATE_BARRIER
    assert by_event["plain:barrier"].phase is TransitionRank.BARRIER_GRANT


# ---------------------------------------------------------------------------
# Registry-derived coverage (slice 0A.9)
#
# What this suite owes a fixture is READ from the two registries that already
# know — the tuple-incapable event-view set and the derived cross-participant
# ``damage_modifier`` producer set — never typed out here.  A hand list would
# be a second home for a fact the registries state, which is the failure shape
# the campaign exists to kill.  Coverage is measured off the receipt's public
# ``support_events`` rows rather than off the fixture's item lists: an equipped
# item whose packet never fires is a fixture that proves nothing.
#
# The two registries are required at different granularities, because they
# name different things.  An event-view holder's mechanic is "this item makes
# the pipeline build the enriched per-event view", which is a property of the
# item, so it is required by item name.  A producer's mechanic is one packet,
# and ``item_support_effects.py`` already ships two packets on one item
# (``Dream Maker — Blue/Purple Dream Bubble``), so requiring producers by item
# would let a second packet on a covered item ride in uncovered.  Producers are
# therefore required by their ``source`` literal, and a fixture is credited for
# both the source and its item on every row it fires.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Holder:
    """One roster participant and the items it carries into the fight.

    Two of these fields change the loadout rather than describing it, so both
    are stated here rather than left to be discovered:

    * a holder carrying items has completed its role quest (``quest`` is
      ``bool(items)`` in :meth:`resolve`), because half the required set is
      support-quest gear and an unfinished quest would change what the fixture
      equips rather than what it reaches;
    * ``ally_effects`` enables the ally-side packet path — see :func:`_roster`
      — and without it an ally holder equips its build and fires nothing."""

    champion: str
    items: tuple[str, ...] = ()
    role: str = "mid"
    level: int = 18
    ally_effects: bool = False

    def resolve(self):
        """The loadout the timeline builder consumes."""
        return _roster(
            self.champion,
            level=self.level,
            items=self.items,
            role=self.role,
            quest=bool(self.items),
            ally_effects=self.ally_effects,
        )


@dataclass(frozen=True, slots=True)
class KernelFixture:
    """One compiled-vs-receipt scenario, and what it puts on the board.

    ``pinned_divergence`` is a *characterization*: a named, reproduced
    disagreement between the two walks that Phase 0A may not fix, because 0A
    moves no number in ``src/``.  A pinned fixture asserts the walks still
    disagree, so the commit that fixes the mechanic turns this suite red and
    its author has to read the reason rather than inherit it.
    """

    name: str
    champion: str
    items: tuple[str, ...]
    enemies: tuple[Holder, ...]
    allies: tuple[Holder, ...] = ()
    role: str = "mid"
    level: int = 18
    duration: float = 8.0
    compiled: bool = True
    invariant: bool = False
    pinned_divergence: str = ""

    def params(self):
        """This fixture's deterministic time-based request."""
        return FightParams.from_request(
            {
                "fight_mode": "time_based",
                "fight_duration": self.duration,
                "role": self.role,
                "include_auto_attacks": True,
                "auto_attack_uptime": 1.0,
            },
            deterministic=True,
        )

    def walk_both(self):
        """``(receipt, score, search_context)`` for this fixture."""
        return _walk_both(
            self.champion,
            [_item(name) for name in self.items],
            self.params(),
            [holder.resolve() for holder in self.enemies],
            [holder.resolve() for holder in self.allies],
            level=self.level,
            role=self.role,
        )

    def receipt(self):
        """The annotating receipt — the only mode carrying the support rows."""
        return _timeline(
            self.champion,
            self.level,
            [_item(name) for name in self.items],
            self.params(),
            [holder.resolve() for holder in self.enemies],
            [holder.resolve() for holder in self.allies],
            role=self.role,
            include_receipt=True,
        )


# Four candidate-holder fixtures and their four ally-holder rung variants.
# The candidate builds ride the compiled or the candidate-local fallback rung.
# An ally build poisons the search context when its holder carries a
# ``damage_modifier`` producer, which three of the four do — that is the rung
# difference these variants exist to pin.  ``takedown_ally`` is the stated
# exception: Cryptbloom is an event-view holder and not a producer, so its
# ally roster stays compilable and what it pins is a dropped packet on an
# un-poisoned context rather than a poisoning.
_CC_TRIGGER_BUILD = (
    "Imperial Mandate",
    "Bandlepipes",
    "Solstice Sleigh",
    "Fimbulwinter",
)
_EVENT_SCAN_BUILD = (
    "Black Cleaver",
    "Bloodletter's Curse",
    "Bloodsong",
    "Phage",
    "Abyssal Mask",
)
_ENCHANTER_BUILD = ("Dream Maker", "Echoes of Helia")
_TAKEDOWN_BUILD = ("Cryptbloom",)

# A level-1 enemy is what makes the takedown fixtures reach a takedown at
# all: Cryptbloom's Life From Death fires on a kill, and a level-18 enemy
# survives the window.
_LIVE_ENEMY = (Holder("Aatrox", role="top"),)
_DOOMED_ENEMY = (Holder("Aatrox", role="top", level=1),)

REGISTRY_FIXTURES = (
    KernelFixture(
        name="cc_trigger_candidate",
        champion="Ahri",
        items=_CC_TRIGGER_BUILD,
        enemies=_LIVE_ENEMY,
        allies=(Holder("Pantheon", role="support"),),
        compiled=False,
    ),
    KernelFixture(
        name="event_scan_candidate",
        champion="Ahri",
        items=_EVENT_SCAN_BUILD,
        enemies=_LIVE_ENEMY,
        allies=(Holder("Pantheon", role="support"),),
    ),
    KernelFixture(
        name="enchanter_trigger_candidate",
        champion="Lulu",
        items=_ENCHANTER_BUILD,
        enemies=_LIVE_ENEMY,
        allies=(Holder("Jax", role="top"),),
        role="support",
    ),
    KernelFixture(
        name="takedown_candidate",
        champion="Ahri",
        items=_TAKEDOWN_BUILD,
        enemies=_DOOMED_ENEMY,
        allies=(Holder("Pantheon", role="support"),),
        duration=20.0,
    ),
    KernelFixture(
        name="cc_trigger_ally",
        champion="Ahri",
        items=(),
        enemies=_LIVE_ENEMY,
        allies=(
            Holder(
                "Pantheon",
                items=_CC_TRIGGER_BUILD,
                role="support",
                ally_effects=True,
            ),
        ),
        compiled=False,
        invariant=True,
    ),
    KernelFixture(
        name="event_scan_ally",
        champion="Ahri",
        items=(),
        enemies=_LIVE_ENEMY,
        allies=(
            Holder(
                "Pantheon",
                items=_EVENT_SCAN_BUILD,
                role="support",
                ally_effects=True,
            ),
        ),
        compiled=False,
        invariant=True,
    ),
    KernelFixture(
        name="enchanter_trigger_ally",
        champion="Ahri",
        items=(),
        enemies=_LIVE_ENEMY,
        allies=(
            Holder("Lulu", items=_ENCHANTER_BUILD, role="support", ally_effects=True),
        ),
        compiled=False,
        invariant=True,
    ),
    KernelFixture(
        name="takedown_ally",
        champion="Ahri",
        items=(),
        enemies=_DOOMED_ENEMY,
        allies=(
            Holder(
                "Pantheon",
                items=_TAKEDOWN_BUILD,
                role="support",
                ally_effects=True,
            ),
        ),
        duration=20.0,
        pinned_divergence=(
            "a roster ally's takedown-triggered support packets never reach "
            "the compiled score path: the receipt composition passes "
            "target_id=defender.participant_id into _support_effect_templates "
            "while the base and signature panels pass no target_id at all, so "
            "the takedown synthesis that reads it never fires and Cryptbloom's "
            "Life From Death authors zero packets"
        ),
    ),
)


def required_coverage_keys() -> frozenset[str]:
    """Every key this suite owes a fixture, read from the registries.

    ``tuple_incapable_items()`` is the tuple-incapable set the pipeline's
    tuple gate consults, and contributes item names;
    ``_declared_authorities()`` is the ``damage_modifier`` producer
    table, and contributes ``source`` literals — one key per packet, not per
    item, so a second packet on an already-equipped item is its own
    requirement.  Neither registry is restated here, so a new event-view
    holder or a seventh producer becomes a required key on the commit that
    adds it — and fails this suite until it has a fixture.

    Both now project one declaration table.  The item half read the hand set
    ``item_support_effects.EVENT_VIEW_SUPPORT_ITEMS`` until Phase 2's P2c
    deleted it, and the producer half read that module's ``ast`` derivation
    over its own call sites until the same commit; both are
    ``trigger_stream.CAPABILITIES`` projections now.
    """
    return tuple_incapable_items() | frozenset(_declared_authorities())


@cache
def _reached_keys(fixture: KernelFixture) -> tuple[frozenset[str], frozenset[str]]:
    """``(candidate-authored, ally-authored)`` keys this fixture really fires.

    Read off the receipt's public ``support_events`` rows and attributed by
    each packet's own ``attacker``, so a fixture that equips an item without
    ever reaching its packet contributes no coverage.  Each row credits both
    granularities the registries use: the packet's own ``source`` literal and
    the item that source names.
    """
    candidate: set[str] = set()
    ally: set[str] = set()
    for event in fixture.receipt().get("support_events", ()):
        source = str(event.get("source", ""))
        keys = {source, producer_item(source)}
        attacker = str(event.get("attacker", ""))
        if attacker == "main":
            candidate |= keys
        elif attacker.startswith("ally:"):
            ally |= keys
    return frozenset(candidate), frozenset(ally)


@cache
def _fixture_coverage() -> tuple[frozenset[str], frozenset[str]]:
    """``(candidate, ally)`` keys the whole fixture set reaches between them."""
    candidate: frozenset[str] = frozenset()
    ally: frozenset[str] = frozenset()
    for fixture in REGISTRY_FIXTURES:
        reached_candidate, reached_ally = _reached_keys(fixture)
        candidate |= reached_candidate
        ally |= reached_ally
    return candidate, ally


def missing_fixtures(
    required: frozenset[str],
    candidate_reached: frozenset[str],
    ally_reached: frozenset[str],
) -> tuple[tuple[str, str], ...]:
    """Every ``(key, side)`` a required key is owed and does not have.

    One pure function over three sets, so the check's own red is reproducible
    on demand instead of being a claim about the past (R-05).
    """
    return tuple(
        sorted(
            (key, side)
            for key in required
            for side, reached in (
                ("candidate", candidate_reached),
                ("ally", ally_reached),
            )
            if key not in reached
        )
    )


def _differing_leaves(left: Any, right: Any, path: str = "") -> tuple[str, ...]:
    """Every leaf path at which two scoring receipts disagree."""
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return tuple(
            leaf
            for key in sorted(set(left) | set(right))
            for leaf in _differing_leaves(
                left.get(key), right.get(key), f"{path}.{key}"
            )
        )
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return (f"{path}[]",)
        return tuple(
            leaf
            for index, (one, other) in enumerate(zip(left, right, strict=False))
            for leaf in _differing_leaves(one, other, f"{path}[{index}]")
        )
    return () if left == right else (path,)


def _ally_survival(result: Mapping[str, Any]) -> Mapping[str, Any]:
    """The one roster ally's survival row of a scoring receipt."""
    allies = [
        participant
        for participant in result["participants"]
        if participant["team"] == "ally"
    ]
    assert len(allies) == 1, "the pinned fixture carries exactly one roster ally"
    return allies[0]["survival"]


@pytest.mark.parametrize(
    "fixture", REGISTRY_FIXTURES, ids=[fixture.name for fixture in REGISTRY_FIXTURES]
)
def test_registry_fixture_pins_the_two_walks(fixture):
    """Every registry-derived fixture pins the two walks against each other.

    A fixture carrying no ``pinned_divergence`` must deep-equal; a pinned one
    must still disagree, and the day it stops disagreeing the pin is what
    forces its fixer to read the reason.
    """
    if not fixture.pinned_divergence:
        _assert_contract(
            fixture.name,
            fixture.champion,
            [_item(name) for name in fixture.items],
            fixture.params(),
            [holder.resolve() for holder in fixture.enemies],
            [holder.resolve() for holder in fixture.allies],
            level=fixture.level,
            role=fixture.role,
            compiled=fixture.compiled,
            invariant=fixture.invariant,
        )
        return
    legacy, fast, context = fixture.walk_both()
    assert fast != legacy, (
        f"{fixture.name}: the pinned divergence is gone — "
        f"{fixture.pinned_divergence}.  Delete the pin in the commit that "
        "fixed it."
    )
    # The rung is pinned for a pinned fixture too — the whole rung, through
    # the same helper the equality fixtures use: a divergence that moved to a
    # different rung is a different divergence.
    _assert_rung(
        fixture.name, context, compiled=fixture.compiled, invariant=fixture.invariant
    )


def test_pinned_ally_takedown_divergence_is_the_dropped_nova_heal():
    """The pinned divergence is exactly a lost heal, named leaf by leaf.

    The receipt walk heals the roster ally with Cryptbloom's takedown nova;
    the compiled score path heals it by nothing at all, and every differing
    leaf is a consequence of that one missing packet.  Pinning the mechanism
    rather than a diff count is what stops this from silently becoming a
    *different* divergence of the same size.
    """
    fixture = next(f for f in REGISTRY_FIXTURES if f.name == "takedown_ally")
    legacy, fast, _context = fixture.walk_both()

    # The heal ARRIVING is the fact, not the headroom it found: this
    # roster's enemy dies before it damages the ally, so the nova lands
    # on a full-health ally and is paid entirely as overheal.  Reading
    # ``healing_received`` alone would call an applied packet a dropped
    # one the moment the ally happens to be topped up.
    def _healed(payload):
        row = _ally_survival(payload)
        return float(row["healing_received"]) + float(row["overhealing"])

    assert _healed(legacy) > 0.0
    assert _healed(fast) == 0.0

    _, ally_reached = _reached_keys(fixture)
    assert (
        "Cryptbloom — Life From Death" in ally_reached
    ), "the receipt walk must author the nova heal"

    # Every leaf that moved is a healing or health consequence of the drop.
    leaves = _differing_leaves(legacy, fast)
    assert leaves, "the pinned divergence must still reproduce"
    assert all(
        leaf.rsplit(".", 1)[-1]
        in {
            "effective_health",
            "ending_health",
            "ending_health_ratio",
            "healing_output",
            "healing_received",
            "overhealing",
            "support_value",
        }
        for leaf in leaves
    ), f"the pinned divergence changed shape: {leaves}"


def test_every_fixture_item_name_resolves():
    """Every name the fixture table equips is a real item record.

    Records load lazily through :func:`_item`, so a renamed or misspelled name
    surfaces as a ``KeyError`` inside whichever contract test happened to reach
    it first — the eager module-level dict this table replaced failed at
    collection instead.  Resolving the whole vocabulary in one place restores
    a single named failure that says which name went away, and the negative
    half proves the resolution can fail at all (R-05).
    """
    names = sorted(
        {name for fixture in REGISTRY_FIXTURES for name in fixture.items}
        | {
            name
            for fixture in REGISTRY_FIXTURES
            for holder in fixture.enemies + fixture.allies
            for name in holder.items
        }
    )
    assert names, "the fixture table equips nothing"
    for name in names:
        assert str(_item(name)["name"]) == name, f"{name}: resolved to another record"
    with pytest.raises(KeyError):
        _item("No Such Item")


def test_the_rung_pin_rejects_a_mis_declared_rung():
    """The rung pin's own red, on demand (R-05).

    A pinned fixture's rung is asserted by the pin rather than by
    :func:`_assert_contract`, so a pin that never checked the rung would be
    indistinguishable from one that did.  Both halves of the check are driven
    with real contexts: ``takedown_ally`` compiles and is not poisoned, so
    declaring it poisoned must fail, and ``cc_trigger_candidate`` takes the
    candidate-local fallback with no panel, so declaring it compiled must fail.
    """
    pinned = next(f for f in REGISTRY_FIXTURES if f.name == "takedown_ally")
    _, _, compiled_context = pinned.walk_both()
    fallback = next(f for f in REGISTRY_FIXTURES if f.name == "cc_trigger_candidate")
    _, _, fallback_context = fallback.walk_both()

    _assert_rung("takedown_ally", compiled_context, compiled=True, invariant=False)
    with pytest.raises(AssertionError):
        _assert_rung("takedown_ally", compiled_context, compiled=True, invariant=True)
    with pytest.raises(AssertionError):
        _assert_rung(
            "cc_trigger_candidate", fallback_context, compiled=True, invariant=False
        )


def test_every_registry_key_has_a_candidate_and_an_ally_fixture():
    """The required set is derived, and every key is reached from both sides.

    Both halves are computed: the required keys from the registries, the
    covered ones from the packets the fixtures actually authored.  A seventh
    ``damage_modifier`` producer, or a new event-view holder, therefore fails
    here on the commit that adds it rather than being assumed covered.

    Credit is awarded off the *receipt* walk, which is the authority the score
    adapter must reproduce — not off the compiled score path.  A key reached
    only by a fixture carrying a ``pinned_divergence`` is therefore credited
    here while the compiled path is known to drop it; ``Cryptbloom — Life From
    Death`` on the ally side is exactly that today.  What holds that case is
    the pin in :func:`test_registry_fixture_pins_the_two_walks`, not this
    check: coverage answers "does a fixture reach the mechanic", equality
    answers "do the two walks agree about it".
    """
    required = required_coverage_keys()
    # Neither half may be empty, or the check below is green over nothing.
    assert tuple_incapable_items()
    assert _declared_authorities()
    assert required >= tuple_incapable_items()
    assert required >= frozenset(_declared_authorities())

    candidate_reached, ally_reached = _fixture_coverage()
    missing = missing_fixtures(required, candidate_reached, ally_reached)
    assert not missing, f"registry keys no fixture reaches: {missing}"


def test_an_undeclared_producer_fails_the_coverage_check():
    """The coverage check's own red, on demand (R-05).

    A seventh ``damage_modifier`` producer with no fixture is reported for
    both sides; nothing about the check can pass by being silent.
    """
    covered = required_coverage_keys()
    assert missing_fixtures(covered | {"Seventh Producer"}, covered, covered) == (
        ("Seventh Producer", "ally"),
        ("Seventh Producer", "candidate"),
    )
    assert missing_fixtures(covered, covered, covered) == ()


def test_a_second_producer_on_a_covered_item_fails_the_coverage_check(monkeypatch):
    """The red for the case item-granularity coverage could not see (R-05).

    A producer added as a *second* packet on an item some fixture already
    equips and already fires — the shape ``Dream Maker`` ships today and the
    shape Phase 0B's Abyssal Mask work adds — is reported missing on both
    sides, driven end to end through the real derivation rather than through
    hand-built sets.
    """
    extra = "Black Cleaver — Brand New Effect"
    assert producer_item(extra) in _fixture_coverage()[0], (
        "the counterexample only bites when the item itself is already "
        "covered on the candidate side"
    )
    declared = dict(_declared_authorities())
    monkeypatch.setattr(
        "tests.test_survival_kernel._declared_authorities",
        lambda: {**declared, extra: None},
    )
    candidate_reached, ally_reached = _fixture_coverage()
    assert missing_fixtures(
        required_coverage_keys(), candidate_reached, ally_reached
    ) == ((extra, "ally"), (extra, "candidate"))


# ---------------------------------------------------------------------------
# From-declaration pricing — the arithmetic (umbrella Amendment L, Ruling 3)
# ---------------------------------------------------------------------------
#
# The walk consumes the pair engine's post-mitigation rows and, where the
# subject's resistance moves, recovers the pre-mitigation side by ratio.  A
# family that declares its own damage brings a raw value and no mitigation to
# divide out, so it has nowhere to hand a price.  `survival/pricing.py` is
# that home; this section pins its arithmetic, its refusals, and the fact that
# the tree's one older from-raw producer now reads it rather than spelling the
# same step again.


@dataclass(frozen=True)
class _PricingHolder:
    """A participant as the strike-back pricer reads one: a stat block.

    `thorns_return_damage` takes the wearer and the striker and reads exactly
    `.stats` off each, so this is the whole of the interface — a full
    `Combatant` would hide which fields the price actually depends on.
    """

    stats: Mapping[str, float]


class TestRawDeclaredDamageBecomesAMitigatedNumber:
    """`mitigate_declared` — one raw magnitude at one resistance."""

    def test_a_positive_resistance_reduces_the_declaration(self):
        """The one resistance formula, not a second copy of it."""
        assert mitigate_declared(252.0, "magic", 67.0) == apply_resistance(252.0, 67.0)
        assert mitigate_declared(100.0, "physical", 100.0) == 50.0

    def test_a_negative_resistance_amplifies_it(self):
        """Negative resistance is a real state, and it is the formula's."""
        assert mitigate_declared(100.0, "magic", -100.0) == apply_resistance(
            100.0, -100.0
        )

    def test_true_damage_meets_no_resistance(self):
        """Priced, never refused: the resistance handed in is ignored."""
        assert mitigate_declared(300.0, "true", 9999.0) == 300.0

    def test_a_negative_declaration_cannot_become_a_heal(self):
        """A declaration is a magnitude, so the floor is at zero.

        Without it a malformed declaration would mitigate into a negative
        number the walk would subtract from a total — a family paying its
        subject rather than damaging it, which no receipt would name.
        """
        assert mitigate_declared(-40.0, "magic", 50.0) == 0.0
        assert mitigate_declared(-40.0, "true", 50.0) == 0.0


class TestTheWalkPricesADeclarationAgainstWhatItMeets:
    """`price_declared_packet` — the resistance resolved at resolve time."""

    def test_a_magic_packet_reads_the_published_magic_resistance(self):
        packet = DeclaredPacket(252.0, "magic", "sunfire_aegis.continuous_aura")
        price = price_declared_packet(
            packet, baseline_effective_armor=120.0, baseline_effective_mr=67.0
        )
        assert price.unavailable == ""
        assert price.resistance == 67.0
        assert price.amount == apply_resistance(252.0, 67.0)

    def test_a_physical_packet_reads_the_published_armour(self):
        packet = DeclaredPacket(100.0, "physical", "fixture.physical")
        price = price_declared_packet(
            packet, baseline_effective_armor=100.0, baseline_effective_mr=67.0
        )
        assert price.resistance == 100.0
        assert price.amount == 50.0

    def test_an_armed_delta_is_part_of_the_mitigation_not_a_second_factor(self):
        """The whole difference between this path and the ratio it replaces.

        The ratio re-prices an already-mitigated number by
        `f(baseline + delta) / f(baseline)`; here the delta is simply part of
        the resistance the raw value meets, mitigated once.  The two agree on
        this input, which is what makes the replacement a re-spelling — and
        they are written out separately so the day they stop agreeing is a
        failure rather than a shared expression.
        """
        packet = DeclaredPacket(252.0, "magic", "fixture.armed")
        price = price_declared_packet(
            packet,
            baseline_effective_armor=None,
            baseline_effective_mr=67.0,
            dynamic_bonus_magic_resistance=30.0,
        )
        assert price.resistance == 97.0
        ratioed = apply_resistance(252.0, 67.0) * (
            apply_resistance(1.0, 97.0) / apply_resistance(1.0, 67.0)
        )
        assert price.amount == pytest.approx(ratioed, rel=1e-12)

    def test_true_damage_is_priced_without_any_baseline(self):
        """No baseline is consulted, so none can be missing."""
        price = price_declared_packet(
            DeclaredPacket(300.0, "true", "fixture.true"),
            baseline_effective_armor=None,
            baseline_effective_mr=None,
        )
        assert price == (300.0, None, "")

    def test_a_missing_baseline_is_refused_by_name(self):
        """R-05: the refusal the walk receipts, reproduced on demand.

        A fight that published no effective resistance leaves the walk
        nothing to mitigate against.  The refusal is a named reason and a
        `None` amount, never a zero a caller could add to a total.
        """
        price = price_declared_packet(
            DeclaredPacket(252.0, "magic", "fixture.blind"),
            baseline_effective_armor=120.0,
            baseline_effective_mr=None,
        )
        assert price.amount is None
        assert price.unavailable == NO_RESISTANCE_PUBLISHED

    def test_a_damage_class_no_resistance_answers_for_is_refused(self):
        """R-05's second red: an unrecognized class is not paid in full.

        Paying it raw would be a mitigation decision taken by silence, which
        is the shape this campaign exists to remove.
        """
        price = price_declared_packet(
            DeclaredPacket(252.0, "adaptive", "fixture.unknown"),
            baseline_effective_armor=120.0,
            baseline_effective_mr=67.0,
        )
        assert price.amount is None
        assert price.unavailable == UNPRICEABLE_DAMAGE_TYPE
        assert "adaptive" not in MITIGATED_DAMAGE_TYPES


def test_the_strike_back_prices_through_the_shared_arithmetic():
    """The tree's one older from-raw producer reads the same home.

    Thorns predates this module: it is the only place the walk's own side
    already turned a declared magnitude into a mitigated number.  Asserting
    the two agree on a real Thornmail profile is what makes `pricing` the one
    home rather than a successor sitting beside a precedent.
    """
    wearer = _PricingHolder({"bonus_armor": 80.0})
    striker = _PricingHolder({"magic_resistance": 67.0})
    profile = thorns_effects([_item("Thornmail")])[0]

    expected_resistance = apply_magic_penetration(67.0, 0.0, 0.0)
    expected_raw = profile.damage + profile.bonus_armor_ratio * 80.0
    assert thorns_return_damage(profile, wearer, striker) == mitigate_declared(
        expected_raw, "magic", expected_resistance
    )


# ---------------------------------------------------------------------------
# From-declaration pricing — the walk-side branch
# ---------------------------------------------------------------------------
#
# `_apply_live_packet_chain` opens on the pair engine's post-mitigation number
# and re-ratios it when the subject's resistance moved.  A packet carrying a
# declaration takes the other arm: the walk mitigates the raw value itself, at
# the resistance resolved for that instant, and the ratio never runs.  These
# cases drive the real kernel, because a branch asserted only through its own
# helper is a branch nothing proves the walk reaches.

#: The subject every declared-packet case is priced against.  One number, so a
#: case that changes it says so rather than quietly comparing two fights.
DECLARED_SUBJECT_MR = 67.0

#: How a `DeclaredPacket` construction is counted in `src/` (R-29's rule
#: stated so the count is reproducible): this pattern over every `.py` file
#: under `src/calculator/`, with `survival/pricing.py` excluded because the
#: line that declares the class matches it and a definition is not a
#: construction.
DECLARED_PACKET_CONSTRUCTION = re.compile(r"\bDeclaredPacket\s*\(")

PRICING_MODULE = "src/calculator/survival/pricing.py"

#: The one module allowed to *compose* a declared packet, as against the one
#: allowed to declare the type.  A roster composes a pair fight in two
#: places, and `program/compile.py` is where both of them meet
#: (`declared_packet_of`), so a second composition site anywhere else is the
#: second reader of one declaration this scan exists to catch.
COMPOSITION_MODULE = "src/calculator/program/compile.py"

#: The two homes a `DeclaredPacket(` line may legally appear in.  Everything
#: else is a family pricing its own declaration behind the registry's back.
DECLARED_PACKET_HOMES = (PRICING_MODULE, COMPOSITION_MODULE)


def _repriced_owners() -> frozenset[str]:
    """Which item names own a mechanic the walk re-prices from its declaration.

    The opt-in set, spelled the way a fixture asks about it: `Sunfire Aegis`
    rather than `sunfire_aegis.continuous_aura`, so a fixture states the item
    it is built on and never a mechanic-id spelling it would have to keep in
    step by hand.
    """
    return frozenset(
        rule.owner
        for owner in rule_owners()
        for rule in behavior_rules(owner)
        if rule.mechanic_id in walk_repriced_mechanics()
    )


def _src_sources() -> Mapping[str, str]:
    """Every `src/calculator/` module's text, keyed by repo-relative path."""
    root = Path(__file__).parents[1]
    return {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted((root / "src" / "calculator").rglob("*.py"))
    }


def declared_packet_construction_sites(
    sources: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    """Every `src/` file that builds a declared packet, its own home aside.

    `sources` is the seam the negative below drives (R-05): a scan that
    cannot be made to report something is indistinguishable from a scan that
    found nothing.
    """
    return tuple(
        path
        for path, text in sorted((sources or _src_sources()).items())
        if path not in DECLARED_PACKET_HOMES
        and DECLARED_PACKET_CONSTRUCTION.search(text)
    )


def _pricing_target():
    """One defender with health, the fixture magic resistance, nothing else."""
    return Combatant(
        participant_id="target",
        team="enemy",
        champion_data={"name": "target"},
        level=1,
        items=(),
        stats={"health": 100000.0, "magic_resistance": DECLARED_SUBJECT_MR},
        defenses=StartingDefenses(
            magic_shield=0.0,
            physical_shield=0.0,
            general_shield=0.0,
            healing_received_multiplier=1.0,
        ),
    )


def _walk_one_declared_packet(packet, *, baseline_mr=DECLARED_SUBJECT_MR):
    """Run the real kernel over one declared packet; return its receipt row.

    The event carries ``damage: 0.0`` on purpose.  That zero is what the pair
    engine's arm would pay, so a row that ends up non-zero can only have been
    priced from the declaration.
    """
    event = {"_event_id": "declared", "time": 0.0, "damage": 0.0}
    action = SurvivalAction(
        sort_key=(0.0, TransitionRank.DAMAGE, 0, 0, 0, "target", "declared", "item"),
        time=0.0,
        phase=TransitionRank.DAMAGE,
        kind=ActionKind.DAMAGE,
        subject=0,
        attacker=0,
        aidx=0,
        amount=0.0,
        damage_type=packet.damage_type,
        declared=packet,
        baseline_effective_mr=baseline_mr,
        source_key="item",
        source="item",
        event_slot=EVENT_SLOTS.slot("declared"),
        sequence=0,
        event=event,
    )
    target = _pricing_target()
    states = build_states([target], (0.0,))
    ledger = ReceiptLedger(
        actions=[action],
        index_of={"target": 0},
        compile_event=action_from_event,
        annotating=True,
    )
    run_survival_walk(
        [action],
        TransitionContext(
            duration=10.0,
            states=states,
            combatants=[target],
            index_of={"target": 0},
            ledger=ledger,
            regeneration_windows=(None,),
        ),
    )
    return event


class TestTheWalkPricesADeclaredPacketItself:
    """The branch, driven through `run_survival_walk` rather than around it."""

    def test_the_declaration_is_paid_and_the_packets_own_amount_is_not(self):
        """The number comes from the raw value, mitigated here.

        252.0 magic at 67 magic resistance is the Sunfire immolate total the
        equivalence fixture pins against the pair engine; what this case
        proves is only that the walk's arm reaches it from a packet whose own
        damage field says zero.
        """
        row = _walk_one_declared_packet(
            DeclaredPacket(252.0, "magic", "fixture.periodic")
        )
        assert row["damage"] == round(apply_resistance(252.0, DECLARED_SUBJECT_MR), 6)

    def test_the_receipt_names_the_rule_and_the_resistance_it_met(self):
        """A priced declaration publishes its arithmetic, not just a total.

        The amp term is in the row for the same reason the raw value is: a
        receipt carrying only the product cannot tell a large declaration
        from an amplified one, and the whole point of the term riding the
        packet is that it stays separately readable.
        """
        row = _walk_one_declared_packet(
            DeclaredPacket(252.0, "magic", "fixture.periodic")
        )
        assert row["declared_price"] == {
            "rule": "fixture.periodic",
            "raw": 252.0,
            "holder_amp": 1.0,
            "resistance": DECLARED_SUBJECT_MR,
            "amount": round(apply_resistance(252.0, DECLARED_SUBJECT_MR), 6),
        }

    def test_true_damage_is_paid_whole_and_records_no_resistance(self):
        """`None` rather than 0.0: it met no resistance, it did not meet zero."""
        row = _walk_one_declared_packet(
            DeclaredPacket(300.0, "true", "fixture.execute"), baseline_mr=None
        )
        assert row["damage"] == 300.0
        assert row["declared_price"]["resistance"] is None

    def test_an_unpriceable_declaration_pays_nothing_and_says_why(self):
        """R-05's red for the walk-side arm, through the real kernel.

        A fight that published no effective magic resistance leaves the raw
        value nothing to be mitigated against.  The packet then pays its own
        amount — zero here — and the row carries a named reason, which is the
        difference between a family that went unpaid and a family that dealt
        no damage.
        """
        row = _walk_one_declared_packet(
            DeclaredPacket(252.0, "magic", "fixture.blind"), baseline_mr=None
        )
        assert row["damage"] == 0.0
        assert row["declared_price_unavailable"] == {
            "rule": "fixture.blind",
            "reason": NO_RESISTANCE_PUBLISHED,
            "damage_type": "magic",
        }
        assert "declared_price" not in row


def _repriced_families() -> tuple[RuleFamily, ...]:
    """Every family whose packets the walk re-prices from their declarations.

    Read off the declarations rather than listed, so the family a retirement
    slice opts in arrives here on the commit that declares it and the tests
    below cannot silently stop covering one.
    """
    repriced = walk_repriced_mechanics()
    return tuple(
        sorted(
            {
                rule.family
                for owner in rule_owners()
                for rule in behavior_rules(owner)
                if rule.mechanic_id in repriced
            },
            key=lambda family: family.value,
        )
    )


class TestTheOptInSetIsExactlyTheFamiliesThatRetired:
    """Amendment L, Ruling 3's inertness clause, once a family has opted in.

    The clause was never "this path stays unreached"; it was "this path is
    inert **until a family's retirement slice opts in**", and one has.  What
    the clause still buys, and what these cases assert, is that the opt-in is
    a *declaration* — the set is read off the registry, it is exactly the
    families whose receipt-walk interpreter is registered, and every family
    outside it still reaches the walk as the pair engine's timed rows.
    """

    def test_the_opt_in_set_is_the_families_with_a_receipt_walk_interpreter(self):
        """A family re-priced with no interpreter to price it is a deletion.

        The two declarations have to agree: the capability says the walk owns
        the number and the registry says which interpreter hands it one.  A
        ``HolderPacket`` half declared for a family no receipt-walk
        interpreter serves would take the pair engine's number out of every
        roster total with nothing replacing it — the half-performed
        retirement umbrella Amendment L, Ruling 1 calls worse than neither
        half.
        """
        families = _repriced_families()
        assert families == (
            RuleFamily.ACTIVE_CAST,
            RuleFamily.CAST_PROC,
            RuleFamily.CHARGED_STRIKE,
            RuleFamily.ON_HIT_STRIKE,
            RuleFamily.PERIODIC,
            RuleFamily.SECONDARY_TARGET,
            RuleFamily.SPELLBLADE,
        )
        for family in families:
            assert (family, EngineLane.RECEIPT_WALK) in INTERPRETERS

    def test_no_family_is_half_retired(self):
        """Every rule of a re-priced family is re-priced or says why it is not.

        A family whose damage arrives by two routes — some rules priced from
        their declarations and the rest consumed as the pair engine's rows —
        is D-60's two engines pricing one mechanic, wearing a retirement's
        name.  The rule set is read from the catalog, so a seventh item
        active declared tomorrow fails here rather than shipping half
        covered.

        A rule that is *not* re-priced is admitted only by its own
        declaration, never by this test knowing its name: it has to declare a
        pair half tagged ``APPLIED``, which is the statement "this mechanic's
        pair-lane number is delivered and previewed by nobody".  That is the
        honest reading for a ``charged_strike`` swing schedule — Guinsoo's
        Rageblade's and Yun Tal Wildarrows' ramps change how often the holder
        swings and author no packet at all, so there is nothing for a walk to
        price and nothing for a preview to double-count.  An undeclared rule
        of a re-priced family fails here, which is what keeps the exclusion
        from being an omission (D-40).
        """
        repriced = walk_repriced_mechanics()
        for family in _repriced_families():
            declared = {
                rule.mechanic_id
                for owner in rule_owners()
                for rule in behavior_rules(owner)
                if rule.family is family
            }
            assert declared, family.value
            for mechanic in sorted(declared - repriced):
                capability = CAPABILITIES.get(mechanic)
                assert capability is not None, mechanic
                assert capability.engine is Engine.PAIR, mechanic
                assert capability.view_tags[Engine.PAIR] is ViewTag.APPLIED, mechanic

    def test_every_other_family_still_reaches_the_walk_as_pair_rows(self):
        """The families that have not opted in are unmoved by this path.

        Stated as the complement rather than as a count, because the number
        of retirements is exactly what the next slices move: what must stay
        true is that a family nobody retired carries no declaration and is
        therefore unreachable from the from-declaration pricer.
        """
        repriced = walk_repriced_mechanics()
        untouched = {
            rule.mechanic_id
            for owner in rule_owners()
            for rule in behavior_rules(owner)
            if rule.family not in _repriced_families()
        }
        assert untouched
        assert not untouched & repriced

    def test_the_composition_still_has_exactly_its_two_homes(self):
        """One declaring module and one composing module, and nothing else.

        The transport is not what a retirement moves: a family opts in by
        declaring a walk half, never by building a `DeclaredPacket` of its
        own.  A second composition site would be a family pricing its own
        declaration behind the registry's back, which is the second reader of
        one declaration this scan exists to catch.
        """
        assert declared_packet_construction_sites() == ()

    def test_the_default_action_declares_nothing(self):
        """The field's default is the inertness, so it is asserted too."""
        assert SurvivalAction().declared is None

    def test_the_inertness_scan_has_a_permanent_injection_seam(self):
        """R-05: a second composition site is a finding, on demand."""
        injected = {
            PRICING_MODULE: "class DeclaredPacket(NamedTuple):\n",
            "src/calculator/interpreters/spellblade.py": (
                "DeclaredPacket(140.0, 'physical', 'bloodsong.spellblade')\n"
            ),
        }
        assert declared_packet_construction_sites(injected) == (
            "src/calculator/interpreters/spellblade.py",
        )


# ---------------------------------------------------------------------------
# From-declaration pricing — the equivalence fixture
# ---------------------------------------------------------------------------
#
# Amendment L, Ruling 3 requires the stage to carry "the from-declaration price
# against the pair-ratioed one, on a family that has not yet opted in, so the
# stage is provably a re-spelling before it is ever a re-pricing".  This is
# that fixture.
#
# The family is `spellblade`, priced through Bloodsong's proc: one declared
# magnitude per proc, physical, over a proc count the pair engine publishes on
# its own row.  It is chosen because everything the comparison needs is
# committed and readable — the covering coupled scenario is derived from the
# committed scenario set by the owner it equips, and the pair engine publishes
# both the number and the effective resistance it priced at.
#
# THE CLAUSE'S OWN SELECTION CLASS IS EMPTYING, and that is recorded here
# rather than worked around.  The fixture stood on `periodic` until that
# family retired on 2026-08-16 and then MOVED to `spellblade`, which was the
# right discipline while there were families left to move to.  There are not:
# `spellblade` retired on 2026-08-17 and `secondary_target` is the last row of
# umbrella Amendment F's fourteen, so a migration would be a fixture rewritten
# twice in two commits for a family the next one retires.
#
# What the comparison asserts does not change, and this is why the case
# survives its clause: it prices a declaration through the walk's own pricer
# and compares it to THE PAIR ENGINE'S OWN PUBLISHED ROW.  The pair engine is
# an independent producer of that number whether or not the family has opted
# in, so the equality is not the stage checking itself — the un-opted-in
# requirement was about the stage being INERT, which is a property Ruling 3
# retired itself the moment the first family opted in.  What replaces the
# opt-in assertion is its successor: the family HAS opted in, and the walk
# therefore prices the same declaration this case prices by hand.
#
# Nothing about the fixture is typed: the scenario, the owner and the rule id
# are all read, so a scenario set that re-covers the family under a different
# roster fails here instead of quietly comparing the old one.


@dataclass(frozen=True)
class DeclaredPricingEquivalence:
    """One family, and where its two prices can be compared.

    `owner` and `breakdown_key` name the declaring item and the pair engine's
    row for it; `family` is the deferral row this fixture stands in for, and
    the scenario is derived from the owner rather than named here.

    `resistance_field` is the fight figure this family's packet is mitigated
    against, and it is stated rather than inferred because the negative case
    below has to perturb the right one: perturbing the resistance a physical
    packet never meets would leave the price unchanged and the red would pass
    by testing nothing.
    """

    name: str
    family: RuleFamily
    deferral_family_key: str
    owner: str
    breakdown_key: str
    resistance_field: str


PRICING_EQUIVALENCE = DeclaredPricingEquivalence(
    name="spellblade_bloodsong",
    family=RuleFamily.SPELLBLADE,
    deferral_family_key="spellblade",
    owner="Bloodsong",
    breakdown_key="spellblade_Bloodsong",
    resistance_field="effective_armor",
)


def _covering_scenario(fixture):
    """The committed coupled scenario that equips *fixture*'s owner.

    Derived from `golden_snapshot.COUPLED_SCENARIOS` by the item the family
    declares, which is the same join the retirement schedule made while this
    family still had a row there — read rather than named, so a scenario set
    that stops covering the owner fails here instead of quietly comparing a
    roster that does not hold it.
    """
    assert fixture.owner in {
        rule.owner
        for rule in behavior_rules(fixture.owner)
        if rule.family is fixture.family
    }, "the catalog no longer joins this owner to this family"
    return next(
        scenario
        for scenario in gs.COUPLED_SCENARIOS
        if fixture.owner in scenario.equipped() and not scenario.score_mode
    )


def _pair_priced(fixture):
    """The pair engine's number for the family, and the fight that priced it."""
    scenario = _covering_scenario(fixture)
    parsed = parse_scenario_request(dict(scenario.request), deterministic=True)
    resolved = resolve_scenario(parsed)
    params = resolved.target_fight_params[0]
    result = run_fight(
        resolved.champion_data, parsed.level, list(resolved.items), params
    )
    return parsed, resolved, params, result


def _declared_packet(fixture, parsed, resolved, params):
    """The same family's damage as its own declaration states it: raw.

    Built the way the pair engine builds it — the family's interpreter, at the
    build context that fight used — so what the comparison isolates is the
    *mitigation*, which is the half this stage moves.
    """
    stats = calculate_total_stats(
        resolved.champion_data,
        parsed.level,
        list(resolved.items),
        item_options=params.item_options,
        role=params.role,
        role_quest_complete=params.role_quest_complete,
        external_stat_bonuses=params.ally_stat_bonuses,
    )
    is_melee = bool(stats.get("is_melee", True))
    duration = float(params.fight_duration_seconds)
    owners = [str(item["name"]) for item in resolved.items]
    slot = resolve_spellblade_slot(
        owners,
        level=parsed.level,
        fight_duration_seconds=duration,
        target_bonus_health=max(0.0, float(params.target_bonus_health or 0.0)),
        holder_is_melee=is_melee,
    )
    assert slot is not None
    assert slot.source.breakdown_key == fixture.breakdown_key
    rule = next(
        declared
        for declared in behavior_rules(fixture.owner)
        if declared.family is fixture.family
    )
    # The proc COUNT is the pair engine's own, read off the row it published:
    # how often a spellblade charge is spent is a fact about the fight's casts
    # and swings, not about the declaration, and the half this fixture
    # isolates is the mitigation.
    procs = int(result_row(fixture, parsed, resolved, params)["count"])
    raw = (
        slot.source.raw_damage(
            DamageInputs(
                champion_stats=stats,
                level=parsed.level,
                is_melee=is_melee,
                target_max_health=float(params.target_health),
                target_current_health=float(params.target_health),
            )
        )
        * procs
    )
    return DeclaredPacket(raw, slot.source.damage_type, rule.mechanic_id)


def result_row(fixture, parsed, resolved, params):
    """The pair engine's own row for this fixture's family."""
    result = run_fight(
        resolved.champion_data, parsed.level, list(resolved.items), params
    )
    return result["breakdown"][fixture.breakdown_key]


class TestTheFromDeclarationPriceReproducesThePairEngines:
    """The stage is a re-spelling before it is ever a re-pricing."""

    def test_the_fixture_family_has_opted_in_and_the_walk_prices_this_owner(self):
        """The successor to the clause's own selection, and its two halves.

        Ruling 3's fixture selected a family that had **not** opted in, so
        that the stage was provably a re-spelling before it was ever a
        re-pricing.  The stage is landed and eight families have opted in
        since; what is left to assert is not that this family is deferred —
        it is not — but that the declaration this case prices by hand is the
        one the walk prices too, which is what makes the equality below a
        statement about the tree rather than about a fixture.

        Two halves, because either alone can be true without the other: the
        receipt-walk interpreter is registered for the family, and the walk
        re-prices this owner's packets rather than dropping them.
        """
        assert (PRICING_EQUIVALENCE.family, EngineLane.RECEIPT_WALK) in INTERPRETERS
        assert _repriced_owners() & {PRICING_EQUIVALENCE.owner}

    def test_the_declaration_prices_to_the_pair_engines_own_number(self):
        """Bit-exact, on identical inputs — the fixture this stage owes.

        The pair engine mitigates the family's raw total once, at the fight's
        effective magic resistance, and hands the walk the result. The walk's
        own pricer, given the same raw total and the same resistance the
        packet would carry as its baseline, returns the same float. That is
        the whole claim: the from-declaration path re-spells a number, it does
        not move one.
        """
        parsed, resolved, params, result = _pair_priced(PRICING_EQUIVALENCE)
        pair = result["breakdown"][PRICING_EQUIVALENCE.breakdown_key]["total_damage"]
        packet = _declared_packet(PRICING_EQUIVALENCE, parsed, resolved, params)

        price = price_declared_packet(
            packet,
            baseline_effective_armor=float(result["effective_armor"]),
            baseline_effective_mr=float(result["effective_mr"]),
        )
        assert price.amount == pair
        assert price.resistance == float(result[PRICING_EQUIVALENCE.resistance_field])

    def test_the_comparison_is_not_vacuous_and_can_fail(self):
        """R-05's permanent negative for the fixture, in two directions.

        An equality between two numbers proves nothing until both are known
        to be non-trivial and the equality is known to be breakable. The raw
        total is positive and strictly larger than the priced one, so
        mitigation really happened; and the same declaration priced one point
        of resistance away from the fight's own does not match, so the
        assertion above is sensitive to the number it is checking.
        """
        parsed, resolved, params, result = _pair_priced(PRICING_EQUIVALENCE)
        pair = result["breakdown"][PRICING_EQUIVALENCE.breakdown_key]["total_damage"]
        packet = _declared_packet(PRICING_EQUIVALENCE, parsed, resolved, params)
        baselines = {
            "baseline_effective_armor": float(result["effective_armor"]),
            "baseline_effective_mr": float(result["effective_mr"]),
        }
        field = f"baseline_{PRICING_EQUIVALENCE.resistance_field}"
        resistance = baselines[field]

        assert packet.raw_amount > pair > 0.0
        assert resistance > 0.0
        assert (
            price_declared_packet(
                packet, **{**baselines, field: resistance + 1.0}
            ).amount
            != pair
        )


# ---------------------------------------------------------------------------
# The declared amp term — the equivalence fixtures at amp != 1.0
# ---------------------------------------------------------------------------
#
# Amendment L, Ruling 3's fixture above runs on a roster where every static
# holder amp reads 1.0, which is the case that cannot fail: with no amp armed,
# a pricer that dropped the term entirely would still reproduce the pair
# engine exactly.  Amendment M, Ruling 1 therefore requires the fixtures to
# cover `amp != 1.0`, and names the two cases: an Abyssal Mask holder's item
# active, and an Abyssal Mask holder's ability-triggered item proc.  Both live
# on `amp_armed_mage_roster`, the covering scenario the coverage act landed for
# exactly this — Ahri holding Actualizer (the ability part amp, its Mana Made
# Real window authored), Abyssal Mask (the magic amp), Hextech Rocketbelt (the
# active) and Stormsurge (the ability-triggered proc).
#
# What the numbers here are is measured, never typed: the raw declaration comes
# from the family's own interpreter, the resistance and the priced row from the
# pair engine's own result, and the amps from `resolve_static_holder_amps` —
# the reading the walk itself makes.
#
# THE ORDERING, AND WHAT IT COSTS, MEASURED.  The pair engine applies these
# amps *after* mitigation: `damage._mitigate` returns
# `apply_resistance(raw, mr) * magic_amp`, and `_add_item_proc_damage`
# multiplies that by the ability amp.  Ruling 1 rules the walk's term
# **pre-mitigation** instead, so the composed value is mitigated once rather
# than a mitigated number being re-multiplied.  Multiplication is commutative
# but not associative in IEEE 754, so `(raw * amp) * m` and `(raw * m) * amp`
# are the same real number rounded at two different points, and on both seeds
# they land one unit in the last place apart.  That is stated and pinned rather
# than smoothed over: each fixture asserts both associations exactly, asserts
# the gap is at most one ULP, and asserts the two agree at the precision every
# committed baseline grades to — so the ruled ordering is implemented, the
# difference it costs is a measured number, and neither can drift in silence.

#: Where the golden baselines round.  A difference this size is invisible to
#: every committed gate, which is the fact the ULP assertions below make
#: checkable instead of assumed.
GOLDEN_DECIMALS = 2


@dataclass(frozen=True)
class AmpArmedSeed:
    """One seed case: a declaring family, its pair row, and the amps on it.

    `attack_class` is how the pair engine delivers the number, which is what
    selects the part amp — the same question `StaticHolderAmps.factor_for`
    asks, so the fixture cannot disagree with the composition it is checking
    about which amps a packet is entitled to.
    """

    name: str
    scenario: str
    breakdown_key: str
    attack_class: Any
    raw_of: Any


def _amp_armed_fight(seed):
    """The seed's committed scenario, run through the pair engine.

    The scenario is resolved by name against `golden_snapshot.COUPLED_SCENARIOS`
    rather than rebuilt here, so a roster edited out from under these fixtures
    fails to resolve instead of quietly comparing a different fight.
    """
    scenario = next(s for s in gs.COUPLED_SCENARIOS if s.name == seed.scenario)
    parsed = parse_scenario_request(dict(scenario.request), deterministic=True)
    resolved = resolve_scenario(parsed)
    params = resolved.target_fight_params[0]
    result = run_fight(
        resolved.champion_data, parsed.level, list(resolved.items), params
    )
    stats = calculate_total_stats(
        resolved.champion_data,
        parsed.level,
        list(resolved.items),
        item_options=params.item_options,
        role=params.role,
        role_quest_complete=params.role_quest_complete,
        external_stat_bonuses=params.ally_stat_bonuses,
    )
    return parsed, resolved, params, result, stats


@cache
def _amp_armed_reading(seed):
    """One seed's raw value, resistances, amps and pair-engine number.

    Every element is read from an instrument: the declaration's raw value from
    the declaring family's interpreter, the resistance and the priced row from
    the pair engine's own result, and the amps from the walk's own reading of
    the declarations that produce them.
    """
    parsed, resolved, params, result, stats = _amp_armed_fight(seed)
    is_melee = bool(stats.get("is_melee", True))
    build = {
        "level": parsed.level,
        "fight_duration_seconds": float(params.fight_duration_seconds),
        "target_bonus_health": max(0.0, float(params.target_bonus_health or 0.0)),
        "holder_is_melee": is_melee,
    }
    source = seed.raw_of(
        [str(item["name"]) for item in resolved.items], seed.breakdown_key, build
    )
    raw = source.raw_damage(
        DamageInputs(
            champion_stats=stats,
            level=parsed.level,
            is_melee=is_melee,
            target_max_health=float(params.target_health),
            target_current_health=float(params.target_health),
        )
    )
    amps = delta_amp.resolve_static_holder_amps(
        list(resolved.items),
        holder_stats=stats,
        # The window is authored by the scenario's own item options, which is
        # what makes this roster the one that arms the ability amp at all.
        ability_amp_armed=True,
        **build,
    )
    return AmpArmedReading(
        raw=raw,
        damage_type=source.damage_type,
        effective_mr=float(result["effective_mr"]),
        effective_armor=float(result["effective_armor"]),
        amps=amps,
        pair=result["breakdown"][seed.breakdown_key]["total_damage"],
    )


@dataclass(frozen=True)
class AmpArmedReading:
    """What one seed measured, so four cases read it by name and not by index."""

    raw: float
    damage_type: str
    effective_mr: float
    effective_armor: float
    amps: Any
    pair: float

    def factor(self, seed) -> float:
        """The composed amp this packet is entitled to, the walk's own reading."""
        return self.amps.factor_for(self.damage_type, seed.attack_class)

    def pair_association(self, seed) -> float:
        """The pair engine's own multiply order, reproduced term by term.

        Mitigate first, then each amp in turn onto the already-mitigated
        number: `_mitigate` applies the magic amp, and the part amp is a
        second multiplication at the call site (`_add_item_proc_damage` for
        an ability part, `_mitigate_basic_attack_swing` for a swing).  Folding
        the two amps together first and multiplying once would be a third
        association and reproduce neither engine, which is exactly why this
        is spelled as the sequence the engine performs.
        """
        value = apply_resistance(self.raw, self.effective_mr)
        if self.damage_type == "magic":
            value *= self.amps.magic
        if seed.attack_class is AttackClass.ABILITY:
            value *= self.amps.ability
        elif seed.attack_class is AttackClass.BASIC_ATTACK:
            value *= self.amps.basic
        return value

    def priced(self, seed, *, amped: bool = True):
        """The walk's price for this seed, with or without the declared term."""
        packet = DeclaredPacket(
            self.raw,
            self.damage_type,
            f"fixture.{seed.name}",
            holder_amp=self.factor(seed) if amped else 1.0,
        )
        return price_declared_packet(
            packet,
            baseline_effective_armor=self.effective_armor,
            baseline_effective_mr=self.effective_mr,
        )


def _active_source(owners, breakdown_key, build):
    """The item active the pair engine prices, from its own interpreter."""
    return next(
        source
        for source in active_cast.active_sources(owners, **build)
        if source.breakdown_key == breakdown_key
    )


def _cast_proc_source(owners, breakdown_key, build):
    """The ability-triggered item proc, from its own interpreter."""
    return next(
        effect.source
        for effect in cast_proc.resolve_slots(owners, **build).cooldown_procs
        if effect.source.breakdown_key == breakdown_key
    )


AMP_ARMED_SEEDS = (
    AmpArmedSeed(
        name="abyssal_holder_item_active",
        scenario="amp_armed_mage_roster",
        breakdown_key="active_Hextech Rocketbelt",
        # An item active is neither an ability part nor a swing, so only the
        # magic amp reaches it — which is the pair engine's own reading in
        # `_add_item_active_damage`, where `_mitigate` is handed `magic_amp`
        # and nothing else.
        attack_class=AttackClass.OTHER,
        raw_of=_active_source,
    ),
    AmpArmedSeed(
        name="abyssal_holder_ability_triggered_proc",
        scenario="amp_armed_mage_roster",
        breakdown_key="proc_Stormsurge",
        # `_add_item_proc_damage` multiplies its mitigated per-proc figure by
        # `state.ability_amp` when the source is ability damage, on top of the
        # magic amp `_mitigate` already applied — so this seed carries both
        # amps and is the one that fails if either is dropped.
        attack_class=AttackClass.ABILITY,
        raw_of=_cast_proc_source,
    ),
)


@pytest.mark.parametrize("seed", AMP_ARMED_SEEDS, ids=lambda seed: seed.name)
class TestTheDeclaredAmpTermReproducesThePairEngines:
    """Amendment M, Ruling 1's fixture: the term, on a roster that arms it."""

    def test_the_seed_really_arms_an_amp(self, seed):
        """A fixture at amp 1.0 proves only the case that cannot fail."""
        reading = _amp_armed_reading(seed)
        assert reading.factor(seed) > 1.0
        assert reading.raw > 0.0
        assert reading.pair > 0.0

    def test_the_two_associations_are_each_exact_and_one_ulp_apart(self, seed):
        """The ordering Ruling 1 chose, and the price of choosing it.

        Three exact claims and one bound, so the reading is complete: the
        pair engine's number *is* its post-mitigation association, the walk's
        price *is* the pre-mitigation one Ruling 1 rules, and the two differ
        by at most one unit in the last place.  Asserting only "they are
        close" would hide an ordering nobody chose; asserting equality alone
        would be false.
        """
        reading = _amp_armed_reading(seed)
        factor = reading.factor(seed)

        assert reading.pair_association(seed) == reading.pair

        amount = reading.priced(seed).amount
        assert amount == apply_resistance(reading.raw * factor, reading.effective_mr)
        assert abs(amount - reading.pair) <= math.ulp(reading.pair)

    def test_the_term_survives_every_gate_the_campaign_grades_with(self, seed):
        """The difference the ordering costs is invisible to the baselines.

        Stated as an assertion rather than as a claim in a comment: the two
        associations agree at the precision the committed golden files round
        to, so the ruled ordering cannot move a leaf any gate reads.
        """
        reading = _amp_armed_reading(seed)
        assert round(reading.priced(seed).amount, GOLDEN_DECIMALS) == round(
            reading.pair, GOLDEN_DECIMALS
        )

    def test_dropping_the_term_would_be_visible(self, seed):
        """R-05's red for the term itself, on the seed that carries it.

        The deletion Ruling 1 exists to forbid, made a measurable event: a
        packet priced with no amp falls short of the pair engine's number by
        the holder's own amplifier, and the shortfall clears golden's own
        precision by a wide margin.
        """
        reading = _amp_armed_reading(seed)
        unamped = reading.priced(seed, amped=False).amount
        assert unamped < reading.pair
        assert unamped * reading.factor(seed) == pytest.approx(reading.pair)
        assert round(reading.pair - unamped, GOLDEN_DECIMALS) > 0.0


# ---------------------------------------------------------------------------
# The per-packet resistance term — the equivalence fixtures inside a window
# ---------------------------------------------------------------------------
#
# Umbrella Amendment N, Ruling 1: a declaration is priced at the resistance ITS
# OWN PACKET met, and the fixtures "MUST cover a lethality-window physical case
# and a Liandry-reprice magic case", on the reasoning that made Amendment M's
# fixtures cover an amp other than 1.0.  A fixture set in which every packet met
# the figure the fight published proves only the case that cannot fail: a pricer
# that dropped the term entirely would reproduce the pair engine exactly.
#
# HOW THE DECLARATION GETS ONTO A PACKET.  No family has retired, so no authoring
# site in `src/` stamps one — that inertness is asserted elsewhere in this file
# and is the point of the stage.  These fixtures stamp one the way a retiring
# family's own authoring site would: inside the engine step that authors the
# packet, from the same `state` it prices with, carrying the raw magnitude that
# step compiled and the resistance the packet met AT AUTHORING TIME.  The rest of
# `run_fight` then runs untouched, which is what makes this an equivalence
# fixture rather than a unit test of the restatement: the window that re-prices
# the packet is the engine's own, resolved where the engine resolves it.
#
# WHAT IS MEASURED.  The declaration the packet comes out carrying, and the price
# the walk's own pricer produces from it, against the number the pair engine put
# on the row.  Bit-for-bit, because there is nothing here for float association
# to disagree about: the walk mitigates one magnitude at one resistance, exactly
# as the engine did.
#
# THE SEED.  The physical case is the seed Amendment N measured and adopted by
# its predicate — Dr. Mundo at level 13, one rotation, on the pinned
# `mundo_3champ` probe build, into that scenario's two enemies — read from
# `bench_coupled_optimizer` rather than retyped, so a re-pinned probe build fails
# here instead of quietly measuring a different fight.


@dataclass(frozen=True)
class WindowSeed:
    """One fight inside a re-pricing window, and the row it re-prices."""

    name: str
    breakdown_key: str
    damage_type: str
    rule_id: str


#: The engine step each seed's family authors its packets in.  Named rather than
#: guessed: the stamp has to land where the family's own retirement slice would
#: put it, which is before every step that could re-price what it authored.
LETHALITY_SEED = WindowSeed(
    name="stridebreaker_active_inside_a_firmament_window",
    breakdown_key="active_Stridebreaker",
    damage_type="physical",
    rule_id="stridebreaker.active",
)

LIANDRY_SEED = WindowSeed(
    name="liandry_burn_after_a_lifeline_raised_the_maximum",
    breakdown_key="burn_Liandry's Torment",
    damage_type="magic",
    rule_id="liandrys_torment.burn",
)


def _mundo_probe_request():
    """The pinned `mundo_3champ` scenario and probe build, read not retyped."""
    build = bench.PROBE_BUILDS["mundo_3champ"]
    return {
        **bench.MUNDO_SCENARIO,
        "items": list(build["items"]),
        "boots": build["boots"],
    }


def _stamping(step, stamp):
    """Wrap one engine step so it stamps declarations on what it authored."""

    def stamped(state, *args, **kwargs):
        step(state, *args, **kwargs)
        stamp(state)

    return stamped


def _declare_authored_row(state, seed):
    """Stamp *seed*'s row with the declaration a retired family would hand over.

    Two facts come off the engine's own `state` and neither is recomputed here:
    the resistance the packet met at authoring time is the fight's published
    effective figure for its class, and the raw magnitude is what the row's own
    events already are, divided back out by that one mitigation.  A retiring
    family would take the magnitude from its interpreter instead; the number is
    the same one, and taking it from the row is what keeps this fixture from
    re-deriving a build context the engine already resolved.
    """
    row = state.breakdown.get(seed.breakdown_key)
    if not isinstance(row, dict):
        return
    resistance = (
        state.resists.effective_armor
        if seed.damage_type == "physical"
        else state.resists.effective_mr
    )
    factor = apply_resistance(1.0, resistance)
    for event in row.get("damage_events") or ():
        event["declared"] = tuple(
            AuthoredDeclaration(
                seed.rule_id,
                float(event["damage"]) / factor,
                AttackClass.OTHER.value,
                float(resistance),
            )
        )


@cache
def _window_readings(seed, request_key):
    """Every fight of one seed's scenario, run with its row declared.

    Returns one reading per pair fight: the fight's published resistance, the
    row the engine finished with, and the declaration each of that row's packets
    came out carrying once every re-pricing step had run.
    """
    request = (
        _mundo_probe_request()
        if request_key == "mundo_3champ"
        else dict(
            next(s for s in gs.COUPLED_SCENARIOS if s.name == request_key).request
        )
    )
    parsed = parse_scenario_request(dict(request), deterministic=True)
    resolved = resolve_scenario(parsed)
    step = (
        pair_engine._add_item_active_damage
        if seed.damage_type == "physical"
        else pair_engine._add_burn_damage
    )
    readings = []
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            pair_engine,
            step.__name__,
            _stamping(step, lambda state: _declare_authored_row(state, seed)),
        )
        for params in resolved.target_fight_params:
            result = run_fight(
                resolved.champion_data, parsed.level, list(resolved.items), params
            )
            row = result["breakdown"][seed.breakdown_key]
            readings.append(
                WindowReading(
                    published=float(
                        result["effective_armor"]
                        if seed.damage_type == "physical"
                        else result["effective_mr"]
                    ),
                    row_total=float(row["total_damage"]),
                    packets=tuple(
                        (
                            float(event["damage"]),
                            AuthoredDeclaration(*event["declared"]),
                        )
                        for event in row["damage_events"]
                    ),
                )
            )
    return tuple(readings)


@dataclass(frozen=True)
class WindowReading:
    """What one pair fight published, and what its packets came out declaring."""

    published: float
    row_total: float
    packets: tuple

    def priced(self, seed, packet, *, at_the_published_baseline=False):
        """The walk's price for one declared packet of this fight."""
        _, declaration = packet
        return price_declared_packet(
            DeclaredPacket(
                declaration.raw_amount,
                seed.damage_type,
                declaration.rule_id,
                effective_resistance=(
                    None
                    if at_the_published_baseline
                    else declaration.effective_resistance
                ),
            ),
            baseline_effective_armor=self.published,
            baseline_effective_mr=self.published,
        )


class TestTheLethalityWindowPacketPricesAtTheArmourItMet:
    """Ruling 1's physical fixture, on the seed the amendment measured."""

    def test_the_window_really_fires_and_the_seed_reproduces(self):
        """The fixture is worth something only where the two figures differ.

        Both of the scenario's fights arm the Firmament window and both drive
        this packet's armour below the figure they published, so the forbidden
        reading and the ruled one are two different numbers on every fight here.
        """
        readings = _window_readings(LETHALITY_SEED, "mundo_3champ")
        assert len(readings) == 2
        for reading in readings:
            assert reading.packets
            for _, declaration in reading.packets:
                assert 0.0 <= declaration.effective_resistance < reading.published
        # The amendment's own reading of this seed, asserted rather than
        # quoted: the first fight's window drives the packet's armour to the
        # floor, which is why its declared raw and its priced row are the same
        # number, and the second fight's does not, which is why the two fights
        # are not one case measured twice.
        first, second = readings
        assert first.packets[0][1].effective_resistance == 0.0
        assert first.packets[0][1].raw_amount == first.row_total
        assert second.packets[0][1].effective_resistance > 0.0

    def test_the_declaration_prices_to_the_pair_engines_own_number(self):
        """Bit-exact, at the resistance the packet met — the whole ruling.

        One magnitude at one resistance on both sides, so there is no float
        association for the two to disagree about and the assertion is equality
        rather than a tolerance.
        """
        for reading in _window_readings(LETHALITY_SEED, "mundo_3champ"):
            for packet in reading.packets:
                damage, _ = packet
                assert reading.priced(LETHALITY_SEED, packet).amount == damage

    def test_pricing_at_the_published_baseline_deletes_the_window(self):
        """R-05's red for the term, and the forbidden reading, measured.

        The branch Ruling 1 forbids is not an error the tree can raise — it is
        a smaller number.  So it is priced here and the shortfall asserted: the
        packet met an armour below the fight's, so paying the fight's figure
        pays strictly less, by a margin every committed gate can see.
        """
        for reading in _window_readings(LETHALITY_SEED, "mundo_3champ"):
            for packet in reading.packets:
                damage, _ = packet
                forbidden = reading.priced(
                    LETHALITY_SEED, packet, at_the_published_baseline=True
                ).amount
                assert forbidden < damage
                assert round(damage - forbidden, GOLDEN_DECIMALS) > 0.0


class TestTheLiandryRepriceKeepsTheDeclarationInStep:
    """Ruling 1's magic fixture: the reprice moves a magnitude, not a mitigation.

    The other half of the ruling's *kept in step*, and the reason it needs its
    own fixture rather than a second physical one.  The lethality window leaves
    the packet's magnitude alone and changes what it met; the max-health reprice
    leaves what it met alone and changes the magnitude — and it does so by
    *replacing* the burn's authored ticks, so a declaration that was not carried
    across would not be wrong, it would be gone.
    """

    def test_the_reprice_really_fires_on_the_committed_roster(self):
        """`liandry_reprice_mage_roster` arms it, which is why it exists.

        Ruling 3's integration act added this roster for exactly this: a fight
        against a Protoplasm Harness holder, short enough that the lifeline's
        own expiry is not reached, so later burn ticks are priced against a
        raised maximum.  Armed means fired — the ticks after the lifeline are
        strictly larger than the ticks before it.
        """
        readings = _window_readings(LIANDRY_SEED, "liandry_reprice_mage_roster")
        amounts = [damage for reading in readings for damage, _ in reading.packets]
        assert amounts
        assert max(amounts) > min(amounts)

    def test_the_declaration_prices_to_the_pair_engines_own_tick(self):
        """Bit-exact, tick by tick, on the repriced ticks and the rest alike."""
        for reading in _window_readings(LIANDRY_SEED, "liandry_reprice_mage_roster"):
            for packet in reading.packets:
                damage, _ = packet
                assert reading.priced(LIANDRY_SEED, packet).amount == damage

    def test_a_repriced_tick_declares_the_published_resistance_and_a_moved_raw(self):
        """Which term moved, and which did not, asserted rather than described.

        Every tick met the magic resistance the fight published — the reprice is
        not a mitigation change — and the repriced ticks carry a raw magnitude
        strictly above the ticks the reprice did not reach.  A fixture that only
        checked the price would pass with both terms wrong by cancelling amounts.
        """
        raws = []
        for reading in _window_readings(LIANDRY_SEED, "liandry_reprice_mage_roster"):
            for _, declaration in reading.packets:
                assert declaration.effective_resistance == reading.published
                raws.append(declaration.raw_amount)
        assert max(raws) > min(raws)

    def test_dropping_the_carry_would_lose_the_declaration_entirely(self):
        """R-05's red for the carry, at the seam that would drop it.

        The reprice hands the row a freshly built tick list.  Run the same
        replacement without the carry and the ticks come back carrying no
        declaration at all — which is the failure mode this half of the ruling
        exists to stop, and it is a different one from pricing at a stale
        number.

        The carried declaration comes back at the declaration's *full* width,
        which is six positions since umbrella Amendment R: a burn no
        basic-attack swing delivered and no routing family re-delivered
        carries `None` in the fifth and the sixth, and `declared_packet_of`
        reads those as no swing composition and no route and prices the tick
        exactly as it priced it before the positions existed.
        """
        authored = [{"damage": 10.0, "declared": ("fixture.burn", 20.0, "other", 30.0)}]
        repriced = [{"time": 0.0, "damage_type": "magic", "damage": 12.0}]
        assert "declared" not in repriced[0]
        pair_engine._carry_declarations_onto_repriced_ticks(authored, repriced)
        assert repriced[0]["declared"] == (
            "fixture.burn",
            24.0,
            "other",
            30.0,
            None,
            None,
        )
        carried = AuthoredDeclaration(*repriced[0]["declared"])
        assert carried.swing_composition() is None
        assert carried.routing_provenance() is None

    def test_a_replacement_the_carry_cannot_join_is_refused(self):
        """R-05's second red: a positional carry that cannot say which tick.

        Refused only where a declaration actually rides one of the authored
        ticks — a burn nobody has retired has nothing to carry, and raising
        there would be the guard inventing a fight the engine has always run.
        """
        undeclared = [{"damage": 10.0}, {"damage": 10.0}]
        one_tick = [{"time": 0.0, "damage_type": "magic", "damage": 12.0}]
        pair_engine._carry_declarations_onto_repriced_ticks(undeclared, one_tick)

        declared = [
            {"damage": 10.0, "declared": ("fixture.burn", 20.0, "other", 30.0)},
            {"damage": 10.0},
        ]
        with pytest.raises(RuntimeError, match="positional carry"):
            pair_engine._carry_declarations_onto_repriced_ticks(declared, one_tick)


# ---------------------------------------------------------------------------
# D-62's uniqueness, for the number this slice arms
# ---------------------------------------------------------------------------


def test_no_leaf_sums_a_pair_preview_and_the_walks_amped_number():
    """D-62, stated for the term Amendment M, Ruling 1 lands.

    The double count a retirement act could create: one family's number
    delivered twice, once as the pair engine's row and once as the walk's own
    amp'd price.  The guard is structural and holds on both sides at once — a
    previewed pair row is excluded from everything the roster composes, and
    the walk pays a declaration only where a packet carries one.

    It holds vacuously today, and that is the reason to pin it now rather than
    on the commit that first pays one: this is the invariant the next thirteen
    retirement slices land against, and an invariant nobody wrote down before
    the first slice is one the first slice gets to define.
    """
    # No static holder amp is among the previewed mechanics, because none of
    # the three authors a summed pair row to preview: they are factors inside
    # `_mitigate` and `_add_item_proc_damage`, and the one row that names an
    # amp — `ability_amp_<owner>` — is stamped `informational` and never added
    # to the pair total.  The owners are read from the same amp-kind join the
    # coverage guard makes, so a fourth amp kind arrives here declared.
    amp_owners = {
        owner for owners in gs.holder_amp_declarations().values() for owner in owners
    }
    assert amp_owners
    previewed_owners = {
        mechanic.split(".", 1)[0] for mechanic in pair_preview_mechanics()
    }
    assert not previewed_owners & {
        owner.lower().replace(" ", "_").replace("'", "") for owner in amp_owners
    }

    # And the walk's side: a packet carrying no declaration pays the pair
    # engine's number and never the walk's, so the two contributions cannot
    # both exist for one packet by construction rather than by review.
    assert SurvivalAction().declared is None
    assert declared_packet_construction_sites() == ()

    # And the join that makes the two sides one property: every mechanic whose
    # pair row is a preview is either dropped from the roster composition or
    # re-priced from its declaration, never both.  The two sets partition the
    # previews, so no packet can carry the pair engine's number *and* the
    # walk's.
    assert walk_repriced_mechanics() <= pair_preview_mechanics()


# ---------------------------------------------------------------------------
# D-62's uniqueness, per retired family, on the roster that can see it
# ---------------------------------------------------------------------------
#
# The case above is the structural half and holds over the registry.  This one
# runs a committed coupled scenario that equips a declaring owner and reads
# what the two engines actually produced, because the failure this guards is a
# number appearing twice in one total and a set relation cannot see a number.
#
# Nothing is typed: the family, its owners and the covering scenario are all
# read, so the family a later retirement slice opts in is covered here on the
# commit that declares it.


def _repriced_owners_of(family):
    """The item names declaring a mechanic of *family* that the walk re-prices."""
    repriced = walk_repriced_mechanics()
    return frozenset(
        rule.owner
        for owner in rule_owners()
        for rule in behavior_rules(owner)
        if rule.family is family and rule.mechanic_id in repriced
    )


def _covering_scenarios_of(family):
    """Committed coupled scenarios equipping a declaring owner of *family*."""
    owners = _repriced_owners_of(family)
    return tuple(
        scenario
        for scenario in gs.COUPLED_SCENARIOS
        if scenario.equipped() & owners and not scenario.score_mode
    )


@cache
def _priced_declarations(scenario_name):
    """Every declaration the coupled walk priced in one scenario, as it priced it.

    Recorded at ``survival.transitions.apply_declared_price`` — the one site a
    declaration becomes a number — so what the case reads is the walk's own
    arithmetic and not a reconstruction of it.

    The subject and the event id ride beside the source key because D-62's
    uniqueness is keyed on ``(mechanic, subject, event_id)`` and a row is not
    an event: a family that authors one packet per swing authors many events
    under one row, and a key that stopped at the row would call a fight's
    fourteen honest applications a double count.
    """
    scenario = next(
        entry for entry in gs.COUPLED_SCENARIOS if entry.name == scenario_name
    )
    recorded = []
    real = transitions.apply_declared_price

    def probe(ctx, action, state):
        priced = real(ctx, action, state)
        recorded.append(
            (
                (
                    action.source_key,
                    action.subject,
                    EVENT_SLOTS.text(action.event_slot),
                ),
                action.declared,
                priced,
                {
                    "baseline_effective_armor": action.baseline_effective_armor,
                    "baseline_effective_mr": action.baseline_effective_mr,
                    "dynamic_bonus_armor": state.get("dynamic_bonus_armor", 0.0),
                    "dynamic_bonus_magic_resistance": state.get(
                        "dynamic_bonus_magic_resistance", 0.0
                    ),
                },
            )
        )
        return priced

    transitions.apply_declared_price = probe
    try:
        gs.coupled_entry(scenario)
    finally:
        transitions.apply_declared_price = real
    return tuple(recorded)


@pytest.mark.parametrize(
    "family", _repriced_families(), ids=lambda family: family.value
)
def test_a_retired_family_is_declared_by_the_pair_engine_and_priced_by_the_walk(family):
    """One family, both halves, on a roster that holds it (D-62, criterion 8).

    The pair engine authors the row and stamps it as a preview of the mechanic
    that declared it; every event under that row carries the declaration and
    no price the walk would have to trust.  The walk then prices exactly that
    declaration.  Both halves at once is what umbrella Amendment L, Ruling 1
    requires and what makes the number arrive once: the stamp is what takes
    the pair engine's figure out of the roster total, and the declaration is
    what puts the walk's own figure into it.
    """
    scenarios = _covering_scenarios_of(family)
    assert scenarios, f"no committed coupled scenario equips {family.value}"
    previews = pair_preview_mechanics()
    repriced = walk_repriced_mechanics()

    rows = 0
    family_rows = 0
    mechanics = frozenset(
        rule.mechanic_id
        for owner in rule_owners()
        for rule in behavior_rules(owner)
        if rule.family is family
    )
    for scenario in scenarios:
        parsed = parse_scenario_request(dict(scenario.request), deterministic=True)
        resolved = resolve_scenario(parsed)
        # EVERY pair of a roster scenario, not the first: a family whose rows
        # exist only at a SECONDARY roster target authors none in pair 0, so a
        # case that priced the first pair alone would report green over a
        # family it never reached.  A manual-target scenario has no enemies and
        # prices the request's own params.
        for params in resolved.target_fight_params or (resolved.fight_params,):
            result = run_fight(
                resolved.champion_data, parsed.level, list(resolved.items), params
            )
            for key, entry in result["breakdown"].items():
                stamp = (
                    entry.get("pair_preview_of") if isinstance(entry, Mapping) else None
                )
                if stamp not in repriced:
                    continue
                rows += 1
                if stamp in mechanics:
                    family_rows += 1
                assert stamp in previews, key
                events = entry.get("damage_events")
                assert isinstance(events, list), key
                assert events, key
                for event in events:
                    declaration = event.get("declared")
                    assert declaration is not None, key
                    authored = AuthoredDeclaration(*declaration)
                    routing = authored.routing_provenance()
                    if routing is None:
                        assert authored.rule_id == stamp, key
                    else:
                        # A ROUTING family's row re-delivers other families'
                        # packets, so the row previews the ROUTER and each
                        # declaration under it names the mechanic that owns
                        # its magnitude (umbrella Amendment R, Ruling 3).
                        assert routing.router_rule_id == stamp, key
                        assert authored.rule_id != stamp, key
                        assert 0.0 < routing.damage_share <= 1.0, key
                    assert authored.raw_amount > 0.0, key
    assert rows, f"no pair row previewed {family.value}"
    assert family_rows, f"no pair row previewed a mechanic of {family.value}"


@pytest.mark.parametrize(
    "family", _repriced_families(), ids=lambda family: family.value
)
def test_no_leaf_of_a_retired_family_sums_the_preview_and_the_walks_price(family):
    """The number arrives once, measured on the walk that pays it.

    Two things a set relation cannot say.  Every packet the walk priced from
    this family's declaration was priced **once** — one pricing per
    ``(mechanic, subject, event_id)``, which is D-62's own key — so no packet
    is paid by both the declaration and the pair engine's row that carried it.
    And the amount the walk paid is the declaration's own price rather than
    the figure the pair engine put on the packet, which is what "the pair row
    left the roster total" means when it is a number rather than a claim.

    The event id is part of the key rather than the row alone.  Every family
    that had retired before ``on_hit_strike`` authored at most one priced
    packet per row per fight in its covering population, so a
    ``(source_key, rule)`` key was accidentally unique there and stopped being
    so the moment a family authored one packet per swing.  Keying on the row
    would then have read a fight's fourteen honest applications as a double
    count, which is the opposite of what D-62 says.

    The **scenario** is part of the key for the same reason, one level up.
    D-62's uniqueness is a property of one walk: two independent scenarios
    that equip the same item against the same enemy roster price the same
    ``(mechanic, subject, event_id)`` in each of their own fights, and that is
    two honest pricings rather than one double count.  A key that pooled the
    scenarios was accidentally unique only while exactly one committed
    scenario covered each family.
    """
    scenarios = _covering_scenarios_of(family)
    assert scenarios, f"no committed coupled scenario equips {family.value}"
    repriced = walk_repriced_mechanics()

    priced = [
        (scenario.name, *record)
        for scenario in scenarios
        for record in _priced_declarations(scenario.name)
        if record[1] is not None and record[1].rule_id in repriced
    ]
    assert priced, f"the walk priced no declaration of {family.value}"
    keys = [(name, identity, packet.rule_id) for name, identity, packet, _, _ in priced]
    assert len(keys) == len(set(keys))

    for _scenario, source_key, packet, amount, resistances in priced:
        assert amount is not None, source_key
        # The paid number, re-computed from the declaration and the
        # resistances that packet met.  Equality is what says the roster total
        # holds the walk's price; a total still holding the pair engine's row
        # would have to be a different number, because the pair engine's is
        # what the packet's own `damage` field carries and this one is
        # mitigated here from a raw magnitude.
        assert amount == price_declared_packet(packet, **resistances).amount
        assert 0.0 < amount < packet.amped_raw, source_key


# ---------------------------------------------------------------------------
# on_hit_strike: an equivalence fixture per declaring owner
# ---------------------------------------------------------------------------
#
# The two cases above run the committed coupled scenarios, and exactly one of
# this family's eight owners is on one: `crit_onhit_carry_roster` holds Blade
# of the Ruined King and nothing committed holds the other seven.  A green
# zero over a population that cannot contain the defect is the shape umbrella
# Amendment N was written about, and umbrella Amendment P's answer for a
# family whose owners the covering set cannot reach is EQUIVALENCE FIXTURES
# PER OWNER -- a fixture set arming one owner proves nothing about the ones
# that can still fail.
#
# Two things vary across the eight and both are exercised here rather than
# argued.  Four of them declare magic, so the holder's magic amp is a live
# term for half this family, and the probe arms it: an Abyssal Mask on the
# holder makes `StaticHolderAmps.magic` something other than 1.0, on
# Amendment M, Ruling 1's own reasoning that a fixture set in which every amp
# is 1.0 proves the stage re-spells the case that cannot fail.  And one of
# them re-reads the target's falling health per application, so its
# applications do not share a magnitude, which the per-event comparison sees
# because it compares every event and not a row total.

#: The holder the probe equips, and the one item beside the owner under test.
#: Abyssal Mask is not decoration: it is the tree's only declaration of the
#: holder's static magic amp, so without it every magic strike below would be
#: priced at an amp of 1.0.
_ON_HIT_PROBE_CHAMPION = "Caitlyn"
_ON_HIT_AMP_OWNER = "Abyssal Mask"


def _on_hit_owners() -> tuple[str, ...]:
    """Every item declaring an ``on_hit_strike`` rule, read from the catalog."""
    return tuple(
        sorted(
            {
                rule.owner
                for owner in rule_owners()
                for rule in behavior_rules(owner)
                if rule.family is RuleFamily.ON_HIT_STRIKE
            }
        )
    )


@cache
def _on_hit_probe(owner: str):
    """One pair fight holding *owner* and the amp owner, with its walk inputs.

    The fight, the holder's resolved stats and the holder's own static amps —
    the three things the walk composes a :class:`DeclaredPacket` out of — read
    from the same instruments the coupled composition reads them from
    (``participant_timeline._holder_amps_of``'s own call), so what this
    compares is the walk's arithmetic rather than a restatement of it.
    """
    champion = gs.fetch_champion_data()[_ON_HIT_PROBE_CHAMPION]
    by_name = {data["name"]: data for data in gs.fetch_item_data().values()}
    items = [by_name[owner], by_name[_ON_HIT_AMP_OWNER]]
    params = FightParams(
        target_health=gs.SNAPSHOT_TARGET_HEALTH,
        target_bonus_health=0.0,
        target_armor=gs.SNAPSHOT_TARGET_ARMOR,
        target_magic_resistance=gs.SNAPSHOT_TARGET_MR,
        fight_duration_seconds=gs.ONE_ROTATION_DURATION,
        auto_attack_uptime=1.0,
        one_rotation=False,
        deterministic=True,
    )
    level = 18
    result = run_fight(champion, level, list(items), params)
    stats = calculate_total_stats(champion, level, list(items))
    amps = delta_amp.resolve_static_holder_amps(
        list(items),
        holder_stats=stats,
        ability_amp_armed=False,
        level=level,
        fight_duration_seconds=float(params.fight_duration_seconds),
        target_bonus_health=0.0,
        holder_is_melee=bool(stats.get("is_melee")),
    )
    return result, amps


@pytest.mark.parametrize("owner", _on_hit_owners())
def test_every_on_hit_owner_prices_from_its_declaration_to_the_pair_engines_number(
    owner,
):
    """One owner, every application: the walk's price is the pair engine's.

    The equivalence this family's retirement rests on, stated per owner
    because the committed coupled set reaches one of the eight.  For every
    event the pair engine authored under this owner's row, the declaration
    riding it, composed with the holder's own amps and mitigated once, equals
    the number the pair engine put on that event — which is what makes the
    retirement a re-spelling before it is a re-pricing (umbrella Amendment L,
    Ruling 3).
    """
    result, amps = _on_hit_probe(owner)
    row = result["breakdown"][f"on_hit_{owner}"]
    assert row["pair_preview_of"] in walk_repriced_mechanics()
    events = row["damage_events"]
    assert events, owner

    magnitudes = set()
    for event in events:
        packet = declared_packet_of(
            event["declared"],
            str(event["damage_type"]),
            f"on_hit_{owner}",
            amps,
        )
        price = price_declared_packet(
            packet,
            baseline_effective_armor=float(result["effective_armor"]),
            baseline_effective_mr=float(result["effective_mr"]),
        )
        assert price.amount == pytest.approx(float(event["damage"]), rel=1e-12)
        magnitudes.add(packet.raw_amount)
        # The amp term is delivered rather than defaulted, and a magic strike
        # is where that is visible: the probe holds the one item in the tree
        # that declares the holder's static magic amp.
        expected_amp = amps.magic if packet.damage_type == "magic" else 1.0
        assert packet.holder_amp == expected_amp
        if packet.damage_type == "magic":
            assert packet.holder_amp > 1.0

    # The one owner whose applications do not share a magnitude proves the
    # per-application declaration is doing work: a row total split evenly
    # would have priced its packets at a number no application had.
    tracks_health = row["pair_preview_of"] == "blade_of_the_ruined_king.on_hit"
    assert (len(magnitudes) > 1) is tracks_health


# ---------------------------------------------------------------------------
# periodic: an equivalence fixture per declaring owner
# ---------------------------------------------------------------------------
#
# :func:`_on_hit_probe`'s reason, for the other family that retired the same
# day and reaches even less of its own coverage.  Two of this family's seven
# owners are on a committed coupled scenario -- Sunfire Aegis on
# `immolate_active_bruiser_roster` and Liandry's Torment on
# `liandry_reprice_mage_roster` -- so five are outside every population, and
# with them a whole declared cadence: FIXED_INTERVAL is declared by Unending
# Despair alone.  Umbrella Amendment P's answer for that shape is equivalence
# fixtures PER OWNER, and this is it.
#
# The probe holds an Abyssal Mask beside the owner under test for the reason
# the on-hit probe does, and here it covers the whole family rather than half
# of it: all seven periodic strikes declare magic, so an amp of 1.0 anywhere
# in this fixture set would mean the amp term was never exercised at all.

#: A melee holder, so an aura and an interval strike both have a fight to run
#: in, and casts to stretch a burn's refresh window.
_PERIODIC_PROBE_CHAMPION = "Darius"


def _periodic_owners() -> tuple[str, ...]:
    """Every item declaring a ``periodic`` rule, read from the catalog."""
    return tuple(
        sorted(
            {
                rule.owner
                for owner in rule_owners()
                for rule in behavior_rules(owner)
                if rule.family is RuleFamily.PERIODIC
            }
        )
    )


@cache
def _periodic_probe(owner: str):
    """One pair fight holding *owner* and the amp owner, with its walk inputs."""
    champion = gs.fetch_champion_data()[_PERIODIC_PROBE_CHAMPION]
    by_name = {data["name"]: data for data in gs.fetch_item_data().values()}
    items = [by_name[owner], by_name[_ON_HIT_AMP_OWNER]]
    params = FightParams(
        target_health=gs.SNAPSHOT_TARGET_HEALTH,
        target_bonus_health=0.0,
        target_armor=gs.SNAPSHOT_TARGET_ARMOR,
        target_magic_resistance=gs.SNAPSHOT_TARGET_MR,
        fight_duration_seconds=gs.ONE_ROTATION_DURATION,
        auto_attack_uptime=1.0,
        one_rotation=False,
        deterministic=True,
    )
    level = 18
    result = run_fight(champion, level, list(items), params)
    stats = calculate_total_stats(champion, level, list(items))
    amps = delta_amp.resolve_static_holder_amps(
        list(items),
        holder_stats=stats,
        ability_amp_armed=False,
        level=level,
        fight_duration_seconds=float(params.fight_duration_seconds),
        target_bonus_health=0.0,
        holder_is_melee=bool(stats.get("is_melee")),
    )
    return result, amps


@pytest.mark.parametrize("owner", _periodic_owners())
def test_every_periodic_owner_prices_from_its_declaration_to_the_pair_engines_number(
    owner,
):
    """One owner, every tick: the walk's price is the pair engine's.

    The equivalence this family's retirement rests on, stated per owner
    because the committed coupled set reaches two of the seven and misses a
    whole cadence.  For every tick the pair engine authored under this owner's
    row, the declaration riding it, composed with the holder's own amps and
    mitigated once, equals the number the pair engine put on that tick -- which
    is what makes the retirement a re-spelling before it is a re-pricing
    (umbrella Amendment L, Ruling 3).
    """
    result, amps = _periodic_probe(owner)
    row = next(
        entry
        for key, entry in result["breakdown"].items()
        if isinstance(entry, Mapping)
        and entry.get("pair_preview_of") in _periodic_mechanics()
        and key.endswith(owner)
    )
    assert row["pair_preview_of"] in walk_repriced_mechanics()
    events = row["damage_events"]
    assert events, owner

    paid = 0.0
    for event in events:
        packet = declared_packet_of(
            event["declared"],
            str(event["damage_type"]),
            row["pair_preview_of"],
            amps,
        )
        price = price_declared_packet(
            packet,
            baseline_effective_armor=float(result["effective_armor"]),
            baseline_effective_mr=float(result["effective_mr"]),
        )
        assert price.amount == pytest.approx(float(event["damage"]), rel=1e-12)
        # All seven declare magic, so the holder's static magic amp is live
        # for the whole family and the probe arms it.
        assert packet.damage_type == "magic"
        assert packet.holder_amp == amps.magic > 1.0
        paid += price.amount

    # The ticks are the row: a cadence whose ticks summed to something else
    # would be a family the walk under- or over-pays by exactly the remainder.
    assert paid == pytest.approx(float(row["total_damage"]), rel=1e-12)


def _periodic_mechanics() -> frozenset[str]:
    """Every declared ``periodic`` mechanic id, read from the catalog."""
    return frozenset(
        rule.mechanic_id
        for owner in rule_owners()
        for rule in behavior_rules(owner)
        if rule.family is RuleFamily.PERIODIC
    )


# ---------------------------------------------------------------------------
# spellblade: an equivalence fixture per declaring owner
# ---------------------------------------------------------------------------
#
# :func:`_on_hit_probe`'s reason again, for the family that reaches the least
# of its own coverage of any retired so far.  ONE of this family's seven
# owners is on a committed coupled scenario — Bloodsong on
# `cleaver_bloodsong_roster` — so six are outside every population, and two of
# those six declare MAGIC: `dusk_and_dawn.spellblade` and
# `lich_bane.spellblade`.  A fixture set that armed only the covered owner
# would price a third of this family at an amp of 1.0 and never once exercise
# the term.  Umbrella Amendment P's answer for that shape is equivalence
# fixtures PER OWNER, and this is it.
#
# The probe holds an Abyssal Mask beside the owner under test for the reason
# the on-hit probe does: it is the tree's one declaration of the holder's
# static magic amp, so without it the two magic spellblades would be priced at
# an amp of 1.0 — Amendment M, Ruling 1's own reasoning that a fixture set in
# which every amp is 1.0 proves the stage re-spells the case that cannot fail.

#: A ranged caster, because a spellblade charge is armed by an ability cast
#: and spent by a basic attack, so the probe needs a rotation with both.
_SPELLBLADE_PROBE_CHAMPION = "Ezreal"


def _spellblade_owners() -> tuple[str, ...]:
    """Every item declaring a ``spellblade`` rule, read from the catalog."""
    return tuple(
        sorted(
            {
                rule.owner
                for owner in rule_owners()
                for rule in behavior_rules(owner)
                if rule.family is RuleFamily.SPELLBLADE
            }
        )
    )


@cache
def _spellblade_probe(owner: str):
    """One pair fight holding *owner* and the amp owner, with its walk inputs.

    ``_on_hit_probe``'s shape: the fight, the holder's resolved stats and the
    holder's own static amps, read from the same instruments the coupled
    composition reads them from, so what this compares is the walk's
    arithmetic rather than a restatement of it.

    The owner under test is bought FIRST because the engine arms the first
    spellblade a build carries and ignores the rest — a probe that let the
    build order decide would silently test one item seven times.
    """
    champion = gs.fetch_champion_data()[_SPELLBLADE_PROBE_CHAMPION]
    by_name = {data["name"]: data for data in gs.fetch_item_data().values()}
    items = [by_name[owner], by_name[_ON_HIT_AMP_OWNER]]
    params = FightParams(
        target_health=gs.SNAPSHOT_TARGET_HEALTH,
        target_bonus_health=0.0,
        target_armor=gs.SNAPSHOT_TARGET_ARMOR,
        target_magic_resistance=gs.SNAPSHOT_TARGET_MR,
        fight_duration_seconds=gs.ONE_ROTATION_DURATION,
        auto_attack_uptime=1.0,
        one_rotation=False,
        deterministic=True,
    )
    level = 18
    result = run_fight(champion, level, list(items), params)
    stats = calculate_total_stats(champion, level, list(items))
    amps = delta_amp.resolve_static_holder_amps(
        list(items),
        holder_stats=stats,
        ability_amp_armed=False,
        level=level,
        fight_duration_seconds=float(params.fight_duration_seconds),
        target_bonus_health=0.0,
        holder_is_melee=bool(stats.get("is_melee")),
    )
    return result, amps


@pytest.mark.parametrize("owner", _spellblade_owners())
def test_every_spellblade_owner_prices_from_its_declaration_to_the_pair_engines_number(
    owner,
):
    """One owner, every proc: the walk's price is the pair engine's.

    The equivalence this family's retirement rests on, stated per owner
    because the committed coupled set reaches one of the seven.  For every
    proc event the pair engine authored under this owner's row, the
    declaration riding it, composed with the holder's own amps and mitigated
    once, equals the number the pair engine put on that event.

    Every proc of one fight shares a magnitude here, and that is asserted
    rather than assumed: the engine prices one raw value per fight and
    multiplies its mitigated figure by the proc count, so a declaration that
    varied across events would mean this site had started splitting a total
    it does not split.
    """
    result, amps = _spellblade_probe(owner)
    row = result["breakdown"][f"spellblade_{owner}"]
    assert row["pair_preview_of"] in walk_repriced_mechanics()
    events = row["damage_events"]
    assert events, owner

    magnitudes = set()
    for event in events:
        packet = declared_packet_of(
            event["declared"],
            str(event["damage_type"]),
            f"spellblade_{owner}",
            amps,
        )
        price = price_declared_packet(
            packet,
            baseline_effective_armor=float(result["effective_armor"]),
            baseline_effective_mr=float(result["effective_mr"]),
        )
        assert price.amount == pytest.approx(float(event["damage"]), rel=1e-12)
        # Non-vacuity: a declaration is a pre-mitigation magnitude, so it is
        # strictly larger than what the target was actually paid.
        assert packet.raw_amount > price.amount > 0.0
        magnitudes.add(packet.raw_amount)
        # The amp term is delivered rather than defaulted, and the two magic
        # spellblades are where that is visible: the probe holds the one item
        # in the tree that declares the holder's static magic amp.
        expected_amp = amps.magic if packet.damage_type == "magic" else 1.0
        assert packet.holder_amp == expected_amp
        if packet.damage_type == "magic":
            assert packet.holder_amp > 1.0

    assert len(magnitudes) == 1, owner
    # The row is the procs: a family whose events summed to something else
    # would be one the walk under- or over-pays by exactly the remainder.
    paid = sum(float(event["damage"]) for event in events)
    assert paid == pytest.approx(float(row["total_damage"]), rel=1e-12)


def test_both_declared_spellblade_damage_classes_are_inside_the_fixture_set():
    """The fixture set covers the term the covering population cannot see.

    Five of the seven declare physical and two declare magic.  A per-owner
    fixture set that happened to reach only one class would leave the
    holder's magic amp unexercised for this family, which is the state the
    covering scenario is in on its own.
    """
    classes = {
        _spellblade_probe(owner)[0]["breakdown"][f"spellblade_{owner}"]["damage_type"]
        for owner in _spellblade_owners()
    }
    assert classes == {"physical", "magic"}


# ---------------------------------------------------------------------------
# The basic-attack swing composition — the equivalence fixtures, inert and armed
# ---------------------------------------------------------------------------
#
# Umbrella Amendment R, Ruling 1.  Every family retired before this one reaches
# its target through `damage._mitigate` and nothing else — a resistance and the
# holder's own amps, which is exactly what `price_declared_packet` carried.  A
# packet delivered as a BASIC-ATTACK SWING is priced by
# `damage._mitigate_basic_attack_swing` instead: it meets the target's plating
# multiplier, its critical-strike damage multiplier and Warden's Mail's Rock
# Solid, and the deterministic reading blends a crit branch against a non-crit
# one with each branch having met the flat subtraction on its own.
#
# THE FIXTURES MUST BE INERT AND ARMED, and the conjunction is load-bearing on
# exactly the reasoning that made Amendment M's fixtures cover `amp != 1.0` and
# Amendment N's cover both re-pricing windows: a fixture set in which every
# target-side term is inert proves the stage re-spells the case that cannot
# fail — a pricer that dropped the whole composition would reproduce the pair
# engine exactly.  So the seed is run in five target-side states and the
# no-composition reading is priced beside the ruled one in every armed state.
#
# THE SEED is the probe Amendment R measured: Caitlyn at level 18 holding
# Runaan's Hurricane and Blade of the Ruined King, deterministic, one rotation
# at full auto uptime, a roster target count of two with the bolt allocated to
# the second, against the snapshot target.  The armed values are read from the
# declaring items' own `ValueRef`s rather than typed, so a registry that stopped
# producing one fails here instead of quietly measuring a different fight.
#
# HOW THE DECLARATION GETS ONTO THE PACKET.  `secondary_target` has not retired,
# so no authoring site in `src/` stamps one; these fixtures stamp one the way its
# retirement slice would — inside the engine step that AUTHORS the bolt row,
# from the same `state` the engine prices with, taking the magnitude from the
# family's own interpreter and the target-side terms from the fight state that
# resolved them.  The rest of `run_fight` then runs untouched.

#: The pair engine's own step for the bolt row, and the row it authors.  Named
#: rather than searched for: the stamp has to land where the family's own
#: retirement slice would put it.
SWING_SEED_STEP = pair_engine._add_single_proc_on_hits
SWING_SEED_ROW = "secondary_Runaan's Hurricane"
SWING_SEED_RULE = "runaans_hurricane.secondary_target"
SWING_SEED_ITEMS = ("Runaan's Hurricane", "Blade of the Ruined King")


def _declared_target_term(owner, term):
    """The sourced number an owner's declaration names for one swing term."""
    return required_effect_value(
        owner,
        next(
            reference.key
            for rule in behavior_rules(owner)
            for reference in getattr(rule.payload, "values", ())
            if getattr(reference, "key", None) == term
        ),
    )


@cache
def _swing_seed_states():
    """The five target-side states the seed is measured in.

    One inert, then each of the three terms armed alone at the value its own
    item declares, then all three at once — because the terms interact: the
    plating factor scales the number Rock Solid's cap is a share of, and a
    fixture that only ever armed one at a time would never price that.
    """
    plating = _declared_target_term(
        "Plated Steelcaps", DefenseField.BASIC_DAMAGE_MULTIPLIER.value
    )
    crit = _declared_target_term(
        "Randuin's Omen", DefenseField.CRITICAL_STRIKE_DAMAGE_MULTIPLIER.value
    )
    flat = {
        "target_basic_damage_flat_reduction": _declared_target_term(
            "Warden's Mail", DefenseField.BASIC_DAMAGE_FLAT_REDUCTION.value
        ),
        "target_basic_damage_flat_reduction_cap": _declared_target_term(
            "Warden's Mail", DefenseField.BASIC_DAMAGE_FLAT_REDUCTION_CAP.value
        ),
    }
    return {
        "all_three": {
            "target_basic_damage_multiplier": plating,
            "target_critical_strike_damage_multiplier": crit,
            **flat,
        },
        "crit_damage": {"target_critical_strike_damage_multiplier": crit},
        "inert": {},
        "plating": {"target_basic_damage_multiplier": plating},
        "rock_solid": dict(flat),
    }


def _declare_swing_row(state):
    """Stamp the bolt row with the declaration its retirement slice would hand over.

    Every number comes off the engine's own `state`.  The magnitude is the
    family's own interpreter's — the declared share of the attacker's damage at
    the on-hit effectiveness of the swing that fired it — and the two target-side
    FACTORS are folded into it, which is what Ruling 1 rules they are: a pure
    factor on a linear mitigation composes into the declared magnitude and
    prices to the same real number.  What is not folded is the blend (two
    magnitudes, not one) and the capped flat subtraction, and those ride on the
    declaration as the swing composition.
    """
    row = state.breakdown.get(SWING_SEED_ROW)
    bolts = state.secondary_target_bolts
    if not isinstance(row, dict) or bolts is None:
        return
    raw = bolts.bolt_damage(
        state.champion_stats["attack_damage"]
    ) * pair_engine._on_hit_effectiveness(state)
    plating = float(state.target_basic_damage_multiplier)
    swing = BasicAttackSwing(
        crit_chance=float(state.crit_chance),
        crit_raw_amount=(
            raw
            * state.crit_multiplier
            * state.target_critical_strike_damage_multiplier
            * plating
        ),
        basic_damage_flat_reduction=float(state.target_basic_damage_flat_reduction),
        basic_damage_flat_reduction_cap=float(
            state.target_basic_damage_flat_reduction_cap
        ),
    )
    declaration = AuthoredDeclaration(
        SWING_SEED_RULE,
        raw * plating,
        AttackClass.BASIC_ATTACK.value,
        float(state.resists.effective_armor),
    ).delivered_as_a_swing(swing)
    for event in row.get("damage_events") or ():
        event["declared"] = tuple(declaration)


@cache
def _swing_seed_reading(case):
    """The seed fight in one target-side state, with its bolt row declared.

    Returns the finished pair-engine result and the holder's own static amps,
    read through the same composition the walk reads them through, so what the
    comparison isolates is the pricing rather than a restatement of it.
    """
    champion = gs.fetch_champion_data()[_ON_HIT_PROBE_CHAMPION]
    by_name = {data["name"]: data for data in gs.fetch_item_data().values()}
    items = [by_name[name] for name in SWING_SEED_ITEMS]
    level = 18
    params = FightParams(
        target_health=gs.SNAPSHOT_TARGET_HEALTH,
        target_bonus_health=0.0,
        target_armor=gs.SNAPSHOT_TARGET_ARMOR,
        target_magic_resistance=gs.SNAPSHOT_TARGET_MR,
        fight_duration_seconds=gs.ONE_ROTATION_DURATION,
        auto_attack_uptime=1.0,
        one_rotation=True,
        deterministic=True,
        roster_target_index=1,
        roster_target_count=2,
        **_swing_seed_states()[case],
    )
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            pair_engine,
            SWING_SEED_STEP.__name__,
            _stamping(SWING_SEED_STEP, _declare_swing_row),
        )
        result = run_fight(champion, level, list(items), params)
    stats = calculate_total_stats(champion, level, list(items))
    amps = delta_amp.resolve_static_holder_amps(
        list(items),
        holder_stats=stats,
        ability_amp_armed=False,
        level=level,
        fight_duration_seconds=float(params.fight_duration_seconds),
        target_bonus_health=0.0,
        holder_is_melee=bool(stats.get("is_melee")),
    )
    return result, amps


def _swing_seed_packets(case):
    """Every declared bolt packet of one state, as the walk composes it."""
    result, amps = _swing_seed_reading(case)
    row = result["breakdown"][SWING_SEED_ROW]
    return (
        result,
        row,
        tuple(
            (
                float(event["damage"]),
                declared_packet_of(event["declared"], "physical", SWING_SEED_ROW, amps),
            )
            for event in row["damage_events"]
        ),
    )


def _swing_seed_price(result, packet, *, composed=True):
    """The walk's price for one declared bolt packet, with or without the term."""
    return price_declared_packet(
        packet if composed else packet._replace(swing=None),
        baseline_effective_armor=float(result["effective_armor"]),
        baseline_effective_mr=float(result["effective_mr"]),
    )


#: Amendment R's own measured reading of this seed, per target-side state.  Not
#: a restatement of the engine: these are the four figures the amendment
#: published, pinned here so a seed that stopped being the seed the ruling was
#: measured on fails rather than quietly measuring a different fight.
#:
#: Re-measured for 16.16.1: Runaan's Hurricane's Wind's Fury bolt share moved
#: 55% AD -> 65% AD, so the seed's bolt raw moved 91.85 -> 108.55 at the pinned
#: Caitlyn probe's 167 AD and every figure below moved with it.  The three
#: multiplier states scale by the share ratio; ``rock_solid`` does not, because
#: Warden's Mail's flat 15.0 (capped at 0.2 of the instance) is a subtraction
#: and a bigger instance loses proportionally less to it.  That is also why the
#: published overpayment fell: 20.3% -> 19.3%.
SWING_SEED_PER_HIT = {
    "inert": 90.45833333333331,
    "plating": 81.4125,
    "crit_damage": 79.60333333333332,
    "rock_solid": 75.85333333333332,
}


class TestTheSeedIsTheOneTheRulingWasMeasuredOn:
    """Before the equivalence is worth anything, the fight has to be that fight."""

    @pytest.mark.parametrize("case", sorted(SWING_SEED_PER_HIT))
    def test_the_amendments_published_figure_reproduces(self, case):
        """All four, exactly, including the 50.0 armour they were priced at."""
        result, row, _ = _swing_seed_packets(case)
        assert float(result["effective_armor"]) == 50.0
        assert row["damage_per_hit"] == SWING_SEED_PER_HIT[case]

    def test_every_armed_state_moves_the_row_and_rock_solid_moves_it_most(self):
        """The armed states are not four spellings of the inert one.

        Stated as an ordering rather than as four more numbers: each term
        takes something off the swing, and Warden's Mail takes the most on
        this seed — which is the 19.3 percent the stopped retirement measured
        a walk would have paid over (20.3 before 16.16.1 widened the bolt;
        see ``SWING_SEED_PER_HIT``).
        """
        inert = SWING_SEED_PER_HIT["inert"]
        for case, figure in SWING_SEED_PER_HIT.items():
            if case != "inert":
                assert figure < inert
        assert SWING_SEED_PER_HIT["rock_solid"] == min(SWING_SEED_PER_HIT.values())
        overpayment = inert / SWING_SEED_PER_HIT["rock_solid"] - 1.0
        assert round(100 * overpayment, 1) == 19.3


@pytest.mark.parametrize("case", sorted(_swing_seed_states()))
class TestTheSwingCompositionReproducesThePairEngines:
    """Ruling 1's fixture, in every target-side state the seed is run in."""

    def test_the_declaration_carries_the_composition_and_the_family_is_deferred(
        self, case
    ):
        """The declaration the fixture stamps is the one the tree stamps.

        This asserted that `secondary_target` was still deferred and that the
        bolt row carried no stamp, which was the honest reading while the
        fixture stood in for a retirement nobody had performed.  The
        retirement landed on 2026-08-17, so the clause is now its successor
        and is a stronger one: the row the fixture stamps is stamped by the
        ENGINE, as a preview of the mechanic the walk re-prices, and the
        declaration the fixture builds carries the same composition and the
        same rule the engine's own does.  A fixture that went on asserting the
        family was deferred would be a case testing its own scaffolding.
        """
        assert (RuleFamily.SECONDARY_TARGET, EngineLane.RECEIPT_WALK) in INTERPRETERS
        _, row, packets = _swing_seed_packets(case)
        assert row["pair_preview_of"] == SWING_SEED_RULE
        assert SWING_SEED_RULE in walk_repriced_mechanics()
        assert packets
        for _, packet in packets:
            assert packet.swing is not None
            assert packet.rule_id == SWING_SEED_RULE
            # The bolt is the ROUTER'S OWN packet: it re-delivers nobody's
            # magnitude, so no routing rides it (umbrella Amendment R,
            # Ruling 3).  Its sibling row is the opposite shape.
            assert packet.routing is None

    def test_the_declaration_prices_to_the_pair_engines_own_number(self, case):
        """Bit-exact, on identical inputs — the whole of what Ruling 1 claims.

        The pair engine mitigates each branch once at the fight's armour, takes
        the capped flat subtraction off each, and blends them; the walk's own
        pricer, given the same magnitudes and the same resistance, returns the
        same float.  Bit-for-bit is available because both sides perform the
        same multiplications: the two folded factors compose into the magnitude
        before the one mitigation, and `apply_resistance` is a single multiply
        by a factor the fight resolved once.
        """
        result, _, packets = _swing_seed_packets(case)
        for damage, packet in packets:
            assert _swing_seed_price(result, packet).amount == damage

    def test_the_row_total_is_the_sum_of_the_priced_packets(self, case):
        """The row, not only its events: a per-packet equality can still miss one."""
        result, row, packets = _swing_seed_packets(case)
        priced = sum(_swing_seed_price(result, packet).amount for _, packet in packets)
        assert priced == pytest.approx(float(row["total_damage"]), rel=1e-12)

    def test_dropping_the_transported_term_is_visible_where_it_is_armed(self, case):
        """R-05's red for the term, and the reason an inert fixture is not enough.

        The transported half of the composition is Rock Solid, and this prices
        the same declaration with it zeroed.  Where the defender does not hold
        Warden's Mail the two readings agree — which is exactly why a fixture
        set in which every target-side term is inert proves the case that
        cannot fail — and where the defender does, the reading without the term
        pays strictly more, by a margin every committed gate can see.
        """
        result, _, packets = _swing_seed_packets(case)
        armed = "target_basic_damage_flat_reduction" in _swing_seed_states()[case]
        for damage, packet in packets:
            unreduced = packet._replace(
                swing=packet.swing._replace(
                    basic_damage_flat_reduction=0.0,
                    basic_damage_flat_reduction_cap=0.0,
                )
            )
            without = _swing_seed_price(result, unreduced).amount
            if not armed:
                assert without == damage
            else:
                assert without > damage
                assert round(without - damage, GOLDEN_DECIMALS) > 0.0

    def test_dropping_the_whole_composition_moves_the_number_either_way(self, case):
        """The blend's own red, and the sign is measured rather than assumed.

        A pricer that ignored the composition entirely would pay the non-crit
        branch alone — the reading a declaration carrying no swing gets, which
        is right for every family retired so far and wrong for this one.  It is
        never the same number, and which way it is wrong depends on the state:
        with the target inert it is too SMALL, because the crit branch it
        deleted is the larger of the two, and with all three terms armed it is
        too LARGE, because the subtraction it also deleted takes more off the
        blend than the missing crit branch put on.  Recorded as the pair it is,
        because a red asserted in one direction would have gone green on the
        state where the number is most wrong.
        """
        result, _, packets = _swing_seed_packets(case)
        for damage, packet in packets:
            without = _swing_seed_price(result, packet, composed=False).amount
            assert round(abs(without - damage), GOLDEN_DECIMALS) > 0.0
            if case == "inert":
                assert without < damage
            elif case == "all_three":
                assert without > damage


class TestRockSolidIsCarriedAsASubtractionAndNeverFolded:
    """The term Ruling 1 says never folds, and why no magnitude reproduces it."""

    def test_the_cap_bites_on_one_branch_and_not_the_other(self):
        """The measured fact that makes the term un-foldable.

        Both branches meet `min(flat, per_hit × cap)`, and on this seed the
        crit branch is large enough to pay the flat in full while the non-crit
        branch is capped at a share of itself.  A factor on the blended number
        cannot produce that, because the two branches lose different fractions
        of themselves.
        """
        result, _, packets = _swing_seed_packets("rock_solid")
        _, packet = packets[0]
        swing = packet.swing
        armour = float(result["effective_armor"])
        non_crit = mitigate_declared(packet.amped_raw, "physical", armour)
        crit = mitigate_declared(packet.amped_crit_raw, "physical", armour)
        flat = swing.basic_damage_flat_reduction
        assert non_crit * swing.basic_damage_flat_reduction_cap < flat
        assert crit * swing.basic_damage_flat_reduction_cap > flat
        assert crit - swing.less_flat_reduction(crit) == flat
        assert non_crit - swing.less_flat_reduction(non_crit) == pytest.approx(
            non_crit * swing.basic_damage_flat_reduction_cap
        )

    def test_no_single_factor_on_the_blend_reproduces_both_branches(self):
        """Stated as the impossibility it is, not as a preference.

        If the subtraction were a factor there would be one number `f` with
        `priced == f × unreduced` for the blend *and* for each branch.  There
        is not: the two branches' own ratios differ, so a declaration that
        folded any single factor would be wrong on at least one of them.
        """
        result, _, packets = _swing_seed_packets("rock_solid")
        _, packet = packets[0]
        swing = packet.swing
        armour = float(result["effective_armor"])
        branches = (
            mitigate_declared(packet.amped_raw, "physical", armour),
            mitigate_declared(packet.amped_crit_raw, "physical", armour),
        )
        ratios = {swing.less_flat_reduction(branch) / branch for branch in branches}
        assert len(ratios) == 2

    def test_a_subtraction_can_never_drive_a_branch_below_zero(self):
        """The floor the pair engine applies, applied here for the same reason."""
        swing = BasicAttackSwing(
            crit_chance=0.0,
            crit_raw_amount=0.0,
            basic_damage_flat_reduction=1000.0,
            basic_damage_flat_reduction_cap=1.0,
        )
        assert swing.less_flat_reduction(10.0) == 0.0
        # A negative branch is an algebraic modifier to a swing, not an
        # incoming event, and a flat defensive proc cannot be consumed by one.
        assert swing.less_flat_reduction(-10.0) == -10.0


class TestTheBlendIsTheDeterministicReadingAndNotAnAverage:
    """The other half of what a declared magnitude cannot carry."""

    def test_the_weight_is_the_holders_crit_chance(self):
        """Read off the seed rather than restated: the blend is affine in it."""
        _, _, packets = _swing_seed_packets("inert")
        _, packet = packets[0]
        swing = packet.swing
        assert 0.0 < swing.crit_chance < 1.0
        assert swing.blended(0.0, 1.0) == swing.crit_chance
        assert swing.blended(100.0, 100.0) == 100.0

    def test_a_declaration_no_swing_delivered_carries_no_composition(self):
        """The inertness this slice rests on, at the type rather than the tree.

        A three- or four-wide declaration — every one the tree authors — resolves
        to no composition, and the packet built from it is priced by the
        resistance and the amps alone.
        """
        for width in (3, 4):
            declaration = AuthoredDeclaration(
                "fixture.rule", 100.0, AttackClass.OTHER.value, 50.0
            )[:width]
            assert AuthoredDeclaration(*declaration).swing_composition() is None
        packet = DeclaredPacket(100.0, "physical", "fixture.rule")
        assert packet.swing is None
        assert price_declared_packet(
            packet, baseline_effective_armor=50.0, baseline_effective_mr=50.0
        ).amount == mitigate_declared(100.0, "physical", 50.0)


# ---------------------------------------------------------------------------
# The routing family — umbrella Amendment R, Ruling 3
# ---------------------------------------------------------------------------
#
# `secondary_target` authors two priced pair rows and declares a magnitude for
# neither.  Wind's Fury's bolt is a declared SHARE of the swing that fired it,
# and the copied on-hit row is the attack's own on-hit packets re-delivered at
# the bolt's target.  Ruling 3 rules that the family is a ROUTING family: it
# re-delivers source families' declared magnitudes at a second subject and
# declares no magnitude of its own, so the routed packet is priced from the
# SOURCE family's declaration composed with the router's share, attributed
# under D-62 at (source mechanic, secondary subject, event_id), with the
# routing recorded in provenance.
#
# The seed is the same Caitlyn probe Ruling 1's fixtures run on, which is what
# makes the two rulings' fixtures one measurement of one fight rather than two.

#: The engine's own row for the copied on-hit packets, and the mechanic that
#: routes them.  The router is read off the family's own slot rather than
#: spelled, so a renamed mechanic fails here.
COPIED_ROW = "on_hit_secondary_Runaan's Hurricane"


@cache
def _routing_slot():
    """The `secondary_target` slot the seed fight resolved, and its build state.

    Captured from inside the engine step that authors both routed rows, so what
    the fixtures read is the declaration the fight actually used rather than a
    second resolution of it.  Its own run, with a capture-only wrapper: the
    routing facts are the same in every target-side state, so there is nothing
    for a stamped declaration to add here.
    """
    captured = {}

    def capture(state):
        bolts = state.secondary_target_bolts
        if bolts is None:  # pragma: no cover - the seed always holds one
            return
        captured.setdefault(
            "slot",
            (
                bolts,
                float(state.champion_stats["attack_damage"]),
                pair_engine._on_hit_effectiveness(state),
                tuple(state.per_hit_strikes),
                float(state.target_health),
                state.level,
                bool(state.is_melee),
                dict(state.champion_stats),
            ),
        )

    champion = gs.fetch_champion_data()[_ON_HIT_PROBE_CHAMPION]
    by_name = {data["name"]: data for data in gs.fetch_item_data().values()}
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            pair_engine, SWING_SEED_STEP.__name__, _stamping(SWING_SEED_STEP, capture)
        )
        run_fight(
            champion,
            18,
            [by_name[name] for name in SWING_SEED_ITEMS],
            FightParams(
                target_health=gs.SNAPSHOT_TARGET_HEALTH,
                target_bonus_health=0.0,
                target_armor=gs.SNAPSHOT_TARGET_ARMOR,
                target_magic_resistance=gs.SNAPSHOT_TARGET_MR,
                fight_duration_seconds=gs.ONE_ROTATION_DURATION,
                auto_attack_uptime=1.0,
                one_rotation=True,
                deterministic=True,
                roster_target_index=1,
                roster_target_count=2,
            ),
        )
    return captured["slot"]


def _routing_provenance():
    """The routing this family declares, built from its own compiled fields."""
    slot = _routing_slot()[0]
    return RoutingProvenance(
        slot.rule.mechanic_id, slot.value(secondary_target.DAMAGE_SHARE_FIELD)
    )


class TestTheRouterDeclaresNoMagnitude:
    """D-60's half of Ruling 3, asserted against the declaration itself."""

    def test_the_declaration_compiles_exactly_the_two_routing_facts(self):
        """`max_targets` and `damage_share`, and nothing that sizes a packet.

        Read off the slot the seed fight resolved rather than off a list here,
        so a third compiled field — a magnitude under any name — fails on the
        commit that adds it.  That is the whole of what keeps this family from
        becoming a second producer of a number a source family declares.
        """
        slot = _routing_slot()[0]
        assert {field.name for field in slot.fields} == {
            secondary_target.MAX_TARGETS_FIELD,
            secondary_target.DAMAGE_SHARE_FIELD,
        }

    def test_neither_routing_fact_is_a_magnitude(self):
        """A count and a fraction: one bounds subjects, one scales somebody else's.

        Stated as the arithmetic property it is — the share is a fraction of a
        packet and the cap is a whole number of subjects — because "not a
        magnitude" is otherwise a claim about naming.
        """
        slot = _routing_slot()[0]
        share = slot.value(secondary_target.DAMAGE_SHARE_FIELD)
        cap = slot.value(secondary_target.MAX_TARGETS_FIELD)
        assert 0.0 < share <= 1.0
        assert cap == int(cap) >= 1

    def test_the_family_is_served_by_its_own_lane_and_still_declares_no_magnitude(self):
        """Ruling 3 retired nothing; the retirement that followed it did.

        What survives the row's retirement is the clause this class is about,
        and the reason it outlives the row: the family's interpreter answers
        for the lane it declares, AND its declaration is still exactly two
        routing facts.  A retirement that had given the router a magnitude
        would pass a registry check and fail this one.
        """
        assert (RuleFamily.SECONDARY_TARGET, EngineLane.RECEIPT_WALK) in INTERPRETERS
        slot = _routing_slot()[0]
        assert {field.name for field in slot.fields} == {
            secondary_target.MAX_TARGETS_FIELD,
            secondary_target.DAMAGE_SHARE_FIELD,
        }


class TestARoutedPacketIsTheSourceFamilysNumber:
    """The composition, on the seed the amendment measured."""

    def test_the_bolt_is_the_swings_magnitude_at_the_declared_share(self):
        """Bit-exact against the raw the pair engine's own slot computed.

        The source family's magnitude is the attacker's damage at the on-hit
        effectiveness of the swing that fired the bolt; the router contributes
        the share.  `route_declared_packet` composes them and reproduces
        `SecondaryTargetSlot.bolt_damage`'s own number, which is the one the
        engine mitigated.
        """
        slot, attack_damage, effectiveness, *_ = _routing_slot()
        routing = _routing_provenance()
        source = DeclaredPacket(
            attack_damage * effectiveness, "physical", "fixture.swing"
        )
        routed = route_declared_packet(source, routing)
        assert routed.raw_amount == slot.bolt_damage(attack_damage) * effectiveness
        # The seed figure, re-measured on 16.16.1 data: Runaan's bolt share
        # moved 55% -> 65% this patch, so this number moved with the
        # declaration the line above reads it from.  Nothing about the
        # composition changed -- that is what the line above pins.
        assert routed.raw_amount == 108.55

    def test_the_routed_packet_keeps_the_source_mechanic_and_names_the_route(self):
        """D-62's key and the provenance beside it, in one assertion each.

        The magnitude belongs to the family that declared it, so `rule_id`
        does not move; what the router contributes is recorded as the routing
        it is.  A routed packet whose `rule_id` became the router's would
        attribute a source family's damage to a family that declared none.
        """
        routing = _routing_provenance()
        source = DeclaredPacket(100.0, "physical", "blade_of_the_ruined_king.on_hit")
        routed = route_declared_packet(source, routing)
        assert routed.rule_id == source.rule_id
        assert routed.routing == routing
        assert routed.routing.router_rule_id == "runaans_hurricane.secondary_target"
        assert source.routing is None

    def test_every_other_term_rides_across_untouched(self):
        """A route is not a re-pricing: it changes the size and nothing else.

        The resistance the source packet met, the holder's amps and the swing
        composition are facts about the packet rather than about how it
        travelled, so they cross unchanged — and the crit branch is scaled by
        the same share as the non-crit one, because a share of a swing is a
        share of both its branches.
        """
        routing = _routing_provenance()
        share = routing.damage_share
        source = DeclaredPacket(
            100.0,
            "physical",
            "fixture.swing",
            holder_amp=1.25,
            effective_resistance=42.0,
            swing=BasicAttackSwing(crit_chance=0.25, crit_raw_amount=200.0),
        )
        routed = route_declared_packet(source, routing)
        assert routed.holder_amp == source.holder_amp
        assert routed.effective_resistance == source.effective_resistance
        assert routed.damage_type == source.damage_type
        assert routed.swing.crit_chance == source.swing.crit_chance
        assert routed.swing.crit_raw_amount == 200.0 * share
        assert routed.raw_amount == 100.0 * share

    def test_a_share_that_is_not_a_fraction_is_refused_by_name(self):
        """R-05's red for the composition: a router cannot amplify what it routes.

        Refused rather than clamped, because paying the smaller number would
        be this function silently deciding a question its caller got wrong.
        """
        source = DeclaredPacket(100.0, "physical", "fixture.swing")
        for share in (1.5, -0.1):
            with pytest.raises(ValueError, match=re.escape("fixture.rout")):
                route_declared_packet(
                    source, RoutingProvenance("fixture.router", share)
                )


class TestTheCopiedRowsMagnitudesBelongToTheOnHitFamily:
    """Ruling 3's other half, measured on the row that opened the question."""

    def test_the_first_copied_packet_is_an_on_hit_declaration_priced_at_the_subject(
        self,
    ):
        """The magnitude is the source family's, and the router declares none.

        At the first application the secondary subject is still at the fight's
        own target health, so the source declaration is exactly what the
        `on_hit_strike` family's own interpreter states there.  Routed whole —
        the router re-delivers on-hit packets rather than sharing them — and
        priced at the fight's armour, it reproduces the number the pair engine
        put on the row's first event.
        """
        result, _ = _swing_seed_reading("inert")
        row = result["breakdown"][COPIED_ROW]
        _, _, effectiveness, strikes, target_health, level, is_melee, stats = (
            _routing_slot()
        )
        declared = sum(
            strike.source.raw_damage(
                DamageInputs(
                    champion_stats=stats,
                    level=level,
                    is_melee=is_melee,
                    target_max_health=target_health,
                    target_current_health=target_health,
                )
            )
            * effectiveness
            for strike in strikes
            if strike.source.damage_type == "physical"
        )
        source = DeclaredPacket(declared, "physical", "blade_of_the_ruined_king.on_hit")
        routed = route_declared_packet(
            source, RoutingProvenance(_routing_provenance().router_rule_id, 1.0)
        )
        price = price_declared_packet(
            routed,
            baseline_effective_armor=float(result["effective_armor"]),
            baseline_effective_mr=float(result["effective_mr"]),
        )
        # Non-vacuity first: an equality between two zeros proves nothing, and
        # the source declaration is strictly larger than the priced packet
        # because the packet met the fight's armour on the way in.
        assert declared > price.amount > 0.0
        assert price.amount == float(row["damage_events"][0]["damage"])
        assert routed.rule_id == "blade_of_the_ruined_king.on_hit"

    def test_the_source_family_declares_the_magnitude_and_the_router_declares_none(
        self,
    ):
        """One producer each, which is what makes the two rows priceable at all.

        The magnitudes the copied row carries belong to a family the walk
        prices from its own declarations, and the family that re-delivered
        them declares none — which is the property, and it is unchanged by
        `secondary_target` retiring on 2026-08-17.  What moved is that both
        families are served by their own lane now; what did not is which of
        them owns a number.  A router that declared one would be the second
        producer criterion 8 forbids.
        """
        assert (RuleFamily.ON_HIT_STRIKE, EngineLane.RECEIPT_WALK) in INTERPRETERS
        assert (RuleFamily.SECONDARY_TARGET, EngineLane.RECEIPT_WALK) in INTERPRETERS
        slot = _routing_slot()[0]
        assert slot.applies_on_hit
        assert all(
            field.name
            in (
                secondary_target.MAX_TARGETS_FIELD,
                secondary_target.DAMAGE_SHARE_FIELD,
            )
            for field in slot.fields
        )


class TestTheCopiedRowPricesFromItsRoutedDeclarations:
    """The retirement's own equivalence for the routed half.

    The class above measures Ruling 3's arithmetic on one hand-built packet.
    This measures the ENGINE's: every event the pair engine authored under the
    copied row carries a routed declaration, and pricing that declaration the
    way the walk prices it returns the number the pair engine put on that
    event.  Both halves of the family are then equivalences rather than one
    equivalence and one description — the bolt's is the five-state swing
    fixture above, and this is the copied row's.
    """

    def test_every_copied_event_prices_to_the_pair_engines_own_number(self):
        """Bit-exact per event, over the seed's own five target-side states.

        The copied packets are priced by `damage._mitigate` and not by the
        swing composition — a copied on-hit effect is not itself a swing — so
        what varies across the five states is the SUBJECT's health rather than
        the packet's terms, and the equality has to hold in each of them
        because a secondary target that took less from the bolt carries more
        health into the current-health strikes that follow it.
        """
        for case in sorted(_swing_seed_states()):
            result, amps = _swing_seed_reading(case)
            row = result["breakdown"][COPIED_ROW]
            assert row["pair_preview_of"] == SWING_SEED_RULE
            events = row["damage_events"]
            assert events, case
            for event in events:
                packet = declared_packet_of(
                    event["declared"], str(event["damage_type"]), COPIED_ROW, amps
                )
                price = price_declared_packet(
                    packet,
                    baseline_effective_armor=float(result["effective_armor"]),
                    baseline_effective_mr=float(result["effective_mr"]),
                )
                assert price.amount == pytest.approx(
                    float(event["damage"]), rel=1e-12
                ), case
                # Non-vacuity, and the routing beside it: a pre-mitigation
                # magnitude is strictly larger than what the subject was paid,
                # and the packet says who re-delivered it.
                assert packet.raw_amount > price.amount > 0.0, case
                assert packet.routing.router_rule_id == SWING_SEED_RULE, case

    def test_the_two_rows_are_declared_by_two_different_producers(self):
        """D-60's half of the retirement, read off the engine's own rows.

        The bolt names the router and the copied packets name the families
        that declared their magnitudes — one producer each, two subjects, no
        number declared twice.  Stated over the engine's rows rather than over
        a hand-built pair, because what could go wrong is a stamping site
        naming the wrong one.
        """
        result, _ = _swing_seed_reading("inert")
        bolt = {
            AuthoredDeclaration(*event["declared"]).rule_id
            for event in result["breakdown"][SWING_SEED_ROW]["damage_events"]
        }
        copied = {
            AuthoredDeclaration(*event["declared"]).rule_id
            for event in result["breakdown"][COPIED_ROW]["damage_events"]
        }
        assert bolt == {SWING_SEED_RULE}
        assert copied
        assert SWING_SEED_RULE not in copied
        assert copied <= walk_repriced_mechanics()


class TestTheRoutingReachesTheReceipt:
    """Provenance is published, because a fact nobody can read is not one."""

    def test_a_routed_price_publishes_its_router_and_its_share(self):
        """The `routing` block beside the source mechanic, on the walk's own row.

        Driven through `run_survival_walk` rather than around it, so what is
        asserted is the receipt the kernel writes.
        """
        routing = _routing_provenance()
        packet = route_declared_packet(
            DeclaredPacket(252.0, "magic", "wits_end.on_hit"), routing
        )
        row = _walk_one_declared_packet(packet)["declared_price"]
        assert row["rule"] == "wits_end.on_hit"
        assert row["raw"] == round(252.0 * routing.damage_share, 6)
        assert row["routing"] == {
            "router": routing.router_rule_id,
            "damage_share": routing.damage_share,
        }

    def test_a_packet_that_reached_its_subject_directly_publishes_no_routing(self):
        """Absent rather than false: nobody claimed anything about it.

        Every packet a retired family authors today is this one, so a key that
        were always present would publish "not routed" as a fact about the
        whole model.
        """
        row = _walk_one_declared_packet(
            DeclaredPacket(252.0, "magic", "wits_end.on_hit")
        )["declared_price"]
        assert "routing" not in row

    def test_d62_keys_the_two_deliveries_apart_by_their_subject(self):
        """The key that makes one producer at two subjects two contributions.

        `(mechanic, subject, event_id)` is D-62's own, and the subject is what
        keeps a routed packet clear of the same mechanic's primary delivery —
        which is precisely why Ruling 3 could leave `rule_id` on the source.
        """
        routing = _routing_provenance()
        source = DeclaredPacket(100.0, "physical", "blade_of_the_ruined_king.on_hit")
        routed = route_declared_packet(source, routing)
        assert routed.rule_id == source.rule_id
        keys = {
            (source.rule_id, 0, 7),
            (routed.rule_id, 1, 7),
        }
        assert len(keys) == 2


class TestTemporaryMaximumIsOneRule:
    """The Wiki's maximum-health-decrease rule, once, for both walks.

    This walk carries two temporary maxima — an overheal-converted grant and
    an armed temporary-health Lifeline — and the ordered damage walk carries
    the Lifeline.  All of them route through
    ``shield_ledger.expire_temporary_max_health``, so the arithmetic that
    distinguishes the sourced rule from a naive clamp (health the defender
    *spent into* survives; only an overhang is lost) cannot come out
    differently depending on which engine ran.

    https://wiki.leagueoflegends.com/en-us/Health, cached by
    ``python scripts/decompose_wiki.py --fetch "Health"``.
    """

    @staticmethod
    def _state(pools):
        return {
            "pools": pools,
            "temporary_health_amount": 0.0,
            "temporary_health_until": 0.0,
            "temporary_health_expired_at": None,
        }

    def test_an_overheal_grant_keeps_the_health_it_was_spent_into(self):
        pools = shield_ledger.ShieldPools(health=700.0, max_health=1200.0)
        state = self._state(pools)
        state["temporary_health_amount"] = 200.0
        state["temporary_health_until"] = 5.0

        assert transitions.expire_temporary_health(state, 5.0) is True
        assert (pools.health, pools.max_health) == (700.0, 1000.0)
        assert state["temporary_health_expired_at"] == 5.0

    def test_the_lifeline_now_expires_in_this_walk_too(self):
        """The same 700-of-1000 the ordered damage walk reaches.

        ``test_protoplasm_temporary_maximum_lapses_on_the_wiki_health_rule``
        drives these exact numbers through the pair engine; this drives them
        through the survival walk's own window edge.  One mechanic, one
        answer.
        """
        pools = shield_ledger.build_pools(
            1000.0,
            threshold_health_bonus=200.0,
            threshold_health_heal=300.0,
            threshold_health_ratio=0.30,
            threshold_health_duration=5.0,
        )
        outcome = shield_ledger.absorb(pools, 800.0, "magic", 0.0)
        assert outcome.threshold_health_triggered is True
        assert (pools.health, pools.max_health) == (400.0, 1200.0)
        pools.health += 300.0  # the walk's heal author delivers the sourced heal

        transitions.finalize_states([self._state(pools)], 5.0)

        assert (pools.health, pools.max_health) == (700.0, 1000.0)

    def test_a_lifeline_inside_its_window_is_left_alone(self):
        pools = shield_ledger.build_pools(
            1000.0,
            threshold_health_bonus=200.0,
            threshold_health_heal=300.0,
            threshold_health_ratio=0.30,
            threshold_health_duration=5.0,
        )
        shield_ledger.absorb(pools, 800.0, "magic", 0.0)

        transitions.finalize_states([self._state(pools)], 4.0)

        assert pools.max_health == 1200.0


def test_existing_shield_gate_uses_the_cast_time_snapshot_in_both_adapters():
    """A heal gated on a shield reads the shield the *cast* saw, not the hit.

    Ported from main's certification suite onto this branch's API: the
    packet declares ``requires_existing_shield`` plus the subject and
    timestamp its gate snapshots (``shield_gate_subject`` /
    ``shield_gate_time``), and the walk answers from
    ``TransitionContext.shield_presence_at_time`` so both adapters read one
    answer.  The shield is gone by the time the heal lands; the cast-time
    snapshot is what makes the heal pay.
    """

    from src.calculator.participant_timeline import Combatant
    from src.calculator.program.build import roster_program
    from src.calculator.program.compile import action_from_event
    from src.calculator.program.views.survival import survival
    from src.calculator.program.walk import walk as run_one_walk
    from src.calculator.survival import (
        EVENT_SLOTS,
        ActionKind,
        ReceiptLedger,
        ScoreLedger,
        SurvivalAction,
        TransitionContext,
        TransitionRank,
        build_states,
    )

    combatant = Combatant(
        participant_id="target",
        team="ally",
        champion_data={"name": "target"},
        level=1,
        items=(),
        stats={"health": 100.0, "is_melee": True},
        defenses=StartingDefenses(
            magic_shield=0.0,
            physical_shield=0.0,
            general_shield=20.0,
            healing_received_multiplier=1.0,
        ),
    )
    actions = [
        SurvivalAction(
            sort_key=(0.0, TransitionRank.DAMAGE, 0, 0, 0, "target", "hit", "auto"),
            time=0.0,
            phase=TransitionRank.DAMAGE,
            kind=ActionKind.PLAIN_DAMAGE,
            subject=0,
            attacker=0,
            aidx=0,
            amount=30.0,
            damage_type="physical",
            source_key="auto_attacks",
            source="auto_attacks",
            event_slot=EVENT_SLOTS.slot("hit"),
            sequence=0,
        ),
        SurvivalAction(
            sort_key=(
                1.0,
                TransitionRank.RECOVERY,
                0,
                0,
                0,
                "target",
                "heal",
                "heal",
            ),
            time=1.0,
            phase=TransitionRank.RECOVERY,
            kind=ActionKind.HEAL,
            subject=0,
            attacker=0,
            aidx=1,
            amount_formula=lambda current, maximum: (max(0.0, maximum - current) * 0.5),
            requires_existing_shield=True,
            shield_gate_subject=0,
            shield_gate_time=0.0,
            source_key="seraphine_w_heal",
            source="Surround Sound · Heal",
            event_slot=EVENT_SLOTS.slot("heal"),
            sequence=0,
        ),
    ]

    def _walk(ledger_cls):
        states = build_states([combatant], (0.0,))
        if ledger_cls is ReceiptLedger:
            walk_actions = [action._replace(event={}) for action in actions]
            ledger = ledger_cls(
                actions=list(walk_actions),
                index_of={"target": 0},
                compile_event=action_from_event,
                annotating=False,
            )
        else:
            walk_actions = actions
            ledger = ledger_cls(len(actions))
        ctx = TransitionContext(
            duration=5.0,
            states=states,
            combatants=[combatant],
            index_of={"target": 0},
            ledger=ledger,
            regeneration_windows=(None,),
        )
        result = run_one_walk(walk_actions, ctx)
        return survival(roster_program([combatant]), result)["target"]

    receipt_row = _walk(ReceiptLedger)
    score_row = _walk(ScoreLedger)
    assert receipt_row == score_row
    assert score_row["healing_received"] == 5.0


# ---------------------------------------------------------------------------
# A cancelled route, and the packet it hands back
# ---------------------------------------------------------------------------


def _bare_combatant(participant_id: str, health: float) -> Combatant:
    """One participant with health, no resistance, and no defenses."""
    return Combatant(
        participant_id=participant_id,
        team="blue",
        champion_data={"name": participant_id},
        level=1,
        items=(),
        stats={"health": health, "magic_resistance": 0.0},
        defenses=StartingDefenses(
            magic_shield=0.0,
            physical_shield=0.0,
            general_shield=0.0,
            healing_received_multiplier=1.0,
        ),
    )


class TestARouteInvertsExactly:
    """``unroute_declared_packet`` is the inverse of the route, for the gate
    that has to hand a whole packet back after staging a share of it."""

    def test_the_share_divides_back_out(self):
        packet = DeclaredPacket(
            raw_amount=250.0, damage_type="magic", rule_id="aura", holder_amp=1.0
        )
        routed = route_declared_packet(
            packet, RoutingProvenance("knights_vow.sacrifice", 0.14)
        )
        assert routed.raw_amount == pytest.approx(35.0)
        recovered = unroute_declared_packet(routed)
        assert recovered.raw_amount == pytest.approx(packet.raw_amount)
        assert recovered._replace(raw_amount=packet.raw_amount) == packet

    def test_an_unrouted_packet_is_returned_untouched(self):
        packet = DeclaredPacket(
            raw_amount=250.0, damage_type="magic", rule_id="aura", holder_amp=1.0
        )
        assert unroute_declared_packet(packet) is packet
        assert unroute_declared_packet(None) is None

    def test_a_zero_share_is_refused_rather_than_inverted(self):
        packet = DeclaredPacket(
            raw_amount=0.0,
            damage_type="magic",
            rule_id="aura",
            holder_amp=1.0,
            routing=RoutingProvenance("knights_vow.sacrifice", 0.0),
        )
        with pytest.raises(ValueError, match="zero share"):
            unroute_declared_packet(packet)


def test_a_cancelled_redirect_restores_the_whole_packet_in_both_lanes():
    """The holder-health gate cancels the redirected child, and the Worthy
    then meets the WHOLE packet — its restored amount and, when its family
    declared its own magnitude, the un-routed declaration.

    Driven with ``event=None`` as well as with an event dict: the receipt
    adapter's restore is written onto the event it holds, and a compiled
    action has none, so a restore only one adapter can read is how the same
    cancelled redirect came to charge the Worthy two different numbers."""
    from src.calculator.program.build import roster_program
    from src.calculator.program.views.survival import survival
    from src.calculator.program.walk import walk as run_one_walk
    from src.calculator.survival.score_state import ScoreLedger

    worthy = _bare_combatant("worthy", 4000.0)
    holder = _bare_combatant("holder", 100.0)
    parent_slot = EVENT_SLOTS.slot("parent")
    declared_slot = EVENT_SLOTS.slot("declared-parent")
    aura = DeclaredPacket(
        raw_amount=100.0, damage_type="magic", rule_id="aura", holder_amp=1.0
    )
    children = {}

    def _parent(aidx, slot, name, amount, original, declaration):
        return SurvivalAction(
            sort_key=(1.0, TransitionRank.DAMAGE, 0, 0, 0, "worthy", name, "src"),
            time=1.0,
            phase=TransitionRank.DAMAGE,
            kind=ActionKind.DAMAGE,
            subject=0,
            attacker=0,
            aidx=aidx,
            amount=amount,
            damage_type="magic",
            declared=declaration,
            baseline_effective_mr=0.0,
            redirect_original_damage=original,
            redirect_holder_health_ratio=0.3,
            source_key="src",
            source="src",
            event_slot=slot,
            sequence=0,
        )

    def _child(aidx, parent_aidx, slot, name, amount, declaration):
        return SurvivalAction(
            sort_key=(1.0, TransitionRank.REACTIVE, 0, 1, 0, "holder", name, "src"),
            time=1.0,
            phase=TransitionRank.DAMAGE,
            kind=ActionKind.REDIRECT,
            subject=1,
            attacker=0,
            aidx=aidx,
            amount=amount,
            damage_type="magic",
            declared=declaration,
            baseline_effective_mr=0.0,
            redirected=True,
            trigger=parent_aidx,
            trigger_slot=slot,
            source_key="src",
            source="src",
            event_slot=EVENT_SLOTS.slot(name),
            sequence=0,
        )

    opening = SurvivalAction(
        sort_key=(0.0, TransitionRank.DAMAGE, 0, 1, 0, "holder", "open", "src"),
        time=0.0,
        phase=TransitionRank.DAMAGE,
        kind=ActionKind.DAMAGE,
        subject=1,
        attacker=0,
        aidx=0,
        amount=80.0,
        damage_type="magic",
        baseline_effective_mr=0.0,
        source_key="src",
        source="src",
        event_slot=EVENT_SLOTS.slot("open"),
        sequence=0,
    )
    plain_parent = _parent(1, parent_slot, "parent", 43.0, 50.0, None)
    plain_child = _child(2, 1, parent_slot, "parent:redirect", 7.0, None)
    declared_parent = _parent(
        3,
        declared_slot,
        "declared-parent",
        86.0,
        100.0,
        route_declared_packet(aura, RoutingProvenance("knights_vow.sacrifice", 0.86)),
    )
    declared_child = _child(
        4,
        3,
        declared_slot,
        "declared-parent:redirect",
        14.0,
        route_declared_packet(aura, RoutingProvenance("knights_vow.sacrifice", 0.14)),
    )
    children = {parent_slot: plain_child, declared_slot: declared_child}
    actions = [opening, plain_parent, plain_child, declared_parent, declared_child]

    def _walk(ledger_cls):
        states = build_states([worthy, holder], (0.0, 0.0))
        index_of = {"worthy": 0, "holder": 1}
        if ledger_cls is ReceiptLedger:
            walk_actions = [
                action._replace(
                    event={"_event_id": str(action.aidx), "damage": action.amount}
                )
                for action in actions
            ]
            ledger = ledger_cls(
                actions=list(walk_actions),
                index_of=index_of,
                compile_event=action_from_event,
                annotating=False,
            )
            live = {slot: walk_actions[child.aidx] for slot, child in children.items()}
        else:
            walk_actions = actions
            ledger = ledger_cls(len(actions))
            live = children
        ctx = TransitionContext(
            duration=5.0,
            states=states,
            combatants=[worthy, holder],
            index_of=index_of,
            ledger=ledger,
            regeneration_windows=(None, None),
            redirect_children=live,
        )
        result = run_one_walk(walk_actions, ctx)
        return survival(roster_program([worthy, holder]), result)

    receipt_rows = _walk(ReceiptLedger)
    score_rows = _walk(ScoreLedger)
    assert receipt_rows == score_rows
    # 50 restored from the pair-engine-priced packet, 100 from the declared
    # one whose route the gate handed back: never 43 + 86.
    assert score_rows["worthy"]["damage_taken"] == pytest.approx(150.0)
    # The holder paid the opening packet and neither cancelled share.
    assert score_rows["holder"]["damage_taken"] == pytest.approx(80.0)
