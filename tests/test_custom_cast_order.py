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
from src.calculator.champions import (  # noqa: E402
    parse_champion_abilities,
    registered_champion_names,
)
from src.calculator.damage import _ridden_parent_slot  # noqa: E402
from src.calculator.data_fetcher import get_champion  # noqa: E402
from src.calculator.pipeline import (  # noqa: E402
    CAST_SLOT_SPELLING,
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

    @pytest.mark.parametrize(
        "bad, message",
        [
            ("QWER", "Cast order must be a list of ability slots"),
            (["Q", {}], "Cast order must be a list of ability slots"),
            ([], "Cast order must name at least one ability slot"),
            (["Q", "W", "Q"], "Cast order must not repeat an ability slot"),
        ],
    )
    def test_the_four_shape_messages_are_what_a_400_now_carries(self, bad, message):
        """One retired message became four, and they are public response text.

        Before C6 every malformed order came back as the single sentence
        ``Cast order must be a permutation of Q, W, E, R``.  An API
        consumer matching on that string sees four sentences now, plus a
        fifth from the kit check below, so the set is pinned rather than
        left to be discovered.
        """
        with pytest.raises(ValueError, match=message):
            validate_cast_order_shape(bad, field="Cast order")


class TestPartialOrdersAreRunnable:
    """The widening the shape rule implies, exercised end to end.

    ``validate_cast_order_shape`` accepts any non-empty list of distinct
    slots, so a request may now name a *subset* of the champion's kit —
    both request paths previously demanded a four-slot permutation and
    raised on anything shorter.  ``/api/calculate`` reads ``cast_order``
    straight off the payload, so this is a live widening of a public
    request parameter and not merely an internal shape rule.
    """

    @pytest.mark.parametrize(
        "order, expected_rows",
        [
            (["Q"], {"Q", "auto_attacks"}),
            (["R", "Q"], {"Q", "R", "auto_attacks"}),
        ],
    )
    def test_a_subset_order_runs_and_prices_only_what_it_names(
        self, order, expected_rows
    ):
        result = run_fight(
            get_champion("Ahri"), 18, [], _fight_params(cast_order=order)
        )
        assert set(result["breakdown"]) == expected_rows
        assert result["rotation"]["order"] == order

    def test_the_subset_prices_below_the_full_rotation(self):
        """A sanity floor: fewer casts, less damage, nothing silently added."""
        totals = {
            tuple(order): run_fight(
                get_champion("Ahri"), 18, [], _fight_params(cast_order=order)
            )["total_damage"]
            for order in (["Q"], ["R", "Q"], ["Q", "W", "E", "R"])
        }
        assert totals[("Q",)] < totals[("R", "Q")] < totals[("Q", "W", "E", "R")]

    def test_the_roster_path_accepts_a_subset_too(self):
        """``scenario.py`` held the second copy of the retired literal."""
        parsed = parse_scenario_request(
            {
                "champion": "Ahri",
                "level": 18,
                "items": [],
                "cast_order": ["Q"],
            },
            deterministic=True,
        )
        assert parsed.fight_params.cast_order == ["Q"]


class TestTheResponseEchoesTheExpandedOrder:
    """What the caller gets back is what was cast, not what was sent."""

    def test_the_rotation_order_reports_the_recast_the_request_omitted(self):
        result = _run_scenario("syndra_custom_order_120")
        requested = _scenario("syndra_custom_order_120").request["cast_order"]
        assert requested == ["Q", "W", "E", "R"]
        assert result["rotation"]["order"][:5] == ["Q", "Q2", "W", "E", "R"]
        assert "Q2" not in requested


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
            orderable_slots(cast_slot_surface(kit))

    def test_the_raise_is_reachable_from_the_request_path(self):
        """The fail-closed half must fire where a request is decided.

        ``cast_slot_surface`` used to drop an unstamped ``Q2`` as a rider
        row, so the only thing that could reach ``orderable_slots``'s raise
        was a hand-built surface — and a real kit carrying one was silently
        deleted from the requested order instead, which is the exact defect
        C6 exists to kill.
        """
        kit = dict(_syndra_kit(120))
        kit["W2"] = {"name": "Invented recast", "cooldown": 4.0, "total_raw": 10.0}
        assert "W2" in cast_slot_surface(kit)
        params = _fight_params(cast_order=["Q", "W", "E", "R"])
        with pytest.raises(UnknownSlotError, match="W2"):
            params.validate_for_champion("Syndra", 18, kit=kit)

    def test_the_surface_tells_cast_slots_from_riders_by_spelling(self):
        """Reading ``recast_of`` here would answer the raise's own question."""
        source = (SRC / "pipeline.py").read_text(encoding="utf-8")
        surface = source.split("def cast_slot_surface(")[1].split("\ndef ")[0]
        assert 'entry.get("recast_of")' not in surface
        assert CAST_SLOT_SPELLING.pattern == "^[QWER][0-9]*$"
        for spelling in ("Q", "Q2", "R2", "E3"):
            assert CAST_SLOT_SPELLING.match(spelling), spelling
        for rider in ("W_frenzy", "R_onhit", "tibbers_attacks", "passive", "P"):
            assert not CAST_SLOT_SPELLING.match(rider), rider

    def test_no_registered_champion_holds_an_unstamped_cast_slot(self):
        """The raise's live population, measured over the whole roster.

        Making the raise reachable is only safe because nothing reaches it
        today, and that is a fact about 173 parses, not an assertion.
        """
        unstamped = []
        cast_shaped = []
        for name in registered_champion_names():
            kit = _roster_kit(name)
            for slot, entry in kit.items():
                if not CAST_SLOT_SPELLING.match(slot) or slot in ("Q", "W", "E", "R"):
                    continue
                cast_shaped.append((name, slot))
                if not entry.get("recast_of"):
                    unstamped.append((name, slot))
        assert unstamped == []
        assert cast_shaped == [
            ("Ambessa", "Q2"),
            ("Camille", "Q2"),
            ("Syndra", "Q2"),
        ]

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


class TestThePostParseCallSiteAsksOneQuestion:
    """It has a parse, so it asks the parse's question and only that one.

    ``validated=True`` is a caller-owned claim that
    ``validate_for_champion`` already ran (the coupled search makes it
    thousands of times per search).  A post-parse call that re-ran the whole
    validator would silently revoke that claim for every caller that also
    supplies a cast order — bis.py, the optimizer, and every roster ally,
    whose ``cast_order`` ``roster_composition.actor_params`` forwards.
    """

    def test_a_prevalidated_caller_is_not_revalidated(self):
        params = _fight_params(
            cast_order=["Q", "W", "E", "R"],
            ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
        )
        with pytest.raises(ValueError, match="requires champion level"):
            params.validate_for_champion("Syndra", 6)
        result = run_fight(get_champion("Syndra"), 6, [], params, validated=True)
        assert result["breakdown"]

    def test_the_call_site_names_the_narrow_check(self):
        source = (SRC / "pipeline.py").read_text(encoding="utf-8")
        post_parse = source.split("The post-parse cast-order call site")[1][:600]
        assert "validate_cast_order_for_kit(" in post_parse
        assert "validate_for_champion(" not in post_parse

    def test_a_request_with_no_cast_order_has_nothing_to_check(self):
        params = _fight_params(cast_order=None)
        params.validate_cast_order_for_kit("Syndra", _syndra_kit(120))


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

    @pytest.mark.parametrize(
        "entry, rides",
        [
            ({"recast_of": "Q", "cooldown": 5.0}, "Q"),
            ({"recast_of": "Q", "cooldown": 0.0}, None),
            ({"recast_of": "Q"}, None),
            ({"recast_of": "Q", "cooldown": None}, None),
            ({"recast_of": "Q", "cooldown": -1.0}, None),
            ({"cooldown": 5.0}, None),
        ],
    )
    def test_the_rule_is_a_positive_declared_cooldown(self, entry, rides):
        """Not only zero: absent, ``None`` and negative all fail to ride.

        C6's body framed the guard as "zero-cooldown", which is the only
        shape the roster holds today (Camille 5.0, Ambessa 10.0, Syndra
        0.0).  A future module that stamps ``recast_of`` and omits
        ``cooldown`` gets the once-only semantics too, and that is the
        deliberate reading: no declared timer is no shared timer.
        """
        assert _ridden_parent_slot(entry) == rides


class TestTheRotationReceiptNamesTheRecastOnce:
    """The stamp is now the only producer of the recast sentence.

    Before C6 both the ``recast_of`` loop and ``rotation_resolver``'s
    name-based ``"Q" plus "Q2"`` fallback fired for a stamped Q2, so
    ``detect_setup_consume_edges`` appended the same Q->Q2 edge twice and
    the receipt carried two identical recast sentences.  Deleting the
    fallback left one.  Neither baseline serialises a derived rotation
    receipt for these champions, so nothing else covers this.
    """

    @pytest.mark.parametrize("champion", ["Camille", "Ambessa"])
    def test_one_recast_sentence_per_stamped_pair(self, champion):
        result = run_fight(
            get_champion(champion), 18, [], _fight_params(one_rotation=False)
        )
        sources = result["rotation"]["sources"]
        recast = [line for line in sources if "recast" in line]
        assert recast == ["Q2 is the recast of Q — Q2 is Q's recast (recast_of atom)"]


def _roster_kit(champion):
    """A level-18, item-free parse at the pin scenario's fight shape.

    The sweep's parse: every champion's module defaults, so a slot that
    only exists under an option (Syndra's second charge below 40 splinters)
    appears exactly when its default makes it live.
    """
    data = get_champion(champion)
    stats = calculate_total_stats(data, 18, [])
    return parse_champion_abilities(
        data,
        18,
        stats["ability_power"],
        champion_stats=dict(stats),
        target_stats={
            "target_max_health": 10000.0,
            "target_current_health": 10000.0,
            "target_missing_health": 0.0,
            "roster_target_index": 0.0,
            "roster_target_count": 1.0,
        },
        champion_options={
            "fight_duration_seconds": 12.0,
            "auto_attack_uptime": 0.5,
        },
    )


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
