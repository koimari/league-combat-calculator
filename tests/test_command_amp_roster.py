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
"""

from functools import lru_cache

import pytest

from src import app as app_module
from src.calculator import item_effects
from src.calculator.champions import parse_champion_abilities
from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.stats import calculate_total_stats

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


@lru_cache(maxsize=2)
def _roster(items):
    """One roster response through the public request path."""
    app_module.app.config["TESTING"] = True
    payload = {
        "champion": HOLDER,
        "level": 18,
        "items": list(items),
        "fight_mode": "time_based",
        "fight_duration": 8,
        "include_auto_attacks": False,
        "enemies": [{"champion": ENEMY, "level": 18, "items": []}],
        "allies": [
            {
                "champion": ALLY,
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


def _command_effect():
    """Command's sourced amp fraction and window, from ``item_effects``."""
    effect = item_effects.command_amp_effect([get_item_by_name(COMMAND_ITEM)])
    assert effect is not None, "the roster fixture needs Command's sourced values"
    return effect


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
