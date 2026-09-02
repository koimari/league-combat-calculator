"""Every published number is named by exactly one dispositions entry.

Umbrella criterion 1, as a machine check rather than an audit over a
hand-maintained path list.  The mechanism is not this file: it is that
``serialize_leaf`` emits a payload leaf and its map entry in one call and
nothing else emits either, so the two cannot drift.  What is here is the
**backstop** behind that single writer -- a two-way key-set equality that goes
red if a leaf is ever published by some other route, or if an entry ever names
a path that is neither a present number nor a declared refusal.

The three payloads are checked at their own boundaries: ``/api/calculate``'s
combat receipt, ``/api/bis`` and ``/api/optimize``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest

from src.calculator.ability_spec import Disposition

DISPOSITIONS = {member.value for member in Disposition}


def numeric_leaf_paths(payload: Mapping, *, skip: Sequence[str] = ()) -> set[str]:
    """Every *quantity* leaf path under *payload*, in the map's key grammar.

    A quantity is a float.  Three kinds of number are deliberately not one,
    and each exclusion is a rule rather than a convenience:

    * ``bool`` -- a flag is not a quantity, and ``isinstance(True, int)`` is
      Python's own trap here;
    * ``int`` -- the payload's ints are identifiers and counts (``sequence``,
      ``level``, a stack count, a candidate count).  A disposition answers
      "did a rule produce this number, or is it standing in for one that did
      not run", and an ordinal has no such reading.  Every leaf a view wrote
      through ``measured`` comes back from the precision registry as a float,
      so this rule and the writer's own agree by construction;
    * blocks named in ``skip`` -- the payload's non-view sections and its
      republications, named at each call site with the reason.
    """
    found: set[str] = set()

    def walk(node, path: str) -> None:
        if isinstance(node, Mapping):
            for key, value in node.items():
                if not path and key in skip:
                    continue
                walk(value, f"{path}.{key}" if path else str(key))
        elif isinstance(node, (list, tuple)):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")
        elif isinstance(node, bool):
            return
        elif isinstance(node, float):
            found.add(path)

    walk(payload, "")
    return found


def entries_are_well_formed(dispositions: Mapping) -> None:
    """Every entry names one of the four spellings and exactly one view tag."""
    for path, entry in dispositions.items():
        assert entry["disposition"] in DISPOSITIONS, path
        assert entry["view_tag"] in {"applied", "theoretical"}, path
        if entry["disposition"] == Disposition.WITHHELD.value:
            assert entry["receipts"], path
        if entry["disposition"] == Disposition.STRUCTURAL_ZERO.value:
            assert entry["reason"], path


def assert_covered(payload: Mapping, *, skip: Sequence[str] = ()) -> None:
    """The two-way check: map keys are exactly the numbers plus the refusals.

    The whole payload, in one call, by the map's own path grammar.  ``skip``
    exists for a payload block that is genuinely not a view's output -- an
    echo of the request, a counter of the search itself -- and every use of
    it names the block and the reason at the call site.  It is deliberately
    awkward to reach for: the first version of this suite never called this
    function at all and re-derived a *hand-enumerated* list of blocks
    instead, which is how a hundred-odd leaves per payload stayed invisible
    to a check whose name says "covered".
    """
    dispositions = payload["dispositions"]
    entries_are_well_formed(dispositions)
    published = numeric_leaf_paths(
        {key: value for key, value in payload.items() if key != "dispositions"},
        skip=skip,
    )
    withheld = {
        path
        for path, entry in dispositions.items()
        if entry["disposition"] == Disposition.WITHHELD.value
    }
    named = set(dispositions)
    # A map entry naming neither a present leaf nor a withheld path fails.
    assert sorted(named - published - withheld) == []
    # Every leaf a view published carries an entry.  The difference is what a
    # second producer of payload numbers would look like.
    assert sorted(published - named) == []


def coverage_of_a_whole_response(response: Mapping) -> dict[str, set[str]]:
    """One /api/calculate response's leaves against *both* of its maps.

    The response carries two ``dispositions`` maps and each covers one block:
    ``combat`` is the five views' own payload, named by the receipt view's
    writer at the paths inside it, and the response's own map covers
    everything else.  Two maps rather than one because criterion 5 says
    **exactly one** entry per leaf: a top-level map that also re-described
    the 495 leaves of the combat receipt would give each of them a second
    entry, and the second describer is the drift the single writer exists to
    make impossible.

    So the check is over the union: every numeric leaf of the response is
    named once, by the map of the block it lives in, and the two maps'
    domains do not overlap.
    """
    combat = response.get("combat") or {}
    body = {key: value for key, value in response.items() if key != "combat"}
    published = numeric_leaf_paths(
        {key: value for key, value in body.items() if key != "dispositions"}
    ) | {
        f"combat.{path}"
        for path in numeric_leaf_paths(
            {key: value for key, value in combat.items() if key != "dispositions"}
        )
    }
    own = response["dispositions"]
    inherited = {
        f"combat.{path}": entry
        for path, entry in combat.get("dispositions", {}).items()
    }
    entries_are_well_formed(own)
    entries_are_well_formed(inherited)
    return {
        "published": published,
        "named": set(own) | set(inherited),
        "withheld": {
            path
            for path, entry in {**own, **inherited}.items()
            if entry["disposition"] == Disposition.WITHHELD.value
        },
        "overlapping": set(own) & set(inherited),
    }


# ---------------------------------------------------------------------------
# The three payloads, checked against live runs rather than against fixtures
# ---------------------------------------------------------------------------

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _golden_snapshot():
    """The capture instrument, imported by path exactly as its own tests do."""
    spec = importlib.util.spec_from_file_location(
        "golden_snapshot", REPO_ROOT / "scripts" / "golden_snapshot.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("golden_snapshot", module)
    spec.loader.exec_module(module)
    return module


def _combat(name: str = "mandate_abyssal_curse_roster") -> Mapping:
    """One coupled scenario's combat receipt, run live."""
    snapshot = _golden_snapshot()
    scenario = next(item for item in snapshot.COUPLED_SCENARIOS if item.name == name)
    return snapshot.coupled_entry(scenario)["combat"]


def _score_mode(scenario_name: str, *, published: bool) -> Mapping:
    """One score-mode scenario's payload, with and without a reader."""
    from src.calculator.defensive_effects import resolve_starting_defenses
    from src.calculator.participant_timeline import (
        CoupledSearchContext,
        build_participant_timeline,
    )
    from src.calculator.scenario import parse_scenario_request, resolve_scenario
    from src.calculator.stats import calculate_total_stats

    snapshot = _golden_snapshot()
    scenario = next(
        item for item in snapshot.COUPLED_SCENARIOS if item.name == scenario_name
    )
    parsed = parse_scenario_request(dict(scenario.request), deterministic=True)
    resolved = resolve_scenario(parsed)
    params = resolved.fight_params
    stats = calculate_total_stats(
        resolved.champion_data,
        parsed.level,
        list(resolved.items),
        item_options=params.item_options,
        role=params.role,
        role_quest_complete=params.role_quest_complete,
        external_stat_bonuses=params.ally_stat_bonuses,
    )
    return build_participant_timeline(
        resolved.champion_data,
        parsed.level,
        list(resolved.items),
        params,
        main_stats=stats,
        main_defenses=resolve_starting_defenses(
            resolved.champion_data["name"],
            parsed.level,
            stats,
            list(resolved.items),
            item_options=params.item_options,
        ),
        enemies=list(resolved.enemies),
        allies=list(resolved.allies),
        include_receipt=False,
        search_context=CoupledSearchContext(),
        pair_result_cache={},
        published=published,
    )


#: Every coupled scenario carrying a combat receipt, so the check runs over
#: the payload shapes the baseline actually holds rather than over one.
COMBAT_SCENARIOS = (
    "mandate_abyssal_curse_roster",
    "cleaver_bloodsong_roster",
    "dream_maker_roster",
    "catalyst_roster",
    "syndra_custom_order_60",
)


#: One coupled request, the shape the endpoint is actually asked for: a
#: roster on both sides, so the response carries targets, allies, a combat
#: receipt and the whole per-target fight block rather than the single-fight
#: short form.
CALCULATE_REQUEST = {
    "champion": "Syndra",
    "level": 13,
    "items": ["Malignance"],
    "enemies": [
        {"champion": "Aatrox", "level": 13, "items": []},
        {"champion": "Ashe", "level": 13, "items": []},
    ],
    "allies": [{"champion": "Lulu", "level": 13, "items": [], "role": "support"}],
}


def _calculate(request: Mapping | None = None) -> Mapping:
    """One live ``/api/calculate`` response, through the app it is served by."""
    from src.app import app

    app.config["RATE_LIMIT_ENABLED"] = False
    response = app.test_client().post(
        "/api/calculate", json=dict(request or CALCULATE_REQUEST)
    )
    assert response.status_code == 200
    return response.get_json()


class TestTheWholeCalculateResponse:
    """The endpoint, not the sub-object — criterion 5's actual sentence.

    The combat receipt is where the five views publish, and it was the only
    block this file ever walked: ``_combat()`` returns
    ``coupled_entry(...)['combat']``, so 492 of the response's 987 numbers --
    the headline ``total_damage``, every ``champion_stats`` leaf, the
    top-level ``breakdown``, ``cast_timeline`` and ``damage_events`` -- were
    outside a check whose criterion says "every numeric leaf of the
    /api/calculate payload".  ``/api/bis`` and ``/api/optimize`` were given
    whole-payload treatment in the same slice; this endpoint was not, and
    nothing recorded the difference.
    """

    def test_every_number_the_endpoint_serves_carries_exactly_one_entry(self) -> None:
        """Both maps, one union, both directions, no overlap."""
        coverage = coverage_of_a_whole_response(_calculate())
        assert (
            sorted(coverage["named"] - coverage["published"] - coverage["withheld"])
            == []
        )
        assert sorted(coverage["published"] - coverage["named"]) == []
        assert sorted(coverage["overlapping"]) == []

    def test_the_response_names_numbers_outside_its_combat_block(self) -> None:
        """A check that passed by walking the sub-object is not this check.

        The named leaves below are the ones a consumer reads first and the
        ones the combat-only map never described.
        """
        response = _calculate()
        dispositions = response["dispositions"]
        assert len(dispositions) > 400
        for path in (
            "total_damage",
            "ability_damage",
            "auto_attack_damage",
            "effective_armor",
            "effective_mr",
            "champion_stats.ability_power",
            "breakdown.Q.total_damage",
        ):
            assert path in dispositions, path
        # ``champion_stats.attack_damage`` is deliberately not in that list:
        # the endpoint rounds it to an int on the wire and an int carries no
        # entry, by the same rule that keeps a build's ``gold`` bare.  The
        # rule is the map's, not this slice's, and changing either the wire
        # type or the rule is its own slice with its own baseline move.
        assert isinstance(response["champion_stats"]["attack_damage"], int)
        assert "champion_stats.attack_damage" not in dispositions
        assert all(path.split(".")[0] != "combat" for path in dispositions)

    def test_the_wire_shape_is_what_it_was_plus_the_map(self) -> None:
        """Re-writing every member through the writer moves no number.

        The walk rebuilds each nested container as it re-writes it, so the
        objects are new; the values, their positions and their JSON types are
        not allowed to be.  ``gold``-style ints stay ints, which is what
        keeps them out of the map.
        """
        from src.calculator.calculate import _name_the_response, calculate_payload

        payload = calculate_payload(dict(CALCULATE_REQUEST))
        before = json.dumps(
            {key: value for key, value in payload.items() if key != "dispositions"},
            sort_keys=False,
        )
        rewritten = {
            key: value for key, value in payload.items() if key != "dispositions"
        }
        _name_the_response(rewritten)
        rewritten.pop("dispositions")
        assert json.dumps(rewritten, sort_keys=False) == before


class TestTheCalculatePayload:
    """``/api/calculate``'s combat receipt — the five views' own output."""

    @pytest.mark.parametrize("scenario", COMBAT_SCENARIOS)
    def test_every_number_it_publishes_carries_exactly_one_entry(
        self, scenario: str
    ) -> None:
        """The whole payload, walked by the map's own path grammar.

        No block list and no skips.  An enumerated list of blocks is a
        second place the payload's shape is written down, and the first
        version of this test had one: it named six blocks, skipped three
        more, and every number outside them -- the duration, ninety-odd
        stats per participant, the utility receipt, both republications --
        was invisible to a check whose docstring said "every published
        number".  111 to 133 leaves per scenario, unnamed and unnoticed.
        """
        assert_covered(_combat(scenario))

    def test_the_map_is_not_vacuous(self) -> None:
        """A check that passes on an empty map is not a check."""
        assert len(_combat()["dispositions"]) > 100

    def test_a_republished_row_is_named_where_it_is_republished(self) -> None:
        """``objective.focus_survival`` is a second path, not a second number.

        A leaf path is where a reader finds a number, so the republication
        carries its own entries: a consumer reading
        ``objective.focus_survival.ending_health`` and finding no entry has
        been handed exactly the undispositioned number this campaign is
        about.  The entries agree with the original's, because the same
        ``serialize_leaf`` call shape produced both.
        """
        combat = _combat()
        dispositions = combat["dispositions"]
        focus = combat["objective"]["focus_participant_id"]
        index = next(
            index
            for index, row in enumerate(combat["participants"])
            if row["participant_id"] == focus
        )
        republished = {
            path[len("objective.focus_survival.") :]: entry
            for path, entry in dispositions.items()
            if path.startswith("objective.focus_survival.")
        }
        assert republished
        for leaf, entry in republished.items():
            assert dispositions[f"participants[{index}].survival.{leaf}"] == entry


class TestARetaggedFieldFailsTheRankingSurfaces:
    """Criterion 4's last clause, over a live receipt.

    "Retagging a field ``THEORETICAL`` makes the optimizer and BIS paths fail
    rather than silently score it" had no mechanism: neither ranking path
    read a view tag at any point, and a preview and a delivery are both
    ordinary ``MEASURED`` floats, so scoring one instead of the other had no
    symptom at all.
    """

    def _scored(self, combat: Mapping):
        """One live combat receipt, scored the way ``bis_payload`` scores it."""
        from src.calculator.bis import bis_objective_score

        objective = combat["objective"]
        focus_id = objective["focus_participant_id"]
        focus = next(
            row for row in combat["participants"] if row["participant_id"] == focus_id
        )
        return bis_objective_score(
            "overall",
            subject_team="main",
            focus_id=focus_id,
            combat=combat,
            objective=objective,
            focus=focus,
        )

    def test_an_applied_receipt_still_scores(self) -> None:
        """The positive control: the refusal is the tag, not the mechanism."""
        score, metric, components, _ = self._scored(_combat())
        assert isinstance(score, float)
        assert metric
        assert components

    def test_one_retagged_leaf_refuses_the_whole_ranking(self) -> None:
        """A preview in the map, and BIS declines to name a winner."""
        from src.calculator.program.views import UnrankableNumber

        combat = dict(_combat())
        leaf = "objective.focus_damage_before_death"
        combat["dispositions"] = {
            **combat["dispositions"],
            leaf: {**combat["dispositions"][leaf], "view_tag": "theoretical"},
        }
        with pytest.raises(UnrankableNumber) as raised:
            self._scored(combat)
        assert raised.value.paths == (leaf,)

    def test_the_refusal_is_not_swallowed_into_a_withheld_candidate(self) -> None:
        """``bis_payload`` catches ``(KeyError, ValueError)`` per candidate.

        An ``UnrankableNumber`` is a ``TypeError`` precisely so it passes
        through that handler: a previewed number is not a candidate that
        could not be evaluated, and a refusal filed as
        ``candidate_loadout_unavailable`` would be this rule failing in the
        shape it exists to stop.
        """
        from src.calculator.program.views import UnrankableNumber

        assert issubclass(UnrankableNumber, TypeError)
        assert not issubclass(UnrankableNumber, (KeyError, ValueError))


BIS_REQUEST = {
    "champion": "Syndra",
    "level": 13,
    "items": ["Malignance"],
    "enemies": [{"champion": "Aatrox", "level": 13, "items": []}],
    "slot_index": 1,
}

OPTIMIZE_REQUEST = {
    "champion": "Syndra",
    "level": 13,
    "items": [],
    "max_legendary_slots": 2,
    "fight_mode": "time_based",
    "fight_duration": 8,
    "target_health": 2000,
    "target_armor": 50,
    "target_mr": 40,
}


def _optimize() -> Mapping:
    """One live ``/api/optimize`` response, through the app it is served by."""
    from src.app import app

    app.config["RATE_LIMIT_ENABLED"] = False
    response = app.test_client().post("/api/optimize", json=dict(OPTIMIZE_REQUEST))
    assert response.status_code == 200
    return response.get_json()


class TestTheTwoScoreServingPayloads:
    """``/api/bis`` and ``/api/optimize`` — the score view's published surfaces.

    D-23 already covers their ``withheld[]`` and exclusion count.  What this
    class pins is the other half of umbrella criterion 1: the numbers they
    publish carry dispositions too, or the two largest numeric surfaces in the
    calculator serve undispositioned numbers while every other criterion
    passes.  It is the reverse direction that was missing -- the old version
    asserted two named leaves were *present* in the map and never asked what
    else the payload held, which is how 14 959 of BIS's 18 807 numbers stayed
    unnamed, the objective's own four score components among them.
    """

    def test_the_bis_payload_names_every_number_it_publishes(self) -> None:
        from src.calculator.bis import bis_payload

        assert_covered(bis_payload(dict(BIS_REQUEST)))

    def test_the_bis_map_is_not_vacuous_and_reaches_the_score_components(
        self,
    ) -> None:
        """A check that passes on an empty map is not a check."""
        from src.calculator.bis import bis_payload

        payload = bis_payload(dict(BIS_REQUEST))
        dispositions = payload["dispositions"]
        assert len(dispositions) > 1000
        for index, row in enumerate(payload["candidates"]):
            for leaf in ("score", "objective_value"):
                assert f"candidates[{index}].{leaf}" in dispositions
            for component in row["components"]:
                assert f"candidates[{index}].components.{component}" in dispositions

    def test_no_internal_ranking_key_reaches_a_published_row(self) -> None:
        """``_survival_dispositions`` was inserted first and popped later.

        A private key smuggled through the public row structure is one
        missed call away from being served, and the coverage receipt read
        those rows *before* the pop.  Nothing carries one now: the entries
        are produced at the path the leaf lives at.
        """
        from src.calculator.bis import bis_payload

        payload = bis_payload(dict(BIS_REQUEST))
        for block in ("candidates", "partial_candidates"):
            for row in payload[block]:
                assert not any(key.startswith("_") for key in row)

    def test_the_optimize_payload_names_every_number_it_publishes(self) -> None:
        """The endpoint had no test in this file at all until now.

        Its own module docstring named all three payloads; two were checked.
        The three numbers a consumer reads first -- the response's
        ``total_damage``, ``team_fight_value`` and ``optimization_time_ms``
        -- were exactly the ones outside the four keys the map named.
        """
        assert_covered(_optimize())

    def test_a_builds_price_stays_an_integer_on_the_wire(self) -> None:
        """``gold`` is a count, and re-writing it as a quantity changed it.

        Routing the key through ``measured`` made ``7300`` serialize as
        ``7300.0``: a wire-type change on a published field, caught by no
        test, mentioned in no commit body.  ``publish`` classifies by what
        the value is, so an int stays an int and carries no entry.
        """
        payload = _optimize()
        for row in payload["ranked_builds"]:
            assert isinstance(row["gold"], int)
            assert json.dumps(row["gold"]) == str(row["gold"])
        assert not any(path.endswith(".gold") for path in payload["dispositions"])


class TestAWithheldComponentMakesEveryTotalReadingItWithheld:
    """Criterion 19's end-to-end backstop, over a real roster receipt.

    The unit half of the criterion — ``Quantity.__add__`` over the full
    member x member matrix — lives in ``tests/test_ability_spec``.  This is
    the half that says the algebra is actually *on* the serving path: a
    roster whose payload carries one ``WITHHELD`` component, and a total that
    refuses rather than ranking the candidate on a number nobody computed.

    The withholding is injected rather than produced, and that is a fact
    about the tree and not a weakness of the fixture: no rule in ``src/``
    constructs a ``Withheld`` quantity today, so a fixture that waited for
    one would be a test of nothing.  What it exercises is the path a real
    withheld leaf will take — absent from the payload, present in the
    ``dispositions`` map with its receipts — which is exactly the shape
    ``serialize_leaf`` produces and the only shape a consumer can meet.

    The trap it closes is the incident's own: a withheld leaf is *absent*, so
    every ``payload.get(path, 0.0)`` on a serving surface reads a zero no
    rule computed, and a fold of five measured components and that zero is a
    ``MEASURED`` total that silently counted the refusal as nothing.
    """

    LEAF = "objective.focus_damage_before_death"
    RECEIPT = "coverage: this fixture withheld the focus damage"

    def _withheld_receipt(self) -> tuple[dict, str]:
        """A live roster receipt with one component withheld the ruled way."""
        combat = dict(_combat())
        objective = dict(combat["objective"])
        # A withheld leaf is absent from the payload while its entry stays.
        objective.pop("focus_damage_before_death", None)
        combat["objective"] = objective
        combat["dispositions"] = {
            **combat["dispositions"],
            self.LEAF: {
                "disposition": "WITHHELD",
                "view_tag": "applied",
                "receipts": [self.RECEIPT],
            },
        }
        return combat, objective["focus_participant_id"]

    def _score(self, combat: Mapping, focus_id: str):
        from src.calculator.bis import bis_objective_score

        focus = next(
            row for row in combat["participants"] if row["participant_id"] == focus_id
        )
        return bis_objective_score(
            "overall",
            subject_team="main",
            focus_id=focus_id,
            combat=combat,
            objective=combat["objective"],
            focus=focus,
        )

    def test_the_total_refuses_and_names_the_member_it_swallowed(self) -> None:
        from src.calculator.ability_spec import WithheldHasNoValue

        combat, focus_id = self._withheld_receipt()
        with pytest.raises(WithheldHasNoValue) as raised:
            self._score(combat, focus_id)
        assert self.RECEIPT in str(raised.value)

    def test_a_total_over_a_withheld_member_is_itself_withheld(self) -> None:
        """The disposition, not just the raise: the propagation row, live."""
        from src.calculator.ability_spec import Disposition, Measured
        from src.calculator.program.build import Tagged, fold_tagged
        from src.calculator.program.views import ViewTag, published_quantity

        combat, _ = self._withheld_receipt()
        withheld = published_quantity(
            combat["dispositions"], self.LEAF, 0.0, surface="the fixture"
        )
        total = fold_tagged(
            [
                Tagged(Measured(amount=1200.0), ViewTag.APPLIED),
                Tagged(withheld, ViewTag.APPLIED),
                Tagged(Measured(amount=340.0), ViewTag.APPLIED),
            ]
        )
        assert total.quantity.disposition is Disposition.WITHHELD
        assert total.quantity.receipts == (self.RECEIPT,)

    def test_the_absent_leaf_would_otherwise_have_folded_as_a_zero(self) -> None:
        """R-05: the red this gate reproduces on demand.

        The payload has no number at that path, so the serving surface's own
        ``.get(..., 0.0)`` yields ``0.0`` -- and folding *that* gives a
        perfectly well-formed ``MEASURED`` total that counted a refusal as
        nothing.  Asserting it here is what stops the check above from being
        satisfied by a payload that simply had no withheld member.
        """
        from src.calculator.ability_spec import Disposition, Measured
        from src.calculator.program.build import Tagged, fold_tagged
        from src.calculator.program.views import ViewTag

        combat, _ = self._withheld_receipt()
        assert "focus_damage_before_death" not in combat["objective"]
        assert float(combat["objective"].get("focus_damage_before_death", 0.0)) == 0.0
        naive = fold_tagged(
            [
                Tagged(Measured(amount=1200.0), ViewTag.APPLIED),
                Tagged(Measured(amount=0.0), ViewTag.APPLIED),
                Tagged(Measured(amount=340.0), ViewTag.APPLIED),
            ]
        )
        assert naive.quantity.disposition is Disposition.MEASURED
        assert naive.quantity.read() == 1540.0

    def test_the_unwithheld_roster_still_scores(self) -> None:
        """The positive control: the refusal is the withholding, not the path."""
        combat = _combat()
        score, metric, _components, _ = self._score(
            combat, combat["objective"]["focus_participant_id"]
        )
        assert isinstance(score, float)
        assert metric
