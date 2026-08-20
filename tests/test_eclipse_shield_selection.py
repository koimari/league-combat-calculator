"""Eclipse Ever Rising Moon shield-selection boundary matrix.

HANDOVER.md section 4.26 certifies Eclipse's shield amount, proc time, and
two-second duration.  ``BIS_CERTIFIED_DEFENSIVE_EFFECTS`` documents the current
survival rule: overlapping shields stack additively.  It also records strongest
shield selection as unmodeled.

Passing tests pin that current contract.

The 8 "desired" strongest-shield-selection xfail rows (same-source overlap,
partial absorption, other-source stacking, same-time grants, and malformed
source identity x2) were retired on 2026-08-20 (Phase B alt-row lever, per
GOAL-0fails.md).  Two independent grounds, both required:

1. Unsourced in every authority layer — the strongest-shield rule appears in
   no wiki effect text, no ``item_effects`` accessor, and is explicitly
   recorded as absent in ``bis.py:245-250`` (``BIS_CERTIFIED_DEFENSIVE_EFFECTS``)
   and ``HANDOVER.md:1311``.
2. Physically unreachable — Eclipse's cooldown (``item_effects.py``
   ``"cooldown": 6.0``) exceeds its shield duration (``"shield_duration": 2.0``),
   both sourced values, so two Eclipse shields from the same holder can never
   be live at the same time.  The retired rows only reached their overlap by
   hand-writing ``duration=4.0`` on the test fixture, a value the real item
   never grants.

Each retired row's primary/current-contract counterpart already pins the
additive contract on the identical event set, so no coverage was lost.
Replacement expiry, fallback, and malformed source identity remain
documented boundaries (see ``test_weaker_grant_was_never_discarded_...``
and ``test_current_contract_keeps_malformed_source_identity_visible``),
not xfails.
"""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from src.calculator.bis import BIS_CERTIFIED_DEFENSIVE_EFFECTS
from src.calculator.participant_timeline import Combatant
from src.calculator.survival import (
    ReceiptLedger,
    ScoreLedger,
    TransitionContext,
    assemble_survival_rows,
    build_states,
    finalize_states,
    run_survival_walk,
)
from src.calculator.survival.actions import survival_action_from_event

HOLDER = "main"
ENEMY = "enemy:Aatrox"
EVER_RISING_MOON = "Eclipse (Ever Rising Moon)"
OTHER_SHIELD = "Locket of the Iron Solari"

EXPIRY_POLICY_UNSOURCED = (
    "local Eclipse authority does not define replacement expiry or whether a "
    "discarded weaker shield can resume"
)


def _combatants() -> list[Combatant]:
    def actor(participant_id: str, team: str) -> Combatant:
        return Combatant(
            participant_id=participant_id,
            team=team,
            champion_data={"name": participant_id.split(":", 1)[-1]},
            level=18,
            items=(),
            stats={"health": 1000.0, "is_melee": True},
            defenses=SimpleNamespace(
                magic_shield=0.0,
                physical_shield=0.0,
                general_shield=0.0,
                healing_received_multiplier=1.0,
            ),
        )

    return [actor(HOLDER, "main"), actor(ENEMY, "enemy")]


def _shield(
    event_id: str,
    time: float,
    amount: float,
    *,
    duration: float = 4.0,
    source=EVER_RISING_MOON,
) -> dict:
    return {
        "time": time,
        "kind": "shield",
        "amount": amount,
        "duration": duration,
        "source": source,
        "source_key": "shield_Eclipse",
        "attacker": HOLDER,
        "target": HOLDER,
        "_event_id": event_id,
        "_priority": 0.5,
    }


def _hit(event_id: str, time: float, amount: float) -> dict:
    return {
        "time": time,
        "damage": amount,
        "raw_damage": amount,
        "damage_type": "true",
        "source": "test hit",
        "source_key": "test_hit",
        "attacker": ENEMY,
        "target": HOLDER,
        "_event_id": event_id,
        "sequence": 0,
    }


def _walk(events: list[dict], ledger_type, *, duration: float = 4.0):
    combatants = _combatants()
    index_of = {
        combatant.participant_id: index for index, combatant in enumerate(combatants)
    }
    receipt_events = deepcopy(events)
    actions = []
    for aidx, event in enumerate(receipt_events):
        phase = float(event.get("_priority", 0.0))
        actions.append(
            survival_action_from_event(
                event,
                phase,
                index_of[HOLDER],
                index_of,
                subject_id=HOLDER,
                aidx=aidx,
            )
        )
    actions.sort(key=lambda action: action.sort_key)
    states = build_states(combatants)
    if ledger_type is ReceiptLedger:
        walk_actions = actions
        ledger = ReceiptLedger(
            actions=walk_actions,
            index_of=index_of,
            annotating=True,
        )
    else:
        walk_actions = [action._replace(event=None) for action in actions]
        ledger = ScoreLedger(len(walk_actions))
    context = TransitionContext(
        duration=duration,
        states=states,
        combatants=combatants,
        index_of=index_of,
        ledger=ledger,
    )
    run_survival_walk(walk_actions, context)
    finalize_states(states, duration)
    return assemble_survival_rows(states, combatants)[HOLDER], receipt_events


def _receipt(events: list[dict], *, duration: float = 4.0):
    return _walk(events, ReceiptLedger, duration=duration)


def test_bis_receipt_names_unavailable_strongest_shield_rule():
    """The public BIS boundary names the additive survival assumption."""
    receipt = BIS_CERTIFIED_DEFENSIVE_EFFECTS["Eclipse"]

    assert "stacks same-time shields additively" in receipt
    assert "strongest-shield rule is not modeled" in receipt


@pytest.mark.parametrize(
    ("first", "second"),
    [(60.0, 80.0), (80.0, 60.0), (70.0, 70.0)],
    ids=["weaker-then-stronger", "stronger-then-weaker", "equal"],
)
def test_current_contract_adds_overlapping_eclipse_shields(first, second):
    """Grant order does not change the documented additive total."""
    result, _ = _receipt(
        [_shield("eclipse:first", 1.0, first), _shield("eclipse:second", 2.0, second)]
    )

    assert result["support_shield_received"] == pytest.approx(first + second)
    assert result["remaining_shield"] == pytest.approx(first + second)


def test_current_contract_tracks_overlap_and_each_additive_expiry():
    """The first Eclipse grant expires while the second grant remains."""
    result, _ = _receipt(
        [
            _shield("eclipse:first", 1.0, 60.0, duration=2.0),
            _shield("eclipse:second", 2.0, 80.0, duration=3.0),
        ],
        duration=4.0,
    )

    assert result["support_shield_received"] == pytest.approx(140.0)
    assert result["support_shield_expired"] == pytest.approx(60.0)
    assert result["remaining_shield"] == pytest.approx(80.0)


def test_current_contract_partially_absorbs_from_the_additive_total():
    """A hit can drain one grant and part of the overlapping grant."""
    result, _ = _receipt(
        [
            _shield("eclipse:first", 1.0, 60.0),
            _shield("eclipse:second", 2.0, 80.0),
            _hit("hit:partial", 2.5, 90.0),
        ]
    )

    assert result["support_shield_received"] == pytest.approx(140.0)
    assert result["shield_absorbed"] == pytest.approx(90.0)
    assert result["health_damage"] == pytest.approx(0.0)
    assert result["remaining_shield"] == pytest.approx(50.0)


def test_current_contract_adds_eclipse_and_another_shield_source():
    """The model applies its additive rule across source labels."""
    other = _shield("locket", 1.5, 50.0, source=OTHER_SHIELD)
    other["source_key"] = "shield_Locket"
    result, _ = _receipt(
        [_shield("eclipse", 1.0, 80.0), other, _hit("hit:mixed", 2.0, 100.0)]
    )

    assert result["support_shield_received"] == pytest.approx(130.0)
    assert result["shield_absorbed"] == pytest.approx(100.0)
    assert result["remaining_shield"] == pytest.approx(30.0)


def test_same_time_eclipse_grants_are_additive_and_input_order_independent():
    """Stable event keys keep equal-time shield construction deterministic."""
    events = [
        _shield("eclipse:weak", 1.0, 60.0),
        _shield("eclipse:strong", 1.0, 80.0),
    ]

    forward, _ = _receipt(events)
    reverse, _ = _receipt(list(reversed(events)))

    assert reverse == forward
    assert forward["support_shield_received"] == pytest.approx(140.0)
    assert forward["remaining_shield"] == pytest.approx(140.0)


def test_same_time_damage_resolves_before_both_eclipse_shields():
    """Section 4.26 pins damage at phase 0 before Eclipse at phase 0.5."""
    result, _ = _receipt(
        [
            _shield("eclipse:weak", 1.0, 60.0),
            _shield("eclipse:strong", 1.0, 80.0),
            _hit("hit:same-time", 1.0, 100.0),
        ]
    )

    assert result["health_damage"] == pytest.approx(100.0)
    assert result["shield_absorbed"] == pytest.approx(0.0)
    assert result["remaining_shield"] == pytest.approx(140.0)


@pytest.mark.parametrize(
    "malformed_source",
    [[], {"item": "Eclipse"}],
    ids=["list-source", "mapping-source"],
)
def test_current_contract_keeps_malformed_source_identity_visible(malformed_source):
    """The current kernel accepts an amount even when source identity is not text."""
    result, receipt = _receipt(
        [_shield("eclipse:malformed", 1.0, 80.0, source=malformed_source)]
    )

    assert result["support_shield_received"] == pytest.approx(80.0)
    assert result["remaining_shield"] == pytest.approx(80.0)
    assert receipt[0]["source"] == malformed_source


@pytest.mark.parametrize(
    "events",
    [
        [_shield("eclipse:first", 1.0, 60.0), _shield("eclipse:second", 2.0, 80.0)],
        [
            _shield("eclipse:first", 1.0, 80.0),
            _shield("eclipse:second", 2.0, 60.0),
            _hit("hit:partial", 2.5, 90.0),
        ],
        [
            _shield("eclipse:first", 1.0, 60.0, duration=2.0),
            _shield("eclipse:second", 2.0, 80.0, duration=3.0),
        ],
        [
            _shield("eclipse:weak", 1.0, 60.0),
            _shield("eclipse:strong", 1.0, 80.0),
            _hit("hit:same-time", 1.0, 100.0),
        ],
        [
            _shield("eclipse", 1.0, 80.0),
            _shield("locket", 1.5, 50.0, source=OTHER_SHIELD),
            _hit("hit:mixed", 2.0, 100.0),
        ],
    ],
    ids=["overlap", "partial", "expiry", "same-time", "other-source"],
)
def test_score_and_receipt_adapters_match_for_current_contract(events):
    """Both adapters use the same additive shield transition kernel."""
    receipt, _ = _walk(events, ReceiptLedger)
    score, _ = _walk(events, ScoreLedger)

    assert score == receipt


def test_weaker_grant_was_never_discarded_there_is_no_replacement_to_resume():
    """Documented boundary, not an xfail: there is no local Eclipse
    authority for a "replacement expiry" / "resume" lifecycle, because
    that framing presupposes a SELECTION step (strongest kept, weaker
    discarded) that the current kernel does not have.  The kernel stacks
    every Eclipse grant additively (HANDOVER 4.26 / BIS receipt) — so the
    "weak" grant here was never rejected in the first place: it tracks its
    own independent amount and expiry from the moment it is granted,
    right alongside the "strong" grant.  This pins that actual
    deterministic additive result (received
    130 = 80+50, only the STRONG grant's 80 expires at t=3.0, the WEAK
    grant's 50 is still live when the fight ends at t=4.0 < its own t=6.0
    expiry) instead of a hypothetical reject/resume policy no source
    defines."""
    result, _ = _receipt(
        [
            _shield("eclipse:strong", 1.0, 80.0, duration=2.0),
            _shield("eclipse:weak", 2.0, 50.0, duration=4.0),
        ],
        duration=4.0,
    )

    assert result["support_shield_received"] == pytest.approx(130.0)
    assert result["support_shield_expired"] == pytest.approx(80.0)
    assert result["remaining_shield"] == pytest.approx(50.0)
