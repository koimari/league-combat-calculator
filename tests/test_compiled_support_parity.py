"""Compiled-panel vs receipt-walk parity for roster support, issue #226.

The compiled score path stages ally support once per attacker against that
attacker's first defender, and until this suite existed nothing pinned that a
recipient other than the first ally got the same number out of it.  Two
things were wrong underneath: a resolved cleanse packet was refused outright
(``support_cleanse`` / ``support_kind=cleanse``), so every roster holding one
of the three cleanse items — or a cleanse-casting champion — priced its whole
search on the receipt walk; and the compiled heal builder stamped no
``cast_while_disabled``, so Gangplank's Remove Scurvy heal was applied by one
walk and blocked by the other the moment the cleanse stopped hiding it.

Every case here asserts the same two things: the compiled surface deep-equals
the receipt surface, and the compiled rung was actually taken — a fallback
makes the two equal by construction and proves nothing.
"""

from collections import Counter
from dataclasses import dataclass, field

import pytest

from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.defensive_effects import resolve_starting_defenses
from src.calculator.participant_timeline import (
    CoupledSearchContext,
    build_participant_timeline,
)
from src.calculator.pipeline import FightParams
from src.calculator.scenario import ChampionLoadout
from src.calculator.stats import calculate_total_stats

MIKAELS = "Mikael's Blessing"
QUICKSILVER = "Quicksilver Sash"
PURIFY_SELECTION = "heal:Mikael's Blessing — Purify"
# Amumu's ultimate is the roster-wide control this suite needs: a targeted
# control lands on the roster's first defender only, so an ally at
# participant[2] would never be crowd-controlled and no cleanse there could
# truncate anything.
STUNNER = ("Amumu", {"Q": 5, "W": 5, "E": 5, "R": 3})
# Corki declares "none" on every slot, which is what a cast the caster's own
# control would gate (Milio's R) needs to reach the walk at all.
NO_CONTROL = ("Corki", {"Q": 5, "W": 5, "E": 5, "R": 3})
TWO_ALLIES = (("Jinx", (), {}), ("Ashe", (), {}))


@dataclass(slots=True)
class _Sink:
    """The six mutable fields ``WorkCounterSink`` asks for."""

    measured_proposals: int = 0
    score_memo_misses: int = 0
    pair_run_fight_calls: int = 0
    walk_invocations: int = 0
    rungs: Counter = field(default_factory=Counter)
    rung_receipts: Counter = field(default_factory=Counter)


def _fight(
    *,
    compiled: bool,
    champion: str = "Lux",
    items: tuple[str, ...] = (),
    item_options: dict | None = None,
    selections: dict | None = None,
    allies: tuple[tuple[str, tuple[str, ...], dict], ...] = TWO_ALLIES,
    enemies: tuple[tuple[str, dict], ...] = (STUNNER,),
    context: CoupledSearchContext | None = None,
):
    """One coupled fight, through the compiled panel path or the receipt walk.

    ``context`` carries a search's compiled panels from one evaluation to the
    next; omitted, a compiled fight gets a fresh one of its own.
    """
    champion_data = get_champion(champion)
    item_data = [get_item_by_name(name) for name in items]
    main_stats = calculate_total_stats(champion_data, 18, item_data)
    params = FightParams.from_request(
        {
            "fight_mode": "time_based",
            "fight_duration": 8.0,
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
            "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
            "item_options": item_options or {},
            "support_target_selections": selections or {},
        },
        deterministic=True,
    )
    if compiled and context is None:
        context = CoupledSearchContext(work_counters=_Sink())
    result = build_participant_timeline(
        champion_data,
        18,
        item_data,
        params,
        main_stats=main_stats,
        main_defenses=resolve_starting_defenses(champion, 18, main_stats, item_data),
        enemies=[
            ChampionLoadout(
                champion=name, level=18, items=(), ability_ranks=ranks
            ).resolve()
            for name, ranks in enemies
        ],
        allies=[
            ChampionLoadout(
                champion=name,
                level=18,
                items=ally_items,
                item_options=ally_options,
                ally_effects_enabled=True,
                ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
            ).resolve()
            for name, ally_items, ally_options in allies
        ],
        include_receipt=False,
        pair_result_cache={} if compiled else None,
        search_context=context,
    )
    return result, context


def _assert_compiled_parity(**case):
    """Both surfaces agree, and the compiled one really was compiled."""
    receipt, _ = _fight(compiled=False, **case)
    compiled, context = _fight(compiled=True, **case)
    assert dict(context.work_counters.rung_receipts) == {}
    assert dict(context.work_counters.rungs) == {"compiled": 1}
    assert compiled == receipt
    return compiled


def _survival(result, participant_id: str) -> dict:
    (row,) = [
        participant
        for participant in result["participants"]
        if participant["participant_id"] == participant_id
    ]
    return row["survival"]


#: Mikael's fires only while its caster is free, so the caster frees itself
#: with Quicksilver at 0.5s and Purifies the second ally at 1.0s, mid-stun.
PURIFY_ON_PARTICIPANT_TWO = {
    "items": (MIKAELS, QUICKSILVER),
    "item_options": {
        MIKAELS: {"active_seconds": 1.0},
        QUICKSILVER: {"active_seconds": 0.5},
    },
    "selections": {PURIFY_SELECTION: 1},
}


def test_mikaels_purify_on_participant_two_compiles_and_matches_the_walk():
    """The recipient the request selected is participant[2] — the SECOND
    ally, not the first — so this is the row the compiled path had no
    coverage for.  It carries the sourced heal, its cleanse receipt and the
    truncated downtime; the first ally carries none of the three."""
    compiled = _assert_compiled_parity(**PURIFY_ON_PARTICIPANT_TWO)
    recipient = _survival(compiled, "ally:Ashe")
    assert recipient["healing_received"] == pytest.approx(280.0, abs=0.05)
    assert recipient["cleanse"]["item"] == MIKAELS
    assert recipient["cleanse"]["target"] == "ally:Ashe"
    # Amumu's ultimate stuns until 2.0s; Purify at 1.0 ends that interval.
    assert recipient["action_downtime"] == pytest.approx(1.0)
    assert [
        row["control_kind"] for row in recipient["cleanse"]["removed_controls"]
    ] == ["stun"]
    unselected = _survival(compiled, "ally:Jinx")
    assert unselected["healing_received"] == pytest.approx(0.0)
    assert "cleanse" not in unselected
    assert unselected["action_downtime"] == pytest.approx(2.0)
    # The caster's own use receipts are on the holder's row, one per item.
    caster = _survival(compiled, "main")
    assert caster["cleanse"]["item"] == QUICKSILVER
    assert caster["cleanse_use"]["uses_after"] == 0


def test_a_self_cast_cleanse_held_by_participant_two_compiles():
    """Quicksilver Sash on the second ally: the holder IS participant[2], so
    the packet is staged by the base panel's ally pass rather than by the
    candidate's own fresh compile."""
    compiled = _assert_compiled_parity(
        allies=(
            ("Jinx", (), {}),
            ("Ashe", (QUICKSILVER,), {QUICKSILVER: {"active_seconds": 1.0}}),
        ),
    )
    holder = _survival(compiled, "ally:Ashe")
    assert holder["cleanse"]["item"] == QUICKSILVER
    assert holder["action_downtime"] == pytest.approx(1.0)
    assert _survival(compiled, "ally:Jinx")["action_downtime"] == pytest.approx(2.0)


def test_a_fan_out_cleanse_reaches_every_participant_on_the_compiled_path():
    """Milio's Breath of Life is one cast with one cleanse group and a
    recipient per teammate, so it is the case where a compiled packet that
    lost its ``cleanse_group`` would spend a use per recipient instead of
    one for the cast.  The cast is blocked while its own caster is held, so
    the enemy here is the one that authors no control."""
    compiled = _assert_compiled_parity(champion="Milio", enemies=(NO_CONTROL,))
    for participant_id in ("main", "ally:Jinx", "ally:Ashe"):
        assert _survival(compiled, participant_id)["cleanse"]["item"] == "Milio R"
    assert _survival(compiled, "main")["cleanse_use"]["activations"] == 1


def test_remove_scurvy_heals_on_the_compiled_path_while_its_caster_is_stunned():
    """Gangplank W is the game's canCastWhileDisabled: being held is the
    reason to cast it.  The compiled heal builder has to stamp that
    exemption, or the compiled walk blocks the heal the receipt walk
    applies — a divergence the cleanse refusal used to hide."""
    compiled = _assert_compiled_parity(champion="Gangplank")
    caster = _survival(compiled, "main")
    assert caster["healing_received"] > 0.0
    assert caster["cleanse"]["item"] == "Gangplank W"
    assert [row["control_kind"] for row in caster["cleanse"]["removed_controls"]] == [
        "stun"
    ]


def test_one_search_context_replays_a_staged_cleanse_across_candidates():
    """A roster cleanse is compiled once into the base panel and replayed by
    every later evaluation, so the case a single-evaluation test cannot see
    is the second candidate reading the first one's actions."""
    context = CoupledSearchContext(work_counters=_Sink())
    allies = (
        ("Jinx", (), {}),
        ("Ashe", (QUICKSILVER,), {QUICKSILVER: {"active_seconds": 1.0}}),
    )
    for items in ((), ("Infinity Edge",), ("Rabadon's Deathcap", "Sorcerer's Shoes")):
        receipt, _ = _fight(compiled=False, items=items, allies=allies)
        compiled, _ = _fight(compiled=True, items=items, allies=allies, context=context)
        assert compiled == receipt
        assert _survival(compiled, "ally:Ashe")["cleanse"]["item"] == QUICKSILVER
    # One base panel, three evaluations, no fallback on any of them.
    assert dict(context.work_counters.rungs) == {"compiled": 3}
    assert len(context.panels) == 1
    assert context.uncompilable is False


@pytest.mark.parametrize(
    "case",
    [
        pytest.param({}, id="no_support"),
        pytest.param(
            {
                "items": (MIKAELS, QUICKSILVER),
                "item_options": PURIFY_ON_PARTICIPANT_TWO["item_options"],
                "selections": {PURIFY_SELECTION: 0},
            },
            id="purify_first_ally",
        ),
        pytest.param(PURIFY_ON_PARTICIPANT_TWO, id="purify_second_ally"),
        pytest.param({"items": ("Redemption",)}, id="redemption_fanout"),
        pytest.param(
            {
                "items": ("Locket of the Iron Solari",),
                "item_options": {"Locket of the Iron Solari": {"active_seconds": 1.0}},
            },
            id="locket_fanout",
        ),
        pytest.param({"champion": "Milio"}, id="milio_fanout_cleanse"),
        pytest.param({"champion": "Gangplank"}, id="gangplank_self_cleanse"),
    ],
)
def test_compiled_support_totals_equal_the_receipt_walks_for_every_participant(case):
    """The per-attacker support fold is two independent sums — the compiled
    path over ``support_entries`` slots, the receipt path over published
    ``applied_amount`` — so a packet staged by one and not the other shows up
    here even when no survival row moves."""
    receipt, _ = _fight(compiled=False, **case)
    compiled, context = _fight(compiled=True, **case)
    assert dict(context.work_counters.rungs) == {"compiled": 1}
    receipt_rows = {row["participant_id"]: row for row in receipt["breakdown"]}
    for row in compiled["breakdown"]:
        expected = receipt_rows[row["participant_id"]]
        assert row["support_value"] == expected["support_value"]
        assert row["healing_output"] == expected["healing_output"]
        assert row["support_shield_received"] == expected["support_shield_received"]
        assert row["healing_received"] == expected["healing_received"]
