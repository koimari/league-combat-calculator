"""The views: one projection per consumer shape, and none of them rounds.

This file is the front door for every module under ``program/views/`` and it
**binds each one as a symbol** — ``from src.calculator.program.views import
survival`` — because a package import backs the package and nothing inside
it.  As the remaining four views land they are added to that import, which is
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
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.calculator import ability_spec
from src.calculator.ability_spec import Measured, Starved, StructuralZero, Withheld
from src.calculator.program import precision
from src.calculator.program.views import (
    LeafWriter,
    ViewTag,
    serialize_leaf,
    survival,
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


def _row(**overrides: object) -> dict[str, object]:
    """The published row for one at-rest participant."""
    return survival.survival_rows([_state(**overrides)], [_combatant()])["target"]


def test_the_projection_publishes_one_row_per_participant() -> None:
    """Keyed by participant id, in roster order."""
    rows = survival.survival_rows(
        [_state(), _state()],
        [
            _combatant(),
            SimpleNamespace(participant_id="ally", defenses=_combatant().defenses),
        ],
    )
    assert list(rows) == ["target", "ally"]


def test_every_published_number_carries_its_declared_precision() -> None:
    """The whole point of the move: the digit count comes from the registry.

    Each published leaf is re-rounded at its registered precision and must be
    unchanged — which is only true if the projection used that precision in
    the first place.
    """
    row = _row(
        healing_received=123.456789,
        venom_until=1.23456789,
        death_time=4.567891,
    )
    for field, digits in precision.ROUNDING.items():
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
