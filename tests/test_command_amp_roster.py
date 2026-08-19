"""Command priced on both sides of one roster, as numbers (criterion 18).

Imperial Mandate's Command is the incident this campaign is named after, and
it is dual-sided: the pair engine prices the holder's own post-immobilize amp
(``damage._apply_command_amp``) and the coupled walk prices every *other*
participant's through the ``Imperial Mandate — Command`` packet, with the
holder carried as ``owner`` so the two halves can never both price him.

Phase 1 makes deleting either half fail on a missing evidence member and
Phase 2 makes emptying its trigger stream fail on a source assertion.  This
file is the number-level half: one roster — a Mandate holder whose E authors
a ``stun``, an ally who does not hold the item, and one enemy — whose totals
are pinned and whose no-Command control totals are different.  Delete
``_apply_command_amp`` and the holder's total falls; drop the coupled packet
and the ally's total falls; either way an arithmetic assertion here is red
before any structural one elsewhere is.

Every pinned total is also re-derived from the control run and Command's own
sourced amp fraction, so a reader can see *why* the number is what it is
rather than trusting a captured constant.

A second roster covers the merge.  Syndra, Pantheon and Aatrox each author at
most one immobilize, so nothing above ever asks what a *second* one does to a
live window; :class:`TestTwoImmobilizesMergeIntoOneRefreshedWindow` is the
Maokai roster that does, on both engines at once.
"""

from functools import lru_cache
from typing import NamedTuple

import pytest

from src import app as app_module
from src.calculator.ability_spec import AttackClass, DamageClass
from src.calculator.champions import parse_champion_abilities
from src.calculator.data_fetcher import get_champion
from src.calculator.interpreters import delta_amp
from src.calculator.item_behavior import AmpChainSlot
from src.calculator.item_behavior_catalog import ACKNOWLEDGED_READING_DIVERGENCES
from src.calculator.stats import calculate_total_stats
from src.calculator.survival.actions import SurvivalAction
from src.calculator.survival.transitions import (
    _apply_cross_participant_modifiers,
    _apply_damage_modifier,
)

# The roster.  Syndra's E is the authored stun (the incident's own marker);
# Pantheon holds nothing, so nothing but Command can move his total between
# the two runs; Aatrox survives the eight-second window at 3490.8 outgoing in
# both runs, so no death cutoff makes the comparison non-linear.
HOLDER = "Syndra"
ALLY = "Pantheon"
ENEMY = "Aatrox"
COMMAND_ITEM = "Imperial Mandate"

# Measured on this roster with Command live.  The holder's figure carries
# Mandate's stats as well as its amp — the control is the same roster without
# the item — while the ally's carries the amp alone, which is why the ally's
# delta is re-derived exactly below and the holder's is re-derived from the
# pair engine's own amplification row.
EXPECTED_HOLDER_TOTAL = 1334.7
EXPECTED_ALLY_TOTAL = 838.3
NO_COMMAND_HOLDER_TOTAL = 956.9
NO_COMMAND_ALLY_TOTAL = 824.6

# The pair engine's amplification row for the holder's own fight.
COMMAND_ROW = f"damage_amp_{COMMAND_ITEM}"

# One-decimal payload rounding, applied twice (per event and per total), is
# the only reason a re-derivation and a pinned total are not bit-equal.
ROUNDING = 0.1


@lru_cache(maxsize=4)
def _roster(items, holder=HOLDER, ally=ALLY):
    """One roster response through the public request path."""
    app_module.app.config["TESTING"] = True
    payload = {
        "champion": holder,
        "level": 18,
        "items": list(items),
        "fight_mode": "time_based",
        "fight_duration": 8,
        "include_auto_attacks": False,
        "enemies": [{"champion": ENEMY, "level": 18, "items": []}],
        "allies": [
            {
                "champion": ally,
                "level": 18,
                "items": [],
                "ally_effects_enabled": True,
            }
        ],
    }
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_data(as_text=True)[:400]
    return response.get_json()


def with_command():
    """The roster holding Imperial Mandate."""
    return _roster((COMMAND_ITEM,))


def no_command():
    """The same roster with nothing held — the control."""
    return _roster(())


class _CommandNumbers(NamedTuple):
    """Command's sourced amp fraction and window, read off its declaration."""

    amp_fraction: float
    duration: float


def _command_effect() -> _CommandNumbers:
    """Command's sourced amp fraction and window, from its declared rule.

    Both numbers used to arrive through a bespoke ``item_effects`` accessor.
    They now arrive through the ``imperial_mandate.command`` declaration and
    its ``ValueRef``s into ``ALLY_ITEM_EFFECTS`` — one home for the number,
    one home for the shape.
    """
    slot = delta_amp.resolve_slot(
        [COMMAND_ITEM],
        AmpChainSlot.POST_IMMOBILIZE,
        level=18,
        fight_duration_seconds=8.0,
        target_bonus_health=0.0,
        holder_is_melee=True,
    )
    assert slot is not None, "the roster fixture needs Command's declared rule"
    return _CommandNumbers(
        amp_fraction=slot.bonus_fraction,
        duration=slot.value(delta_amp.WINDOW_DURATION_FIELD),
    )


def _outgoing(response, participant_id):
    """One participant's coupled outgoing total."""
    row = next(
        row
        for row in response["combat"]["breakdown"]
        if row["participant_id"] == participant_id
    )
    return row["total_damage"]


def _windowed_damage(response, attacker, *, start, end):
    """An attacker's damage landing strictly after *start* and by *end*.

    Amplification delta rows are excluded: they are the amp, not the damage
    the amp is a fraction of.
    """
    return sum(
        event["damage"]
        for event in response["combat"]["events"]
        if event["attacker"] == attacker
        and not str(event["source"]).startswith("damage_amp_")
        and start < event["time"] <= end
    )


class TestTheRosterAuthorsTheMarkerCommandNeeds:
    """The fixture is only a fixture if its precondition holds."""

    def test_the_holder_authors_a_stun(self):
        champion = get_champion(HOLDER)
        stats = calculate_total_stats(champion, 18, [])
        abilities = parse_champion_abilities(
            champion,
            18,
            stats["ability_power"],
            champion_stats=stats,
            target_stats={
                "target_max_health": 1000.0,
                "target_current_health": 1000.0,
                "target_missing_health": 0.0,
            },
        )
        assert [part.cc_kind for part in abilities["E"]["parts"]] == ["stun"]

    def test_the_walk_arms_command_against_the_enemy(self):
        packets = [
            event
            for event in with_command()["combat"]["support_events"]
            if event["source"].startswith(f"{COMMAND_ITEM} — Command")
        ]
        assert len(packets) == 1
        assert packets[0]["attacker"] == "main"
        assert packets[0]["target"] == f"enemy:{ENEMY}"
        assert packets[0]["applied_amount"] == pytest.approx(
            _command_effect().amp_fraction
        )

    def test_the_control_arms_nothing(self):
        assert no_command()["combat"]["support_events"] == []

    def test_the_enemy_survives_both_runs_so_the_comparison_is_linear(self):
        """No death cutoff between the two totals being subtracted."""
        assert _outgoing(with_command(), f"enemy:{ENEMY}") == _outgoing(
            no_command(), f"enemy:{ENEMY}"
        )


class TestDeletingThePairSidePricerFailsOnANumber:
    """``damage._apply_command_amp`` — the holder's own half."""

    def test_the_holder_total_is_pinned_and_differs_from_the_control(self):
        holder = _outgoing(with_command(), "main")
        assert holder == pytest.approx(EXPECTED_HOLDER_TOTAL)
        assert _outgoing(no_command(), "main") == pytest.approx(NO_COMMAND_HOLDER_TOTAL)
        assert holder != pytest.approx(NO_COMMAND_HOLDER_TOTAL), (
            "criterion 18: the Mandate roster's holder total now equals its "
            "no-Command control, so the pair-side pricer has stopped pricing."
        )

    def test_the_amplification_row_is_the_sourced_fraction_of_its_window(self):
        """The re-derivation: 7% of the holder's damage inside the window."""
        response = with_command()
        effect = _command_effect()
        row = response["breakdown"][COMMAND_ROW]
        windowed = _windowed_damage(response, "main", start=0.0, end=effect.duration)
        assert windowed > 0.0
        assert row["total_damage"] == pytest.approx(
            windowed * effect.amp_fraction, abs=ROUNDING
        )

    def test_the_holder_total_carries_the_amplification_row(self):
        """Deleting the row and deleting the amp are the same number."""
        response = with_command()
        row = response["breakdown"][COMMAND_ROW]["total_damage"]
        assert row > 0.0
        priced = sum(
            entry["total_damage"]
            for key, entry in response["breakdown"].items()
            if key != COMMAND_ROW
        )
        assert _outgoing(response, "main") == pytest.approx(priced + row, abs=ROUNDING)
        assert priced == pytest.approx(EXPECTED_HOLDER_TOTAL - row, abs=ROUNDING)


class TestDroppingTheCoupledPricerFailsOnANumber:
    """The ``Imperial Mandate — Command`` packet — everyone else's half.

    The ally holds nothing and gains nothing from the holder's item stats, so
    the whole difference between his two totals is the walk's amp.  That
    makes his delta the clean instrument: it is re-derived exactly, from the
    control run's own events and Command's sourced fraction and window.
    """

    def test_the_ally_total_is_pinned_and_differs_from_the_control(self):
        ally = _outgoing(with_command(), f"ally:{ALLY}")
        assert ally == pytest.approx(EXPECTED_ALLY_TOTAL)
        assert _outgoing(no_command(), f"ally:{ALLY}") == pytest.approx(
            NO_COMMAND_ALLY_TOTAL
        )
        assert ally != pytest.approx(NO_COMMAND_ALLY_TOTAL), (
            "criterion 18: an ally who holds no Mandate now deals exactly "
            "what he deals without one, so the coupled packet has stopped "
            "reaching him — the incident, at the number."
        )

    def test_the_ally_delta_is_the_sourced_fraction_of_his_windowed_damage(self):
        effect = _command_effect()
        control = no_command()
        windowed = _windowed_damage(
            control, f"ally:{ALLY}", start=0.0, end=effect.duration
        )
        assert windowed > 0.0
        expected = NO_COMMAND_ALLY_TOTAL + windowed * effect.amp_fraction
        assert _outgoing(with_command(), f"ally:{ALLY}") == pytest.approx(
            expected, abs=ROUNDING
        )

    def test_the_holder_is_not_amped_twice(self):
        """The ``owner`` handshake: the walk skips the half the pair priced.

        The holder's coupled total is exactly the pair engine's own total,
        amplification row included, so the walk added no second 7%.
        """
        response = with_command()
        pair_total = sum(
            entry["total_damage"] for entry in response["breakdown"].values()
        )
        assert _outgoing(response, "main") == pytest.approx(pair_total, abs=ROUNDING)


# ---------------------------------------------------------------------------
# The merge — two immobilizes inside one window
# ---------------------------------------------------------------------------

# Maokai authors two immobilizes a quarter-second apart: W (Twisted Advance)
# roots at 0.3 and R (Nature's Grasp) roots at 0.55, so the second lands with
# 3.75 s left on the first one's mark.  Everything else about the roster is the
# fixture above's: level 18, eight seconds, no ambient autos, one enemy.
MERGE_HOLDER = "Maokai"
# The ally is chosen for having no immobilize of his own and real damage inside
# the merged window — his delta is the walk half's clean instrument, and a
# second CC author would make it ambiguous whose mark priced it.
MERGE_ALLY = "Ezreal"

# Measured on this roster.  The holder's figure carries Mandate's stats as well
# as its amp; the ally's carries the amp alone.
MERGE_HOLDER_TOTAL = 1008.0
MERGE_ALLY_TOTAL = 1411.6
NO_MERGE_HOLDER_TOTAL = 884.5
NO_MERGE_ALLY_TOTAL = 1359.5

# The two triggers, and the one window they leave behind.  ``REFRESH`` moves
# the mark's expiry to the *last* immobilize plus one duration; the additive
# reading would leave it at the first expiry plus another duration.
FIRST_TRIGGER = 0.3
SECOND_TRIGGER = 0.55
REFRESHED_EXPIRY = 4.55
FIRST_EXPIRY = 4.3
ADDITIVE_EXPIRY = FIRST_EXPIRY + 4.0


def merged():
    """The merge roster holding Imperial Mandate."""
    return _roster((COMMAND_ITEM,), MERGE_HOLDER, MERGE_ALLY)


def no_merge():
    """The same roster with nothing held — the control."""
    return _roster((), MERGE_HOLDER, MERGE_ALLY)


def _command_packets(response):
    """The walk's Command packets, in emission order."""
    return [
        event
        for event in response["combat"]["support_events"]
        if str(event["source"]).startswith(f"{COMMAND_ITEM} — Command")
    ]


class _RecordingLedger:
    """A walk context whose ledger keeps what was written to it."""

    def __init__(self):
        self.written = []
        self.ledger = self
        self.combatants = ()
        self.states = []

    def write(self, action, **fields):  # pylint: disable=unused-argument
        """Keep the receipt fields."""
        self.written.append(fields)

    def skip(self, action, reason):  # pylint: disable=unused-argument
        """Keep the refusal."""
        self.written.append({"skip": reason})


class TestTwoImmobilizesMergeIntoOneRefreshedWindow:
    """One mark, refreshed — the merge, priced on both engines.

    **The oracle.**  The League Wiki's Imperial Mandate page says
    "Subsequent immobilizes against a target extend the duration of the
    effect".  Riot's own sources say no such thing: the in-client tooltip
    (CommunityDragon ``items.json`` id 4005) reads only "mark them as 7%
    Vulnerable for 4 seconds", and ``items.cdtb.bin.json`` ``Items/4005``
    carries ``DamageAmp 0.07`` and ``DamageAmpDuration 4.0`` with no merge
    script at all.  So the sources rule out a second stacking 7% and leave
    refresh-versus-additive open, and the declaration ships the conservative
    reading — ``merge=REFRESH``, filed with its open alternative in
    ``item_behavior_catalog.ACKNOWLEDGED_READING_DIVERGENCES``.

    This class is what that ruling has to satisfy, and what the additive
    reading would have to break to land.  It replaces the Phase 0 sentinel
    that asserted no authored pair could merge: that fact stopped being true
    when the champion corpus grew, and the sentinel's own message asked for
    exactly this — "give it a fixture and an oracle receipt before landing
    it".
    """

    def test_the_holder_authors_two_immobilizes_inside_one_duration(self):
        """The precondition: without it every assertion below is vacuous."""
        packets = _command_packets(merged())
        assert [packet["time"] for packet in packets] == [
            FIRST_TRIGGER,
            SECOND_TRIGGER,
        ], (
            "the merge fixture needs two immobilizes closer together than "
            "Command's window; this roster no longer authors them"
        )
        duration = _command_effect().duration
        assert SECOND_TRIGGER - FIRST_TRIGGER < duration
        assert [packet["expires_at"] for packet in packets] == [
            FIRST_EXPIRY,
            REFRESHED_EXPIRY,
        ]
        assert REFRESHED_EXPIRY == pytest.approx(SECOND_TRIGGER + duration), (
            "REFRESH: the surviving expiry is the *last* trigger plus one "
            "duration, not the first expiry plus another"
        )

    def test_the_enemy_survives_both_runs_so_the_comparison_is_linear(self):
        assert _outgoing(merged(), f"enemy:{ENEMY}") == _outgoing(
            no_merge(), f"enemy:{ENEMY}"
        )

    def test_the_pair_row_is_the_fraction_of_one_merged_window(self):
        """One row over one window — not two rows, and not a doubled one."""
        response = merged()
        effect = _command_effect()
        windowed = _windowed_damage(
            response, "main", start=FIRST_TRIGGER, end=REFRESHED_EXPIRY
        )
        assert windowed > 0.0
        row = response["breakdown"][COMMAND_ROW]
        assert row["total_damage"] == pytest.approx(
            windowed * effect.amp_fraction, abs=ROUNDING
        )
        assert _outgoing(response, "main") == pytest.approx(
            MERGE_HOLDER_TOTAL, abs=ROUNDING
        )
        assert _outgoing(no_merge(), "main") == pytest.approx(
            NO_MERGE_HOLDER_TOTAL, abs=ROUNDING
        )

    def test_the_second_trigger_neither_stacks_the_amp_nor_opens_a_row(self):
        """Two triggers, one row, one fraction — the two rejected readings."""
        response = merged()
        effect = _command_effect()
        rows = [key for key in response["breakdown"] if key.startswith("damage_amp_")]
        assert rows == [COMMAND_ROW]
        windowed = _windowed_damage(
            response, "main", start=FIRST_TRIGGER, end=REFRESHED_EXPIRY
        )
        stacked = windowed * ((1.0 + effect.amp_fraction) ** 2 - 1.0)
        assert response["breakdown"][COMMAND_ROW]["total_damage"] != pytest.approx(
            stacked, abs=ROUNDING
        ), "a second immobilize must not compound the amp (1.07 squared)"

    def test_the_walk_keeps_one_modifier_and_receipts_the_refresh(self):
        """The walk half: the second packet refreshes rather than arming.

        Driven with the two packets the roster above actually emitted, so the
        walk's arming is tested against the fixture's own numbers and not
        against a hand-written pair.
        """
        packets = _command_packets(merged())
        context = _RecordingLedger()
        armed: list[dict] = []
        state = {"active_damage_modifiers": armed}
        for packet in packets:
            _apply_damage_modifier(
                context,
                SurvivalAction(
                    source=packet["source"],
                    holder=0,
                    attacker=-1,
                    time=packet["time"],
                    duration=packet["duration"],
                    multiplier=packet["multiplier"],
                    amount=packet["amount"],
                    damage_classes=frozenset(DamageClass),
                    attack_classes=frozenset(AttackClass),
                ),
                state,
            )

        assert len(armed) == 1, (
            "two immobilizes armed two modifiers; every packet inside the "
            "overlap would then be multiplied twice"
        )
        assert armed[0]["until"] == pytest.approx(REFRESHED_EXPIRY)
        assert armed[0]["multiplier"] == pytest.approx(
            1.0 + _command_effect().amp_fraction
        )
        assert [
            fields["refresh"] for fields in context.written if "refresh" in fields
        ] == [
            {
                "reason": "refresh",
                "source": f"{COMMAND_ITEM} — Command",
                "previous_expires_at": FIRST_EXPIRY,
            }
        ]

    def test_a_packet_inside_the_overlap_is_amped_once(self):
        """1.07, never 1.1449 — the double count the refresh exists to stop."""
        packets = _command_packets(merged())
        context = _RecordingLedger()
        state = {"active_damage_modifiers": []}
        for packet in packets:
            _apply_damage_modifier(
                context,
                SurvivalAction(
                    source=packet["source"],
                    holder=0,
                    attacker=-1,
                    time=packet["time"],
                    duration=packet["duration"],
                    multiplier=packet["multiplier"],
                    amount=packet["amount"],
                    damage_classes=frozenset(DamageClass),
                    attack_classes=frozenset(AttackClass),
                ),
                state,
            )
        fraction = _command_effect().amp_fraction
        priced = _apply_cross_participant_modifiers(
            _RecordingLedger(),
            SurvivalAction(
                damage_type="magic",
                is_ability=True,
                time=(FIRST_TRIGGER + REFRESHED_EXPIRY) / 2.0,
                attacker=-1,
            ),
            state,
            100.0,
        )
        assert priced == pytest.approx(100.0 * (1.0 + fraction))
        assert priced != pytest.approx(100.0 * (1.0 + fraction) ** 2)

    def test_the_ally_delta_is_the_merged_window_and_prices_the_other_reading(self):
        """The costed half of the divergence, re-measured rather than quoted.

        The ally holds nothing, so his whole delta is the walk's amp.  Priced
        over the shipped ``REFRESH`` window it matches to the payload's own
        rounding; priced over the window the Wiki's "extend the duration"
        wording would open it does not, and the gap between the two is what
        the additive reading would cost on this roster.
        """
        effect = _command_effect()
        control = no_merge()
        participant = f"ally:{MERGE_ALLY}"
        assert _outgoing(control, participant) == pytest.approx(
            NO_MERGE_ALLY_TOTAL, abs=ROUNDING
        )

        refreshed = _windowed_damage(
            control, participant, start=FIRST_TRIGGER, end=REFRESHED_EXPIRY
        )
        additive = _windowed_damage(
            control, participant, start=FIRST_TRIGGER, end=ADDITIVE_EXPIRY
        )
        assert refreshed > 0.0
        assert additive > refreshed, (
            "the two readings are indistinguishable on this roster, so it "
            "cannot price the divergence it is cited for"
        )

        measured = _outgoing(merged(), participant)
        assert measured == pytest.approx(MERGE_ALLY_TOTAL, abs=ROUNDING)
        assert measured == pytest.approx(
            NO_MERGE_ALLY_TOTAL + refreshed * effect.amp_fraction, abs=ROUNDING
        )
        assert measured != pytest.approx(
            NO_MERGE_ALLY_TOTAL + additive * effect.amp_fraction, abs=ROUNDING
        )
        exposure = (additive - refreshed) * effect.amp_fraction
        assert exposure > ROUNDING, (
            "the priced exposure of the additive reading collapsed to nothing; "
            "if that is real the divergence is settled and its entry in "
            "ACKNOWLEDGED_READING_DIVERGENCES should say so"
        )

    def test_the_divergence_is_declared_and_names_this_gate(self):
        """The note and the fixture point at each other, or neither is a home."""
        note = ACKNOWLEDGED_READING_DIVERGENCES["imperial_mandate.command"]
        assert "test_command_amp_roster" in note
        assert "extend the duration of the effect" in note
