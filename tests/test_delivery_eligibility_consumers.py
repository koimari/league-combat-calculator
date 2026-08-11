"""P2 delivery/eligibility consumers: Braum E + Yasuo W recomposition.

Integration tests through the public API (``src.app`` ->
``POST /api/calculate``) for the recomposed defense path: the walk
applies the kernel's eligibility decisions with the exact previous
applied semantics (first-block-then-reduce for Braum, destroy for
Yasuo), while the receipts carry the new delivery/eligibility/uses
fields and the new event-id selection option.

Pinned companion suite: tests/test_delivery_interaction_eligibility.py
(the RLM-2 acceptance matrix, owned by the test-matrix child).
"""

import pytest

from src.app import app
from src.calculator.delivery_eligibility import (
    DefenseEligibility,
    DeliveryAcceptance,
    DefenseWindow,
    SourceSelection,
)


def _calculate(payload: dict) -> dict:
    app.config["TESTING"] = True
    response = app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_data(as_text=True)[:500]
    return response.get_json()["combat"]


def _events(combat: dict, *, target: str, source: str) -> list[dict]:
    return [
        event
        for event in combat["events"]
        if event.get("target") == target and event.get("source") == source
    ]


def _survival(combat: dict, participant_id: str) -> dict:
    return next(
        row["survival"]
        for row in combat["participants"]
        if row["participant_id"] == participant_id
    )


def _ezreal_timed(duration: float = 8.0) -> dict:
    return {
        "champion": "Ezreal",
        "level": 18,
        "items": [],
        "fight_mode": "time_based",
        "fight_duration": duration,
        "include_auto_attacks": False,
        "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
    }


# ---------------------------------------------------------------------------
# Receipts carry the new contract fields (delivery, eligibility, uses)
# ---------------------------------------------------------------------------


class TestNewReceiptFields:
    def test_braum_receipts_carry_delivery_eligibility_and_remaining_uses(self):
        combat = _calculate(
            {
                **_ezreal_timed(),
                "enemies": [
                    {
                        "champion": "Braum",
                        "level": 18,
                        "items": [],
                        "ability_ranks": {"Q": 0, "W": 0, "E": 5, "R": 0},
                        "champion_options": {
                            "e_active": True,
                            "e_active_seconds": 4.0,
                            "e_blocked_skillshots": ["Q"],
                        },
                    }
                ],
            }
        )
        q_events = sorted(
            _events(combat, target="enemy:Braum", source="Q"),
            key=lambda event: event["time"],
        )
        first, later = q_events[0], q_events[1]
        assert first["damage"] == pytest.approx(0.0)
        assert first["projectile_defense"]["mode"] == "full_block"
        assert first["projectile_defense"]["delivery"] == {
            "classes": ["projectile"],
            "unknown": False,
            "unknown_markers": [],
        }
        assert first["projectile_defense"]["eligible"] is True
        assert first["projectile_defense"]["remaining_uses"] == 0
        assert later["projectile_defense"]["mode"] == "reduced"
        assert later["projectile_defense"]["delivery"]["classes"] == ["projectile"]
        assert later["projectile_defense"]["remaining_uses"] == 0

        row = _survival(combat, "enemy:Braum")["projectile_defense"]
        assert row["remaining_uses"] == 0
        assert row["acceptance"]["accepts_deliveries"] == ["projectile"]
        assert row["composition"]["full_block"]["mode"] == "first"
        assert row["composition"]["full_block_uses"]["uses"] == 1
        assert [d["delivery"] for d in row["delivery_declarations"]] == [
            "projectile",
            "hitscan",
            "area",
            "targeted",
            "basic_attack",
            "damage_over_time",
        ]

    def test_yasuo_receipts_carry_unlimited_destruction(self):
        combat = _calculate(
            {
                **_ezreal_timed(),
                "enemies": [
                    {
                        "champion": "Yasuo",
                        "level": 18,
                        "items": [],
                        "ability_ranks": {"Q": 0, "W": 5, "E": 0, "R": 0},
                        "champion_options": {
                            "w_active": True,
                            "w_active_seconds": 4.0,
                            "w_blocked_skillshots": ["Q"],
                        },
                    }
                ],
            }
        )
        destroyed = [
            event
            for event in _events(combat, target="enemy:Yasuo", source="Q")
            if event.get("projectile_defense", {}).get("mode") == "destroyed"
        ]
        assert len(destroyed) == 2
        for event in destroyed:
            assert event["projectile_defense"]["eligible"] is True
            assert event["projectile_defense"]["delivery"]["classes"] == ["projectile"]
            assert event["projectile_defense"]["remaining_uses"] is None
        row = _survival(combat, "enemy:Yasuo")["projectile_defense"]
        assert row["remaining_uses"] is None
        assert row["composition"]["destroy"]["enabled"] is True

    def test_unused_defense_reports_full_remaining_uses(self):
        combat = _calculate(
            {
                **_ezreal_timed(),
                "enemies": [
                    {
                        "champion": "Braum",
                        "level": 18,
                        "items": [],
                        "ability_ranks": {"Q": 0, "W": 0, "E": 5, "R": 0},
                        "champion_options": {
                            "e_active": True,
                            "e_active_seconds": 4.0,
                            "e_blocked_skillshots": ["Never-Matched"],
                        },
                    }
                ],
            }
        )
        row = _survival(combat, "enemy:Braum")["projectile_defense"]
        # No incoming event matches the selection, so the one-use budget
        # is never spent.
        assert row["remaining_uses"] == 1
        assert _survival(combat, "enemy:Braum")["projectile_defense_blocked"] == []


# ---------------------------------------------------------------------------
# Event-id selection (new option)
# ---------------------------------------------------------------------------


class TestEventIdSelection:
    def test_braum_blocks_one_specific_event_id(self):
        combat = _calculate(
            {
                **_ezreal_timed(duration=4.0),
                "enemies": [
                    {
                        "champion": "Braum",
                        "level": 18,
                        "items": [],
                        "ability_ranks": {"Q": 0, "W": 0, "E": 5, "R": 0},
                        "champion_options": {
                            "e_active": True,
                            "e_active_seconds": 4.0,
                            "e_blocked_skillshots": [],
                            "e_blocked_event_ids": ["main:enemy:Braum:4"],
                        },
                    }
                ],
            }
        )
        q_events = sorted(
            _events(combat, target="enemy:Braum", source="Q"),
            key=lambda event: event["time"],
        )
        assert [event["event_id"] for event in q_events] == [
            "main:enemy:Braum:1",
            "main:enemy:Braum:4",
        ]
        first, selected = q_events
        # The first Q is NOT selected (its id is not in the list).
        assert first["damage"] > 0.0
        assert "projectile_defense" not in first
        # The specific second Q is fully blocked and consumes the one use.
        assert selected["damage"] == pytest.approx(0.0)
        assert selected["projectile_defense"]["mode"] == "full_block"
        assert selected["projectile_defense"]["remaining_uses"] == 0
        blocked = _survival(combat, "enemy:Braum")["projectile_defense_blocked"]
        assert blocked == [
            {"time": selected["time"], "source": "Q", "mode": "full_block"}
        ]

    def test_yasuo_destroys_selected_event_ids_only(self):
        combat = _calculate(
            {
                **_ezreal_timed(duration=4.0),
                "enemies": [
                    {
                        "champion": "Yasuo",
                        "level": 18,
                        "items": [],
                        "ability_ranks": {"Q": 0, "W": 5, "E": 0, "R": 0},
                        "champion_options": {
                            "w_active": True,
                            "w_active_seconds": 4.0,
                            "w_blocked_skillshots": [],
                            "w_blocked_event_ids": ["main:enemy:Yasuo:4"],
                        },
                    }
                ],
            }
        )
        q_events = sorted(
            _events(combat, target="enemy:Yasuo", source="Q"),
            key=lambda event: event["time"],
        )
        first, selected = q_events
        assert first["damage"] > 0.0
        assert "projectile_defense" not in first
        assert selected["damage"] == pytest.approx(0.0)
        assert selected["projectile_defense"]["mode"] == "destroyed"
        assert selected["skipped_reason"] == "yasuo_wind_wall"

    def test_mixed_slot_and_event_id_selection_is_a_union(self):
        combat = _calculate(
            {
                **_ezreal_timed(),
                "enemies": [
                    {
                        "champion": "Braum",
                        "level": 18,
                        "items": [],
                        "ability_ranks": {"Q": 0, "W": 0, "E": 5, "R": 0},
                        "champion_options": {
                            "e_active": True,
                            "e_active_seconds": 4.0,
                            "e_blocked_skillshots": ["W"],
                            "e_blocked_event_ids": ["main:enemy:Braum:4"],
                        },
                    }
                ],
            }
        )
        events = [
            event
            for event in combat["events"]
            if event.get("target") == "enemy:Braum"
            and event.get("source") in ("W", "Q")
        ]
        selected = [event for event in events if event.get("projectile_defense")]
        sources = sorted(event["source"] for event in selected)
        # W matches the slot; the second Q matches the event id.  The
        # first Q (id 1) is not selected and passes with full damage.
        assert sources == ["Q", "W"]
        q_first = next(
            event
            for event in events
            if event["source"] == "Q" and event["time"] == 0.25
        )
        assert "projectile_defense" not in q_first
        assert q_first["damage"] > 0.0

    def test_unmatched_event_ids_are_reported_on_the_row(self):
        combat = _calculate(
            {
                **_ezreal_timed(),
                "enemies": [
                    {
                        "champion": "Braum",
                        "level": 18,
                        "items": [],
                        "ability_ranks": {"Q": 0, "W": 0, "E": 5, "R": 0},
                        "champion_options": {
                            "e_active": True,
                            "e_active_seconds": 4.0,
                            "e_blocked_skillshots": [],
                            "e_blocked_event_ids": [
                                "main:enemy:Braum:4",
                                "main:enemy:Braum:999",
                            ],
                        },
                    }
                ],
            }
        )
        row = _survival(combat, "enemy:Braum")["projectile_defense"]
        assert row["blocked_event_ids"] == [
            "main:enemy:Braum:4",
            "main:enemy:Braum:999",
        ]
        assert row["blocked_event_ids_unmatched"] == ["main:enemy:Braum:999"]

    def test_event_id_options_are_declared_in_champion_metadata(self):
        from src.calculator.champions import get_champion_options_meta

        braum_keys = {
            option["key"] for option in get_champion_options_meta("Braum")["options"]
        }
        yasuo_keys = {
            option["key"] for option in get_champion_options_meta("Yasuo")["options"]
        }
        assert "e_blocked_event_ids" in braum_keys
        assert "w_blocked_event_ids" in yasuo_keys


# ---------------------------------------------------------------------------
# Window boundaries through the recomposed path
# ---------------------------------------------------------------------------


class TestWindowBoundaries:
    def test_start_inclusive(self):
        combat = _calculate(
            {
                **_ezreal_timed(),
                "enemies": [
                    {
                        "champion": "Braum",
                        "level": 18,
                        "items": [],
                        "ability_ranks": {"Q": 0, "W": 0, "E": 5, "R": 0},
                        "champion_options": {
                            "e_active": True,
                            "e_active_from": 0.25,
                            "e_active_seconds": 4.0,
                            "e_blocked_skillshots": ["Q"],
                        },
                    }
                ],
            }
        )
        q_events = sorted(
            _events(combat, target="enemy:Braum", source="Q"),
            key=lambda event: event["time"],
        )
        assert q_events[0]["projectile_defense"]["mode"] == "full_block"

    def test_end_exclusive(self):
        combat = _calculate(
            {
                **_ezreal_timed(),
                "enemies": [
                    {
                        "champion": "Braum",
                        "level": 18,
                        "items": [],
                        "ability_ranks": {"Q": 0, "W": 0, "E": 5, "R": 0},
                        "champion_options": {
                            "e_active": True,
                            "e_active_seconds": 0.25,
                            "e_blocked_skillshots": [],
                        },
                    }
                ],
            }
        )
        q_events = sorted(
            _events(combat, target="enemy:Braum", source="Q"),
            key=lambda event: event["time"],
        )
        # Q at 0.25 is exactly at the end (exclusive) -> passes.
        assert q_events[0]["damage"] > 0.0
        assert "projectile_defense" not in q_events[0]


# ---------------------------------------------------------------------------
# Area-marked skillshots now reduce with the projectile value (the one
# deliberate behavior fix: Braum intercepts Trueshot Barrage in-game)
# ---------------------------------------------------------------------------


class TestAreaSkillshotFix:
    def test_braum_reduces_area_marked_skillshot_with_rank_value(self):
        combat = _calculate(
            {
                **_ezreal_timed(),
                "enemies": [
                    {
                        "champion": "Braum",
                        "level": 18,
                        "items": [],
                        "ability_ranks": {"Q": 0, "W": 0, "E": 5, "R": 0},
                        "champion_options": {
                            "e_active": True,
                            "e_active_seconds": 4.0,
                            "e_blocked_skillshots": [],
                        },
                    }
                ],
            }
        )
        r_events = [
            event
            for event in combat["events"]
            if event.get("target") == "enemy:Braum" and event.get("source") == "R"
        ]
        reduced = next(
            event
            for event in r_events
            if event.get("projectile_defense", {}).get("mode") == "reduced"
        )
        assert reduced["skillshot"] is True
        assert reduced["area_damage"] is True
        # 449.1 x (1 - 0.55) = 202.1 — the projectile reduction, not 0.0.
        assert reduced["projectile_defense"]["reduction"] == pytest.approx(0.55)
        assert reduced["damage"] == pytest.approx(202.1, abs=0.2)

    def test_true_damage_part_still_passes_cleanly(self):
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
                    {
                        "champion": "Braum",
                        "level": 18,
                        "items": [],
                        "ability_ranks": {"Q": 0, "W": 0, "E": 5, "R": 0},
                        "champion_options": {
                            "e_active": True,
                            "e_active_seconds": 4.0,
                            "e_blocked_skillshots": ["E", "Q"],
                        },
                    }
                ],
            }
        )
        q_events = [
            event
            for event in combat["events"]
            if event.get("target") == "enemy:Braum" and event.get("source") == "Q"
        ]
        magic_part = next(
            event for event in q_events if event["damage_type"] == "magic"
        )
        true_part = next(event for event in q_events if event["damage_type"] == "true")
        assert magic_part["projectile_defense"]["mode"] == "reduced"
        assert magic_part["projectile_defense"]["reduction"] == pytest.approx(0.55)
        assert "projectile_defense" not in true_part
        assert true_part["damage"] == pytest.approx(135.0)


# ---------------------------------------------------------------------------
# Same-time determinism and uses through the recomposed path
# ---------------------------------------------------------------------------


class TestOrderingAndUses:
    def test_same_timestamp_first_use_is_deterministic(self):
        combat = _calculate(
            {
                "champion": "Ezreal",
                "level": 18,
                "items": [],
                "fight_mode": "one_rotation",
                "include_auto_attacks": False,
                "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
                "enemies": [
                    {
                        "champion": "Braum",
                        "level": 18,
                        "items": [],
                        "ability_ranks": {"Q": 0, "W": 0, "E": 5, "R": 0},
                        "champion_options": {
                            "e_active": True,
                            "e_active_seconds": 4.0,
                            "e_blocked_skillshots": [],
                        },
                    }
                ],
            }
        )
        blocked = _survival(combat, "enemy:Braum")["projectile_defense_blocked"]
        assert blocked == [{"time": 0.0, "source": "W", "mode": "full_block"}]

    def test_destroy_has_no_use_cap(self):
        combat = _calculate(
            {
                "champion": "Ezreal",
                "level": 18,
                "items": [],
                "fight_mode": "one_rotation",
                "include_auto_attacks": False,
                "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
                "enemies": [
                    {
                        "champion": "Yasuo",
                        "level": 18,
                        "items": [],
                        "ability_ranks": {"Q": 0, "W": 5, "E": 0, "R": 0},
                        "champion_options": {
                            "w_active": True,
                            "w_active_seconds": 4.0,
                            "w_blocked_skillshots": [],
                        },
                    }
                ],
            }
        )
        blocked = _survival(combat, "enemy:Yasuo")["projectile_defense_blocked"]
        assert [entry["source"] for entry in blocked] == ["W", "Q", "E", "R"]
        assert all(entry["mode"] == "destroyed" for entry in blocked)


# ---------------------------------------------------------------------------
# The kernel objects ride the shared survival state (both adapters)
# ---------------------------------------------------------------------------


class TestKernelStateWiring:
    def test_state_builds_typed_kernel_contracts(self):
        from src.calculator.data_fetcher import get_champion
        from src.calculator.survival.receipt_state import build_state

        class Defenses:
            starting_stasis_duration = 0.0
            starting_stasis_source = ""
            spell_shield_ready = False
            spell_shield_source = ""
            bloodthirster_shield_cap = 0.0
            bloodthirster_starting_shield = 0.0
            reactive_shield_amount = 0.0
            reactive_shield_damage_type = ""
            reactive_shield_duration = 0.0
            reactive_shield_cooldown = 0.0
            reactive_shield_source = ""
            incoming_damage_multiplier = 1.0
            incoming_damage_linger = 0.0
            incoming_damage_cooldown = 0.0
            incoming_damage_source = ""
            healing_received_multiplier = 1.0
            maw_lifeline_omnivamp_percent = 0.0
            revive_health_amount = 0.0
            revive_delay = 0.0
            revive_source = ""
            damage_deferral_fraction = 0.0
            magic_shield = 0.0
            physical_shield = 0.0
            general_shield = 0.0
            threshold_shield = 0.0
            threshold_health = 0.0
            max_health = 2000.0
            health = 2000.0
            venom_factor = 1.0

        class Combatant:
            participant_id = "enemy:Braum"
            level = 18
            stats = {
                "armor": 50.0,
                "magic_resistance": 40.0,
                "bonus_armor": 0.0,
                "bonus_magic_resistance": 0.0,
            }
            items = []
            defenses = Defenses()

            def __init__(self) -> None:
                self.champion_data = get_champion("Braum")
                self.request = type(
                    "R",
                    (),
                    {
                        "ability_ranks": {"Q": 0, "W": 0, "E": 5, "R": 0},
                        "champion_options": {
                            "e_active": True,
                            "e_active_seconds": 4.0,
                            "e_blocked_skillshots": ["Q"],
                        },
                    },
                )()

        state = build_state(Combatant())
        eligibility = state["projectile_defense_eligibility"]
        assert isinstance(eligibility, DefenseEligibility)
        assert eligibility.window.start == 0.0
        assert eligibility.window.until == 4.0
        assert eligibility.window.source_atoms[0]["hash"] == "d6f463652bc9c57b"
        assert eligibility.selection == SourceSelection(blocked_sources=("Q",))
        assert eligibility.acceptance == DeliveryAcceptance(requires_skillshot=True)
        assert state["projectile_defense_uses_remaining"] == 1
        assert state["projectile_defense_full_block_events"] == set()
        assert state["projectile_defense_blocked"] == []
