"""Focused matrix for Fimbulwinter Everlasting cadence-burn semantics.

The sourced packet already permits one Everlasting shield per authored ability
instance.  Local evidence does not yet certify whether a mana-gate or cooldown
denial consumes that instance.  Those two policy choices stay strict xfails.
"""

from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.usefixtures("authorized_fimbulwinter_mana_gate")

from src.calculator.champions import parse_champion_abilities
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.item_support_effects import derive_item_support_effects
from src.calculator.stats import calculate_total_stats

FIMBULWINTER = "Fimbulwinter"
EVERLASTING = "Fimbulwinter — Everlasting"


def _actor(
    participant_id: str,
    team: str,
    items: tuple[str, ...] = (),
    *,
    max_mana: float = 1_000.0,
) -> SimpleNamespace:
    return SimpleNamespace(
        participant_id=participant_id,
        team=team,
        level=18,
        items=tuple({"name": name} for name in items),
        stats={"mana": max_mana, "max_mana": max_mana, "is_melee": True},
        request=SimpleNamespace(item_options={}, ally_effects_enabled=True),
    )


def _event(
    time: float,
    *,
    instance: object,
    event_id: str,
    source_key: str = "E",
    cc_kind: str = "stun",
) -> dict:
    event = {
        "time": time,
        "target": "enemy:Aatrox",
        "source_key": source_key,
        "cc_kind": cc_kind,
        "cc_reviewed": True,
        "is_ability": True,
        "_event_id": event_id,
    }
    if instance is not None:
        event["ability_instance"] = instance
    return event


def _run(
    *,
    damage_events: list[dict] | None = None,
    control_events: list[dict] | None = None,
    cast_timeline: list[dict] | None = None,
) -> list[dict]:
    holder = _actor("main:Ahri", "main", (FIMBULWINTER,))
    enemy = _actor("enemy:Aatrox", "enemy")
    result = {
        "damage_events": damage_events or [],
        "control_events": control_events or [],
    }
    if cast_timeline is not None:
        result["cast_timeline"] = cast_timeline
    return derive_item_support_effects(holder, result, [holder, enemy])


def _shields(packets: list[dict]) -> list[dict]:
    return [
        packet
        for packet in packets
        if packet.get("source") == EVERLASTING and packet.get("kind") == "shield"
    ]


def _denials(packets: list[dict]) -> list[dict]:
    return [
        packet
        for packet in packets
        if packet.get("source") == EVERLASTING and packet.get("kind") == "item_denial"
    ]


def _packet_signature(packets: list[dict]) -> list[tuple]:
    return [
        (
            packet.get("kind"),
            packet.get("time"),
            packet.get("reason"),
            packet.get("trigger_kind"),
            packet.get("_trigger_event_id"),
        )
        for packet in packets
        if packet.get("source") == EVERLASTING
    ]


class TestSupportedCadenceRows:
    """Rows that follow the current sourced instance and trigger contracts."""

    def test_multi_event_same_instance_fires_once_with_exact_duplicate_receipt(self):
        packets = _run(
            damage_events=[
                _event(1.0, instance="E:1", event_id="first"),
                _event(1.5, instance="E:1", event_id="second"),
            ]
        )

        assert [row["_trigger_event_id"] for row in _shields(packets)] == ["first"]
        assert [
            (row["time"], row["reason"], row["event_id"]) for row in _denials(packets)
        ] == [
            (
                pytest.approx(1.0),
                "nearby_enemy_spatial_input_unavailable",
                "first",
            ),
            (pytest.approx(1.5), "duplicate_instance", "second"),
        ]

    def test_distinct_instances_fire_after_the_inclusive_cooldown_boundary(self):
        packets = _run(
            damage_events=[
                _event(1.0, instance="E:1", event_id="first"),
                _event(9.0, instance="E:2", event_id="second"),
            ]
        )

        assert [row["time"] for row in _shields(packets)] == [
            pytest.approx(1.0),
            pytest.approx(9.0),
        ]
        assert [row["reason"] for row in _denials(packets)] == [
            "nearby_enemy_spatial_input_unavailable",
            "nearby_enemy_spatial_input_unavailable",
        ]

    def test_control_only_same_instance_uses_the_same_cadence(self):
        packets = _run(
            control_events=[
                _event(1.0, instance="Q:1", event_id="control-first", source_key="Q"),
                _event(
                    1.5,
                    instance="Q:1",
                    event_id="control-second",
                    source_key="Q",
                ),
            ]
        )

        assert [row["_trigger_event_id"] for row in _shields(packets)] == [
            "control-first"
        ]
        assert [(row["reason"], row["event_id"]) for row in _denials(packets)] == [
            ("nearby_enemy_spatial_input_unavailable", "control-first"),
            ("duplicate_instance", "control-second"),
        ]

    def test_mana_and_cooldown_denials_have_exact_receipts(self):
        mana_packets = _run(
            damage_events=[_event(1.0, instance="E:mana", event_id="mana")],
            cast_timeline=[{"time": 1.0, "resource_after": 200.0}],
        )
        cooldown_packets = _run(
            damage_events=[
                _event(1.0, instance="E:first", event_id="accepted"),
                _event(5.0, instance="E:cooldown", event_id="cooldown"),
            ]
        )

        assert [
            (row["time"], row["reason"], row["event_id"])
            for row in _denials(mana_packets)
        ] == [(pytest.approx(1.0), "mana_gate", "mana")]
        assert [
            (row["time"], row["reason"], row["event_id"])
            for row in _denials(cooldown_packets)
        ] == [
            (
                pytest.approx(1.0),
                "nearby_enemy_spatial_input_unavailable",
                "accepted",
            ),
            (pytest.approx(5.0), "cooldown", "cooldown"),
        ]


class TestUnsourcedCadenceBurnRows:
    """Policy rows stay unbound until source evidence selects a behavior."""

    @pytest.mark.xfail(
        strict=True,
        reason="no local source certifies that a mana denial burns the instance",
    )
    def test_mana_denial_allows_a_later_valid_event_from_the_same_instance(self):
        packets = _run(
            damage_events=[
                _event(1.0, instance="E:1", event_id="denied"),
                _event(2.0, instance="E:1", event_id="retry"),
            ],
            cast_timeline=[
                {"time": 1.0, "resource_after": 200.0},
                {"time": 2.0, "resource_after": 900.0},
            ],
        )

        assert [row["_trigger_event_id"] for row in _shields(packets)] == ["retry"]
        assert [row["reason"] for row in _denials(packets)] == ["mana_gate"]

    @pytest.mark.xfail(
        strict=True,
        reason="no local source certifies that a cooldown denial burns the instance",
    )
    def test_cooldown_denial_allows_same_instance_after_cooldown_is_ready(self):
        packets = _run(
            damage_events=[
                _event(1.0, instance="E:accepted", event_id="accepted"),
                _event(5.0, instance="E:retry", event_id="denied"),
                _event(9.0, instance="E:retry", event_id="retry"),
            ]
        )

        assert [row["_trigger_event_id"] for row in _shields(packets)] == [
            "accepted",
            "retry",
        ]
        assert [row["reason"] for row in _denials(packets)] == ["cooldown"]


class TestFailClosedIdentity:
    """Authored instance identity is required before cadence can run."""

    @pytest.mark.parametrize("instance", [None, "", "   ", 123])
    def test_missing_or_malformed_ability_instance_identity_fails_closed(
        self, instance
    ):
        packets = _run(
            damage_events=[_event(1.0, instance=instance, event_id="missing-instance")]
        )

        assert _shields(packets) == []
        assert len(_denials(packets)) == 1
        assert _denials(packets)[0]["reason"] == "missing_instance_identity"
        assert _denials(packets)[0]["event_id"] == "missing-instance"


class TestScoreReceiptParity:
    """Full and score calculations feed the same Everlasting receipt walk."""

    def test_full_and_score_paths_emit_the_same_cadence_receipts(self):
        champion = get_champion("Morgana")
        item = get_item_by_name(FIMBULWINTER)
        stats = calculate_total_stats(champion, 18, [item])
        abilities = parse_champion_abilities(
            champion,
            18,
            stats["ability_power"],
            ability_ranks={"Q": 0, "W": 0, "E": 0, "R": 3},
            champion_stats=stats,
            target_stats={
                "target_max_health": 5_000.0,
                "target_current_health": 5_000.0,
                "target_missing_health": 0.0,
            },
        )
        config = FightConfig(
            target_health=5_000.0,
            target_armor=0.0,
            target_magic_resistance=0.0,
            fight_duration_seconds=5.0,
            auto_attack_uptime=0.0,
            one_rotation=True,
            cast_order=["R"],
        )
        full = calculate_fight_damage(stats, {"R": abilities["R"]}, [item], config)
        score = calculate_fight_damage(
            stats,
            {"R": abilities["R"]},
            [item],
            config,
            score_only=True,
        )
        holder = _actor(
            "main:Morgana", "main", (FIMBULWINTER,), max_mana=stats["max_mana"]
        )
        enemy = _actor("enemy:Aatrox", "enemy")

        full_packets = derive_item_support_effects(holder, full, [holder, enemy])
        score_packets = derive_item_support_effects(holder, score, [holder, enemy])

        assert _packet_signature(score_packets) == _packet_signature(full_packets)
        assert score["total_damage"] == pytest.approx(full["total_damage"])
