"""Fimbulwinter Everlasting nearby-enemy range certification.

The cached Everlasting branch certifies a 1200-unit, holder-centered count.
The 1.8 shield multiplier applies only when more than one enemy champion is
inside that radius.  The support runtime has no typed spatial-input contract.
It keeps the sourced base shield, withholds the 1.8 branch, and emits a named
receipt.  Geometry tests stay strict xfails until a later packet supplies
authoritative inputs and the exact boundary operator.
"""

from types import SimpleNamespace

import pytest

from src.calculator.champions import parse_champion_abilities
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.item_effects import required_effect_value
from src.calculator.item_support_effects import derive_item_support_effects
from src.calculator.stats import calculate_total_stats

pytestmark = pytest.mark.usefixtures("authorized_fimbulwinter_mana_gate")

FIMBULWINTER = "Fimbulwinter"
EVERLASTING = "Fimbulwinter — Everlasting"
RANGE_UNITS = 1_200.0
MULTI_TARGET_MULTIPLIER = 1.8
BASE_SHIELD = 100.0
CURRENT_MANA_RATIO = 0.045
CURRENT_MANA = 900.0
SPATIAL_UNAVAILABLE = "nearby_enemy_spatial_input_unavailable"
MISSING = object()


def _actor(
    participant_id: object,
    team: str,
    item_names: tuple[str, ...] = (),
    *,
    position: object = MISSING,
) -> SimpleNamespace:
    stats: dict[str, object] = {
        "mana": 1_000.0,
        "max_mana": 1_000.0,
        "is_melee": True,
    }
    if position is not MISSING:
        stats["position"] = position
    values: dict[str, object] = {
        "team": team,
        "level": 18,
        "items": tuple({"name": name} for name in item_names),
        "stats": stats,
        "request": SimpleNamespace(item_options={}, ally_effects_enabled=True),
    }
    if participant_id is not MISSING:
        values["participant_id"] = participant_id
    return SimpleNamespace(**values)


def _event(target: str = "enemy:Enemy0") -> dict[str, object]:
    return {
        "time": 1.0,
        "target": target,
        "source_key": "E",
        "ability_instance": "E:1",
        "cc_kind": "immobilize",
        "cc_reviewed": True,
        "is_ability": True,
        "_event_id": "fimbulwinter-range-event",
    }


def _run(
    enemy_positions: tuple[object, ...],
    *,
    holder_position: object = (0.0, 0.0),
    holder_id: object = "main:Ahri",
    result: dict | None = None,
) -> list[dict]:
    holder = _actor(
        holder_id,
        "main",
        (FIMBULWINTER,),
        position=holder_position,
    )
    enemies = tuple(
        _actor(f"enemy:Enemy{index}", "enemy", position=position)
        for index, position in enumerate(enemy_positions)
    )
    target = enemies[0].participant_id if enemies else "enemy:outside-authored-target"
    fight_result = result or {
        "cast_timeline": [{"time": 1.0, "resource_after": CURRENT_MANA}],
        "damage_events": [_event(target)],
    }
    return derive_item_support_effects(holder, fight_result, [holder, *enemies])


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


def _shield(packets: list[dict]) -> dict:
    rows = _shields(packets)
    assert len(rows) == 1
    return rows[0]


def _base_amount() -> float:
    return BASE_SHIELD + CURRENT_MANA_RATIO * CURRENT_MANA


def test_cached_branch_certifies_range_count_and_multiplier() -> None:
    item = get_item_by_name(FIMBULWINTER)
    branch = next(
        text
        for passive in item["passives"]
        if passive.get("name") == "Everlasting"
        for text in passive.get("branches", [])
    )

    assert "more than one enemy champion" in branch
    assert "1200 units" in branch
    assert required_effect_value(
        FIMBULWINTER, "everlasting_multi_target_multiplier"
    ) == pytest.approx(MULTI_TARGET_MULTIPLIER)
    assert required_effect_value(
        FIMBULWINTER, "everlasting_nearby_enemy_range"
    ) == pytest.approx(RANGE_UNITS)
    assert (
        required_effect_value(
            FIMBULWINTER, "everlasting_multi_target_minimum_enemy_count"
        )
        == 2
    )


def test_whole_roster_is_not_treated_as_inside_the_sourced_range() -> None:
    packets = _run(((2_000.0, 0.0), (-2_000.0, 0.0)))
    packet = _shield(packets)

    assert packet["nearby_enemy_count"] == 0
    assert packet["nearby_enemy_range_units"] == pytest.approx(RANGE_UNITS)
    assert packet["range_input_status"] == "spatially_certified"
    assert packet["multi_target_multiplier"] == pytest.approx(1.0)
    assert packet["requested_multi_target_multiplier"] == pytest.approx(
        MULTI_TARGET_MULTIPLIER
    )
    assert packet["amount"] == pytest.approx(_base_amount())
    assert _denials(packets) == []


def test_shield_receipt_keeps_holder_and_trigger_target_identity() -> None:
    packet = _shield(_run(((600.0, 0.0),)))

    assert packet["attacker"] == "main:Ahri"
    assert packet["target"] == "main:Ahri"
    assert packet["target_scope"] == "self"
    assert packet["_trigger_event_id"] == "fimbulwinter-range-event"


def test_zero_one_and_multiple_enemies_inside_or_outside_range() -> None:
    cases = (
        (((1_200.01, 0.0), (0.0, 1_200.01)), 0, 1.0),
        (((600.0, 0.0), (1_200.01, 0.0)), 1, 1.0),
        (((300.0, 400.0), (0.0, 1_200.0), (1_200.01, 0.0)), 2, 1.8),
    )

    for positions, expected_count, expected_multiplier in cases:
        packet = _shield(_run(positions))
        assert packet["nearby_enemy_count"] == expected_count
        assert packet["multi_target_multiplier"] == pytest.approx(expected_multiplier)
        assert packet["amount"] == pytest.approx(_base_amount() * expected_multiplier)


def test_exact_boundary_is_inside_the_holder_centered_radius() -> None:
    packet = _shield(_run(((1_200.0, 0.0),)))

    assert packet["nearby_enemy_range_units"] == pytest.approx(RANGE_UNITS)
    assert packet["nearby_enemy_count"] == 1
    assert packet["multi_target_multiplier"] == pytest.approx(1.0)


def test_missing_enemy_positions_keep_base_shield_and_name_the_gap() -> None:
    packets = _run((MISSING, MISSING))

    packet = _shield(packets)
    assert packet["nearby_enemy_count"] is None
    assert packet["multi_target_multiplier"] == pytest.approx(1.0)
    assert packet["amount"] == pytest.approx(_base_amount())
    assert [row["reason"] for row in _denials(packets)] == [SPATIAL_UNAVAILABLE]


def test_missing_holder_position_keeps_base_shield_and_names_the_gap() -> None:
    packets = _run(((300.0, 0.0), (600.0, 0.0)), holder_position=MISSING)

    packet = _shield(packets)
    assert packet["nearby_enemy_count"] is None
    assert packet["multi_target_multiplier"] == pytest.approx(1.0)
    assert packet["amount"] == pytest.approx(_base_amount())
    assert [row["reason"] for row in _denials(packets)] == [SPATIAL_UNAVAILABLE]


@pytest.mark.parametrize(
    "bad_position",
    [None, ("bad", 0.0), (float("nan"), 0.0)],
)
def test_malformed_enemy_distance_keeps_base_shield_and_names_the_gap(
    bad_position: object,
) -> None:
    packets = _run((bad_position,))

    packet = _shield(packets)
    assert packet["nearby_enemy_count"] is None
    assert packet["multi_target_multiplier"] == pytest.approx(1.0)
    assert [row["reason"] for row in _denials(packets)] == [SPATIAL_UNAVAILABLE]


def test_missing_holder_identity_fails_closed() -> None:
    packets = _run(((300.0, 0.0),), holder_id=MISSING)

    assert _shields(packets) == []
    assert [row["reason"] for row in _denials(packets)] == ["missing_holder_identity"]


def test_pair_and_roster_paths_ignore_out_of_range_roster_members() -> None:
    pair = _shield(_run(((600.0, 0.0),)))
    roster = _shield(_run(((600.0, 0.0), (2_000.0, 0.0))))

    fields = ("nearby_enemy_count", "multi_target_multiplier", "amount")
    assert tuple(pair[field] for field in fields) == tuple(
        roster[field] for field in fields
    )


def test_multiplier_uses_only_multiple_enemies_inside_range() -> None:
    packet = _shield(_run(((300.0, 0.0), (0.0, 1_100.0), (2_000.0, 0.0))))

    assert packet["nearby_enemy_count"] == 2
    assert packet["multi_target_multiplier"] == pytest.approx(MULTI_TARGET_MULTIPLIER)
    assert packet["amount"] == pytest.approx(_base_amount() * MULTI_TARGET_MULTIPLIER)


def test_public_receipt_certifies_holder_centered_range_evaluation() -> None:
    packet = _shield(_run(((500.0, 0.0), (1_500.0, 0.0))))

    assert packet["source_url"].endswith("/Fimbulwinter")
    assert packet["source_revision_id"] == 3984419
    assert packet["range_center"] == "main:Ahri"
    assert packet["nearby_enemy_range_units"] == pytest.approx(RANGE_UNITS)
    assert packet["nearby_enemy_count"] == 1
    assert packet["range_input_status"] == "spatially_certified"


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
    result = calculate_fight_damage(
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
    # Provide champion_stats so the Fimbulwinter mana gate can resolve;
    # the first accepted cast leaves 900 mana (>20% of 1000 so the gate
    # passes).  Also stamp ability_instance and target on CC events.
    result["champion_stats"] = {"max_mana": 1_000.0}
    result["cast_timeline"] = [{"time": 0.0, "resource_after": 900.0}]
    for event in (*result.get("damage_events", []), *result.get("control_events", [])):
        if event.get("cc_kind"):
            event["ability_instance"] = "R:1"
            event["target"] = "main:Morgana"
    return result


def test_full_and_score_paths_match_spatial_unavailable_receipts() -> None:
    holder = _actor(
        "main:Morgana",
        "main",
        (FIMBULWINTER,),
        position=(0.0, 0.0),
    )
    inside = _actor("enemy:Aatrox", "enemy", position=(600.0, 0.0))
    outside = _actor("enemy:Galio", "enemy", position=(1_500.0, 0.0))
    full = _shield(
        derive_item_support_effects(
            holder, _fight(score_only=False), [holder, inside, outside]
        )
    )
    score = _shield(
        derive_item_support_effects(
            holder, _fight(score_only=True), [holder, inside, outside]
        )
    )

    fields = (
        "nearby_enemy_count",
        "nearby_enemy_range_units",
        "range_input_status",
        "multi_target_multiplier",
        "amount",
        "range_center",
        "source_url",
        "source_revision_id",
    )
    assert tuple(score[field] for field in fields) == tuple(
        full[field] for field in fields
    )
    # With positions available, the spatial evaluation certifies the
    # range: one enemy (Aatrox) at 600 units is inside 1200.
    assert full["nearby_enemy_count"] == 1
    assert full["range_input_status"] == "spatially_certified"
    assert full["multi_target_multiplier"] == pytest.approx(1.0)
