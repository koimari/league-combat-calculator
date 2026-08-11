"""Eclipse stack-source packet for DoT and crowd-control applications.

The certified path grants one ordinary stack per cast instance and enemy
champion.  Direct damage and reviewed control-only applications share the
same cast identity, so damage plus control from one cast stays one stack.

The Wiki authorizes DoT applications.  Its application timestamp is absent
from the generic event packet.  The engine therefore emits a named
zero-damage receipt and does not turn periodic ticks into stack events.
The desired DoT application behavior stays a strict expected failure until
a champion packet supplies that source-backed boundary.
"""

from types import SimpleNamespace

import pytest

from src.calculator.ability_spec import ControlEvent, DamagePart
from src.calculator.damage import (
    FightConfig,
    _stacked_champion_proc_times,
    calculate_fight_damage,
)
from src.calculator.item_effects import resolve_damage_effects


def _stats() -> dict:
    return {
        "attack_damage": 100.0,
        "ability_power": 0.0,
        "base_attack_damage": 100.0,
        "attack_speed": 1.0,
        "attack_speed_ratio": 0.625,
        "magic_penetration_flat": 0.0,
        "magic_penetration_percent": 0.0,
        "armor_penetration_percent": 0.0,
        "flat_armor_penetration": 0.0,
        "critical_strike_chance": 0.0,
        "is_melee": False,
        "level": 18,
        "bonus_attack_damage": 0.0,
    }


def _direct(name: str, *, time_offset: float | None = None) -> dict:
    return {
        "name": name,
        "rank": 1,
        "cooldown": 5.0,
        "physical_damage": 100.0,
        "parts": (DamagePart("physical", 100.0, time_offset=time_offset),),
        "total_raw": 100.0,
        "damage_type": "physical",
        "event_order_certified": "single_hit",
        "cc_reviewed": True,
    }


def _dot(name: str = "Poison") -> dict:
    return {
        "name": name,
        "rank": 1,
        "cooldown": 5.0,
        "magic_damage": 300.0,
        "parts": (DamagePart("magic", 300.0),),
        "total_raw": 300.0,
        "damage_type": "magic",
        "dot_duration": 3.0,
        "dot_tick_interval": 0.5,
        "cc_reviewed": True,
    }


def _control_only(name: str, *, time_offset: float = 0.0) -> dict:
    return {
        "name": name,
        "rank": 1,
        "cooldown": 5.0,
        "parts": (),
        "total_raw": 0.0,
        "damage_type": "magic",
        "control_events": (ControlEvent("root", 1.0, time_offset=time_offset),),
        "cc_reviewed": True,
    }


def _damage_and_control(name: str) -> dict:
    return {
        "name": name,
        "rank": 1,
        "cooldown": 5.0,
        "physical_damage": 100.0,
        "parts": (
            DamagePart(
                "physical",
                100.0,
                time_offset=0.0,
                cc_kind="root",
                cc_duration=1.0,
            ),
        ),
        "total_raw": 100.0,
        "damage_type": "physical",
        "cc_reviewed": True,
    }


def _fight(
    abilities: dict,
    *,
    duration: float = 3.0,
    score_only: bool = False,
) -> dict:
    return calculate_fight_damage(
        _stats(),
        abilities,
        [{"name": "Eclipse"}],
        FightConfig(
            target_health=2000.0,
            target_armor=0.0,
            target_magic_resistance=0.0,
            fight_duration_seconds=duration,
            one_rotation=True,
            auto_attack_uptime=0.0,
        ),
        score_only=score_only,
    )


def _eclipse_effect():
    effects = resolve_damage_effects([{"name": "Eclipse"}])
    return next(
        effect
        for effect in effects.cooldown_procs
        if effect.source.item_name == "Eclipse"
    )


class TestCertifiedDamageAndDotSources:
    def test_two_distinct_direct_damage_casts_complete_one_pair(self) -> None:
        result = _fight({"Q": _direct("Q"), "W": _direct("W")})

        row = result["breakdown"]["proc_Eclipse"]
        assert row["count"] == 1
        assert [event["time"] for event in row["damage_events"]] == [0.0]
        assert [
            transition["kind"] for transition in row["state_transitions"]["transitions"]
        ] == ["gain", "proc", "cooldown_start"]

    @pytest.mark.xfail(
        strict=True,
        reason="the generic DoT packet has no sourced application timestamp",
    )
    def test_multi_tick_dot_application_adds_one_cast_stack(self) -> None:
        result = _fight({"Q": _dot(), "W": _direct("W")})

        dot_events = result["breakdown"]["Q"]["damage_events"]
        assert len(dot_events) == 6
        assert [event["time"] for event in dot_events] == [
            0.5,
            1.0,
            1.5,
            2.0,
            2.5,
            3.0,
        ]
        assert result["breakdown"]["proc_Eclipse"]["count"] == 1

    def test_multi_tick_dot_does_not_add_one_stack_per_tick(self) -> None:
        result = _fight({"Q": _dot()})

        assert len(result["breakdown"]["Q"]["damage_events"]) == 6
        row = result["breakdown"]["proc_Eclipse"]
        assert row["count"] == 0
        assert row["total_damage"] == 0.0
        assert row["withheld_reason"] == "eclipse_stack_source_unavailable"
        assert row["stack_source_denials"] == [
            {
                "source": "Eclipse (Ever Rising Moon)",
                "reason": "dot_application_timing_unavailable",
                "source_key": "Q",
                "time": 0.0,
                "source_url": "https://wiki.leagueoflegends.com/en-us/Eclipse",
                "source_revision_id": 4015408,
                "cast_id": "Q:1",
                "target_id": "target:0",
            }
        ]

    def test_damage_plus_cc_on_one_application_is_one_stack(self) -> None:
        result = _fight({"Q": _damage_and_control("Q")})

        events = result["breakdown"]["Q"]["damage_events"]
        assert len(events) == 1
        assert events[0]["cc_kind"] == "root"
        assert events[0]["cc_reviewed"] is True
        assert "proc_Eclipse" not in result["breakdown"]

    def test_two_stack_window_expiry_restarts_without_proc(self) -> None:
        result = _fight(
            {
                "Q": _direct("Q"),
                "W": _direct("W", time_offset=2.5),
            }
        )

        assert "proc_Eclipse" not in result["breakdown"]


class TestFailClosedIdentityAndMetadata:
    def test_missing_cast_identity_has_named_denial(self) -> None:
        state = SimpleNamespace(
            breakdown={"Q": {"total_damage": 100.0}},
            ability_damages={"Q": _direct("Q")},
            num_auto_attacks=0,
            roster_target_index=0,
            cast_order=["Q"],
        )
        rotation = SimpleNamespace(
            cast_events=({"time": 0.0, "slot": "Q", "target_id": "target:0"},),
            control_events=(),
            forced_basic_attacks=0,
        )

        events, _gate, denials = _stacked_champion_proc_times(
            state, rotation, _eclipse_effect()
        )
        assert events == []
        assert denials[0]["reason"] == "application_identity_unavailable"

    def test_non_finite_hit_metadata_has_named_receipt(self) -> None:
        result = _fight({"Q": _direct("Q", time_offset=float("nan"))})

        row = result["breakdown"]["proc_Eclipse"]
        assert row["event_phase"] == "coarse"
        assert row["withheld_reason"] == "malformed_proc_receipt"
        assert (
            row["shield_withheld_reason"]
            == "self_shield_attached_only_to_certified_proc_events"
        )
        assert "damage_events" not in row

    def test_missing_target_identity_has_named_denial(self) -> None:
        state = SimpleNamespace(
            breakdown={"Q": {"total_damage": 100.0}},
            ability_damages={"Q": _direct("Q")},
            num_auto_attacks=0,
            roster_target_index=0,
            cast_order=["Q"],
        )
        rotation = SimpleNamespace(
            cast_events=({"time": 0.0, "slot": "Q", "cast_id": "Q:1"},),
            control_events=(),
            forced_basic_attacks=0,
        )

        events, _gate, denials = _stacked_champion_proc_times(
            state, rotation, _eclipse_effect()
        )
        assert events == []
        assert denials[0]["reason"] == "target_identity_unavailable"

    @pytest.mark.xfail(
        strict=True,
        reason="malformed DoT classification has no Eclipse denial receipt seam",
    )
    def test_malformed_dot_metadata_has_named_denial(self) -> None:
        malformed = _dot()
        malformed["dot_tick_interval"] = "half-second"

        result = _fight({"Q": malformed, "W": _direct("W")})
        receipts = result["item_denial_receipts"]
        assert {
            "source": "Eclipse (Ever Rising Moon)",
            "reason": "dot_classification_unavailable",
        } in receipts


class TestCertifiedCrowdControlSources:
    def test_direct_damage_plus_control_only_cc_completes_pair(self) -> None:
        result = _fight(
            {
                "Q": _direct("Q"),
                "W": _control_only("W"),
            }
        )

        row = result["breakdown"]["proc_Eclipse"]
        assert row["count"] == 1
        assert row["state_transitions"]["procs"][0]["time"] == 0.0

    def test_two_distinct_control_only_casts_complete_pair(self) -> None:
        result = _fight(
            {
                "Q": _control_only("Q"),
                "W": _control_only("W", time_offset=0.5),
            }
        )

        row = result["breakdown"]["proc_Eclipse"]
        assert row["count"] == 1
        assert row["damage_events"][0]["time"] == 0.5


class TestScoreReceiptParity:
    def test_score_and_receipt_paths_match_for_certified_sources(self) -> None:
        abilities = {"Q": _direct("Q"), "W": _control_only("W")}
        receipt = _fight(abilities)
        score = _fight(abilities, score_only=True)

        receipt_row = receipt["breakdown"]["proc_Eclipse"]
        score_row = score["breakdown"]["proc_Eclipse"]
        assert score_row["count"] == receipt_row["count"] == 1
        assert score_row["total_damage"] == receipt_row["total_damage"]
        assert score_row["damage_events"] == receipt_row["damage_events"]
        assert score_row["state_transitions"] == receipt_row["state_transitions"]
