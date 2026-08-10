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
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

from src.calculator import trigger_stream as ts
from src.calculator.ability_spec import (
    CC_KIND_VOCABULARY,
    IMMOBILIZING_CC_KINDS,
    Authority,
    Disposition,
)
from src.calculator.ability_spec import is_immobilizing_event as legacy_immobilizing
from src.calculator.item_support_effects import (
    EVENT_VIEW_SUPPORT_ITEMS,
    cross_participant_authorities,
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


def test_classification_agrees_with_the_vocabulary_it_replaces():
    """The bus predicate answers exactly what ``ability_spec``'s does.

    Pinned over the whole vocabulary plus the two legacy booleans, because
    P2b repoints four consumers onto the bus predicate and "the two sides of
    one trigger must never diverge" has to be a measurement, not a claim.
    """
    for kind in sorted(CC_KIND_VOCABULARY):
        row = _row(cc_kind=kind)
        assert ts.is_immobilizing_event(row) == legacy_immobilizing(row), kind
    for marker in ("immobilized", "hard_cc"):
        row = _row(**{marker: True})
        assert ts.is_immobilizing_event(row) == legacy_immobilizing(row) is True
    assert ts.is_immobilizing_event(_row(crowd_control=True)) is False
    assert legacy_immobilizing(_row(crowd_control=True)) is False


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


def test_the_derivation_lands_beside_the_live_legacy_set():
    """D-98's witness is the **imported** set, never a transcription of it."""
    assert ts.tuple_incapable_items() ^ EVENT_VIEW_SUPPORT_ITEMS == frozenset()


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


def test_the_bus_imports_exactly_one_intra_package_module():
    """``ability_spec`` and nothing else — the acyclicity argument."""
    tree = ast.parse((SRC / "calculator/trigger_stream.py").read_text("utf-8"))
    relative = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.level
    }
    assert relative == {"ability_spec"}


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


def test_a_paired_capability_with_no_packet_source_is_rejected(monkeypatch):
    """``PAIRED ⇒ packet_source`` — the packet is what the halves share."""
    broken = dict(ts.CAPABILITIES)
    broken["synthetic.mechanic"] = _capability(
        pairing=ts.Pairing.PAIRED,
        pair_of="abyssal_mask.magic_amp",
        packet_source=None,
    )
    monkeypatch.setattr(ts, "CAPABILITIES", broken)
    monkeypatch.setattr(ts, "_DECLARATIONS", tuple(broken.values()))
    with pytest.raises(ts.TriggerRegistryError, match="no packet_source"):
        ts._validate_registry()


# ---------------------------------------------------------------------------
# A1 — one ``cc_kind`` parser, allowlisted by (module, symbol)
# ---------------------------------------------------------------------------

# The live readers at P2a.  P2b repoints the four legacy symbols onto the bus
# and P2c deletes them, so this map shrinks to the one parser the phase's
# goal names; it is pinned here so each of those deletions is a visible,
# attributable edit rather than a silent one.
CC_KIND_READERS = {
    "src/calculator/ability_spec.py": frozenset({"is_immobilizing_event"}),
    "src/calculator/damage.py": frozenset(
        {"_fimbulwinter_event_coverage", "add_declared_events"}
    ),
    "src/calculator/item_support_effects.py": frozenset(
        {"_cc_triggers", "_fimbulwinter_trigger_kind"}
    ),
    "src/calculator/survival/actions.py": frozenset({"survival_action_from_event"}),
    "src/calculator/trigger_stream.py": frozenset({"_classify_cc"}),
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

# ``phase-2-trigger-bus.md``'s *Retired symbols*.  The value is the module
# that still defines the symbol at this commit; P2b/P2c empty this map, and
# an entry appearing anywhere else fails now.
RETIRED_SYMBOL_HOMES = {
    # ``is_immobilizing_event`` has two homes at P2a on purpose: D-98 lands
    # the derivation beside the symbol it replaces, and P2c deletes the
    # ``ability_spec`` one in a single-symbol diff that reverts cleanly.
    "is_immobilizing_event": [
        "src/calculator/ability_spec.py",
        "src/calculator/trigger_stream.py",
    ],
    "_CC_TRIGGER_KINDS": ["src/calculator/item_support_effects.py"],
    "_cc_triggers": ["src/calculator/item_support_effects.py"],
    "_fimbulwinter_trigger_kind": ["src/calculator/item_support_effects.py"],
    "_takedown_triggers": ["src/calculator/item_support_effects.py"],
    "_damage_triggers": ["src/calculator/item_support_effects.py"],
    "EVENT_SCAN_SUPPORT_ITEMS": ["src/calculator/item_support_effects.py"],
    "has_event_scan_support_items": ["src/calculator/item_support_effects.py"],
    "TAKEDOWN_SCAN_SUPPORT_ITEMS": ["src/calculator/item_support_effects.py"],
    "has_takedown_scan_support_items": ["src/calculator/item_support_effects.py"],
    "CC_TRIGGER_ITEMS": ["src/calculator/item_support_effects.py"],
    "DAMAGE_TRIGGER_ITEMS": ["src/calculator/item_support_effects.py"],
    "EVENT_VIEW_SUPPORT_ITEMS": ["src/calculator/item_support_effects.py"],
    "has_event_view_support_items": ["src/calculator/item_support_effects.py"],
    "cross_participant_authorities": ["src/calculator/item_support_effects.py"],
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
    """
    capabilities = capabilities or ts.CAPABILITIES
    sources = sources or live_sources()
    declared: dict[str, set[str]] = {}
    for capability in capabilities.values():
        if not isinstance(capability.owner, ts.ItemOwner):
            continue
        if capability.engine is not ts.Engine.WALK or capability.packet_source is None:
            continue
        declared.setdefault(capability.impl, set()).add(capability.owner.name)
    return {
        impl: (
            _guarded_names(_function_node(sources[_impl_path(impl)], impl)),
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
            '    if "Cull" in names:',
            '    if "Zhonya\'s Hourglass" in names:\n        pass\n'
            '    if "Cull" in names:',
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

# The occurrence sites at P2a, which P2c drives to empty.  Pinning them here
# is what makes each removal an attributable diff rather than a claim.
LEGACY_NAME_SET_SITES = {
    "EVENT_SCAN_SUPPORT_ITEMS": ["src/calculator/item_support_effects.py"],
    "TAKEDOWN_SCAN_SUPPORT_ITEMS": ["src/calculator/item_support_effects.py"],
    "CC_TRIGGER_ITEMS": ["src/calculator/item_support_effects.py"],
    "DAMAGE_TRIGGER_ITEMS": ["src/calculator/item_support_effects.py"],
    "EVENT_VIEW_SUPPORT_ITEMS": ["src/calculator/item_support_effects.py"],
    "has_event_scan_support_items": ["src/calculator/item_support_effects.py"],
    "has_takedown_scan_support_items": [
        "src/calculator/damage.py",
        "src/calculator/item_support_effects.py",
    ],
    "has_event_view_support_items": [
        "src/calculator/item_support_effects.py",
        "src/calculator/participant_timeline.py",
        "src/calculator/pipeline.py",
    ],
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


def test_a7_the_immobilize_vocabulary_has_one_literal_home():
    """A7 — the fourth re-typing of this set is what D-08 had to widen."""
    sites = immobilize_literal_sites()
    assert len(sites) == 1
    assert sites[0].startswith("src/calculator/ability_spec.py:")
    assert {"stun", "root"} <= IMMOBILIZING_CC_KINDS


def test_a7_has_a_permanent_injection_seam():
    """R-05: re-type the set anywhere and A7 goes red."""
    injected = _with(
        live_sources(),
        "src/calculator/economy.py",
        'HARD_CC = {"stun", "root", "snare"}\n',
    )
    assert len(immobilize_literal_sites(injected)) == 2


# ---------------------------------------------------------------------------
# A8 — pairing is declared, cited and resolvable
# ---------------------------------------------------------------------------


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
        text = sources.get(_impl_path(capability.impl), "")
        if capability.packet_source not in text:
            defects.append(
                f"{mechanic}: packet_source {capability.packet_source!r} is "
                f"absent from {capability.impl}"
            )
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
    """A8 — empty defect set, and the escape hatch itself is empty."""
    assert pairing_defects() == ()
    # Phase 2 creates no DivergenceReceipt; Phase 3 creates the one live
    # instance (Bloodsong) and Phase 4 retires it (D-92).
    assert dict(ts.DIVERGENCES) == {}


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


def test_the_coupled_producer_source_reads_the_capability_registry():
    """R-12 — the derivation lands beside the live set it replaces (D-98)."""
    from scripts.golden_snapshot import cross_participant_producers

    assert cross_participant_producers() == frozenset(cross_participant_authorities())


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


def except_projection_starvation_sites(
    sources: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    """Every ``except ProjectionStarvation`` clause in ``src/`` (D-25)."""
    sites = []
    for path, text in sorted((sources or live_sources()).items()):
        for node in ast.walk(ast.parse(text)):
            if not isinstance(node, ast.ExceptHandler) or node.type is None:
                continue
            names = [
                handled.id
                for handled in ast.walk(node.type)
                if isinstance(handled, ast.Name)
            ]
            if "ProjectionStarvation" in names:
                sites.append(path)
    return tuple(sites)


def test_exactly_one_projection_starvation_catch_exists():
    """D-25 — allowlisted by source assertion, and every other forbidden."""
    assert except_projection_starvation_sites() == ("src/app.py",)


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
    assert except_projection_starvation_sites(injected) == (
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
