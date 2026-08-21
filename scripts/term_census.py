"""Umbrella Amendment N, Ruling 2 — the term census, derived from source.

Twice now a family's retirement has been stopped by the same shape: a term the
pair engine applies to a packet and the from-declaration pricing stage does
not.  Amendment M found the first by tripping over it, Amendment N found the
second the same way, and a third would have been found the same way again.
Ruling 2 rules that terms shall not be discovered one halt at a time.

This is that census.  It enumerates every **post-authoring packet-mutation
site** in the pair engine — every site that changes what an already-authored
packet is worth — and asserts each is covered by a pricing-stage term or by a
ruled, dated exclusion.  It is derived from ``src/calculator/damage.py``'s own
syntax tree and never hand-listed, because a hand list is the thing that failed
twice.

**Re-pricing is a write derived from the value it replaces.**  That is the
predicate, and it is the census's one non-obvious idea.  Authoring a packet and
re-pricing one are both assignments to a ``damage`` or ``total_damage``
subscript, and no key spelling tells them apart; what tells them apart is where
the new value came from.  ``row["total_damage"] = float(row["total_damage"]) +
delta`` reads what was there and adjusts it, and so — transitively — does
``event["damage"] = new_damage`` where ``new_damage`` was computed from the
event's own damage.  ``row["total_damage"] = total_stored`` does not: that row
is being authored, whatever was in it before.  So the scan follows the value
backwards through the enclosing function's assignments and asks whether the
write depends on the thing it overwrites.

**The census owes two shapes, and the obvious one covers only its own term.**
The two re-pricing windows write a packet in place.  The holder's static amps
(umbrella Amendment M, Ruling 1) write nothing in place at all: they are
factors inside ``_mitigate``, ``_add_item_proc_damage`` and
``_mitigate_basic_attack_swing``, and a census keyed only on in-place writes
would enumerate Amendment N's term and silently miss Amendment M's.  So the
amp fold is enumerated as its own shape, and the amp fields it is enumerated
by are read from ``interpreters.delta_amp.StaticHolderAmps`` rather than typed
here — a fourth static holder amp reaches this census on the commit that
declares it.

**Coverage is derived too.**  A site that re-prices a packet is covered when it
keeps the declaration riding that packet in step, which is a call to the one
restatement home (``damage._restate_declaration`` or the positional carry
beside it) inside its own body.  A site whose writes only move a row's
aggregate, or only drop packets from a list, re-prices nothing and is covered
by that fact.  A site that folds a holder amp is covered by
``DeclaredPacket.holder_amp``, and the join is checked rather than asserted in
prose: every amp ``StaticHolderAmps`` declares must be one ``factor_for``
folds, so an amp the walk would not deliver fails here.

Anything else is **UNCOVERED**, and an uncovered site is a red gate: no further
family retires while the census shows one (Ruling 2).  Adding an exclusion is
not a lane's to do — Ruling 2 says a ruled, dated one recorded in the umbrella —
so the instrument reports the site and stops rather than growing a list.

**The predicate widens to authoring time** (umbrella Amendment R, Ruling 2,
2026-08-16).  Everything above ranges over what happens to a packet *after* it
is authored, and a third family was stopped by a term that is applied *while*
it is authored: a packet delivered as a basic-attack swing meets the target's
own defences inside the mitigation function that prices it, and no census in
the shape above can see one.  The green above was therefore truthful under the
old predicate and is recorded as truthful; what was missing was reach, not
honesty.  So the census additionally enumerates every term ``_mitigate`` and
``_mitigate_basic_attack_swing`` apply to a packet as they price it — target
side as well as holder side — derived from the same syntax tree, and asserts
each is carried by a pricing-stage term.

**A factor folds and a subtraction does not, and that is derived rather than
asserted.**  The fold is legitimate exactly when the term reaches the priced
number by multiplication alone: a pure factor on a linear mitigation composes
into the declared magnitude and prices to the same real number, so the walk
needs no term for it.  Anything else has to be *transported*, and is covered
only where ``survival.pricing.BasicAttackSwing`` declares a field of that
term's own name.  So the scan follows the value the mitigation carries,
closing it under multiplication only — ``reduced = damage * plating`` keeps
carrying it and ``per_hit = reduced / hits`` does not — and asks whether every
use of the term multiplies a carrier into another carrier.  Warden's Mail's
cap is the case that makes the distinction load-bearing: it is used in a
product, and the product is subtracted rather than carried, so it comes back
transported and its coverage is the field that transports it.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.calculator.interpreters.delta_amp import (  # noqa: E402  (path set above)
    StaticHolderAmps,
)
from src.calculator.item_behavior import DefenseField  # noqa: E402  (path set above)
from src.calculator.survival.pricing import (  # noqa: E402  (path set above)
    BasicAttackSwing,
)

#: The pair engine, which is the jurisdiction Ruling 2 names.  One module,
#: because "the pair engine" is one module: every step of a fight between the
#: ledger being authored and the result being published lives here.
PAIR_ENGINE = "src/calculator/damage.py"

#: The subscript keys that hold what a packet or a row is worth.  A write to
#: one of these is what "changes an already-authored packet's amount" means in
#: the tree's own spelling; ``damage_events`` is here because replacing a
#: packet list changes every amount in it at once.
PRICED_KEYS = ("damage", "total_damage", "damage_per_hit", "damage_events")

#: The one home a re-pricing site keeps its declaration in step through
#: (Amendment N, Ruling 1), and the positional carry beside it.  Coverage is a
#: call to one of these from inside the site's own body, so a site that
#: re-prices a packet and forgets is a finding rather than a review note.
RESTATEMENT_HOME = ("_restate_declaration", "_carry_declarations_onto_repriced_ticks")

#: How the fight state spells one of ``StaticHolderAmps``' amps.  The names are
#: derived, never listed: whatever float amps that type declares, the engine
#: holds under the same name with this suffix, and the census asserts the join
#: rather than trusting it.
AMP_FIELD_SUFFIX = "_amp"

#: The pair engine's two mitigation entry points — the functions that turn a
#: raw magnitude into what a packet is worth.  Named because Amendment R,
#: Ruling 2 names them, and checked for existence rather than assumed, so a
#: rename arrives here as a stop instead of as an empty enumeration.
MITIGATION_ENTRY_POINTS = ("_mitigate", "_mitigate_basic_attack_swing")

#: How the fight state spells a term the *target* brings to a packet.  The
#: suffix is joined against ``DefenseField``'s own vocabulary, so an attribute
#: that is not a declared defensive field is not a term any item can arm.
TARGET_FIELD_PREFIX = "target_"

#: The resolved-resistance object the mitigation reads a resistance off.  A
#: term census keyed on attribute names alone would have to list the two
#: resistances; keyed on the container, it reaches whatever third resistance
#: that object ever grows.
RESISTS_CONTAINER = "resists"


def static_holder_amp_fields() -> tuple[str, ...]:
    """Each static holder amp, spelled the way the pair engine's state holds it.

    Read off :class:`~src.calculator.interpreters.delta_amp.StaticHolderAmps`,
    whose float members are the amps, so a fourth arrives already named.
    """
    return tuple(
        f"{field.name}{AMP_FIELD_SUFFIX}"
        for field in fields(StaticHolderAmps)
        if isinstance(field.default, float)
    )


def amps_the_walk_folds() -> tuple[str, ...]:
    """Each amp ``StaticHolderAmps.factor_for`` actually multiplies into a packet.

    The walk-side half of the same join: the term ``DeclaredPacket.holder_amp``
    covers an amp only if the composition that produces it reads that amp.  An
    amp declared and never folded is a term that exists without reaching the
    packet, so it must not pass as covered.
    """
    tree = ast.parse(ast.unparse(_factor_for_source()))
    return tuple(
        sorted(
            {
                f"{node.attr}{AMP_FIELD_SUFFIX}"
                for node in ast.walk(tree)
                if isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "self"
                and f"{node.attr}{AMP_FIELD_SUFFIX}" in static_holder_amp_fields()
            }
        )
    )


def _factor_for_source() -> ast.AST:
    """`StaticHolderAmps.factor_for`'s own syntax tree."""
    module = ast.parse(
        (REPO_ROOT / "src" / "calculator" / "interpreters" / "delta_amp.py").read_text(
            encoding="utf-8"
        )
    )
    holder = next(
        node
        for node in ast.walk(module)
        if isinstance(node, ast.ClassDef) and node.name == StaticHolderAmps.__name__
    )
    return next(
        node
        for node in holder.body
        if isinstance(node, ast.FunctionDef) and node.name == "factor_for"
    )


#: A site's disposition, closed and ordered weakest-first.  A function's class
#: is the strongest disposition among its writes, because a function that
#: re-prices one packet and moves one row aggregate is a re-pricing site.
DISPOSITIONS = ("row_aggregate", "packet_removal", "packet_reprice")


@dataclass(frozen=True, slots=True)
class Write:
    """One assignment to a priced key, and what the scan made of it."""

    line: int
    target: str
    disposition: str


@dataclass(frozen=True, slots=True)
class Site:
    """One post-authoring packet-mutation site: a function, and why it is one."""

    function: str
    line: int
    shape: str
    disposition: str
    writes: tuple[Write, ...]
    amps: tuple[str, ...]
    restates: tuple[str, ...]

    def coverage(self) -> str:
        """Which pricing-stage term carries this site's effect to the walk."""
        if self.shape == "holder_amp_fold":
            return "term:DeclaredPacket.holder_amp"
        if self.disposition != "packet_reprice":
            return f"no_packet_is_re_priced:{self.disposition}"
        if self.restates:
            return "term:AuthoredDeclaration.kept_in_step"
        return "UNCOVERED"

    def as_row(self) -> dict[str, Any]:
        """This site as the JSON report states it."""
        return {
            "function": self.function,
            "line": self.line,
            "shape": self.shape,
            "disposition": self.disposition,
            "coverage": self.coverage(),
            "writes": [
                {"line": w.line, "target": w.target, "disposition": w.disposition}
                for w in self.writes
            ],
            "amps": list(self.amps),
            "restates": list(self.restates),
        }


@dataclass(frozen=True, slots=True)
class Term:
    """One authoring-time mitigation term, and how it reaches the price."""

    function: str
    line: int
    kind: str
    name: str
    application: str

    def coverage(self) -> str:
        """Which pricing-stage term carries this one to the walk."""
        if self.kind == "resistance":
            return "term:DeclaredPacket.effective_resistance"
        if self.kind == "holder_amp":
            return "term:DeclaredPacket.holder_amp"
        if self.application == "factor":
            return "term:folded_into_the_declared_magnitude"
        if self.name in BasicAttackSwing._fields:
            return f"term:BasicAttackSwing.{self.name}"
        return "UNCOVERED"

    def as_row(self) -> dict[str, Any]:
        """This term as the JSON report states it."""
        return {
            "function": self.function,
            "line": self.line,
            "kind": self.kind,
            "name": self.name,
            "application": self.application,
            "coverage": self.coverage(),
        }


def _targets(node: ast.AST) -> list[ast.expr]:
    """Every assignment target of one statement, whatever its assignment form."""
    if isinstance(node, ast.Assign):
        return list(node.targets)
    if isinstance(node, (ast.AugAssign, ast.AnnAssign)):
        return [node.target]
    return []


def _priced_key(target: ast.expr) -> str | None:
    """The priced key this target writes, or ``None`` if it writes none."""
    if (
        isinstance(target, ast.Subscript)
        and isinstance(target.slice, ast.Constant)
        and target.slice.value in PRICED_KEYS
    ):
        return str(target.slice.value)
    return None


def _derivations(function: ast.AST) -> dict[str, list[str]]:
    """Each local name, mapped to the source text of what it was bound from.

    A name may be bound more than once and every binding is kept: the scan is
    asking whether a value *could* have come from the thing it overwrites, and
    dropping a binding would answer no on a function that re-prices in a
    branch.
    """
    bound: dict[str, list[str]] = {}

    def bind(target: ast.expr, value: ast.AST | None) -> None:
        if value is None:
            return
        if isinstance(target, ast.Name):
            bound.setdefault(target.id, []).append(ast.unparse(value))
        elif isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                bind(element, value)

    for node in ast.walk(function):
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            for target in _targets(node):
                bind(target, node.value)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            bind(node.target, node.iter)
        elif isinstance(node, (ast.comprehension,)):
            bind(node.target, node.iter)
        elif isinstance(node, ast.withitem) and node.optional_vars is not None:
            bind(node.optional_vars, node.context_expr)
    return bound


def _is_priced_read(node: ast.AST, container: str) -> bool:
    """Whether one expression node reads a priced key off *container*.

    Both spellings the engine uses, and only those: ``row["total_damage"]``
    and ``row.get("damage_events")``.  Passing a row whole to a helper is not
    a priced read — a function handed a row to compute from is authoring one,
    not re-pricing it — which is the distinction that keeps the census's
    subject to sites that consulted what was already there.
    """
    if (
        isinstance(node, ast.Subscript)
        and isinstance(node.slice, ast.Constant)
        and node.slice.value in PRICED_KEYS
    ):
        return ast.unparse(node.value) == container
    if not isinstance(node, ast.Call) or not node.args:
        return False
    getter = node.func
    if not isinstance(getter, ast.Attribute) or getter.attr != "get":
        return False
    key = node.args[0]
    if not isinstance(key, ast.Constant) or key.value not in PRICED_KEYS:
        return False
    return ast.unparse(getter.value) == container


def _reads_the_price(
    expression: str, container: str, bound: Mapping[str, list[str]]
) -> bool:
    """Whether *expression* depends, however indirectly, on *container*'s price.

    The transitive question the predicate rests on: a write is a **re-pricing**
    when the value assigned was derived from what the row or packet was
    already worth, and an **authoring** when it was not.  Walked over the
    enclosing function's own bindings, with a visited set because a fight's
    arithmetic loops.
    """
    seen: set[str] = set()
    frontier = [expression]
    while frontier:
        text = frontier.pop()
        if text in seen:
            continue
        seen.add(text)
        try:
            tree = ast.parse(text, mode="eval")
        except SyntaxError:  # pragma: no cover - unparse round-trips
            continue
        for node in ast.walk(tree):
            if _is_priced_read(node, container):
                return True
            if isinstance(node, ast.Name):
                frontier.extend(bound.get(node.id, ()))
    return False


def _authored_here(function: ast.AST) -> frozenset[str]:
    """Every container this function gave its value to, as source text.

    A row or a packet list built from a display in the same body is one this
    function authored, whatever the breakdown held under that key before, so
    a later write into it is part of the authoring rather than a re-pricing
    of somebody else's packet.
    """
    displays = (ast.Dict, ast.List, ast.DictComp, ast.ListComp)
    authored: set[str] = set()
    for node in ast.walk(function):
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(
            node.value, displays
        ):
            authored.update(ast.unparse(target) for target in _targets(node))
    return frozenset(authored)


def _disposition(
    node: ast.AST,
    target: ast.Subscript,
    key: str,
    bound: Mapping[str, list[str]],
    authored: frozenset[str],
) -> str | None:
    """What one write to a priced key does to the packets under it.

    ``None`` is an authoring write — a row or an event being given its value
    for the first time — which is not this census's subject.
    """
    container = ast.unparse(target.value)
    if container in authored or _base_name(target.value) in authored:
        return None
    value = getattr(node, "value", None)
    derived = isinstance(node, ast.AugAssign) or (
        value is not None and _reads_the_price(ast.unparse(value), container, bound)
    )
    if not derived:
        return None
    if key == "damage_events":
        # A slice of the list it replaces removes packets; anything else puts
        # different packets there, which re-prices every one of them at once.
        if isinstance(value, ast.Subscript) and isinstance(value.slice, ast.Slice):
            return "packet_removal"
        return "packet_reprice"
    if key == "damage":
        return "packet_reprice"
    return "row_aggregate"


def _base_name(node: ast.expr) -> str:
    """The name a subscript chain is rooted at, for the authored-here test."""
    while isinstance(node, ast.Subscript):
        node = node.value
    return node.id if isinstance(node, ast.Name) else ast.unparse(node)


def _function_defs(tree: ast.AST) -> Iterable[ast.AST]:
    """Every function in the module, nested ones included."""
    return (
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    )


def census(source: str | None = None) -> tuple[Site, ...]:
    """Every post-authoring packet-mutation site in the pair engine.

    *source* is the seam the R-05 negative drives: a scan that cannot be made
    to report something is indistinguishable from a scan that found nothing.
    """
    text = (
        (REPO_ROOT / PAIR_ENGINE).read_text(encoding="utf-8")
        if source is None
        else source
    )
    tree = ast.parse(text)
    amp_fields = frozenset(static_holder_amp_fields())
    sites: list[Site] = []
    for function in _function_defs(tree):
        bound = _derivations(function)
        authored = _authored_here(function)
        writes: list[Write] = []
        for node in ast.walk(function):
            for target in _targets(node):
                key = _priced_key(target)
                if key is None:
                    continue
                disposition = _disposition(node, target, key, bound, authored)
                if disposition is not None:
                    writes.append(Write(node.lineno, ast.unparse(target), disposition))
        amps = tuple(
            sorted(
                {
                    node.attr
                    for node in ast.walk(function)
                    if isinstance(node, ast.Attribute) and node.attr in amp_fields
                }
                | {
                    node.arg
                    for node in ast.walk(function)
                    if isinstance(node, ast.arg) and node.arg in amp_fields
                }
            )
        )
        if not writes and not amps:
            continue
        restates = tuple(
            sorted(
                {
                    node.func.id
                    for node in ast.walk(function)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id in RESTATEMENT_HOME
                }
            )
        )
        disposition = max(
            (write.disposition for write in writes),
            key=DISPOSITIONS.index,
            default="",
        )
        sites.append(
            Site(
                function=function.name,
                line=function.lineno,
                shape="in_place_reprice" if writes else "holder_amp_fold",
                disposition=disposition,
                writes=tuple(sorted(writes, key=lambda w: w.line)),
                amps=amps,
                restates=restates,
            )
        )
    return tuple(sorted(sites, key=lambda site: site.line))


def _reached_from(tree: ast.AST, entry_points: Sequence[str]) -> dict[str, ast.AST]:
    """Each named entry point and every module function it calls, transitively.

    The terms a mitigation applies are spread across the entry point and the
    helpers it calls, so a term added to a fourth helper has to arrive here on
    the commit that adds it rather than on the commit somebody notices.
    """
    defined = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    reached: dict[str, ast.AST] = {}
    pending = [name for name in entry_points if name in defined]
    while pending:
        name = pending.pop()
        if name in reached:
            continue
        reached[name] = defined[name]
        pending.extend(
            node.func.id
            for node in ast.walk(defined[name])
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in defined
        )
    return reached


def _term_of(node: ast.AST, amp_fields: frozenset[str]) -> tuple[str, str, str] | None:
    """The ``(kind, name, spelling)`` of the term a node reads, or ``None``.

    Three kinds and no fourth: the resistance the packet is mitigated at, one
    of the holder's own static amps, and a defensive field the *target*
    brings.  Each is recognised by the tree's own vocabulary rather than by a
    name typed here — the resists container, ``StaticHolderAmps``' declared
    amps, and ``DefenseField``'s values behind the fight state's prefix.

    ``spelling`` is how the term's *uses* read, which is not always how its
    declaration does: an amp arrives at ``_mitigate`` as a parameter and is
    applied as a bare name, so classifying the parameter by its own text
    would find no use of it at all.
    """
    defence_fields = {field.value for field in DefenseField}
    if isinstance(node, ast.arg):
        return ("holder_amp", node.arg, node.arg) if node.arg in amp_fields else None
    if not isinstance(node, ast.Attribute):
        return None
    if ast.unparse(node.value).split(".")[-1] == RESISTS_CONTAINER:
        return "resistance", node.attr, ast.unparse(node)
    if node.attr in amp_fields:
        return "holder_amp", node.attr, ast.unparse(node)
    if node.attr.startswith(TARGET_FIELD_PREFIX):
        field = node.attr[len(TARGET_FIELD_PREFIX) :]
        if field in defence_fields:
            return "target_term", field, ast.unparse(node)
    return None


def _carriers(function: ast.AST) -> frozenset[str]:
    """Every local name that still carries the value being mitigated.

    Seeded at the function's own arguments — the raw or already-mitigated
    magnitude arrives as one — and closed under **multiplication only**, plus
    the calls the magnitude passes through.  Multiplication only is the whole
    content: a name bound to ``carrier * factor`` is still the priced number
    scaled, and a name bound to ``carrier / hits`` is a share of it that the
    engine then subtracts, so the two must not be one class.
    """
    carriers = {
        argument.arg
        for argument in getattr(function, "args", ast.arguments()).args
        if argument.arg not in ("self", "state")
    }
    for _ in range(len(list(ast.walk(function)))):
        grown = False
        for node in ast.walk(function):
            if isinstance(node, ast.AugAssign):
                if not isinstance(node.op, ast.Mult):
                    continue
                names = {ast.unparse(node.target)}
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                if not _carries(node.value, carriers):
                    continue
                names = {ast.unparse(target) for target in _targets(node)}
            else:
                continue
            if not names <= carriers:
                carriers |= names
                grown = True
        if not grown:
            break
    return frozenset(carriers)


def _carries(value: ast.AST | None, carriers: frozenset[str] | set[str]) -> bool:
    """Whether one expression still carries the value being mitigated.

    A carrier name, a product one of whose operands carries it, or a call one
    of whose arguments does — the mitigation formula and the two clamps the
    engine wraps a priced number in are all calls, and a value that passes
    through one is the same value.
    """
    if value is None:
        return False
    if isinstance(value, ast.Name):
        return value.id in carriers
    if isinstance(value, ast.BinOp) and isinstance(value.op, ast.Mult):
        return _carries(value.left, carriers) or _carries(value.right, carriers)
    if isinstance(value, ast.Call):
        return any(_carries(argument, carriers) for argument in value.args)
    return False


def _application_of(function: ast.AST, spelling: str, carriers: frozenset[str]) -> str:
    """Whether one term's every use multiplies a carrier into another carrier.

    ``factor`` is the folding case Ruling 1 rules composes into the declared
    magnitude; anything else has to be transported on the declaration.  Asked
    over *every* use of the term rather than over one, because a value used
    once as a factor and once as a threshold is not a factor.

    Deliberately conservative, and the conservatism runs the safe way: binding
    a term to a local name is a use that is not a multiplication, so a term
    read into a variable before it is applied comes back ``transported`` and
    is red unless the pricing stage transports it.  A foldable term written
    that way is a stop asking for a ruling, which is what Ruling 2 asks the
    instrument to do; the reverse mistake would be a term called foldable
    because one of its uses happened to be a product.
    """
    uses = folds = 0
    for node in ast.walk(function):
        if isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Mult):
            if ast.unparse(node.value) == spelling:
                uses += 1
                folds += ast.unparse(node.target) in carriers
            continue
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
            sides = (ast.unparse(node.left), ast.unparse(node.right))
            if spelling in sides:
                uses += 1
                folds += _carries(node.left, carriers) or _carries(node.right, carriers)
                continue
        for child in ast.iter_child_nodes(node):
            if ast.unparse(child) == spelling and not isinstance(
                node, (ast.BinOp, ast.AugAssign)
            ):
                uses += 1
    return "factor" if uses and uses == folds else "transported"


def authoring_time_terms(source: str | None = None) -> tuple[Term, ...]:
    """Every term the pair engine's mitigation applies to a packet it prices.

    Umbrella Amendment R, Ruling 2's widened predicate: the terms applied
    *while* the packet is being authored, which no census over post-authoring
    mutation can reach.  Same ``source`` seam as :func:`census`, for the same
    reason — a scan that cannot be made to report something is
    indistinguishable from a scan that found nothing.
    """
    text = (
        (REPO_ROOT / PAIR_ENGINE).read_text(encoding="utf-8")
        if source is None
        else source
    )
    tree = ast.parse(text)
    amp_fields = frozenset(static_holder_amp_fields())
    terms: dict[tuple[str, str, str], Term] = {}
    for name, function in _reached_from(tree, MITIGATION_ENTRY_POINTS).items():
        carriers = _carriers(function)
        for node in ast.walk(function):
            found = _term_of(node, amp_fields)
            if found is None:
                continue
            kind, term_name, spelling = found
            key = (name, kind, term_name)
            if key in terms:
                continue
            terms[key] = Term(
                function=name,
                line=getattr(node, "lineno", function.lineno),
                kind=kind,
                name=term_name,
                application=(
                    "transported"
                    if kind == "resistance"
                    else _application_of(function, spelling, carriers)
                ),
            )
    return tuple(sorted(terms.values(), key=lambda term: (term.function, term.name)))


def uncovered_terms(terms: Sequence[Term]) -> tuple[Term, ...]:
    """Every authoring-time term no pricing-stage term carries to the walk."""
    return tuple(term for term in terms if term.coverage() == "UNCOVERED")


def unfolded_amps() -> tuple[str, ...]:
    """Static holder amps the walk's own composition does not deliver."""
    return tuple(
        amp for amp in static_holder_amp_fields() if amp not in amps_the_walk_folds()
    )


def uncovered(sites: Sequence[Site]) -> tuple[Site, ...]:
    """Every enumerated site no pricing-stage term carries to the walk."""
    return tuple(site for site in sites if site.coverage() == "UNCOVERED")


def report(
    sites: Sequence[Site], terms: Sequence[Term] | None = None
) -> dict[str, Any]:
    """The census as one JSON object, both predicates in it."""
    terms = authoring_time_terms() if terms is None else terms
    return {
        "jurisdiction": PAIR_ENGINE,
        "static_holder_amps": list(static_holder_amp_fields()),
        "amps_the_walk_folds": list(amps_the_walk_folds()),
        "unfolded_amps": list(unfolded_amps()),
        "sites": [site.as_row() for site in sites],
        "uncovered": [site.function for site in uncovered(sites)],
        "authoring_time_terms": [term.as_row() for term in terms],
        "uncovered_terms": [
            f"{term.function}:{term.name}" for term in uncovered_terms(terms)
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Run the census; ``--check`` fails on an uncovered site or unfolded amp."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print the full census")
    parser.add_argument(
        "--check", action="store_true", help="exit non-zero on an uncovered site"
    )
    args = parser.parse_args(argv)
    sites = census()
    terms = authoring_time_terms()
    if args.json:
        print(json.dumps(report(sites, terms), indent=1, sort_keys=True))
        return 0
    open_sites = uncovered(sites)
    open_terms = uncovered_terms(terms)
    unfolded = unfolded_amps()
    print(
        f"term census over {PAIR_ENGINE}: {len(sites)} post-authoring "
        f"packet-mutation site(s), {len(open_sites)} uncovered, "
        f"{len(terms)} authoring-time mitigation term(s), "
        f"{len(open_terms)} uncovered, "
        f"{len(static_holder_amp_fields())} static holder amp(s), "
        f"{len(unfolded)} unfolded"
    )
    for site in open_sites:
        print(
            f"  UNCOVERED {site.function} (line {site.line}): re-prices "
            f"{', '.join(write.target for write in site.writes)} and keeps no "
            "declaration in step"
        )
    for term in open_terms:
        print(
            f"  UNCOVERED TERM {term.name} in {term.function} (line {term.line}): "
            f"applied {term.application} while the packet is priced, and no "
            "pricing-stage term transports it"
        )
    for amp in unfolded:
        print(
            f"  UNFOLDED {amp}: declared by StaticHolderAmps, not folded by factor_for"
        )
    if args.check and (open_sites or open_terms or unfolded):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())
