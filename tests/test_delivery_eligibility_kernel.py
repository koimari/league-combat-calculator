"""P2 delivery/eligibility kernel: declarations, classification, eligibility,
composition rules, and fail-closed behavior (roadmap P2).

Covers the shared contracts in ``src/calculator/delivery_eligibility.py``:
the six typed delivery declarations with source receipts, deterministic
delivery classification (projectile / hitscan / area / targeted / basic
attack / damage over time), the named fail-closed path for unclassifiable
deliveries, window boundaries (start inclusive, end exclusive), source-
slot and event-id selection, the delivery acceptance gates, and the
orthogonal composition rules (finite
uses, first-valid-hit, destruction, later-hit reduction).
"""

import pytest

from src.calculator import delivery_eligibility as de
from src.calculator.state_lifecycle import SourceReceipt


class _Action:
    """Minimal survival-action stand-in carrying the typed markers."""

    def __init__(
        self,
        *,
        time: float = 0.0,
        sequence: int = 0,
        source_key: str = "Q",
        source: str = "Q",
        event_id: str | None = None,
        is_ability: bool = True,
        basic_attack: bool = False,
        damage_over_time: bool = False,
        skillshot: bool = False,
        area_damage: bool = False,
        amount: float = 100.0,
        damage_type: str = "magic",
    ) -> None:
        self.time = time
        self.sequence = sequence
        self.source_key = source_key
        self.source = source
        self.event_id = event_id
        self.is_ability = is_ability
        self.basic_attack = basic_attack
        self.damage_over_time = damage_over_time
        self.skillshot = skillshot
        self.area_damage = area_damage
        self.amount = amount
        self.damage_type = damage_type


class _Attacker:
    def __init__(self, name: str) -> None:
        self.champion_data = {"name": name}


# ---------------------------------------------------------------------------
# Delivery declarations
# ---------------------------------------------------------------------------


class TestDeliveryDeclarations:
    def test_six_declared_classes_with_receipts(self) -> None:
        assert de.DELIVERY_CLASSES == (
            "projectile",
            "hitscan",
            "area",
            "targeted",
            "basic_attack",
            "damage_over_time",
        )
        receipt = de.delivery_declarations_receipt()
        assert [row["delivery"] for row in receipt] == list(de.DELIVERY_CLASSES)
        for row in receipt:
            assert row["description"]
            assert row["source"]["url"].startswith("https://")
            assert row["marker"] in {
                "skillshot",
                "area_damage",
                "basic_attack",
                "damage_over_time",
                "",
            }

    def test_markers_are_the_engine_typed_stamps(self) -> None:
        by_delivery = {
            row["delivery"]: row for row in de.delivery_declarations_receipt()
        }
        assert by_delivery["projectile"]["marker"] == "skillshot"
        assert by_delivery["area"]["marker"] == "area_damage"
        assert by_delivery["basic_attack"]["marker"] == "basic_attack"
        assert by_delivery["damage_over_time"]["marker"] == "damage_over_time"


# ---------------------------------------------------------------------------
# Delivery classification
# ---------------------------------------------------------------------------


class TestClassifyDelivery:
    def test_projectile_from_skillshot_marker(self) -> None:
        profile = de.classify_delivery(_Action(skillshot=True))
        assert profile.classes == frozenset({"projectile"})
        assert not profile.unknown
        assert profile.has("projectile")

    def test_area_and_projectile_combine(self) -> None:
        profile = de.classify_delivery(_Action(skillshot=True, area_damage=True))
        assert profile.classes == frozenset({"projectile", "area"})

    def test_basic_attack_is_its_own_class(self) -> None:
        profile = de.classify_delivery(_Action(basic_attack=True, is_ability=False))
        assert profile.classes == frozenset({"basic_attack"})

    def test_damage_over_time_is_its_own_class(self) -> None:
        profile = de.classify_delivery(_Action(damage_over_time=True))
        assert profile.classes == frozenset({"damage_over_time"})

    def test_ability_without_markers_is_targeted(self) -> None:
        profile = de.classify_delivery(_Action(is_ability=True))
        assert profile.classes == frozenset({"targeted"})
        assert not profile.unknown

    def test_non_ability_without_markers_is_unknown(self) -> None:
        profile = de.classify_delivery(_Action(is_ability=False))
        assert profile.classes == frozenset()
        assert profile.unknown
        assert profile.unknown_markers == ("no_declared_marker",)
        assert profile.public_receipt()["unknown"] is True

    def test_public_receipt_is_json_safe(self) -> None:
        receipt = de.classify_delivery(
            _Action(skillshot=True, area_damage=True)
        ).public_receipt()
        assert receipt == {
            "classes": ["area", "projectile"],
            "unknown": False,
            "unknown_markers": [],
        }


class TestRequiredDeliveryClass:
    def test_returns_the_accepted_class(self) -> None:
        action = _Action(skillshot=True, is_ability=True)
        assert (
            de.required_delivery_class(action, frozenset({"projectile", "area"}))
            == "projectile"
        )

    def test_fails_closed_on_unknown(self) -> None:
        action = _Action(is_ability=False)
        with pytest.raises(de.UnknownDeliveryError, match="unknown delivery"):
            de.required_delivery_class(action, frozenset({"projectile"}))

    def test_fails_closed_on_not_accepted(self) -> None:
        action = _Action(skillshot=True)
        with pytest.raises(de.UnknownDeliveryError, match="not accepted"):
            de.required_delivery_class(action, frozenset({"area"}))


# ---------------------------------------------------------------------------
# Window and selection
# ---------------------------------------------------------------------------


class TestDefenseWindow:
    def test_start_inclusive_end_exclusive(self) -> None:
        window = de.DefenseWindow(start=0.25, until=4.0)
        assert window.active_at(0.25) is True
        assert window.active_at(1.0) is True
        assert window.active_at(3.999) is True
        assert window.active_at(4.0) is False
        assert window.active_at(0.249) is False

    def test_receipt_rounds_and_keeps_atoms(self) -> None:
        window = de.DefenseWindow(
            start=0.0, until=4.0, source_atoms=({"atom_id": "x"},)
        )
        receipt = window.public_receipt()
        assert receipt["start"] == 0.0
        assert receipt["until"] == 4.0
        assert receipt["source_atoms"] == [{"atom_id": "x"}]


class TestSourceSelection:
    def test_empty_selection_selects_everything(self) -> None:
        selection = de.SourceSelection()
        assert selection.selects(_Action(source_key="Q"), _Attacker("Ezreal")) == (
            True,
            "",
        )

    def test_source_slot_matches_casefolded_candidates(self) -> None:
        selection = de.SourceSelection(blocked_sources=("q",))
        assert selection.selects(_Action(source_key="Q"), _Attacker("Ezreal")) == (
            True,
            "",
        )
        # Attacker-prefixed spellings match too.
        selection = de.SourceSelection(blocked_sources=("Ezreal:Q", "Ezreal Q"))
        assert selection.selects(_Action(source_key="Q"), _Attacker("Ezreal")) == (
            True,
            "",
        )
        # Unselected source is denied with the named reason.
        selection = de.SourceSelection(blocked_sources=("W",))
        assert selection.selects(_Action(source_key="Q"), _Attacker("Ezreal")) == (
            False,
            "source_not_selected",
        )

    def test_event_id_selection_is_exact(self) -> None:
        selection = de.SourceSelection(blocked_event_ids=("main:enemy:Braum:4",))
        assert selection.selects(
            _Action(source_key="Q", event_id="main:enemy:Braum:4"), _Attacker("Ezreal")
        ) == (True, "")
        assert selection.selects(
            _Action(source_key="Q", event_id="main:enemy:Braum:1"), _Attacker("Ezreal")
        ) == (False, "source_not_selected")

    def test_slot_and_event_id_selection_union(self) -> None:
        selection = de.SourceSelection(
            blocked_sources=("Q",), blocked_event_ids=("main:enemy:Braum:4",)
        )
        # Matched by slot.
        assert selection.selects(
            _Action(source_key="Q", event_id="main:enemy:Braum:0"), _Attacker("Ezreal")
        ) == (True, "")
        # Matched by event id even when the slot differs.
        assert selection.selects(
            _Action(source_key="W", event_id="main:enemy:Braum:4"), _Attacker("Ezreal")
        ) == (True, "")

    def test_receipt_shows_both_lists(self) -> None:
        selection = de.SourceSelection(
            blocked_sources=("Q",), blocked_event_ids=("main:enemy:Braum:1",)
        )
        assert selection.public_receipt() == {
            "blocked_sources": ["Q"],
            "blocked_event_ids": ["main:enemy:Braum:1"],
        }


# ---------------------------------------------------------------------------
# Delivery acceptance
# ---------------------------------------------------------------------------


class TestDeliveryAcceptance:
    def test_skillshot_only_defense(self) -> None:
        rule = de.DeliveryAcceptance(requires_skillshot=True)
        assert rule.accepts_deliveries() == ("projectile",)
        assert rule.accepts(
            _Action(skillshot=True), de.classify_delivery(_Action(skillshot=True))
        ) == (True, "")
        denied, reason = rule.accepts(
            _Action(skillshot=False, is_ability=True),
            de.classify_delivery(_Action(skillshot=False, is_ability=True)),
        )
        assert (denied, reason) == (False, "delivery_not_accepted")

    def test_basic_and_area_only_defense_jax(self) -> None:
        rule = de.DeliveryAcceptance(
            requires_skillshot=False,
            blocks_basic_attacks=True,
            area_damage_reduction=0.25,
        )
        assert rule.accepts_deliveries() == ("basic_attack", "area")
        basic = _Action(basic_attack=True, is_ability=False)
        assert rule.accepts(basic, de.classify_delivery(basic)) == (True, "")
        area = _Action(area_damage=True)
        assert rule.accepts(area, de.classify_delivery(area)) == (True, "")
        skillshot = _Action(skillshot=True)
        assert rule.accepts(skillshot, de.classify_delivery(skillshot)) == (
            False,
            "delivery_not_accepted",
        )

    def test_fiora_full_block_accepts_unknown_by_declaration(self) -> None:
        rule = de.DeliveryAcceptance(requires_skillshot=False, accepts_unknown=True)
        assert rule.accepts_deliveries() == de.DELIVERY_CLASSES
        packet = _Action(is_ability=False)
        assert rule.accepts(packet, de.classify_delivery(packet)) == (True, "")

    def test_unknown_delivery_fails_closed_with_named_reason(self) -> None:
        rule = de.DeliveryAcceptance()
        packet = _Action(is_ability=False)
        denied, reason = rule.accepts(packet, de.classify_delivery(packet))
        assert (denied, reason) == (False, "unknown_delivery")


# ---------------------------------------------------------------------------
# Eligibility decisions
# ---------------------------------------------------------------------------


class TestEligibilityDecide:
    def _braum_like(self) -> de.DefenseEligibility:
        return de.DefenseEligibility(
            name="braum_unbreakable",
            window=de.DefenseWindow(start=0.0, until=4.0),
            acceptance=de.DeliveryAcceptance(requires_skillshot=True),
        )

    def test_eligible_projectile_in_window(self) -> None:
        decision = self._braum_like().decide(
            _Action(time=0.25, skillshot=True, source_key="Q"), _Attacker("Ezreal")
        )
        assert decision.eligible
        assert decision.reason == ""
        assert decision.delivery.classes == frozenset({"projectile"})
        receipt = decision.public_receipt()
        assert receipt["eligible"] is True
        assert receipt["delivery"]["classes"] == ["projectile"]

    def test_outside_window_is_named_denial(self) -> None:
        decision = self._braum_like().decide(
            _Action(time=4.0, skillshot=True, source_key="Q"), _Attacker("Ezreal")
        )
        assert (decision.eligible, decision.reason) == (False, "outside_window")

    def test_source_not_selected_is_named_denial(self) -> None:
        eligibility = de.DefenseEligibility(
            name="braum_unbreakable",
            window=de.DefenseWindow(start=0.0, until=4.0),
            selection=de.SourceSelection(blocked_sources=("Q",)),
            acceptance=de.DeliveryAcceptance(requires_skillshot=True),
        )
        decision = eligibility.decide(
            _Action(time=0.25, skillshot=True, source_key="W", source="W"),
            _Attacker("Ezreal"),
        )
        assert (decision.eligible, decision.reason) == (
            False,
            "source_not_selected",
        )

    def test_targeted_delivery_denied_by_skillshot_rule(self) -> None:
        decision = self._braum_like().decide(
            _Action(time=0.25, is_ability=True), _Attacker("Ezreal")
        )
        assert (decision.eligible, decision.reason) == (
            False,
            "delivery_not_accepted",
        )
        assert decision.delivery.classes == frozenset({"targeted"})

    def test_unknown_delivery_fails_closed(self) -> None:
        decision = self._braum_like().decide(
            _Action(time=0.25, is_ability=False), _Attacker("Ezreal")
        )
        assert (decision.eligible, decision.reason) == (False, "unknown_delivery")

    def test_event_key_is_stable_and_deterministic(self) -> None:
        first = _Action(time=0.25, sequence=2, source_key="Q")
        second = _Action(time=0.25, sequence=2, source_key="Q")
        assert de.stable_event_key(first) == de.stable_event_key(second) == "Q:0.25:2"
        assert de.stable_event_key(_Action(time=0.25, sequence=3, source_key="Q")) == (
            "Q:0.25:3"
        )

    def test_public_receipt_is_json_safe(self) -> None:
        decision = self._braum_like().decide(
            _Action(time=4.0, skillshot=True, source_key="Q"), _Attacker("Ezreal")
        )
        assert decision.public_receipt() == {
            "eligible": False,
            "reason": "outside_window",
            "delivery": {
                "classes": ["projectile"],
                "unknown": False,
                "unknown_markers": [],
            },
            "event_key": "Q:4.0:0",
        }


# ---------------------------------------------------------------------------
# Composition rules (orthogonal: uses, first-hit, destruction, reduction)
# ---------------------------------------------------------------------------


class TestComposition:
    def test_braum_composition_first_block_one_use(self) -> None:
        composition = de.DefenseComposition(
            full_block=de.FullBlockRule(mode="first", blocks_true_damage=False),
            full_block_uses=de.UseBudget(
                action_mode="full_block", uses=1, consume="first_eligible"
            ),
            reduction=de.ReductionRule(later_hit_reduction=0.55),
        )
        assert de.initial_full_block_uses(composition) == 1
        assert composition.full_block.blocks_true_damage is False
        assert composition.reduction.reduction_for(_Action()) == 0.55
        # Braum has no area rule: area-marked skillshots use later-hit.
        assert composition.reduction.reduction_for(_Action(area_damage=True)) == 0.55

    def test_yasuo_composition_unlimited_destruction(self) -> None:
        composition = de.DefenseComposition(destroy=de.DestructionRule(enabled=True))
        assert de.initial_full_block_uses(composition) is None
        assert composition.destroy.enabled is True
        assert composition.full_block.mode == "none"

    def test_jax_area_reduction_uses_the_declared_area_rule(self) -> None:
        composition = de.DefenseComposition(
            full_block=de.FullBlockRule(mode="all", blocks_true_damage=True),
            reduction=de.ReductionRule(
                later_hit_reduction=0.0,
                area_damage_reduction=0.25,
                applies_to_true_damage=True,
            ),
        )
        assert composition.reduction.reduction_for(_Action(area_damage=True)) == 0.25
        assert composition.reduction.reduction_for(_Action()) == 0.0

    def test_public_receipts_are_json_safe(self) -> None:
        composition = de.DefenseComposition(
            full_block=de.FullBlockRule(mode="first", blocks_true_damage=False),
            full_block_uses=de.UseBudget(
                action_mode="full_block", uses=1, consume="first_eligible"
            ),
            destroy=de.DestructionRule(enabled=False),
            reduction=de.ReductionRule(later_hit_reduction=0.55),
        )
        receipt = composition.public_receipt()
        assert receipt["full_block"]["mode"] == "first"
        assert receipt["full_block_uses"]["uses"] == 1
        assert receipt["destroy"]["enabled"] is False
        assert receipt["reduction"]["later_hit_reduction"] == pytest.approx(0.55)

    def test_declaration_validation_rejects_bad_use_budgets(self) -> None:
        with pytest.raises(ValueError, match="uses"):
            de.UseBudget(action_mode="full_block", uses=0)


__all__ = []
