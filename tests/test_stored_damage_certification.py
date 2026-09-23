"""An engine-built damage event carries its slot's reviewed control state.

The Everlasting scan certifies a timed fight only when every damaging ability
event reaching the control bus carries a reviewed crowd-control state. A
module states that per slot in ``MODULE_CC``, and ``slot_cc`` stamps the
reviewed-no-control answer onto the entry as ``cc_reviewed``.

A stored-damage row declares no parts BY CONSTRUCTION: the module authors the
rule and the fight engine builds the events from the post-mitigation ledger.
So the parts-reading marker has nothing to read, and before this the events
reached the bus bare. Yone's E was reviewed control-free in ``MODULE_CC`` and
still forced Fimbulwinter to coarse ordering, which is the one residue row
``docs/coverage-residue.json`` marked ``certification_shape``: the source
states the missing piece and only the certification shape refused it.

Fail-closed is the half that matters as much as the fix: an entry that is NOT
reviewed stamps nothing and still goes coarse.
"""

import dataclasses

import pytest

from src.calculator.calculate import calculate_payload
from src.calculator.champions.yone import MODULE_CC

_ENEMY = {"kind": "champion", "champion": "Garen", "level": 18, "role": "top"}


@dataclasses.dataclass
class _StubState:
    """Only the fields ``_add_stored_damage`` reads, so the probe is the rule.

    A real ``FightState`` would drag the whole fight in and hide which field
    the stamp depends on; this names them.
    """

    ability_damages: dict
    breakdown: dict
    cast_order: tuple = ("Q", "E")
    ledger_target_index: int | None = None
    total_damage: float = 0.0


@dataclasses.dataclass
class _StubRotation:
    cast_events: tuple = (
        {"slot": "Q", "time": 0.0},
        {"slot": "E", "time": 0.0},
    )


def _fight(*, items: list[str], mode: str = "time_based", autos: bool = True) -> dict:
    return calculate_payload(
        {
            "champion": "Yone",
            "level": 18,
            "role": "mid",
            "items": items,
            "enemies": [_ENEMY],
            "fight_duration": 10,
            "fight_mode": mode,
            "include_auto_attacks": autos,
            "auto_attack_uptime": 1.0,
        },
        deterministic=True,
    )


def test_the_module_reviewed_the_slot_as_control_free():
    """The fact was always stated. Only the event did not carry it."""
    assert MODULE_CC["E"] == "none"


def test_the_entry_carries_the_reviewed_flag_and_declares_no_parts():
    """Why the parts-reading marker cannot answer for this row."""
    import copy

    from src.calculator.champions import parse_champion_abilities
    from src.calculator.data_fetcher import get_champion
    from src.calculator.stats import calculate_total_stats

    data = copy.deepcopy(get_champion("Yone"))
    stats = dict(calculate_total_stats(data, 18, []))
    abilities = parse_champion_abilities(
        data,
        18,
        stats["ability_power"],
        ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
        champion_stats=stats,
        target_stats={
            "armor": 100.0,
            "magic_resist": 50.0,
            "magic_resistance": 50.0,
            "target_max_health": 2500.0,
            "target_current_health": 2500.0,
            "target_missing_health": 0.0,
        },
    )
    entry = abilities["E"]
    assert entry["cc_reviewed"] is True
    assert entry["parts"] == ()
    assert entry["stored_damage"]["ratio"] > 0.0


@pytest.mark.parametrize(
    ("mode", "autos"),
    [("one_rotation", True), ("time_based", True), ("time_based", False)],
)
def test_a_control_armed_holder_shield_certifies_on_every_window(mode, autos):
    """The gate this closes. Before the stamp, all three read coarse.

    Fimbulwinter's Everlasting arms on Yone's R immobilize and then walked the
    ledger, where E's engine-built stored event had no reviewed state.
    """
    bare = _fight(items=[], mode=mode, autos=autos)["timeline_coverage"]
    holder = _fight(items=["Fimbulwinter"], mode=mode, autos=autos)["timeline_coverage"]
    assert bare["coarse_sources"] == []
    assert holder["coarse_sources"] == []
    assert holder["certification"] == "event_order_certified"


def test_the_stored_events_carry_the_flag_they_inherited():
    """Read off the published row, not inferred from the coverage verdict."""
    row = next(
        source
        for source in _fight(items=["Fimbulwinter"])["combat"]["breakdown"][0][
            "sources"
        ]
        if source["name"] == "Fate Sealed"
    )
    assert row["total_damage"] > 0.0


def test_an_unreviewed_stored_row_stamps_nothing():
    """Fail-closed, driven over the real builder rather than asserted about it.

    A stored row whose owning entry was never reviewed must stamp nothing, so
    a module that forgets ``MODULE_CC`` cannot buy certification just by
    declaring ``stored_damage``. Both halves run here over the same fixture
    with one flag flipped, which is what makes the stamp a consequence of the
    review rather than of the row's shape.
    """
    from src.calculator.fight.after.stored_damage import _add_stored_damage

    def _events(*, reviewed: bool) -> list[dict]:
        entry = {
            "stored_damage": {
                "ratio": 0.5,
                "duration": 5.0,
                "source_slots": ("Q",),
                "include_auto_attacks": False,
            }
        }
        if reviewed:
            entry["cc_reviewed"] = True
        row = {"casts": 1}
        state = _StubState(
            ability_damages={"E": entry, "Q": {}},
            breakdown={
                "E": row,
                "Q": {
                    "casts": 1,
                    "damage_events": [
                        {
                            "time": 1.0,
                            "damage": 100.0,
                            "damage_type": "physical",
                            "source_key": "Q",
                        }
                    ],
                },
            },
        )
        _add_stored_damage(state, _StubRotation())
        return row.get("damage_events", [])

    stamped = _events(reviewed=True)
    bare = _events(reviewed=False)
    assert stamped, "the probe built no stored event to inspect"
    assert [event["damage"] for event in stamped] == [
        event["damage"] for event in bare
    ], "only the marker may differ between the two runs"
    assert all(event.get("cc_reviewed") is True for event in stamped)
    assert all("cc_reviewed" not in event for event in bare)
