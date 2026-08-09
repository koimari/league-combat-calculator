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
"""

from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.defensive_effects import resolve_starting_defenses
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
    assert fast == legacy, f"{name}: score path diverged from the receipt walk"
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


_ITEMS = {
    name: get_item_by_name(name)
    for name in (
        "Infinity Edge",
        "Rapid Firecannon",
        "Phantom Dancer",
        "Essence Reaver",
        "Lord Dominik's Regards",
        "Berserker's Greaves",
        "Rabadon's Deathcap",
        "The Collector",
        "Death's Dance",
        "Bloodthirster",
        "Hextech Gunblade",
        "Spirit Visage",
        "Morellonomicon",
    )
}


def _roster(champion, level=18, items=(), role="mid", quest=False):
    return ChampionLoadout(
        champion=champion,
        level=level,
        role=role,
        items=items,
        role_quest_complete=quest,
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
            _ITEMS[n]
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
        [_ITEMS["Infinity Edge"]],
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
        [_ITEMS["Infinity Edge"]],
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
            _ITEMS[n]
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
        [_ITEMS["Rabadon's Deathcap"]],
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
        [_ITEMS["Rabadon's Deathcap"]],
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
        [_ITEMS["Bloodthirster"], _ITEMS["Infinity Edge"]],
        params,
        [_roster("Cassiopeia")],
    )
    # Omnivamp beside Spirit Visage: the received-healing multiplier must
    # keep exempting vamp heals on the compiled path.
    _assert_contract(
        "omnivamp-spirit-visage",
        "Ahri",
        [_ITEMS["Hextech Gunblade"], _ITEMS["Spirit Visage"]],
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
        [_ITEMS["Morellonomicon"], _ITEMS["Rabadon's Deathcap"]],
        params,
        [_roster("Dr. Mundo", items=("Spirit Visage", "Kaenic Rookern"), role="top")],
    )
    # Roster Morellonomicon + Vampiric Scepter: the enemy's wound reduces the
    # vamp candidate's healing, and the enemy's own vamp heals compile too.
    _assert_contract(
        "morello-roster",
        "Ahri",
        [_ITEMS["Bloodthirster"], _ITEMS["Infinity Edge"]],
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
        [_ITEMS["The Collector"], _ITEMS["Infinity Edge"], _ITEMS["Rapid Firecannon"]],
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
        [_ITEMS["Death's Dance"], _ITEMS["Infinity Edge"]],
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
        [_ITEMS["Infinity Edge"]],
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
