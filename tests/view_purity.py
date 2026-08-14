"""The AST reading of Phase 4 criterion 3: a view re-runs no arithmetic.

The criterion is deliberately not path-scoped.  "No module under
``program/views/`` performs arithmetic" is satisfied by moving the sum into
``program/view_math.py`` and calling it, so the criterion says **nor any
``src/`` function in a view's call graph** -- and a check that only walked
the five view modules would pass on exactly the arrangement the sentence was
written to forbid.  So this module resolves the call graph and walks that.

**The counting rule, stated so the number is reproducible** (R-29):

*Roots.*  The five view front doors -- ``score``, ``breakdown``,
``survival``, ``tdd``, ``receipt`` -- plus every other module-level function
defined under ``src/calculator/program/views/``, because a view module's
helpers are the view.

*Edges.*  A call resolves to a ``src/calculator`` function when its callee is

1. a bare name bound in the calling module to a module-level ``def`` in that
   module, or imported by ``from <src.calculator module> import <name>``;
2. ``<module>.<name>`` where ``<module>`` is a module imported from
   ``src/calculator`` and defines ``<name>`` at module level;
3. ``<anything>.<name>`` where any class under ``src/calculator`` defines a
   method spelled ``<name>``.  **Every** owner is followed, not one: a
   purity check must over-approximate, because following an extra owner can
   only add a site to the walk while following none can hide one.  The one
   exception is ``PROTOCOL_ATTRIBUTES`` below -- a call spelled ``x.get(...)``
   in a view is a dict read, and chasing it into every class that happens to
   define a ``get`` resolves a builtin to unrelated arithmetic.

A class name resolves to that class's own ``__init__``/``__post_init__``, so
constructing a record is walked like any other call.

*Unresolved callees are not ignored.*  Every callee name the rules above do
not resolve is reported, and the suite asserts that set is exactly a
committed list of builtins and protocol methods.  A frontier that is
enumerated is a frontier a reader can audit; one that is merely absent is
the shape this campaign exists to remove.

*Arithmetic.*  A binary ``+ - * / // % ** @``, an augmented assignment with
one of those, a unary minus or plus on anything but a literal, or a call to
one of the folding builtins ``sum``/``min``/``max``/``abs``.  Rounding is
**not** arithmetic: D-71 rules it presentation, it is already gated to the
one registry by its own test, and every published digit count comes from
there.  String and path building is not arithmetic either, and needs no
exemption -- the views spell paths with f-strings, which are not ``BinOp``.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "calculator"

#: The dotted name of the package whose functions are the walk's roots.
VIEWS_PACKAGE = "program.views"

#: The arithmetic operators.  Rounding is presentation and is gated
#: elsewhere; concatenation of strings would be caught here too, which is
#: why the views build paths with f-strings rather than with ``+``.
ARITHMETIC = (
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.MatMult,
)

#: Builtins that fold several numbers into one.  A view calling any of them
#: is adding, whoever wrote the loop.
FOLD_BUILTINS = frozenset({"sum", "min", "max", "abs"})

#: Attribute spellings the mapping and sequence protocols own.  ``x.get(...)``
#: in a view is a dict read, and following it into every ``src/`` class that
#: happens to define a method of that name resolves a builtin to unrelated
#: arithmetic -- ``value_ref``'s own ``get`` is the live example.  Named as a
#: closed list rather than guessed at, so the one way the walk stops early is
#: a rule a reader can check.
PROTOCOL_ATTRIBUTES = frozenset(
    {
        "append",
        "clear",
        "copy",
        "count",
        "extend",
        "get",
        "index",
        "insert",
        "items",
        "keys",
        "pop",
        "remove",
        "setdefault",
        "sort",
        "update",
        "values",
    }
)

#: Callee spellings the resolver deliberately does not follow, each because
#: it is not a ``src/calculator`` function: a builtin, a mapping/sequence
#: protocol method, or a stdlib constructor.  Asserted equal to what the
#: scan actually leaves unresolved, so the boundary of the check is a
#: committed list rather than whatever the resolver happened to miss.
UNRESOLVED_ALLOWED = frozenset(
    {
        # A call whose callee is itself an expression.  The one live case is
        # ``ability_spec``'s lazily-fetched ``ProjectionStarvation`` class,
        # raised as ``_projection_starvation()(...)``.
        "<expression>",
        "ValueError",
        # ``precision.sum_plan``'s fail-closed refusal of an undeclared
        # panel, reached since S10 gave the receipt's three panels a
        # ``SumPlan`` (D-65).  A raise over panel *names*, not arithmetic.
        "KeyError",
        "_set",  # a bound ``dict.__setitem__``, not a method this package has
        # ``Withheld.__post_init__``'s receipt check, reached since S10 made
        # ``published_quantity`` rebuild a payload's quantity from its own
        # dispositions entry.  Both are builtins over strings, not arithmetic.
        "all",
        "strip",
        "append",
        "bool",
        "dict",
        "enumerate",
        "float",
        "get",
        "getattr",
        "int",
        "isinstance",
        "items",
        "len",
        "list",
        "range",
        "round",
        "sorted",
        "str",
        # The builtin proxy, not a method this package defines.  Only the
        # ``super()`` call itself stops here: the delegation around it --
        # ``super().block(...)`` -- is an attribute call, so rule 3 follows it
        # into every class defining that name, ``LeafWriter.block`` included.
        "super",
        "tuple",
    }
)


@dataclass(frozen=True, slots=True)
class Impurity:
    """One arithmetic expression inside a view or its call graph."""

    module: str
    function: str
    lineno: int
    what: str

    def __str__(self) -> str:
        """The line a failing assertion prints."""
        return f"{self.module}:{self.lineno} {self.function}() -> {self.what}"


def _sources(overrides: Mapping[str, str] | None = None) -> dict[str, str]:
    """Every ``src/calculator`` module's text, keyed by dotted module name.

    ``overrides`` is the seam R-05 asks a new gate to ship with: a fixture
    hands doctored text for one module and the check fails on command,
    rather than the campaign asserting that it once failed during
    development.
    """
    texts: dict[str, str] = {}
    for path in sorted(SRC.rglob("*.py")):
        parts = list(path.relative_to(SRC).with_suffix("").parts)
        if parts[-1] == "__init__":
            # A package's ``__init__`` *is* the package: ``from . import
            # LeafWriter`` names ``program.views``, and indexing it under a
            # second dotted name is how the resolver failed to follow the
            # writer every view builds its leaves with.
            parts.pop()
        texts[".".join(parts)] = path.read_text(encoding="utf-8")
    texts.update(overrides or {})
    return texts


def _module_of(dotted: str, node: ast.ImportFrom, level: int) -> str | None:
    """The dotted module a relative ``from ... import`` names, or None.

    ``None`` means the import leaves ``src/calculator``, which the resolver
    treats as a leaf: a function this package does not define is not a
    ``src/`` function in the view's call graph.
    """
    if level == 0:
        return None
    parts = dotted.split(".")[:-level] if level <= len(dotted.split(".")) else []
    if node.module:
        parts = parts + node.module.split(".")
    return ".".join(parts) if parts or node.module else ""


class _Index:
    """Every function and method the package defines, resolvable by name."""

    def __init__(self, texts: Mapping[str, str]) -> None:
        """Parse each module once and file what it defines."""
        self.trees = {name: ast.parse(text) for name, text in texts.items()}
        self.functions: dict[tuple[str, str], ast.AST] = {}
        self.methods: dict[str, list[tuple[str, ast.AST]]] = {}
        self.classes: dict[tuple[str, str], set[str]] = {}
        for module, tree in self.trees.items():
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self.functions[(module, node.name)] = node
                elif isinstance(node, ast.ClassDef):
                    members = self.classes.setdefault((module, node.name), set())
                    for member in node.body:
                        if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            members.add(member.name)
                            self.methods.setdefault(member.name, []).append(
                                (module, member)
                            )
        self.imports = {
            module: self._imports(module, tree) for module, tree in self.trees.items()
        }

    def _imports(self, module: str, tree: ast.Module) -> dict[str, tuple[str, str]]:
        """``local name -> (module, name)`` for every in-package import.

        A module imported as a whole (``from . import precision``) files as
        ``(target, "")`` so an ``Attribute`` call can be resolved against it.
        """
        bound: dict[str, tuple[str, str]] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            target = _module_of(module, node, node.level)
            if target is None:
                continue
            for alias in node.names:
                local = alias.asname or alias.name
                candidate = f"{target}.{alias.name}" if target else alias.name
                if candidate in self.trees:
                    bound[local] = (candidate, "")
                else:
                    bound[local] = (target, alias.name)
        return bound

    def resolve(
        self, module: str, call: ast.Call
    ) -> tuple[tuple[str, str], ...] | None:
        """Every ``(module, function)`` a call may run, or ``None`` if it leaves.

        A tuple rather than one answer, because an attribute spelling can
        belong to more than one class and a purity check must **over**-
        approximate: following every owner can only add a site to the walk,
        while following none can hide one.  A class name resolves to that
        class's own constructor bodies for the same reason, and an empty
        tuple -- a class the package defines with no constructor of its own
        -- is a resolved call with nothing to walk, which is not the same
        answer as ``None``.
        """
        func = call.func
        if isinstance(func, ast.Name):
            if (module, func.id) in self.functions:
                return ((module, func.id),)
            if (module, func.id) in self.classes:
                return self._constructors(module, func.id)
            bound = self.imports.get(module, {}).get(func.id)
            if bound and bound[1]:
                if bound in self.functions:
                    return (bound,)
                if bound in self.classes:
                    return self._constructors(*bound)
            return None
        if isinstance(func, ast.Attribute):
            if isinstance(func.value, ast.Name):
                bound = self.imports.get(module, {}).get(func.value.id)
                if bound and not bound[1] and (bound[0], func.attr) in self.functions:
                    return ((bound[0], func.attr),)
            if func.attr in PROTOCOL_ATTRIBUTES:
                return None
            owners = self.methods.get(func.attr, ())
            if not owners:
                return None
            return tuple(dict.fromkeys((owner, func.attr) for owner, _ in owners))
        return None

    def _constructors(self, module: str, name: str) -> tuple[tuple[str, str], ...]:
        """The bodies constructing one class runs, as call-graph targets."""
        defined = self.classes[(module, name)]
        return tuple(
            (module, member)
            for member in ("__init__", "__post_init__")
            if member in defined
        )

    def bodies(self, where: tuple[str, str]) -> tuple[ast.AST, ...]:
        """Every definition a resolved call may run."""
        module, name = where
        if (module, name) in self.functions:
            return (self.functions[(module, name)],)
        return tuple(
            node for owner, node in self.methods.get(name, ()) if owner == module
        )


def _callee_name(call: ast.Call) -> str:
    """How a call spells its callee, for the unresolved-frontier report."""
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return "<expression>"


def _arithmetic_in(node: ast.AST, module: str, function: str) -> list[Impurity]:
    """Every arithmetic expression inside one function body."""
    found: list[Impurity] = []
    for child in ast.walk(node):
        if isinstance(child, ast.BinOp) and isinstance(child.op, ARITHMETIC):
            found.append(
                Impurity(module, function, child.lineno, type(child.op).__name__)
            )
        elif isinstance(child, ast.AugAssign) and isinstance(child.op, ARITHMETIC):
            found.append(
                Impurity(
                    module, function, child.lineno, f"aug {type(child.op).__name__}"
                )
            )
        elif isinstance(child, ast.UnaryOp) and isinstance(
            child.op, (ast.USub, ast.UAdd)
        ):
            if not isinstance(child.operand, ast.Constant):
                found.append(Impurity(module, function, child.lineno, "unary sign"))
        elif (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id in FOLD_BUILTINS
        ):
            found.append(Impurity(module, function, child.lineno, child.func.id))
    return found


def view_roots(index: _Index) -> list[tuple[str, str]]:
    """Every module-level function the views package defines."""
    return sorted(
        (module, name)
        for (module, name) in index.functions
        if module == VIEWS_PACKAGE or module.startswith(VIEWS_PACKAGE + ".")
    )


def call_graph(
    overrides: Mapping[str, str] | None = None,
) -> tuple[list[tuple[str, str]], set[str]]:
    """Every function reachable from a view, and the callees that left ``src/``.

    Returned rather than asserted so both halves are testable: the closure is
    what the purity walk covers, and the unresolved set is the boundary that
    walk stops at.
    """
    index = _Index(_sources(overrides))
    seen: set[tuple[str, str]] = set()
    unresolved: set[str] = set()
    queue = list(view_roots(index))
    while queue:
        where = queue.pop()
        if where in seen:
            continue
        seen.add(where)
        for body in index.bodies(where):
            for node in ast.walk(body):
                if not isinstance(node, ast.Call):
                    continue
                targets = index.resolve(where[0], node)
                if targets is None:
                    unresolved.add(_callee_name(node))
                    continue
                queue.extend(target for target in targets if target not in seen)
    return sorted(seen), unresolved


def impurities(overrides: Mapping[str, str] | None = None) -> list[Impurity]:
    """Criterion 3's verdict: every arithmetic site a view can reach.

    An empty list is the pass condition.
    """
    index = _Index(_sources(overrides))
    reachable, _ = call_graph(overrides)
    found: list[Impurity] = []
    for module, name in reachable:
        for body in index.bodies((module, name)):
            found.extend(_arithmetic_in(body, module, name))
    return sorted(found, key=lambda site: (site.module, site.lineno))


def report(sites: Iterable[Impurity]) -> str:
    """One line per site, for an assertion that has to be readable."""
    return "\n".join(str(site) for site in sites)
