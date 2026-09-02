"""P2 delivery/eligibility kernel slice — acceptance matrix (Braum E, Yasuo W).

This file is the RLM-2 acceptance-matrix suite for the shared
``src/calculator/delivery_eligibility.py`` kernel (typed delivery
declarations, defense eligibility, composition rules).  It uses the same
public API as ``tests/test_interaction_atoms.py`` (``src.app`` ->
``POST /api/calculate``) and pins the CURRENT runtime's behavior so the
kernel recomposition cannot drift silently.

Row status conventions:
- "CURRENT" rows assert behavior the tree already satisfies today.
- "NEW-CONTRACT" rows assert the current baseline where the future kernel
  must define different behavior; each carries a comment naming the
  contract question the kernel owner must resolve (the assertion will
  break when the kernel lands, which is the intended signal).
"""

from operator import itemgetter

import pytest

from src.app import app
from tests.survival_probe import survival_of

_BY_TIME = itemgetter("time")


def _calculate(payload: dict) -> dict:
    response = app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_data(as_text=True)[:500]
    return response.get_json()["combat"]


def _events(
    combat: dict, *, attacker: str, target: str, source: str | None
) -> list[dict]:
    return [
        event
        for event in combat["events"]
        if event.get("attacker") == attacker
        and event.get("target") == target
        and (source is None or event.get("source") == source)
    ]


def _reject(payload: dict) -> tuple[int, dict]:
    response = app.test_client().post("/api/calculate", json=payload)
    return response.status_code, response.get_json()


def _enemy(champion: str, *, options: dict | None = None, **overrides) -> dict:
    enemy = {
        "champion": champion,
        "level": 18,
        "items": [],
        "ability_ranks": {"Q": 0, "W": 0, "E": 5, "R": 0},
    }
    if options is not None:
        enemy["champion_options"] = options
    enemy.update(overrides)
    return enemy


def _braum(options: dict, **overrides) -> dict:
    return _enemy("Braum", options=options, **overrides)


def _yasuo(options: dict, **overrides) -> dict:
    return _enemy(
        "Yasuo",
        options=options,
        ability_ranks={"Q": 0, "W": 5, "E": 0, "R": 0},
        **overrides,
    )


def _ezreal_timed(duration: float = 8.0, *, autos: bool = False) -> dict:
    return {
        "champion": "Ezreal",
        "level": 18,
        "items": [],
        "fight_mode": "time_based",
        "fight_duration": duration,
        "include_auto_attacks": autos,
        "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
    }


# ---------------------------------------------------------------------------
# Dimension 1 — delivery classes
# ---------------------------------------------------------------------------


def test_d1_projectile_skillshot_braum_full_blocks_then_reduces():
    """Projectile (skillshot) delivery: first selected hit full-blocked,
    later selected hits reduced at the ranked value, later casts pass."""
    combat = _calculate(
        {
            **_ezreal_timed(),
            "enemies": [
                _braum(
                    {
                        "e_active": True,
                        "e_active_seconds": 4.0,
                        "e_blocked_skillshots": ["Q"],
                    }
                )
            ],
        }
    )
    q_events = sorted(
        _events(combat, attacker="main", target="enemy:Braum", source="Q"),
        key=_BY_TIME,
    )
    assert [event["time"] for event in q_events] == [0.25, 3.5, 6.75]
    first, later, after = q_events

    assert first["skillshot"] is True
    assert first["damage"] == pytest.approx(0.0)
    receipt = first["projectile_defense"]
    assert receipt["source"] == "Braum E · Unbreakable"
    assert receipt["mode"] == "full_block"
    # Contract item 8: every per-event receipt carries the typed delivery
    # declaration, the eligibility verdict, and the remaining-use count.
    assert receipt["eligible"] is True
    assert receipt["remaining_uses"] == 0
    assert receipt["delivery"] == {
        "classes": ["projectile"],
        "unknown": False,
        "unknown_markers": [],
    }

    assert later["damage"] == pytest.approx(57.5)
    assert later["projectile_defense"]["mode"] == "reduced"
    assert later["projectile_defense"]["reduction"] == pytest.approx(0.55)
    assert later["projectile_defense"]["mitigated"] == pytest.approx(70.3)
    assert later["projectile_defense"]["eligible"] is True
    assert later["projectile_defense"]["remaining_uses"] == 0
    assert later["projectile_defense"]["delivery"]["classes"] == ["projectile"]

    assert after["damage"] == pytest.approx(127.8)
    assert "projectile_defense" not in after

    survival = survival_of(combat, "enemy:Braum")
    assert survival["projectile_defense"]["until"] == pytest.approx(4.0)
    assert survival["projectile_defense_blocked"] == [
        {"time": 0.25, "source": "Q", "mode": "full_block"}
    ]


def test_d1_area_only_delivery_passes_braum():
    """Area (area_damage, no skillshot marker) delivery is not eligible for
    a requires_skillshot defense: full damage, no receipt."""
    combat = _calculate(
        {
            "champion": "Brand",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 6,
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
            "enemies": [
                _braum(
                    {
                        "e_active": True,
                        "e_active_seconds": 4.0,
                        "e_blocked_skillshots": ["W"],
                    }
                )
            ],
        }
    )
    w_events = _events(combat, attacker="main", target="enemy:Braum", source="W")
    assert w_events
    for event in w_events:
        assert event["area_damage"] is True
        assert "skillshot" not in event
        assert event["damage"] == pytest.approx(190.9)
        assert "projectile_defense" not in event
    assert survival_of(combat, "enemy:Braum")["projectile_defense_blocked"] == []


def test_d1_targeted_unmarked_ability_passes_braum():
    """Targeted/non-skillshot ability (no projectile, no area marker):
    not eligible, full damage."""
    combat = _calculate(
        {
            "champion": "Camille",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 6,
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
            "enemies": [
                _braum(
                    {
                        "e_active": True,
                        "e_active_seconds": 4.0,
                        "e_blocked_skillshots": ["Q"],
                    }
                )
            ],
        }
    )
    q_events = _events(combat, attacker="main", target="enemy:Braum", source="Q")
    assert q_events
    for event in q_events:
        assert "skillshot" not in event
        assert event["damage"] == pytest.approx(84.6)
        assert "projectile_defense" not in event
    assert survival_of(combat, "enemy:Braum")["projectile_defense_blocked"] == []


def test_d1_basic_attack_delivery_passes_both_defenses():
    """Basic-attack delivery: never eligible for Braum E or Yasuo W (no
    blocks_basic_attacks declaration on either)."""
    for enemy in (
        _braum(
            {
                "e_active": True,
                "e_active_seconds": 4.0,
                "e_blocked_skillshots": ["Q"],
            }
        ),
        _yasuo(
            {
                "w_active": True,
                "w_active_seconds": 4.0,
                "w_blocked_skillshots": ["Q"],
            }
        ),
    ):
        combat = _calculate({**_ezreal_timed(autos=True), "enemies": [enemy]})
        target = f"enemy:{enemy['champion']}"
        autos = _events(combat, attacker="main", target=target, source="auto_attacks")
        assert len(autos) >= 2
        for event in autos:
            assert "projectile_defense" not in event
            if event.get("skipped_reason") is None:
                assert event["damage"] > 0.0
        # The selected Q skillshots are the only eligible packets; the
        # blocked list never contains basic-attack entries.
        assert all(
            entry["source"] != "auto_attacks"
            for entry in survival_of(combat, target)["projectile_defense_blocked"]
        )


def test_d1_damage_over_time_ticks_pass_unmarked_defense():
    """Damage-over-time delivery (dot ticks without a skillshot marker):
    not eligible for projectile destruction; every tick lands."""
    combat = _calculate(
        {
            "champion": "Cassiopeia",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 6,
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
            "enemies": [
                _yasuo(
                    {
                        "w_active": True,
                        "w_active_seconds": 4.0,
                        "w_blocked_skillshots": ["Q"],
                    }
                )
            ],
        }
    )
    q_events = _events(combat, attacker="main", target="enemy:Yasuo", source="Q")
    assert len(q_events) >= 8
    for event in q_events:
        assert event["area_damage"] is True
        assert "skillshot" not in event
        assert "projectile_defense" not in event
        if event.get("skipped_reason") is None:
            assert event["damage"] == pytest.approx(18.4)
    assert survival_of(combat, "enemy:Yasuo")["projectile_defense_blocked"] == []


def test_d1_skillshot_marked_dot_ticks_are_destroyed_by_wind_wall():
    """NEW-CONTRACT (delivery classification): Malzahar E's dot ticks carry
    the ability row's skillshot marker, so the current runtime destroys
    each tick inside the wall window.  The kernel must decide whether
    damage_over_time delivery is eligible for projectile destruction at
    all (in-game the wall blocks the initial missile, not the ticks)."""
    combat = _calculate(
        {
            "champion": "Malzahar",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 6,
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
            "enemies": [
                _yasuo(
                    {
                        "w_active": True,
                        "w_active_seconds": 4.0,
                        "w_blocked_skillshots": ["E"],
                    }
                )
            ],
        }
    )
    e_events = sorted(
        _events(combat, attacker="main", target="enemy:Yasuo", source="E"),
        key=_BY_TIME,
    )
    destroyed = [event for event in e_events if event.get("projectile_defense")]
    # Ticks at 0.5s..3.75s (0.25s cadence) fall inside [0, 4.0).
    assert [event["time"] for event in destroyed] == pytest.approx(
        [0.5 + 0.25 * index for index in range(14)]
    )
    for event in destroyed:
        assert event["damage"] == pytest.approx(0.0)
        assert event["projectile_defense"]["mode"] == "destroyed"
        assert event["skipped_reason"] == "yasuo_wind_wall"
    first_passing = next(event for event in e_events if event["time"] == 4.0)
    assert first_passing["damage"] == pytest.approx(8.2)
    assert "projectile_defense" not in first_passing
    blocked = survival_of(combat, "enemy:Yasuo")["projectile_defense_blocked"]
    assert len(blocked) == 14
    assert blocked[0] == {"time": 0.5, "source": "E", "mode": "destroyed"}


def test_d1_unknown_unmarked_delivery_has_no_receipt():
    """NEW-CONTRACT (fail-closed classification): an unmarked packet (Olaf E
    true damage — no projectile, no area marker) currently passes silently
    with no receipt.  The kernel must type this delivery (targeted/melee)
    and fail closed for genuinely unknown packets."""
    combat = _calculate(
        {
            "champion": "Olaf",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 6,
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
            "enemies": [
                _braum(
                    {
                        "e_active": True,
                        "e_active_seconds": 4.0,
                        "e_blocked_skillshots": ["Q"],
                    }
                )
            ],
        }
    )
    e_events = _events(combat, attacker="main", target="enemy:Braum", source="E")
    assert e_events
    for event in e_events:
        assert event["damage_type"] == "true"
        assert "skillshot" not in event
        # 250 (rank 5) + 50% AD, and the AD is Olaf's own steroid-averaged
        # figure: R grants 30 + 25% AD = 67 for 3s of this 6s fight, which
        # olaf.py applies at the window share (0.5) — so 148 + 33.5 = 181.5
        # total AD and 250 + 90.75 = 340.75.
        assert event["damage"] == pytest.approx(340.8)
        assert "projectile_defense" not in event
    # Only the selected skillshot (Olaf Q) is ever listed; the unmarked E
    # packets never reach the defense.
    assert all(
        entry["source"] == "Q"
        for entry in survival_of(combat, "enemy:Braum")["projectile_defense_blocked"]
    )


# ---------------------------------------------------------------------------
# Dimension 2 — eligibility
# ---------------------------------------------------------------------------


def test_d2_braum_blocks_only_selected_skillshots():
    """Source-slot selection: only the selected slot is eligible."""
    combat = _calculate(
        {
            **_ezreal_timed(),
            "enemies": [
                _braum(
                    {
                        "e_active": True,
                        "e_active_seconds": 4.0,
                        "e_blocked_skillshots": ["Q"],
                    }
                )
            ],
        }
    )
    q_first = _events(combat, attacker="main", target="enemy:Braum", source="Q")[0]
    assert q_first["projectile_defense"]["mode"] == "full_block"
    w_events = _events(combat, attacker="main", target="enemy:Braum", source="W")
    assert w_events[0]["damage"] == pytest.approx(179.6)
    assert "projectile_defense" not in w_events[0]
    assert survival_of(combat, "enemy:Braum")["projectile_defense_blocked"] == [
        {"time": 0.25, "source": "Q", "mode": "full_block"}
    ]


def test_d2_yasuo_blocks_only_selected_projectiles():
    """Yasuo W selection: only the selected marked projectile is destroyed."""
    combat = _calculate(
        {
            **_ezreal_timed(),
            "enemies": [
                _yasuo(
                    {
                        "w_active": True,
                        "w_active_seconds": 4.0,
                        "w_blocked_skillshots": ["Q"],
                    }
                )
            ],
        }
    )
    q_events = sorted(
        _events(combat, attacker="main", target="enemy:Yasuo", source="Q"),
        key=_BY_TIME,
    )
    assert q_events[0]["projectile_defense"]["mode"] == "destroyed"
    assert q_events[0]["skipped_reason"] == "yasuo_wind_wall"
    w_events = _events(combat, attacker="main", target="enemy:Yasuo", source="W")
    assert w_events[0]["damage"] == pytest.approx(179.6)
    assert "projectile_defense" not in w_events[0]


def test_d2_empty_selection_blocks_all_marked_skillshots():
    """Empty source selection means every marked skillshot is eligible
    (first full block, later hits reduced)."""
    combat = _calculate(
        {
            **_ezreal_timed(),
            "enemies": [
                _braum(
                    {
                        "e_active": True,
                        "e_active_seconds": 4.0,
                        "e_blocked_skillshots": [],
                    }
                )
            ],
        }
    )
    w_first = _events(combat, attacker="main", target="enemy:Braum", source="W")[0]
    q_first = _events(combat, attacker="main", target="enemy:Braum", source="Q")[0]
    e_first = _events(combat, attacker="main", target="enemy:Braum", source="E")[0]
    assert w_first["projectile_defense"]["mode"] == "full_block"
    assert w_first["damage"] == pytest.approx(0.0)
    assert q_first["projectile_defense"]["mode"] == "reduced"
    assert q_first["projectile_defense"]["reduction"] == pytest.approx(0.55)
    assert e_first["projectile_defense"]["mode"] == "reduced"
    assert survival_of(combat, "enemy:Braum")["projectile_defense_blocked"] == [
        {"time": 0.0, "source": "W", "mode": "full_block"}
    ]


def test_d2_empty_selection_destroys_all_marked_projectiles():
    """Yasuo W with empty selection destroys every marked projectile in the
    window, across slots, with no use cap."""
    combat = _calculate(
        {
            **_ezreal_timed(),
            "enemies": [
                _yasuo(
                    {
                        "w_active": True,
                        "w_active_seconds": 4.0,
                        "w_blocked_skillshots": [],
                    }
                )
            ],
        }
    )
    destroyed = []
    for source in ("W", "Q", "E", "R"):
        destroyed.extend(
            event
            for event in _events(
                combat, attacker="main", target="enemy:Yasuo", source=source
            )
            if event.get("projectile_defense")
        )
    assert sorted(event["time"] for event in destroyed) == [
        0.0,
        0.25,
        0.5,
        0.75,
        3.5,
    ]
    for event in destroyed:
        assert event["projectile_defense"]["mode"] == "destroyed"
        assert event["skipped_reason"] == "yasuo_wind_wall"
        assert event["damage"] == pytest.approx(0.0)
    # The cast after the window passes untouched.
    q_later = _events(combat, attacker="main", target="enemy:Yasuo", source="Q")[-1]
    assert q_later["time"] == pytest.approx(6.75)
    assert q_later["damage"] == pytest.approx(133.9)
    assert "projectile_defense" not in q_later
    blocked = survival_of(combat, "enemy:Yasuo")["projectile_defense_blocked"]
    assert len(blocked) == 5


def test_d2_selection_matching_is_case_insensitive_and_attacker_prefixed():
    """Source-slot matching accepts lowercase slots and 'Champion:Slot'
    forms (candidates are built from source_key + attacker identity)."""
    for selection in (["q"], ["Ezreal:Q"]):
        combat = _calculate(
            {
                **_ezreal_timed(),
                "enemies": [
                    _braum(
                        {
                            "e_active": True,
                            "e_active_seconds": 4.0,
                            "e_blocked_skillshots": selection,
                        }
                    )
                ],
            }
        )
        q_first = _events(combat, attacker="main", target="enemy:Braum", source="Q")[0]
        assert q_first["projectile_defense"]["mode"] == "full_block"


def test_d2_defense_is_per_target():
    """A defense belongs to its owning participant: only the Braum enemy's
    incoming events are filtered; the other enemy is untouched."""
    combat = _calculate(
        {
            **_ezreal_timed(),
            "enemies": [
                _braum(
                    {
                        "e_active": True,
                        "e_active_seconds": 4.0,
                        "e_blocked_skillshots": ["Q"],
                    }
                ),
                _enemy(
                    "Aatrox",
                    ability_ranks={"Q": 0, "W": 0, "E": 0, "R": 0},
                ),
            ],
        }
    )
    braum_q = _events(combat, attacker="main", target="enemy:Braum", source="Q")[0]
    aatrox_q = _events(combat, attacker="main", target="enemy:Aatrox", source="Q")[0]
    assert braum_q["projectile_defense"]["mode"] == "full_block"
    assert aatrox_q["damage"] == pytest.approx(127.8)
    assert "projectile_defense" not in aatrox_q
    assert survival_of(combat, "enemy:Aatrox")["projectile_defense"] is None
    assert survival_of(combat, "enemy:Aatrox")["projectile_defense_blocked"] == []


# ---------------------------------------------------------------------------
# Dimension 3 — selection: source slots vs event ids
# ---------------------------------------------------------------------------


def test_d3_source_slot_selection_is_declared_and_receipted():
    """Source-slot selection is the current runtime's only selection mode;
    the public defense receipt echoes the selected slots."""
    combat = _calculate(
        {
            **_ezreal_timed(),
            "enemies": [
                _braum(
                    {
                        "e_active": True,
                        "e_active_seconds": 4.0,
                        "e_blocked_skillshots": ["Q"],
                    }
                )
            ],
        }
    )
    defense = survival_of(combat, "enemy:Braum")["projectile_defense"]
    assert defense["blocked_sources"] == ["Q"]
    assert defense["requires_skillshot"] is True


def test_d3_event_id_selection_blocks_exact_packets():
    """Event-ID selection is a declared option: ``e_blocked_event_ids``
    selects individual incoming packets by their public ``event_id``
    (``main:enemy:Braum:4`` = the second Q in a 4.0 s fight), so only that
    packet is eligible — the first Q passes untouched."""
    combat = _calculate(
        {
            **_ezreal_timed(duration=4.0),
            "enemies": [
                _braum(
                    {
                        "e_active": True,
                        "e_active_seconds": 4.0,
                        "e_blocked_skillshots": [],
                        "e_blocked_event_ids": ["main:enemy:Braum:4"],
                    }
                )
            ],
        }
    )
    q_events = sorted(
        _events(combat, attacker="main", target="enemy:Braum", source="Q"),
        key=_BY_TIME,
    )
    first, second = q_events
    assert first["event_id"] == "main:enemy:Braum:1"
    assert first["time"] == pytest.approx(0.25)
    assert first["damage"] == pytest.approx(127.8)
    assert "projectile_defense" not in first
    assert second["event_id"] == "main:enemy:Braum:4"
    assert second["time"] == pytest.approx(3.5)
    assert second["damage"] == pytest.approx(0.0)
    assert second["projectile_defense"]["mode"] == "full_block"
    survival = survival_of(combat, "enemy:Braum")
    assert survival["projectile_defense_blocked"] == [
        {"time": 3.5, "source": "Q", "mode": "full_block"}
    ]
    assert survival["projectile_defense"]["blocked_event_ids"] == ["main:enemy:Braum:4"]


def test_d3_mixed_slot_and_event_id_selection_is_a_union():
    """Mixing slot and event-id selection is representable: eligibility is
    the union (slot match OR event-id match).  W (slot) consumes the first
    use at 0.0; the event-id-selected Q at 3.5 is the next eligible packet
    and is reduced; the first Q (no match) passes untouched."""
    combat = _calculate(
        {
            **_ezreal_timed(duration=4.0),
            "enemies": [
                _braum(
                    {
                        "e_active": True,
                        "e_active_seconds": 4.0,
                        "e_blocked_skillshots": ["W"],
                        "e_blocked_event_ids": ["main:enemy:Braum:4"],
                    }
                )
            ],
        }
    )
    w_first = _events(combat, attacker="main", target="enemy:Braum", source="W")[0]
    assert w_first["projectile_defense"]["mode"] == "full_block"
    assert w_first["damage"] == pytest.approx(0.0)
    q_events = sorted(
        _events(combat, attacker="main", target="enemy:Braum", source="Q"),
        key=_BY_TIME,
    )
    first, second = q_events
    assert first["time"] == pytest.approx(0.25)
    assert first["damage"] == pytest.approx(127.8)
    assert "projectile_defense" not in first
    assert second["time"] == pytest.approx(3.5)
    assert second["damage"] == pytest.approx(57.5)
    assert second["projectile_defense"]["mode"] == "reduced"
    assert second["projectile_defense"]["reduction"] == pytest.approx(0.55)
    survival = survival_of(combat, "enemy:Braum")
    assert survival["projectile_defense_blocked"] == [
        {"time": 0.0, "source": "W", "mode": "full_block"}
    ]
    assert survival["projectile_defense"]["blocked_event_ids"] == ["main:enemy:Braum:4"]


# ---------------------------------------------------------------------------
# Dimension 4 — limited uptime (window boundaries)
# ---------------------------------------------------------------------------


def test_d4_event_before_window_start_passes():
    combat = _calculate(
        {
            **_ezreal_timed(),
            "enemies": [
                _braum(
                    {
                        "e_active": True,
                        "e_active_from": 1.0,
                        "e_active_seconds": 0.5,
                        "e_blocked_skillshots": ["Q"],
                    }
                )
            ],
        }
    )
    q_first = _events(combat, attacker="main", target="enemy:Braum", source="Q")[0]
    assert q_first["time"] == pytest.approx(0.25)
    assert q_first["damage"] == pytest.approx(127.8)
    assert "projectile_defense" not in q_first
    assert survival_of(combat, "enemy:Braum")["projectile_defense_blocked"] == []


def test_d4_event_exactly_at_window_start_is_included():
    """The window start is inclusive: an event at exactly t == start is
    eligible."""
    combat = _calculate(
        {
            **_ezreal_timed(),
            "enemies": [
                _braum(
                    {
                        "e_active": True,
                        "e_active_from": 0.25,
                        "e_active_seconds": 4.0,
                        "e_blocked_skillshots": ["Q"],
                    }
                )
            ],
        }
    )
    q_first = _events(combat, attacker="main", target="enemy:Braum", source="Q")[0]
    assert q_first["time"] == pytest.approx(0.25)
    assert q_first["projectile_defense"]["mode"] == "full_block"
    assert q_first["damage"] == pytest.approx(0.0)


def test_d4_event_exactly_at_window_end_is_excluded():
    """The window end is exclusive: an event at exactly t == until is NOT
    eligible."""
    combat = _calculate(
        {
            **_ezreal_timed(),
            "enemies": [
                _braum(
                    {
                        "e_active": True,
                        "e_active_from": 0.0,
                        "e_active_seconds": 0.25,
                        "e_blocked_skillshots": ["Q"],
                    }
                )
            ],
        }
    )
    q_first = _events(combat, attacker="main", target="enemy:Braum", source="Q")[0]
    assert q_first["time"] == pytest.approx(0.25)
    assert q_first["damage"] == pytest.approx(127.8)
    assert "projectile_defense" not in q_first
    assert survival_of(combat, "enemy:Braum")["projectile_defense_blocked"] == []


def test_d4_event_after_window_end_passes():
    combat = _calculate(
        {
            **_ezreal_timed(),
            "enemies": [
                _braum(
                    {
                        "e_active": True,
                        "e_active_from": 0.0,
                        "e_active_seconds": 0.5,
                        "e_blocked_skillshots": ["Q"],
                    }
                )
            ],
        }
    )
    q_events = sorted(
        _events(combat, attacker="main", target="enemy:Braum", source="Q"),
        key=_BY_TIME,
    )
    assert q_events[0]["time"] == pytest.approx(0.25)
    assert q_events[0]["projectile_defense"]["mode"] == "full_block"
    assert q_events[1]["time"] == pytest.approx(3.5)
    assert q_events[1]["damage"] == pytest.approx(127.8)
    assert "projectile_defense" not in q_events[1]


def test_d4_zero_active_seconds_uses_source_rank_duration():
    """e_active_seconds == 0 means 'use the sourced rank duration'
    (rank 5 Barrier Duration = 4.0 s)."""
    combat = _calculate(
        {
            **_ezreal_timed(),
            "enemies": [
                _braum(
                    {
                        "e_active": True,
                        "e_active_from": 0.0,
                        "e_active_seconds": 0.0,
                        "e_blocked_skillshots": ["Q"],
                    }
                )
            ],
        }
    )
    defense = survival_of(combat, "enemy:Braum")["projectile_defense"]
    assert defense["start"] == pytest.approx(0.0)
    assert defense["until"] == pytest.approx(4.0)
    q_second = _events(combat, attacker="main", target="enemy:Braum", source="Q")[1]
    assert q_second["time"] == pytest.approx(3.5)
    assert q_second["projectile_defense"]["mode"] == "reduced"


def test_d4_requested_duration_clamps_to_source_rank_duration():
    """A requested duration above the rank's sourced duration clamps to the
    source value (rank 1: 3.0 s, reduction 35%)."""
    combat = _calculate(
        {
            **_ezreal_timed(),
            "enemies": [
                _braum(
                    {
                        "e_active": True,
                        "e_active_from": 0.0,
                        "e_active_seconds": 3.5,
                        "e_blocked_skillshots": ["Q"],
                    },
                    ability_ranks={"Q": 0, "W": 0, "E": 1, "R": 0},
                )
            ],
        }
    )
    defense = survival_of(combat, "enemy:Braum")["projectile_defense"]
    assert defense["until"] == pytest.approx(3.0)
    assert defense["damage_reduction"] == pytest.approx(0.35)
    q_events = sorted(
        _events(combat, attacker="main", target="enemy:Braum", source="Q"),
        key=_BY_TIME,
    )
    assert q_events[0]["projectile_defense"]["mode"] == "full_block"
    # The 3.5 s hit is outside the clamped [0, 3.0) window.
    assert q_events[1]["time"] == pytest.approx(3.5)
    assert q_events[1]["damage"] == pytest.approx(127.8)
    assert "projectile_defense" not in q_events[1]


def test_d4_out_of_range_duration_is_rejected():
    """Option bounds enforce the sourced maximum: oversized durations are
    rejected (400), not silently clamped, at the public API."""
    status, body = _reject(
        {
            **_ezreal_timed(duration=4.0),
            "enemies": [
                _braum(
                    {
                        "e_active": True,
                        "e_active_seconds": 4.5,
                        "e_blocked_skillshots": ["Q"],
                    }
                )
            ],
        }
    )
    assert status == 400
    assert "e_active_seconds must be between 0.0 and 4.0" in body["error"]
    status, body = _reject(
        {
            **_ezreal_timed(duration=4.0),
            "enemies": [
                _yasuo(
                    {
                        "w_active": True,
                        "w_active_seconds": 10.0,
                        "w_blocked_skillshots": ["Q"],
                    }
                )
            ],
        }
    )
    assert status == 400
    assert "w_active_seconds must be between 0.0 and 4.0" in body["error"]


# ---------------------------------------------------------------------------
# Dimension 5 — uses (finite first-use, destruction without cap)
# ---------------------------------------------------------------------------


def test_d5_braum_reduction_value_scales_with_rank():
    """Reduction at rank: 35% at rank 1, 55% at rank 5, from the sourced
    atom (3e8de1fe75f419da)."""
    for rank, expected in ((1, 0.35), (5, 0.55)):
        combat = _calculate(
            {
                **_ezreal_timed(),
                "enemies": [
                    _braum(
                        {
                            "e_active": True,
                            "e_active_seconds": 4.0,
                            "e_blocked_skillshots": [],
                        },
                        ability_ranks={"Q": 0, "W": 0, "E": rank, "R": 0},
                    )
                ],
            }
        )
        defense = survival_of(combat, "enemy:Braum")["projectile_defense"]
        assert defense["damage_reduction"] == pytest.approx(expected)
        # W (0.0 s) consumes the first use; Q (0.25 s) is the first reduced
        # selected hit at the ranked value.
        q_first = _events(combat, attacker="main", target="enemy:Braum", source="Q")[0]
        assert q_first["projectile_defense"]["mode"] == "reduced"
        assert q_first["projectile_defense"]["reduction"] == pytest.approx(expected)
        assert q_first["projectile_defense"]["mitigated"] > 0.0


def test_d5_braum_full_block_is_a_single_first_use():
    """Composition rule 'finite uses / first-valid-hit': exactly one full
    block per window; every later selected hit is reduced."""
    combat = _calculate(
        {
            **_ezreal_timed(),
            "enemies": [
                _braum(
                    {
                        "e_active": True,
                        "e_active_seconds": 4.0,
                        "e_blocked_skillshots": [],
                    }
                )
            ],
        }
    )
    receipts = [
        event.get("projectile_defense")
        for event in _events(combat, attacker="main", target="enemy:Braum", source="Q")
    ]
    assert [receipt["mode"] for receipt in receipts if receipt] == [
        "reduced",
        "reduced",
    ]
    blocked = survival_of(combat, "enemy:Braum")["projectile_defense_blocked"]
    assert [entry["mode"] for entry in blocked] == ["full_block"]
    assert blocked[0]["source"] == "W"  # the first eligible packet consumed it


def test_d5_yasuo_destroys_every_selected_projectile_without_cap():
    """Composition rule 'destruction': Yasuo W has no use counter; every
    selected projectile in the window is destroyed."""
    combat = _calculate(
        {
            **_ezreal_timed(),
            "enemies": [
                _yasuo(
                    {
                        "w_active": True,
                        "w_active_seconds": 4.0,
                        "w_blocked_skillshots": ["Q"],
                    }
                )
            ],
        }
    )
    q_events = sorted(
        _events(combat, attacker="main", target="enemy:Yasuo", source="Q"),
        key=_BY_TIME,
    )
    assert q_events[0]["projectile_defense"]["mode"] == "destroyed"
    assert q_events[1]["projectile_defense"]["mode"] == "destroyed"
    assert q_events[2]["time"] == pytest.approx(6.75)
    assert "projectile_defense" not in q_events[2]
    blocked = survival_of(combat, "enemy:Yasuo")["projectile_defense_blocked"]
    assert [entry["time"] for entry in blocked] == [0.25, 3.5]


def test_d5_control_only_packet_can_consume_the_full_block():
    """Composition rule 'control-only packets': a zero-damage control
    packet is still eligible for the first-use full block (Darius E
    airborne); the block then suppresses the CC entirely."""
    combat = _calculate(
        {
            "champion": "Darius",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 8,
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
            "enemies": [
                _braum(
                    {
                        "e_active": True,
                        "e_active_seconds": 4.0,
                        "e_blocked_skillshots": ["E"],
                    }
                )
            ],
        }
    )
    e_control = _events(combat, attacker="main", target="enemy:Braum", source="E")
    assert len(e_control) == 1
    event = e_control[0]
    assert event["cc_kind"] == "airborne"
    assert event["cc_duration"] == pytest.approx(1.0)
    assert event["projectile_defense"]["mode"] == "full_block"
    assert event["skipped_reason"] == "braum_unbreakable"
    survival = survival_of(combat, "enemy:Braum")
    assert survival["projectile_defense_blocked"] == [
        {"time": 0.0, "source": "E", "mode": "full_block"}
    ]
    assert survival["crowd_control_intervals"] == []


def test_d5_control_carrying_hit_consumes_first_use_and_cc_is_skipped():
    """A control-carrying hit (Ahri E charm + damage) consumes the first
    use: damage zeroed and the charm never lands; a later cast outside the
    window passes with full damage and full CC."""
    combat = _calculate(
        {
            "champion": "Ahri",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 20,
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
            "enemies": [
                _braum(
                    {
                        "e_active": True,
                        "e_active_seconds": 4.0,
                        "e_blocked_skillshots": ["E"],
                    }
                )
            ],
        }
    )
    e_events = sorted(
        _events(combat, attacker="main", target="enemy:Braum", source="E"),
        key=_BY_TIME,
    )
    first, later = e_events
    assert first["time"] == pytest.approx(0.0)
    assert first["damage"] == pytest.approx(0.0)
    assert first["projectile_defense"]["mode"] == "full_block"
    assert first["cc_kind"] == "immobilize"
    assert later["time"] == pytest.approx(12.25)
    assert later["damage"] > 0.0
    assert "projectile_defense" not in later
    assert later["cc_kind"] == "immobilize"
    survival = survival_of(combat, "enemy:Braum")
    assert survival["projectile_defense_blocked"] == [
        {"time": 0.0, "source": "E", "mode": "full_block"}
    ]
    # Only the later (unblocked) charm lands.
    assert survival["crowd_control_intervals"] == [
        {
            "recipient": "enemy:Braum",
            "kind": "immobilize",
            "start": 12.25,
            "end": 14.05,
            "source": "E",
        }
    ]


# ---------------------------------------------------------------------------
# Dimension 6 — same-time ordering and gate ordering
# ---------------------------------------------------------------------------


def test_d6_same_timestamp_selection_is_deterministic():
    """Two+ selected events at an identical timestamp resolve by the walk's
    deterministic total order (time, phase, sequence): the first sequence
    wins the full block, the rest are reduced."""
    combat = _calculate(
        {
            "champion": "Ezreal",
            "level": 18,
            "items": [],
            "fight_mode": "one_rotation",
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
            "enemies": [
                _braum(
                    {
                        "e_active": True,
                        "e_active_seconds": 4.0,
                        "e_blocked_skillshots": [],
                    }
                )
            ],
        }
    )
    events = sorted(
        _events(combat, attacker="main", target="enemy:Braum", source=None),
        key=lambda event: (event["time"], event["sequence"]),
    )
    assert len(events) == 4
    assert all(event["time"] == pytest.approx(0.0) for event in events)
    modes = [
        event["projectile_defense"]["mode"] if event.get("projectile_defense") else None
        for event in events
    ]
    assert modes[0] == "full_block"
    assert modes[1:] == ["reduced", "reduced", "reduced"]
    assert [event["source"] for event in events] == ["W", "Q", "E", "R"]
    assert survival_of(combat, "enemy:Braum")["projectile_defense_blocked"] == [
        {"time": 0.0, "source": "W", "mode": "full_block"}
    ]


def test_d6_target_state_gate_runs_before_projectile_defense():
    """Gate order: target stasis skips the packet before the defense can
    consume its first use — the stasis-skipped hit carries no receipt and
    the full block is still available after stasis ends."""
    combat = _calculate(
        {
            **_ezreal_timed(),
            "enemies": [
                _braum(
                    {
                        "e_active": True,
                        "e_active_seconds": 4.0,
                        "e_blocked_skillshots": ["Q"],
                    },
                    items=["Zhonya's Hourglass"],
                    item_options={"Zhonya's Hourglass": {"stasis_active_seconds": 2}},
                )
            ],
        }
    )
    q_events = sorted(
        _events(combat, attacker="main", target="enemy:Braum", source="Q"),
        key=_BY_TIME,
    )
    in_stasis, after_stasis, _ = q_events
    assert in_stasis["time"] == pytest.approx(0.25)
    assert in_stasis["skipped_reason"] == "target_state_blocked"
    assert "projectile_defense" not in in_stasis
    assert after_stasis["time"] == pytest.approx(3.5)
    assert after_stasis["projectile_defense"]["mode"] == "full_block"
    assert survival_of(combat, "enemy:Braum")["projectile_defense_blocked"] == [
        {"time": 3.5, "source": "Q", "mode": "full_block"}
    ]


def test_d6_attacker_state_gate_runs_after_full_block_prepare():
    """Gate order: the full-block prepare runs before the attacker-state
    gate.  A CC'd attacker's hit still consumes the first use (receipt
    present, damage zeroed, later hit reduced) — the kernel should decide
    whether a state-skipped packet may consume a use."""
    combat = _calculate(
        {
            **_ezreal_timed(),
            "enemies": [
                _braum(
                    {
                        "e_active": True,
                        "e_active_seconds": 4.0,
                        "e_blocked_skillshots": ["Q"],
                    },
                    ability_ranks={"Q": 0, "W": 0, "E": 5, "R": 3},
                )
            ],
        }
    )
    q_events = sorted(
        _events(combat, attacker="main", target="enemy:Braum", source="Q"),
        key=_BY_TIME,
    )
    cc_hit, later, after = q_events
    assert cc_hit["time"] == pytest.approx(0.25)
    assert cc_hit["projectile_defense"]["mode"] == "full_block"
    assert cc_hit["skipped_reason"] == "attacker_state_blocked"
    assert later["time"] == pytest.approx(3.5)
    assert later["projectile_defense"]["mode"] == "reduced"
    assert after["time"] == pytest.approx(6.75)
    assert "projectile_defense" not in after
    assert survival_of(combat, "enemy:Braum")["projectile_defense_blocked"] == [
        {"time": 0.25, "source": "Q", "mode": "full_block"}
    ]


# ---------------------------------------------------------------------------
# Dimension 7 — denied interactions
# ---------------------------------------------------------------------------


def test_d7_true_damage_bypasses_braum_e():
    """True damage is not full-blocked or reduced by Braum E (damage_type
    true and not full_block_all): the selected Sett W lands unchanged with
    no receipt."""
    combat = _calculate(
        {
            "champion": "Sett",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 6,
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
            "enemies": [
                _braum(
                    {
                        "e_active": True,
                        "e_active_seconds": 4.0,
                        "e_blocked_skillshots": ["W"],
                    }
                )
            ],
        }
    )
    w_events = _events(combat, attacker="main", target="enemy:Braum", source="W")
    assert w_events
    for event in w_events:
        assert event["damage_type"] == "true"
        assert event["skillshot"] is True
        assert event["damage"] == pytest.approx(160.0)
        assert "projectile_defense" not in event
    assert survival_of(combat, "enemy:Braum")["projectile_defense_blocked"] == []


def test_d7_true_damage_is_destroyed_by_yasuo_w():
    """NEW-CONTRACT (true-damage policy): the destroy branch has no
    true-damage exclusion, so Wind Wall currently destroys selected
    true-damage skillshots (Sett W).  The kernel must make the
    true-damage/destruction policy explicit for both defenses."""
    combat = _calculate(
        {
            "champion": "Sett",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 6,
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
            "enemies": [
                _yasuo(
                    {
                        "w_active": True,
                        "w_active_seconds": 4.0,
                        "w_blocked_skillshots": ["W"],
                    }
                )
            ],
        }
    )
    w_first = _events(combat, attacker="main", target="enemy:Yasuo", source="W")[0]
    assert w_first["damage_type"] == "true"
    assert w_first["projectile_defense"]["mode"] == "destroyed"
    assert w_first["skipped_reason"] == "yasuo_wind_wall"
    assert w_first["damage"] == pytest.approx(0.0)


def test_d7_area_skillshot_against_braum_uses_projectile_reduction():
    """An area-marked skillshot (Ezreal R) is a projectile first: the
    ranked projectile reduction applies (449.1 x 0.45 = 202.1), and the
    typed delivery receipt declares both classes (area + projectile)."""
    combat = _calculate(
        {
            **_ezreal_timed(),
            "enemies": [
                _braum(
                    {
                        "e_active": True,
                        "e_active_seconds": 4.0,
                        "e_blocked_skillshots": [],
                    }
                )
            ],
        }
    )
    r_first = _events(combat, attacker="main", target="enemy:Braum", source="R")[0]
    assert r_first["skillshot"] is True
    assert r_first["area_damage"] is True
    assert r_first["damage"] == pytest.approx(202.1)
    receipt = r_first["projectile_defense"]
    assert receipt["mode"] == "reduced"
    assert receipt["reduction"] == pytest.approx(0.55)
    assert receipt["mitigated"] == pytest.approx(247.0, abs=0.2)
    assert receipt["delivery"]["classes"] == ["area", "projectile"]
    assert receipt["delivery"]["unknown"] is False
    assert receipt["eligible"] is True


def test_d7_true_damage_part_skips_the_area_reduction_receipt():
    """Within one cast, the true-damage part is never receipted (Ahri Q):
    the outgoing area+projectile magic part is reduced at the ranked
    projectile value (0.55), while the return true part passes cleanly."""
    combat = _calculate(
        {
            "champion": "Ahri",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 6,
            "include_auto_attacks": False,
            "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
            "enemies": [
                _braum(
                    {
                        "e_active": True,
                        "e_active_seconds": 4.0,
                        "e_blocked_skillshots": ["E", "Q"],
                    }
                )
            ],
        }
    )
    q_events = _events(combat, attacker="main", target="enemy:Braum", source="Q")
    magic_part = next(event for event in q_events if event["damage_type"] == "magic")
    true_part = next(event for event in q_events if event["damage_type"] == "true")
    assert magic_part["projectile_defense"]["mode"] == "reduced"
    assert magic_part["projectile_defense"]["reduction"] == pytest.approx(0.55)
    assert magic_part["damage"] == pytest.approx(36.4)
    assert magic_part["projectile_defense"]["delivery"]["classes"] == [
        "area",
        "projectile",
    ]
    assert true_part["damage"] == pytest.approx(135.0)
    assert "projectile_defense" not in true_part


# ---------------------------------------------------------------------------
# Dimension 8 — receipt-vs-result parity
# ---------------------------------------------------------------------------


def test_d8_blocked_list_matches_per_event_receipts():
    """survival.projectile_defense_blocked mirrors exactly the per-event
    receipts whose mode is full_block or destroyed (reduced events are
    not listed), for both defense kinds."""
    for enemy, options, target in (
        (
            "Braum",
            {
                "e_active": True,
                "e_active_seconds": 4.0,
                "e_blocked_skillshots": ["Q"],
            },
            "enemy:Braum",
        ),
        (
            "Yasuo",
            {
                "w_active": True,
                "w_active_seconds": 4.0,
                "w_blocked_skillshots": ["Q"],
            },
            "enemy:Yasuo",
        ),
    ):
        combat = _calculate(
            {
                **_ezreal_timed(),
                "enemies": [
                    _enemy(
                        enemy,
                        options=options,
                        ability_ranks=(
                            {"Q": 0, "W": 0, "E": 5, "R": 0}
                            if enemy == "Braum"
                            else {"Q": 0, "W": 5, "E": 0, "R": 0}
                        ),
                    )
                ],
            }
        )
        listed = []
        for event in _events(combat, attacker="main", target=target, source=None):
            receipt = event.get("projectile_defense")
            if receipt is None:
                continue
            assert receipt["source"] in {
                "Braum E · Unbreakable",
                "Yasuo W · Wind Wall",
            }
            # Contract item 8: every receipt — full_block, reduced, and
            # destroyed alike — carries the typed delivery declaration and
            # the eligibility verdict; the use counter is only meaningful
            # for finite-use full-block defenses.
            assert receipt["eligible"] is True
            assert receipt["delivery"]["unknown"] is False
            assert receipt["delivery"]["unknown_markers"] == []
            assert "projectile" in receipt["delivery"]["classes"]
            if receipt["mode"] in ("full_block", "destroyed"):
                listed.append(
                    {
                        "time": round(float(event["time"]), 3),
                        "source": event["source"],
                        "mode": receipt["mode"],
                    }
                )
            else:
                assert receipt["mode"] == "reduced"
        assert survival_of(combat, target)["projectile_defense_blocked"] == listed


def test_d8_full_block_events_have_zero_damage():
    """Every full_block receipt corresponds to a zero-damage event."""
    combat = _calculate(
        {
            **_ezreal_timed(),
            "enemies": [
                _braum(
                    {
                        "e_active": True,
                        "e_active_seconds": 4.0,
                        "e_blocked_skillshots": ["Q"],
                    }
                )
            ],
        }
    )
    for event in _events(combat, attacker="main", target="enemy:Braum", source="Q"):
        receipt = event.get("projectile_defense")
        if receipt and receipt["mode"] == "full_block":
            assert event["damage"] == pytest.approx(0.0)


def test_d8_destroyed_events_carry_kind_skipped_reason():
    """Every destroyed event is skipped with the defense kind as the
    skipped_reason."""
    combat = _calculate(
        {
            **_ezreal_timed(),
            "enemies": [
                _yasuo(
                    {
                        "w_active": True,
                        "w_active_seconds": 4.0,
                        "w_blocked_skillshots": ["Q"],
                    }
                )
            ],
        }
    )
    destroyed = [
        event
        for event in _events(combat, attacker="main", target="enemy:Yasuo", source="Q")
        if event.get("projectile_defense", {}).get("mode") == "destroyed"
    ]
    assert destroyed
    for event in destroyed:
        assert event["skipped_reason"] == "yasuo_wind_wall"
        assert event["damage"] == pytest.approx(0.0)


def test_d8_reduced_events_preserve_pair_math_and_listing():
    """A reduced event's receipt preserves the pair engine's math:
    damage + mitigated == pair_damage, and damage == pair_damage x
    (1 - reduction). Reduced events never enter the blocked list."""
    combat = _calculate(
        {
            **_ezreal_timed(),
            "enemies": [
                _braum(
                    {
                        "e_active": True,
                        "e_active_seconds": 4.0,
                        "e_blocked_skillshots": ["Q"],
                    }
                )
            ],
        }
    )
    reduced = next(
        event
        for event in _events(combat, attacker="main", target="enemy:Braum", source="Q")
        if event.get("projectile_defense", {}).get("mode") == "reduced"
    )
    receipt = reduced["projectile_defense"]
    assert receipt["reduction"] == pytest.approx(0.55)
    # The pair engine's post-mitigation amount is preserved: the reduced
    # damage plus the receipted mitigation restores the pre-defense value,
    # and the public pair_damage reflects the post-defense value.
    before = reduced["damage"] + receipt["mitigated"]
    assert before == pytest.approx(127.8, abs=0.2)
    assert reduced["damage"] == pytest.approx(reduced["pair_damage"], abs=0.2)
    assert receipt["mitigated"] == pytest.approx(before * receipt["reduction"], abs=0.2)
    blocked = survival_of(combat, "enemy:Braum")["projectile_defense_blocked"]
    assert all(entry["mode"] != "reduced" for entry in blocked)


def test_d8_defense_receipts_carry_sourced_atom_hashes():
    """Provenance: the public defense receipt keeps the exact sourced atoms
    (Barrier Duration d6f463652bc9c57b, Damage reduction 3e8de1fe75f419da,
    Wind Wall active duration df1b544914798426)."""
    braum_combat = _calculate(
        {
            **_ezreal_timed(),
            "enemies": [
                _braum(
                    {
                        "e_active": True,
                        "e_active_seconds": 4.0,
                        "e_blocked_skillshots": ["Q"],
                    }
                )
            ],
        }
    )
    atoms = survival_of(braum_combat, "enemy:Braum")["projectile_defense"][
        "source_atoms"
    ]
    assert [atom["hash"] for atom in atoms] == [
        "d6f463652bc9c57b",
        "3e8de1fe75f419da",
    ]
    yasuo_combat = _calculate(
        {
            **_ezreal_timed(),
            "enemies": [
                _yasuo(
                    {
                        "w_active": True,
                        "w_active_seconds": 4.0,
                        "w_blocked_skillshots": ["Q"],
                    }
                )
            ],
        }
    )
    atoms = survival_of(yasuo_combat, "enemy:Yasuo")["projectile_defense"][
        "source_atoms"
    ]
    assert [atom["hash"] for atom in atoms] == ["df1b544914798426"]
