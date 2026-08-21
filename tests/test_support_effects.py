"""Fail-closed timestamp contracts for ally support packets."""

import math

import pytest

from src.calculator.data_fetcher import get_champion
from src.calculator.support_effects import _support_profile, derive_ally_effects


def _sona_effects(cast_timeline):
    return derive_ally_effects(
        get_champion("Sona"),
        18,
        {"ability_power": 0.0},
        cast_timeline,
    )


def test_support_packet_preserves_sourced_cast_time():
    effects = _sona_effects([{"slot": "W", "time": 2.5}])

    assert effects
    assert {effect["time"] for effect in effects} == {2.5}


def test_self_granted_shield_targets_the_caster_without_a_teammate():
    effects = derive_ally_effects(
        get_champion("Annie"),
        12,
        {"ability_power": 0.0},
        [{"slot": "E", "time": 0.0}],
    )

    assert effects == [
        {
            "time": 0.0,
            "kind": "shield",
            "amount": 60.0,
            "source": "Molten Shield · Shield Strength",
            "slot": "E",
            "target_self": True,
            "target_scope": "one_teammate",
            "rank": 1,
        }
    ]


@pytest.mark.parametrize(
    ("champion", "slot"),
    [("Janna", "E"), ("Milio", "E"), ("Zilean", "R")],
)
def test_self_or_target_support_packets_mark_caster_scope(champion, slot):
    ability = get_champion(champion)["abilities"][slot][0]

    _shield, _heal, target_self, target_scope, _prose = _support_profile(ability)

    assert target_self is True
    assert target_scope == "one_teammate"


@pytest.mark.parametrize("bad_time", [None, "unknown", True, math.inf, -math.inf])
def test_support_packet_missing_or_invalid_cast_time_fails_closed(bad_time):
    cast = {"slot": "W"}
    if bad_time is not None:
        cast["time"] = bad_time

    with pytest.raises(
        ValueError, match="Support cast W time|missing its sourced time"
    ):
        _sona_effects([cast])


def test_prose_that_grants_only_the_caster_never_targets_a_teammate():
    """Rumble W: "grant himself a shield" is a self grant, not an ally packet.

    The scanner's self markers were inflected verb forms ("grants himself",
    "granting himself"), so the wiki's bare infinitive fell through to the
    one-teammate default and published Scrap Shield to a teammate.  The rule
    is now the sentence, not the conjugation: the row that declares the
    shield names the caster and no ally.
    """
    effects = derive_ally_effects(
        get_champion("Rumble"),
        18,
        {"ability_power": 100.0, "max_health": 2000.0},
        [{"slot": "W", "time": 0.0}],
    )

    assert [
        (
            effect["kind"],
            effect["amount"],
            effect["target_scope"],
            effect["target_self"],
        )
        for effect in effects
    ] == [("shield", 175.0, "self", True)]


@pytest.mark.parametrize(
    ("champion", "slot", "row"),
    [
        # The Potential Shield "decays by 8 : 25 (based on level) every
        # second"; the wiki template still names that row ``Heal``.
        ("Mordekaiser", "W", "Indestructible"),
        # The lightning strikes "deal a minimum of 40 : 174.12 (based on
        # level) against minions" — the sentence's last unlabelled row.
        ("Udyr", "Q", "Wilding Claw"),
    ],
)
def test_a_heal_named_row_whose_sentence_states_no_heal_is_refused(champion, slot, row):
    effects = derive_ally_effects(
        get_champion(champion),
        18,
        {"ability_power": 100.0, "max_health": 2000.0, "bonus_attack_damage": 50.0},
        [{"slot": slot, "time": 0.0}],
    )

    assert not [effect for effect in effects if effect["kind"] == "heal"], row


def test_sivir_spell_shield_heals_only_sivir():
    """ "she heals herself and activates Fleet of Foot" — the "and" is a verb.

    The ability-wide scope read "<pronoun> and" as a second recipient and
    scoped the heal ``self_and_one_teammate``; the declaring sentence names
    no ally, so the packet is the caster's alone.
    """
    effects = derive_ally_effects(
        get_champion("Sivir"),
        18,
        {"ability_power": 100.0},
        [{"slot": "E", "time": 0.0}],
    )

    assert [(effect["kind"], effect["target_scope"]) for effect in effects] == [
        ("heal", "self")
    ]
