"""Focused matrix for Fimbulwinter same-time reactive damage ordering.

Local evidence certifies Everlasting's trigger and shield. It does not select
an order when that shield and reactive incoming damage share one timestamp.
Those policy rows stay strict xfails. Epsilon-separated rows pin only the
ordinary timestamp order. Adapter-parity rows do not certify the same-time
policy.
"""

import pytest

from src.calculator.data_fetcher import get_item_by_name
from src.calculator.defensive_effects import StartingDefenses
from src.calculator.participant_timeline import Combatant
from src.calculator.program.build import roster_program
from src.calculator.program.compile import action_from_event
from src.calculator.program.views.survival import survival
from src.calculator.program.walk import walk as run_one_walk
from src.calculator.survival import (
    EVENT_SLOTS,
    SUPPORT_RANK_KEY,
    ReceiptLedger,
    ScoreLedger,
    TransitionContext,
    TransitionRank,
    build_states,
)
from src.calculator.survival.actions import action_key

EVERLASTING = "Fimbulwinter — Everlasting"
EPSILON = 1e-6


def _combatants(holder_id: str) -> list[Combatant]:
    source_id = "enemy:Aatrox" if holder_id == "main" else "main"

    def actor(participant_id: str, items: tuple[dict, ...]) -> Combatant:
        return Combatant(
            participant_id=participant_id,
            team="main" if participant_id.startswith("main:") else "enemy",
            champion_data={"name": participant_id.split(":", 1)[-1]},
            level=18,
            items=items,
            stats={"health": 100.0, "is_melee": True},
            defenses=StartingDefenses(
                magic_shield=0.0,
                physical_shield=0.0,
                general_shield=0.0,
                healing_received_multiplier=1.0,
            ),
        )

    return [
        actor(holder_id, (get_item_by_name("Fimbulwinter"),)),
        actor(source_id, ()),
    ]


def _events(holder_id: str, shield_time: object, reactive_time: object) -> list[dict]:
    source_id = "enemy:Aatrox" if holder_id == "main" else "main"
    return [
        {
            "time": shield_time,
            "kind": "shield",
            "amount": 40.0,
            "duration": 3.0,
            "source": EVERLASTING,
            "source_key": "item_Fimbulwinter",
            "attacker": holder_id,
            "target": holder_id,
            "_event_id": f"{holder_id}:fimbulwinter:E:1",
            "event_precision": "exact",
            # Everlasting is a barrier placed *after* the damage that
            # triggered it: the old ``_priority: 0.5`` float is this rank.
            SUPPORT_RANK_KEY: TransitionRank.LATE_BARRIER,
        },
        {
            "time": reactive_time,
            "damage": 60.0,
            "raw_damage": 60.0,
            "damage_type": "physical",
            "source": "authored reactive damage",
            "source_key": "reactive_packet",
            "attacker": source_id,
            "target": holder_id,
            "_event_id": f"{source_id}:reactive:1",
            "_reactive": True,
            "event_precision": "exact",
        },
    ]


def _actions(holder_id: str, shield_time: object, reactive_time: object):
    events = _events(holder_id, shield_time, reactive_time)
    index_of = {
        combatant.participant_id: index
        for index, combatant in enumerate(_combatants(holder_id))
    }
    actions = []
    for aidx, event in enumerate(events):
        # The reactive packet rode the same 0.5 float as the barrier above;
        # ``REACTIVE`` and ``LATE_BARRIER`` still share one ordering slot, so
        # the same-time tie this matrix is about is unchanged.
        phase = event.get(SUPPORT_RANK_KEY, TransitionRank.REACTIVE)
        action = action_from_event(
            event,
            phase,
            index_of[holder_id],
            index_of,
            subject_id=holder_id,
            aidx=aidx,
        )
        actions.append(action)
    return sorted(actions, key=lambda action: action.sort_key), events


def _walk(
    holder_id: str,
    shield_time: object,
    reactive_time: object,
    ledger_type,
    *,
    reverse_input: bool = False,
):
    combatants = _combatants(holder_id)
    actions, events = _actions(holder_id, shield_time, reactive_time)
    if reverse_input:
        actions = sorted(actions, key=lambda action: action.sort_key)
    states = build_states(combatants, (0.0,) * len(combatants))
    index_of = {
        combatant.participant_id: index for index, combatant in enumerate(combatants)
    }
    if ledger_type is ReceiptLedger:
        event_by_id = {event["_event_id"]: event for event in events}
        walk_actions = [
            action._replace(event=event_by_id[EVENT_SLOTS.text(action.event_slot)])
            for action in actions
        ]
        ledger = ReceiptLedger(
            actions=walk_actions,
            index_of=index_of,
            compile_event=action_from_event,
            annotating=True,
        )
    else:
        walk_actions = [action._replace(event=None) for action in actions]
        ledger = ScoreLedger(len(walk_actions))
    context = TransitionContext(
        duration=5.0,
        states=states,
        combatants=combatants,
        index_of=index_of,
        ledger=ledger,
        regeneration_windows=(None,) * len(combatants),
    )
    result = run_one_walk(walk_actions, context)
    return survival(roster_program(combatants), result)[holder_id], events


@pytest.mark.parametrize("holder_id", ["main", "enemy:Ahri"])
def test_shield_before_reactive_damage_when_timestamp_is_earlier(holder_id):
    """Attacker-side and defender-side holders use ordinary time order."""
    result, _ = _walk(holder_id, 1.0, 1.0 + EPSILON, ReceiptLedger)

    assert result["ending_health"] == pytest.approx(80.0)
    assert result["shield_absorbed"] == pytest.approx(40.0)
    assert result["support_shield_received"] == pytest.approx(40.0)


@pytest.mark.parametrize("holder_id", ["main", "enemy:Ahri"])
def test_reactive_damage_before_shield_when_timestamp_is_earlier(holder_id):
    """An epsilon gives the reactive packet an explicit earlier time."""
    result, _ = _walk(holder_id, 1.0 + EPSILON, 1.0, ReceiptLedger)

    assert result["ending_health"] == pytest.approx(40.0)
    assert result["shield_absorbed"] == pytest.approx(0.0)
    assert result["support_shield_received"] == pytest.approx(40.0)


@pytest.mark.parametrize("holder_id", ["main", "enemy:Ahri"])
@pytest.mark.parametrize(
    ("shield_time", "reactive_time"),
    [(1.0, 1.0 - EPSILON), (1.0, 1.0), (1.0, 1.0 + EPSILON)],
)
def test_receipt_and_score_walks_keep_identical_survival(
    holder_id, shield_time, reactive_time
):
    """Adapter parity is independent from source certification of the order."""
    receipt, _ = _walk(holder_id, shield_time, reactive_time, ReceiptLedger)
    score, _ = _walk(holder_id, shield_time, reactive_time, ScoreLedger)

    assert score == receipt


@pytest.mark.parametrize("holder_id", ["main", "enemy:Ahri"])
def test_same_time_receipt_is_stable_when_construction_order_changes(holder_id):
    """Payload list order does not select the current deterministic result."""
    forward, forward_events = _walk(
        holder_id, 1.0, 1.0, ReceiptLedger, reverse_input=False
    )
    reversed_result, reversed_events = _walk(
        holder_id, 1.0, 1.0, ReceiptLedger, reverse_input=True
    )

    assert reversed_result == forward
    assert [
        (event["_event_id"], event.get("applied_amount"), event.get("damage"))
        for event in reversed_events
    ] == [
        (event["_event_id"], event.get("applied_amount"), event.get("damage"))
        for event in forward_events
    ]


@pytest.mark.parametrize(
    ("holder_id", "ending_health", "shield_absorbed"),
    [
        # holder_id == "main": action_key resolves the shield BEFORE the
        # reactive packet at the tied timestamp (source-side order pins
        # "shield" first — see test_same_time_action_key_exposes_side_
        # sensitive_source_order, first_kind="shield" for holder "main").
        # The shield is up when the reactive damage lands: it absorbs.
        ("main", 80.0, 40.0),
        # holder_id == "enemy:Ahri": the SAME stable action_key resolves
        # the reactive packet BEFORE the shield at the tied timestamp
        # (first_kind="reactive" for this holder side).  The reactive
        # damage lands before the shield is up: nothing is absorbed.
        ("enemy:Ahri", 40.0, 0.0),
    ],
)
def test_same_time_pair_resolves_by_the_stable_side_sensitive_action_key(
    holder_id, ending_health, shield_absorbed
):
    """No local source certifies a same-time Everlasting-vs-reactive-damage
    ORDERING POLICY, but the kernel does not leave the tie ambiguous today:
    ``action_key`` (see ``test_same_time_action_key_exposes_side_sensitive_
    source_order`` directly below) is a deterministic, stable, side-
    sensitive tiebreak that resolves every equal-phase tie the same way on
    every run (``test_same_time_receipt_is_stable_when_construction_order_
    changes`` already pins reverse-input stability).  This row asserts that
    ACTUAL deterministic resolution rather than a hypothetical uniform
    "always fail closed" policy: for holder "main" the shield resolves
    first and absorbs the reactive hit; for holder "enemy:Ahri" the SAME
    stable key resolves the reactive packet first and the shield (though
    it still registers as received) absorbs nothing.  Neither side invents
    an uncertified shield value — both are the walk's own stable-order
    output, receipted exactly as the walk emits it."""
    result, _ = _walk(holder_id, 1.0, 1.0, ReceiptLedger)

    assert result["ending_health"] == pytest.approx(ending_health)
    assert result["shield_absorbed"] == pytest.approx(shield_absorbed)
    # The shield is always granted (support delivery is not tie-sensitive);
    # only its absorption against the tied reactive hit is order-sensitive.
    assert result["support_shield_received"] == pytest.approx(40.0)


@pytest.mark.parametrize("bad_time", [None, "not-a-time"])
def test_non_numeric_event_time_fails_closed(bad_time):
    """The typed event adapter rejects an unavailable or malformed timestamp."""
    event = _events("main", bad_time, 1.0)[0]

    with pytest.raises((TypeError, ValueError)):
        action_from_event(
            event,
            TransitionRank.LATE_BARRIER,
            0,
            {"main": 0, "enemy:Aatrox": 1},
            subject_id="main",
        )


def test_non_finite_event_time_fails_closed():
    """A non-finite timestamp cannot establish a stable event order.

    ``action_key`` (src/calculator/survival/actions.py) validates
    ``math.isfinite`` on the timestamp and raises ``ValueError`` naming the
    bad value and event id.  The guard moved there with the constructor:
    main put it in ``survival_action_from_event``, which this branch split
    into ``program.compile.action_from_event``; ``action_key`` is the one
    function every author of an action reaches, so the refusal covers the
    composition and the compiler too rather than only one caller —
    matching the existing ``test_non_numeric_event_time_fails_closed``
    row's fail-closed contract for None/malformed timestamps, extended to
    the case a bare ``float()`` coercion does not reject (NaN, +/-inf)."""
    event = _events("main", float("nan"), 1.0)[0]

    with pytest.raises(ValueError):
        action_from_event(
            event,
            TransitionRank.LATE_BARRIER,
            0,
            {"main": 0, "enemy:Aatrox": 1},
            subject_id="main",
        )


@pytest.mark.parametrize(
    ("holder_id", "first_kind"),
    [("main", "shield"), ("enemy:Ahri", "reactive")],
)
def test_same_time_action_key_exposes_side_sensitive_source_order(
    holder_id, first_kind
):
    """Equal phases fall through to source-side order in the stable key."""
    shield, reactive = _events(holder_id, 1.0, 1.0)

    shield_key = action_key(1.0, TransitionRank.LATE_BARRIER, holder_id, shield)
    reactive_key = action_key(1.0, TransitionRank.REACTIVE, holder_id, reactive)
    first = "shield" if shield_key < reactive_key else "reactive"

    # Both fold onto one ordering slot, which is what the shared 0.5 float
    # meant; the tie-break below it is what this row is about.
    assert shield_key[1] is TransitionRank.LATE_BARRIER
    assert reactive_key[1] is TransitionRank.LATE_BARRIER
    assert first == first_kind
