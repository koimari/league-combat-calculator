"""Fail-closed timestamp contracts for ally support packets."""

import math

import pytest

from src.calculator.data_fetcher import get_champion
from src.calculator import support_effects
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


def test_morgana_black_shield_uses_typed_magic_pool_and_duration_atoms():
    effects = derive_ally_effects(
        get_champion("Morgana"),
        18,
        {"ability_power": 50.0},
        [{"slot": "E", "time": 1.25}],
        {"E": 5},
    )

    assert len(effects) == 1
    shield = effects[0]
    assert shield["amount"] == pytest.approx(355.0)
    assert shield["duration"] == pytest.approx(5.0)
    assert shield["shield_pool"] == "magic"
    assert shield["crowd_control_immunity_while_shield"] is True
    assert shield["target_selection_key"] == "shield:E:0"
    assert shield["source_atom"]["hash"] == "797fffe3046f726e"
    assert shield["duration_atom"]["hash"] == "106f001ee676d9f2"


@pytest.mark.parametrize(
    ("champion", "slot", "duration", "effect_index"),
    [
        ("Jarvan IV", "W", 4.0, 1),
        ("Olaf", "W", 2.5, 1),
        ("Renata Glasc", "E", 3.0, 1),
        ("Thresh", "W", 4.0, 1),
    ],
)
def test_support_shield_duration_uses_the_typed_shield_sentence(
    champion, slot, duration, effect_index
):
    effects = derive_ally_effects(
        get_champion(champion),
        18,
        {"ability_power": 0.0, "bonus_attack_damage": 0.0},
        [{"slot": slot, "time": 1.0}],
    )

    shield = next(effect for effect in effects if effect["kind"] == "shield")
    assert shield["duration"] == pytest.approx(duration)
    assert shield["duration_atom"]["atom_id"] == "timing.shield_duration"
    assert shield["duration_atom"]["source"].endswith(
        f".effects[{effect_index}].description"
    )


def test_taric_bastion_uses_the_protected_units_max_health_atom():
    """A recipient-scaled row is narrowed to the caster and PRICED.

    Ruling: a sourced non-zero number beats a zero-plus-formula row.  Bastion
    is "11% of target's maximum health" at rank 5, and the one recipient a
    scan holds stats for is the caster — so the row is published at the
    caster's own 2000 maximum health rather than as a 0.0 placeholder for the
    walk to fill in.  The formula and its atom still ride the row, which is
    what keeps per-recipient pricing (the deferred follow-up) a re-read of
    this receipt rather than a re-derivation.
    """
    effects = derive_ally_effects(
        get_champion("Taric"),
        18,
        {"ability_power": 0.0, "bonus_attack_damage": 0.0, "health": 2000.0},
        [{"slot": "W", "time": 1.0}],
        {"W": 5},
    )

    shield = effects[0]
    assert shield["amount"] == pytest.approx(220.0)
    assert shield["amount_formula"](0.0, 2000.0) == pytest.approx(220.0)
    assert shield["amount_formula"](0.0, 2500.0) == pytest.approx(275.0)
    assert shield["amount_formula_atom"]["source"] == (
        "Taric.W[0].effects[1].leveling[0].modifiers[0]"
    )
    assert shield["duration"] == pytest.approx(2.5)


def test_taric_cosmic_radiance_emits_a_delayed_typed_state_packet():
    effects = derive_ally_effects(
        get_champion("Taric"),
        18,
        {"ability_power": 0.0},
        [{"slot": "R", "time": 1.0}],
        {"R": 3},
    )

    assert len(effects) == 1
    state = effects[0]
    assert state["time"] == pytest.approx(3.5)
    assert state["kind"] == "invulnerability"
    assert state["duration"] == pytest.approx(2.5)
    assert state["activation_delay"] == pytest.approx(2.5)
    assert state["target_self"] is True
    assert state["target_scope"] == "self_and_all_teammates"
    assert state["target_selection_key"] == "state:R:0"
    assert state["activation_delay_atom"]["atom_id"] == ("timing.invulnerability_delay")
    assert state["duration_atom"]["atom_id"] == ("timing.invulnerability_duration")
    assert state["activation_delay_atom"]["source"] == (
        "Taric.R[0].effects[0].description"
    )


def test_seraphine_surround_sound_publishes_only_the_priced_caster_shield():
    """The same ruling, applied to a row the caster's stats cannot price.

    Surround Sound's pulse heals off the RECIPIENT's *missing* health, and
    missing health is not a scan-time fact for anybody — not even the caster.
    So narrowing to the caster prices it at nothing, and a sourced zero
    beats no row only when the zero is measured: here it is a refusal.  The
    cast still publishes its sourced caster shield, and that row carries the
    atom receipt.  Per-recipient pricing is the deferred follow-up.
    """
    effects = derive_ally_effects(
        get_champion("Seraphine"),
        18,
        {"ability_power": 0.0},
        [{"slot": "W", "time": 1.0}],
        {"W": 5},
    )

    assert [effect["kind"] for effect in effects] == ["shield"]
    shield = effects[0]
    assert shield["time"] == pytest.approx(1.0)
    assert shield["amount"] == pytest.approx(140.0)
    assert shield["duration"] == pytest.approx(2.5)
    assert shield["duration_atom"]["source"] == "Seraphine.W[0].effects[0].description"


def test_seraphine_first_pulse_option_resurrects_no_zero_row():
    """``w_already_shielded`` gates a pulse that is refused either way.

    Pinned because the option's only job was to drop the shield gate on a
    zero-amount heal row, and a refused row must not come back as a zero one
    when the gate is assumed away.
    """
    effects = derive_ally_effects(
        get_champion("Seraphine"),
        18,
        {"ability_power": 0.0},
        [{"slot": "W", "time": 1.0}],
        {"W": 5},
        champion_options={"w_already_shielded": True},
    )

    assert [effect["kind"] for effect in effects] == ["shield"]


@pytest.mark.parametrize(
    ("champion", "slot", "scope"),
    [
        ("Ekko", "W", "self"),
        ("K'Sante", "E", "one_teammate"),
        ("Kassadin", "Q", "self"),
        ("Lee Sin", "W", "self_and_one_teammate"),
        ("Rumble", "W", "self"),
    ],
)
def test_reviewed_self_or_ally_shields_expose_their_target_scope(champion, slot, scope):
    effects = derive_ally_effects(
        get_champion(champion),
        18,
        {"ability_power": 0.0, "bonus_attack_damage": 0.0, "health": 2000.0},
        [{"slot": slot, "time": 1.0}],
        {slot: 5},
    )

    shield = next(effect for effect in effects if effect["kind"] == "shield")
    assert shield["target_scope"] == scope


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
            "target_selection_key": "shield:E:0",
            "duration": 3.0,
            "duration_atom": {
                "atom_id": "timing.active_duration",
                "behavior": "timing",
                "source": "Annie.E[0].effects[0].description",
                "values": [3.0],
                "units": ["s"],
                "evidence": ["active duration@effects[0].description"],
                "hash": "cf4f073d11dc6fc7",
            },
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
        (effect["kind"], effect["amount"], effect["target_scope"]) for effect in effects
    ] == [("shield", 175.0, "self")]


def test_a_self_scoped_row_flags_itself_as_a_self_grant():
    """A ``self`` scope override carries the self flag with it: the pair
    ``scope="self"`` / ``target_self=False`` is unreachable through the
    ordinary path, and the roster resolver's teammate-less branch reads
    the flag, so it used to drop the shield in a solo fight."""
    effects = derive_ally_effects(
        get_champion("Rumble"),
        18,
        {"ability_power": 100.0, "max_health": 2000.0},
        [{"slot": "W", "time": 0.0}],
    )

    assert [effect["target_self"] for effect in effects] == [True]


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
    """ "she heals herself and activates Fleet of Foot" â the "and" is a verb.

    The declaring sentence names no ally, so the packet is the caster's
    alone.  MERGE: the scanner no longer publishes it at all, and that is
    the more capable answer.  The wiki gates the heal on a successful
    block â "Upon successfully blocking a hostile effect, she heals
    herself" â which a scanner row cannot express: it would pay at the
    cast whether or not anything was blocked.  So ``("Sivir", "E")`` is a
    declared ``_STATE_AUTHORED_HEAL_SLOTS`` member and the champion module
    authors the heal on its spell-shield state instead, where the block is
    the occasion that pays it.
    """
    effects = derive_ally_effects(
        get_champion("Sivir"),
        18,
        {"ability_power": 100.0},
        [{"slot": "E", "time": 0.0}],
    )

    assert effects == [], "the scanner defers Sivir E to the module"
    assert ("Sivir", "E") in support_effects._STATE_AUTHORED_HEAL_SLOTS

    # The heal it defers to: the module's own spell-shield state, paid on
    # a block, scoped to Sivir and to nobody else.
    from src.calculator.champions import sivir as sivir_module

    entry = sivir_module.parse_abilities(
        get_champion("Sivir"),
        18,
        100.0,
        ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
        champion_options={},
    )["E"]
    (state,) = entry["self_state_events"]
    assert state["kind"] == "spell_shield"
    assert state["on_block_heal_amount"] > 0.0
    assert state["on_block_heal_source"] == "Spell Shield · Heal"
