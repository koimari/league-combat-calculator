"""The precision registry: one home for every published digit count (D-71).

What is asserted here is not that ``round`` works.  It is that the registry
is the *only* place ``program/`` decides a precision, that an undeclared
field fails closed instead of picking a default, and that the death-time
cutoff is a named policy rather than a comparison somebody could quietly
improve.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.calculator.program import precision

PROGRAM_ROOT = Path(precision.__file__).resolve().parent


def test_every_declared_precision_is_a_digit_count() -> None:
    """A registry entry is a field name and a non-negative integer."""
    for field, digits in precision.ROUNDING.items():
        assert isinstance(field, str) and field.strip(), field
        assert isinstance(digits, int) and digits >= 0, field


def test_the_registry_is_not_writable_through_its_public_name() -> None:
    """One home means one writer: the mapping is a read-only view."""
    with pytest.raises(TypeError):
        precision.ROUNDING["death_time"] = 9  # type: ignore[index]


def test_a_field_with_no_declared_precision_raises_naming_itself() -> None:
    """Fail closed: an undeclared field never gets a default digit count."""
    with pytest.raises(precision.UnregisteredField) as excinfo:
        precision.digits_for("a_field_nobody_declared")
    assert "a_field_nobody_declared" in str(excinfo.value)
    assert "ROUNDING" in str(excinfo.value)


def test_round_field_rounds_at_the_declared_precision() -> None:
    """The three published precisions, each read off the registry."""
    assert precision.round_field("damage_taken", 1234.5678) == 1234.6
    assert precision.round_field("death_time", 4.567891) == 4.568
    assert precision.round_field("venom_factor", 0.8765432198) == 0.876543


def test_round_field_refuses_a_field_it_has_no_precision_for() -> None:
    """``round_field`` is ``digits_for`` plus a call; it fails the same way."""
    with pytest.raises(precision.UnregisteredField):
        precision.round_field("a_field_nobody_declared", 1.0)


def test_the_cutoff_policy_has_exactly_one_member_and_no_default() -> None:
    """One live policy, named.  A second member is what a change looks like."""
    assert [member.name for member in precision.CutoffPolicy] == ["ROUNDED_DEATH_TIME"]


def test_a_survivor_is_cut_off_at_the_fight_window() -> None:
    """No death time means the window itself is the cutoff."""
    assert (
        precision.damage_cutoff(None, 5.0, precision.CutoffPolicy.ROUNDED_DEATH_TIME)
        == 5.0
    )


def test_the_cutoff_is_the_published_death_time_sliver_and_all() -> None:
    """The quirk the policy names, asserted rather than described.

    The walk's raw death time is published rounded to the millisecond, and
    the cutoff reads the published number.  An event at 4.5679 s therefore
    still counts against an actor whose raw death was 4.56789 s, because the
    published time is 4.568.  Reaching for the raw number would be the more
    correct comparison and a silent change to a published total.
    """
    raw_death = 4.567891
    published = precision.round_field("death_time", raw_death)
    cutoff = precision.damage_cutoff(
        published, 10.0, precision.CutoffPolicy.ROUNDED_DEATH_TIME
    )
    assert cutoff == 4.568
    assert 4.5679 <= cutoff
    assert 4.5679 > raw_death


def test_an_unknown_cutoff_policy_raises() -> None:
    """Totality: the function answers for members, and refuses the rest."""
    with pytest.raises(ValueError):
        precision.damage_cutoff(1.0, 5.0, "rounded_death_time")  # type: ignore[arg-type]


def _round_call_sites(path: Path) -> list[int]:
    """Every ``round(...)`` call expression in one module."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "round"
    ]


def test_the_registry_is_the_only_module_in_program_that_rounds() -> None:
    """D-71's scope clause, as a test on the package rather than a rule.

    Migration frontier counter 6 gates the same property from the outside;
    this is the inside view, so a new ``program/`` module that rounds fails
    on the suite rather than only on the gate script.
    """
    offenders = {
        path.relative_to(PROGRAM_ROOT).as_posix(): _round_call_sites(path)
        for path in sorted(PROGRAM_ROOT.rglob("*.py"))
        if path.name != "precision.py" and _round_call_sites(path)
    }
    assert offenders == {}


# --- SumPlan: what a total sums, and in what order (D-65) --------------------


class TestTheSumPlanCountsEachEventOnce:
    """Criterion 14's ``SumPlan`` clause, which had no mechanism at all.

    The receipt publishes three event panels and a reader that wants every
    event of a fight unions them.  D-65's note is that three sources are
    unioned with only a comment preventing a double count -- and the
    measurement says the comment was not enough: a Redemption Intervention
    is published on ``events`` as damage and on ``support_events`` as the
    packet that dealt it, one id, one amount, twice.
    """

    def test_the_declared_panels_are_the_receipts_three(self) -> None:
        assert precision.SUM_PANELS == (
            "events",
            "healing_events",
            "support_events",
        )

    def test_members_arrive_in_panel_order_then_walk_order(self) -> None:
        """The ordering is declared, because float addition is not associative."""
        plan = precision.sum_plan(
            {
                "support_events": [{"event_id": "s0"}, {"event_id": "s1"}],
                "events": [{"event_id": "d0"}, {"event_id": "d1"}],
                "healing_events": [{"event_id": "h0"}],
            }
        )
        assert plan.ids == ("d0", "d1", "h0", "s0", "s1")

    def test_an_id_on_two_panels_is_summed_once_by_the_first(self) -> None:
        """The double count, made unrepresentable rather than tested for."""
        plan = precision.sum_plan(
            {
                "events": [{"event_id": "shared"}],
                "support_events": [{"event_id": "shared"}, {"event_id": "s1"}],
            }
        )
        assert plan.ids == ("shared", "s1")
        assert plan.shared == (("shared", ("events", "support_events")),)

    def test_a_fight_with_no_overlap_shares_nothing(self) -> None:
        plan = precision.sum_plan(
            {"events": [{"event_id": "d0"}], "healing_events": [{"event_id": "h0"}]}
        )
        assert plan.shared == ()
        assert plan.ids == ("d0", "h0")

    def test_one_panels_contribution_is_readable_on_its_own(self) -> None:
        plan = precision.sum_plan(
            {"events": [{"event_id": "d0"}], "healing_events": [{"event_id": "h0"}]}
        )
        assert plan.of("healing_events") == ("h0",)
        assert plan.of("support_events") == ()

    def test_one_panel_publishing_one_id_twice_is_not_a_plan(self) -> None:
        """R-05: the check ships with a red it can produce on demand.

        This is the half with no benign reading -- a panel repeating its own
        id makes that panel's own rows repeat -- so it raises where the
        cross-panel case is recorded.
        """
        with pytest.raises(precision.DuplicateSumMember, match="twice"):
            precision.sum_plan({"events": [{"event_id": "d0"}, {"event_id": "d0"}]})

    def test_the_refusal_is_on_the_type_not_on_the_builder(self) -> None:
        with pytest.raises(precision.DuplicateSumMember):
            precision.SumPlan(members=(("events", "x"), ("events", "x")))

    def test_a_row_with_no_id_contributes_no_member(self) -> None:
        """An unidentified row is not something a union over ids can repeat."""
        plan = precision.sum_plan({"events": [{"time": 0.0}, {"event_id": "d0"}]})
        assert plan.ids == ("d0",)

    def test_a_fourth_panel_fails_closed_rather_than_escaping_the_plan(self) -> None:
        with pytest.raises(KeyError, match="not a declared sum panel"):
            precision.sum_plan({"objective": [{"event_id": "o0"}]})


class TestTheReceiptBuildsItsPlan:
    """The plan has a live consumer, or it is a type nobody's payload obeys."""

    def test_the_receipt_view_builds_the_plan_over_its_three_panels(self) -> None:
        source = (PROGRAM_ROOT / "views" / "receipt.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "sum_plan"
        ]
        assert len(calls) == 1
        keys = {
            key.value
            for arg in calls[0].args
            if isinstance(arg, ast.Dict)
            for key in arg.keys
            if isinstance(key, ast.Constant)
        }
        assert keys == set(precision.SUM_PANELS)

    @staticmethod
    def _combat(items, allies):
        """One roster receipt, through the composition every payload uses."""
        from src.calculator.data_fetcher import get_champion, get_item_by_name
        from src.calculator.defensive_effects import resolve_starting_defenses
        from src.calculator.participant_timeline import build_participant_timeline
        from src.calculator.pipeline import FightParams
        from src.calculator.scenario import ChampionLoadout
        from src.calculator.stats import calculate_total_stats

        champion = get_champion("Ahri")
        item_data = [get_item_by_name(name) for name in items]
        stats = calculate_total_stats(champion, 18, item_data, role="mid")
        return build_participant_timeline(
            champion,
            18,
            item_data,
            FightParams.from_request(
                {"fight_mode": "time_based", "fight_duration": 8, "role": "mid"},
                deterministic=True,
            ),
            main_stats=stats,
            main_defenses=resolve_starting_defenses("Ahri", 18, stats, item_data),
            enemies=[
                ChampionLoadout(champion="Aatrox", level=18, role="top").resolve()
            ],
            allies=list(allies),
        )

    def test_an_ordinary_roster_receipt_publishes_each_event_once(self) -> None:
        """Measured, not assumed: the property holds on a real payload."""
        from src.calculator.scenario import ChampionLoadout

        combat = self._combat(
            ["Imperial Mandate"],
            [ChampionLoadout(champion="Pantheon", level=18, role="support").resolve()],
        )
        plan = precision.sum_plan(
            {panel: combat.get(panel, []) for panel in precision.SUM_PANELS}
        )
        assert plan.ids, "a fixture with no identified rows would pass vacuously"
        assert len(plan.ids) == len(set(plan.ids))
        assert plan.shared == ()

    def test_a_support_packet_that_dealt_damage_is_on_two_panels_once(self) -> None:
        """The live overlap the plan was built to survive, named by fixture.

        Redemption's Intervention is one delivery published twice -- as the
        damage it dealt and as the support packet that dealt it, same id and
        same amount.  The plan carries it once, attributed to ``events``,
        and names it in ``shared`` so the repeat is visible rather than
        merely absent.
        """
        from src.calculator.scenario import ChampionLoadout

        combat = self._combat(
            [],
            [
                ChampionLoadout(
                    champion="Lulu",
                    level=18,
                    role="support",
                    items=("Redemption",),
                    item_options={"Redemption": {"active_seconds": 1.0}},
                    ally_effects_enabled=True,
                ).resolve()
            ],
        )
        panels = {panel: combat.get(panel, []) for panel in precision.SUM_PANELS}
        plan = precision.sum_plan(panels)
        assert plan.shared, "the fixture exists for the overlap; there is none"
        for event_id, on_panels in plan.shared:
            assert on_panels == ("events", "support_events"), event_id
            assert plan.ids.count(event_id) == 1
        assert len(plan.ids) == len(set(plan.ids))
