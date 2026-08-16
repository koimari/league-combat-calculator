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


def static_holder_amp_fields() -> tuple[str, ...]:
    """Each static holder amp, spelled the way the pair engine's state holds it.

    Read off :class:`~src.calculator.interpreters.delta_amp.StaticHolderAmps` —
    its float members are the amps and its string members name their owners —
    so a fourth amp arrives in this census already named, on the commit that
    declares it, instead of being discovered by whoever next re-prices.
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
    amp declared and never folded would be a term that exists and does not
    reach the packet, which is the deletion Amendment M, Ruling 1 forbids
    wearing a green gate.
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


def unfolded_amps() -> tuple[str, ...]:
    """Static holder amps the walk's own composition does not deliver."""
    return tuple(
        amp for amp in static_holder_amp_fields() if amp not in amps_the_walk_folds()
    )


def uncovered(sites: Sequence[Site]) -> tuple[Site, ...]:
    """Every enumerated site no pricing-stage term carries to the walk."""
    return tuple(site for site in sites if site.coverage() == "UNCOVERED")


def report(sites: Sequence[Site]) -> dict[str, Any]:
    """The census as one JSON object."""
    return {
        "jurisdiction": PAIR_ENGINE,
        "static_holder_amps": list(static_holder_amp_fields()),
        "amps_the_walk_folds": list(amps_the_walk_folds()),
        "unfolded_amps": list(unfolded_amps()),
        "sites": [site.as_row() for site in sites],
        "uncovered": [site.function for site in uncovered(sites)],
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
    if args.json:
        print(json.dumps(report(sites), indent=1, sort_keys=True))
        return 0
    open_sites = uncovered(sites)
    unfolded = unfolded_amps()
    print(
        f"term census over {PAIR_ENGINE}: {len(sites)} post-authoring "
        f"packet-mutation site(s), {len(open_sites)} uncovered, "
        f"{len(static_holder_amp_fields())} static holder amp(s), "
        f"{len(unfolded)} unfolded"
    )
    for site in open_sites:
        print(
            f"  UNCOVERED {site.function} (line {site.line}): re-prices "
            f"{', '.join(write.target for write in site.writes)} and keeps no "
            "declaration in step"
        )
    for amp in unfolded:
        print(
            f"  UNFOLDED {amp}: declared by StaticHolderAmps, not folded by factor_for"
        )
    if args.check and (open_sites or unfolded):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())
