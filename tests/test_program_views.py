"""The views: one projection per consumer shape, and none of them rounds.

This file is the front door for every module under ``program/views/`` and it
**binds each one as a symbol** — ``from src.calculator.program.views import
survival`` — because a package import backs the package and nothing inside
it.  As the remaining views land they are added to that import, which is
what keeps the derived front-door registry honest about all five rather than
about one mention of a directory.

At S3 there is one view: the end-of-walk survival projection, moved out of
the kernel with its 38 digit counts.  S7 adds ``ViewTag`` to the package
initialiser, so its two rules are pinned here too, and S9 adds
``serialize_leaf`` -- the one producer of a payload leaf and of that leaf's
``dispositions`` entry.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.calculator import ability_spec
from src.calculator.ability_spec import Measured, Starved, StructuralZero, Withheld
from src.calculator.program import precision
from src.calculator.program.build import roster_program
from src.calculator.program.walk import AttackerOutcome, WalkResult, survival_folds
from src.calculator.program.rung import CompiledFast
from src.calculator.program.views import (
    DISCARD,
    LeafWriter,
    ViewTag,
    breakdown,
    receipt,
    score,
    serialize_leaf,
    survival,
    tdd,
)
from src.calculator.trigger_stream import ProjectionStarvation

VIEWS_ROOT = Path(survival.__file__).resolve().parent


class _Pools(SimpleNamespace):
    """The shield-pool record the projection reads, with published defaults."""


def _state(**overrides: object) -> dict[str, object]:
    """One participant's final walk state, at rest unless a test moves it."""
    pools = _Pools(
        max_health=1000.0,
        health=250.0,
        damage_taken=750.0,
        overkill=0.0,
        health_damage=750.0,
        shield_absorbed=0.0,
        shield_expired=0.0,
        magic_shield=0.0,
        physical_shield=0.0,
        general_shield=0.0,
        venom_factor=1.0,
        threshold_shield=None,
        threshold_health=None,
    )
    state: dict[str, object] = {
        "pools": pools,
        "starting_shield": 0.0,
        "healing_received": 0.0,
        "overhealing": 0.0,
        "healing_reduced": 0.0,
        "support_shield_received": 0.0,
        "temporary_health_received": 0.0,
        "temporary_health_until": 0.0,
        "temporary_health_expired_at": None,
        "temporary_health_source": "",
        "healing_reduction_until": 0.0,
        "healing_reduction_sources": set(),
        "healing_reduction_events": [],
        "venom_until": 0.0,
        "venom_events": [],
        "death_time": None,
        "first_death_time": None,
        "revived": False,
        "revive_time": None,
        "revive_health_restored": 0.0,
        "revive_source": "",
        "terminal_phase": "alive",
        "execute_time": None,
        "execute_source": "",
        "stasis_until": 0.0,
        "stasis_started_at": None,
        "stasis_source": "",
        "invulnerable_until": 0.0,
        "untargetable_until": 0.0,
        "spell_shield_used": False,
        "spell_shield_source": "",
        "spell_shield_until": 0.0,
        "force_stacks": 0,
        "force_stacks_until": 0.0,
        "force_stack_events": [],
        "jaksho_stacks": 0,
        "jaksho_stack_events": [],
        "damage_deferral_pending": 0.0,
        "damage_deferral_cleared": 0.0,
        "defy_triggered": False,
        "defy_trigger_time": None,
        "defy_heal_received": 0.0,
    }
    state.update(overrides)
    return state


def _combatant(**defenses: object) -> SimpleNamespace:
    """One participant, carrying only what the projection reads off it."""
    return SimpleNamespace(
        participant_id="target",
        defenses=SimpleNamespace(damage_deferral_fraction=0.0, **defenses),
    )


def _result(states: list[dict[str, object]], **fields: object) -> WalkResult:
    """A finished walk carrying only the states the projection reads.

    The survival fold comes from ``survival_folds`` rather than from a
    literal, because a fixture that spelled those three numbers itself would
    be the second producer criterion 3 exists to forbid, wearing a test's
    clothes.
    """
    return WalkResult(
        actions=(),
        states=tuple(states),
        coverage=(),
        rung=CompiledFast(),
        survival=survival_folds(states),
        **fields,
    )


def _row(**overrides: object) -> dict[str, object]:
    """The published row for one at-rest participant."""
    states = [_state(**overrides)]
    return survival.survival(roster_program([_combatant()]), _result(states))["target"]


def test_the_projection_publishes_one_row_per_participant() -> None:
    """Keyed by participant id, in roster order."""
    combatants = [
        _combatant(),
        SimpleNamespace(participant_id="ally", defenses=_combatant().defenses),
    ]
    rows = survival.survival(roster_program(combatants), _result([_state(), _state()]))
    assert list(rows) == ["target", "ally"]


def test_every_published_number_carries_its_declared_precision() -> None:
    """The whole point of the move: the digit count comes from the registry.

    Each published leaf is re-rounded at its registered precision and must be
    unchanged — which is only true if the projection used that precision in
    the first place.
    """
    states = [
        _state(healing_received=123.456789, venom_until=1.23456789, death_time=4.567891)
    ]
    row = survival.survival(
        roster_program([_combatant()]),
        _result(
            states,
            grey_health={
                "source": "Mordekaiser",
                "grey_health_stored": 12.3456789,
                "grey_health_consumed": 3.21987654,
            },
        ),
    )["target"]
    for field, digits in precision.ROUNDING_BY_VIEW["survival"].items():
        if "." in field:
            block, leaf = field.split(".")
            value = row[block][leaf]
        else:
            value = row[field]
        if value is None:
            continue
        assert value == round(value, digits), field


def test_a_survivor_publishes_no_death_time_rather_than_a_zero() -> None:
    """``None`` is not a timestamp and is never rounded into one."""
    row = _row()
    assert row["death_time"] is None
    assert row["survived_window"] is True


def test_a_death_time_is_published_at_millisecond_precision() -> None:
    """The number the post-death cutoff then reads (``CutoffPolicy``)."""
    row = _row(death_time=4.567891)
    assert row["death_time"] == 4.568
    assert row["survived_window"] is False


def test_an_unused_spell_shield_publishes_none_rather_than_infinity() -> None:
    """A ready shield's ``inf`` sentinel is not a serializable timestamp."""
    assert _row(spell_shield_until=float("inf"))["spell_shield_until"] is None
    assert _row(spell_shield_until=2.5)["spell_shield_until"] == 2.5


def test_the_two_stack_blocks_publish_their_own_resistances() -> None:
    """``dynamic_bonus_magic_resistance`` is published twice, under two keys.

    That collision is why the precision registry keys on ``block.name``: a
    bare-leaf registry would have had to guess which block a caller meant.
    """
    row = _row(dynamic_bonus_magic_resistance=12.3456789, dynamic_bonus_armor=7.65432)
    assert row["force_of_nature"]["dynamic_bonus_magic_resistance"] == 12.346
    assert row["jaksho"]["dynamic_bonus_magic_resistance"] == 12.346
    assert row["jaksho"]["dynamic_bonus_armor"] == 7.654


def test_the_row_key_order_is_the_published_order() -> None:
    """Serialization order is part of the published shape, so it is pinned."""
    keys = list(_row())
    assert keys[:4] == [
        "max_health",
        "ending_health",
        "ending_health_ratio",
        "damage_taken",
    ]
    assert keys[
        keys.index("spell_shield_until") + 1 : keys.index("spell_shield_until") + 3
    ] == [
        "force_of_nature",
        "jaksho",
    ]
    assert keys[-1] == "defy_heal_received"


def test_no_view_module_rounds_outside_the_registry() -> None:
    """D-71's scope clause, on the package the projection now lives in."""
    offenders = []
    for path in sorted(VIEWS_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        offenders.extend(
            f"{path.name}:{node.lineno}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "round"
        )
    assert offenders == []


def test_a_field_the_registry_does_not_know_cannot_be_published() -> None:
    """Fail closed: the projection cannot invent a precision for a new leaf."""
    with pytest.raises(precision.UnregisteredField):
        precision.round_field("a_leaf_somebody_added", 1.0)


# ---------------------------------------------------------------------------
# ViewTag — S7's vocabulary, and the two rules it exists to make checkable
# ---------------------------------------------------------------------------


def test_the_view_tag_vocabulary_is_closed_at_two_members() -> None:
    """ "Requested" is deliberately not a third member.

    The ladder is requested -> priced -> applied, and a request carries no
    number.  Tagging a non-number would re-open exactly the zero-versus-absent
    confusion the campaign exists to close, so the enum stops at the two
    states a *number* can be in.
    """
    assert [tag.name for tag in ViewTag] == ["THEORETICAL", "APPLIED"]


def test_the_tag_vocabulary_module_reaches_only_the_vocabulary_leaf() -> None:
    """It is a leaf, and ``trigger_stream``'s second import depends on it.

    The bus may name ``ViewTag`` only because this module reaches no further;
    an import added here would silently give the bus a transitive dependency
    the acyclicity clause forbids.  ``ability_spec`` is the single permitted
    reach, and permitting it costs the argument nothing: it is the campaign's
    dependency-free vocabulary leaf, ``trigger_stream`` already imports it for
    ``Authority``, and S9's ``serialize_leaf`` is defined over ``Quantity``,
    which lives there.  The check below is therefore two clauses rather than
    one -- what this module may import, and that the one thing it imports
    imports nothing back.
    """
    source = (VIEWS_ROOT / "__init__.py").read_text(encoding="utf-8")
    relative = {
        node.module
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom) and node.level
    }
    assert relative == {"ability_spec"}
    vocabulary = Path(ability_spec.__file__).read_text(encoding="utf-8")
    assert {
        node.module
        for node in ast.walk(ast.parse(vocabulary))
        if isinstance(node, ast.ImportFrom) and node.level and node.col_offset == 0
    } == set()


# ---------------------------------------------------------------------------
# serialize_leaf — S9's one producer of a leaf and of its dispositions entry
# ---------------------------------------------------------------------------


def test_a_measured_leaf_is_a_bare_number_beside_an_entry_that_names_it() -> None:
    """The common case, and the one the wire shape is designed around.

    A bare JSON number cannot carry a field, so the disposition rides in a
    sibling map -- which is what keeps every measured leaf byte-identical to
    what clients already parse.
    """
    out = serialize_leaf(
        "breakdown.main.total_damage", Measured(1234.5), ViewTag.APPLIED
    )
    assert out.present is True
    assert out.value == 1234.5
    assert out.entry == {"disposition": "MEASURED", "view_tag": "applied"}


def test_a_structural_zero_publishes_the_zero_and_the_declaration() -> None:
    """Zero is the answer, and the declaration is the receipt -- so both ship."""
    out = serialize_leaf(
        "breakdown.ally.support_value",
        StructuralZero(reason="no support declaration on this roster"),
        ViewTag.APPLIED,
    )
    assert out.present is True
    assert out.value == 0.0
    assert out.entry["disposition"] == "STRUCTURAL_ZERO"
    assert out.entry["reason"] == "no support declaration on this roster"


def test_a_withheld_leaf_has_no_number_and_its_entry_carries_the_receipts() -> None:
    """The asymmetry the whole map exists for.

    Absent-with-a-receipt is a different published answer from zero, and it is
    the one this campaign was opened over.
    """
    out = serialize_leaf(
        "breakdown.main.total_damage",
        Withheld(receipts=("coverage: Nashor's Tooth on-hit is unmodelled",)),
        ViewTag.APPLIED,
    )
    assert out.present is False
    assert out.value is None
    assert out.entry["disposition"] == "WITHHELD"
    assert out.entry["receipts"] == ["coverage: Nashor's Tooth on-hit is unmodelled"]


def test_a_starved_leaf_raises_rather_than_serializing_anything() -> None:
    """D-25: the failure surfaces where the projection was asked the question."""
    with pytest.raises(ProjectionStarvation):
        serialize_leaf(
            "survival.main.ending_health",
            Starved(field="pools", producer="score ledger", reason="score projection"),
            ViewTag.APPLIED,
        )


def test_a_theoretical_number_says_so_in_its_own_entry() -> None:
    """One tag per serialized number, and never as a field on the number."""
    out = serialize_leaf("tdd.main.theoretical", Measured(10.0), ViewTag.THEORETICAL)
    assert out.entry["view_tag"] == "theoretical"


def test_the_writer_puts_the_leaf_and_records_its_entry_in_one_call() -> None:
    """One writer: the map and the leaves cannot drift because nothing keeps them."""
    writer = LeafWriter()
    row: dict[str, object] = {}
    block = writer.block(row, "breakdown.main")
    block.measured("total_damage", 12.0)
    block.put("support_value", Withheld(receipts=("coverage: unmodelled",)))
    assert row == {"total_damage": 12.0}
    assert set(writer.entries()) == {
        "breakdown.main.total_damage",
        "breakdown.main.support_value",
    }
    assert writer.withheld_paths() == {"breakdown.main.support_value"}


def test_a_leaf_path_is_its_payload_key_and_cannot_be_spelled_apart() -> None:
    """The block binds prefix to target, so a rename moves both or neither."""
    writer = LeafWriter()
    row: dict[str, object] = {}
    writer.block(row, "survival.main").measured("ending_health", 250.0)
    assert list(row) == ["ending_health"]
    assert writer.paths() == {"survival.main.ending_health"}


def test_the_writer_preserves_the_order_the_view_spells() -> None:
    """Key order is part of the published shape, so the writer never reorders."""
    writer = LeafWriter()
    row: dict[str, object] = {}
    block = writer.block(row, "leaf")
    for index, name in enumerate(("alpha", "beta", "gamma")):
        block.measured(name, float(index))
    assert list(row) == ["alpha", "beta", "gamma"]


# ---------------------------------------------------------------------------
# breakdown and score — the two views S9's assembly deletion moved into
# ---------------------------------------------------------------------------


def _actor(participant_id: str = "main", team: str = "main", champion: str = "Syndra"):
    """One roster member, carrying only what the two views read off it."""
    return SimpleNamespace(
        participant_id=participant_id,
        team=team,
        level=13,
        champion_data={"name": champion},
        defenses=SimpleNamespace(damage_deferral_fraction=0.0),
    )


def _outcome(**overrides: object) -> AttackerOutcome:
    """One attacker's folded numbers, at rest unless a test moves them."""
    fields: dict[str, object] = {
        "participant_id": "main",
        "team": "main",
        "champion": "Syndra",
        "total_damage": 1234.56,
        "incoming_damage": 750.0,
        "health_damage": 750.0,
        "shield_absorbed": 0.0,
        "effective_health": 1000.0,
        "healing_received": 0.0,
        "healing_reduced": 0.0,
        "support_shield_received": 0.0,
        "support_value": 12.34,
        "healing_output": 0.0,
        "survived_window": True,
        "death_time": None,
    }
    fields.update(overrides)
    return AttackerOutcome(**fields)  # type: ignore[arg-type]


def test_the_breakdown_row_key_order_is_the_published_order() -> None:
    """The order two composition tails produced by hand, now produced once."""
    rows = breakdown.breakdown(
        roster_program([_actor()]), _result([_state()], outcomes=(_outcome(),))
    )
    assert list(rows[0]) == [
        "participant_id",
        "team",
        "champion",
        "total_damage",
        "sources",
        "outgoing_damage_before_death",
        "incoming_damage",
        "health_damage",
        "shield_absorbed",
        "effective_health",
        "healing_received",
        "healing_reduced",
        "support_shield_received",
        "support_value",
        "healing_output",
        "survived_window",
        "death_time",
    ]


def test_the_breakdown_rounds_only_at_declared_precisions() -> None:
    """Every published number is its leaf re-rounded, never re-derived."""
    rows = breakdown.breakdown(
        roster_program([_actor()]), _result([_state()], outcomes=(_outcome(),))
    )
    assert rows[0]["total_damage"] == 1234.6
    assert rows[0]["outgoing_damage_before_death"] == 1234.6
    assert rows[0]["incoming_damage"] == 750.0
    assert rows[0]["support_value"] == 12.3


def test_a_utility_receipt_is_absent_rather_than_empty_when_there_is_none() -> None:
    """The optimizer's score subset displays no timeline, so it carries none.

    Absence is the statement: an empty dict would be a receipt claiming the
    participant had no utility outcomes, which is a different answer from
    "this payload does not publish utility outcomes at all".
    """
    program = roster_program([_actor()])
    without = breakdown.breakdown(program, _result([_state()], outcomes=(_outcome(),)))
    with_receipt = breakdown.breakdown(
        program,
        _result([_state()], outcomes=(_outcome(utility_outcomes={"movement": 1.0}),)),
    )
    assert "utility_outcomes" not in without[0]
    assert with_receipt[0]["utility_outcomes"] == {"movement": 1.0}


def test_the_breakdown_publishes_the_identity_the_composition_folded() -> None:
    """A preserved defect, pinned so a later slice has to mean to change it.

    The receipt path fills a row's identity inside its attacker loop, so a
    participant who dealt no damage is published with an empty champion.  A
    pure stage relocates that decision; it does not correct it.
    """
    rows = breakdown.breakdown(
        roster_program([_actor()]),
        _result([_state()], outcomes=(_outcome(champion="", team=""),)),
    )
    assert rows[0]["champion"] == ""
    assert rows[0]["team"] == ""


def test_a_fold_that_lost_a_participant_raises_rather_than_publishing_short() -> None:
    """A breakdown row with no participant behind it is a number about nobody."""
    with pytest.raises(ValueError):
        breakdown.breakdown(
            roster_program([_actor(), _actor("ally", "ally", "Lulu")]),
            _result([_state(), _state()], outcomes=(_outcome(),)),
        )


def test_the_score_payload_is_the_keys_a_candidate_is_scored_from() -> None:
    """One projection, so score mode and receipt mode cannot disagree."""
    payload = score.score(
        roster_program([_actor()]),
        _result(
            [_state()],
            duration=12.0,
            outcomes=(_outcome(),),
            timeline_coverage={"complete": True},
        ),
    )
    assert list(payload) == [
        "duration",
        "participants",
        "breakdown",
        "timeline_coverage",
        "dispositions",
    ]
    assert payload["duration"] == 12.0
    assert payload["timeline_coverage"] == {"complete": True}
    assert list(payload["participants"][0]) == [
        "participant_id",
        "team",
        "champion",
        "level",
        "survival",
    ]


def test_the_score_view_publishes_the_roster_identity_not_the_folded_one() -> None:
    """The participants block always read the roster; only breakdown did not.

    Two identity sources in one payload is exactly the kind of divergence
    this phase exists to make visible, so it is pinned rather than tidied:
    tidying it moves published output.
    """
    payload = score.score(
        roster_program([_actor()]),
        _result([_state()], outcomes=(_outcome(champion=""),)),
    )
    assert payload["participants"][0]["champion"] == "Syndra"
    assert payload["breakdown"][0]["champion"] == ""


def test_the_score_payload_names_every_number_in_it() -> None:
    """A candidate's payload is a published payload the moment one is kept.

    It carried no map at all on the grounds that nobody reads a candidate --
    and three score-mode coupled scenarios snapshot 133 of its numbers each.
    """
    payload = score.score(
        roster_program([_actor()]),
        _result(
            [_state()],
            duration=12.0,
            outcomes=(_outcome(),),
            timeline_coverage={"complete": True},
        ),
    )
    entries = payload["dispositions"]
    assert entries["duration"]["disposition"] == "MEASURED"
    assert "participants[0].survival.max_health" in entries
    assert "breakdown[0].total_damage" in entries


# ---------------------------------------------------------------------------
# The UI's one budgeted change — a withheld leaf renders as a named refusal
# ---------------------------------------------------------------------------

APP_JS = Path(__file__).resolve().parent.parent / "static" / "js" / "app.js"


def test_the_ui_has_one_shared_withheld_marker_and_one_leaf_reader() -> None:
    """S9's one budgeted UI change, pinned as one.

    Two helpers and no third: a second place that decided how a refusal looks
    is a second place that could decide it looks like a blank.
    """
    source = APP_JS.read_text(encoding="utf-8")
    assert source.count("const withheldMarker = ") == 1
    assert source.count("const leafText = ") == 1


def test_a_withheld_leaf_never_renders_as_a_blank_a_zero_or_a_nan() -> None:
    """The failure this campaign is named after, at the last inch of it."""
    source = APP_JS.read_text(encoding="utf-8")
    start = source.index("const withheldMarker = ")
    body = source[start : source.index("function invalidateOptimization", start)]
    assert 'disposition === "WITHHELD"' in body
    assert "withheld" in body
    # The reader falls through to the marker when the payload carries no
    # number, which is exactly the absent-with-a-receipt case.
    assert "if (value == null) return withheldMarker(entry);" in body


def test_a_measured_leaf_still_renders_as_the_bare_number() -> None:
    """Unchanged rendering of measured leaves, pinned by test (criterion 5).

    The formatter is the payload's own bare number put through the same
    ``fmt`` every stat card already used; the disposition map changes what a
    *refusal* looks like and nothing about what a number looks like.
    """
    source = APP_JS.read_text(encoding="utf-8")
    start = source.index("const leafText = ")
    body = source[start : source.index("function invalidateOptimization", start)]
    assert "format = fmt" in body
    assert "return escapeHtml(format(value));" in body


def _js_call_sites(source: str, name: str) -> int:
    """How many times *name* is invoked.

    An arrow-function definition spells ``const name = (``, with the space
    and the ``=`` between, so it does not match ``name(`` and needs no
    subtracting -- and a subtraction that assumed it did is how this check
    read one live call site as zero while it was being written.
    """
    return len(re.findall(rf"(?<![\w.]){re.escape(name)}\(", source))


def test_the_refusal_helpers_are_reached_by_something_that_renders() -> None:
    """A helper with no callers is a definition, not a rendering change.

    ``withheldMarker`` and ``leafText`` shipped with zero call sites and no
    ``.leaf-withheld`` rule: the payload could carry a refused leaf and the
    page would still print the ``?? 0`` that stands in for it, which is the
    exact failure the campaign is named after surviving the commit that
    claimed to close it.
    """
    source = APP_JS.read_text(encoding="utf-8")
    assert _js_call_sites(source, "leafText") >= 1
    assert _js_call_sites(source, "withheldMarker") >= 1
    assert _js_call_sites(source, "leafWithheld") >= 1
    assert _js_call_sites(source, "survivalLeafPath") >= 1


def test_a_refused_survival_leaf_is_not_read_as_a_zero() -> None:
    """The two readers the verifier named, and the total over them.

    ``Number(row.survival?.ending_health ?? 0)`` turns an absent leaf into a
    measured zero.  Both the per-participant row and the enemy health total
    ask the map first now, and a total with a refused member is refused
    rather than quietly short by that member's amount.
    """
    source = APP_JS.read_text(encoding="utf-8")
    start = source.index("function enemyHealthRemaining(")
    body = source[start : source.index("function enemyOverkill(", start)]
    assert "withheldEntry(" in body
    assert "health withheld" in body
    start = source.index('$("healthRows").innerHTML')
    row = source[start : source.index("renderFightChart(", start)]
    assert "leafWithheld(healthPath, healthDispositions)" in row
    assert "leafText(null, healthPath, healthDispositions)" in row


def test_the_page_has_a_rule_for_what_a_refusal_looks_like() -> None:
    """A marker with no style is a word that reads as a value."""
    css = (
        Path(__file__).resolve().parent.parent / "static" / "css" / "style.css"
    ).read_text(encoding="utf-8")
    assert ".leaf-withheld {" in css


def test_a_discarded_row_is_identical_to_a_recorded_one() -> None:
    """The fast branch is the same expression, not a second producer.

    ``serialize_leaf`` returns ``quantity.read()`` and ``Measured.read()`` is
    ``float(self.amount)``, so the discarding branch's ``float(value)`` is
    that expression with the two allocations only the recording path needs
    taken out.  Pinned here because "provably the same" is worth one test,
    and because the optimizer's rows and the receipt's rows differing would
    be the score-versus-receipt divergence this phase exists to close.
    """
    program = roster_program([_combatant()])
    result = _result([_state(healing_received=123.456789, death_time=4.567891)])
    paths = survival.participant_paths(program)
    recorded = survival.survival_leaves(program, result, LeafWriter(), paths)
    discarded = survival.survival_leaves(program, result, DISCARD, paths)
    assert recorded == discarded
