"""The trigger bus's construction invariants, registry and source assertions.

Every assertion A1-A9 below is written as a pure function over its inputs —
the scanned module text, or the capability registry — and every one of them
is exercised twice: once against the live tree, where it must pass, and once
against an injected mutation, where it must fail.  That second call is the
permanent seam R-05 requires: a check whose red is remembered rather than
reproducible is indistinguishable from a check that cannot fail, which is
the exact failure this campaign exists to end.
"""

import ast
import builtins
import importlib
import importlib.util
import inspect
import json
import re
import sys
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

from src.calculator import damage
from src.calculator import item_behavior_catalog as catalog
from src.calculator.item_behavior_catalog import behavior_rules
from src.calculator import trigger_stream as ts
from src.calculator.interpreters import INTERPRETERS
from src.calculator.item_behavior import (
    AllyProducer,
    EngineLane,
    LivePredicate,
    RuleFamily,
)
from src.calculator.ability_spec import (
    CC_KIND_VOCABULARY,
    IMMOBILIZING_CC_KINDS,
    Authority,
    DamagePart,
    Disposition,
)
from src.calculator.champions.engine import _validate_cc_event_contract
from src.calculator.item_support_effects import (
    EventViewStarvationError,
    _declared_authorities,
    derive_item_support_effects,
)
from src.calculator.program.compile import WalkCompiler, action_from_event
from src.calculator.survival.actions import TransitionRank
from src.calculator.program.views import ViewTag
from src.calculator.roster_composition import ActorRequest
from src.calculator.survival.compile import (
    UncompilableActionError,
    unrepresentable_template_receipt,
)

ROOT = Path(__file__).parents[1]
SRC = ROOT / "src"


# ---------------------------------------------------------------------------
# Source scanning — the shared seam every source assertion is injected through
# ---------------------------------------------------------------------------


def live_sources() -> dict[str, str]:
    """Every ``src/`` module's text, keyed by repo-relative posix path."""
    return {
        str(path.relative_to(ROOT)).replace("\\", "/"): path.read_text(encoding="utf-8")
        for path in sorted(SRC.rglob("*.py"))
    }


def _with(sources: Mapping[str, str], path: str, text: str) -> dict[str, str]:
    """The scanned tree with one module replaced — the injection seam."""
    injected = dict(sources)
    injected[path] = text
    return injected


def _enclosing(tree: ast.AST, node: ast.AST) -> str:
    """The innermost def/class a node sits inside, or ``<module>``."""
    best = None
    for candidate in ast.walk(tree):
        if not isinstance(
            candidate, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            continue
        end = candidate.end_lineno or candidate.lineno
        if candidate.lineno <= node.lineno <= end:
            if best is None or candidate.lineno > best.lineno:
                best = candidate
    return best.name if best else "<module>"


def _declared_guard_names(function: ast.AST) -> frozenset[str]:
    """Every item this function guards through a Phase 3 ally-packet producer.

    Phase 3's ``3.6`` replaces ``if "Fimbulwinter" in names`` with a guard on
    the declared producer the holder's registry entry carries, so A3's
    question — "does this impl guard exactly the items it declares?" — has to
    be asked of both guard forms or it would read a migrated branch as an
    unguarded one.  The producer is mapped back to its owners by
    ``item_behavior_catalog.owners_for``, which derives the answer from the
    registries; nothing here is a name list.
    """
    producers: set[str] = set()
    for node in ast.walk(function):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "AllyProducer"
        ):
            producers.add(node.attr)
    return frozenset(
        owner
        for producer in producers
        for owner in catalog.owners_for(AllyProducer[producer])
    )


def _guarded_names(function: ast.AST) -> frozenset[str]:
    """Every string literal this function tests for membership.

    Both live guard forms are read: the direct ``if "Phage" in names`` and
    the loop form ``for quest_item in ("World Atlas", "Runic Compass")``
    followed by ``if quest_item not in names``.  Resolving the loop variable
    is what makes the extraction total *before* P2b normalizes the two forms
    away, so this assertion is green on the commit that introduces it rather
    than one commit later.
    """
    loop_values: dict[str, tuple[str, ...]] = {}
    for node in ast.walk(function):
        if not isinstance(node, ast.For) or not isinstance(node.target, ast.Name):
            continue
        if not isinstance(node.iter, (ast.Tuple, ast.List, ast.Set)):
            continue
        values = tuple(
            element.value
            for element in node.iter.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        )
        if values:
            loop_values[node.target.id] = values
    names: set[str] = set()
    for node in ast.walk(function):
        if not isinstance(node, ast.Compare):
            continue
        if not any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
            continue
        left = node.left
        if isinstance(left, ast.Constant) and isinstance(left.value, str):
            names.add(left.value)
        elif isinstance(left, ast.Name) and left.id in loop_values:
            names.update(loop_values[left.id])
    return frozenset(names)


def _function_node(source: str, qualified: str) -> ast.AST:
    """The ``module.function`` node named by an ``impl`` path."""
    wanted = qualified.rsplit(".", 1)[1]
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == wanted:
            return node
    raise AssertionError(f"{qualified} names no function in its module")


def _impl_path(impl: str) -> str:
    """The repo-relative module file an ``impl`` dotted path lives in."""
    module = impl.rsplit(".", 1)[0]
    return "src/calculator/" + module.replace(".", "/") + ".py"


# ---------------------------------------------------------------------------
# Trigger construction and classification
# ---------------------------------------------------------------------------


def _row(**fields):
    base = {"time": 1.0, "source_key": "Q", "damage": 100.0, "damage_type": "magic"}
    base.update(fields)
    return base


def test_trigger_rejects_a_misspelled_cc_kind():
    """``Trigger(cc_kind="stnu", …)`` names the field and the vocabulary."""
    with pytest.raises(ValueError) as excinfo:
        ts.Trigger(
            kind=ts.TriggerKind.DAMAGE,
            time=0.0,
            source_key="Q",
            event_id="",
            attacker_id="",
            target_id="",
            sequence=-1,
            ability_instance="",
            damage=0.0,
            raw_damage=0.0,
            damage_type="",
            is_ability=False,
            basic_attack=False,
            reactive=False,
            cc=ts.CcClass.UNREVIEWED,
            cc_kind="stnu",
            cc_reviewed=False,
        )
    message = str(excinfo.value)
    assert "cc_kind" in message
    assert "CC_KIND_VOCABULARY" in message
    assert "'stun'" in message


@pytest.mark.parametrize(
    "field, value",
    [
        ("time", float("inf")),
        ("damage", -1.0),
        ("raw_damage", float("nan")),
        ("damage_type", "physcal"),
        ("source_key", ""),
    ],
)
def test_trigger_construction_violations_name_their_field(field, value):
    """Every construction violation raises ``ValueError`` naming the field."""
    fields = {
        "kind": ts.TriggerKind.DAMAGE,
        "time": 0.0,
        "source_key": "Q",
        "event_id": "",
        "attacker_id": "",
        "target_id": "",
        "sequence": -1,
        "ability_instance": "",
        "damage": 0.0,
        "raw_damage": 0.0,
        "damage_type": "",
        "is_ability": False,
        "basic_attack": False,
        "reactive": False,
        "cc": ts.CcClass.UNREVIEWED,
        "cc_kind": "",
        "cc_reviewed": False,
    }
    fields[field] = value
    with pytest.raises(ValueError, match=field):
        ts.Trigger(**fields)


def test_a_cc_trigger_can_never_carry_cc_none():
    """``kind is CC ⟹ cc is not NONE`` — the D-33 invariant, enforced."""
    with pytest.raises(ValueError, match="NONE"):
        ts.Trigger(
            kind=ts.TriggerKind.CC,
            time=0.0,
            source_key="E",
            event_id="",
            attacker_id="",
            target_id="",
            sequence=-1,
            ability_instance="",
            damage=0.0,
            raw_damage=0.0,
            damage_type="",
            is_ability=False,
            basic_attack=False,
            reactive=False,
            cc=ts.CcClass.NONE,
            cc_kind="none",
            cc_reviewed=True,
        )


def test_trigger_is_frozen_hashable_and_unordered():
    """Compared and hashed in dedupe keys, never sorted."""
    (trigger,) = ts.event_triggers(_row())
    assert hash(trigger) == hash(ts.event_triggers(_row())[0])
    with pytest.raises(AttributeError):
        trigger.time = 2.0  # type: ignore[misc]
    with pytest.raises(TypeError):
        _ = trigger < trigger  # type: ignore[operator]


def test_an_unmarked_row_classifies_unreviewed_and_never_none():
    """A silent absence and a reviewed "no control" are not the same fact."""
    assert ts._classify_cc(_row()) == (ts.CcClass.UNREVIEWED, "", False)
    assert ts._classify_cc(_row(cc_kind="none")) == (ts.CcClass.NONE, "none", True)


def test_control_that_is_neither_immobilize_nor_slow_is_reviewed_and_arms_nothing():
    """Malphite's cripple, Malzahar's silence and Teemo's blind have words.

    Calling either one "slow" claims a movement slow the Wiki does not,
    and calling it "none" denies a control the ability applies — so the
    vocabulary carries them, and they narrow a part to reviewed control
    that triggers neither Command nor Everlasting.
    """
    for kind in ("cripple", "silence", "blind"):
        cc_class, cc_kind, reviewed = ts._classify_cc(_row(cc_kind=kind))
        assert cc_class is ts.CcClass.NONE
        assert cc_kind == kind
        assert reviewed is True
        assert not ts.is_immobilizing_event(_row(cc_kind=kind))


def test_a_bare_crowd_control_row_is_unclassified_control():
    """The live stream admits rows carrying only the bare marker (D-33)."""
    cc_class, cc_kind, _ = ts._classify_cc(_row(crowd_control=True))
    assert cc_class is ts.CcClass.UNCLASSIFIED_CONTROL
    # Fimbulwinter's branch reads the token, and a bare marker does not
    # distinguish its immobilize and slow rungs, so it must stay empty.
    assert cc_kind == ""


def test_a_stunning_damage_row_yields_two_triggers_sharing_time_and_event():
    """One row, both streams — the packet is damage *and* control."""
    triggers = ts.event_triggers(
        _row(cc_kind="stun", _event_id="main:Q:0", target="enemy:Aatrox")
    )
    assert [trigger.kind for trigger in triggers] == [
        ts.TriggerKind.DAMAGE,
        ts.TriggerKind.CC,
    ]
    assert len({trigger.time for trigger in triggers}) == 1
    assert len({trigger.event_id for trigger in triggers}) == 1
    assert all(trigger.cc is ts.CcClass.IMMOBILIZE for trigger in triggers)


def test_a_misspelled_cc_kind_cannot_enter_the_stream():
    """A typo must never author a no-op stun, even from a raw row."""
    with pytest.raises(ValueError, match="cc_kind"):
        ts.event_triggers(_row(cc_kind="stnu"))


def test_a_misspelled_cc_kind_is_rejected_whichever_kind_was_asked_for():
    """Classification is unconditional; only *construction* is lazy."""
    for kinds in (
        frozenset({ts.TriggerKind.CC}),
        frozenset({ts.TriggerKind.DAMAGE}),
    ):
        with pytest.raises(ValueError, match="cc_kind"):
            ts.event_triggers(_row(cc_kind="stnu"), kinds=kinds)


def test_event_triggers_builds_only_the_kinds_asked_for():
    """D-30's laziness, made real: an unasked kind is never constructed.

    Not a micro-optimisation — an unbuilt trigger is also an unjudged one,
    which is what lets a control-only holder read a row the damage stream's
    stricter field contract would reject.
    """
    row = _row(cc_kind="stun")
    only_cc = ts.event_triggers(row, kinds=frozenset({ts.TriggerKind.CC}))
    assert [trigger.kind for trigger in only_cc] == [ts.TriggerKind.CC]
    only_damage = ts.event_triggers(row, kinds=frozenset({ts.TriggerKind.DAMAGE}))
    assert [trigger.kind for trigger in only_damage] == [ts.TriggerKind.DAMAGE]
    assert ts.event_triggers(row, kinds=frozenset()) == ()


def test_source_key_is_required_on_the_stream_that_dispatches_on_it():
    """Damage rows are attributed by source; control rows are not.

    Phage reads ``auto_attacks`` and Bloodsong reads
    ``spellblade_Bloodsong`` off the damage stream, so an unattributed
    damage row is one those two would price wrong.  Nothing dispatches on a
    control row's source, and the live scanners accept control rows that
    carry none — rejecting them would be a refactor changing behaviour.
    """
    unattributed = _row(source_key="", cc_kind="stun")
    with pytest.raises(ValueError, match="source_key"):
        ts.event_triggers(unattributed, kinds=frozenset({ts.TriggerKind.DAMAGE}))
    (control,) = ts.event_triggers(unattributed, kinds=frozenset({ts.TriggerKind.CC}))
    assert control.kind is ts.TriggerKind.CC
    assert control.source_key == ""
    assert control.cc is ts.CcClass.IMMOBILIZE


def _control_rows():
    """Every combination of a reviewed kind and the four legacy flags.

    The cross product, not the two axes separately: a row carrying both a
    ``cc_kind`` and a legacy boolean is exactly where a precedence rule can
    hide, and one axis at a time can never see it.
    """
    flags = ("immobilized", "hard_cc", "slowed", "slow", "crowd_control")
    for kind in ("", *sorted(CC_KIND_VOCABULARY)):
        for mask in range(1 << len(flags)):
            marks = {
                flag: True for index, flag in enumerate(flags) if mask & (1 << index)
            }
            yield _row(**({"cc_kind": kind} if kind else {}), **marks)


def test_sequence_zero_is_a_sequence_and_not_an_absent_one():
    """The ledger's first row is numbered zero, so zero has to survive.

    P2a spelled the parse ``int(_float(row.get("sequence", -1)) or -1)``,
    and ``0.0 or -1`` is ``-1``: every ledger's first row arrived on the bus
    carrying the absent marker.  Latent — no consumer reads
    ``Trigger.sequence`` today — but it is a field the bus publishes, and
    the control below is the ledger numbering it has to agree with.
    """
    assert ts.event_triggers(_row(sequence=0))[0].sequence == 0
    assert ts.event_triggers(_row(sequence=7))[0].sequence == 7
    assert ts.event_triggers(_row(sequence="3"))[0].sequence == 3
    # Absent, explicitly null, and unparsable all mean "this row carries no
    # ordinal", which is the one thing -1 is for.
    assert ts.event_triggers(_row())[0].sequence == -1
    assert ts.event_triggers(_row(sequence=None))[0].sequence == -1
    assert ts.event_triggers(_row(sequence="third"))[0].sequence == -1
    assert ts.event_triggers(_row(sequence=float("inf")))[0].sequence == -1
    ledger = (SRC / "calculator" / "damage.py").read_text(encoding="utf-8")
    assert "\n    sequence = 0\n" in ledger


def retired_immobilizing(row) -> bool:
    """The body ``ability_spec.is_immobilizing_event`` carried until P2c.

    P2a and P2b pinned the bus predicate against the *live* legacy symbol,
    which is what D-98 asks of a derivation landing beside the thing it
    replaces.  P2c deletes that symbol, so the witness becomes this
    transcription — kept here, in the suite, so the 192-row equivalence
    below stays a measurement rather than a memory of one.
    """
    kind = str(row.get("cc_kind", "")).lower().strip()
    return (
        kind in IMMOBILIZING_CC_KINDS
        or bool(row.get("immobilized"))
        or bool(row.get("hard_cc"))
    )


def test_classification_agrees_with_the_vocabulary_it_replaces():
    """The bus predicate answers exactly what ``ability_spec``'s did.

    Pinned over the **cross product** of the whole vocabulary and the five
    legacy booleans — 192 rows — because P2b repoints four consumers onto
    the bus predicate and "the two sides of one trigger must never diverge"
    has to be a measurement, not a claim.  The earlier form walked the two
    axes separately and so could not see the one place they interact: a
    ``cc_kind`` is evidence, never an override, so a reviewed ``"none"``
    beside a legacy ``hard_cc`` still classifies ``IMMOBILIZE``.
    """
    rows = list(_control_rows())
    assert len(rows) == (1 + len(CC_KIND_VOCABULARY)) * 32
    for row in rows:
        assert ts.is_immobilizing_event(row) == retired_immobilizing(row), row


def test_a_reviewed_no_control_kind_does_not_veto_a_legacy_flag():
    """The precedence question, pinned in both directions.

    ``cc_kind="none"`` narrows nothing, so it neither creates control nor
    destroys it; a narrowed kind that *is* control answers on its own.
    """
    assert ts._classify_cc(_row(cc_kind="none"))[0] is ts.CcClass.NONE
    assert ts._classify_cc(_row(cc_kind="none", hard_cc=True)) == (
        ts.CcClass.IMMOBILIZE,
        "none",
        True,
    )
    assert ts._classify_cc(_row(cc_kind="none", slowed=True))[0] is ts.CcClass.SLOW
    assert (
        ts._classify_cc(_row(cc_kind="none", crowd_control=True))[0]
        is ts.CcClass.UNCLASSIFIED_CONTROL
    )
    assert (
        ts._classify_cc(_row(cc_kind="stun", slowed=True))[0] is ts.CcClass.IMMOBILIZE
    )


def test_the_ladder_reads_immobilize_evidence_before_slow_evidence():
    """A row asserting both facts at once takes the immobilize rung.

    This is the one place the two retired predicates disagreed with each
    other, so unifying them had to pick: ``ability_spec``'s said immobilize
    (it OR'd the flags in) and ``_fimbulwinter_trigger_kind`` said slow (its
    slow rung sat above its legacy-flag rung).  The bus keeps
    ``ability_spec``'s answer — the three Command consumers outnumber
    Everlasting, and an immobilize is the stronger claim about the row —
    which moves Everlasting's rung on a control row carrying a slow fact and
    an immobilize fact together, and on that row alone.  No ``src/`` writer
    emits one: the two ``cc_kind`` writers (``_damage_event_row`` and
    ``_evaluate_cast_parts``) write no legacy boolean at all.
    """
    both = _row(hard_cc=True, slowed=True)
    assert ts._classify_cc(both)[0] is ts.CcClass.IMMOBILIZE
    assert retired_immobilizing(both) is True
    # Either fact alone still lands on its own rung.
    assert ts._classify_cc(_row(slowed=True))[0] is ts.CcClass.SLOW
    assert ts._classify_cc(_row(hard_cc=True))[0] is ts.CcClass.IMMOBILIZE


# ---------------------------------------------------------------------------
# The bus: lazy building and starvation
# ---------------------------------------------------------------------------


def test_authored_triggers_builds_only_the_declared_streams():
    """Lazy by construction — the whole performance argument for D-30."""
    result = {"damage_events": [_row(cc_kind="stun")], "takedown_events": [{}]}
    only_cc = ts.authored_triggers(result, streams=frozenset({ts.Stream.CC}))
    assert {trigger.kind for trigger in only_cc} == {ts.TriggerKind.CC}
    assert ts.authored_triggers(result, streams=frozenset()) == ()


def test_authored_triggers_skips_rows_that_are_not_mappings():
    """Echoes of Helia's missing ``isinstance`` guard dies structurally."""
    result = {"damage_events": ["not a row", _row()]}
    triggers = ts.authored_triggers(result, streams=frozenset({ts.Stream.DAMAGE}))
    assert len(triggers) == 1


def test_a_tuple_ledger_starves_a_declared_stream():
    """The campaign's ``STARVED`` leaf, as a control-flow signal (D-25)."""
    with pytest.raises(ts.ProjectionStarvation) as excinfo:
        ts.authored_triggers(
            {"damage_events_tuple": [(0.0, "main", 1.0)]},
            streams=frozenset({ts.Stream.CC}),
            holder="Imperial Mandate",
        )
    starved = excinfo.value
    assert starved.field == "cc"
    assert starved.producer == "Imperial Mandate"
    assert "tuple ledger" in starved.reason
    assert starved.disposition is Disposition.STARVED
    assert "STARVED" in str(starved)


def test_a_tuple_ledger_does_not_starve_a_caller_asking_for_nothing():
    """Raised on the read that cannot be answered, never at construction."""
    assert (
        ts.authored_triggers({"damage_events_tuple": [()]}, streams=frozenset()) == ()
    )


# ---------------------------------------------------------------------------
# Projections, pinned by name in both directions
# ---------------------------------------------------------------------------

TUPLE_INCAPABLE = frozenset(
    {
        "Bandlepipes",
        "Black Cleaver",
        "Bloodletter's Curse",
        "Bloodsong",
        "Cryptbloom",
        "Echoes of Helia",
        "Fimbulwinter",
        "Imperial Mandate",
        "Phage",
        "Solstice Sleigh",
    }
)
ENRICHED_VIEW = frozenset(
    {
        "Black Cleaver",
        "Bloodletter's Curse",
        "Bloodsong",
        "Cryptbloom",
        "Fimbulwinter",
        "Imperial Mandate",
    }
)
PAIR_OUTCOME = frozenset({"Cryptbloom"})


@pytest.mark.parametrize(
    "projection, expected",
    [
        (ts.tuple_incapable_items, TUPLE_INCAPABLE),
        (ts.enriched_view_items, ENRICHED_VIEW),
        (ts.pair_outcome_items, PAIR_OUTCOME),
    ],
)
def test_projections_equal_their_docstring_memberships(projection, expected):
    """Item for item, both directions, so drift either way fails."""
    assert projection() == expected
    for name in sorted(expected):
        assert name in projection.__doc__


def test_solstice_sleigh_is_tuple_incapable_by_declaration():
    """D-02: membership, and health regen is *not* the reason it is safe."""
    sleigh = ts.CAPABILITIES["solstice_sleigh.going_sledding"]
    assert "Solstice Sleigh" in ts.tuple_incapable_items()
    assert ts.Stream.CC in sleigh.reads
    assert sleigh.needs == frozenset({ts.Field.TIME})


def test_fimbulwinter_needs_the_enriched_view():
    """D-03: it carries ``_event_id`` onto its shield packet."""
    fimbulwinter = ts.CAPABILITIES["fimbulwinter.everlasting"]
    assert ts.Field.EVENT_ID in fimbulwinter.needs
    assert "Fimbulwinter" in ts.enriched_view_items()


# D-98's witness — ``tuple_incapable_items() ^ EVENT_VIEW_SUPPORT_ITEMS``
# asserted empty against the **imported** live set — lived here through P2a
# and P2b and is deleted by the same one-symbol commit that deletes the set
# it witnessed.  What survives it is stronger and not a comparison against a
# second list at all: ``test_projections_equal_their_docstring_memberships``
# pins the derivation item for item, in both directions.


# ---------------------------------------------------------------------------
# The enrichment shrink, proved packet-for-packet rather than asserted
# ---------------------------------------------------------------------------


def _scan_actor(participant_id, team, item_names):
    """One roster member the item scan can compile packets for."""
    return SimpleNamespace(
        participant_id=participant_id,
        team=team,
        level=18,
        items=tuple({"name": name} for name in item_names),
        stats={"mana": 1000.0, "max_mana": 1000.0, "is_melee": False},
        request=ActorRequest(item_options={}, ally_effects_enabled=True),
    )


# One auto, one stunning ability and one plain ability — enough to reach
# every branch the four shrinking holders own.
_SCAN_ROWS = (
    {
        "time": 0.5,
        "source_key": "auto_attacks",
        "damage": 90.0,
        "raw_damage": 120.0,
        "damage_type": "physical",
        "basic_attack": True,
    },
    {
        "time": 1.5,
        "source_key": "E",
        "damage": 200.0,
        "raw_damage": 260.0,
        "damage_type": "magic",
        "is_ability": True,
        "cc_kind": "stun",
    },
    {
        "time": 2.5,
        "source_key": "Q",
        "damage": 150.0,
        "raw_damage": 150.0,
        "damage_type": "magic",
        "is_ability": True,
    },
)

_HEAL_TRIGGER = {
    "time": 1.0,
    "kind": "heal",
    "target": "ally:Lulu",
    "amount": 200.0,
    "duration": 0.0,
}


def _enriched_view(defender):
    """The per-event copy ``participant_timeline`` builds for the scan."""
    return {
        "damage_events": [
            {**row, "target": defender, "_event_id": f"main:{defender}:{index}"}
            for index, row in enumerate(_SCAN_ROWS)
        ],
        # The enriched path also synthesises the first pair's takedown, so
        # the proof carries it: a shrinking holder must be indifferent to
        # that too, not merely to the two per-event fields.
        "takedown_events": [
            {"time": 2.5, "target": defender, "attacker": "main:Ahri"},
        ],
        "champion_stats": {"mana": 1000.0, "max_mana": 1000.0, "is_melee": False},
    }


def test_the_shrinking_holders_are_exactly_the_projection_difference():
    """The four the enrichment set loses, read off the projections."""
    assert ts.tuple_incapable_items() - ts.enriched_view_items() == frozenset(
        {"Bandlepipes", "Echoes of Helia", "Phage", "Solstice Sleigh"}
    )


@pytest.mark.parametrize(
    "holder_item", ["Bandlepipes", "Echoes of Helia", "Phage", "Solstice Sleigh"]
)
def test_the_enrichment_shrink_is_packet_for_packet(holder_item):
    """The one membership change inside a pure-refactor phase, proved.

    Each holder the enrichment set drops must author byte-identical
    templates from the plain engine result and from the enriched per-event
    copy — otherwise "the shrink is inert" is a claim about code nobody ran.
    """
    from src.calculator.item_support_effects import derive_item_support_effects

    holder = _scan_actor("main:Ahri", "main", (holder_item,))
    ally = _scan_actor("ally:Lulu", "ally", ())
    enemy = _scan_actor("enemy:Aatrox", "enemy", ())
    roster = [holder, ally, enemy]
    enriched = _enriched_view(enemy.participant_id)
    plain = {
        "damage_events": [dict(row) for row in _SCAN_ROWS],
        "champion_stats": enriched["champion_stats"],
    }

    from_plain = derive_item_support_effects(
        holder, plain, roster, trigger_effects=[_HEAL_TRIGGER]
    )
    from_enriched = derive_item_support_effects(
        holder, enriched, roster, trigger_effects=[_HEAL_TRIGGER]
    )

    assert from_plain, f"{holder_item} authored nothing — the proof would be vacuous"
    assert from_plain == from_enriched


def test_streams_for_and_holders_in_are_the_gate_call_shape():
    """The two functions the tuple gate and the enrichment gate will call."""
    assert ts.streams_for(frozenset({"Cryptbloom"})) == frozenset({ts.Stream.TAKEDOWN})
    assert ts.streams_for(frozenset({"Cull"})) == frozenset()
    assert ts.streams_for(frozenset({"Echoes of Helia"})) == frozenset(
        {ts.Stream.DAMAGE, ts.Stream.SUPPORT_TRIGGER}
    )
    items = [{"name": "Phage"}, {"name": "Boots"}]
    assert ts.holders_in(items, ts.tuple_incapable_items()) is True
    assert ts.holders_in(items, ts.pair_outcome_items()) is False


def test_every_item_owner_resolves_against_the_cached_item_data():
    """Registry validation reads no file, so the *test* does the resolving."""
    from src.calculator.data_fetcher import fetch_item_data

    catalog = {
        str(entry.get("name", ""))
        for entry in fetch_item_data().values()
        if isinstance(entry, dict)
    }
    unknown = sorted(
        capability.owner.name
        for capability in ts.CAPABILITIES.values()
        if isinstance(capability.owner, ts.ItemOwner)
        and capability.owner.name not in catalog
    )
    assert unknown == []


def test_importing_the_bus_performs_no_filesystem_read():
    """A leaf that touches ``data/`` is neither a leaf nor cached (D-35).

    Executed as a *fresh* module object rather than a reload, so the live
    ``trigger_stream`` enums keep their identity for every other test in the
    session; ``ability_spec`` is already imported, so a relative import here
    resolves out of ``sys.modules`` and reads nothing either.
    """
    spec = importlib.util.spec_from_file_location(
        "src.calculator._trigger_stream_import_probe",
        SRC / "calculator/trigger_stream.py",
    )
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "src.calculator"
    opened: list[str] = []
    real_open = builtins.open

    def _watched(*args, **kwargs):
        opened.append(str(args[0] if args else kwargs.get("file", "")))
        return real_open(*args, **kwargs)

    builtins.open = _watched
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        builtins.open = real_open
        del sys.modules[spec.name]
    assert opened == []
    assert module.tuple_incapable_items() == TUPLE_INCAPABLE


def test_the_bus_imports_exactly_two_intra_package_modules():
    """``ability_spec`` and ``program.views`` — the acyclicity argument.

    Phase 2 shipped this as *exactly one*, and Phase 4 S7 amends it to
    exactly two, in the criterion rather than in silence: ``view_tags`` is a
    field of the declaration table, so ``ViewTag`` has to be nameable here,
    and its home is ``program/views/__init__.py`` (umbrella, shared names).

    The amendment is bounded by what the original clause was protecting, and
    both halves are re-asserted rather than relaxed.  ``program.views``
    imports nothing, so the package graph is still acyclic; and the
    filesystem probe above still reports zero reads, which is the property
    that rules ``EngineLane``'s home *out* — importing ``item_behavior``
    opens ``data/items.json`` and ``data/runes.json`` at module scope, and a
    bus that reads ``data/`` is neither a leaf nor inside the caching layer
    (D-35, repo rule 2).  Anything beyond these two is still an error.
    """
    tree = ast.parse((SRC / "calculator/trigger_stream.py").read_text("utf-8"))
    relative = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.level
    }
    assert relative == {"ability_spec", "program.views"}


def test_the_view_tag_vocabulary_costs_the_bus_no_data_read():
    """The amendment's own red: ``program.views`` must stay import-free.

    A future edit that gave the views package a module-scope import of the
    behaviour registry would re-create exactly the condition the clause
    above forbids — silently, because the bus would keep importing one name
    from one module.  So the admissible import is pinned at its source.

    S9's ``serialize_leaf`` is defined over ``Quantity`` and joins the list:
    ``ability_spec`` is the campaign's dependency-free vocabulary leaf, which
    the line above already admits as the bus's *own* first import, so
    admitting it here reaches nothing the bus did not already reach.  The
    stdlib members are the type annotations the serializer carries.
    """
    tree = ast.parse((SRC / "calculator/program/views/__init__.py").read_text("utf-8"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for node in (node,)
        if getattr(node, "module", None) is not None
    }
    assert imported <= {
        "__future__",
        "ability_spec",
        "collections.abc",
        "dataclasses",
        "enum",
    }


# ---------------------------------------------------------------------------
# Registry validation — structural, and every branch has its own red
# ---------------------------------------------------------------------------


def _capability(**overrides) -> ts.MechanicCapability:
    fields = {
        "mechanic": "synthetic.mechanic",
        "owner": ts.ItemOwner("Synthetic"),
        "engine": ts.Engine.WALK,
        "reads": frozenset(),
        "needs": frozenset(),
        "authority": Authority.COUPLED_AUTHORITATIVE,
        "pairing": ts.Pairing.SOLO,
        "pair_of": None,
        "divergence_ref": None,
        "impl": "item_support_effects.derive_item_support_effects",
        "packet_source": "Synthetic — Mechanic",
        "view_tags": MappingProxyType({ts.Engine.WALK: ViewTag.APPLIED}),
        "holder_stacking": None,
    }
    fields.update(overrides)
    return ts.MechanicCapability(**fields)


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"mechanic": "Synthetic Mechanic"}, "mechanic id"),
        ({"owner": "Synthetic"}, "MechanicOwner"),
        ({"impl": "not a path"}, "dotted path"),
        ({"pairing": ts.Pairing.PAIRED}, "no pair_of"),
        ({"pair_of": "cull.reap"}, "pair_of"),
        (
            {"pairing": ts.Pairing.UNPAIRED_KNOWN_DEFECT},
            "resolves in no",
        ),
        ({"divergence_ref": "ghost"}, "divergence_ref"),
        (
            {"reads": frozenset({ts.Stream.TAKEDOWN})},
            "TARGET_ID",
        ),
        ({"needs": frozenset({ts.Field.TIME})}, "only readable off a stream"),
    ],
)
def test_registry_validation_rejects_each_structural_defect(
    monkeypatch, overrides, message
):
    """Every ``_validate_registry`` branch ships with a red it can reproduce."""
    broken = dict(ts.CAPABILITIES)
    capability = _capability(**overrides)
    broken[capability.mechanic] = capability
    monkeypatch.setattr(ts, "CAPABILITIES", broken)
    monkeypatch.setattr(ts, "_DECLARATIONS", tuple(broken.values()))
    with pytest.raises(ts.TriggerRegistryError, match=message):
        ts._validate_registry()


def test_registry_validation_rejects_duplicate_mechanic_ids(monkeypatch):
    """Two declarations, one id — the dict would silently keep the last."""
    monkeypatch.setattr(
        ts, "_DECLARATIONS", (_capability(), _capability(engine=ts.Engine.PAIR))
    )
    with pytest.raises(ts.TriggerRegistryError, match="duplicate mechanic ids"):
        ts._validate_registry()


def test_a_paired_capability_pointing_at_a_walk_half_is_rejected(monkeypatch):
    """``pair_of`` resolves to an ``Engine.PAIR`` capability, or it is a lie."""
    broken = dict(ts.CAPABILITIES)
    broken["synthetic.mechanic"] = _capability(
        pairing=ts.Pairing.PAIRED, pair_of="cull.reap"
    )
    monkeypatch.setattr(ts, "CAPABILITIES", broken)
    monkeypatch.setattr(ts, "_DECLARATIONS", tuple(broken.values()))
    with pytest.raises(ts.TriggerRegistryError, match="Engine.PAIR"):
        ts._validate_registry()


def test_a_paired_capability_naming_no_delivery_is_rejected(monkeypatch):
    """``PAIRED ⇒ a delivery reference`` — the half the pair half is paired against.

    The negative direction of Amendment C, and the one that had to survive
    it: widening the field to admit a rider must not turn "declares nothing"
    into a legal declaration.  Neither a packet source nor a rider stamp is
    still a paired half nobody can find.
    """
    broken = dict(ts.CAPABILITIES)
    broken["synthetic.mechanic"] = _capability(
        pairing=ts.Pairing.PAIRED,
        pair_of="abyssal_mask.magic_amp",
        packet_source=None,
    )
    monkeypatch.setattr(ts, "CAPABILITIES", broken)
    monkeypatch.setattr(ts, "_DECLARATIONS", tuple(broken.values()))
    with pytest.raises(ts.TriggerRegistryError, match="names no delivery"):
        ts._validate_registry()


def test_a_rider_delivered_paired_half_is_a_legal_declaration(monkeypatch):
    """The positive direction of Amendment C: a rider is a delivery.

    Shadowflame's Cinderbloom hands the walk an ``AmpBonus`` rider on its
    own triggering event rather than a packet, and before this amendment the
    registry had no shape that could say so — a ``PAIRED`` walk half had to
    carry a ``packet_source``, so the only constructible declaration was one
    that lied about what the mechanic does.  A stamp is a delivery
    reference, and this is the test that it constructs.
    """
    rider = _capability(
        mechanic="synthetic.rider",
        authority=Authority.COUPLED_AUTHORITATIVE_WITH_PAIR_PREVIEW,
        pairing=ts.Pairing.PAIRED,
        pair_of="abyssal_mask.magic_amp",
        packet_source=ts.RiderDelivery("Synthetic — Rider"),
        holder_stacking=ts.HolderStacking.PER_HOLDER,
    )
    declared = {**ts.CAPABILITIES, rider.mechanic: rider}
    monkeypatch.setattr(ts, "CAPABILITIES", declared)
    monkeypatch.setattr(ts, "_DECLARATIONS", tuple(declared.values()))
    ts._validate_registry()

    assert ts.delivery_reference(rider) == "Synthetic — Rider"
    assert ts.packet_source_literal(rider) is None


@pytest.mark.parametrize(
    "empty", [ts.RiderDelivery("  "), ts.HolderPacket("")], ids=["rider", "holder"]
)
def test_a_self_scoped_delivery_naming_nothing_is_rejected(monkeypatch, empty):
    """R-05's red for the amendment's own branch, for both self-scoped shapes.

    An empty literal is the self-scoped spelling of the packet with no
    source: a delivery reference nobody can grep for is a number no reader
    can trace back to the mechanic that authored it.  One clause covers both
    because it reads ``SELF_SCOPED_DELIVERIES``, so Amendment M's shape
    arrived already checked rather than with a second copy of the check.
    """
    broken = dict(ts.CAPABILITIES)
    broken["synthetic.mechanic"] = _capability(packet_source=empty)
    monkeypatch.setattr(ts, "CAPABILITIES", broken)
    monkeypatch.setattr(ts, "_DECLARATIONS", tuple(broken.values()))
    with pytest.raises(ts.TriggerRegistryError, match="naming nothing"):
        ts._validate_registry()


# ---------------------------------------------------------------------------
# A1 — one ``cc_kind`` parser, allowlisted by (module, symbol)
# ---------------------------------------------------------------------------

# The live readers after P2c.  P2b repointed the legacy symbols onto the bus
# and P2c deleted them, so what is left is the one classifier the phase's
# goal names plus the two sites that copy the token onto a row without ever
# branching on it; it is pinned here so each of those deletions was a
# visible, attributable edit rather than a silent one.
CC_KIND_READERS = {
    # ``_damage_event_row`` copies the token onto the ledger row; it is
    # the one reader that never classifies.  D-34's certification gate left
    # this map at P2b, when it moved onto the bus.
    "src/calculator/damage.py": frozenset({"_damage_event_row"}),
    # The two compiler entries are copies too, and the distinction is the
    # whole of A1: each stamps the raw token onto ``SurvivalAction.cc_kind``
    # and neither branches on it.  Every "is this an immobilize?" question
    # they ask goes to ``is_immobilizing_event`` on the line above the copy,
    # so the classifier still has one home.  ``add_engine_result`` joined
    # when the merge restored the delivery facts on compiled damage rows:
    # Force of Nature's Steadfast and the spell-shield cast grouping read
    # ``action.cc_kind`` off the action, and a compiled packet that carried
    # none priced differently from the receipt packet with nothing saying so.
    "src/calculator/program/compile.py": frozenset(
        {"action_from_event", "add_engine_result"}
    ),
    # The receipt view publishes the token as a public field; a projection
    # that classified it would be a second classifier inside a layer that
    # may not compute at all (criterion 3).
    "src/calculator/program/views/receipt.py": frozenset({"_damage_event_rows"}),
    "src/calculator/trigger_stream.py": frozenset({"_classify_cc"}),
    # ``state_lifecycle`` asks main's *action-blocking* question (may the
    # holder act?), which D-08 rules is a different question from the bus's
    # immobilize one: the two vocabularies differ on polymorph and on
    # flee/pull/snare/stasis, and it receipts an out-of-vocabulary token as
    # ``unknown_cc_kind`` where the bus refuses it.  One classifier per
    # question; each declared here.
    "src/calculator/state_lifecycle.py": frozenset(
        {"denial_reason", "is_candidate", "match"}
    ),
    # Everlasting's own kernel rule filters the control stream (it admits
    # kinds the immobilize predicate drops) and names the denial; the
    # dedupe key copies the token without branching on it.
    "src/calculator/item_support_effects.py": frozenset(
        {"_cc_event_stream", "_denial"}
    ),
}


def cc_kind_readers(sources: Mapping[str, str] | None = None) -> dict[str, frozenset]:
    """Every ``(module, symbol)`` that reads ``cc_kind`` off a raw row."""
    found: dict[str, set[str]] = {}
    for path, text in (sources or live_sources()).items():
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and node.args:
                first = node.args[0]
                name = (
                    node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else getattr(node.func, "id", "")
                )
                reads = (
                    name == "get"
                    and isinstance(first, ast.Constant)
                    and first.value == "cc_kind"
                )
            elif isinstance(node, ast.Subscript):
                reads = (
                    isinstance(node.slice, ast.Constant)
                    and node.slice.value == "cc_kind"
                )
            else:
                continue
            if reads:
                found.setdefault(path, set()).add(_enclosing(tree, node))
    return {path: frozenset(symbols) for path, symbols in found.items()}


def test_a1_cc_kind_is_parsed_only_where_the_allowlist_says():
    """A1 — and each allowlisted module holds no read outside its symbols."""
    assert cc_kind_readers() == CC_KIND_READERS


def test_a1_has_a_permanent_injection_seam():
    """R-05: A1's red is reproducible on demand, not remembered."""
    injected = _with(
        live_sources(),
        "src/calculator/economy.py",
        'def sneaky(row):\n    return row.get("cc_kind", "")\n',
    )
    assert cc_kind_readers(injected) != CC_KIND_READERS


# ---------------------------------------------------------------------------
# A2 — the retired scanners stay where the retirement schedule puts them
# ---------------------------------------------------------------------------

# ``phase-2-trigger-bus.md``'s *Retired symbols*.  The value was the module
# that still defined the symbol at the commit this map was last edited;
# P2b/P2c emptied it, so every entry is now ``[]`` and any definition
# anywhere in ``src/`` fails.  ``trigger_stream.is_immobilizing_event`` is
# absent from the map on purpose: the retired symbol is the ``ability_spec``
# one, and the bus's own predicate is the thing that replaced it.
RETIRED_SYMBOL_HOMES = {
    # Retired by P2b: the four raw-row scanners and the kind set behind
    # them.  ``event_triggers`` classifies the row now, and the branches
    # they fed read ``Trigger.cc`` instead.
    "_CC_TRIGGER_KINDS": [],
    "_cc_triggers": [],
    "_fimbulwinter_trigger_kind": [],
    "_takedown_triggers": [],
    "_damage_triggers": [],
    # Retired by P2c: the five hand name sets, their three ``has_*``
    # helpers, and the second authority table.
    "EVENT_SCAN_SUPPORT_ITEMS": [],
    "has_event_scan_support_items": [],
    "TAKEDOWN_SCAN_SUPPORT_ITEMS": [],
    "has_takedown_scan_support_items": [],
    "CC_TRIGGER_ITEMS": [],
    "DAMAGE_TRIGGER_ITEMS": [],
    "EVENT_VIEW_SUPPORT_ITEMS": [],
    "has_event_view_support_items": [],
    "cross_participant_authorities": [],
}


def retired_symbol_homes(
    sources: Mapping[str, str] | None = None,
) -> dict[str, list[str]]:
    """Where each retired symbol is *defined*, across the scanned tree."""
    homes: dict[str, list[str]] = {name: [] for name in RETIRED_SYMBOL_HOMES}
    for path, text in sorted((sources or live_sources()).items()):
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                defined = node.name
            elif isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                defined = target.id if isinstance(target, ast.Name) else ""
            else:
                continue
            if defined in homes:
                homes[defined].append(path)
    return {name: sorted(set(paths)) for name, paths in homes.items()}


def test_a2_the_retired_scanners_are_defined_only_in_their_retiring_module():
    """A2 — and ``trigger_stream`` re-defines none of them."""
    assert retired_symbol_homes() == RETIRED_SYMBOL_HOMES


def test_a2_has_a_permanent_injection_seam():
    """R-05: reinstate a scanner elsewhere and A2 goes red."""
    injected = _with(
        live_sources(),
        "src/calculator/economy.py",
        "def _cc_triggers(result):\n    return []\n",
    )
    assert retired_symbol_homes(injected) != RETIRED_SYMBOL_HOMES


# ---------------------------------------------------------------------------
# A3 — guarded == declared, folded per ``impl`` (D-37)
# ---------------------------------------------------------------------------


def name_guarded_impls(
    capabilities: Mapping[str, ts.MechanicCapability] | None = None,
    sources: Mapping[str, str] | None = None,
) -> dict[str, tuple[frozenset[str], frozenset[str]]]:
    """Per packet-emitting impl, the ``(guarded, declared)`` item names.

    Folded per ``impl`` because scoped to ``derive_item_support_effects``
    alone the identity is simply false for the other two producers —
    ``schedule_knights_vow`` guards ``Knight's Vow`` in the same module, and
    the ally-effects producer guards its items in another one.

    A **self-scoped** delivery is out of scope, and that is the check's own
    semantic rather than an exemption.  This fold is over impls that build a
    packet by asking whether an item name is in a build; a retired family's
    walk half builds nothing — it prices the declaration riding a packet the
    pair engine already authored — so it dispatches on no name and has none
    to guard.  Including it would ask a name-guard question of the one shape
    that exists precisely so the engine stops asking item names (D-42).
    """
    capabilities = capabilities or ts.CAPABILITIES
    sources = sources or live_sources()
    declared: dict[str, set[str]] = {}
    for capability in capabilities.values():
        if not isinstance(capability.owner, ts.ItemOwner):
            continue
        if capability.engine is not ts.Engine.WALK:
            continue
        if isinstance(capability.packet_source, ts.SELF_SCOPED_DELIVERIES):
            continue
        if ts.packet_source_literal(capability) is None:
            continue
        declared.setdefault(capability.impl, set()).add(capability.owner.name)
    return {
        impl: (
            _guarded_names(_function_node(sources[_impl_path(impl)], impl))
            | _declared_guard_names(_function_node(sources[_impl_path(impl)], impl)),
            frozenset(names),
        )
        for impl, names in sorted(declared.items())
    }


def test_a3_every_packet_emitting_impl_guards_exactly_what_it_declares():
    """A3 — an unregistered ``in names`` guard is a hole, and this is it."""
    folds = name_guarded_impls()
    assert set(folds) == {
        "item_support_effects.derive_item_support_effects",
        "item_support_effects.schedule_knights_vow",
    }
    for impl, (guarded, declared) in folds.items():
        assert guarded == declared, impl


def test_a3_has_a_permanent_injection_seam():
    """R-05: add an unregistered ``in names`` guard and A3 goes red."""
    path = "src/calculator/item_support_effects.py"
    sources = live_sources()
    injected = _with(
        sources,
        path,
        sources[path].replace(
            "    triggers = _support_triggers(trigger_effects, attacker)",
            '    if "Zhonya\'s Hourglass" in names:\n        pass\n'
            "    triggers = _support_triggers(trigger_effects, attacker)",
            1,
        ),
    )
    assert injected[path] != sources[path], "the injection did not apply"
    guarded, declared = name_guarded_impls(sources=injected)[
        "item_support_effects.derive_item_support_effects"
    ]
    assert guarded != declared


# ---------------------------------------------------------------------------
# A4 — the five hand name sets and three ``has_*`` helpers
# ---------------------------------------------------------------------------

# The occurrence sites, which P2c drove to empty.  Pinning them here is what
# makes each removal an attributable diff rather than a claim — the map read
# ``["src/calculator/item_support_effects.py"]`` on every row through P2a and
# P2b, and the criterion this discharges is "zero occurrences in ``src/``".
LEGACY_NAME_SET_SITES = {
    "EVENT_SCAN_SUPPORT_ITEMS": [],
    "TAKEDOWN_SCAN_SUPPORT_ITEMS": [],
    "CC_TRIGGER_ITEMS": [],
    "DAMAGE_TRIGGER_ITEMS": [],
    "EVENT_VIEW_SUPPORT_ITEMS": [],
    "has_event_scan_support_items": [],
    "has_takedown_scan_support_items": [],
    "has_event_view_support_items": [],
}


def legacy_name_set_sites(
    sources: Mapping[str, str] | None = None,
) -> dict[str, list[str]]:
    """Which ``src/`` modules still mention each retired name set or helper."""
    sites: dict[str, set[str]] = {name: set() for name in LEGACY_NAME_SET_SITES}
    for path, text in (sources or live_sources()).items():
        tree = ast.parse(text)
        for node in ast.walk(tree):
            name = ""
            if isinstance(node, ast.Name):
                name = node.id
            elif isinstance(node, ast.Attribute):
                name = node.attr
            elif isinstance(node, ast.alias):
                name = node.name
            elif isinstance(node, ast.FunctionDef):
                name = node.name
            if name in sites:
                sites[name].add(path)
    return {name: sorted(paths) for name, paths in sites.items()}


def test_a4_the_legacy_name_sets_occur_exactly_where_the_schedule_says():
    """A4 — zero occurrences after P2c; every occurrence pinned until then."""
    assert legacy_name_set_sites() == LEGACY_NAME_SET_SITES


def test_a4_has_a_permanent_injection_seam():
    """R-05: a new reader of a retired set is a new site, and A4 sees it."""
    injected = _with(
        live_sources(),
        "src/calculator/economy.py",
        "from .item_support_effects import CC_TRIGGER_ITEMS\n",
    )
    assert legacy_name_set_sites(injected) != LEGACY_NAME_SET_SITES


# The closing criterion says "no retired symbol appears **anywhere** in
# ``src/``", and A2/A4 above both read the parsed tree — definitions,
# imports, names, attributes — so a retired name surviving as prose in a
# comment or a docstring passes them.  That gap is not hypothetical: the
# phase-2 sign-off found ``_cc_triggers`` still named in ``trigger_stream``'s
# own ``Trigger`` docstring, describing what the retired scanner used to
# accept.  Prose is exactly where a retired name does its remaining damage —
# it is what a reader greps, and a docstring that discusses a symbol reads as
# a symbol that still exists — so the criterion is checked as written rather
# than narrowed to what the parser sees.
#
# ``EVENT_VIEW_STREAMS`` joins the list here because the phase's *Retired
# symbols* section names it in prose ("one symbol P2c deletes that this list
# does not name") rather than in the list ``RETIRED_SYMBOL_HOMES`` mirrors.
# ``is_immobilizing_event`` stays out for A2's reason: the retired symbol is
# ``ability_spec``'s and the bus's predicate is its live replacement, so a
# text scan cannot tell the two apart and the definition scan already can.
RETIRED_SYMBOL_TEXT = (*RETIRED_SYMBOL_HOMES, "EVENT_VIEW_STREAMS")


def retired_symbol_prose(
    sources: Mapping[str, str] | None = None,
) -> dict[str, list[str]]:
    """Every ``src/`` file naming a retired symbol in its *text*."""
    found: dict[str, list[str]] = {}
    for path, text in sorted((sources or live_sources()).items()):
        for name in RETIRED_SYMBOL_TEXT:
            if re.search(rf"\b{re.escape(name)}\b", text):
                found.setdefault(name, []).append(path)
    return found


def test_no_retired_symbol_is_named_anywhere_in_src_not_even_in_prose():
    """The closing criterion, read literally — comments and docstrings too."""
    assert retired_symbol_prose() == {}


def test_the_prose_scan_has_a_permanent_injection_seam():
    """R-05: a retired name reappearing in a comment is a finding."""
    injected = _with(
        live_sources(),
        "src/calculator/economy.py",
        "# the retired _cc_triggers used to read this row\n",
    )
    assert retired_symbol_prose(injected) == {
        "_cc_triggers": ["src/calculator/economy.py"]
    }


# ---------------------------------------------------------------------------
# A5 — nobody branches on the receipt token
# ---------------------------------------------------------------------------


def cc_kind_comparison_sites(
    sources: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    """Every ``x.cc_kind ==`` / ``x.cc_kind in`` comparison in ``src/``."""
    sites = []
    for path, text in sorted((sources or live_sources()).items()):
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            if path == "src/calculator/trigger_stream.py":
                # ``Trigger.__post_init__``'s own vocabulary guard is the
                # authoring check, not a consumer branch: it is what makes a
                # misspelled kind unrepresentable in the first place.
                continue
            if not any(
                isinstance(op, (ast.Eq, ast.NotEq, ast.In, ast.NotIn))
                for op in node.ops
            ):
                continue
            left = node.left
            if isinstance(left, ast.Attribute) and left.attr == "cc_kind":
                sites.append(f"{path}:{node.lineno}")
    return tuple(sites)


def test_a5_no_consumer_branches_on_the_opaque_receipt_token():
    """A5 — consumers branch on ``Trigger.cc``; ``cc_kind`` is a receipt."""
    assert cc_kind_comparison_sites() == ()


def test_a5_has_a_permanent_injection_seam():
    """R-05: add a ``cc_kind`` comparison and A5 goes red."""
    injected = _with(
        live_sources(),
        "src/calculator/economy.py",
        'def sneaky(trigger):\n    return trigger.cc_kind == "stun"\n',
    )
    assert cc_kind_comparison_sites(injected) != ()


# ---------------------------------------------------------------------------
# A6 — the takedown stream stays bounded (D-31)
# ---------------------------------------------------------------------------


def takedown_readers(
    capabilities: Mapping[str, ts.MechanicCapability] | None = None,
) -> frozenset[str]:
    """Every mechanic declaring the takedown stream."""
    return frozenset(
        mechanic
        for mechanic, capability in (capabilities or ts.CAPABILITIES).items()
        if ts.Stream.TAKEDOWN in capability.reads
    )


def takedown_synthesis_sites(
    sources: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    """Every assignment to a ``takedown_events`` key in the timeline."""
    text = (sources or live_sources())["src/calculator/participant_timeline.py"]
    sites = []
    for node in ast.walk(ast.parse(text)):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Subscript)
                and isinstance(target.slice, ast.Constant)
                and target.slice.value == "takedown_events"
            ):
                sites.append(f"participant_timeline.py:{node.lineno}")
    return tuple(sites)


def test_a6_the_takedown_stream_has_one_reader_and_one_synthesizer():
    """A6 — a bounded compatibility member, and both bounds are asserted."""
    assert takedown_readers() == frozenset({"cryptbloom.life_from_death"})
    assert len(takedown_synthesis_sites()) == 1
    for look_alike in ("axiom_arc.flux", "deaths_dance.defy"):
        assert ts.CAPABILITIES[look_alike].reads == frozenset()


def test_a6_has_a_permanent_injection_seam():
    """R-05: widen the takedown set, or add a second synthesizer, and A6 fails."""
    widened = dict(ts.CAPABILITIES)
    widened["axiom_arc.flux"] = _capability(
        mechanic="axiom_arc.flux",
        owner=ts.ItemOwner("Axiom Arc"),
        reads=frozenset({ts.Stream.TAKEDOWN}),
        needs=frozenset({ts.Field.TARGET_ID}),
    )
    assert takedown_readers(widened) != frozenset({"cryptbloom.life_from_death"})
    sources = live_sources()
    path = "src/calculator/participant_timeline.py"
    injected = _with(
        sources,
        path,
        sources[path] + '\ndef _second(result):\n    result["takedown_events"] = []\n',
    )
    assert len(takedown_synthesis_sites(injected)) == 2


# ---------------------------------------------------------------------------
# A7 — one immobilize vocabulary
# ---------------------------------------------------------------------------


def immobilize_literal_sites(
    sources: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    """Every collection literal holding both ``"stun"`` and ``"root"``."""
    sites = []
    for path, text in sorted((sources or live_sources()).items()):
        for node in ast.walk(ast.parse(text)):
            if not isinstance(node, (ast.Set, ast.List, ast.Tuple)):
                continue
            values = {
                element.value
                for element in node.elts
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            }
            if {"stun", "root"} <= values:
                sites.append(f"{path}:{node.lineno}")
    return tuple(sites)


def test_a7_the_immobilize_vocabulary_lives_only_in_the_vocabulary_module():
    """A7 — the fourth re-typing of this set is what D-08 had to widen.

    MERGE: ``ability_spec`` declares TWO such literals now, and they are two
    questions rather than one fact typed twice.  ``IMMOBILIZING_CC_KINDS``
    is what counts as an immobilize (Imperial Mandate's Command,
    Fimbulwinter's non-melee Everlasting); ``ACTION_BLOCKING_CC_KINDS`` is
    what stops a champion acting for the authored interval, read only by
    ``transitions.py``.  A knockback blocks the action and is not the
    immobilize the shield arms on, so collapsing them would move an answer.

    What A7 guards against is a re-typing in a CONSUMER, so the assertion
    is where the sites live rather than how many there are.
    """
    sites = immobilize_literal_sites()
    assert sites, "the vocabulary literal disappeared"
    assert all(site.startswith("src/calculator/ability_spec.py:") for site in sites)
    assert {"stun", "root"} <= IMMOBILIZING_CC_KINDS


def test_a7_has_a_permanent_injection_seam():
    """R-05: re-type the set outside the vocabulary module and A7 goes red."""
    injected = _with(
        live_sources(),
        "src/calculator/economy.py",
        'HARD_CC = {"stun", "root", "snare"}\n',
    )
    sites = immobilize_literal_sites(injected)
    assert "src/calculator/economy.py:1" in sites
    assert not all(site.startswith("src/calculator/ability_spec.py:") for site in sites)


# ---------------------------------------------------------------------------
# A8 — pairing is declared, cited and resolvable
# ---------------------------------------------------------------------------


def _delivery_defects(
    mechanic: str,
    capability: ts.MechanicCapability,
    sources: Mapping[str, str],
) -> tuple[str, ...]:
    """One paired half's delivery reference, resolved against what delivers it.

    Three deliveries, three resolutions, and neither of the last two is a
    weaker version of the first.  A packet-delivered half names a ``source``
    literal, and the check is that the literal is really in the builder's
    source — the incident's own failure was a claim about code that nothing
    read the code to confirm.  A rider-delivered half names no packet and
    therefore has no literal to grep for: its stamp is the mechanic id its
    rule carries and its rows publish, so it resolves against the
    **declaration**, which must hold a rule of that id whose activation is a
    live predicate.  That is what makes a stamp deliverable, and a stamp
    naming no such rule is the same defect one layer over.

    A :class:`~src.calculator.trigger_stream.HolderPacket` half resolves
    against the declaration for the same kind of reason and a different one.
    Its number arrives on a packet the *pair engine* authored, identified by
    the ``AuthoredDeclaration`` riding it — so the literal to resolve is a
    rule id, not a string in the walk's own pricing site, and grepping the
    pricing site for it would be a check that could never pass.  What makes
    the delivery real is that the owner declares a rule of that id and that
    the rule's family has a receipt-walk interpreter to price it: a half
    claiming to re-price a family no interpreter serves is the pair engine's
    number leaving a roster total with nothing replacing it.
    """
    delivery = ts.delivery_reference(capability)
    if isinstance(capability.packet_source, ts.RiderDelivery):
        owner = getattr(capability.owner, "name", "")
        declared = [
            rule
            for rule in behavior_rules(owner)
            if rule.mechanic_id == delivery
            and isinstance(rule.payload.activation, LivePredicate)
        ]
        if not declared:
            return (
                f"{mechanic}: rider stamp {delivery!r} names no declared "
                f"live-predicate rule of {owner!r}",
            )
        return ()
    if isinstance(capability.packet_source, ts.HolderPacket):
        owner = getattr(capability.owner, "name", "")
        rule = next(
            (
                declared
                for declared in behavior_rules(owner)
                if declared.mechanic_id == delivery
            ),
            None,
        )
        if rule is None:
            return (
                f"{mechanic}: holder packet {delivery!r} names no declared "
                f"rule of {owner!r}",
            )
        if (rule.family, EngineLane.RECEIPT_WALK) not in INTERPRETERS:
            return (
                f"{mechanic}: holder packet {delivery!r} declares "
                f"{rule.family.value}, which no receipt-walk interpreter "
                "serves, so the pair engine's number would leave the roster "
                "total with nothing replacing it",
            )
        return ()
    text = sources.get(_impl_path(capability.impl), "")
    if delivery not in text:
        return (
            f"{mechanic}: delivery reference {delivery!r} is "
            f"absent from {capability.impl}",
        )
    return ()


def pairing_defects(
    capabilities: Mapping[str, ts.MechanicCapability] | None = None,
    sources: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    """Every pairing claim that does not hold against source."""
    capabilities = capabilities or ts.CAPABILITIES
    sources = sources or live_sources()
    defects = []
    for mechanic, capability in sorted(capabilities.items()):
        if capability.pairing is ts.Pairing.UNPAIRED_KNOWN_DEFECT:
            defects.append(f"{mechanic}: unpaired known defect is not empty (D-92)")
        if capability.pairing is not ts.Pairing.PAIRED:
            continue
        defects.extend(_delivery_defects(mechanic, capability, sources))
        partner = capabilities.get(capability.pair_of or "")
        if partner is None:
            defects.append(f"{mechanic}: pair_of resolves to no capability")
            continue
        module, attribute = partner.impl.rsplit(".", 1)
        resolved = importlib.import_module(f"src.calculator.{module}")
        if not hasattr(resolved, attribute):
            defects.append(f"{mechanic}: pair half {partner.impl} does not import")
    return tuple(defects)


def test_a8_every_pairing_claim_holds_against_source():
    """A8 — empty defect set, and both escape hatches empty.

    ``UNPAIRED_KNOWN_DEFECT`` is the escape hatch D-92 pins empty: one half
    missing is a different statement from two halves disagreeing.  Phase 3
    froze Bloodsong's disagreement as the campaign's one
    :class:`DivergenceReceipt`, and Phase 4 S7 retired it by naming an
    authority — the walk — so the pair reading became a declared
    ``THEORETICAL`` preview rather than a rival answer.  ``DIVERGENCES`` is
    therefore empty too, and no row points at a receipt.

    Empty is the end state, not a hole: the type survives, and the next
    divergence has to be a typed entry pointing at a receipt.
    """
    assert pairing_defects() == ()
    assert dict(ts.DIVERGENCES) == {}
    assert [
        mechanic
        for mechanic, capability in ts.CAPABILITIES.items()
        if capability.divergence_ref is not None
    ] == []


def test_a_divergence_reference_that_resolves_in_nothing_is_still_rejected():
    """The retired receipt's gate outlives the receipt.

    ``DIVERGENCES`` being empty must not make ``divergence_ref`` a field that
    accepts anything — an empty registry that validates every reference is
    the shape of a check that cannot fail.
    """
    capability = _capability(
        pairing=ts.Pairing.PAIRED,
        pair_of="abyssal_mask.magic_amp",
        divergence_ref="bloodsong.expose_weakness",
        holder_stacking=ts.HolderStacking.PER_HOLDER,
    )
    with pytest.raises(ts.TriggerRegistryError, match="resolves in no"):
        ts._validate_pairing(capability.mechanic, capability)


def test_a8_has_a_permanent_injection_seam():
    """R-05: break a packet_source, an unpaired defect, or a pair half."""
    broken = dict(ts.CAPABILITIES)
    broken["abyssal_mask.unmake"] = _capability(
        mechanic="abyssal_mask.unmake",
        owner=ts.ItemOwner("Abyssal Mask"),
        authority=Authority.SPLIT,
        pairing=ts.Pairing.PAIRED,
        pair_of="abyssal_mask.magic_amp",
        packet_source="Abyssal Mask — Unmade",
    )
    assert pairing_defects(broken) != ()
    unpaired = dict(ts.CAPABILITIES)
    unpaired["synthetic.mechanic"] = _capability(
        pairing=ts.Pairing.UNPAIRED_KNOWN_DEFECT, divergence_ref="ghost"
    )
    assert pairing_defects(unpaired) != ()


# ---------------------------------------------------------------------------
# A9 — the declared-stream sensitivity matrix
# ---------------------------------------------------------------------------

_STREAM_PROBE = {
    ts.Stream.CC: (
        "damage_events",
        {
            "time": 3.0,
            "source_key": "E",
            "cc_kind": "stun",
            "target": "enemy:Aatrox",
            "_event_id": "main:E:0",
            "damage": 50.0,
            "damage_type": "magic",
        },
    ),
    ts.Stream.DAMAGE: (
        "damage_events",
        {
            "time": 1.0,
            "source_key": "Q",
            "target": "enemy:Aatrox",
            "_event_id": "main:Q:0",
            "damage": 120.0,
            "raw_damage": 200.0,
            "damage_type": "physical",
            "is_ability": True,
        },
    ),
    ts.Stream.TAKEDOWN: (
        "takedown_events",
        {"time": 5.0, "target": "enemy:Aatrox", "source_key": "takedown"},
    ),
}


def stream_sensitivity(
    capabilities: Mapping[str, ts.MechanicCapability] | None = None,
    build=None,
) -> dict[str, dict[str, bool]]:
    """Per capability, whether each declared stream changes what the bus emits.

    Generated from the registry so a new capability inherits the matrix.
    ``streams_for`` builds only what ``reads`` declares, so an omitted
    ``Stream.CC`` hands a scanner an empty list and prices zero — failure
    mode 2 of the incident, reproduced by a typo.  This is the umbrella's
    "emptying its trigger stream" mutation, and no other phase carries it.

    ``build`` is the injection seam: it defaults to the real bus and a
    substitute that silently drops one stream turns every declaring
    capability's row False, which is exactly the typo being guarded against.
    """
    builder = build or ts.authored_triggers
    matrix: dict[str, dict[str, bool]] = {}
    for mechanic, capability in sorted((capabilities or ts.CAPABILITIES).items()):
        declared = capability.reads & frozenset(_STREAM_PROBE)
        if not declared:
            continue
        row: dict[str, bool] = {}
        for stream in sorted(declared, key=lambda member: member.value):
            key, probe = _STREAM_PROBE[stream]
            fed = builder({key: [probe]}, streams=capability.reads)
            without = builder({key: [probe]}, streams=capability.reads - {stream})
            row[stream.value] = bool(fed) and len(without) < len(fed)
        matrix[mechanic] = row
    return matrix


def test_a9_every_declared_stream_is_load_bearing():
    """A9 — a capability invariant under all its declared streams fails."""
    matrix = stream_sensitivity()
    assert matrix, "the matrix is generated from CAPABILITIES and must not be empty"
    assert set(matrix) == {
        mechanic
        for mechanic, capability in ts.CAPABILITIES.items()
        if capability.reads & frozenset(_STREAM_PROBE)
    }
    for mechanic, row in matrix.items():
        assert row and all(row.values()), f"{mechanic} declares an inert stream: {row}"
    # Every SUPPORT_TRIGGER reader is reachable through the same projection,
    # even though its stream is built from authored templates rather than
    # parsed off raw rows.
    for capability in ts.CAPABILITIES.values():
        if ts.Stream.SUPPORT_TRIGGER not in capability.reads:
            continue
        assert ts.Stream.SUPPORT_TRIGGER in ts.streams_for(
            frozenset({capability.owner.name})
        )


def test_a9_has_a_permanent_injection_seam():
    """R-05: empty a declared stream and every capability reading it fails."""

    def _cc_dropped(result, *, streams, holder=""):
        """The typo: one declared stream silently never gets built."""
        return ts.authored_triggers(
            result, streams=streams - {ts.Stream.CC}, holder=holder
        )

    mutated = stream_sensitivity(build=_cc_dropped)
    cc_readers = [
        mechanic
        for mechanic, capability in ts.CAPABILITIES.items()
        if ts.Stream.CC in capability.reads
    ]
    assert cc_readers
    for mechanic in cc_readers:
        assert mutated[mechanic]["cc"] is False


# ---------------------------------------------------------------------------
# The R-12 producer source, and D-25's single boundary
# ---------------------------------------------------------------------------


# D-07's producer set, by name and not only by count: umbrella criterion 3
# reads "six, not five", and the count alone cannot tell a seventh producer
# from a swapped one.  Pinned here, beside the derivation, because this is
# the number the Shadowflame escalation argued from and the one Amendment C
# keeps standing.
RULED_CROSS_PARTICIPANT_PRODUCERS = frozenset(
    {
        "Abyssal Mask — Unmake",
        "Black Cleaver — Carve",
        "Bloodletter's Curse — Vile Decay",
        "Bloodsong — Expose Weakness",
        "Dream Maker — Blue Dream Bubble",
        "Imperial Mandate — Command",
    }
)


def test_the_cross_participant_producers_are_the_ruled_six():
    """Every packet modifying another participant's damage, enumerated."""
    from scripts.golden_snapshot import cross_participant_producers

    assert cross_participant_producers() == RULED_CROSS_PARTICIPANT_PRODUCERS


def test_a_rider_delivered_half_is_not_a_cross_participant_producer(monkeypatch):
    """Amendment C's other half — D-07 keys on the semantic, not the field.

    A rider amplifies the event it rides, and that event belongs to its own
    holder, so a rider-delivered half modifies no *other* participant's
    damage.  Were the producer set keyed on "a walk half with a
    cross-participant authority carrying anything in ``packet_source``",
    declaring Shadowflame's Cinderbloom would move a ruled count in order to
    satisfy a validator — which is a plan being edited by an implementation
    detail.  A packet-delivered half with the same authority still joins,
    which is what stops this being a hole rather than a distinction.
    """
    import scripts.golden_snapshot as gs

    rider = _capability(
        mechanic="synthetic.rider",
        authority=Authority.COUPLED_AUTHORITATIVE_WITH_PAIR_PREVIEW,
        pairing=ts.Pairing.PAIRED,
        pair_of="abyssal_mask.magic_amp",
        packet_source=ts.RiderDelivery("Synthetic — Rider"),
        holder_stacking=ts.HolderStacking.PER_HOLDER,
    )
    assert ts.cross_participant_packet_source(rider) is None
    monkeypatch.setattr(gs, "CAPABILITIES", {**ts.CAPABILITIES, rider.mechanic: rider})
    assert gs.cross_participant_producers() == RULED_CROSS_PARTICIPANT_PRODUCERS

    packeted = _capability(
        mechanic="synthetic.packeted",
        authority=Authority.COUPLED_AUTHORITATIVE_WITH_PAIR_PREVIEW,
        packet_source="Synthetic — Packet",
    )
    assert ts.cross_participant_packet_source(packeted) == "Synthetic — Packet"


def test_a_holder_scoped_packet_half_is_not_a_cross_participant_producer(monkeypatch):
    """Amendment M, Ruling 3 — the same semantic, the other delivery shape.

    A retiring family's walk half prices *its own holder's* damage and
    delivers it as an ordinary walk packet.  Keyed on "packet-delivered with
    a cross-participant authority" it would join the ruled six on the commit
    its retirement slice declares it, which is the ruled count moving to
    satisfy a validator that Amendment C already refused from the rider side.

    Three assertions, because the distinction has to hold without becoming a
    hole: the holder packet is not a producer, the producer set does not move
    when one is declared, and its literal is still findable through the two
    readings that ask whether a packet exists rather than whose damage it
    moves.
    """
    import scripts.golden_snapshot as gs

    holder = _capability(
        mechanic="synthetic.holder_scoped",
        authority=Authority.COUPLED_AUTHORITATIVE_WITH_PAIR_PREVIEW,
        packet_source=ts.HolderPacket("Synthetic — Holder Packet"),
    )
    assert ts.cross_participant_packet_source(holder) is None
    monkeypatch.setattr(
        gs, "CAPABILITIES", {**ts.CAPABILITIES, holder.mechanic: holder}
    )
    assert gs.cross_participant_producers() == RULED_CROSS_PARTICIPANT_PRODUCERS

    assert ts.packet_source_literal(holder) == "Synthetic — Holder Packet"
    assert ts.delivery_reference(holder) == "Synthetic — Holder Packet"


def test_the_coupled_producer_source_reads_the_capability_registry():
    """R-12 — the instrument and the packet compiler read one table.

    P2a landed the instrument's reading beside the ``ast``-derived table it
    replaces and asserted the two equal (D-98); P2c deleted that table, so
    what this now pins is that the two *readings* of ``CAPABILITIES`` — the
    baseline instrument's producer set and the packet compiler's
    owner-iff-``SPLIT`` table — still name the same producers.
    """
    from scripts.golden_snapshot import cross_participant_producers

    assert cross_participant_producers() == frozenset(_declared_authorities())


def test_a_seventh_producer_with_no_scenario_fails_capture(monkeypatch):
    """Runbook criterion 6's post-P2a half, exercised through the registry."""
    import scripts.golden_snapshot as gs

    seventh = _capability(
        mechanic="synthetic.seventh",
        owner=ts.ItemOwner("Synthetic Seventh"),
        authority=Authority.COUPLED_ONLY,
        packet_source="Synthetic Seventh — Curse",
    )
    monkeypatch.setattr(
        gs, "CAPABILITIES", {**ts.CAPABILITIES, "synthetic.seventh": seventh}
    )
    with pytest.raises(ValueError, match="Synthetic Seventh"):
        gs.capture_coupled(
            gs.COUPLED_SCENARIOS, producers=gs.cross_participant_producers()
        )


#: Every spelling that catches a member of the ``STARVED`` class.  The base
#: and its members are listed together because D-25's rule is about *where* a
#: named refusal is converted, so catching a subclass somewhere else evades it
#: exactly as catching the base would (umbrella Amendment G).
_STARVED_CLASS_NAMES = frozenset(
    {
        "StarvedSignal",
        "ProjectionStarvation",
        "OutcomeRewritten",
        "DuplicateApplied",
        "UnwrittenAdjustment",
    }
)


def except_starved_signal_sites(
    sources: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    """Every clause in ``src/`` catching a ``STARVED`` signal (D-25)."""
    sites = []
    for path, text in sorted((sources or live_sources()).items()):
        for node in ast.walk(ast.parse(text)):
            if not isinstance(node, ast.ExceptHandler) or node.type is None:
                continue
            names = {
                handled.id
                for handled in ast.walk(node.type)
                if isinstance(handled, ast.Name)
            }
            if names & _STARVED_CLASS_NAMES:
                sites.append(path)
    return tuple(sites)


def test_exactly_one_starved_signal_catch_exists():
    """D-25 — allowlisted by source assertion, and every other forbidden.

    Over the class rather than over one name.  Amendment G reads "exactly one
    catch" as one *place*, which is only enforceable if catching a member
    somewhere else is as red as catching the base: an absorbed
    ``OutcomeRewritten`` is the last-write-wins the write-once ledger exists
    to refuse, and it would be invisible to a scan keyed on one spelling.
    """
    assert except_starved_signal_sites() == ("src/app.py",)


def test_the_single_catch_has_a_permanent_injection_seam():
    """R-05: a second handler anywhere in ``src/`` turns the allowlist red."""
    injected = _with(
        live_sources(),
        "src/calculator/economy.py",
        "from .trigger_stream import ProjectionStarvation\n"
        "\n"
        "def swallow(run):\n"
        "    try:\n"
        "        return run()\n"
        "    except ProjectionStarvation:\n"
        "        return 0.0\n",
    )
    assert except_starved_signal_sites(injected) == (
        "src/app.py",
        "src/calculator/economy.py",
    )


def test_the_seam_catches_a_swallowed_ledger_raise_too():
    """The widening the class buys, injected: a member, not the base.

    Without this the generalisation would be untested in the direction that
    matters — the one where somebody absorbs a contested outcome under a name
    D-25 never mentioned.
    """
    injected = _with(
        live_sources(),
        "src/calculator/economy.py",
        "from .survival.outcome_state import OutcomeRewritten\n"
        "\n"
        "def swallow(run):\n"
        "    try:\n"
        "        return run()\n"
        "    except OutcomeRewritten:\n"
        "        return 0.0\n",
    )
    assert except_starved_signal_sites(injected) == (
        "src/app.py",
        "src/calculator/economy.py",
    )


def test_the_request_boundary_converts_a_starvation_into_a_named_500():
    """The one catch, exercised: a 500 carrying the ``STARVED`` receipt."""
    import src.app as app_module

    def _starving():
        raise ts.ProjectionStarvation("cc", "Imperial Mandate", "tuple ledger")

    guarded = app_module._within_starvation_boundary(_starving)
    with app_module.app.test_request_context("/api/calculate", method="POST"):
        response, status = guarded()
    assert status == 500
    payload = response.get_json()
    assert payload["disposition"] == Disposition.STARVED.value
    assert payload["starved"] == {
        "field": "cc",
        "producer": "Imperial Mandate",
        "reason": "tuple ledger",
    }


def test_every_registered_view_runs_inside_the_boundary():
    """One wrapper, applied once every route is registered — not per route."""
    import src.app as app_module

    unwrapped = sorted(
        endpoint
        for endpoint, view in app_module.app.view_functions.items()
        if getattr(view, "__wrapped__", None) is None
    )
    assert unwrapped == []
    assert "api_calculate" in app_module.app.view_functions
    assert (
        inspect.unwrap(app_module.app.view_functions["api_calculate"])
        is app_module.api_calculate
    )


# ---------------------------------------------------------------------------
# The edges P2b moved — every consumer difference the migration carries
# ---------------------------------------------------------------------------
#
# A pure refactor still has a boundary: four consumers stopped reading raw
# rows and started reading Triggers, and a Trigger is a narrower object than
# the dict it summarises.  Each difference below was found by the
# ``verify-P2b`` signoff rather than declared by the slice that shipped it,
# which is exactly why each is now a pin: prose that says "latent" ages into
# prose that said "latent", while a test says it again on every run.


def _fimbulwinter_gate(rows):
    """``damage._control_armed_event_coverage`` over one hand-built ledger."""
    complete, source, _note = damage._control_armed_event_coverage(
        [{"name": "Fimbulwinter"}], rows
    )
    return complete, source


def _support_actor(participant_id, team, item_names):
    """The ``derive_item_support_effects`` actor shape, minimally."""
    return SimpleNamespace(
        participant_id=participant_id,
        team=team,
        level=18,
        items=tuple({"name": name} for name in item_names),
        stats={"mana": 1000.0, "max_mana": 1000.0, "is_melee": False},
        request=ActorRequest(item_options={}, ally_effects_enabled=True),
    )


def test_the_certification_gate_is_not_exactly_the_disjunction_it_replaced():
    """``Trigger.cc_reviewed`` is narrower one way and wider the other.

    The retired gate read ``cc_reviewed is True or cc_kind is not None``, so
    mere *key presence* certified — a row carrying ``cc_kind=""`` passed.
    The bus has no key-presence fact to offer: an empty token is an
    unreviewed row, and reaching past the bus for the raw key would put a
    second ``cc_kind`` reader in ``damage.py``, which is the divergence A1
    exists to forbid.  So the gate withholds there, and withholding is the
    direction a certification gate is allowed to move.

    It is also wider in one place: ``is True`` became a truth test, so a
    truthy non-``True`` marker now certifies.

    Neither direction is reachable from the engine: ``_damage_event_row``
    never emits a token without a certifying flag beside it.  That is
    asserted below by driving the row builder rather than by matching its
    source, because the property is what makes the divergence unreachable
    and a text match also fails on a reformat that changes nothing.
    """
    assert _fimbulwinter_gate([{"is_ability": True, "source_key": "Q"}]) == (
        False,
        "fimbulwinter_everlasting",
    )
    assert _fimbulwinter_gate(
        [{"is_ability": True, "source_key": "Q", "cc_kind": "stun"}]
    ) == (True, "")
    # Narrower: a present-but-empty token certified before and does not now.
    assert _fimbulwinter_gate(
        [{"is_ability": True, "source_key": "Q", "cc_kind": ""}]
    ) == (False, "fimbulwinter_everlasting")
    # Wider: ``is True`` became a truth test.
    assert _fimbulwinter_gate(
        [{"is_ability": True, "source_key": "Q", "cc_reviewed": 1}]
    ) == (True, "")
    # The control that makes both unreachable from the engine, driven.
    for authored in (
        {"cc_kind": ""},
        {"cc_kind": "stun"},
        {"cc_kind": "none"},
        {"cc_reviewed": True},
        {},
    ):
        row = damage._damage_event_row(
            False,
            False,
            "Q",
            "physical",
            10.0,
            0.0,
            0,
            0.0,
            "ability",
            1,
            authored,
            True,
            False,
            None,
        )
        assert "cc_kind" not in row or row.get("cc_reviewed") is True


def test_the_certification_gate_selects_its_holder_from_a_declaration():
    """Who the gate certifies, and what it calls the refusal, are derived (3.9).

    The gate used to ask ``requires_authored_control_event`` — a registry-key
    read — and then spell ``Fimbulwinter`` twice more: once as the bus holder
    tag and once inside the note.  It now asks the ally-packet declarations
    for the shape it actually owes proof of, a shield the holder receives on a
    control event, and builds both receipts out of the declaration it found.

    So the two producers armed by the *same* trigger that deliver elsewhere
    are not swept in, and neither receipt can drift from the rule: the coarse
    source is the rule's own ``mechanic_id`` and the note names the holder and
    the producer it came from.
    """
    unreviewed = [{"is_ability": True, "source_key": "Q"}]
    complete, source, note = damage._control_armed_event_coverage(
        [{"name": "Fimbulwinter"}], unreviewed
    )
    rule = next(
        rule
        for rule in catalog.behavior_rules("Fimbulwinter")
        if rule.family is RuleFamily.ALLY_PACKET
    )
    assert (complete, source) == (False, rule.mechanic_id.replace(".", "_"))
    assert note == (
        "Fimbulwinter's Everlasting needs an authored immobilize/slow marker; "
        "the ability packet did not certify its crowd-control state."
    )
    # Same trigger, different recipient and different kind: neither is owed.
    for other in ("Imperial Mandate", "Bandlepipes"):
        assert damage._control_armed_event_coverage([{"name": other}], unreviewed) == (
            True,
            "",
            "",
        )
    assert damage._control_armed_holder_shields([{"name": "Fimbulwinter"}]) != ()
    assert damage._control_armed_holder_shields([{"name": "Bandlepipes"}]) == ()


def test_the_certification_gate_reads_every_mapping_not_only_a_dict():
    """``isinstance(event, dict)`` became ``isinstance(row, Mapping)``.

    The three sibling scanners the bus replaced all tested ``Mapping``; only
    this gate tested ``dict``, so the migration made it agree with them.  A
    non-dict ``Mapping`` ability row is therefore classified where it used
    to be skipped — and skipped meant vacuously certified.
    """
    row = MappingProxyType({"is_ability": True, "source_key": "Q"})
    assert _fimbulwinter_gate([row]) == (False, "fimbulwinter_everlasting")
    assert _fimbulwinter_gate([("positional", "row")]) == (True, "")


def test_the_certification_gate_propagates_the_damage_field_contract():
    """Two tolerated-in-silence rows are now named ``ValueError``s.

    The gate asks for ``Stream.DAMAGE``, so every ability row it inspects is
    built as a damage ``Trigger`` and judged by that stream's contract: an
    unattributed row and a ``damage_type`` outside the vocabulary both raise
    where the old ``.get`` comparisons shrugged.  Both are unreachable from
    the engine's ledger, and the control below is the reason — every row
    reaching it passed a ``damage_type`` filter naming the same three types,
    in both of ``_ordered_damage_events``' builders.
    """
    with pytest.raises(ValueError, match="source_key"):
        _fimbulwinter_gate([{"is_ability": True, "source_key": ""}])
    with pytest.raises(ValueError, match="damage_type"):
        _fimbulwinter_gate(
            [{"is_ability": True, "source_key": "Q", "damage_type": "mixed"}]
        )
    ledger = (SRC / "calculator" / "damage.py").read_text(encoding="utf-8")
    assert (
        ledger.count('damage_type not in {"physical", "magic", "true"}') == 2
    ), "both ledger builders must keep the filter that makes 'mixed' unreachable"


def test_a_control_trigger_is_not_judged_by_the_damage_type_contract():
    """The damage stream's type vocabulary stops at the damage stream.

    ``Trigger.__post_init__`` used to check ``damage_type`` for every kind,
    so a control-only holder — one whose ``reads`` never mentions
    ``Stream.DAMAGE`` — was judged by a contract it does not consume: a
    control row typed ``"mixed"`` raised out of
    ``derive_item_support_effects`` where the retired ``_cc_triggers``
    accepted it.  That is precisely the move ``source_key``'s own narrowing
    refused — "requiring one there would reject authored control the legacy
    scanner accepted, which a refactor may not do" — and the two fields now
    say the same thing.

    ``damage._damage_type_fields`` really does emit ``"mixed"``, so the
    reading matters even though the ledger filter keeps it off the engine's
    stream.  The controls: the type is still enforced on the damage stream,
    and it still reaches the control trigger as a verbatim receipt token.
    """
    row = {
        "time": 0.5,
        "source_key": "Q",
        "damage": 10.0,
        "damage_type": "mixed",
        "cc_kind": "stun",
        "cc_reviewed": True,
        "target": "enemy:Aatrox",
        "attacker": "main:Annie",
    }
    (control,) = ts.event_triggers(row, kinds=frozenset({ts.TriggerKind.CC}))
    assert control.kind is ts.TriggerKind.CC
    assert control.damage_type == "mixed"
    with pytest.raises(ValueError, match="damage_type"):
        ts.event_triggers(row, kinds=frozenset({ts.TriggerKind.DAMAGE}))
    assert "mixed" in (SRC / "calculator" / "damage.py").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "item",
    ["Solstice Sleigh", "Bandlepipes", "Imperial Mandate", "Fimbulwinter"],
)
def test_a_control_only_holder_scans_a_mixed_typed_row(item):
    """The four holders that read control and no damage, through the seam.

    Each declares ``Stream.CC`` and not ``Stream.DAMAGE``, which is the
    condition the narrowing turns on; the assertion below reads that off the
    registry rather than trusting the list.  Before the narrowing every one
    of them raised ``ValueError`` on this row.
    """
    reads = ts.streams_for(frozenset({item}))
    assert ts.Stream.CC in reads and ts.Stream.DAMAGE not in reads
    holder = _support_actor("ally:Lulu", "ally", (item,))
    ally = _support_actor("main:Ahri", "main", ())
    enemy = _support_actor("enemy:Aatrox", "enemy", ())
    result = {
        "damage_events": [
            {
                "time": 0.5,
                "source_key": "Q",
                "damage": 10.0,
                "damage_type": "mixed",
                "cc_kind": "stun",
                "cc_reviewed": True,
                "target": "enemy:Aatrox",
                "attacker": "ally:Lulu",
                "_event_id": "e1",
            }
        ]
    }
    derive_item_support_effects(holder, result, [holder, ally, enemy])


def test_echoes_of_helia_clamps_each_number_before_its_branch_chooses():
    """A negative raw number now contributes the row's mitigated damage.

    The retired expression clamped the value it had *chosen* —
    ``max(0.0, raw if present else damage)`` — so a present negative raw
    contributed nothing.  The bus clamps each field at construction and the
    branch then picks ``raw or damage``, so a clamped-to-zero raw falls
    through to the damage.  A negative raw is nonsense a producer would have
    to author deliberately; the pin records which way it now resolves.
    """
    holder = _support_actor("ally:Lulu", "ally", ("Echoes of Helia",))
    ally = _support_actor("main:Ahri", "main", ())

    def charges(**extra):
        row = {
            "time": 0.5,
            "source_key": "Q",
            "damage_type": "magic",
            "damage": 5.0,
            "target": "main:Ahri",
            **extra,
        }
        packets = derive_item_support_effects(
            holder,
            {"damage_events": [row]},
            [holder, ally],
            trigger_effects=[
                {"time": 1.0, "kind": "heal", "target": "main:Ahri", "amount": 100.0}
            ],
        )
        return [packet["amount"] for packet in packets]

    assert charges(raw_damage=-5.0) == charges() != []
    # ...and a row with nothing to charge from still produces no packet, so
    # the assertion above is a statement about the negative raw and not about
    # the branch firing unconditionally.
    assert charges(damage=0.0, raw_damage=-5.0) == []


@pytest.mark.parametrize("item", ["Phage", "Echoes of Helia"])
def test_a_tuple_ledger_names_the_holder_before_the_bus_can_starve(item):
    """The declared-holder raise still precedes the bus's own.

    Both holders declare ``Stream.DAMAGE`` now, so ``authored_triggers``
    would raise ``ProjectionStarvation`` on a tuple ledger — but
    ``require_event_view`` runs first and both are in the projected set, so
    the observable failure is the same named error it was before P2b.  That
    ordering is the whole reason the new raise path is unreachable, which
    makes it worth a test rather than a sentence.
    """
    holder = _support_actor("main:Annie", "main", (item,))
    ally = _support_actor("ally:Pantheon", "ally", ())
    result = {"damage_events_tuple": True, "damage_events": [(0.0, 100.0, "Q")]}
    with pytest.raises(EventViewStarvationError):
        derive_item_support_effects(holder, result, [holder, ally])
    assert item in ts.tuple_incapable_items()


def test_the_stack_ledgers_carry_a_coerced_string_trigger_event_id():
    """``_event_id`` reaches Carve and Vile Decay as the bus's ``str``.

    The retired expression passed the raw value through when the key was
    present, so a non-string or ``None`` id landed on the packet
    unconverted.  Every ``_event_id`` writer in ``src/`` builds one with an
    f-string or ``str(...)``, so only a hand-built row can tell the two
    apart.
    """
    holder = _support_actor("main:Annie", "main", ("Black Cleaver",))
    enemy = _support_actor("enemy:Aatrox", "enemy", ())

    def carve(**extra):
        row = {
            "time": 0.5,
            "source_key": "Q",
            "damage_type": "physical",
            "damage": 100.0,
            "target": "enemy:Aatrox",
            **extra,
        }
        packets = derive_item_support_effects(
            holder, {"damage_events": [row]}, [holder, enemy]
        )
        return [packet["trigger_event_id"] for packet in packets]

    assert carve() == [""]
    assert carve(_event_id=42) == ["42"]
    assert carve(_event_id=None) == [""]


def test_bloodsong_normalises_an_empty_trigger_event_id_to_none():
    """Expose Weakness spells its link ``event.event_id or None``.

    Three producers in this module now spell one thing three ways:
    Fimbulwinter and Bloodsong coerce an empty id to ``None``, Carve and
    Vile Decay pass the bus's ``str`` through as ``""``.  The retired code
    passed ``event.get("_event_id")`` through everywhere, so a
    present-but-empty id stayed ``""`` on all four.  44e10ea's body covers
    Fimbulwinter's ``or None`` and Carve/Vile Decay's ``""`` and not this
    one, so it is pinned here.

    Inert: every ``_event_id`` writer in ``src/`` builds one with an
    f-string, and both spellings are falsy, which is all the walk's
    trigger-link check reads.
    """
    holder = _support_actor("main:Annie", "main", ("Bloodsong",))
    enemy = _support_actor("enemy:Aatrox", "enemy", ())

    def expose(**extra):
        row = {
            "time": 0.5,
            "source_key": "spellblade_Bloodsong",
            "damage_type": "physical",
            "damage": 100.0,
            "target": "enemy:Aatrox",
            **extra,
        }
        packets = derive_item_support_effects(
            holder, {"damage_events": [row]}, [holder, enemy]
        )
        return [packet["trigger_event_id"] for packet in packets]

    assert expose(_event_id="e1") == ["e1"]
    assert expose(_event_id="") == [None]
    assert expose() == [None]


class TestTheSupportTriggerLinkRaise:
    """``survival/compile.py``'s ``support_trigger_link`` branch, in facts.

    This phase's Shape table rules that the comment above that branch —
    "No current support author emits a trigger link" — dies, because the
    sentence is false and a false "nobody emits this" reads as a licence to
    delete the guard.  Replacing one sentence with another only moves the
    day it goes stale, so the replacement comment states three facts and
    every one of them is asserted here instead: the link *is* emitted, the
    emitted one is declined a branch earlier, and the branch is live for
    anything the earlier receipt admits.
    """

    @staticmethod
    def _everlasting(**extra):
        """Fimbulwinter's shield packets from one authored immobilize.

        Two things the emitter's fail-closed contract owes and this class
        does not pin: a cast the holder can be identified by
        (``ability_instance``, without which the cadence refuses the trigger
        by name), and the separate ``item_denial`` receipt for a roster that
        states no positions.  So the row authors the identity and the helper
        keeps the shields, which is what the trigger link rides.
        """
        holder = _support_actor("main:Annie", "main", ("Fimbulwinter",))
        enemy = _support_actor("enemy:Aatrox", "enemy", ())
        row = {
            "time": 0.5,
            "source_key": "Q",
            "damage_type": "magic",
            "damage": 10.0,
            "cc_kind": "stun",
            "cc_reviewed": True,
            "ability_instance": "Q:1",
            "target": "enemy:Aatrox",
            "attacker": "main:Annie",
            **extra,
        }
        return [
            packet
            for packet in derive_item_support_effects(
                holder, {"damage_events": [row]}, [holder, enemy]
            )
            if packet["kind"] == "shield"
        ]

    def test_a_support_author_does_emit_a_trigger_link(self):
        """The enriched view stamps one; the plain view stamps ``None``.

        ``event.event_id or None`` is the spelling, so the field is absent
        as ``None`` rather than as ``""`` — which is what makes the
        compiler's ``is not None`` read the enrichment and not the key.
        """
        (enriched,) = self._everlasting(_event_id="e1")
        (plain,) = self._everlasting()
        assert enriched["source"] == "Fimbulwinter — Everlasting"
        assert enriched["_trigger_event_id"] == "e1"
        assert plain["_trigger_event_id"] is None

    def test_the_emitted_link_is_declined_one_branch_earlier(self):
        """Everlasting's own declaration refuses it before any template gate.

        The 3 s duration used to be that earlier decline; the typed shield
        ledger now stages a timed shield, so the duration refuses nothing and
        the template receipt admits this packet.  What still shadows the
        guard is a branch earlier still — Everlasting is declared a SELF
        shield, and the compiled kernel cannot stage one at all — so the
        trigger-link branch is again not what refuses today's one linked
        packet, and a comment claiming it is would be the mirror image of
        the one it replaced.  Pinned on the declaration because that is
        where the shadowing now lives: make the kernel stage a self shield
        and this test says so.
        """
        (enriched,) = self._everlasting(_event_id="e1")
        assert enriched["duration"] == 3.0
        assert unrepresentable_template_receipt(enriched) is None
        (rule,) = [
            rule
            for rule in catalog.behavior_rules("Fimbulwinter")
            if rule.family is catalog.RuleFamily.ALLY_PACKET
        ]
        assert rule.compilability is catalog.COMPILED_KERNEL_CANNOT_SELF_SHIELD

    def test_the_branch_still_refuses_a_link_the_receipt_admits(self):
        """An instant linked heal reaches the guard and is refused by name.

        This is the reachability the retired comment denied.  A shield or
        heal with no duration and no amount formula clears
        ``unrepresentable_template_receipt`` entirely, so the trigger link
        is the only thing standing between it and a compiled action that
        would silently ignore the link.
        """
        linked = {
            "target": "main:Annie",
            "kind": "heal",
            "amount": 10.0,
            "duration": 0.0,
            "time": 0.5,
            "source": "probe",
            "_trigger_event_id": "e1",
        }
        assert unrepresentable_template_receipt(linked) is None
        with pytest.raises(UncompilableActionError) as raised:
            WalkCompiler().add_support_templates([linked], 0, {"main:Annie": 0})
        assert raised.value.receipt == "support_trigger_link"
        assert raised.value.source == "probe"

    def test_the_same_template_without_the_link_compiles(self):
        """R-05's seam: the link is what fires the raise, not the shape.

        Without it the identical template compiles to one action, so the
        test above cannot be passing for an unrelated reason.
        """
        unlinked = {
            "target": "main:Annie",
            "kind": "heal",
            "amount": 10.0,
            "duration": 0.0,
            "time": 0.5,
            "source": "probe",
            "_trigger_event_id": None,
        }
        compiler = WalkCompiler()
        compiler.add_support_templates([unlinked], 0, {"main:Annie": 0})
        assert len(compiler.actions) == 1


def test_a_support_scan_row_carrying_a_garbage_number_is_dropped_not_raised():
    """``_float`` softened the damage numbers the way it softened ``time``.

    The retired ``_damage_triggers`` read
    ``float(event.get("damage", 0.0) or 0.0) > 0.0``: a garbage number
    raised ``ValueError`` out of the scan, and an infinite one compared
    greater than zero and was admitted.  The bus coerces both to 0.0 —
    non-finite included, since ``Trigger`` refuses a non-finite number —
    and ``_stack_triggers`` then drops the row for carrying no damage.
    44e10ea named this softening for ``time`` only.

    So the direction moved twice, and opposite ways: garbage no longer
    raises, and infinity no longer stacks.
    """
    holder = _support_actor("main:Annie", "main", ("Black Cleaver",))
    enemy = _support_actor("enemy:Aatrox", "enemy", ())

    def carve(**extra):
        row = {
            "time": 0.5,
            "source_key": "Q",
            "damage_type": "physical",
            "damage": 100.0,
            "target": "enemy:Aatrox",
            **extra,
        }
        return derive_item_support_effects(
            holder, {"damage_events": [row]}, [holder, enemy]
        )

    assert len(carve()) == 1
    assert carve(damage="a lot") == []
    assert carve(damage=float("inf")) == []
    assert carve(damage=float("nan")) == []
    # raw_damage rides the same coercion, and it does not decide the stack.
    assert len(carve(raw_damage="a lot")) == 1


def test_the_receipt_token_is_the_rows_own_token_on_every_rung():
    """b2882ec reordered the ladder and moved no ``cc_kind`` token.

    ``verify-P2b``'s second pass read the reorder as also propagating the
    token onto rungs that used to blank it — ``{"cc_kind": "none",
    "hard_cc": True}`` yielding ``cc_kind="none"`` where it once yielded
    ``""``.  It does not: the retired ladder returned the normalised token
    whenever it was non-empty and ``""`` exactly when it was empty, which
    is the same function as returning it unconditionally.  What b2882ec
    moved is the *class* on that row, from ``NONE`` to ``IMMOBILIZE``, and
    that move is what its body describes.

    The pin is the property rather than the two rows: over the vocabulary
    crossed with the five legacy booleans, the token the bus publishes is
    always the row's own token, normalised.
    """
    flags = ("immobilized", "hard_cc", "slowed", "slow", "crowd_control")
    rows = 0
    for kind in sorted(CC_KIND_VOCABULARY) + [""]:
        for bits in range(1 << len(flags)):
            row = {
                "cc_kind": kind,
                **{flag: bool(bits & (1 << index)) for index, flag in enumerate(flags)},
            }
            rows += 1
            assert ts._classify_cc(row)[1] == kind, row
    assert rows == (len(CC_KIND_VOCABULARY) + 1) * (1 << len(flags))
    # The two rows the signoff named, stated outright.
    assert ts._classify_cc({"cc_kind": "none", "hard_cc": True}) == (
        ts.CcClass.IMMOBILIZE,
        "none",
        True,
    )
    assert ts._classify_cc({"cc_kind": "none"}) == (ts.CcClass.NONE, "none", True)


def test_an_out_of_vocabulary_cc_kind_raises_on_every_path_p2b_repointed():
    """The walk gained a raise it did not have, and this is where it fires.

    All three retired predicates coerced an unknown ``cc_kind`` to "not
    immobilizing" and carried on, so a kind outside the vocabulary priced
    zero in silence.  P2b routed four consumers onto ``_classify_cc``,
    which refuses it — the ruling in Phase 2's Types section, and the right
    answer: a misspelled kind must never author a no-op stun.  None of the
    nine slice bodies says the walk started raising, so the pin says it.

    The control is the sibling authoring path: a ``cc_kind`` on a *part* is
    already refused at parse time, by a message naming the champion, the
    entry and the kind.  The gap between the two paths — a module-authored
    ``damage_events`` row reaches the walk unchecked — is the escalation in
    ``docs/receipts/escalated-defects-P2b.json``.
    """
    row = {
        "time": 0.5,
        "source_key": "Q",
        "damage_type": "magic",
        "damage": 100.0,
        "target": "enemy:Aatrox",
        "attacker": "main:Annie",
        "is_ability": True,
        "cc_kind": "mesmerize",
    }
    with pytest.raises(ValueError, match="CC_KIND_VOCABULARY"):
        ts.is_immobilizing_event(row)
    with pytest.raises(ValueError, match="CC_KIND_VOCABULARY"):
        damage._control_armed_event_coverage([{"name": "Fimbulwinter"}], [row])
    with pytest.raises(ValueError, match="CC_KIND_VOCABULARY"):
        action_from_event(row, TransitionRank.DAMAGE, 0, {"enemy:Aatrox": 0})
    holder = _support_actor("ally:Lulu", "ally", ("Imperial Mandate",))
    enemy = _support_actor("enemy:Aatrox", "enemy", ())
    with pytest.raises(ValueError, match="CC_KIND_VOCABULARY"):
        derive_item_support_effects(holder, {"damage_events": [row]}, [holder, enemy])
    # The fourth path is reached through a FightState the walk builds; the
    # control is that it reads the same predicate and no other.
    command_amp = inspect.getsource(damage._apply_command_amp)
    assert "is_immobilizing_event(event)" in command_amp
    assert "from .trigger_stream import" in (
        SRC / "calculator" / "damage.py"
    ).read_text(encoding="utf-8")
    # ...and the control that this is a refusal, not a regression: the part
    # spelling of the same kind never gets near the walk.
    with pytest.raises(ValueError, match="unknown cc_kind"):
        _validate_cc_event_contract(
            "Fakechamp",
            "Q",
            {"parts": (DamagePart("magic", 100.0, cc_kind="mesmerize"),)},
        )


class TestTheEscalatedDefectIsStillTracked:
    """The one gap P2b's pins cannot close, held as an artifact.

    The bus's refusal is ruled and correct, and the champion contract
    already refuses the part-authored spelling at parse time.  The
    module-authored ``damage_events`` spelling reaches the walk unchecked,
    where the refusal lands as a plain ``ValueError`` the campaign's single
    request-boundary catch does not name.  Fixing that is a new parse-time
    rejection in a file outside this phase's Shape table, inside a phase
    ruled a pure refactor, so the slice may not do it.

    An escalation that lives only in a commit body is absorbed by the next
    baseline re-capture.  This one is joined to the signoff that raised it,
    to the source sites that carry it, and to a reproducer that turns red
    the moment the defect stops reproducing — which is how the entry gets
    closed deliberately rather than fading out.
    """

    RECEIPT = ROOT / "docs" / "receipts" / "escalated-defects-P2b.json"
    REQUIRED = (
        "id",
        "dated",
        "origin",
        "raised_by",
        "site",
        "defect",
        "live_signature",
        "not_fixed_here_because",
        "resolution",
    )

    def _entries(self):
        return json.loads(self.RECEIPT.read_text(encoding="utf-8"))["defects"]

    def test_every_entry_carries_what_an_escalation_needs(self):
        entries = self._entries()
        assert entries, "the escalation ledger is empty"
        for entry in entries:
            for field in self.REQUIRED:
                assert entry.get(field), f"{entry.get('id')} omits {field}"
            assert len(entry["dated"]) == 10 and entry["dated"].count("-") == 2

    def test_every_site_still_carries_the_defect(self):
        for entry in self._entries():
            for site in entry["site"]:
                source = (ROOT / site["file"]).read_text(encoding="utf-8")
                assert site["fragment"] in source, f"{entry['id']}: {site['file']}"

    def test_the_defect_still_reproduces(self):
        """Parse time refuses one spelling of the kind and not the other."""
        (entry,) = self._entries()
        kind = entry["live_signature"]["unknown_kind"]
        assert kind not in CC_KIND_VOCABULARY
        with pytest.raises(ValueError, match="unknown cc_kind"):
            _validate_cc_event_contract(
                "Fakechamp", "Q", {"parts": (DamagePart("magic", 1.0, cc_kind=kind),)}
            )
        # The same kind, authored as a declared event, passes parse time...
        _validate_cc_event_contract(
            "Fakechamp",
            "Q",
            {"parts": (), "damage_events": [{"time": 0.0, "cc_kind": kind}]},
        )
        # ...is copied onto the ledger row verbatim...
        assert 'row["cc_kind"] = str(cc_kind)' in (
            SRC / "calculator" / "damage.py"
        ).read_text(encoding="utf-8")
        # ...and raises a bare ValueError, not the type the one request
        # boundary names, on every walk path the receipt lists.
        with pytest.raises(ValueError) as excinfo:
            ts.is_immobilizing_event({"cc_kind": kind})
        assert not isinstance(excinfo.value, ts.ProjectionStarvation)
        assert entry["live_signature"]["caught_at_the_request_boundary"] is False
        assert except_starved_signal_sites() == ("src/app.py",)

    def test_the_caller_is_told_a_champion_defect_is_a_bad_request(self):
        """What the endpoint actually does with it — measured, not reasoned.

        The signoff that raised this expected an unnamed 500.  It is a 400
        whose body is the vocabulary message, because ``/api/calculate``
        wraps its engine call in ``except ValueError``.  Milder than
        reported and still wrong: an authoring defect inside a champion
        module is billed to the caller, and it carries none of the
        ``STARVED`` receipt the sibling condition gets one boundary away.

        The seam injects the *exception*, not the outcome: the raise is the
        one ``_classify_cc`` produces, verbatim.
        """
        import src.app as app_module

        (entry,) = self._entries()
        with pytest.raises(ValueError) as excinfo:
            ts.is_immobilizing_event(
                {"cc_kind": entry["live_signature"]["unknown_kind"]}
            )
        raised = excinfo.value

        def _raise_the_walks_error(_data):
            raise raised

        original = app_module.calculate_payload
        app_module.calculate_payload = _raise_the_walks_error
        try:
            response = app_module.app.test_client().post(
                "/api/calculate", json={"champion": "Ahri", "level": 1}
            )
        finally:
            app_module.calculate_payload = original
        surfaced = entry["live_signature"]["surfaced_to_the_caller_as"]
        assert response.status_code == surfaced["status"]
        payload = response.get_json()
        assert sorted(payload) == sorted(surfaced["body_keys"])
        assert str(raised) == payload["error"]
        assert "disposition" not in payload and "starved" not in payload
        assert surfaced["carries_disposition"] is False


class TestTheP2aGateBreachIsStillTracked:
    """The one red this phase shipped, held as an artifact instead of a word.

    P2a's own 54 lines in ``src/app.py`` pushed the two score-serving route
    decorators past ``CITATION_WINDOW``, four plan citations drifted with
    them, and R-01 row 1 was red at that commit.  Its body called the
    failures pre-existing.  The tree at that commit cannot be repaired by a
    commit after it, and this lane may not rewrite a range the sign-off, the
    phase document and the sibling receipt all cite by sha.

    So the record is corrected and pinned: the receipt carries the three
    commits by sha and subject and what ``plan_audit`` measured at each --
    clean at the entry tip, exactly the four findings at P2a, clean again at
    the repair.  Those trees are immutable and R-34 reserves rewriting them,
    so the measurement has one answer forever; re-deriving it per run bought
    nothing and cost the suite the whole repository instead of the tree.

    What stays checkable here is what a later commit can still falsify: the
    entry's shape, and that the three source sites the breach is written
    across still say what the receipt cites.  The named resolution is
    unchanged -- the integration agent folds the locator refresh into the
    commit that caused the shift, R-01 row 1 goes green at every commit of
    the integrated history, and this class and its receipt are retired in the
    same pass.
    """

    RECEIPT = ROOT / "docs" / "receipts" / "escalated-defects-P2a.json"
    REQUIRED = TestTheEscalatedDefectIsStillTracked.REQUIRED
    #: The three commits the receipt measures ``plan_audit`` at, and whether
    #: the gate was clean there.
    MEASURED = (
        ("phase_entry_tip", True),
        ("breached_in", False),
        ("repaired_in", True),
    )

    def _entries(self):
        return json.loads(self.RECEIPT.read_text(encoding="utf-8"))["defects"]

    def test_every_entry_carries_what_an_escalation_needs(self):
        entries = self._entries()
        assert entries, "the escalation ledger is empty"
        for entry in entries:
            for field in self.REQUIRED:
                assert entry.get(field), f"{entry.get('id')} omits {field}"
            assert len(entry["dated"]) == 10 and entry["dated"].count("-") == 2

    def test_every_site_still_carries_the_defect(self):
        """The three files the breach is written across still say what it cites."""
        for entry in self._entries():
            for site in entry["site"]:
                source = (ROOT / site["file"]).read_text(encoding="utf-8")
                assert site["fragment"] in source, f"{entry['id']}: {site['file']}"

    def test_the_pinned_breach_carries_the_measurement_it_stands_on(self):
        """A pin is only a record if it says what was measured, where, and how it read.

        Each of the three commits is named by full sha and by subject -- the
        handle that survives a rebase -- and carries the exit code
        ``plan_audit`` returned on its tree.  The breach carries the four
        findings; a clean commit carries none, so "clean" is a recorded
        emptiness rather than an absent key.
        """
        (entry,) = self._entries()
        signature = entry["live_signature"]
        for handle, clean in self.MEASURED:
            block = signature[handle]
            assert len(block["commit"]) == 40, handle
            assert block["subject"], handle
            assert block["plan_audit_exit"] == (0 if clean else 1), handle
            assert (block["findings"] == []) is clean, handle
        assert len(signature["breached_in"]["findings"]) == 4

    def test_the_withdrawn_claim_is_quoted_and_marked_false(self):
        """The receipt may not paraphrase the sentence it calls false."""
        (entry,) = self._entries()
        signature = entry["live_signature"]
        assert signature["commit_body_claim_is_true"] is False
        assert signature["withdrawn_word"] in signature["commit_body_claim"]


# ---------------------------------------------------------------------------
# Phase 4 S7 — the two fields the migration lane writes on the declaration
# ---------------------------------------------------------------------------


def test_every_half_tags_exactly_the_engine_it_runs_on():
    """D-62's "one tag per (mechanic, engine)", read off the live registry.

    A tag says what *this* half's numbers mean.  A half carrying a tag for
    the other engine would be one side of a split mechanic declaring what the
    other side's number is worth, which is the shape of the sentence — "the
    holder's pair engine already prices its own amp" — that this campaign
    exists because nobody could check.
    """
    for mechanic, capability in ts.CAPABILITIES.items():
        assert set(capability.view_tags) == {capability.engine}, mechanic
        assert all(isinstance(tag, ViewTag) for tag in capability.view_tags.values())


@pytest.mark.parametrize(
    "overrides, message",
    [
        (
            {"pairing": ts.Pairing.PAIRED, "pair_of": "abyssal_mask.magic_amp"},
            "there is no default to inherit",
        ),
        (
            {"holder_stacking": ts.HolderStacking.PER_HOLDER},
            "only a dual-sided mechanic",
        ),
        (
            {"view_tags": MappingProxyType({ts.Engine.PAIR: ViewTag.APPLIED})},
            "tags the engine it runs on",
        ),
    ],
)
def test_the_two_phase_four_fields_reject_their_own_defects(overrides, message):
    """Both directions of D-66, plus the tag rule, each with a red.

    A dual-sided declaration that omits ``holder_stacking`` must fail to
    construct rather than inherit a guess; a solo one that carries a value
    nobody reads must fail too, because a value nobody reads is a value that
    can be wrong for a whole release without a symptom.
    """
    capability = _capability(**overrides)
    with pytest.raises(ts.TriggerRegistryError, match=message):
        ts._validate_view_semantics(capability.mechanic, capability)


def test_holder_stacking_is_declared_exactly_on_the_dual_sided_mechanics():
    """The fifty-four, by name, with the value each one declares.

    Pinned rather than derived: D-66's whole point is that the answer is a
    per-mechanic fact, so a test that recomputed it from some property of the
    row would be the second answer the field exists to prevent.  Abyssal Mask
    is the aura; every other row is per-holder, and two of them carry an
    unanswered ``[H]`` id rather than a ruling.

    Shadowflame's Cinderbloom is per-holder for a reason worth stating,
    because it is the one row that arms nothing: its bonus rides its own
    holder's damage events, so two holders amplify two disjoint sets of
    packets and their contributions can never be the same one counted twice.
    ``PER_HOLDER`` is that fact declared, not a default it fell through to —
    the field has none.

    The six item actives, the eight cast-triggered procs, the eleven damaging
    charged strikes, the eight on-hit strikes and the seven periodic cadences
    joined on 2026-08-16, when ``active_cast``, ``cast_proc``,
    ``charged_strike``, ``on_hit_strike`` and ``periodic`` retired off the pair
    engine, and on 2026-08-17 the seven spellblades with ``spellblade`` and
    Wind's Fury with ``secondary_target``, the last of the fourteen.  Their answer is per-holder for the same reason and one step more
    plainly: each one's walk half prices *its own holder's* packet, so two
    roster members holding one item pay two packets and an aura key would
    silently drop the second — which is the incident's own shape mandated by
    a rule.
    """
    declared = {
        mechanic: capability.holder_stacking.value
        for mechanic, capability in ts.CAPABILITIES.items()
        if capability.holder_stacking is not None
    }
    assert declared == {
        "abyssal_mask.unmake": "idempotent_aura",
        "bastionbreaker.shaped_charge": "per_holder",
        "black_cleaver.carve": "per_holder",
        "bamis_cinder.continuous_aura": "per_holder",
        "blade_of_the_ruined_king.on_hit": "per_holder",
        "blackfire_torch.refreshed_burn": "per_holder",
        "bloodletters_curse.vile_decay": "per_holder",
        "bloodsong.expose_weakness": "per_holder",
        "bloodsong.spellblade": "per_holder",
        "dead_mans_plate.empowered_hit": "per_holder",
        "dusk_and_dawn.spellblade": "per_holder",
        "eclipse.proc": "per_holder",
        "essence_reaver.spellblade": "per_holder",
        "fated_ashes.refreshed_burn": "per_holder",
        "fiendhunter_bolts.empowered_autos": "per_holder",
        "heartsteel.empowered_hit": "per_holder",
        "hextech_alternator.proc": "per_holder",
        "guinsoos_rageblade.on_hit": "per_holder",
        "hextech_gunblade.active": "per_holder",
        "hextech_rocketbelt.active": "per_holder",
        "hullbreaker.repeating_strike": "per_holder",
        "imperial_mandate.command": "per_holder",
        "iceborn_gauntlet.spellblade": "per_holder",
        "hollow_radiance.continuous_aura": "per_holder",
        "kraken_slayer.repeating_strike": "per_holder",
        "liandrys_torment.refreshed_burn": "per_holder",
        "lich_bane.spellblade": "per_holder",
        "ludens_echo.proc": "per_holder",
        "malignance.ultimate_proc": "per_holder",
        "muramana.on_hit": "per_holder",
        "nashors_tooth.on_hit": "per_holder",
        "profane_hydra.active": "per_holder",
        "rapid_firecannon.empowered_hit": "per_holder",
        "ravenous_hydra.active": "per_holder",
        "recurve_bow.on_hit": "per_holder",
        "runaans_hurricane.secondary_target": "per_holder",
        "scouts_slingshot.proc": "per_holder",
        "shadowflame.cinderbloom": "per_holder",
        "sheen.spellblade": "per_holder",
        "statikk_shiv.empowered_hit": "per_holder",
        "stormrazor.empowered_hit": "per_holder",
        "stormsurge.proc": "per_holder",
        "sunfire_aegis.continuous_aura": "per_holder",
        "stridebreaker.active": "per_holder",
        "terminus.on_hit": "per_holder",
        "titanic_hydra.on_hit": "per_holder",
        "trinity_force.spellblade": "per_holder",
        "tiamat.active": "per_holder",
        "umbral_glaive.empowered_hit": "per_holder",
        "unending_despair.fixed_interval": "per_holder",
        "voltaic_cyclosword.empowered_hit": "per_holder",
        "wits_end.on_hit": "per_holder",
        "zazzaks_realmspike.proc": "per_holder",
        "zekes_convergence.ultimate_proc": "per_holder",
    }


def test_a_rider_stamp_naming_no_live_predicate_rule_is_a_pairing_defect():
    """A8's rider branch has a red it can reproduce on demand.

    A rider-delivered half is resolved against the declaration rather than
    against a source literal, and a resolution that could not fail would be
    the "prose nothing checks" shape one layer over.
    """
    landed = ts.CAPABILITIES["shadowflame.cinderbloom"]
    misstamped = replace(landed, packet_source=ts.RiderDelivery("shadowflame.ashes"))
    defects = pairing_defects(
        {**ts.CAPABILITIES, "shadowflame.cinderbloom": misstamped}
    )
    assert any("names no declared live-predicate rule" in defect for defect in defects)


def test_the_three_held_authority_moves_name_their_blocking_human_decision():
    """Command, Carve and Vile Decay carry an ``[H]`` id, not a guess.

    Phase 4 declares seven authority moves and lands four.  The other three
    are blocked on decisions a machine may not make, and the campaign's rule
    is that a deferral is *written down* where the declaration lives — a row
    that simply kept its old authority with no explanation is
    indistinguishable from a row nobody looked at.
    """
    source = (SRC / "calculator/trigger_stream.py").read_text("utf-8")
    for mechanic, marker in (
        ("imperial_mandate.command", "# H2"),
        ("black_cleaver.carve", "# H1"),
        ("bloodletters_curse.vile_decay", "# H1"),
    ):
        row = source.index(f'"{mechanic}"')
        preamble = source[max(0, row - 700) : row]
        assert marker in preamble, mechanic
        assert ts.CAPABILITIES[mechanic].authority is Authority.SPLIT


def test_every_compiled_rune_declares_exactly_one_capability():
    """The rune half of D-36's non-item owners, joined to its own table.

    ``trigger_stream`` is a data-free leaf (D-35) and ``rune_effects`` reads
    ``data/runes.json`` at import, so the names are spelled in the
    declaration rather than derived from the compiler table.  The join that
    keeps the two spellings equal therefore lives here — the same place the
    item-name projections are pinned — and a rune compiled without a
    capability (or the reverse) fails here rather than in review.
    """
    # pylint: disable-next=import-outside-toplevel
    from src.calculator import rune_effects

    declared = {
        capability.owner.name: capability
        for capability in ts.CAPABILITIES.values()
        if isinstance(capability.owner, ts.RuneOwner)
    }
    assert set(declared) == set(rune_effects._compilers())
    for name, capability in declared.items():
        assert capability.engine is ts.Engine.PAIR, name
        assert capability.authority is Authority.PAIR_ONLY, name
        assert capability.impl == "rune_effects.resolve_rune", name
