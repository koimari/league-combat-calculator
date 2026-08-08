"""Front-door tests for roster composition primitives.

The coupled timeline keeps its historical behavior tests in
``test_participant_timeline.py``. These tests make the new ownership path
easy to find.
"""

from types import SimpleNamespace

from src.calculator.pipeline import FightParams
from src.calculator.roster_composition import (
    Combatant,
    actor_params,
    coalesce_darius_q_heals,
    from_loadout,
    has_catalyst,
    main_combatant,
)


def test_from_loadout_preserves_the_resolved_roster_fields():
    request = SimpleNamespace(level=12)
    loadout = SimpleNamespace(
        champion_data={"name": "Aatrox"},
        request=request,
        item_data=({"name": "Ruby Crystal"},),
        stats={"health": 1200.0},
        defenses=SimpleNamespace(),
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
            "champion_options": {"sweetspot": True},
            "cast_order": ["Q", "W", "E", "R"],
        },
        deterministic=True,
    )
    main = main_combatant(
        {"name": "Ahri"},
        18,
        [],
        stats={},
        defenses=SimpleNamespace(),
        params=params,
    )
    roster = Combatant(
        participant_id="ally:Lux",
        team="ally",
        champion_data={"name": "Lux"},
        level=12,
        items=(),
        stats={},
        defenses=SimpleNamespace(),
        request=SimpleNamespace(
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
    assert has_catalyst([]) is False
    assert has_catalyst([{"name": "Catalyst of Aeons"}]) is True
