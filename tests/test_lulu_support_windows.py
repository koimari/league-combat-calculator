"""Lulu grants apply to one recipient and expire at their source boundaries."""

import pytest

from src.calculator.binary_roots import (
    calculation_coefficient,
    data_value,
    spell_object,
)
from src.calculator.champions.lulu_events import derive_lulu_support_events
from src.calculator.champions.slotlib import extract_named, extract_value
from src.calculator.data_fetcher import get_champion
from src.calculator.defensive_effects import StartingDefenses
from src.calculator.participant_timeline import Combatant, _simulate_survival
from src.calculator.program.build import roster_program
from src.calculator.program.views.survival import survival
from src.calculator.shield_ledger import ShieldPools
from src.calculator.survival.transitions import (
    expire_support_buffs,
    expire_temporary_health,
    grant_temporary_health,
)


def _actor(name, team):
    return Combatant(
        participant_id=name,
        team=team,
        champion_data={"name": name},
        level=1,
        items=(),
        stats={"health": 1000.0},
        defenses=StartingDefenses(),
    )


def _rows(actors, incoming, support, duration):
    return survival(
        roster_program(actors),
        _simulate_survival(actors, incoming, {}, support, duration),
    )


def test_lulu_window_values_follow_rank_ap_and_binary_duration():
    champion = get_champion("Lulu")
    for rank, ap in [(1, 0.0), (3, 200.0)]:
        stats = {"ability_power": ap}
        rows = derive_lulu_support_events(
            champion,
            18,
            stats,
            [{"slot": "W", "time": 2.0}, {"slot": "R", "time": 4.0}],
            ability_ranks={"W": rank, "R": rank},
        )
        whimsy, growth = rows
        assert whimsy["time"] == 2.0
        assert whimsy["bonus_attack_speed_percent"] == extract_value(
            champion["abilities"]["W"][0], "Bonus Attack Speed", rank
        )
        spell = spell_object("Lulu", "LuluW")
        assert whimsy["bonus_move_speed_percent"] == 100 * (
            data_value(spell, "BaseMS") + calculation_coefficient(spell, "TotalMS") * ap
        )
        assert growth["amount"] == extract_named(
            champion["abilities"]["R"][0], "Bonus Health", rank, stats, {}
        )
        assert growth["duration"] == data_value(
            spell_object("Lulu", "LuluR"), "BuffDuration"
        )
        assert growth["kind"] == "temporary_health"


def test_lulu_unranked_cast_has_no_grant():
    assert (
        derive_lulu_support_events(
            get_champion("Lulu"),
            1,
            {"ability_power": 0.0},
            [{"slot": "R", "time": 0.0}],
            ability_ranks={"R": 0},
        )
        == []
    )


@pytest.mark.parametrize("recipient", ["caster", "ally"])
def test_whimsy_records_only_the_recipients_live_stat_window(recipient):
    actors = [_actor("caster", "main"), _actor("ally", "ally")]
    grant = derive_lulu_support_events(
        get_champion("Lulu"), 18, {"ability_power": 200.0}, [{"slot": "W", "time": 2.0}]
    )[0]
    grant.update(attacker="caster", cast_blocked_by_attacker_control=True)
    walk = _simulate_survival(actors, {}, {}, {recipient: [dict(grant)]}, 5.0)
    recipient_index = 0 if recipient == "caster" else 1
    buff = walk.states[recipient_index]["support_buffs"][0]
    assert buff["from"] == 2.0
    assert buff["until"] == 6.0
    assert buff["bonus_attack_speed_percent"] == grant["bonus_attack_speed_percent"]
    assert buff["bonus_move_speed_percent"] == grant["bonus_move_speed_percent"]
    assert walk.states[1 - recipient_index]["support_buffs"] == []
    expired = _simulate_survival(actors, {}, {}, {recipient: [dict(grant)]}, 6.0)
    assert expired.states[recipient_index]["support_buffs"] == []


@pytest.mark.parametrize("recipient", ["caster", "ally"])
def test_wild_growth_changes_only_selected_recipient_and_expires(recipient):
    actors = [_actor("caster", "main"), _actor("ally", "ally")]
    grant = derive_lulu_support_events(
        get_champion("Lulu"), 18, {"ability_power": 0.0}, [{"slot": "R", "time": 2.0}]
    )[0]
    amount = grant["amount"]
    grant.update(attacker="caster", cast_blocked_by_attacker_control=True)
    before_expiry = _rows(actors, {}, {recipient: [dict(grant)]}, 8.0)
    assert before_expiry[recipient]["max_health"] == 1000.0 + amount
    assert before_expiry[recipient]["ending_health"] == 1000.0 + amount
    other = "ally" if recipient == "caster" else "caster"
    assert before_expiry[other]["max_health"] == 1000.0
    after_expiry = _rows(actors, {}, {recipient: [dict(grant)]}, 9.0)
    assert after_expiry[recipient]["max_health"] == 1000.0
    assert after_expiry[recipient]["ending_health"] == 1000.0
    assert after_expiry[recipient]["temporary_health_expired_at"] == 9.0


def test_temporary_health_sources_keep_independent_expiry():
    state = {
        "pools": ShieldPools(health=1000.0, max_health=1000.0),
        "temporary_health_amount": 0.0,
        "temporary_health_until": 0.0,
        "temporary_health_received": 0.0,
        "temporary_health_source": "",
        "temporary_health_expired_at": None,
    }
    grant_temporary_health(state, amount=300.0, until=7.0, source="Wild Growth")
    grant_temporary_health(state, amount=100.0, until=10.0, source="Another grant")
    assert expire_temporary_health(state, 7.0)
    assert state["pools"].max_health == 1100.0
    assert state["temporary_health_amount"] == 100.0
    assert state["temporary_health_until"] == 10.0
    assert expire_temporary_health(state, 10.0)
    assert state["pools"].max_health == 1000.0


def test_stat_buff_expiry_preserves_other_live_windows():
    state = {
        "support_buffs": [
            {"source": "Whimsy", "until": 4.0},
            {"source": "Later buff", "until": 6.0},
        ]
    }
    expire_support_buffs(state, 3.999)
    assert len(state["support_buffs"]) == 2
    expire_support_buffs(state, 4.0)
    assert state["support_buffs"] == [{"source": "Later buff", "until": 6.0}]
    expire_support_buffs(state, 6.0)
    assert state["support_buffs"] == []


@pytest.mark.parametrize("kind", ["stat_buff", "temporary_health", "shield"])
@pytest.mark.parametrize("blocked", ["dead", "stunned"])
def test_explicit_support_cast_cannot_fire_from_disabled_caster(kind, blocked):
    actors = [
        _actor("caster", "main"),
        _actor("ally", "ally"),
        _actor("enemy", "enemy"),
    ]
    hostile = {
        "time": 0.0,
        "attacker": "enemy",
        "target": "caster",
        "sequence": 0,
        "_event_id": "hostile",
        "source": "Test control",
    }
    if blocked == "dead":
        hostile.update(damage=2000.0, damage_type="true")
    else:
        hostile.update(
            kind="crowd_control", damage=0.0, cc_kind="stun", cc_duration=3.0
        )
    grant = {
        "time": 1.0,
        "kind": kind,
        "amount": 100.0,
        "duration": 4.0,
        "bonus_attack_speed_percent": 30.0,
        "attacker": "caster",
        "source": "Authored Lulu spell",
        "cast_blocked_by_attacker_control": True,
    }
    rows = _rows(actors, {"caster": [hostile]}, {"ally": [grant]}, 5.0)
    assert grant["skipped_reason"] == (
        "attacker_dead" if blocked == "dead" else "attacker_state_blocked"
    )
    assert rows["ally"]["temporary_health_received"] == 0.0
    assert rows["ally"]["support_shield_received"] == 0.0


def test_lulu_support_requires_the_accepted_cast_slot():
    with pytest.raises(KeyError, match="slot"):
        derive_lulu_support_events(
            get_champion("Lulu"), 1, {"ability_power": 0.0}, [{"time": 0.0}]
        )
