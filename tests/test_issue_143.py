"""Issue #143 — one authoritative ledger owner per champion heal.

Taric Q was double-granted: the E1 self-heal rule priced the sourced
5-charge stock into ``healing[attacker]`` while the generic support
scanner re-derived the same cast at a hardcoded 1-charge amount into the
support ledger (self 241.4 + 48.28 from one Q).  The ownership registry
was also defined twice — the second definition shadowed the first at
import time and silently killed Shyvana W's exclusion.  These tests lock
the single registry, the single formula source, the one-event fan-out
with provable id linkage, and the applied totals.
"""

import inspect
from functools import partial

import pytest

from src.calculator import support_effects
from src.calculator.champions.taric import _starlights_touch
from src.calculator.data_fetcher import get_champion
from src.calculator.defensive_effects import resolve_starting_defenses
from src.calculator.healing import derive_self_healing
from src.calculator.participant_timeline import (
    CoupledSearchContext,
    build_participant_timeline,
)
from src.calculator.pipeline import FightParams
from src.calculator.scenario import ChampionLoadout
from src.calculator.stats import calculate_total_stats
from src.calculator.support_effects import (
    _MODULE_AUTHORED_HEAL_SLOTS,
    _MODULE_AUTHORED_SHIELD_SLOTS,
    derive_ally_effects,
)


def test_registry_membership_and_single_definition():
    """One registry of the module-owned heal slots — the phase 1 trio, the
    phase 2 audit (11 self double-grants + 5 fabricated ally heals), Soraka
    Q, and the W3 scan's three — defined exactly once (a second assignment
    shadows the first at import time — the E9-3/E9-2 history).  Rakan Q is
    deliberately absent: its scanner ally branch stays at its own amount
    (see ``_SCOPE_OVERRIDES``)."""
    assert (
        frozenset(
            {
                ("Shyvana", "W"),
                ("Naafiri", "Q"),
                ("Taric", "Q"),
                ("Sona", "W"),
                ("Janna", "R"),
                ("Milio", "R"),
                ("Irelia", "Q"),
                ("Vladimir", "Q"),
                ("Volibear", "W"),
                ("Ekko", "R"),
                ("Gangplank", "W"),
                ("Kha'Zix", "W"),
                ("Tahm Kench", "Q"),
                ("Sylas", "W"),
                ("Tryndamere", "Q"),
                ("Talon", "Q"),
                ("Yorick", "Q"),
                ("Kindred", "W"),
                ("Soraka", "Q"),
                ("Vladimir", "R"),
                ("Locke", "W"),
                ("Zilean", "R"),
            }
        )
        == _MODULE_AUTHORED_HEAL_SLOTS
    )
    source = inspect.getsource(support_effects)
    assert source.count("_MODULE_AUTHORED_HEAL_SLOTS = frozenset(") == 1
    assert source.count("_MODULE_AUTHORED_HEAL_SLOTS = ") == 1


def test_taric_q_single_ownership_rule_prices_the_stock():
    """One Q cast yields exactly one self-heal event at the sourced
    5-charge price (2000 HP, 0 AP, rank 5) with the fan-out scope, the
    charge count, and a stable raw event id."""
    taric = get_champion("Taric")
    heals = derive_self_healing(
        taric,
        {"level": 18, "health": 2000.0, "ability_power": 0.0},
        {"Q": {"rank": 5}},
        [],
        [{"slot": "Q", "time": 1.0}],
        5.0,
    )
    assert len(heals) == 1
    heal = heals[0]
    assert heal["amount"] == pytest.approx(225.0)  # 5 × (25 + 1% max HP)
    assert heal["source"] == "Starlight's Touch"
    assert heal["target_scope"] == "self_and_all_teammates"
    assert heal["charges"] == 5
    assert heal["_event_id"] == "taric:q:0"
    assert heal["actor_wide"] is True


def test_taric_starlights_touch_formula_matches_pinned_amount():
    """The extracted formula agrees with the pinned E1 test semantics:
    amount = min(stock × per-charge, the maximum row)."""
    taric = get_champion("Taric")
    q = taric["abilities"]["Q"][0]
    amount, charges = _starlights_touch(q, 5, {"health": 2000.0, "ability_power": 0.0})
    assert charges == 5
    assert amount == pytest.approx(225.0)
    amount_ap, _ = _starlights_touch(q, 5, {"health": 2000.0, "ability_power": 100.0})
    assert amount_ap == pytest.approx(225.0 + 5 * 15.0)


def test_taric_q_scanner_emits_nothing():
    """The support scanner defers Taric Q entirely (no heal, no shield)."""
    taric = get_champion("Taric")
    eff = derive_ally_effects(
        taric,
        18,
        {"ability_power": 0.0, "health": 2000.0},
        [{"slot": "Q", "time": 1.0}],
    )
    assert [e for e in eff if e["slot"] == "Q"] == []


def test_shyvana_w_heal_set_alone_excludes_the_scanner(monkeypatch):
    """Shyvana W's scanner exclusion must come from the HEAL registry: even
    when the shield registry does not mention the slot, no scanner-derived
    heal packet appears (the duplicate-constant history made this depend on
    the shield set by accident)."""
    original = _MODULE_AUTHORED_SHIELD_SLOTS
    monkeypatch.setattr(
        support_effects,
        "_MODULE_AUTHORED_SHIELD_SLOTS",
        original - {("Shyvana", "W")},
    )
    shyvana = get_champion("Shyvana")
    eff = derive_ally_effects(
        shyvana,
        18,
        {"ability_power": 0.0, "health": 2000.0},
        [{"slot": "W", "time": 1.0}],
    )
    assert [e for e in eff if e["kind"] == "heal" and e["slot"] == "W"] == []


def test_naafiri_q_scanner_emits_nothing():
    naafiri = get_champion("Naafiri")
    eff = derive_ally_effects(
        naafiri,
        18,
        {"ability_power": 0.0, "health": 2000.0},
        [{"slot": "Q", "time": 1.0}],
    )
    assert [e for e in eff if e["kind"] == "heal" and e["slot"] == "Q"] == []


def _taric_timeline(*, with_ally: bool):
    taric = get_champion("Taric")
    params = FightParams.from_request(
        {
            "fight_mode": "one_rotation",
            "role": "support",
            "cast_order": ["Q", "W", "E", "R"],
            # Keep the heal ownership test focused on Q. Taric E's sourced
            # stun correctly prevents Ahri from acting at the opening cast.
            "ability_ranks": {"Q": 5, "W": 0, "E": 0, "R": 0},
        },
        deterministic=True,
    )
    enemies = [
        ChampionLoadout(
            champion="Ahri",
            level=18,
            role="mid",
            ability_ranks={"E": 0},
        ).resolve()
    ]
    allies = (
        [ChampionLoadout(champion="Ashe", level=18, role="bottom").resolve()]
        if with_ally
        else []
    )
    stats = calculate_total_stats(taric, 18, [], role="support")
    defenses = resolve_starting_defenses("Taric", 18, stats, [])
    return build_participant_timeline(
        taric,
        18,
        [],
        params,
        main_stats=stats,
        main_defenses=defenses,
        enemies=enemies,
        allies=allies,
    )


def test_taric_1v1_applies_the_self_heal_once():
    """One Q cast in a 1v1: healing_received is 241.4 (the 5-charge rule),
    never 289.7 (rule + scanner 1-charge packet)."""
    res = _taric_timeline(with_ally=False)
    main = next(p for p in res["participants"] if p["participant_id"] == "main")
    assert main["survival"]["healing_received"] == pytest.approx(241.4)
    starlight = [
        e for e in res["healing_events"] if "Starlight" in str(e.get("source", ""))
    ]
    assert len(starlight) == 1
    assert starlight[0]["applied_amount"] == pytest.approx(241.4)
    assert starlight[0]["charges"] == 5
    assert not any(
        "prose heal" in str(e.get("source", "")) for e in res["support_events"]
    )


def test_taric_roster_fans_out_one_event_per_recipient():
    """With one ally, the Q heal pays 241.4 to self AND one 241.4 clone to
    the ally — same time/amount/source, distinct ids, and the clone links
    back to the applied self copy via ``source_event_id``."""
    res = _taric_timeline(with_ally=True)
    self_events = [
        e for e in res["healing_events"] if "Starlight" in str(e.get("source", ""))
    ]
    assert len(self_events) == 1
    self_event = self_events[0]
    assert self_event["applied_amount"] == pytest.approx(241.4)
    ally_events = [
        e for e in res["support_events"] if "Starlight" in str(e.get("source", ""))
    ]
    assert len(ally_events) == 1
    clone = ally_events[0]
    assert clone["target"] == "ally:Ashe"
    assert clone["amount"] == self_event["amount"]
    assert clone["time"] == self_event["time"]
    assert clone["source"] == self_event["source"]
    assert clone["event_id"] == f'{self_event["event_id"]}:ally:1'
    assert clone["source_event_id"] == self_event["event_id"]
    assert clone["target_policy"] == "self_and_all_selected_teammates"
    main = next(p for p in res["participants"] if p["participant_id"] == "main")
    ashe = next(p for p in res["participants"] if p["participant_id"] == "ally:Ashe")
    assert main["survival"]["healing_received"] == pytest.approx(241.4)
    assert ashe["survival"]["healing_received"] == pytest.approx(241.4)


def test_taric_compiled_score_path_matches_receipt():
    """The fan-out rides both walks: the compiled optimizer path must
    deep-equal the legacy score receipt for the 1v1 and the roster."""
    for with_ally in (False, True):
        taric = get_champion("Taric")
        params = FightParams.from_request(
            {
                "fight_mode": "one_rotation",
                "role": "support",
                "cast_order": ["Q", "W", "E", "R"],
            },
            deterministic=True,
        )
        enemies = [
            ChampionLoadout(
                champion="Ahri",
                level=18,
                role="mid",
                ability_ranks={"E": 0},
            ).resolve()
        ]
        allies = (
            [ChampionLoadout(champion="Ashe", level=18, role="bottom").resolve()]
            if with_ally
            else []
        )
        stats = calculate_total_stats(taric, 18, [], role="support")
        defenses = resolve_starting_defenses("Taric", 18, stats, [])

        timeline = partial(
            build_participant_timeline,
            taric,
            18,
            [],
            params,
            main_stats=stats,
            main_defenses=defenses,
            enemies=enemies,
            allies=allies,
        )

        legacy_score = timeline(include_receipt=False)
        fast = timeline(
            pair_result_cache={},
            include_receipt=False,
            search_context=CoupledSearchContext(),
        )
        assert fast == legacy_score
