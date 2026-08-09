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

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Mapping

import pytest

from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.defensive_effects import resolve_starting_defenses
from src.calculator.item_support_effects import (
    EVENT_VIEW_SUPPORT_ITEMS,
    cross_participant_authorities,
    producer_item,
)
from src.calculator.participant_timeline import (
    CoupledSearchContext,
    build_participant_timeline,
)
from src.calculator.pipeline import FightParams
from src.calculator.scenario import ChampionLoadout
from src.calculator.stats import calculate_total_stats


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
    defenses = resolve_starting_defenses(champion_name, level, stats, items)
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
):
    """The score path must deep-equal the receipt path on the whole scoring
    receipt, and must have taken the documented path."""
    legacy, fast, context = _walk_both(
        champion_name, items, params, enemies, allies, level=level, role=role
    )
    assert fast == legacy, f"{name}: score path diverged from the receipt walk"
    _assert_rung(name, context, compiled=compiled, invariant=invariant)


@lru_cache(maxsize=None)
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


def test_knights_vow_redirect_poisons_context_and_falls_back():
    """Knight's Vow's Worthy redirect is authored by the receipt scheduler;
    the roster capability report poisons the context and the score receipt
    deep-equals the receipt."""
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
        compiled=False,
        invariant=True,
    )


def test_receipt_and_score_adapters_share_one_kernel():
    """Unit-level pin: the same typed action applied through the receipt
    ledger and the score ledger produces identical survival rows."""
    from types import SimpleNamespace

    from src.calculator.participant_timeline import Combatant
    from src.calculator.survival import (
        ActionKind,
        ReceiptLedger,
        ScoreLedger,
        SurvivalAction,
        TransitionContext,
        assemble_survival_rows,
        build_states,
        finalize_states,
        run_survival_walk,
    )

    combatant = Combatant(
        participant_id="target",
        team="enemy",
        champion_data={"name": "target"},
        level=1,
        items=(),
        stats={"health": 100.0, "is_melee": True},
        defenses=SimpleNamespace(
            magic_shield=0.0,
            physical_shield=0.0,
            general_shield=0.0,
            healing_received_multiplier=1.0,
        ),
    )
    actions = [
        SurvivalAction(
            sort_key=(0.0, 0.0, 0, 0, 0, "target", "hit", "auto"),
            time=0.0,
            phase=0.0,
            kind=ActionKind.PLAIN_DAMAGE,
            subject=0,
            attacker=0,
            aidx=0,
            amount=60.0,
            damage_type="physical",
            source_key="auto_attacks",
            source="auto_attacks",
            event_id="hit",
            sequence=0,
        ),
        SurvivalAction(
            sort_key=(1.0, 1.0, 0, 0, 0, "target", "heal", "heal"),
            time=1.0,
            phase=1.0,
            kind=ActionKind.HEAL,
            subject=0,
            attacker=0,
            aidx=1,
            amount=50.0,
            source_key="heal",
            source="heal",
            event_id="heal",
            sequence=0,
        ),
    ]

    def _walk(ledger_cls, annotate):
        states = build_states([combatant])
        if ledger_cls is ReceiptLedger:
            ledger = ledger_cls(
                actions=[a._replace(event={}) for a in actions],
                index_of={"target": 0},
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
        )
        run_survival_walk(
            (
                actions
                if ledger_cls is ScoreLedger
                else [a._replace(event={}) for a in actions]
            ),
            ctx,
        )
        finalize_states(states, 5.0)
        return assemble_survival_rows(states, [combatant])["target"]

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
    from src.calculator.survival import (
        SUPPORT_RANK_KEY,
        TransitionRank,
        WalkCompiler,
        legacy_phase,
        support_transition_rank,
    )
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
    by_event = {action.event_id: action for action in compiler.actions}

    for template in (declared, plain):
        expected = legacy_phase(support_transition_rank(template))
        action = by_event[template["_event_id"]]
        assert action.phase == expected
        assert action.sort_key[1] == expected

    # The declaration is what separates them: same kind, different arming.
    assert by_event["declared:late"].phase == legacy_phase(TransitionRank.LATE_BARRIER)
    assert by_event["plain:barrier"].phase == legacy_phase(TransitionRank.BARRIER_GRANT)


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

    ``EVENT_VIEW_SUPPORT_ITEMS`` is the tuple-incapable set the pipeline's
    tuple gate consults, and contributes item names;
    ``cross_participant_authorities()`` is the derived ``damage_modifier``
    producer set, and contributes ``source`` literals — one key per packet,
    not per item, so a second packet on an already-equipped item is its own
    requirement.  Neither registry is restated here, so a new event-view
    holder or a seventh producer becomes a required key on the commit that
    adds it — and fails this suite until it has a fixture.
    """
    return EVENT_VIEW_SUPPORT_ITEMS | frozenset(cross_participant_authorities())


@lru_cache(maxsize=None)
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


@lru_cache(maxsize=None)
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
            for index, (one, other) in enumerate(zip(left, right))
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

    assert _ally_survival(legacy)["healing_received"] > 0.0
    assert _ally_survival(fast)["healing_received"] == 0.0

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
    assert EVENT_VIEW_SUPPORT_ITEMS and cross_participant_authorities()
    assert required >= EVENT_VIEW_SUPPORT_ITEMS
    assert required >= frozenset(cross_participant_authorities())

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
    declared = dict(cross_participant_authorities())
    monkeypatch.setattr(
        "tests.test_survival_kernel.cross_participant_authorities",
        lambda: {**declared, extra: None},
    )
    candidate_reached, ally_reached = _fixture_coverage()
    assert missing_fixtures(
        required_coverage_keys(), candidate_reached, ally_reached
    ) == ((extra, "ally"), (extra, "candidate"))
