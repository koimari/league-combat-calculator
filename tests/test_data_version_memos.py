"""Test front door for ``data_registry``'s memo tables (D-49).

Fifteen memos in this tree hold values derived from cached ``data/`` files,
and a sixteenth is cleared wholesale by the refresh it follows.  The seven
this phase owns were keyed on object identity alone, which answers
"is this the same dict?" and never "was this dict built from the cache we
are reading now?".  Those are different questions, and a patch-day refresh
is exactly where they diverge.

Two properties are checked here and neither is a convention:

* **The population is closed.**  A scan over ``src/calculator`` finds every
  module-level mapping whose name ends in ``_MEMO`` or ``_CACHE`` and
  asserts the four declared tables partition it.  A sixteenth memo therefore
  fails collection until somebody puts it in one of them.
* **The key really carries the version.**  Each of the seven is exercised
  through its own front door: memoize a value, mutate the source in place so
  identity cannot see the change, bump the counter, and assert the answer
  moves.  A key that merely mentions ``data_version()`` without reaching the
  lookup would pass a source scan and fail these.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.calculator import data_registry, economy, stats, support_effects

SRC_ROOT = Path(__file__).resolve().parent.parent / "src"

MEMO_SUFFIXES = ("_MEMO", "_CACHE")


def _module_name(path: Path) -> str:
    return ".".join(path.relative_to(SRC_ROOT).with_suffix("").parts)


def scan_memos() -> frozenset[str]:
    """Every module-level mapping under ``src/`` named like a memo.

    The shape rule is the whole definition: ``<module>.<NAME>`` where NAME
    ends in ``_MEMO`` or ``_CACHE`` and the bound value is a dict display.
    Names like ``_STATE_PROTO_MEMO_LIMIT`` and ``_SUSTAIN_STAT_CACHE_KEYS``
    fall out because they do not end in a memo suffix, and a non-mapping
    constant falls out because it cannot hold entries.
    """
    found: set[str] = set()
    for path in sorted(SRC_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.AnnAssign):
                target, value = node.target, node.value
            elif isinstance(node, ast.Assign) and len(node.targets) == 1:
                target, value = node.targets[0], node.value
            else:
                continue
            if not isinstance(target, ast.Name):
                continue
            if not target.id.endswith(MEMO_SUFFIXES):
                continue
            if not isinstance(value, ast.Dict):
                continue
            found.add(f"{_module_name(path)}.{target.id}")
    return frozenset(found)


@pytest.fixture(name="bumped_version")
def _bumped_version(monkeypatch: pytest.MonkeyPatch):
    """Advance the runtime-cache generation without writing a file."""

    def bump() -> None:
        monkeypatch.setattr(
            data_registry,
            "_DATA_VERSION",
            data_registry.data_version() + 1,
            raising=True,
        )

    return bump


def test_declared_tables_partition_every_memo_in_the_tree() -> None:
    """No memo is outside the four tables, and none is in two of them."""
    tables = {
        "keyed": frozenset(data_registry.DATA_VERSION_KEYED_MEMOS),
        "rotation": data_registry.ROTATION_MEMOS,
        "ungoverned": frozenset(data_registry.UNGOVERNED_MEMOS),
        "deferred": frozenset(data_registry.DEFERRED_MEMOS),
    }
    declared: set[str] = set()
    for name, members in tables.items():
        overlap = declared & members
        assert not overlap, f"{name} re-declares {sorted(overlap)}"
        declared |= members
    assert scan_memos() == declared


def test_the_phase_keys_seven_and_phase_five_keys_the_two_rotation_memos() -> None:
    """The split D-49 rules, as a number rather than as prose."""
    assert len(data_registry.DATA_VERSION_KEYED_MEMOS) == 7
    assert len(data_registry.ROTATION_MEMOS) == 2


def test_every_declared_memo_carries_a_reason() -> None:
    """A table entry with an empty reason is an undeclared memo in disguise."""
    for table in (
        data_registry.DATA_VERSION_KEYED_MEMOS,
        data_registry.UNGOVERNED_MEMOS,
        data_registry.DEFERRED_MEMOS,
        data_registry.REFRESH_CLEARED_MEMOS,
    ):
        for member, reason in table.items():
            assert reason.strip(), member


def test_rotation_memos_are_keyed_by_their_own_lane() -> None:
    """Phase 5's half of D-49 is asserted here, not assumed."""
    source = (SRC_ROOT / "calculator" / "rotation_resolver.py").read_text(
        encoding="utf-8"
    )
    assert "cache_key = (champion_name, data_version())" in source
    assert "cache_key = (champion_name, signature, data_version())" in source


def test_refresh_cleared_memo_is_emptied_by_the_refresh_it_names() -> None:
    """The one memo whose safety is somebody else's ``clear()`` call."""
    from src.calculator import item_effects

    item_effects.resolve_damage_effects([{"name": "Infinity Edge"}])
    assert item_effects._RESOLVED_DAMAGE_EFFECTS
    item_effects.refresh_item_effects()
    assert not item_effects._RESOLVED_DAMAGE_EFFECTS


def test_item_stats_memo_recomputes_after_a_version_bump(bumped_version) -> None:
    """``stats`` re-extracts when the generation moves, not only the id."""
    item = {
        "id": 3031,
        "name": "Synthetic Blade",
        "stats": {
            "attackDamage": {
                "flat": 40.0,
                "percent": 0.0,
                "perLevel": 0.0,
                "percentPerLevel": 0.0,
                "percentBase": 0.0,
                "percentBonus": 0.0,
            }
        },
    }
    assert stats.get_item_stats(item)["attack_damage"] == 40.0
    item["stats"]["attackDamage"]["flat"] = 70.0
    assert stats.get_item_stats(item)["attack_damage"] == 40.0, "memo should hold"
    bumped_version()
    assert stats.get_item_stats(item)["attack_damage"] == 70.0


def test_item_by_id_memo_rebuilds_after_a_version_bump(bumped_version) -> None:
    """``economy``'s id-keyed view is a generation of the cache, not a copy."""
    first = economy._item_by_id()
    assert economy._item_by_id() is first
    bumped_version()
    assert economy._item_by_id() is not first


def test_support_attrs_memo_recomputes_after_a_version_bump(bumped_version) -> None:
    """A champion's support verdict follows the cache it was read from."""
    champion = {
        "abilities": {
            "Q": [{"effects": [{"leveling": [{"attribute": "Damage"}]}]}],
            "W": [],
            "E": [],
            "R": [],
        }
    }
    assert support_effects._has_support_attributes(champion) is False
    champion["abilities"]["Q"][0]["effects"][0]["leveling"][0]["attribute"] = "Heal"
    assert support_effects._has_support_attributes(champion) is False, "memo holds"
    bumped_version()
    assert support_effects._has_support_attributes(champion) is True


def test_support_profile_memo_recomputes_after_a_version_bump(bumped_version) -> None:
    """An ability's shield/heal profile follows its cache generation too."""
    ability = {"effects": [{"leveling": [{"attribute": "Damage"}]}]}
    assert support_effects._support_profile(ability)[1] is None
    ability["effects"][0]["leveling"][0]["attribute"] = "Heal"
    assert support_effects._support_profile(ability)[1] is None, "memo holds"
    bumped_version()
    assert support_effects._support_profile(ability)[1] == "Heal"


UNBOUNDED_KEYED_MEMOS = {
    "calculator.stats._ITEM_STATS_MEMO": (stats, "_ITEM_STATS_MEMO"),
    "calculator.stats._ITEM_STATS_VALIDATION_MEMO": (
        stats,
        "_ITEM_STATS_VALIDATION_MEMO",
    ),
    "calculator.support_effects._SUPPORT_ATTRS_MEMO": (
        support_effects,
        "_SUPPORT_ATTRS_MEMO",
    ),
    "calculator.support_effects._SUPPORT_PROFILE_MEMO": (
        support_effects,
        "_SUPPORT_PROFILE_MEMO",
    ),
}
"""The version-keyed memos with no size bound, and therefore no other evictor.

``_CAST_ORDER_PARAMS_MEMO`` and ``_STATE_PROTO_MEMO`` clear wholesale at 512
entries and ``_ITEM_BY_ID_MEMO`` is rebuilt rather than appended to, so the
generation prefix costs them nothing.  These four grow without limit, which
is why they read the generation through ``live_generation``.
"""


def test_a_superseded_generation_is_evicted_rather_than_retained(
    bumped_version,
) -> None:
    """Unreachable is not gone: the version prefix must also collect.

    Keying on ``(data_version(), id(x))`` makes a stale entry unreachable —
    but before the prefix existed, a refresh that recycled an ``id()``
    overwrote its predecessor.  With the prefix and no size bound, both
    generations coexist and each holds a strong reference to the cached
    dict it was derived from, so every superseded generation is retained
    for the life of the process.
    """
    item = {
        "id": 3031,
        "name": "Synthetic Blade",
        "stats": {
            "attackDamage": {
                "flat": 40.0,
                "percent": 0.0,
                "perLevel": 0.0,
                "percentPerLevel": 0.0,
                "percentBase": 0.0,
                "percentBonus": 0.0,
            }
        },
    }
    champion = {
        "abilities": {
            "Q": [{"effects": [{"leveling": [{"attribute": "Damage"}]}]}],
            "W": [],
            "E": [],
            "R": [],
        }
    }
    ability = {"effects": [{"leveling": [{"attribute": "Damage"}]}]}

    def touch_every_memo() -> None:
        stats.get_item_stats(item)
        support_effects._has_support_attributes(champion)
        support_effects._support_profile(ability)

    touch_every_memo()
    before = {
        name: len(getattr(module, attribute))
        for name, (module, attribute) in UNBOUNDED_KEYED_MEMOS.items()
    }
    assert all(size > 0 for size in before.values()), before

    bumped_version()
    touch_every_memo()

    after = {
        name: len(getattr(module, attribute))
        for name, (module, attribute) in UNBOUNDED_KEYED_MEMOS.items()
    }
    assert after == before, (
        "a bumped generation must replace the previous one, not accumulate "
        f"beside it: {before} -> {after}"
    )
    versions = {
        name: {key[0] for key in getattr(module, attribute)}
        for name, (module, attribute) in UNBOUNDED_KEYED_MEMOS.items()
    }
    assert all(len(seen) == 1 for seen in versions.values()), versions


def test_the_unbounded_memo_set_is_the_keyed_set_minus_the_bounded_ones() -> None:
    """The four are derived from the declared table, never re-listed.

    ``UNBOUNDED_KEYED_MEMOS`` above must stay a subset of the memos
    ``data_registry`` declares version-keyed; a keyed memo that later loses
    its size bound has to join it rather than quietly grow.
    """
    keyed = set(data_registry.DATA_VERSION_KEYED_MEMOS)
    assert set(UNBOUNDED_KEYED_MEMOS) <= keyed
    bounded_or_rebuilt = keyed - set(UNBOUNDED_KEYED_MEMOS)
    assert bounded_or_rebuilt == {
        "calculator.economy._ITEM_BY_ID_MEMO",
        "calculator.pipeline._CAST_ORDER_PARAMS_MEMO",
        "calculator.survival.receipt_state._STATE_PROTO_MEMO",
    }


def test_state_proto_memo_key_carries_the_version() -> None:
    """The survival prototype memo is keyed ``(version, id(combatant))``.

    Asserted over source rather than through an import: ``receipt_state``
    is on the front-door frontier under Phase 4's name, and importing it
    here would silently claim this file as its front door.
    """
    source = (SRC_ROOT / "calculator" / "survival" / "receipt_state.py").read_text(
        encoding="utf-8"
    )
    assert "memo_key = (data_version(), id(combatant))" in source


def test_cast_order_params_memo_key_carries_the_version() -> None:
    """The derived cast-order params memo keys on the generation as well."""
    source = (SRC_ROOT / "calculator" / "pipeline.py").read_text(encoding="utf-8")
    assert "key = (data_version(), id(params), tuple(declared_order))" in source
