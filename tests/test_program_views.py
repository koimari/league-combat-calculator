"""The views: one projection per consumer shape, and none of them rounds.

This file is the front door for every module under ``program/views/`` and it
**binds each one as a symbol** — ``from src.calculator.program.views import
survival`` — because a package import backs the package and nothing inside
it.  As the remaining four views land they are added to that import, which is
what keeps the derived front-door registry honest about all five rather than
about one mention of a directory.

At S3 there is one view: the end-of-walk survival projection, moved out of
the kernel with its 38 digit counts.  S7 adds ``ViewTag`` to the package
initialiser, so its two rules are pinned here too.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.calculator.program import precision
from src.calculator.program.views import ViewTag, survival

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


def test_the_tag_vocabulary_module_imports_nothing_from_the_package() -> None:
    """It is a leaf, and ``trigger_stream``'s second import depends on it.

    The bus may name ``ViewTag`` only because this module reaches no further;
    an import added here would silently give the bus a transitive dependency
    the acyclicity clause forbids.
    """
    source = (VIEWS_ROOT / "__init__.py").read_text(encoding="utf-8")
    relative = {
        node.module
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom) and node.level
    }
    assert relative == set()
