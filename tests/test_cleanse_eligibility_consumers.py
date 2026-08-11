"""P2 Slice 4 cleanse walk-integration consumer tests (owner-owned).

Timeline-level walk integration (through
``participant_timeline._simulate_survival``), app-level self-cast actives
(Quicksilver Sash / Mercurial Scimitar item options), the Mikael's Purify
heal+cleanse marker, and the compiled-score fail-closed surface.
"""

from types import SimpleNamespace

import pytest

from src.app import app
from src.calculator.participant_timeline import (
    Combatant,
    _WalkCompiler,
    _simulate_survival,
)
from src.calculator.survival.actions import ActionKind
from src.calculator.survival.compile import (
    UncompilableActionError,
    unrepresentable_template_receipt,
)

MIKAELS_SOURCE = "Mikael's Blessing — Purify"
QUICKSILVER_SOURCE = "Quicksilver Sash — Quicksilver"
MERCURIAL_SOURCE = "Mercurial Scimitar — Quicksilver"


def _combatant(participant_id: str, team: str, health: float = 3000.0) -> Combatant:
    defenses = SimpleNamespace(
        magic_shield=0.0,
        physical_shield=0.0,
        general_shield=0.0,
        healing_received_multiplier=1.0,
    )
    return Combatant(
        participant_id=participant_id,
        team=team,
        champion_data={"name": participant_id},
        level=1,
        items=(),
        stats={"health": health},
        defenses=defenses,
    )


def _control(
    time: float,
    kind: str,
    duration: float,
    *,
    source: str = "E",
    target: str = "target",
    sequence: int = 0,
) -> dict:
    return {
        "time": time,
        "damage": 0.0,
        "damage_type": "magic",
        "attacker": "enemy",
        "target": target,
        "source_key": source,
        "source": source,
        "is_ability": True,
        "kind": "crowd_control",
        "sequence": sequence,
        "_event_id": f"cc-{sequence}",
        "cc_kind": kind,
        "cc_duration": duration,
    }


def _cleanse(
    time: float,
    *,
    target: str = "target",
    attacker: str = "target",
    source: str = QUICKSILVER_SOURCE,
    sequence: int = 0,
) -> dict:
    return {
        "time": time,
        "kind": "cleanse",
        "amount": 1.0,
        "attacker": attacker,
        "target": target,
        "source": source,
        "source_key": source,
        "utility_kind": "cleanse",
        "sequence": sequence,
        "_event_id": f"cleanse-{sequence}",
    }


def _purify(
    time: float,
    *,
    target: str = "target",
    attacker: str = "caster",
    amount: float = 100.0,
    sequence: int = 0,
) -> dict:
    return {
        "time": time,
        "kind": "heal",
        "amount": amount,
        "attacker": attacker,
        "target": target,
        "source": MIKAELS_SOURCE,
        "source_key": MIKAELS_SOURCE,
        "cleanse": True,
        "cleanse_item": "Mikael's Blessing",
        "sequence": sequence,
        "_event_id": f"purify-{sequence}",
    }


def _movement(time: float, *, target: str = "target", attacker: str = "target") -> dict:
    return {
        "time": time,
        "kind": "movement",
        "amount": 50.0,
        "duration": 2.0,
        "bonus_move_speed_percent": 50.0,
        "attacker": attacker,
        "target": target,
        "source": MERCURIAL_SOURCE,
        "source_key": MERCURIAL_SOURCE,
        "utility_kind": "movement",
        "sequence": 9,
        "_event_id": "movement-9",
    }


def _run(
    incoming: list[dict],
    supports: list[dict],
    *,
    combatants: list[Combatant] | None = None,
) -> dict[str, dict]:
    if combatants is None:
        combatants = [
            _combatant("enemy", "enemy"),
            _combatant("target", "main"),
            _combatant("caster", "main"),
        ]
    return _simulate_survival(
        combatants,
        {"target": [dict(p) for p in incoming]},
        {},
        {"target": [dict(p) for p in supports]},
        10.0,
    )


# ---------------------------------------------------------------------------
# Walk integration: self-cast truncation
# ---------------------------------------------------------------------------


def test_self_cast_truncates_the_holders_own_interval():
    result = _run(
        [_control(1.0, "stun", 2.0)],
        [_cleanse(1.5)],
    )
    receipt = result["target"]["cleanse"]
    assert receipt["decision"]["reason"] == ""
    assert receipt["removed_controls"] == [
        {
            "control_kind": "stun",
            "source": "E",
            "start": pytest.approx(1.5),
            "end": pytest.approx(3.0),
            "reason": "",
        }
    ]
    assert result["target"]["action_downtime"] == pytest.approx(0.5)
    assert result["target"]["crowd_control_until"] == pytest.approx(1.5)
    assert result["target"]["crowd_control_intervals"] == [
        {
            "recipient": "target",
            "kind": "stun",
            "start": 1.0,
            "end": 1.5,
            "source": "E",
        }
    ]
    use = result["target"]["cleanse_use"]
    assert use["uses_before"] == 1
    assert use["uses_after"] == 0
    assert use["activations"] == 1
    assert use["cooldown_source_gap"] is True
    assert use["fired_while_crowd_controlled"] is True


def test_self_cast_while_not_ccd_still_consumes_the_use():
    result = _run([], [_cleanse(1.5)])
    receipt = result["target"]["cleanse"]
    assert receipt["decision"]["reason"] == "control_not_active"
    assert receipt["use_consumed"] is True
    assert result["target"]["cleanse_use"]["uses_after"] == 0


def test_second_activation_is_denied_use_spent():
    result = _run(
        [_control(1.0, "stun", 2.0)],
        [_cleanse(1.5, sequence=0), _cleanse(2.0, sequence=1)],
    )
    first = result["target"]["cleanse"]
    assert first["decision"]["reason"] == ""
    assert result["target"]["cleanse_denied"] == [
        {"time": pytest.approx(2.0), "reason": "use_spent"}
    ]
    use = result["target"]["cleanse_use"]
    assert use["uses_after"] == 0
    assert use["activations"] == 2
    # The denied second activation truncated nothing further.
    assert result["target"]["crowd_control_intervals"][0]["end"] == pytest.approx(1.5)


def test_suppressed_caster_cannot_cast_self_cleanse():
    result = _run(
        [_control(1.0, "suppression", 2.0)],
        [_cleanse(1.5)],
    )
    receipt = result["target"]["cleanse"]
    assert receipt["decision"]["reason"] == "caster_control_blocks_cleanse"
    assert receipt["removed_controls"] == []
    (rejected,) = receipt["rejected_controls"]
    assert rejected["control_kind"] == "suppression"
    assert rejected["reason"] == "caster_control_blocks_cleanse"
    assert result["target"]["action_downtime"] == pytest.approx(2.0)
    assert result["target"]["cleanse_use"]["uses_after"] == 1  # not consumed


def test_mikaels_purify_truncates_the_selected_ally_only():
    combatants = [
        _combatant("enemy", "enemy"),
        _combatant("ally:one", "main"),
        _combatant("ally:two", "main"),
        _combatant("caster", "main"),
    ]
    result = _simulate_survival(
        combatants,
        {
            "ally:one": [_control(1.0, "stun", 2.0, target="ally:one")],
            "ally:two": [_control(1.0, "stun", 2.0, target="ally:two")],
        },
        {},
        {
            "ally:one": [
                _purify(1.5, target="ally:one", attacker="caster", amount=100.0)
            ]
        },
        10.0,
    )
    one = result["ally:one"]
    assert one["cleanse"]["decision"]["reason"] == ""
    assert one["cleanse"]["heal"]["amount"] == pytest.approx(100.0)
    assert one["action_downtime"] == pytest.approx(0.5)
    two = result["ally:two"]
    assert "cleanse" not in two
    assert two["action_downtime"] == pytest.approx(2.0)
    # The caster's row carries the use receipt (fired while free).
    caster = result["caster"]
    assert caster["cleanse_use"]["item"] == "Mikael's Blessing"
    assert caster["cleanse_use"]["fired_while_crowd_controlled"] is False


def test_mikaels_heal_is_gated_while_the_caster_is_ccd():
    combatants = [
        _combatant("enemy", "enemy"),
        _combatant("target", "main"),
        _combatant("caster", "main"),
    ]
    result = _simulate_survival(
        combatants,
        {
            "target": [_control(1.0, "stun", 2.0, target="target")],
            "caster": [_control(0.5, "stun", 2.0, target="caster", source="W")],
        },
        {},
        {"target": [_purify(1.5, target="target", attacker="caster")]},
        10.0,
    )
    # Mikael's 3222Active carries no canCastWhileDisabled: the heal+cleanse
    # is gated by the caster's crowd control (attacker_state_blocked) and
    # the use is NOT consumed.
    assert result["target"]["healing_received"] == pytest.approx(0.0)
    assert result["target"]["action_downtime"] == pytest.approx(2.0)
    assert "cleanse" not in result["target"]
    use = result["caster"]["cleanse_use"]
    assert use["fired_while_crowd_controlled"] is False
    assert use["uses_after"] == 1


def test_mercurial_cleanse_and_movement_are_separate_effects():
    result = _run(
        [_control(1.0, "stun", 2.0)],
        [_cleanse(1.5, source=MERCURIAL_SOURCE), _movement(1.5)],
    )
    receipt = result["target"]["cleanse"]
    assert receipt["item"] == "Mercurial Scimitar"
    assert receipt["removed_controls"][0]["control_kind"] == "stun"
    movement = receipt["movement"]
    assert movement["amount"] == pytest.approx(50.0)
    assert movement["duration"] == pytest.approx(2.0)
    assert movement["source"] == MERCURIAL_SOURCE
    assert {atom["hash"] for atom in movement["source_atoms"]} == {"5e5f100f08a793f9"}
    assert receipt["heal"] is None
    assert result["target"]["action_downtime"] == pytest.approx(0.5)


def test_unknown_control_kind_fails_closed_at_the_walk():
    result = _run(
        [_control(1.0, "dance", 2.0)],
        [_cleanse(1.5)],
    )
    receipt = result["target"]["cleanse"]
    assert receipt["decision"]["reason"] == "unknown_control"
    assert receipt["removed_controls"] == []
    assert result["target"]["crowd_control_intervals"][0]["end"] == pytest.approx(3.0)
    assert result["target"]["cleanse_use"]["uses_after"] == 1  # not consumed


# ---------------------------------------------------------------------------
# App-level self-cast actives (item options)
# ---------------------------------------------------------------------------


def _calculate(payload: dict) -> dict:
    app.config["TESTING"] = True
    response = app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_data(as_text=True)[:500]
    return response.get_json()["combat"]


def _main(item: str) -> dict:
    return {
        "champion": "Lux",
        "level": 18,
        "items": [item],
        "item_options": {item: {"active_seconds": 1.0}},
        "fight_mode": "time_based",
        "fight_duration": 4.0,
        "include_auto_attacks": False,
        "ability_ranks": {"Q": 0, "W": 0, "E": 0, "R": 0},
        "enemies": [
            {
                "champion": "Ahri",
                "level": 18,
                "items": [],
                "ability_ranks": {"Q": 0, "W": 0, "E": 5, "R": 0},
            }
        ],
    }


@pytest.mark.parametrize(
    "item,source",
    [
        ("Quicksilver Sash", QUICKSILVER_SOURCE),
        ("Mercurial Scimitar", MERCURIAL_SOURCE),
    ],
)
def test_app_self_cleanse_option_truncates_the_charm(item, source):
    combat = _calculate(_main(item))
    rows = {p["participant_id"]: p["survival"] for p in combat["participants"]}
    main = rows["main"]
    receipt = main["cleanse"]
    assert receipt["item"] == item
    assert receipt["target"] == "main"
    assert receipt["decision"]["reason"] == ""
    assert receipt["removed_controls"][0]["control_kind"] == "immobilize"
    assert main["action_downtime"] == pytest.approx(1.0)
    assert main["cleanse_use"]["uses_after"] == 0
    if item == "Mercurial Scimitar":
        movement = combat["utility_outcomes"]["participants"]["main"]["movement"]
        assert movement["event_count"] == 1
        assert movement["speed_percent_seconds"] == pytest.approx(100.0)


def test_app_mercurial_movement_rides_utility_outcomes():
    combat = _calculate(_main("Mercurial Scimitar"))
    outcomes = combat["utility_outcomes"]["participants"]["main"]
    assert outcomes["cleanse"]["event_count"] == 1
    assert outcomes["movement"]["event_count"] == 1


def test_app_mikaels_heal_and_cleanse_receipts():
    combat = _calculate(
        {
            **_main("Mikael's Blessing"),
            "item_options": {"Mikael's Blessing": {"active_seconds": 2.5}},
            "support_target_selections": {"heal:Mikael's Blessing — Purify": 0},
            "enemies": [
                {
                    "champion": "Lulu",
                    "level": 18,
                    "items": [],
                    "ability_ranks": {"Q": 5, "W": 5, "E": 0, "R": 0},
                }
            ],
            "allies": [
                {
                    "champion": "Jinx",
                    "level": 18,
                    "items": [],
                    "ally_effects_enabled": True,
                    "ability_ranks": {"Q": 0, "W": 0, "E": 0, "R": 0},
                }
            ],
        }
    )
    rows = {p["participant_id"]: p["survival"] for p in combat["participants"]}
    jinx = rows["ally:Jinx"]
    assert jinx["cleanse"]["decision"]["reason"] == "control_not_active"
    assert jinx["cleanse"]["heal"]["source"] == MIKAELS_SOURCE
    assert {atom["hash"] for atom in jinx["cleanse"]["heal"]["source_atoms"]} == {
        "cf9fe930ebd40602"
    }
    assert rows["main"]["cleanse_use"]["item"] == "Mikael's Blessing"


# ---------------------------------------------------------------------------
# Score path: fail closed
# ---------------------------------------------------------------------------


def test_compiled_walk_fails_closed_on_cleanse_templates():
    compiler = _WalkCompiler()
    with pytest.raises(UncompilableActionError) as excinfo:
        compiler.add_support_templates(
            [
                {
                    "kind": "cleanse",
                    "amount": 1.0,
                    "attacker": "main",
                    "target": "main",
                    "time": 1.0,
                }
            ],
            0,
            {"main": 0},
        )
    assert "support_kind=cleanse" in str(excinfo.value)
    compiler = _WalkCompiler()
    with pytest.raises(UncompilableActionError) as excinfo:
        compiler.add_support_templates(
            [
                {
                    "kind": "movement",
                    "amount": 50.0,
                    "duration": 2.0,
                    "attacker": "main",
                    "target": "main",
                    "time": 1.0,
                }
            ],
            0,
            {"main": 0},
        )
    assert "support_kind=movement" in str(excinfo.value)


def test_compiled_walk_fails_closed_on_mikaels_heal_marker():
    # The heal+cleanse marker must not compile as a silent plain heal.
    assert (
        unrepresentable_template_receipt(
            {"kind": "heal", "amount": 100.0, "cleanse": True}
        )
        == "support_cleanse"
    )
    compiler = _WalkCompiler()
    with pytest.raises(UncompilableActionError) as excinfo:
        compiler.add_support_templates(
            [
                {
                    "kind": "heal",
                    "amount": 100.0,
                    "cleanse": True,
                    "source": MIKAELS_SOURCE,
                    "attacker": "caster",
                    "target": "main",
                    "time": 2.5,
                }
            ],
            0,
            {"main": 0, "caster": 1},
        )
    assert "support_cleanse" in str(excinfo.value)
    # A plain heal stays representable.
    compiler = _WalkCompiler()
    compiler.add_support_templates(
        [
            {
                "kind": "heal",
                "amount": 100.0,
                "attacker": "caster",
                "target": "main",
                "time": 2.5,
            }
        ],
        0,
        {"main": 0, "caster": 1},
    )
    (action,) = compiler.actions
    assert action.kind is ActionKind.HEAL
