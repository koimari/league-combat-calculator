"""Two holders of one mechanic: one modifier, or two (D-66, criterion 10).

Abyssal Mask's Unmake is an aura.  Two holders standing in range of one
enemy curse it *once* — a second curse would double a 12% amp nobody grants
twice.  Imperial Mandate's Command is a per-holder pool: two Mandate holders
each pay their own amplification, and dropping the second one would be the
campaign's founding incident re-created by a rule rather than by an
accident.

So "does a second holder arm a second modifier?" is a per-mechanic
declaration and not a policy the arming code picks, and this file is that
declaration checked in both directions, for every mechanic that carries one.
``program.amp.arm_key`` is the single decider; ``ArmingLedger`` is the single
place ``src/`` asks it; and a dropped arming leaves a ``dedupe`` receipt row
in the public support ledger rather than vanishing.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src import app as app_module
from src.calculator.program.amp import ArmingLedger, arm_key
from src.calculator.program.build import arming_stacking
from src.calculator.trigger_stream import (
    CAPABILITIES,
    SELF_SCOPED_DELIVERIES,
    HolderPacket,
    HolderStacking,
    RiderDelivery,
    packet_source_literal,
)

SRC = Path(__file__).resolve().parent.parent / "src"

# Subject and two distinct holders, as roster slots.  The subject is fixed
# because the question is only ever asked about one subject at a time: two
# holders cursing two different enemies is two armings under any declaration.
SUBJECT = 0
FIRST_HOLDER = 1
SECOND_HOLDER = 2


def _arming() -> tuple[tuple[str, str, HolderStacking], ...]:
    """Every mechanic that both declares a stacking and arms a packet.

    Read rather than listed: criterion 10 asks for one test per dual-sided
    mechanic, and a hand list would silently stop covering the next one the
    day somebody declares it.

    The filter is a **self-scoped** delivery and not "carries something in
    ``packet_source``", because the arming question is only ever asked of a
    half that arms a modifier on somebody else's subject.  A
    **rider-delivered** half authors no packet at all — its bonus rides an
    event its own holder already produced — and a retired family's
    **holder packet** modifies its own holder's damage, so neither has an
    arming key and neither can collide with a second holder.
    :func:`_rider_delivered` and :func:`_holder_packet_delivered` cover them
    instead; handing either one to the ledger would test it against a key
    ``src/`` never builds.
    """
    return tuple(
        (capability.mechanic, source, capability.holder_stacking)
        for capability in sorted(CAPABILITIES.values(), key=lambda cap: cap.mechanic)
        if capability.holder_stacking is not None
        and not isinstance(capability.packet_source, SELF_SCOPED_DELIVERIES)
        and (source := packet_source_literal(capability)) is not None
    )


def _rider_delivered() -> tuple[tuple[str, HolderStacking], ...]:
    """Every dual-sided mechanic whose walk half delivers a rider, not a packet."""
    return tuple(
        (capability.mechanic, capability.holder_stacking)
        for capability in sorted(CAPABILITIES.values(), key=lambda cap: cap.mechanic)
        if capability.holder_stacking is not None
        and isinstance(capability.packet_source, RiderDelivery)
    )


def _holder_packet_delivered() -> tuple[tuple[str, HolderStacking], ...]:
    """Every dual-sided mechanic whose walk half re-prices its holder's packet."""
    return tuple(
        (capability.mechanic, capability.holder_stacking)
        for capability in sorted(CAPABILITIES.values(), key=lambda cap: cap.mechanic)
        if capability.holder_stacking is not None
        and isinstance(capability.packet_source, HolderPacket)
    )


def test_every_dual_sided_mechanic_is_covered_here():
    """A vacuous parametrisation would make the tests below pass by emptiness.

    Twenty dual-sided mechanics in three delivery shapes: five arm packets on
    another participant, one delivers a rider, and fourteen re-price their own
    holder's packet since ``active_cast`` and ``cast_proc`` retired off the
    pair engine.  The three counts are asserted separately so a mechanic
    silently changing which kind it is shows up here rather than as a test
    that stopped running.
    """
    assert len(_arming()) == 5
    assert len(_rider_delivered()) == 1
    assert len(_holder_packet_delivered()) == 14
    assert (
        len(_arming()) + len(_rider_delivered()) + len(_holder_packet_delivered())
    ) == len([cap for cap in CAPABILITIES.values() if cap.holder_stacking is not None])


@pytest.mark.parametrize("mechanic, stacking", _rider_delivered())
def test_a_rider_delivered_mechanic_declares_stacking_and_arms_nothing(
    mechanic, stacking
):
    """The sixth mechanic's answer to the same question, in its own shape.

    Shadowflame's Cinderbloom amplifies its **own holder's** damage events,
    so two holders amplify two disjoint sets of packets and their
    contributions can never be the same one counted twice.  ``PER_HOLDER``
    is that fact declared rather than a default it fell through to — the
    field has none — and the ledger is deliberately never asked, because a
    dedupe key for a mechanic that arms nothing would be an answer to a
    question the declaration does not pose.
    """
    assert stacking is HolderStacking.PER_HOLDER
    armed = {declared for declared, _ in arming_stacking().values()}
    assert mechanic not in armed


@pytest.mark.parametrize("mechanic, stacking", _holder_packet_delivered())
def test_a_holder_packet_declares_stacking_and_arms_nothing(mechanic, stacking):
    """A retired family's answer to the same question, in its own shape.

    An item active's walk half prices *its own holder's* packet, so two
    roster members holding one item pay two disjoint packets and their
    contributions can never be the same one counted twice.  ``PER_HOLDER`` is
    that fact declared rather than a default it fell through to — the field
    has none — and the ledger is deliberately never asked, for the reason it
    is never asked of a rider: a dedupe key for a mechanic that arms no
    modifier on anyone else's subject would answer a question the
    declaration does not pose.
    """
    assert stacking is HolderStacking.PER_HOLDER
    armed = {declared for declared, _ in arming_stacking().values()}
    assert mechanic not in armed


@pytest.mark.parametrize("mechanic, packet_source, stacking", _arming())
def test_a_second_holder_arms_exactly_what_the_mechanic_declares(
    mechanic, packet_source, stacking
):
    """Both directions, one mechanic at a time — the criterion, literally.

    An aura's second arming collides and is dropped with a receipt naming the
    holder that got there first; a per-holder pool's second arming stands, so
    the second holder's contribution is priced rather than deduped away.
    """
    ledger = ArmingLedger(arming_stacking())
    assert ledger.admit(packet_source, SUBJECT, FIRST_HOLDER) is None, mechanic

    second = ledger.admit(packet_source, SUBJECT, SECOND_HOLDER)
    if stacking is HolderStacking.IDEMPOTENT_AURA:
        assert second is not None, mechanic
        assert second.receipt() == {
            "reason": "dedupe",
            "mechanic": mechanic,
            "holder_stacking": "idempotent_aura",
            "first_holder": FIRST_HOLDER,
        }
    else:
        assert second is None, mechanic


@pytest.mark.parametrize("mechanic, packet_source, stacking", _arming())
def test_the_key_shape_is_the_declaration_and_nothing_else(
    mechanic, packet_source, stacking
):
    """An aura drops the holder from the key; a per-holder pool keeps it.

    Pinned as a shape rather than only as an outcome, because the two
    outcomes above would also be produced by a key that happened to collide
    for an unrelated reason.
    """
    key = arm_key(SUBJECT, mechanic, FIRST_HOLDER, stacking)
    expected = (
        (SUBJECT, mechanic)
        if stacking is HolderStacking.IDEMPOTENT_AURA
        else (SUBJECT, mechanic, FIRST_HOLDER)
    )
    assert key == expected


@pytest.mark.parametrize("mechanic, packet_source, stacking", _arming())
def test_one_holder_re_arming_over_time_is_never_a_duplicate(
    mechanic, packet_source, stacking
):
    """A collision is between two holders; a repeat by one is a re-arm.

    Carve arms one modifier per damage event and Expose Weakness one per
    spellblade proc, so a single holder legitimately arms the same
    ``(subject, mechanic, holder)`` key dozens of times in one fight.  A
    ledger that collapsed those would be answering a question no mechanic
    declares — "may one holder arm this twice over time?" — and would have
    silently deleted every stack after the first.
    """
    ledger = ArmingLedger(arming_stacking())
    verdicts = [ledger.admit(packet_source, SUBJECT, FIRST_HOLDER) for _ in range(5)]
    assert verdicts == [None] * 5, mechanic


def test_a_mechanic_with_no_declared_stacking_is_never_keyed():
    """No declaration, no dedupe question — never a guessed one.

    A packet whose source names no dual-sided mechanic is admitted without a
    key being built at all.  Inventing an answer for it would be a policy
    where the campaign requires a declaration.
    """
    ledger = ArmingLedger(arming_stacking())
    for holder in (FIRST_HOLDER, SECOND_HOLDER):
        assert (
            ledger.admit("Locket of the Iron Solari — Devotion", SUBJECT, holder)
            is None
        )


def test_arm_key_is_the_only_arming_dedupe_in_src():
    """Criterion 10's source scan.

    A second "did this already arm?" answer would disagree with this one on
    exactly the roster that has two holders — the only roster where the
    question is asked at all, and therefore the only one where nobody would
    notice the disagreement until a number was already wrong.
    """
    deciders = []
    for path in sorted((SRC / "calculator").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        deciders.extend(
            f"{path.name}:{node.lineno}"
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "arm_key"
        )
    assert deciders == ["amp.py:" + str(_arm_key_lineno())]


def _arm_key_lineno() -> int:
    """Where ``arm_key`` is defined, read off the module rather than typed."""
    source = (SRC / "calculator/program/amp.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    return next(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "arm_key"
    )


# ---------------------------------------------------------------------------
# End to end: the aura, on a roster that really holds it twice
# ---------------------------------------------------------------------------

UNMAKE = "Abyssal Mask — Unmake"


def _two_abyssal_holders():
    """One roster where the main champion and an ally both hold Abyssal Mask."""
    app_module.app.config["TESTING"] = True
    payload = {
        "champion": "Ahri",
        "level": 18,
        "items": ["Abyssal Mask"],
        "fight_mode": "time_based",
        "fight_duration": 8,
        "enemies": [{"champion": "Aatrox", "level": 18, "items": []}],
        "allies": [
            {
                "champion": "Pantheon",
                "level": 18,
                "items": ["Abyssal Mask"],
                "ally_effects_enabled": True,
            }
        ],
    }
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_data(as_text=True)[:400]
    return response.get_json()


def test_two_abyssal_holders_curse_one_enemy_once_and_say_so():
    """The aura's live path: two packets, one arming, one named refusal.

    The dropped packet stays in the public ledger with ``applied_amount`` 0
    and a ``dedupe`` block naming the holder that armed first.  That is the
    whole point of a receipt: "the aura was already up" and "nothing was ever
    armed here" are two different facts, and a payload that showed neither
    would be the incident in miniature.
    """
    body = _two_abyssal_holders()
    unmake = [
        event for event in body["combat"]["support_events"] if event["source"] == UNMAKE
    ]
    armed = [event for event in unmake if "dedupe" not in event]
    dropped = [event for event in unmake if "dedupe" in event]

    assert len(unmake) == 2, "each holder authors its own curse packet"
    assert len(armed) == 1
    assert len(dropped) == 1
    assert dropped[0]["applied_amount"] == 0.0
    assert dropped[0]["dedupe"]["reason"] == "dedupe"
    assert dropped[0]["dedupe"]["mechanic"] == "abyssal_mask.unmake"
    assert dropped[0]["dedupe"]["holder_stacking"] == "idempotent_aura"
    assert armed[0]["target"] == dropped[0]["target"]
    assert armed[0]["attacker"] != dropped[0]["attacker"]
