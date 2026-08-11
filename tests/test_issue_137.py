"""Issue #137 — one state transition engine for receipts and optimizer walks.

Phase 1: the compiled optimizer walk fails closed.  ``_WalkCompiler`` (and
the compile-stage capability checks) raise a named
``UncompilableActionError`` for any packet/loadout transition the score
kernel cannot represent — overheal-to-shield (Aphelios Severum), vamp
source categories, timed shields, live gates, execute thresholds, stat
buffs — and ``build_participant_timeline`` falls back to the
authoritative event walk.  Before this fix the Aphelios Severum score
path silently erased the overheal shield (fast != legacy); now the two
paths agree by construction.
"""

import pytest

from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.pipeline import FightParams
from src.calculator.scenario import ChampionLoadout
from src.calculator.stats import calculate_total_stats
from src.calculator.defensive_effects import resolve_starting_defenses
from src.calculator.participant_timeline import (
    CoupledSearchContext,
    UncompilableActionError,
    _WalkCompiler,
    build_participant_timeline,
)

_APHELIOS_ITEMS = [
    get_item_by_name(name)
    for name in (
        "Infinity Edge",
        "Rapid Firecannon",
        "Phantom Dancer",
        "Essence Reaver",
        "Lord Dominik's Regards",
        "Berserker's Greaves",
    )
]


def _aphelios_timeline(items, **kwargs):
    champion = get_champion("Aphelios")
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
    enemies = [ChampionLoadout(champion="Janna", level=1, role="support").resolve()]
    stats = calculate_total_stats(champion, 18, items, role="bottom")
    defenses = resolve_starting_defenses("Aphelios", 18, stats, items)
    return build_participant_timeline(
        champion,
        18,
        items,
        params,
        main_stats=stats,
        main_defenses=defenses,
        enemies=enemies,
        allies=[],
        **kwargs,
    )


def _assert_severum_conversion_present(survival):
    """The receipt walk converts sourced overheal into a timed shield: the
    conversion counter is positive and no excess leaked into overhealing.
    (The surviving shield amount depends on the enemy's follow-up damage —
    the no-item build converts 18.6 and consumes all of it.)"""
    assert survival["support_shield_received"] > 0.0
    assert survival["overhealing"] == 0.0


def test_aphelios_severum_score_path_matches_receipt():
    """The optimizer score path (compiled walk) must deep-equal the legacy
    score receipt when Severum's overheal-to-shield is active — previously
    the compiled walk silently erased the shield (11.2 EHP in this
    fixture)."""
    for items in ([], _APHELIOS_ITEMS):
        legacy_score = _aphelios_timeline(items, include_receipt=False)
        fast = _aphelios_timeline(
            items,
            pair_result_cache={},
            include_receipt=False,
            search_context=CoupledSearchContext(),
        )
        assert fast == legacy_score
        main = next(p for p in fast["participants"] if p["participant_id"] == "main")
        _assert_severum_conversion_present(main["survival"])


def test_compiler_fails_closed_on_overheal_to_shield():
    """A self-heal packet carrying the Severum transition raises the named
    error with a receipt naming the transition and source."""
    compiler = _WalkCompiler()
    result = {
        "damage_events": [],
        "self_healing_events": [
            {
                "time": 1.0,
                "amount": 100.0,
                "source": "Severum",
                "overheal_to_shield": True,
                "overheal_shield_cap": 300.0,
                "overheal_shield_duration": 30.0,
            }
        ],
    }
    with pytest.raises(UncompilableActionError) as exc:
        compiler.add_engine_result(
            result,
            "main",
            0,
            "enemy:X",
            1,
            {},
            10.0,
            {},
            [],
            0,
        )
    assert exc.value.receipt == "overheal_to_shield"
    assert exc.value.source == "Severum"
    assert exc.value.invariant is False


def test_compiler_carries_vamp_healing_category():
    """A vamp heal compiles with its category intact (issue #169), so the
    kernel's carve-outs — the received-healing multiplier exemption and the
    ichor conversion — read the same field either adapter supplies."""
    compiler = _WalkCompiler()
    result = {
        "damage_events": [],
        "self_healing_events": [
            {
                "time": 1.0,
                "amount": 50.0,
                "source": "Life steal",
                "healing_category": "vamp",
            }
        ],
    }
    compiler.add_engine_result(
        result,
        "main",
        0,
        "enemy:X",
        1,
        {},
        10.0,
        {},
        [],
        0,
    )
    heal = next(action for action in compiler.actions if action.kind.name == "HEAL")
    assert heal.healing_category == "vamp"


def test_compiler_carries_timed_support_shield():
    compiler = _WalkCompiler()
    compiler.add_support_templates(
        [
            {
                "time": 1.0,
                "kind": "shield",
                "amount": 100.0,
                "duration": 2.5,
                "source": "Locket of the Iron Solari",
                "target": "ally:X",
            }
        ],
        0,
        {"ally:X": 1},
    )
    shield = compiler.actions[0]
    assert shield.kind.name == "SHIELD"
    assert shield.duration == pytest.approx(2.5)


def test_compiler_fails_closed_on_stat_buff_template():
    compiler = _WalkCompiler()
    with pytest.raises(UncompilableActionError) as exc:
        compiler.add_support_templates(
            [
                {
                    "time": 1.0,
                    "kind": "stat_buff",
                    "amount": 25.0,
                    "source": "Ardent Censer",
                    "target": "ally:X",
                }
            ],
            0,
            {"ally:X": 1},
        )
    assert exc.value.receipt == "support_kind=stat_buff"


def test_compiler_fails_closed_on_execute_threshold_damage():
    compiler = _WalkCompiler()
    result = {
        "damage_events": [
            {
                "time": 1.0,
                "sequence": 0,
                "source_key": "Q",
                "source": "Q",
                "damage_type": "physical",
                "damage": 100.0,
                "execute_threshold_ratio": 0.05,
                "execute_source": "The Collector",
            }
        ],
        "self_healing_events": [],
    }
    with pytest.raises(UncompilableActionError) as exc:
        compiler.add_engine_result(
            result,
            "main",
            0,
            "enemy:X",
            1,
            {},
            10.0,
            {},
            [],
            0,
        )
    assert exc.value.receipt == "execute_threshold=The Collector"


def test_uncompilable_roster_poisons_context_and_falls_back():
    """A roster actor whose build the compiled kernel cannot represent
    (Death's Dance deferral, authored by the receipt walk) poisons the
    context: the first evaluation falls back to the receipt walk, later
    evaluations skip the compiled path entirely, and every score receipt
    deep-equals the legacy one."""
    champion = get_champion("Cassiopeia")
    params = FightParams.from_request(
        {"fight_mode": "one_rotation", "role": "mid"}, deterministic=True
    )
    enemies = [
        ChampionLoadout(
            champion="Dr. Mundo",
            level=18,
            role="top",
            boots="Plated Steelcaps",
            items=("Death's Dance", "Heartsteel", "Randuin's Omen"),
        ).resolve(),
    ]
    items = [get_item_by_name("Rabadon's Deathcap")]
    stats = calculate_total_stats(champion, 13, items, role="mid")
    defenses = resolve_starting_defenses("Cassiopeia", 13, stats, items)

    def timeline(**kwargs):
        return build_participant_timeline(
            champion,
            13,
            items,
            params,
            main_stats=stats,
            main_defenses=defenses,
            enemies=enemies,
            allies=[],
            **kwargs,
        )

    legacy_score = timeline(include_receipt=False)
    context = CoupledSearchContext()
    first = timeline(
        pair_result_cache={},
        include_receipt=False,
        search_context=context,
    )
    assert first == legacy_score
    assert context.uncompilable is True
    second = timeline(
        pair_result_cache={},
        include_receipt=False,
        search_context=context,
    )
    assert second == legacy_score
    assert context.panels == {}


def test_inactive_warmog_stays_compilable():
    """Warmog's Armor below the active threshold authors no ticks in either
    walk, so the compiled path remains usable (the legacy ``_has_active_warmog``
    precision)."""
    champion = get_champion("Cassiopeia")
    params = FightParams.from_request(
        {"fight_mode": "one_rotation", "role": "mid"}, deterministic=True
    )
    enemies = [
        ChampionLoadout(
            champion="Dr. Mundo",
            level=13,
            role="top",
            boots="Plated Steelcaps",
            items=("Warmog's Armor",),
        ).resolve(),
    ]
    items = [get_item_by_name("Rabadon's Deathcap")]
    stats = calculate_total_stats(champion, 13, items, role="mid")
    defenses = resolve_starting_defenses("Cassiopeia", 13, stats, items)

    def timeline(**kwargs):
        return build_participant_timeline(
            champion,
            13,
            items,
            params,
            main_stats=stats,
            main_defenses=defenses,
            enemies=enemies,
            allies=[],
            **kwargs,
        )

    legacy_score = timeline(include_receipt=False)
    context = CoupledSearchContext()
    fast = timeline(
        pair_result_cache={},
        include_receipt=False,
        search_context=context,
    )
    assert fast == legacy_score
    assert context.uncompilable is False
    assert context.panels, "the compiled path should have been used"
