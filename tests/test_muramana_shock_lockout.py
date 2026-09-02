"""Muramana Shock same-cast, same-target lockout contract tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.calculator import item_effects
from src.calculator.ability_spec import DamagePart
from src.calculator.atomizer_domains import atomize_item
from src.calculator.damage import (
    FightConfig,
    RotationResult,
    _muramana_proc_events,
    calculate_fight_damage,
)
from src.calculator.data_fetcher import get_item_by_name
from src.calculator.state_lifecycle import InstanceCadence

MURAMANA = "Muramana"
ABILITY_ROW = "muramana_ability"
LOCKOUT_SECONDS = 6.5
DEFAULT_TARGET = "target:default"


def _muramana_lockout_atom() -> dict:
    atoms = atomize_item(get_item_by_name(MURAMANA))
    return next(
        atom
        for atom in atoms
        if atom["atom_id"] == "timing.same_target_cast_lockout"
        and atom["source"] == "Muramana.passives[1].branches[1]"
    )


def _identity(target_id: str, cast_id: str) -> str:
    return f"{target_id}|cast:{cast_id}"


def _proc_state(*, damage: float = 100.0) -> SimpleNamespace:
    return SimpleNamespace(
        ability_damages={
            "Q": {
                "cast_instances": 1,
                "parts": (DamagePart("magic", damage),),
            }
        },
        breakdown={"Q": {"casts": 10}},
        cast_order=["Q"],
    )


def _proc_events(cast_events: list[dict], *, expected: int) -> list[dict] | None:
    return _muramana_proc_events(
        _proc_state(),
        RotationResult(total_muramana_procs=expected, cast_events=cast_events),
        lockout_seconds=LOCKOUT_SECONDS,
    )


def _fight(attacker_stats, *, score_only: bool) -> dict:
    stats = attacker_stats()
    stats.update({"max_mana": 1500.0, "is_melee": False})
    abilities = {
        "Q": {
            "name": "Test Q",
            "rank": 1,
            "cooldown": 3.0,
            "parts": (DamagePart("magic", 100.0),),
            "total_raw": 100.0,
            "damage_type": "magic",
        }
    }
    return calculate_fight_damage(
        stats,
        abilities,
        [{"name": MURAMANA}],
        FightConfig(
            target_health=2000.0,
            target_armor=0.0,
            target_magic_resistance=0.0,
            fight_duration_seconds=7.1,
            auto_attack_uptime=0.0,
            cast_order=["Q"],
        ),
        score_only=score_only,
    )


class TestSourcedLockoutDeclaration:
    def test_atom_carries_same_target_same_cast_interval(self) -> None:
        item = get_item_by_name(MURAMANA)
        shock = next(
            passive for passive in item["passives"] if passive["name"] == "Shock"
        )
        ability_branch = shock["branches"][1]
        atom = _muramana_lockout_atom()

        assert "same target" in ability_branch
        assert "same cast instance" in ability_branch
        assert f"{{{{fd|{LOCKOUT_SECONDS}}}}}" in ability_branch
        assert atom["values"] == [LOCKOUT_SECONDS]
        assert atom["units"] == ["seconds"]
        assert atom["evidence"] == ["passive:Shock@kw:ability damage"]
        assert atom["hash"] == "5a5263cc7e165ee4"

    def test_parser_owned_value_reaches_the_compiled_damage_source(self) -> None:
        source = item_effects.resolve_damage_effects(
            [{"name": MURAMANA}]
        ).per_ability_hits[0]

        assert source.same_target_cast_lockout_seconds == LOCKOUT_SECONDS


class TestLifecycleIdentityMatrix:
    def test_same_target_and_cast_is_denied_inside_and_allowed_at_boundary(
        self,
    ) -> None:
        cadence = InstanceCadence(interval_seconds=LOCKOUT_SECONDS)
        identity = _identity(DEFAULT_TARGET, "Q:1")

        assert cadence.allow(0.0, identity)
        assert not cadence.allow(LOCKOUT_SECONDS - 0.001, identity)
        assert cadence.allow(LOCKOUT_SECONDS, identity)
        assert cadence.public_receipt() == {
            "interval_seconds": LOCKOUT_SECONDS,
            "once_only": False,
            "instances_seen": 1,
        }

    def test_distinct_cast_ids_on_same_target_have_independent_clocks(self) -> None:
        cadence = InstanceCadence(interval_seconds=LOCKOUT_SECONDS)

        assert cadence.allow(0.0, _identity(DEFAULT_TARGET, "Q:1"))
        assert cadence.allow(0.1, _identity(DEFAULT_TARGET, "Q:2"))
        assert not cadence.allow(0.2, _identity(DEFAULT_TARGET, "Q:1"))


class TestRuntimeIdentityContract:
    def test_same_cast_and_target_inside_lockout_emits_one_proc(self) -> None:
        events = _proc_events(
            [
                {
                    "slot": "Q",
                    "time": 0.0,
                    "cast_id": "Q:1",
                    "target_id": DEFAULT_TARGET,
                },
                {
                    "slot": "Q",
                    "time": 6.499,
                    "cast_id": "Q:1",
                    "target_id": DEFAULT_TARGET,
                },
            ],
            expected=2,
        )

        assert events is not None
        assert len(events) == 1

    def test_same_cast_and_target_at_boundary_preserves_identity(self) -> None:
        events = _proc_events(
            [
                {
                    "slot": "Q",
                    "time": 0.0,
                    "cast_id": "Q:1",
                    "target_id": DEFAULT_TARGET,
                },
                {
                    "slot": "Q",
                    "time": LOCKOUT_SECONDS,
                    "cast_id": "Q:1",
                    "target_id": DEFAULT_TARGET,
                },
            ],
            expected=2,
        )

        assert events is not None
        assert [(event["cast_id"], event["target_id"]) for event in events] == [
            ("Q:1", DEFAULT_TARGET),
            ("Q:1", DEFAULT_TARGET),
        ]

    def test_distinct_cast_ids_inside_window_preserve_separate_receipts(self) -> None:
        events = _proc_events(
            [
                {
                    "slot": "Q",
                    "time": 0.0,
                    "cast_id": "Q:1",
                    "target_id": DEFAULT_TARGET,
                },
                {
                    "slot": "Q",
                    "time": 0.1,
                    "cast_id": "Q:2",
                    "target_id": DEFAULT_TARGET,
                },
            ],
            expected=2,
        )

        assert events is not None
        assert [event["cast_id"] for event in events] == ["Q:1", "Q:2"]

    def test_distinct_targets_inside_window_have_independent_clocks(self) -> None:
        events = _proc_events(
            [
                {
                    "slot": "Q",
                    "time": 0.0,
                    "cast_id": "Q:1",
                    "target_id": "target:0",
                },
                {
                    "slot": "Q",
                    "time": 0.1,
                    "cast_id": "Q:1",
                    "target_id": "target:1",
                },
            ],
            expected=2,
        )

        assert events is not None
        assert [event["target_id"] for event in events] == ["target:0", "target:1"]

    @pytest.mark.parametrize(
        "cast_event",
        [
            {"slot": "Q", "time": 0.0, "target_id": DEFAULT_TARGET},
            {"slot": "Q", "time": 0.0, "cast_id": "Q:1"},
        ],
        ids=["missing-cast-id", "missing-target-id"],
    )
    def test_missing_identity_withholds_proc(self, cast_event: dict) -> None:
        assert _proc_events([cast_event], expected=1) is None

    @pytest.mark.parametrize(
        "cast_event",
        [
            {
                "slot": "Q",
                "time": 0.0,
                "cast_id": "",
                "target_id": DEFAULT_TARGET,
            },
            {
                "slot": "Q",
                "time": 0.0,
                "cast_id": 1,
                "target_id": DEFAULT_TARGET,
            },
            {"slot": "Q", "time": 0.0, "cast_id": "Q:1", "target_id": ""},
        ],
        ids=["blank-cast-id", "non-string-cast-id", "blank-target-id"],
    )
    def test_malformed_identity_withholds_proc(self, cast_event: dict) -> None:
        assert _proc_events([cast_event], expected=1) is None


class TestDamageAndParity:
    def test_zero_damage_cast_has_no_shock_in_either_mode(self, attacker_stats) -> None:
        stats = attacker_stats()
        stats.update({"max_mana": 1500.0, "is_melee": False})
        abilities = {
            "Q": {
                "name": "Zero Q",
                "rank": 1,
                "cooldown": 3.0,
                "parts": (DamagePart("magic", 0.0),),
                "total_raw": 0.0,
                "damage_type": "magic",
            }
        }
        config = FightConfig(
            target_health=2000.0,
            target_armor=0.0,
            target_magic_resistance=0.0,
            fight_duration_seconds=7.1,
            auto_attack_uptime=0.0,
            cast_order=["Q"],
        )

        receipt = calculate_fight_damage(
            stats, abilities, [{"name": MURAMANA}], config, score_only=False
        )
        score = calculate_fight_damage(
            stats, abilities, [{"name": MURAMANA}], config, score_only=True
        )

        assert ABILITY_ROW not in receipt["breakdown"]
        assert ABILITY_ROW not in score["breakdown"]

    def test_distinct_scheduled_casts_keep_receipt_score_parity(
        self, attacker_stats
    ) -> None:
        receipt = _fight(attacker_stats, score_only=False)
        score = _fight(attacker_stats, score_only=True)
        receipt_row = receipt["breakdown"][ABILITY_ROW]
        score_row = score["breakdown"][ABILITY_ROW]

        assert receipt["breakdown"]["Q"]["casts"] == 3
        assert [event["time"] for event in receipt_row["damage_events"]] == [
            0.0,
            3.0,
            6.0,
        ]
        assert score_row == receipt_row
        assert receipt_row["lockout_receipt"] == {
            "interval_seconds": LOCKOUT_SECONDS,
            "identity": "target_id|cast:cast_id",
            "candidate_count": 3,
            "accepted_count": 3,
            "suppressed_count": 0,
        }
        assert score["total_damage"] == pytest.approx(receipt["total_damage"])
