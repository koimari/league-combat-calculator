"""Test front door for ``data_registry``'s memo tables (D-49).

Most memos in this tree hold values derived from cached ``data/`` files; one
is cleared wholesale by the refresh it follows and one caches imported Python
modules.  The seven this phase owns were keyed on object identity alone,
which answers "is this the same dict?" and never "was this dict built from
the cache we are reading now?".  Those are different questions, and a
patch-day refresh is exactly where they diverge.

Two properties are checked here and neither is a convention:

* **The population is closed.**  A scan over ``src/calculator`` finds every
  module-level mapping named like a memo **and** every module-level empty
  dict some function fills lazily, and asserts the five declared tables
  partition the union.  A new memo therefore fails collection until somebody
  puts it in one of them — including one spelled off the naming convention,
  which is the hole S10 closed after finding an already-governed member
  sitting in it.  No count is stated here: the population is meant to grow,
  and a number in this docstring would be the drift the campaign is about.
* **The key really carries the version.**  Each of the seven is exercised
  through its own front door: memoize a value, mutate the source in place so
  identity cannot see the change, bump the counter, and assert the answer
  moves.  A key that merely mentions ``data_version()`` without reaching the
  lookup would pass a source scan and fail these.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.calculator import (
    data_registry,
    economy,
    item_behavior_catalog,
    stats,
    support_effects,
)

SRC_ROOT = Path(__file__).resolve().parent.parent / "src"


def _combatant_stub() -> SimpleNamespace:
    """The two attributes the survival prototype's key reads, and no more."""
    from src.calculator.defensive_effects import StartingDefenses

    return SimpleNamespace(
        defenses=StartingDefenses(),
        stats={
            "armor": 40.0,
            "magic_resistance": 32.0,
            "bonus_armor": 0.0,
            "bonus_magic_resistance": 0.0,
        },
    )


MEMO_SUFFIXES = ("_MEMO", "_CACHE")
MEMO_MUTATIONS = ("clear", "pop", "setdefault", "update")


def _module_name(path: Path) -> str:
    return ".".join(path.relative_to(SRC_ROOT).with_suffix("").parts)


def _module_level_dicts(tree: ast.Module) -> dict[str, ast.Dict]:
    """Every ``NAME = {...}`` bound at a module's top level."""
    bound: dict[str, ast.Dict] = {}
    for node in tree.body:
        if isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        else:
            continue
        if isinstance(target, ast.Name) and isinstance(value, ast.Dict):
            bound[target.id] = value
    return bound


def _filled_lazily(tree: ast.Module, names: Iterable[str]) -> set[str]:
    """Of *names*, those a function body writes into or empties.

    A memo is filled *lazily*: the module binds an empty dict and some
    function later stores into it.  A registry built at import time is the
    same expression mutated at module scope, which is why the scope of the
    mutation is the discriminator and the name is not.
    """
    wanted = set(names)
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Assign):
                for target in inner.targets:
                    if (
                        isinstance(target, ast.Subscript)
                        and isinstance(target.value, ast.Name)
                        and target.value.id in wanted
                    ):
                        found.add(target.value.id)
            elif (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Attribute)
                and isinstance(inner.func.value, ast.Name)
                and inner.func.value.id in wanted
                and inner.func.attr in MEMO_MUTATIONS
            ):
                found.add(inner.func.value.id)
    return found


def scan_memos() -> frozenset[str]:
    """Every module-level mapping under ``src/`` that is a memo.

    **Two detectors, unioned, because either one alone has a blind spot.**

    *By name*: ``<module>.<NAME>`` where NAME ends in ``_MEMO`` or
    ``_CACHE`` and the bound value is a dict display.  Names like
    ``_STATE_PROTO_MEMO_LIMIT`` and ``_SUSTAIN_STAT_CACHE_KEYS`` fall out
    because they do not end in a memo suffix, and a non-mapping constant
    falls out because it cannot hold entries.

    *By shape*: a module-level **empty** dict display that some function in
    the same module stores into, clears, pops, updates or ``setdefault``s.
    That is what a lazily filled cache looks like whatever it is called,
    and it is here because the name rule was the whole population until
    S10 — which made "the population is closed" a claim closed over a
    naming convention, with one already-governed member outside it:
    ``item_effects._RESOLVED_DAMAGE_EFFECTS``, declared in
    ``REFRESH_CLEARED_MEMOS`` and invisible to the scan that was supposed
    to prove nothing was missing.  The shape rule finds it, and finds the
    next one nobody thought to name well.

    Import-time registries are not caught: those are mutated at module
    scope, and the scope of the mutation rather than the name is what
    separates "filled on demand" from "built once at import".
    """
    found: set[str] = set()
    for path in sorted(SRC_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        module = _module_name(path)
        bound = _module_level_dicts(tree)
        by_name = {name for name in bound if name.endswith(MEMO_SUFFIXES)}
        by_shape = _filled_lazily(
            tree, (name for name, value in bound.items() if not value.keys)
        )
        found.update(f"{module}.{name}" for name in by_name | by_shape)
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
    """No memo is outside the five tables, and none is in two of them.

    Five, not four: ``REFRESH_CLEARED_MEMOS`` used to be left out of this
    partition, and it worked only because its one member's name does not
    match the convention the scan keyed on.  A table excluded from the
    partition that proves the population is closed is a table the partition
    cannot see grow.
    """
    tables = {
        "keyed": frozenset(data_registry.DATA_VERSION_KEYED_MEMOS),
        "rotation": frozenset(data_registry.ROTATION_MEMOS),
        "ungoverned": frozenset(data_registry.UNGOVERNED_MEMOS),
        "refresh_cleared": frozenset(data_registry.REFRESH_CLEARED_MEMOS),
        "deferred": frozenset(data_registry.DEFERRED_MEMOS),
    }
    declared: set[str] = set()
    for name, members in tables.items():
        overlap = declared & members
        assert not overlap, f"{name} re-declares {sorted(overlap)}"
        declared |= members
    assert scan_memos() == declared


# The seven non-rotation survivors D-49 names, by name rather than by count.
# A count agrees with itself after a swap, and this population *grows*: a memo
# a later slice creates over item-derived values is required by D-49's own
# rule — "keyed on by every item-derived memo" — to join the table, so a
# length assertion would turn obeying the decision into a failure.  What
# cannot happen is one of these seven leaving.
D49_SURVIVORS: frozenset[str] = frozenset(
    {
        "calculator.economy._ITEM_BY_ID_MEMO",
        "calculator.pipeline._CAST_ORDER_PARAMS_MEMO",
        "calculator.stats._ITEM_STATS_MEMO",
        "calculator.stats._ITEM_STATS_VALIDATION_MEMO",
        "calculator.support_effects._SUPPORT_ATTRS_MEMO",
        "calculator.support_effects._SUPPORT_PROFILE_MEMO",
        "calculator.survival.receipt_state._STATE_PROTO_MEMO",
    }
)


def test_the_phase_keys_its_survivors_and_the_rotation_lane_keys_its_own() -> None:
    """The split D-49 rules, as the two populations rather than as prose.

    Membership and not size: both tables are meant to grow — a later memo
    over item-derived values is *required* to join the keyed one — so a
    length here would turn obeying the decision into a failure.
    """
    assert D49_SURVIVORS <= set(data_registry.DATA_VERSION_KEYED_MEMOS)
    assert D49_SURVIVORS.isdisjoint(data_registry.ROTATION_MEMOS)
    assert data_registry.ROTATION_MEMOS


def test_every_declared_memo_carries_a_reason() -> None:
    """A table entry with an empty reason is an undeclared memo in disguise."""
    for table in (
        data_registry.DATA_VERSION_KEYED_MEMOS,
        data_registry.ROTATION_MEMOS,
        data_registry.UNGOVERNED_MEMOS,
        data_registry.DEFERRED_MEMOS,
        data_registry.REFRESH_CLEARED_MEMOS,
    ):
        for member, governance in table.items():
            assert governance.why.strip(), member


def test_every_declared_memo_names_what_stales_it() -> None:
    """Criterion 14's first clause, over the population it was unaskable of.

    "Every cache declares ``invalidated_by``" was a sentence about
    ``program/caches``; the memos here declared their governance by
    which table they sat in, which is a different language for the same
    question.  It is one language now -- :class:`Invalidator` is declared
    beside ``data_version`` and ``program/caches`` imports it -- so the
    clause is a loop rather than a survey.
    """
    for name, governance in data_registry.GOVERNED_MEMOS.items():
        assert governance.invalidated_by, name
        for member in governance.invalidated_by:
            assert isinstance(member, data_registry.Invalidator), name


def test_a_governance_with_no_invalidator_is_not_constructible() -> None:
    """R-05: the declaration refuses the empty set rather than storing it."""
    with pytest.raises(ValueError, match="says nothing"):
        data_registry.MemoGovernance(invalidated_by=frozenset(), why="because")


def test_a_governance_with_no_reason_is_not_constructible() -> None:
    with pytest.raises(ValueError, match="undeclared"):
        data_registry.MemoGovernance(
            invalidated_by=frozenset({data_registry.Invalidator.DATA_VERSION}),
            why="   ",
        )


def test_the_two_registries_are_one_question_with_one_reader() -> None:
    """``every_declaration`` unions both populations without overlapping."""
    from src.calculator.program.caches import CACHES, every_declaration

    declared = every_declaration()
    assert set(data_registry.GOVERNED_MEMOS) <= set(declared)
    assert {f"program.{name}" for name in CACHES} <= set(declared)
    assert len(declared) == len(data_registry.GOVERNED_MEMOS) + len(CACHES)
    for name, invalidators in declared.items():
        assert invalidators, name


def test_the_keyed_tables_all_say_data_version_and_the_others_do_not() -> None:
    """The vocabulary is shared; the claims each table makes are still four."""
    version = data_registry.Invalidator.DATA_VERSION
    for table in (
        data_registry.DATA_VERSION_KEYED_MEMOS,
        data_registry.ROTATION_MEMOS,
    ):
        for name, governance in table.items():
            assert version in governance.invalidated_by, name
    for table in (
        data_registry.UNGOVERNED_MEMOS,
        data_registry.DEFERRED_MEMOS,
        data_registry.REFRESH_CLEARED_MEMOS,
    ):
        for name, governance in table.items():
            assert version not in governance.invalidated_by, name


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
    "calculator.item_behavior_catalog._BEHAVIOR_RULES_MEMO": (
        item_behavior_catalog,
        "_BEHAVIOR_RULES_MEMO",
    ),
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
generation prefix costs them nothing.  These five grow without limit, which
is why their writes go through ``store_for_generation``.
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
        item_behavior_catalog.behavior_rules("Recurve Bow")
        stats.get_item_stats(item)
        support_effects._has_support_attributes(champion)
        support_effects._support_profile(ability)

    # The catalog memo is written by every test that reads a declaration, so
    # it arrives here already full of this generation's entries.  Cleared so
    # that "one touch, one entry" is true of every member and the comparison
    # below measures eviction rather than the session's history.
    item_behavior_catalog._BEHAVIOR_RULES_MEMO.clear()  # noqa: SLF001
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
        # One entry per mechanic per generation, and one mechanic declared,
        # so the generation prefix costs it nothing either.  Same key, same
        # bound, for the cadence its heal is delivered on.
        "calculator.interpreters.threshold_defense._THRESHOLD_HEALTH_OWNER_MEMO",
        "calculator.interpreters.threshold_defense._THRESHOLD_HEALTH_TICK_MEMO",
        # Bounded WITHIN a generation -- one entry per champion, so the
        # roster bounds it -- which is why it is here rather than in
        # ``UNBOUNDED_KEYED_MEMOS``.  Its write still goes through
        # ``store_for_generation``: bounded is not the same as evicting,
        # and each row set pins the cached ability dicts it came from.
        # The eviction claim is the test below.
        "calculator.ability_atoms._ABILITY_ATOMS_MEMO",
    }


def test_the_ability_atoms_memo_drops_its_superseded_generation(
    bumped_version,
) -> None:
    """The eviction claim, for the memo the merge added to the keyed table."""
    from src.calculator import ability_atoms  # noqa: PLC0415
    from src.calculator.data_fetcher import get_champion  # noqa: PLC0415

    champion = get_champion("Ahri")
    ability_atoms._ABILITY_ATOMS_MEMO.clear()  # noqa: SLF001
    ability_atoms._ability_atoms("Ahri", champion)  # noqa: SLF001
    before = len(ability_atoms._ABILITY_ATOMS_MEMO)  # noqa: SLF001

    bumped_version()
    ability_atoms._ability_atoms("Ahri", champion)  # noqa: SLF001

    assert len(ability_atoms._ABILITY_ATOMS_MEMO) == before  # noqa: SLF001
    generations = {key[0] for key in ability_atoms._ABILITY_ATOMS_MEMO}  # noqa: SLF001
    assert len(generations) == 1


def test_state_proto_memo_key_carries_the_version_and_every_input() -> None:
    """The survival prototype memo keys on values, and on all of them.

    The key gained the compiled below-half healing bonus when 3.9 made that
    number a parameter rather than a read, and lost ``id(combatant)`` at
    Phase 4 S10, which is where migration frontier counter 7 reached zero.
    A key that stopped short of its inputs would serve one participant's
    state to a caller that asked with another — silently, which is the whole
    failure this campaign is about.

    Read through the key function rather than off the source text: what the
    key must contain is a set of values, and a text match cannot say whether
    two of them are the same one.
    """
    from src.calculator.survival import receipt_state

    key = receipt_state._state_proto_key(  # pylint: disable=protected-access
        _combatant_stub(), 0.25
    )
    assert key[0] == data_registry.data_version()
    assert 0.25 in key
    assert len(key) == 3 + len(receipt_state._STATE_KEY_STATS)


def test_the_state_proto_key_covers_every_stat_the_prototype_reads() -> None:
    """A read the key cannot see is the one way a value key goes wrong.

    The population is every ``combatant.stats.get("...")`` in the module,
    read off the AST, so a field the construction starts consuming without
    joining ``_STATE_KEY_STATS`` fails here rather than serving one
    participant's resistances to another with the same defences.
    """
    from src.calculator.survival import receipt_state

    source = (SRC_ROOT / "calculator" / "survival" / "receipt_state.py").read_text(
        encoding="utf-8"
    )
    read = {
        node.args[0].value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr == "stats"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    }
    assert read == set(receipt_state._STATE_KEY_STATS)  # pylint: disable=W0212


def test_the_prototype_holds_no_health_derived_value() -> None:
    """The stat the guard above structurally cannot see, removed instead.

    ``_STATE_KEY_STATS`` covers every ``combatant.stats.get(...)`` in this
    module, and health was never one of them — it was read one call away,
    through ``transitions.participant_pools``, inside the construction the
    memo stores.  Two combatants with matching defences and resistances
    share a prototype now, and one may have 1000 health and the other 2500;
    that was safe only because ``build_state`` overwrote both fields, which
    is a fact about the caller.  So the prototype carries the slots and
    never the values, and this is what says so.
    """
    from src.calculator.survival import receipt_state

    proto = receipt_state._build_state_uncached(  # pylint: disable=W0212
        _combatant_stub(), 0.0
    )
    for field in receipt_state._PER_CALL_FIELDS:  # pylint: disable=W0212
        assert field in proto
    assert proto["pools"] is None
    assert proto["starting_shield"] == 0.0


def test_the_prototype_builder_never_reaches_the_health_read() -> None:
    """Read off the source, because the point is that it is unreachable."""
    from src.calculator.survival import receipt_state

    source = (SRC_ROOT / "calculator" / "survival" / "receipt_state.py").read_text(
        encoding="utf-8"
    )
    builder = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == "_build_state_uncached"
    )
    called = {
        node.func.id
        for node in ast.walk(builder)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "participant_pools" not in called
    assert "participant_pools" in receipt_state.__dict__


def test_two_combatants_sharing_a_prototype_keep_their_own_health() -> None:
    """The sharing the value key introduced, exercised rather than reasoned.

    Same defence record, same four resistances, different health: one memo
    entry, two states, two pools.  This is the end-to-end backstop for the
    two assertions above — they say the prototype cannot carry health, and
    this says the built state still does.
    """
    from src.calculator.survival import receipt_state

    states = []
    for health in (1000.0, 2500.0):
        combatant = _combatant_stub()
        combatant.stats = {**combatant.stats, "health": health}
        states.append(receipt_state.build_state(combatant, 0.0))
    assert [state["pools"].health for state in states] == [1000.0, 2500.0]
    assert states[0]["base_armor"] == states[1]["base_armor"]


def test_cast_order_params_memo_key_carries_the_version() -> None:
    """The derived cast-order params memo keys on the generation as well."""
    source = (SRC_ROOT / "calculator" / "pipeline.py").read_text(encoding="utf-8")
    assert "key = (data_version(), id(params), tuple(declared_order))" in source


def test_threshold_health_owner_memo_recomputes_after_a_version_bump(
    bumped_version, monkeypatch
) -> None:
    """Which item declares the temporary-health Lifeline follows the cache.

    The derivation is a scan over the catalog, so it is memoized — and a memo
    over a declaration is exactly the thing that must move when the registry
    behind the declaration is rebuilt.  The catalog is redirected rather than
    the registry mutated, because that is the shape identity keying cannot
    see either.
    """
    from src.calculator.interpreters import threshold_defense

    # A throwaway memo: this test writes an answer under a generation the
    # process has not reached yet, and a later real bump would otherwise
    # arrive at a key already holding the planted name.
    monkeypatch.setattr(threshold_defense, "_THRESHOLD_HEALTH_OWNER_MEMO", {})
    real = threshold_defense.behavior_rules
    assert threshold_defense.threshold_health_owner() == "Protoplasm Harness"

    renamed = tuple(
        replace(rule, owner="Cytoplasm Harness") for rule in real("Protoplasm Harness")
    )
    monkeypatch.setattr(
        threshold_defense,
        "behavior_rules",
        lambda owner: renamed if owner == "Protoplasm Harness" else real(owner),
    )
    assert (
        threshold_defense.threshold_health_owner() == "Protoplasm Harness"
    ), "memo should hold"
    bumped_version()
    assert threshold_defense.threshold_health_owner() == "Cytoplasm Harness"
