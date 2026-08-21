"""A live-predicate amplifier is a rider, and a rider dies with its host.

Shadowflame's Cinderbloom is the one amplifier in the tree whose pool does
not exist until the walk runs: it reads the target's health *at the instant
of the hit*, under fire from a whole roster.  Phase 4 S7 gave the mechanic to
the walk for exactly that reason, and the shape the ruling names is a rider —
an :class:`~src.calculator.survival.actions.LiveAmp` field on the damage
action itself rather than an event of its own.

That shape is the whole fix, and this file is it in both directions.  A hit
that never lands emits no bonus *because there is nothing to carry one*: a
spell-shielded, state-blocked or post-death packet never reaches the damage
branch, so no cancellation logic has to exist and none can be forgotten.  And
the predicate is read before absorption, so a shield does not hide a low
target and a killing blow does not retroactively qualify its own hit.
"""

from __future__ import annotations

from functools import lru_cache
from types import SimpleNamespace

import pytest

from src.calculator.delivery_eligibility import (
    SPELL_SHIELD_ONE_USE_RULE,
    DefenseWindow,
    SourceReceipt,
    SpellShieldComposition,
    SpellShieldEligibility,
)

from src import app as app_module
from src.calculator.defensive_effects import StartingDefenses
from src.calculator.participant_timeline import Combatant
from src.calculator.program.amp import LiveAmpRider, live_amp_for, live_amp_riders
from src.calculator.program.compile import action_from_event
from src.calculator.survival import (
    EVENT_SLOTS,
    ActionKind,
    ReceiptLedger,
    SurvivalAction,
    TransitionContext,
    TransitionRank,
    build_states,
    finalize_states,
    run_survival_walk,
)
from src.calculator.survival.actions import LiveAmp, LiveProbe

CINDERBLOOM = LiveAmp(
    probe=LiveProbe.HEALTH_BELOW_RATIO,
    threshold=0.4,
    fraction=0.2,
    mechanic="shadowflame.cinderbloom",
)


def _target(max_health: float, *, general_shield: float = 0.0) -> Combatant:
    """One defender with nothing but health and an optional shield."""
    return Combatant(
        participant_id="target",
        team="enemy",
        champion_data={"name": "target"},
        level=1,
        items=(),
        stats={"health": max_health, "is_melee": True},
        defenses=StartingDefenses(
            magic_shield=0.0,
            physical_shield=0.0,
            general_shield=general_shield,
            healing_received_multiplier=1.0,
        ),
    )


def _hit(
    aidx: int,
    time: float,
    amount: float,
    *,
    live_amp: LiveAmp | None = None,
    is_ability: bool = False,
) -> SurvivalAction:
    """One magic packet into the target, optionally carrying a rider."""
    event_id = f"hit:{aidx}"
    return SurvivalAction(
        sort_key=(time, TransitionRank.DAMAGE, aidx, 0, 0, "target", event_id, "spell"),
        time=time,
        phase=TransitionRank.DAMAGE,
        kind=ActionKind.DAMAGE if is_ability else ActionKind.PLAIN_DAMAGE,
        subject=0,
        attacker=0,
        aidx=aidx,
        amount=amount,
        damage_type="magic",
        is_ability=is_ability,
        ability_instance=f"spell:{aidx}" if is_ability else None,
        source_key="spell",
        source="spell",
        event_slot=EVENT_SLOTS.slot(event_id),
        sequence=aidx,
        live_amp=live_amp,
    )


def _walk(actions, target, *, state_edits=None):
    """Run the kernel over *actions* and return the observed events.

    ``state_edits`` mutates the built state before the walk, which is how a
    spell shield, a stasis window and a dead attacker are staged without
    authoring the transitions that grant them — those are other mechanics'
    tests, and what is under test here is what the rider does when its host
    does not land.
    """
    observed = [dict(action.event or {}) for action in actions]
    staged = [action._replace(event=event) for action, event in zip(actions, observed)]
    states = build_states([target], (0.0,))
    if state_edits is not None:
        state_edits(states)
    ledger = ReceiptLedger(
        actions=staged,
        index_of={"target": 0},
        compile_event=action_from_event,
        annotating=True,
    )
    ctx = TransitionContext(
        duration=10.0,
        states=states,
        combatants=[target],
        index_of={"target": 0},
        ledger=ledger,
        regeneration_windows=(None,),
    )
    run_survival_walk(staged, ctx)
    finalize_states(states, 10.0)
    return observed, states[0]


def _bonus(observed) -> float:
    """Every rider bonus the walk recorded, summed."""
    return sum(float(event.get("live_amp_bonus", 0.0)) for event in observed)


# ---------------------------------------------------------------------------
# The predicate, and when it is read
# ---------------------------------------------------------------------------


def test_a_target_under_the_threshold_is_amplified():
    """The ordinary case: below the declared ratio, the bonus is priced."""
    observed, state = _walk(
        [_hit(0, 0.0, 700.0), _hit(1, 1.0, 100.0, live_amp=CINDERBLOOM)],
        _target(1000.0),
    )
    assert _bonus(observed) == pytest.approx(20.0)
    assert observed[1]["live_amp_source"] == "shadowflame.cinderbloom"
    assert state["pools"].health == pytest.approx(180.0)


def test_a_target_over_the_threshold_is_not():
    """Above the ratio the rule ran and measured zero — no row, no bonus."""
    observed, state = _walk(
        [_hit(0, 1.0, 100.0, live_amp=CINDERBLOOM)], _target(1000.0)
    )
    assert _bonus(observed) == 0.0
    assert "live_amp_source" not in observed[0]
    assert state["pools"].health == pytest.approx(900.0)


def test_the_predicate_reads_the_health_before_this_packet_lands():
    """A killing blow does not retroactively qualify itself.

    The target sits at 50% and this one packet takes it to 10%.  Reading the
    predicate *after* absorption would amplify the very hit that made the
    condition true, which is a different mechanic — and a strictly more
    generous one — from the declared "against enemies below 40% health".
    """
    observed, _ = _walk(
        [_hit(0, 0.0, 500.0), _hit(1, 1.0, 400.0, live_amp=CINDERBLOOM)],
        _target(1000.0),
    )
    assert _bonus(observed) == 0.0


def test_a_shield_does_not_hide_a_low_target():
    """Health is what the predicate reads, and it is read before absorption.

    The target is at 30% health behind a large shield.  A predicate read
    after absorption would see a packet the shield ate and a health pool
    that never moved; read before it, the target is low and the bonus is
    priced — which is also what the pair engine's own ordered ledger does,
    so the two engines answer the same question about the same instant.
    """
    observed, state = _walk(
        [_hit(0, 0.0, 700.0), _hit(1, 1.0, 100.0, live_amp=CINDERBLOOM)],
        _target(1000.0, general_shield=1000.0),
        state_edits=lambda states: states[0]["pools"].__setattr__("health", 300.0),
    )
    assert _bonus(observed) == pytest.approx(20.0)
    assert state["pools"].health == pytest.approx(300.0)


# ---------------------------------------------------------------------------
# A rider dies with its host
# ---------------------------------------------------------------------------


def test_a_spell_shielded_trigger_emits_no_bonus():
    """The packet never reaches the damage branch, so neither does its rider."""
    observed, state = _walk(
        [
            _hit(0, 0.0, 700.0),
            _hit(1, 1.0, 100.0, live_amp=CINDERBLOOM, is_ability=True),
        ],
        _target(1000.0),
        # The kernel's spell-shield gate is the typed eligibility contract
        # (P2 Slice 2), not the legacy ``spell_shield_until`` projection the
        # branch this fixture predates read; arming the contract is what
        # "a shield is up" now means.
        state_edits=lambda states: states[0].update(
            {
                "spell_shield_until": 5.0,
                "spell_shield_source": "Banshee's Veil",
                "spell_shield_eligibility": SpellShieldEligibility(
                    name="spell_shield",
                    window=DefenseWindow(start=0.0, until=5.0),
                    block_rule=SPELL_SHIELD_ONE_USE_RULE,
                    source=SourceReceipt(
                        label="Banshee's Veil",
                        url="https://wiki.leagueoflegends.com",
                    ),
                ),
                "spell_shield_composition": SpellShieldComposition(),
                "spell_shield_uses_remaining": 1,
            }
        ),
    )
    assert _bonus(observed) == 0.0
    assert state["pools"].health == pytest.approx(300.0)


def test_a_state_blocked_trigger_emits_no_bonus():
    """Stasis, invulnerability and untargetability skip the packet outright."""
    observed, state = _walk(
        [_hit(0, 0.0, 700.0), _hit(1, 1.0, 100.0, live_amp=CINDERBLOOM)],
        _target(1000.0),
        state_edits=lambda states: states[0].update({"stasis_until": 5.0}),
    )
    assert _bonus(observed) == 0.0
    assert state["pools"].health == pytest.approx(1000.0)


def test_a_post_death_trigger_emits_no_bonus():
    """A dead attacker's already-scheduled packet carries no bonus either."""

    def kill_the_attacker(states):
        states[0]["death_time"] = 0.5

    observed, _ = _walk(
        [_hit(0, 0.0, 700.0), _hit(1, 1.0, 100.0, live_amp=CINDERBLOOM)],
        _target(1000.0),
        state_edits=kill_the_attacker,
    )
    assert _bonus(observed) == 0.0


def test_a_probe_the_kernel_cannot_read_raises_rather_than_amplifying_nothing():
    """An unknown tag is a rule that did not run, never a bonus of zero."""
    unknown = SimpleNamespace(
        probe="a_pool_nobody_declared",
        threshold=0.4,
        fraction=0.2,
        mechanic="probe.unreadable",
    )
    with pytest.raises(ValueError, match="the walk cannot read"):
        _walk(
            [_hit(0, 0.0, 700.0), _hit(1, 1.0, 100.0, live_amp=unknown)],
            _target(1000.0),
        )


# ---------------------------------------------------------------------------
# The interpreter that builds one
# ---------------------------------------------------------------------------


def test_the_interpreter_reads_shadowflames_own_declaration():
    """Threshold, fraction and typing come from the rule, not from here."""
    riders = live_amp_riders(
        ["Shadowflame"],
        level=18,
        fight_duration_seconds=8.0,
        target_bonus_health=0.0,
        holder_is_melee=False,
    )
    assert len(riders) == 1
    rider = riders[0]
    assert rider.amp.mechanic == "shadowflame.cinderbloom"
    assert rider.amp.probe is LiveProbe.HEALTH_BELOW_RATIO
    assert rider.amp.threshold == pytest.approx(0.4)
    assert rider.amp.fraction == pytest.approx(0.2)
    assert rider.damage_types == frozenset({"magic", "true"})
    assert rider.rides("magic") and not rider.rides("physical")


def test_a_build_declaring_no_live_predicate_declares_no_rider():
    """No holder, no rider — an answer, not an amplifier of zero."""
    assert (
        live_amp_riders(
            ["Void Staff"],
            level=18,
            fight_duration_seconds=8.0,
            target_bonus_health=0.0,
            holder_is_melee=False,
        )
        == ()
    )


def test_two_riders_claiming_one_packet_raise_rather_than_dropping_one():
    """A packet carries one rider, and which one is not this code's to pick."""
    second = LiveAmpRider(amp=CINDERBLOOM, damage_types=frozenset({"magic"}))
    with pytest.raises(ValueError, match="two live amplifiers claim one"):
        live_amp_for((second, second), "magic")


# ---------------------------------------------------------------------------
# The roster: the applied number is the coupled one, and it is not the preview
# ---------------------------------------------------------------------------

HOLDER = "Ahri"
ENEMY = "Aatrox"
ALLY = "Pantheon"


@lru_cache(maxsize=4)
def _roster(allies):
    """One roster response through the public request path."""
    app_module.app.config["TESTING"] = True
    payload = {
        "champion": HOLDER,
        "level": 18,
        "items": ["Shadowflame", "Rabadon's Deathcap"],
        "fight_mode": "time_based",
        "fight_duration": 8,
        "enemies": [{"champion": ENEMY, "level": 18, "items": []}],
        "allies": [
            {
                "champion": name,
                "level": 18,
                "items": [],
                "ally_effects_enabled": True,
            }
            for name in allies
        ],
    }
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_data(as_text=True)[:400]
    return response.get_json()


def _death_time(body, participant_id=f"enemy:{ENEMY}"):
    """When the roster killed one participant."""
    return next(
        row
        for row in body["combat"]["breakdown"]
        if row["participant_id"] == participant_id
    )["death_time"]


def _applied(body):
    """Every rider bonus the coupled receipt published, summed."""
    return sum(
        event["live_amp"]["bonus"]
        for event in body["combat"]["events"]
        if event.get("live_amp")
    )


def test_the_contribution_rises_in_a_multi_attacker_roster():
    """The reason the walk owns this mechanic, as a number.

    Add one ally and the same holder's own packets land on a target the
    roster took low sooner and harder — precisely the input a pair engine
    cannot see and the pair preview therefore cannot price.  The claim is
    the *rise*: the solo figure is no longer zero (this holder alone now
    reaches the 40% threshold inside the window), so the two rosters are
    compared against each other rather than against a stale zero.
    """
    solo = _applied(_roster(()))
    with_ally = _applied(_roster((ALLY,)))
    assert solo > 0.0
    assert with_ally > solo


def test_the_preview_survives_where_it_is_the_answer_and_is_not_the_applied_number():
    """Two readings, published in the two places each one answers for.

    The pair-engine breakdown is the single-attacker question and its
    Cinderbloom row is still there, unchanged — a preview is not a deletion.
    What it may never be is the roster's number, and it is not: the applied
    total is the walk's own, computed against a target the whole roster took
    low, and the two figures are different numbers arrived at differently.
    """
    body = _roster((ALLY,))
    preview = body["breakdown"]["shadowflame_Shadowflame"]["total_damage"]
    assert preview > 0.0
    assert _applied(body) != pytest.approx(preview, abs=0.15)


def test_removing_the_coupled_interpreter_drops_it_to_zero_not_to_the_preview(
    monkeypatch,
):
    """Zero with a receipt, never a fall back to the pair engine's figure.

    The preview is still computed — it is the honest single-attacker answer
    and the pair breakdown publishes it — so an implementation that composed
    it when the coupled interpreter went missing would look healthy and be
    wrong.  With the interpreter removed the applied total is zero, not the
    preview.

    The removal is read off the *fight*, not off the outgoing total: this
    roster kills the target either way, so ``outgoing_damage_before_death``
    saturates at the target's health pool and cannot carry the difference.
    What the bonus moves is when the target dies.
    """
    from src.calculator import participant_timeline

    body = _roster((ALLY,))
    applied = _applied(body)
    preview = body["breakdown"]["shadowflame_Shadowflame"]["total_damage"]
    assert applied > 0.0 and preview > 0.0
    _roster.cache_clear()
    monkeypatch.setattr(
        participant_timeline, "_live_amps_of", lambda attacker, defender, params: ()
    )
    without = _roster((ALLY,))
    _roster.cache_clear()
    assert _applied(without) == 0.0
    assert _death_time(without) > _death_time(body)
