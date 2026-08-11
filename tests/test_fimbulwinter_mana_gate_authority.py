"""Fimbulwinter Everlasting mana-gate authority certification.

Local item data does not provide script-level authority for the 20% gate,
its boundary operator, its current-versus-maximum mana terms, or manaless
behavior.  Runtime rows therefore require a named unavailable receipt.  The
blocked mechanic claims stay strict xfails until direct script evidence exists.
"""

from types import SimpleNamespace

import pytest

from src.calculator.champions import parse_champion_abilities
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.item_effects import item_state_receipts, required_effect_value
from src.calculator.item_support_effects import derive_item_support_effects
from src.calculator.stats import calculate_total_stats

FIMBULWINTER = "Fimbulwinter"
EVERLASTING = "Fimbulwinter — Everlasting"
UNAVAILABLE_REASON = "mana_gate_authority_unavailable"
SOURCE_UNAVAILABLE = "source_unavailable"
MISSING = object()


def _actor(
    participant_id: str,
    team: str,
    item_names: tuple[str, ...] = (),
    *,
    maximum_mana: object = 1_000.0,
    include_current_mana: bool = True,
) -> SimpleNamespace:
    stats: dict[str, object] = {"is_melee": True}
    if maximum_mana is not MISSING:
        stats["max_mana"] = maximum_mana
        if include_current_mana:
            stats["mana"] = maximum_mana
    return SimpleNamespace(
        participant_id=participant_id,
        team=team,
        level=18,
        items=tuple({"name": name} for name in item_names),
        stats=stats,
        request=SimpleNamespace(item_options={}, ally_effects_enabled=True),
    )


def _event() -> dict:
    return {
        "time": 1.0,
        "target": "enemy:Aatrox",
        "source_key": "E",
        "ability_instance": "E:1",
        "cc_kind": "immobilize",
        "cc_reviewed": True,
        "is_ability": True,
        "_event_id": "mana-gate-event",
    }


def _run(
    *,
    maximum_mana: object = 1_000.0,
    resource_after: object = 900.0,
    include_cast_timeline: bool = True,
    include_current_mana: bool = True,
) -> list[dict]:
    holder = _actor(
        "main:Ahri",
        "main",
        (FIMBULWINTER,),
        maximum_mana=maximum_mana,
        include_current_mana=include_current_mana,
    )
    enemy = _actor("enemy:Aatrox", "enemy")
    result: dict[str, object] = {"damage_events": [_event()]}
    if include_cast_timeline:
        result["cast_timeline"] = [{"time": 1.0, "resource_after": resource_after}]
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


def _gate_state_receipt() -> dict:
    rows = item_state_receipts(
        [get_item_by_name(FIMBULWINTER)],
        {},
        fight_duration_seconds=5.0,
        is_melee=True,
        max_mana=1_000.0,
    )
    return next(row for row in rows if row["item"] == FIMBULWINTER)


def _assert_unavailable(packets: list[dict]) -> dict:
    assert _shields(packets) == []
    rows = _denials(packets)
    assert len(rows) == 1
    row = rows[0]
    assert row["reason"] == UNAVAILABLE_REASON
    assert row["mana_gate_status"] == SOURCE_UNAVAILABLE
    assert row["source_url"].endswith("/Fimbulwinter")
    assert row["source_revision_id"] == 3984419
    return row


class TestUnavailableAuthorityContract:
    """The blocked numeric rule cannot control shield eligibility."""

    def test_state_receipt_marks_the_gate_unavailable(self) -> None:
        receipt = _gate_state_receipt()

        assert receipt["mana_gate_status"] == SOURCE_UNAVAILABLE
        assert receipt["mana_threshold_ratio"] is None
        assert receipt["mana_comparison"] is None

    @pytest.mark.parametrize("resource_after", [900.0, 200.0, 150.0])
    def test_all_threshold_positions_emit_the_same_unavailable_receipt(
        self, resource_after: float
    ) -> None:
        row = _assert_unavailable(_run(resource_after=resource_after))

        assert row["event_id"] == "mana-gate-event"


class TestManaInputValidation:
    """Absent or malformed mana state fails closed without a crash."""

    def test_missing_maximum_mana_has_a_named_denial(self) -> None:
        packets = _run(maximum_mana=MISSING, resource_after=900.0)

        assert _shields(packets) == []
        assert [row["reason"] for row in _denials(packets)] == ["missing_maximum_mana"]

    def test_missing_current_mana_has_a_named_denial(self) -> None:
        packets = _run(
            resource_after=MISSING,
            include_cast_timeline=False,
            include_current_mana=False,
        )

        assert _shields(packets) == []
        assert [row["reason"] for row in _denials(packets)] == ["missing_current_mana"]

    @pytest.mark.parametrize("maximum_mana", [None, "bad", float("nan")])
    def test_malformed_maximum_mana_has_a_named_denial(
        self, maximum_mana: object
    ) -> None:
        packets = _run(maximum_mana=maximum_mana, resource_after=900.0)

        assert _shields(packets) == []
        assert [row["reason"] for row in _denials(packets)] == ["invalid_maximum_mana"]

    @pytest.mark.parametrize("resource_after", [None, "bad", float("nan")])
    def test_malformed_current_mana_has_a_named_denial(
        self, resource_after: object
    ) -> None:
        packets = _run(resource_after=resource_after)

        assert _shields(packets) == []
        assert [row["reason"] for row in _denials(packets)] == ["invalid_current_mana"]


@pytest.mark.xfail(
    strict=True,
    reason="direct script authority for the 20% gate is unavailable",
)
@pytest.mark.parametrize(
    ("resource_after", "expected_kind"),
    [(200.01, "shield"), (200.0, "item_denial"), (199.99, "item_denial")],
)
def test_unsourced_twenty_percent_boundary_operator(
    resource_after: float, expected_kind: str
) -> None:
    """The strict-above 20% rule waits for direct script evidence."""
    packets = _run(resource_after=resource_after)
    receipt = _gate_state_receipt()
    everlasting = [row for row in packets if row.get("source") == EVERLASTING]

    assert required_effect_value(
        FIMBULWINTER, "everlasting_mana_threshold_ratio"
    ) == pytest.approx(0.20)
    assert receipt["mana_gate_status"] == "script_authorized"
    assert receipt["mana_comparison"] == "current_mana > maximum_mana * ratio"
    assert [row["kind"] for row in everlasting] == [expected_kind]


@pytest.mark.xfail(
    strict=True,
    reason="direct script authority for current-versus-maximum mana terms is unavailable",
)
@pytest.mark.parametrize(
    ("maximum_mana", "resource_after", "expected_kind"),
    [(2_000.0, 300.0, "item_denial"), (500.0, 150.0, "shield")],
)
def test_unsourced_current_versus_maximum_mana_terms(
    maximum_mana: float, resource_after: float, expected_kind: str
) -> None:
    """Absolute mana does not replace the blocked percentage terms."""
    packets = _run(maximum_mana=maximum_mana, resource_after=resource_after)
    receipt = _gate_state_receipt()
    everlasting = [row for row in packets if row.get("source") == EVERLASTING]

    assert receipt["mana_gate_status"] == "script_authorized"
    assert receipt["mana_current_term"] == "post_cast_current_mana"
    assert receipt["mana_maximum_term"] == "holder_maximum_mana"
    assert [row["kind"] for row in everlasting] == [expected_kind]


@pytest.mark.xfail(
    strict=True,
    reason="direct script authority for manaless behavior is unavailable",
)
def test_unsourced_manaless_gate_behavior() -> None:
    """A zero-mana holder rule waits for direct script evidence."""
    packets = _run(maximum_mana=0.0, resource_after=0.0)
    receipt = _gate_state_receipt()

    assert receipt["mana_gate_status"] == "script_authorized"
    assert _shields(packets) == []
    assert [row["reason"] for row in _denials(packets)] == ["mana_gate"]


class TestReceiptScoreParity:
    """Full and score paths expose the same unavailable gate receipt."""

    @staticmethod
    def _fight(*, score_only: bool) -> dict:
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
        return calculate_fight_damage(
            stats,
            {"R": abilities["R"]},
            [item],
            FightConfig(
                target_health=5_000.0,
                target_armor=0.0,
                target_magic_resistance=0.0,
                fight_duration_seconds=2.0,
                auto_attack_uptime=0.0,
                one_rotation=True,
                cast_order=["R"],
            ),
            score_only=score_only,
        )

    def test_full_and_score_paths_match_the_unavailable_receipt(self) -> None:
        full = self._fight(score_only=False)
        score = self._fight(score_only=True)
        for result in (full, score):
            for event in result.get("damage_events", []):
                if event.get("cc_kind"):
                    event["ability_instance"] = "R:1"
            for event in result.get("control_events", []):
                if event.get("cc_kind"):
                    event["ability_instance"] = "R:1"
        item = get_item_by_name(FIMBULWINTER)
        champion = get_champion("Morgana")
        stats = calculate_total_stats(champion, 18, [item])
        holder = _actor(
            "main:Morgana",
            "main",
            (FIMBULWINTER,),
            maximum_mana=stats["max_mana"],
        )
        enemy = _actor("enemy:Aatrox", "enemy")

        full_packets = derive_item_support_effects(holder, full, [holder, enemy])
        score_packets = derive_item_support_effects(holder, score, [holder, enemy])
        assert _shields(full_packets) == []
        assert _shields(score_packets) == []
        full_rows = _denials(full_packets)
        score_rows = _denials(score_packets)
        assert full_rows
        assert score_rows
        assert UNAVAILABLE_REASON in {row["reason"] for row in full_rows}
        assert UNAVAILABLE_REASON in {row["reason"] for row in score_rows}
        assert SOURCE_UNAVAILABLE in {row.get("mana_gate_status") for row in full_rows}
        assert SOURCE_UNAVAILABLE in {row.get("mana_gate_status") for row in score_rows}

        fields = ("kind", "reason", "time", "event_id", "mana_gate_status")
        assert [tuple(row[field] for field in fields) for row in score_rows] == [
            tuple(row[field] for field in fields) for row in full_rows
        ]
        assert score["total_damage"] == pytest.approx(full["total_damage"])
