"""C6 — a custom ``cast_order`` may no longer delete a recast slot (D-11).

The defect: both request paths validated a requested order against the
literal ``sorted(order) == ["E", "Q", "R", "W"]``, so the only orders a
caller could send were the four base slots — and the engine then cast
exactly what it was handed. Syndra's 40-splinter second Dark Sphere
charge is a fifth parsed row that rides Q, so every custom-order request
silently dropped a whole damage row from the breakdown while reporting
success.

The fix has three halves and this suite pins all three: the shape check
stays champion-agnostic, the *which slots* question is answered against
the parsed kit through ``cast_dependency.orderable_slots``, and live
recast slots are folded back in by ``cast_dependency.expand_user_order``.
Recast parentage comes from ``recast_of`` on the parsed entry and from
nothing else — no name table, no ``"Q" + "Q2"`` inference.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import golden_snapshot  # noqa: E402  pylint: disable=wrong-import-position

from src.calculator.cast_dependency import (  # noqa: E402
    UnknownSlotError,
    expand_user_order,
    orderable_slots,
)
from src.calculator.champions import parse_champion_abilities  # noqa: E402
from src.calculator.data_fetcher import get_champion  # noqa: E402
from src.calculator.pipeline import (  # noqa: E402
    FightParams,
    cast_slot_surface,
    run_fight,
    validate_cast_order_shape,
)
from src.calculator.scenario import (  # noqa: E402
    parse_scenario_request,
    resolve_scenario,
)
from src.calculator.stats import calculate_total_stats  # noqa: E402

SRC = ROOT / "src" / "calculator"


def _scenario(name):
    """One named coupled scenario from 0A.2's set — the parameters live there."""
    for scenario in golden_snapshot.COUPLED_SCENARIOS:
        if scenario.name == name:
            return scenario
    raise AssertionError(f"coupled scenario {name!r} is missing")


def _run_scenario(name):
    """Run a named coupled scenario's main attacker through the public path."""
    parsed = parse_scenario_request(dict(_scenario(name).request), deterministic=True)
    resolved = resolve_scenario(parsed)
    return run_fight(
        resolved.champion_data,
        parsed.level,
        list(resolved.items),
        resolved.fight_params,
    )


def _timeline(result):
    """The public cast timeline as (time, slot) pairs."""
    return [(cast["time"], cast["slot"]) for cast in result["cast_timeline"]]


def _syndra_kit(splinters):
    """Syndra's parsed kit at the pin scenario's ranks and splinter count."""
    data = get_champion("Syndra")
    stats = calculate_total_stats(data, 18, [])
    return parse_champion_abilities(
        data,
        18,
        stats["ability_power"],
        ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
        champion_stats=dict(stats),
        target_stats={
            "target_max_health": 10000.0,
            "target_current_health": 10000.0,
            "target_missing_health": 0.0,
            "roster_target_index": 0.0,
            "roster_target_count": 1.0,
        },
        champion_options={
            "splinters": splinters,
            "fight_duration_seconds": 12.0,
            "auto_attack_uptime": 0.0,
        },
    )


class TestRecastParentageHasOneAuthority:
    """``recast_of`` on the parsed entry, and nothing that reads a name."""

    def test_syndra_second_charge_is_stamped(self):
        assert _syndra_kit(120)["Q2"]["recast_of"] == "Q"

    def test_the_name_based_q_to_q2_fallback_is_gone(self):
        source = (SRC / "rotation_resolver.py").read_text(encoding="utf-8")
        assert "Q2 is Q's second cast" not in source
        assert '"Q2" in corpora' not in source

    def test_every_stamped_recast_names_a_slot_its_own_kit_has(self):
        """A stamp pointing at an absent parent would strand the recast."""
        for splinters in (60, 120):
            kit = _syndra_kit(splinters)
            for slot, entry in kit.items():
                parent = entry.get("recast_of")
                if parent:
                    assert parent in kit, f"{slot} is a recast of absent {parent}"


class TestChampionAgnosticShapeCheck:
    """What ``_validate_request_values`` and ``scenario.py`` still decide."""

    @pytest.mark.parametrize(
        "bad", ["QWER", ["Q", {}], [], ["Q", "W", "Q"], ["Q", "Q"]]
    )
    def test_malformed_orders_are_rejected(self, bad):
        with pytest.raises(ValueError):
            validate_cast_order_shape(bad, field="Cast order")

    @pytest.mark.parametrize(
        "good", [None, ["Q"], ["Q", "W"], ["R", "E", "Q", "W"], ["Q", "Q2", "W"]]
    )
    def test_the_shape_check_names_no_champion(self, good):
        """It may not decide which slots exist — only that the list is well formed."""
        validate_cast_order_shape(good, field="Cast order")

    def test_neither_permutation_literal_survives(self):
        for module in ("pipeline.py", "scenario.py"):
            source = (SRC / module).read_text(encoding="utf-8")
            assert '["E", "Q", "R", "W"]' not in source, module
            assert "permutation of Q, W, E, R" not in source, module


class TestOrderableSlotsAnswerTheChampionQuestion:
    """The kit decides which slots a request may name."""

    def test_syndra_offers_the_four_base_slots_and_not_the_recast(self):
        assert orderable_slots(cast_slot_surface(_syndra_kit(120))) == (
            "Q",
            "W",
            "E",
            "R",
        )

    def test_naming_the_recast_slot_is_rejected(self):
        params = _fight_params(cast_order=["Q", "Q2", "W", "E", "R"])
        with pytest.raises(ValueError, match="Q2"):
            params.validate_for_champion("Syndra", 18, kit=_syndra_kit(120))

    def test_naming_a_slot_the_kit_does_not_have_is_rejected(self):
        params = _fight_params(cast_order=["Q", "W", "E", "R", "Z"])
        with pytest.raises(ValueError, match="Z"):
            params.validate_for_champion("Syndra", 18, kit=_syndra_kit(120))

    def test_an_unstamped_synthetic_cast_slot_raises(self):
        """Neither a base slot nor a declared recast — nothing may guess (D-11)."""
        kit = dict(_syndra_kit(120))
        kit["W2"] = {"name": "Invented recast", "cooldown": 4.0, "total_raw": 10.0}
        with pytest.raises(UnknownSlotError, match="W2"):
            orderable_slots({**cast_slot_surface(kit), "W2": kit["W2"]})

    def test_rider_rows_are_not_cast_slots(self):
        """Briar's Frenzy swing is priced through its own atoms, never ordered."""
        data = get_champion("Briar")
        stats = calculate_total_stats(data, 18, [])
        kit = parse_champion_abilities(
            data,
            18,
            stats["ability_power"],
            champion_stats=dict(stats),
            target_stats={
                "target_max_health": 1000.0,
                "target_current_health": 1000.0,
                "target_missing_health": 0.0,
                "roster_target_index": 0.0,
                "roster_target_count": 1.0,
            },
            champion_options={
                "fight_duration_seconds": 5.0,
                "auto_attack_uptime": 0.0,
            },
        )
        assert "W_frenzy" in kit
        assert "W_frenzy" not in cast_slot_surface(kit)
        assert orderable_slots(cast_slot_surface(kit)) == ("Q", "W", "E", "R")


class TestExpansionReinsertsTheRecast:
    """``expand_user_order`` folds a live recast in after its parent."""

    def test_the_live_recast_follows_its_parent(self):
        assert expand_user_order(["Q", "W", "E", "R"], _syndra_kit(120)) == [
            "Q",
            "Q2",
            "W",
            "E",
            "R",
        ]

    def test_an_absent_recast_changes_nothing(self):
        """Below 40 splinters there is no second charge to fold in."""
        assert expand_user_order(["Q", "W", "E", "R"], _syndra_kit(39)) == [
            "Q",
            "W",
            "E",
            "R",
        ]


class TestTheCustomOrderPinScenario:
    """Criterion 14: C6 is pinned by a timeline, not a scalar.

    The parameter set lives once, in 0A.2's ``syndra_custom_order``
    scenario definition; this suite runs it by name and retypes nothing.
    """

    def test_the_requested_order_keeps_the_second_charge(self):
        result = _run_scenario("syndra_custom_order_120")
        assert result["breakdown"]["Q2"]["casts"] == 1
        assert (0.0, "Q2") in _timeline(result)

    def test_the_second_charge_casts_once_not_once_per_parent_cast(self):
        """A zero-cooldown charge is one extra cast, not one per Q."""
        result = _run_scenario("syndra_custom_order_120")
        assert result["breakdown"]["Q"]["casts"] == 3
        assert [slot for _, slot in _timeline(result)].count("Q2") == 1

    def test_the_requested_timeline_is_not_the_derived_timeline(self):
        """Otherwise a fall-through to the derived order would also pass."""
        requested = _timeline(_run_scenario("syndra_custom_order_120"))
        derived = _timeline(_run_scenario("syndra_derived_order_120"))
        assert requested != derived
        assert (0.0, "Q2") in requested and (0.0, "Q2") in derived

    def test_a_kit_without_the_charge_is_untouched(self):
        """39 splinters: no recast is live, so the order is what was asked."""
        result = _run_scenario("syndra_custom_order_39")
        assert "Q2" not in result["breakdown"]
        assert [slot for _, slot in _timeline(result)] == [
            "Q",
            "W",
            "E",
            "R",
            "Q",
            "W",
            "Q",
        ]

    def test_the_roster_path_accepts_the_same_request(self):
        """``scenario.py`` held the second copy of the retired literal."""
        parsed = parse_scenario_request(
            dict(_scenario("syndra_custom_order_120").request), deterministic=True
        )
        resolved = resolve_scenario(parsed)
        assert [ally.request.cast_order for ally in resolved.allies] == [
            ["Q", "W", "E", "R"]
        ]


class TestTheRecastCastCountRuleStaysScoped:
    """Riding the parent's cast count is a claim about a shared cooldown."""

    @pytest.mark.parametrize("champion", ["Camille", "Ambessa"])
    def test_a_cooldown_bearing_recast_still_rides_its_parent(self, champion):
        data = get_champion(champion)
        result = run_fight(data, 18, [], _fight_params(one_rotation=False))
        breakdown = result["breakdown"]
        assert breakdown["Q2"]["casts"] == breakdown["Q"]["casts"]

    def test_syndra_is_the_only_zero_cooldown_recast_in_the_roster(self):
        """The guard's whole population, so its scope is measured not asserted."""
        zero_cooldown = []
        for name in ("Syndra", "Camille", "Ambessa"):
            kit = _syndra_kit(120) if name == "Syndra" else _parsed_kit(name)
            for slot, entry in kit.items():
                if entry.get("recast_of") and not float(
                    entry.get("cooldown", 0.0) or 0
                ):
                    zero_cooldown.append((name, slot))
        assert zero_cooldown == [("Syndra", "Q2")]


class TestPairEngineGoldenIsStructurallyBlind:
    """C6's 'zero on pair-engine golden' is asserted, never assumed."""

    def test_every_snapshot_fight_is_built_with_no_cast_order(self):
        source = (ROOT / "scripts" / "golden_snapshot.py").read_text(encoding="utf-8")
        assert source.count("FightParams(") == 1
        assert "cast_order=None," in source


class TestTheAllowlistIsCommitted:
    """R-17: the code lands against the committed baseline plus an allowlist."""

    def test_the_c6_allowlist_names_its_population(self):
        receipt = json.loads(
            (ROOT / "docs" / "receipts" / "expected-golden-diff-C6.json").read_text(
                encoding="utf-8"
            )
        )
        assert receipt["slice"] == "C6"
        assert receipt["decisions"] == ["D-11"]
        population = receipt["qualifying_population"]
        assert population["enumerated_before_first_src_edit"] is True
        assert set(population["scenarios"]) == {
            "syndra_custom_order_39",
            "syndra_custom_order_60",
            "syndra_custom_order_120",
        }


def _parsed_kit(champion):
    """A level-18 parse with no items, for the recast-scope population."""
    data = get_champion(champion)
    stats = calculate_total_stats(data, 18, [])
    return parse_champion_abilities(
        data,
        18,
        stats["ability_power"],
        champion_stats=dict(stats),
        target_stats={
            "target_max_health": 1000.0,
            "target_current_health": 1000.0,
            "target_missing_health": 0.0,
            "roster_target_index": 0.0,
            "roster_target_count": 1.0,
        },
        champion_options={"fight_duration_seconds": 5.0, "auto_attack_uptime": 0.0},
    )


def _fight_params(**overrides):
    """A one-rotation FightParams, field-overridable."""
    config = {
        "target_health": 1000.0,
        "target_bonus_health": 0.0,
        "target_armor": 0.0,
        "target_magic_resistance": 0.0,
        "fight_duration_seconds": 5.0,
        "auto_attack_uptime": 0.0,
        "one_rotation": True,
        "include_actives": True,
        "cast_order": None,
        "auto_attacks_only": False,
        "ability_ranks": None,
        "champion_options": None,
        "deterministic": True,
    }
    config.update(overrides)
    return FightParams(**config)
