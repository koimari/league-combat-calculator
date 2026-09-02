"""Front-door tests for roster composition primitives.

The coupled timeline keeps its historical behavior tests in
``test_participant_timeline.py``. These tests make the new ownership path
easy to find.
"""

from types import SimpleNamespace

import pytest

from src.calculator import item_effects, roster_composition
from src.calculator.defensive_effects import StartingDefenses
from src.calculator.interpreters.stat_derivation import StatSlot
from src.calculator.item_behavior import EngineLane, KernelField
from src.calculator.pipeline import FightParams
from src.calculator.roster_composition import (
    ActorRequest,
    Combatant,
    actor_params,
    coalesce_darius_q_heals,
    from_loadout,
    main_combatant,
    mana_spent_heal_slot,
    target_overrides,
)
from src.calculator.scenario import ChampionLoadout


@pytest.mark.parametrize(
    "defenses", [SimpleNamespace(magic_shield=0.0), None], ids=["namespace", "none"]
)
def test_a_combatant_refuses_defenses_that_are_not_starting_defenses(defenses):
    """The typed field is enforced where the participant is built.

    Every walk-side consumer reads ``defenses`` by direct attribute, so a
    stand-in would fail deep in the kernel on the first field it lacks; the
    constructor names the participant and the wrong type instead.
    """
    with pytest.raises(
        TypeError, match="ally:Lux: defenses must be a StartingDefenses"
    ):
        Combatant(
            participant_id="ally:Lux",
            team="ally",
            champion_data={"name": "Lux"},
            level=12,
            items=(),
            stats={},
            defenses=defenses,
        )


@pytest.mark.parametrize(
    "request_double",
    [SimpleNamespace(role="mid"), None],
    ids=["namespace", "none"],
)
def test_a_combatant_refuses_a_request_that_is_not_an_actor_request(
    request_double,
):
    """``request`` is read by direct attribute the same way ``defenses`` is.

    A stand-in used to buy every field it did not carry a silent default
    -- an absent ``ability_ranks`` read as no manual allocation, an absent
    ``ally_effects_enabled`` as opted out.
    """
    with pytest.raises(TypeError, match="ally:Lux: request must be an ActorRequest"):
        Combatant(
            participant_id="ally:Lux",
            team="ally",
            champion_data={"name": "Lux"},
            level=12,
            items=(),
            stats={},
            defenses=StartingDefenses(),
            request=request_double,
        )


def test_a_roster_card_and_the_main_params_build_one_request_shape():
    """Both producers emit an ``ActorRequest``; neither invents a type."""
    params = FightParams.from_request(
        {"fight_mode": "one_rotation", "role": "mid"}, deterministic=True
    )
    main = main_combatant(
        {"name": "Ahri"}, 18, [], stats={}, defenses=StartingDefenses(), params=params
    )
    loadout = SimpleNamespace(
        champion_data={"name": "Lux"},
        request=ChampionLoadout(champion="Lux", level=12, ally_effects_enabled=True),
        item_data=(),
        stats={},
        defenses=StartingDefenses(),
    )

    ally = from_loadout("ally:Lux", "ally", loadout)

    assert isinstance(main.request, ActorRequest)
    assert isinstance(ally.request, ActorRequest)
    assert ally.request.ally_effects_enabled is True
    assert main.request.ally_effects_enabled is False
    # ``None`` survives the carrier: an absent option map is the
    # direct-caller default, and an empty one is not the same answer.
    assert main.request.item_options is None
    assert ally.request.item_options == {}


def test_from_loadout_preserves_the_resolved_roster_fields():
    request = ChampionLoadout(champion="Aatrox", level=12)
    loadout = SimpleNamespace(
        champion_data={"name": "Aatrox"},
        request=request,
        item_data=({"name": "Ruby Crystal"},),
        stats={"health": 1200.0},
        defenses=StartingDefenses(),
    )

    actor = from_loadout("enemy:Aatrox", "enemy", loadout)

    assert isinstance(actor, Combatant)
    assert actor.participant_id == "enemy:Aatrox"
    assert actor.team == "enemy"
    assert actor.level == 12
    assert actor.items == loadout.item_data


def test_main_and_actor_params_keep_their_own_request_controls():
    params = FightParams.from_request(
        {
            "fight_mode": "one_rotation",
            "role": "mid",
            "ability_ranks": {"Q": 5},
            "champion_options": {"q_variant": 7},
            "cast_order": ["Q", "W", "E", "R"],
        },
        deterministic=True,
    )
    main = main_combatant(
        {"name": "Ahri"},
        18,
        [],
        stats={},
        defenses=StartingDefenses(),
        params=params,
    )
    roster = Combatant(
        participant_id="ally:Lux",
        team="ally",
        champion_data={"name": "Lux"},
        level=12,
        items=(),
        stats={},
        defenses=StartingDefenses(),
        request=ActorRequest(
            role="support",
            role_quest_complete=True,
            ability_ranks={"Q": 3},
            champion_options={"shield": True},
            cast_order=None,
            item_options={"Moonstone Renewer": {"stacks": 2}},
        ),
    )

    actor_params_result = actor_params(params, roster)

    assert main.participant_id == "main"
    assert main.request.role == "mid"
    assert actor_params_result.role == "support"
    assert actor_params_result.cast_order is None
    assert actor_params_result.ability_ranks == {"Q": 3}


def test_roster_helpers_keep_darius_coalescing_and_catalyst_presence_typed():
    events = {
        "main": [
            {"time": 1.0, "source": "Decimate", "_darius_q_group": (1.0, 2)},
            {"time": 1.0, "source": "Decimate", "_darius_q_group": (1.0, 2)},
        ]
    }

    coalesce_darius_q_heals(events)

    assert len(events["main"]) == 1
    assert events["main"][0]["amount_formula"](500.0, 1000.0) == 170.0
    assert mana_spent_heal_slot([]) is None
    slot = mana_spent_heal_slot([{"name": "Catalyst of Aeons"}])
    assert slot is not None
    assert slot.value("damage_taken_to_mana_ratio") > 0.0


# ── the restore ledger's answer to a late hit ─────────────────────────────


def _catalyst_actor() -> Combatant:
    return Combatant(
        participant_id="main",
        team="ally",
        champion_data={"name": "Ahri"},
        level=18,
        items=[{"name": "Catalyst of Aeons"}],
        stats={},
        defenses=StartingDefenses(),
    )


def _incoming(*times: float) -> dict:
    return {
        "main": [
            {"time": time, "raw_damage": 100.0, "attacker": "enemy:Aatrox"}
            for time in times
        ]
    }


def test_a_hit_past_the_window_is_dropped_rather_than_refusing_the_packet():
    """A late hit is not an unreadable hit.

    The survival walk skips every action past the fight window
    (``outside_window``), damage included, so a restore derived from a
    post-window hit would be mana for damage the fight never takes.  It is
    dropped; refusing the whole packet for it would cap every authored
    ``time_offset`` at the fight length — which is what kept Aatrox's Q
    cadence out (its third strike lands at 8.85s in an eight-second fight).
    """
    restores, complete = roster_composition.resource_restores(
        _catalyst_actor(), _incoming(2.0, 8.85), 8.0
    )

    assert complete is True
    assert [time for time, _amount in restores] == [2.0]


@pytest.mark.parametrize("bad_time", [float("nan"), float("inf"), -1.0])
def test_a_time_the_packet_cannot_state_still_refuses_the_whole_packet(bad_time):
    """The fail-closed check survives, on the cases it was built for."""
    restores, complete = roster_composition.resource_restores(
        _catalyst_actor(), _incoming(2.0, bad_time), 8.0
    )

    assert complete is False
    assert restores == ()


# ── the attack-speed aura, read from the declaration (3.9) ────────────────

AURA_HOLDER = "Frozen Heart"


def _defender(*item_names: str) -> Combatant:
    """A defender carrying only what ``target_overrides`` reads."""
    return Combatant(
        participant_id=f"enemy:{'+'.join(item_names) or 'bare'}",
        team="enemy",
        champion_data={"name": "Malphite"},
        level=13,
        items=tuple({"name": name} for name in item_names),
        stats={"health": 2000.0, "armor": 100.0, "magic_resistance": 50.0},
        defenses=StartingDefenses(
            magic_shield=0.0,
            physical_shield=0.0,
            general_shield=0.0,
            basic_damage_multiplier=1.0,
            basic_damage_flat_reduction=0.0,
            basic_damage_flat_reduction_cap=0.0,
            critical_strike_damage_multiplier=1.0,
            threshold_shield_amount=0.0,
            threshold_shield_health_ratio=0.0,
            threshold_shield_duration=0.0,
            threshold_shield_damage_type="",
            threshold_health_bonus=0.0,
            threshold_health_heal=0.0,
            threshold_health_ratio=0.0,
            threshold_health_duration=0.0,
            revive_health_amount=0.0,
            revive_delay=0.0,
            revive_cooldown=0.0,
        ),
    )


def test_the_attack_speed_cripple_is_the_declared_reduction():
    """The aura's number and the registry key the retired branch read agree.

    The claim of this migration is that the declaration reproduces the hand
    branch exactly, so the assertion is against ``required_effect_value``'s
    own answer rather than against a literal — a literal here would pass on
    the commit that broke the reference.
    """
    reduction = item_effects.required_effect_value(
        AURA_HOLDER, "attack_speed_reduction"
    )

    overrides = target_overrides(_defender(AURA_HOLDER))

    assert overrides["attacker_attack_speed_multiplier"] == pytest.approx(
        1.0 - reduction
    )


def test_a_defender_declaring_no_aura_leaves_the_attacker_alone():
    """No declaration ran, so the multiplier is one — an answer, not a zero."""
    overrides = target_overrides(_defender("Ruby Crystal"))

    assert overrides["attacker_attack_speed_multiplier"] == 1.0


def test_two_declared_attack_speed_auras_stop_rather_than_pick_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R-05's red: nothing declares how two auras of one stat compose.

    Only one item declares a ``StatAuraRule`` today, so the second holder is
    planted — the point is that the composition question is answered by a
    named stop instead of by whichever slot happens to be first.
    """
    real = roster_composition.declared_stat_derivations

    def _two(owners, payload_type):
        slots = real([AURA_HOLDER], payload_type)
        return slots + tuple(
            StatSlot(
                rule=slot.rule,
                fields=tuple(
                    KernelField(
                        name=field.name,
                        value=field.value,
                        lane=EngineLane.STAT_RESOLVER,
                        rule_id=field.rule_id,
                    )
                    for field in slot.fields
                ),
            )
            for slot in slots
        )

    monkeypatch.setattr(roster_composition, "declared_stat_derivations", _two)

    with pytest.raises(ValueError, match="attack-speed aura"):
        target_overrides(_defender(AURA_HOLDER))
