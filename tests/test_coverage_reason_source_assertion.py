"""The published all-defence coverage reason, bound to the branch that emits it.

The umbrella's **Amendment J — 2026-08-15** rules that a campaign-authored
justification string asserting a fact about ``src``-level vocabulary is
adjudicated *by source assertion*: a machine check binding the string to the
predicate that produces it, never by an R-18 investigation, whose export is
``data/`` plus ``docs/math-foundations.md`` and excludes ``src/`` by design.
The string it rules on is this one —

    "<subject> is a defence: the represented mechanic changes
     durability, not outgoing TDD."

where ``<subject>`` names the mechanics the item declares ("Plating",
"Unmake") and falls back to the universal "Every declared family on this
item" when the rule set names none.  The subject varies; the CLAIM — the
clause after it — is one literal in ``src`` and is what this file binds.

— published on an item's coverage payload, and the fact it asserts is about
``item_behavior.RuleFamily``: that every family the item declares is in the
defence group.  ``oracle-P3-3.8-leaf24.json`` could not check it and said so
in its own limitations block; the amendment permits the sentence to say it
**because this file is what keeps it true**, which is the campaign's own
prose-must-not-outrun-code mechanism turned on prose.  Without this file the
ruling rests on a premise nobody enforces, so it lands with it.

The amendment's three guards are the three shapes of check below.

*Guard 1 — one producer, named.*  :func:`emitting_sites` is a pure function
over module source, so the assertion is that the sentence is emitted at
exactly one site in ``src/``, inside ``item_coverage._declared_status``, under
an ``if`` whose test calls ``declares_only_defence`` — and
:func:`subset_comparisons` is the second half of it: that predicate must be
the subset test itself, ``families <= _DEFENCE_FAMILIES``, and not a list of
item names wearing a predicate's clothes (project rule 6).  A subset test has
a right-hand side, so :func:`grouped_members` is the third: the group the
sentence calls "a defence" is the one ``RuleFamily`` declares under its own
``# defence`` heading, and not a second opinion held in a frozenset beside it.

*Guard 2 — total, and in both directions.*  "Every declared family" is a
universal, so its check ranges over every cached item rather than over the
examples somebody thought of: an item published with the sentence declares
only defence families, and an item declaring only defence families with no
more specific receipt is published with the sentence.  One direction alone
would let the sentence be published somewhere new, or quietly stop being
published at all, with this file still green.

*Guard 3 — only the ``src``-vocabulary claim is carved out.*  Nothing here
touches the operative clause about outgoing TDD, which is R-18's and which
leaf24 certified on both sides.  This file asserts the added universal and
nothing else, which is exactly the portion the amendment reaches.

R-05: :func:`emitting_sites`, :func:`subset_comparisons`,
:func:`grouped_members` and :func:`unbound_claims` are pure, so every check
here has a permanent negative that reproduces its red on demand from a
fabricated source or a fabricated census — no mutated file on disk, and no
claim that a red was demonstrated once during development.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Mapping

import pytest

from src.calculator import item_coverage
from src.calculator.data_fetcher import fetch_item_data
from src.calculator.item_coverage import (
    ATTACKER_LANES,
    declares_only_defence,
    gated_state_reason,
    item_model_coverage,
)

SRC = Path(__file__).resolve().parents[1] / "src"

#: The published sentence, pinned here as the one thing this file is about.
#: Pinned rather than imported, because importing it from the module under
#: assertion would make "the sentence is emitted here" true by construction —
#: the tautology the campaign's own resolution check exists to refuse.
CENSUS_CLAIM = (
    " is a defence: the represented mechanic changes durability, " "not outgoing TDD."
)


# ── the pure halves (R-05's seams) ────────────────────────────────────────


def emitting_sites(
    source: str, sentence: str
) -> tuple[tuple[str, frozenset[str]], ...]:
    """Every place one module's source emits ``sentence``, with what guards it.

    A site is the enclosing function's name and the set of predicates called
    in the tests of the ``if`` statements the sentence sits in the *body* of.
    An ``else`` branch is not a guard: a sentence reachable when the predicate
    is false is precisely the binding this file exists to deny.
    """
    tree = ast.parse(source)
    parents = {
        child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)
    }
    sites: list[tuple[int, int, str, set[str]]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and node.value == sentence):
            continue
        function = ""
        guards: set[str] = set()
        child, current = node, parents.get(node)
        while current is not None:
            if isinstance(current, ast.FunctionDef) and not function:
                function = current.name
            if isinstance(current, ast.If) and child in current.body:
                guards.update(_called_names(current.test))
            child, current = current, parents.get(current)
        sites.append((node.lineno, node.col_offset, function or "<module>", guards))
    # Source order, because ``ast.walk`` yields breadth-first: a *guarded*
    # emitter sits one level deeper than an unguarded one beside it, so the
    # walk's own order would report the two in the opposite order to the file
    # a reader is holding.
    return tuple(
        (function, frozenset(guards))
        for _line, _column, function, guards in sorted(sites, key=lambda site: site[:2])
    )


def _called_names(test: ast.expr) -> frozenset[str]:
    """The names of every function called inside one ``if`` test."""
    names = set()
    for node in ast.walk(test):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            names.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            names.add(node.func.attr)
    return frozenset(names)


def subset_comparisons(source: str, function: str) -> tuple[tuple[str, str], ...]:
    """Every ``a <= b`` over two names inside one named function.

    The shape of the sentence, as code: a declared set contained in a group.
    A predicate that reaches its answer some other way — a membership test
    against a literal collection, a name lookup — returns nothing here, which
    is what the negative below asserts.
    """
    tree = ast.parse(source)
    found: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name == function):
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Compare) or len(inner.ops) != 1:
                continue
            left, right = inner.left, inner.comparators[0]
            if (
                isinstance(inner.ops[0], ast.LtE)
                and isinstance(left, ast.Name)
                and isinstance(right, ast.Name)
            ):
                found.append((left.id, right.id))
    return tuple(found)


def grouped_members(source: str, class_name: str) -> dict[str, tuple[str, ...]]:
    """One class's members, keyed by the ``# group`` comment they sit under.

    ``RuleFamily`` declares its four groups in comments — *strike*, *pricing*,
    *defence*, *rest* — and its docstring says the union is closable only
    because of them.  Comments are not in the tree ``ast`` builds, so this
    reads the class's own lines; what it buys is that the word "defence" in
    the published sentence means the group the enum declares, rather than a
    second opinion held in a frozenset beside it.
    """
    lines = source.splitlines()
    tree = ast.parse(source)
    node = next(
        item
        for item in ast.walk(tree)
        if isinstance(item, ast.ClassDef) and item.name == class_name
    )
    groups: dict[str, list[str]] = {}
    current = ""
    for line in lines[node.lineno : node.end_lineno or node.lineno]:
        comment = re.match(r"\s*#\s*(\w+)", line)
        member = re.match(r"\s*([A-Z][A-Z_0-9]*)\s*=", line)
        if comment:
            current = comment.group(1)
        elif member and current:
            groups.setdefault(current, []).append(member.group(1))
    return {name: tuple(members) for name, members in groups.items()}


def unbound_claims(
    published: Mapping[str, str], declared_defence_only: Mapping[str, bool]
) -> tuple[str, ...]:
    """Items published with the sentence whose declaration does not say it.

    The check itself, over two mappings rather than over the live cache, so a
    fabricated pair can turn it red without a file being edited.
    """
    return tuple(
        sorted(
            name
            for name, reason in published.items()
            if reason.endswith(CENSUS_CLAIM)
            and not declared_defence_only.get(name, False)
        )
    )


# ── the live census, computed once ────────────────────────────────────────


@pytest.fixture(name="published", scope="module")
def _published() -> dict[str, str]:
    """Every cached item's attacker-lane coverage reason, by item name."""
    names = {
        str(record.get("name", ""))
        for record in fetch_item_data().values()
        if isinstance(record, dict) and record.get("name")
    }
    return {name: item_model_coverage(name, ATTACKER_LANES).reason for name in names}


# ── guard 1: one producer, and it is the predicate ────────────────────────


def test_the_sentence_is_emitted_at_exactly_one_site_in_src() -> None:
    """One producer, named — the whole tree asked, not one file."""
    sites = {
        path.relative_to(SRC).as_posix(): emitting_sites(
            path.read_text(encoding="utf-8"), CENSUS_CLAIM
        )
        for path in sorted(SRC.rglob("*.py"))
    }
    emitting = {where: found for where, found in sites.items() if found}
    assert list(emitting) == ["calculator/item_coverage.py"], emitting
    assert emitting["calculator/item_coverage.py"] == (
        ("_declared_status", frozenset({"declares_only_defence"})),
    )


def test_the_guarding_predicate_is_the_sentence_evaluated() -> None:
    """``declares_only_defence`` is the subset test, not a list of items."""
    source = (SRC / "calculator" / "item_coverage.py").read_text(encoding="utf-8")
    assert subset_comparisons(source, "declares_only_defence") == (
        ("families", "_DEFENCE_FAMILIES"),
    )
    assert item_coverage._DEFENCE_FAMILIES  # the group the sentence names exists


def test_the_defence_group_the_sentence_names_has_one_home() -> None:
    """ "A defence" means the group ``RuleFamily`` itself declares.

    The predicate is a subset test and the group is its right-hand side, so a
    family added to ``_DEFENCE_FAMILIES`` without moving under the enum's own
    ``# defence`` heading would widen what the published sentence asserts
    while every other check here stayed green — the two would simply agree
    with each other.  This is the third opinion that stops them.
    """
    source = (SRC / "calculator" / "item_behavior.py").read_text(encoding="utf-8")
    declared = grouped_members(source, "RuleFamily")["defence"]
    assert {family.name for family in item_coverage._DEFENCE_FAMILIES} == set(declared)


def test_a_regrouped_family_is_reported() -> None:
    """R-05 for the group's one home: the reader is the enum's own comment."""
    fabricated = (
        "class RuleFamily(Enum):\n"
        '    """Doc."""\n'
        "    # strike — a hit lands\n"
        "    ON_HIT_STRIKE = 'on_hit_strike'\n"
        "    # defence — the subject survives differently\n"
        "    OPENING_DEFENSE = 'opening_defense'\n"
        "    # rest\n"
        "    SUSTAIN = 'sustain'\n"
    )
    assert grouped_members(fabricated, "RuleFamily") == {
        "strike": ("ON_HIT_STRIKE",),
        "defence": ("OPENING_DEFENSE",),
        "rest": ("SUSTAIN",),
    }


def test_a_second_or_unguarded_emitter_is_reported() -> None:
    """R-05 for guard 1, at the pure function.

    Three failures the assertion above must be able to see: a second site, a
    site guarded by some other predicate, and a site reachable when the
    predicate is *false*.
    """
    fabricated = (
        "def _declared_status(name, families):\n"
        "    if declares_only_defence(name):\n"
        f"        return {CENSUS_CLAIM!r}\n"
        f"    return {CENSUS_CLAIM!r}\n"
        "def somewhere_else(name):\n"
        "    if name in _A_HAND_LIST:\n"
        f"        return {CENSUS_CLAIM!r}\n"
    )
    assert emitting_sites(fabricated, CENSUS_CLAIM) == (
        ("_declared_status", frozenset({"declares_only_defence"})),
        ("_declared_status", frozenset()),
        ("somewhere_else", frozenset()),
    )


def test_a_predicate_that_is_not_a_subset_test_is_reported() -> None:
    """R-05 for guard 1's second half: a name list is not the sentence."""
    fabricated = (
        "def declares_only_defence(name):\n" "    return name in _DEFENCE_ITEM_NAMES\n"
    )
    assert subset_comparisons(fabricated, "declares_only_defence") == ()


# ── guard 2: total over the cache, in both directions ─────────────────────


def test_every_published_claim_is_one_the_declaration_makes(published) -> None:
    """Forwards: the sentence is never published over a non-defence family."""
    declared = {name: declares_only_defence(name) for name in published}
    assert unbound_claims(published, declared) == ()
    for name, reason in published.items():
        if not reason.endswith(CENSUS_CLAIM):
            continue
        families = item_coverage._declared_families(name)
        assert families, name
        assert families <= item_coverage._DEFENCE_FAMILIES, name


def test_every_declaration_that_makes_the_claim_publishes_it(published) -> None:
    """Backwards: the sentence cannot quietly stop being the answer.

    ``gated_state_reason`` is the one thing that outranks it — an item whose
    defence is armed by a bounded scenario input publishes that gate instead,
    which rung 2's own tests pin.  Everything else declaring only defence
    families publishes this sentence.
    """
    for name, reason in published.items():
        if not declares_only_defence(name) or gated_state_reason(name) is not None:
            continue
        assert reason.endswith(CENSUS_CLAIM), name


def test_the_population_the_sentence_quantifies_over_is_not_empty(published) -> None:
    """A universal over nothing is green by vacuity, which is not a check."""
    claiming = {
        name for name, reason in published.items() if reason.endswith(CENSUS_CLAIM)
    }
    assert claiming
    assert claiming == {
        name
        for name in published
        if declares_only_defence(name) and gated_state_reason(name) is None
    }


def test_an_unbound_publication_is_reported() -> None:
    """R-05 for guard 2, at the pure function.

    The failure this file exists to catch: the sentence published over an item
    whose declaration does not support it — the campaign-authored string
    outrunning the code, which is what the ruling permits it to assert only
    because this goes red.
    """
    fabricated = {"A Fabricated Item": CENSUS_CLAIM, "Another": "something else"}
    assert unbound_claims(fabricated, {"A Fabricated Item": False}) == (
        "A Fabricated Item",
    )
    assert unbound_claims(fabricated, {"A Fabricated Item": True}) == ()
