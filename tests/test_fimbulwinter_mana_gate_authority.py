"""Fimbulwinter Everlasting mana-gate authority certification.

The gate is SOURCED, from Fimbulwinter revision 3984419: a melee holder's slow arms
Everlasting above the 20%-maximum-mana gate, and
the whole champion x Fimbulwinter coverage fan-out prices through it.  The
registry states that authority in ``everlasting_mana_gate_status``, and the
runtime reads the contract rather than a literal.

The unavailable path is still the fail-closed contract and is still tested,
through ``_desourced_gate()``: it swaps the entry's own status to
``source_unavailable`` so the branch is exercised against a synthetic
de-sourcing rather than being deleted with the ruling.
"""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from src.calculator.champions import parse_champion_abilities
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.data_fetcher import get_champion, get_item_by_name
from src.calculator.item_effects import (
    ITEM_EFFECTS,
    item_state_receipts,
    required_effect_value,
)
from src.calculator.item_support_effects import derive_item_support_effects
from src.calculator.stats import calculate_total_stats

FIMBULWINTER = "Fimbulwinter"
EVERLASTING = "Fimbulwinter — Everlasting"
UNAVAILABLE_REASON = "mana_gate_authority_unavailable"
SOURCE_UNAVAILABLE = "source_unavailable"
MISSING = object()
GATE_DENIED_REASON = "mana_gate"
# The base shield still lands when the holder-centered range has no spatial
# input; only the 1.8x multiplier is withheld, so this receipt rides beside a
# granted shield and is not an eligibility refusal.
SPATIAL_RECEIPT = "nearby_enemy_spatial_input_unavailable"
SOURCE_AUTHORIZED = "source_authorized"
THRESHOLD_RATIO = 0.20


@contextmanager
def _desourced_gate():
    """Run a body against a synthetic de-sourcing of the gate.

    The entry states its own authority, so withdrawing it is a one-key swap
    rather than a monkeypatched function: this is exactly the state the
    registry would be in if a future patch removed the sentence, and the
    named-denial branch below is what the runtime owes that state.
    """
    entry = ITEM_EFFECTS[FIMBULWINTER]
    status = entry["everlasting_mana_gate_status"]
    ratio = entry.pop("everlasting_mana_threshold_ratio")
    entry["everlasting_mana_gate_status"] = SOURCE_UNAVAILABLE
    try:
        yield
    finally:
        entry["everlasting_mana_gate_status"] = status
        entry["everlasting_mana_threshold_ratio"] = ratio


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


def _assert_gate_denied(packets: list[dict]) -> dict:
    """The authorized gate refusing a position at or below the threshold."""
    assert _shields(packets) == []
    rows = [row for row in _denials(packets) if row["reason"] == GATE_DENIED_REASON]
    assert len(rows) == 1
    row = rows[0]
    assert row["mana_threshold_ratio"] == pytest.approx(THRESHOLD_RATIO)
    assert row["mana_comparison"] == "current_mana > maximum_mana * ratio"
    return row


class TestAuthorizedGateContract:
    """The sourced gate is what decides shield eligibility."""

    def test_state_receipt_carries_the_sourced_gate(self) -> None:
        receipt = _gate_state_receipt()

        assert receipt["mana_gate_status"] == SOURCE_AUTHORIZED
        assert receipt["mana_threshold_ratio"] == pytest.approx(THRESHOLD_RATIO)
        assert receipt["mana_comparison"] == "current_mana > maximum_mana * ratio"


class TestUnavailableAuthorityContract:
    """A de-sourced gate cannot control shield eligibility, and says so."""

    def test_state_receipt_marks_the_gate_unavailable(self) -> None:
        with _desourced_gate():
            receipt = _gate_state_receipt()

        assert receipt["mana_gate_status"] == SOURCE_UNAVAILABLE
        assert receipt["mana_threshold_ratio"] is None
        assert receipt["mana_comparison"] is None

    @pytest.mark.parametrize("resource_after", [900.0, 200.0, 150.0])
    def test_all_threshold_positions_emit_the_same_unavailable_receipt(
        self, resource_after: float
    ) -> None:
        with _desourced_gate():
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


class TestTwentyPercentBoundaryIsAuthored:
    """The sourced boundary, pinned from both sides.

    Fimbulwinter revision 3984419 is the ruling (campaign U11a): the shield
    arms while the holder is ABOVE 20% of maximum mana, so the comparison is
    strict and the boundary itself denies.  A de-sourced gate collapses every
    one of these positions onto the same named receipt, which is what the
    ``_desourced_gate`` half asserts.
    """

    def test_above_the_boundary_arms_the_shield(self) -> None:
        packets = _run(resource_after=200.01)

        assert _shields(packets)
        assert [
            row["reason"]
            for row in _denials(packets)
            if row["reason"] != SPATIAL_RECEIPT
        ] == []

    @pytest.mark.parametrize("resource_after", [200.0, 199.99])
    def test_at_or_below_the_boundary_denies_by_the_sourced_gate(
        self, resource_after: float
    ) -> None:
        row = _assert_gate_denied(_run(resource_after=resource_after))

        assert row["current_mana"] == pytest.approx(resource_after)
        assert row["maximum_mana"] == pytest.approx(1_000.0)

    @pytest.mark.parametrize("resource_after", [200.01, 200.0, 199.99])
    def test_a_desourced_gate_denies_every_position_identically(
        self, resource_after: float
    ) -> None:
        with _desourced_gate():
            row = _assert_unavailable(_run(resource_after=resource_after))

        assert row["current_mana"] == pytest.approx(resource_after)
        assert row["maximum_mana"] == pytest.approx(1_000.0)
        assert row["mana_threshold_ratio"] is None
        assert row["mana_comparison"] is None

    def test_the_threshold_ratio_is_read_through_the_typed_accessor(self) -> None:
        """Rule 5: the ratio is a registry value with no literal fallback,
        and a de-sourced entry makes reading it raise, naming item and key."""
        assert required_effect_value(
            FIMBULWINTER, "everlasting_mana_threshold_ratio"
        ) == pytest.approx(THRESHOLD_RATIO)
        with _desourced_gate(), pytest.raises(KeyError) as excinfo:
            required_effect_value(FIMBULWINTER, "everlasting_mana_threshold_ratio")
        message = excinfo.value.args[0]
        assert FIMBULWINTER in message
        assert "everlasting_mana_threshold_ratio" in message


class TestCurrentVersusMaximumManaTermsRideTheSourcedRatio:
    """The comparison is a share of maximum mana, not an absolute amount:
    the same absolute current mana arms or denies depending on the maximum
    it is measured against."""

    def test_a_small_share_of_a_large_pool_denies(self) -> None:
        row = _assert_gate_denied(_run(maximum_mana=2_000.0, resource_after=300.0))

        assert row["current_mana"] == pytest.approx(300.0)
        assert row["maximum_mana"] == pytest.approx(2_000.0)

    def test_a_large_share_of_a_small_pool_arms(self) -> None:
        packets = _run(maximum_mana=500.0, resource_after=150.0)

        assert _shields(packets)
        assert [
            row["reason"]
            for row in _denials(packets)
            if row["reason"] != SPATIAL_RECEIPT
        ] == []

    def test_no_current_or_maximum_term_key_is_authored_in_the_typed_registry(
        self,
    ) -> None:
        """The terms are the gate authority's own contract fields, not
        registry keys; asking for them by key still fails loud."""
        for key in ("everlasting_mana_current_term", "everlasting_mana_maximum_term"):
            with pytest.raises(KeyError) as excinfo:
                required_effect_value(FIMBULWINTER, key)
            message = excinfo.value.args[0]
            assert FIMBULWINTER in message
            assert key in message


def test_the_manaless_holder_denies_by_the_gate_rather_than_a_manaless_rule() -> None:
    """A zero-max-mana holder is denied by the ordinary comparison — 0.0 is
    a valid, finite ``max_mana`` (unlike the ``TestManaInputValidation``
    rows), so it reaches the gate rather than a missing/invalid-mana denial,
    and nothing above it authors a manaless special case."""
    row = _assert_gate_denied(_run(maximum_mana=0.0, resource_after=0.0))

    assert row["current_mana"] == pytest.approx(0.0)
    assert row["maximum_mana"] == pytest.approx(0.0)


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

    def test_full_and_score_paths_match_the_gate_receipt(self) -> None:
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

        # Parity is the claim, and it holds whichever way the gate answered:
        # the two paths stage the same shields and the same named receipts.
        fields = ("kind", "reason", "time", "event_id", "mana_gate_status")
        assert [
            tuple(row.get(field) for field in fields) for row in _denials(score_packets)
        ] == [
            tuple(row.get(field) for field in fields) for row in _denials(full_packets)
        ]
        assert [row["amount"] for row in _shields(score_packets)] == [
            row["amount"] for row in _shields(full_packets)
        ]
        assert {row["mana_gate_status"] for row in _denials(full_packets)} <= {
            SOURCE_AUTHORIZED
        }
        assert score["total_damage"] == pytest.approx(full["total_damage"])
