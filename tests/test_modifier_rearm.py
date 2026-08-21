"""One holder's one mechanic on one subject is one debuff, refreshed.

The walk armed a *new* cross-participant modifier every time a trigger fired
and multiplied every live one into each packet.  For a mechanic whose window
outlives its own cooldown that is a double count with no symptom: Bloodsong's
Expose Weakness opens a 4-second window on a 1.5-second cooldown, so an
eight-second fight arms it three times, and every packet inside an overlap
was multiplied by ``1.08`` **twice**.  Black Cleaver's Carve is the same
shape and worse — its packet already carries the *cumulative* stack
percentage, so eight live arms compounded eight armour reductions on one
attack.

Neither had a symptom, because ``_apply_cross_participant_modifiers`` writes
``support_damage_multiplier`` once per applying modifier and the receipt
therefore published the **last** factor rather than the product.  A number
the model computed that its own receipt contradicts is this campaign's
subject, so the fix belongs where the modifier arms and the test belongs
here.

Two different *holders* still keep two modifiers.  Whether they should is
:class:`~src.calculator.trigger_stream.HolderStacking`'s question and D-66's
``ArmingLedger`` is the one place it is answered; this rule must not become a
second answer to it.
"""

import pytest

from src.calculator.ability_spec import AttackClass, DamageClass
from src.calculator.survival.actions import SurvivalAction
from src.calculator.survival.transitions import (
    _apply_cross_participant_modifiers,
    _apply_damage_modifier,
)

ALL_DAMAGE = frozenset(DamageClass)
ALL_ATTACK = frozenset(AttackClass)

EXPOSE = "Bloodsong — Expose Weakness"
CARVE = "Black Cleaver — Carve"
UNMAKE = "Abyssal Mask — Unmake"

_HOLDER = 0
_SECOND_HOLDER = 1
_ALLY = 2


class _Ledger:
    """Every field the two transitions write, kept per event id."""

    def __init__(self):
        self.written = []

    def write(self, action, **fields):
        """Record the write the way the walk does — onto the packet."""
        self.written.append(fields)
        if action.event is not None:
            action.event.update(fields)

    def skip(self, action, reason):  # pylint: disable=unused-argument
        """Record nothing: no test here arms an unavailable modifier."""


class _Ctx:
    """The one context member the two transitions under test read."""

    def __init__(self):
        self.ledger = _Ledger()


def _arm(state, ctx, *, source, at, duration, holder, multiplier=1.08, **overrides):
    """Arm one cross-participant modifier the way a support packet does."""
    fields = {
        "source": source,
        "time": at,
        "duration": duration,
        "attacker": holder,
        "multiplier": multiplier,
        "amount": multiplier - 1.0,
        "damage_classes": ALL_DAMAGE,
        "attack_classes": ALL_ATTACK,
        "event": {},
    }
    fields.update(overrides)
    action = SurvivalAction(**fields)
    _apply_damage_modifier(ctx, action, state)
    return action


def _packet(*, at, attacker=_ALLY, damage_type="physical"):
    """A damage packet delivered by somebody who is not the holder."""
    return SurvivalAction(
        time=at,
        attacker=attacker,
        damage_type=damage_type,
        basic_attack=True,
        event={},
    )


@pytest.fixture(name="walk")
def _walk():
    """An empty subject state and the context the transitions write through."""
    return {"active_damage_modifiers": []}, _Ctx()


class TestOneHolderArmsOneModifier:
    """The arming rule: a re-arm refreshes, it never stacks."""

    def test_a_second_arm_inside_the_first_window_refreshes_it(self, walk):
        state, ctx = walk
        _arm(state, ctx, source=EXPOSE, at=1.5, duration=4.0, holder=_HOLDER)
        _arm(state, ctx, source=EXPOSE, at=4.5, duration=4.0, holder=_HOLDER)
        armed = state["active_damage_modifiers"]
        assert len(armed) == 1
        assert armed[0]["until"] == pytest.approx(8.5)

    def test_a_refresh_never_truncates_the_longer_window(self, walk):
        """The surviving expiry is the later one — the pair engine's union."""
        state, ctx = walk
        _arm(state, ctx, source=EXPOSE, at=1.0, duration=6.0, holder=_HOLDER)
        _arm(state, ctx, source=EXPOSE, at=2.0, duration=1.0, holder=_HOLDER)
        assert state["active_damage_modifiers"][0]["until"] == pytest.approx(7.0)

    def test_a_refresh_publishes_the_window_it_replaced(self, walk):
        """A window the walk discarded is a receipt row, never a silence."""
        state, ctx = walk
        _arm(state, ctx, source=EXPOSE, at=1.5, duration=4.0, holder=_HOLDER)
        action = _arm(state, ctx, source=EXPOSE, at=4.5, duration=4.0, holder=_HOLDER)
        assert action.event["refresh"] == {
            "reason": "refresh",
            "source": EXPOSE,
            "previous_expires_at": 5.5,
        }

    def test_a_first_arm_publishes_no_refresh(self, walk):
        state, ctx = walk
        action = _arm(state, ctx, source=EXPOSE, at=1.5, duration=4.0, holder=_HOLDER)
        assert "refresh" not in action.event

    def test_two_holders_keep_two_modifiers(self, walk):
        """PER_HOLDER's answer stays D-66's; this rule is not a second one."""
        state, ctx = walk
        _arm(state, ctx, source=EXPOSE, at=1.5, duration=4.0, holder=_HOLDER)
        _arm(state, ctx, source=EXPOSE, at=2.0, duration=4.0, holder=_SECOND_HOLDER)
        assert len(state["active_damage_modifiers"]) == 2

    def test_two_mechanics_from_one_holder_keep_two_modifiers(self, walk):
        state, ctx = walk
        _arm(state, ctx, source=EXPOSE, at=1.5, duration=4.0, holder=_HOLDER)
        _arm(state, ctx, source=CARVE, at=1.5, duration=6.0, holder=_HOLDER)
        assert len(state["active_damage_modifiers"]) == 2


class TestTheNumberIsAmplifiedOnce:
    """The defect, priced: what a packet inside an overlap is multiplied by."""

    def test_overlapping_windows_amplify_a_packet_once(self, walk):
        state, ctx = walk
        _arm(state, ctx, source=EXPOSE, at=1.5, duration=4.0, holder=_HOLDER)
        _arm(state, ctx, source=EXPOSE, at=4.5, duration=4.0, holder=_HOLDER)
        amount = _apply_cross_participant_modifiers(ctx, _packet(at=5.0), state, 100.0)
        assert amount == pytest.approx(108.0)

    def test_the_receipt_agrees_with_the_number(self, walk):
        """1.08 published and 1.1664 applied was the silent half of the bug."""
        state, ctx = walk
        _arm(state, ctx, source=EXPOSE, at=1.5, duration=4.0, holder=_HOLDER)
        _arm(state, ctx, source=EXPOSE, at=4.5, duration=4.0, holder=_HOLDER)
        packet = _packet(at=5.0)
        amount = _apply_cross_participant_modifiers(ctx, packet, state, 100.0)
        published = packet.event["support_damage_multiplier"]["multiplier"]
        assert amount == pytest.approx(100.0 * published)

    def test_two_holders_still_amplify_twice(self, walk):
        """The two-holder roster is the one this rule may not touch."""
        state, ctx = walk
        _arm(state, ctx, source=EXPOSE, at=1.5, duration=4.0, holder=_HOLDER)
        _arm(state, ctx, source=EXPOSE, at=2.0, duration=4.0, holder=_SECOND_HOLDER)
        amount = _apply_cross_participant_modifiers(ctx, _packet(at=3.0), state, 100.0)
        assert amount == pytest.approx(100.0 * 1.08 * 1.08)


class TestTheStackLedgerReducesOnce:
    """Carve's packet carries the cumulative percentage; only one may apply."""

    def _armed_carve(self, state, ctx, *stacks):
        for index, percent in enumerate(stacks):
            _arm(
                state,
                ctx,
                source=CARVE,
                at=float(index),
                duration=6.0,
                holder=_HOLDER,
                multiplier=1.0,
                amount=percent,
                armor_reduction_percent=percent,
                resistance_type="armor",
                damage_classes=frozenset({DamageClass.PHYSICAL}),
            )

    def test_five_stack_arms_leave_one_live_reduction(self, walk):
        state, ctx = walk
        self._armed_carve(state, ctx, 0.06, 0.12, 0.18, 0.24, 0.30)
        armed = state["active_damage_modifiers"]
        assert len(armed) == 1
        assert armed[0]["armor_reduction_percent"] == pytest.approx(0.30)

    def test_the_reduction_is_the_latest_stack_count_not_their_product(self, walk):
        state, ctx = walk
        self._armed_carve(state, ctx, 0.06, 0.12, 0.18, 0.24, 0.30)
        packet = _packet(at=5.0)
        packet = packet._replace(baseline_effective_armor=100.0)
        amount = _apply_cross_participant_modifiers(ctx, packet, state, 100.0)
        # 100 armour mitigates to 1/2; 30% reduced armour mitigates to 1/1.7.
        assert amount == pytest.approx(100.0 * (1.0 / 1.7) / (1.0 / 2.0))


class TestThePublishedFactorIsNotTheAppliedProduct:
    """Two live modifiers apply two factors; the receipt publishes one.

    The re-arm rule above folds one holder's repeats into one debuff, so the
    remaining shape is two *different* arms on one packet — two holders of
    one mechanic, or two mechanics. ``_apply_cross_participant_modifiers``
    writes ``support_damage_multiplier`` once per applying modifier, so the
    published factor is the last one and the applied amount is the product.
    """

    def test_two_holders_apply_two_factors_and_the_receipt_names_one(self):
        state, ctx = {"active_damage_modifiers": []}, _Ctx()
        for holder in (_HOLDER, _SECOND_HOLDER):
            _arm(state, ctx, source=EXPOSE, at=1.0, duration=4.0, holder=holder)
        packet = _packet(at=2.0, damage_type="physical")
        amount = _apply_cross_participant_modifiers(ctx, packet, state, 100.0)
        published = packet.event["support_damage_multiplier"]["multiplier"]
        assert amount == pytest.approx(100.0 * 1.08 * 1.08)
        assert published == pytest.approx(1.08)
        assert amount != pytest.approx(100.0 * published)

    def test_two_mechanics_on_one_packet_publish_one_of_them(self):
        state, ctx = {"active_damage_modifiers": []}, _Ctx()
        for source, multiplier in ((EXPOSE, 1.08), (UNMAKE, 1.12)):
            _arm(
                state,
                ctx,
                source=source,
                at=0.0,
                duration=4.0,
                holder=_HOLDER,
                multiplier=multiplier,
            )
        packet = _packet(at=1.0, damage_type="magic")
        amount = _apply_cross_participant_modifiers(ctx, packet, state, 100.0)
        published = packet.event["support_damage_multiplier"]["multiplier"]
        assert amount == pytest.approx(100.0 * 1.08 * 1.12)
        assert amount != pytest.approx(100.0 * published)
