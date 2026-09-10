"""Move top-level units out of one module into a package of new modules.

    python scripts/extract_modules.py scripts/assignments/damage.json
    python scripts/extract_modules.py scripts/assignments/damage.json --write

The assignment (JSON) names the source module, a docstring line per new package
directory, and each new module's path, one-line docstring and defs in source
order: ``{"source": <path>, "packages": {<dir>: <docstring>}, "modules":
[{"path": <path>, "docstring": <line>, "defs": [<name>, ...]}]}``.  One file per
source module, all of them under ``scripts/assignments/``, so a split is
reviewable as its own mapping: name, old home, new home.  A run may be followed
by edits the mapping does not carry (a moved def published under a shorter
name), and those live in the file's ``decisions``, so the record is reviewable
rather than replayable.  ``tests/test_extract_modules.py`` holds every declared
path to a file that exists.

A top-level ``def``, ``class`` or assignment is one movable unit, cut by AST span
with the contiguous ``#`` block above it; order inside a unit never changes and a
unit the assignment does not name stays in the residue.  A new module reading a
residue unit imports it back from the source, and the refusal is a cycle over the
whole graph, the residue counted as one node.  Readers under ``src/``,
``tests/`` and ``scripts/`` are repointed at the new home by
``scripts/module_readers.py``, and ``scripts/module_units.py`` holds the AST
vocabulary both phases cut with.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.module_readers import reader_files, rewrite_reader
from scripts.module_units import (
    MOVABLE,
    Unit,
    bound_alias,
    bound_names,
    free_names,
    import_sections,
    import_sort_key,
    import_statement,
    is_future_import,
    merge_imports,
    read_lines,
    read_parts,
    relative_head,
    relative_import,
)

REPO = Path(__file__).resolve().parent.parent


class Refusal(Exception):
    """The assignment cannot be carried out; the message names what blocks it."""


class Source:
    """The module being split: its text, its units and its import block."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lines, self.newline = read_lines(REPO / path)
        self.tree = ast.parse(self.newline.join(self.lines))
        named = path.with_suffix("").parts
        # A package is read by its directory name; `__init__` names no module.
        self.parts = named[:-1] if named[-1] == "__init__" else named
        self.pkg, self.dotted = path.parent.parts, ".".join(self.parts)
        self.stem = self.parts[-1]
        self.import_of: dict[str, tuple[ast.stmt, ast.alias]] = {}
        self.import_end = self.future = 0
        for node in self.tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                self.import_end = node.end_lineno or node.lineno
                self.future |= is_future_import(node)
                for alias in node.names:
                    self.import_of[bound_alias(alias)] = (node, alias)
        self.units = self._cut_units()
        self.exports = next((u for u in self.units if "__all__" in u.names), None)

    def _cut_units(self) -> list[Unit]:
        units: list[Unit] = []
        previous_end = 0
        for node in self.tree.body:
            end = node.end_lineno or node.lineno
            if isinstance(node, MOVABLE):
                start = self._span_start(node, previous_end)
                units.append(Unit(bound_names(node), start, end, node))
            previous_end = end
        return units

    def _span_start(self, node: ast.stmt, previous_end: int) -> int:
        """Where a unit starts: its decorators, then the ``#`` block above them."""
        decorators = (d.lineno for d in getattr(node, "decorator_list", []))
        start = min([node.lineno, *decorators])
        while start - 1 > previous_end:
            if not self.lines[start - 2].lstrip().startswith("#"):
                break
            start -= 1
        return start

    def span_text(self, unit: Unit, pkg: tuple[str, ...]) -> str:
        """The source of one unit, its comment block included, read from ``pkg``.

        A deferred import inside the body is relative to the source's package,
        so it is re-levelled for the module the unit lands in.
        """
        lines = list(self.lines[unit.start - 1 : unit.end])
        for node in ast.walk(unit.node):
            if not isinstance(node, ast.ImportFrom) or not node.level:
                continue
            old = f"from {'.' * node.level}{node.module or ''} import"
            new = relative_head(read_parts(node, self.pkg), pkg)
            index = node.lineno - unit.start
            lines[index] = lines[index].replace(old, new, 1)
        return "\n".join(lines)

    def import_anchor(self, statement: str) -> int:
        """The line one import sorts in front of, ``0`` past every import here."""
        key = import_sort_key(statement)
        previous_end = 0
        for node in self.tree.body:
            spelled = isinstance(node, (ast.Import, ast.ImportFrom))
            sorts_later = (
                spelled
                and not is_future_import(node)
                and (import_sort_key(import_statement(node, node.names)) > key)
            )
            if sorts_later:
                return self._span_start(node, previous_end)
            previous_end = node.end_lineno or node.lineno
        return 0

    def render_import(self, name: str, pkg: tuple[str, ...]) -> str:
        """Copy the source's own import of ``name``, re-levelled for ``pkg``."""
        node, alias = self.import_of[name]
        piece = alias.name + (f" as {alias.asname}" if alias.asname else "")
        if isinstance(node, ast.Import):
            return f"import {piece}"
        if node.level == 0:
            return f"from {node.module} import {piece}"
        return relative_import(read_parts(node, self.pkg), pkg, piece)


def docstring_block(text: str, width: int = 88) -> str:
    """One module docstring, wrapped when the line it would be is too wide."""
    if len(text) + 6 <= width:
        return f'"""{text}"""'
    return '"""' + textwrap.fill(text, width=width - 3) + '"""'


class NewModule:
    """One module the assignment creates, and the units it takes."""

    def __init__(self, entry: dict, source: Source) -> None:
        self.path, self.source = Path(entry["path"]), source
        self.key, self.pkg = self.path.as_posix(), self.path.parent.parts
        self.parts = self.path.with_suffix("").parts
        self.docstring, self.defs = entry["docstring"], tuple(entry["defs"])
        self.units: list[Unit] = []
        self.bound: set[str] = set()
        self.imports: list[str] = []
        self.deps: set[str] = set()

    def take(self, unit: Unit) -> None:
        """Give one unit its home here."""
        self.units.append(unit)
        self.bound.update(unit.names)

    def render(self) -> str:
        """The module's text: docstring, imports, then units in source order."""
        blocks = [docstring_block(self.docstring)]
        statements = [*self.imports]
        if self.source.future:
            statements.append("from __future__ import annotations")
        if statements:
            blocks.append("\n\n".join(import_sections(statements)))
        blocks.extend(self.source.span_text(unit, self.pkg) for unit in self.units)
        return ("\n\n\n".join(blocks) + "\n").replace("\n", self.source.newline)


class Plan:
    """The whole move: which unit goes where, and what each module imports."""

    def __init__(self, assignment: dict, *, write: bool = False) -> None:
        self.write = write
        self.source = Source(Path(assignment["source"]))
        self.packages = dict(assignment.get("packages", {}))
        self.modules = [NewModule(e, self.source) for e in assignment["modules"]]
        self.home = self._resolve_homes()
        self.moved = {name for module in self.modules for name in module.bound}
        stayed = (u for u in self.source.units if not set(u.names) & self.moved)
        self.residue_units = list(stayed)
        self._resolve_imports()
        self.kept_exports = self._kept_exports()
        self.residue_reads = self._residue_reads()
        self.residue_imports = self._residue_imports()
        self._refuse_cycles()
        read = reader_files(self, REPO)
        found = ((p.as_posix(), rewrite_reader(p, self, REPO)) for p in read)
        self.rewrites = {path: sites for path, sites in found if sites}

    def _resolve_homes(self) -> dict[str, NewModule]:
        home: dict[str, NewModule] = {}
        for module in self.modules:
            for name in module.defs:
                if name in home:
                    raise Refusal(f"{name} is assigned to two modules")
                home[name] = module
        known = {name for unit in self.source.units for name in unit.names}
        if missing := sorted(set(home) - known):
            raise Refusal(f"not a unit of {self.source.path}: {', '.join(missing)}")
        for unit in self.source.units:
            homes = {home[name].key for name in unit.names if name in home}
            if len(homes) > 1:
                raise Refusal(f"one unit binds names assigned to {sorted(homes)}")
            if homes:
                owner = home[next(n for n in unit.names if n in home)]
                owner.take(unit)
                home.update(dict.fromkeys(unit.names, owner))
        return home

    def _resolve_imports(self) -> None:
        residue_bound = {name for unit in self.residue_units for name in unit.names}
        refusals: list[str] = []
        for module in self.modules:
            reads = set().union(*(free_names(u.node) for u in module.units))
            for name in sorted(reads - module.bound):
                if (target := self.home.get(name)) is not None:
                    module.imports.append(
                        relative_import(target.parts, module.pkg, name)
                    )
                    module.deps.add(target.key)
                elif name in self.source.import_of:
                    module.imports.append(self.source.render_import(name, module.pkg))
                elif name in residue_bound:
                    module.imports.append(
                        relative_import(self.source.parts, module.pkg, name)
                    )
                    module.deps.add(self.source.path.as_posix())
                else:
                    refusals.append(
                        f"unresolved: {module.key} reads {name}, bound nowhere"
                    )
        if refusals:
            raise Refusal("\n".join(refusals))
        for module in self.modules:
            ordered = sorted(module.imports, key=import_sort_key)
            module.imports[:] = merge_imports(ordered)

    def _refuse_cycles(self) -> None:
        """Refuse an import loop; the residue is the node the source path names."""
        graph = {module.key: sorted(module.deps) for module in self.modules}
        back = {self.home[name].key for name in self.residue_reads & self.moved}
        graph[self.source.path.as_posix()] = sorted(back)
        state: dict[str, int] = {}

        def walk(node: str, trail: list[str]) -> None:
            state[node] = 1
            for nxt in graph.get(node, ()):
                if state.get(nxt) == 1:
                    raise Refusal(
                        "cycle: " + " -> ".join([*trail[trail.index(nxt) :], nxt])
                    )
                if nxt not in state:
                    walk(nxt, [*trail, nxt])
            state[node] = 2

        for key in graph:
            if key not in state:
                walk(key, [key])

    def _kept_exports(self) -> tuple[str, ...]:
        """The names the residue's ``__all__`` still publishes, in source order."""
        exports = self.source.exports
        elements = exports.node.value.elts if exports else []
        return tuple(
            element.value
            for element in elements
            if isinstance(element, ast.Constant) and element.value not in self.moved
        )

    def _residue_reads(self) -> set[str]:
        """Every name the residue still needs, a re-export through ``__all__`` included."""
        body = self.source.tree.body
        kept = [
            n for n in body if not isinstance(n, MOVABLE) and not is_future_import(n)
        ]
        kept += [unit.node for unit in self.residue_units]
        reads = set().union(*(free_names(node) for node in kept)) if kept else set()
        return reads | set(self.kept_exports)

    def _residue_imports(self) -> list[str]:
        by_home: dict[str, list[str]] = {}
        for name in sorted(self.residue_reads & self.moved):
            by_home.setdefault(self.home[name].key, []).append(name)
        homes = ((self.home[n[0]].parts, ", ".join(n)) for n in by_home.values())
        lines = [relative_import(parts, self.source.pkg, p) for parts, p in homes]
        return sorted(lines, key=import_sort_key)


def _exports_line(plan: Plan) -> str:
    """The residue's ``__all__``, with every moved name dropped from it."""
    return "__all__ = [" + ", ".join(f'"{n}"' for n in plan.kept_exports) + "]"


def _unread_imports(plan: Plan) -> tuple[set[int], dict[int, str]]:
    """Import lines nothing in the residue reads, and the ones it half reads.

    An import the residue keeps whole is left exactly as the source spells it,
    and a ``__future__`` import is kept whatever the residue reads.
    """
    dropped: set[int] = set()
    narrowed: dict[int, str] = {}
    for node in plan.source.tree.body:
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if is_future_import(node):
            continue
        read = [a for a in node.names if bound_alias(a) in plan.residue_reads]
        if len(read) == len(node.names):
            continue
        dropped.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
        if read:
            narrowed[node.lineno] = import_statement(node, read)
    return dropped, narrowed


def _residue_exports(plan: Plan) -> tuple[set[int], dict[int, str]]:
    """The ``__all__`` lines to drop, and the line the pruned list is written on."""
    exports = plan.source.exports
    elements = exports.node.value.elts if exports else []
    if not any(getattr(e, "value", None) in plan.moved for e in elements):
        return set(), {}
    span = set(range(exports.start, exports.end + 1))
    return span, {exports.end: _exports_line(plan)}


def build_residue(plan: Plan) -> str:
    """The source minus its moved units, plus imports of the names it still reads."""
    source = plan.source
    dropped, replaced = _unread_imports(plan)
    export_lines, export_text = _residue_exports(plan)
    dropped |= export_lines
    dropped.update(
        n for m in plan.modules for u in m.units for n in range(u.start, u.end + 1)
    )
    replaced |= export_text
    kept: list[str] = []
    at: dict[int, int] = {}
    anchor = 0
    for number, line in enumerate(source.lines, start=1):
        at[number] = len(kept)
        if number in replaced:
            kept.append(replaced[number])
        elif number not in dropped and (line.strip() or kept[-2:] != ["", ""]):
            kept.append(line)
        if number == source.import_end:
            anchor = len(kept)
    placed = [
        (at.get(source.import_anchor(statement), anchor), order, statement)
        for order, statement in enumerate(plan.residue_imports)
    ]
    for index, _, statement in sorted(placed, reverse=True):
        kept.insert(index, statement)
    return source.newline.join(kept)


def write_plan(plan: Plan) -> list[str]:
    """Write every new module, its packages and the residue; report the paths."""
    written = []
    for directory, docstring in plan.packages.items():
        init = REPO / directory / "__init__.py"
        init.parent.mkdir(parents=True, exist_ok=True)
        init.write_bytes(f'"""{docstring}"""{plan.source.newline}'.encode())
        written.append(init.relative_to(REPO).as_posix())
    for module in plan.modules:
        (REPO / module.path).parent.mkdir(parents=True, exist_ok=True)
        (REPO / module.path).write_bytes(module.render().encode("utf-8"))
    (REPO / plan.source.path).write_bytes(build_residue(plan).encode("utf-8"))
    return [*written, *(m.key for m in plan.modules), plan.source.path.as_posix()]


def print_plan(plan: Plan) -> str:
    """What a ``--check`` run prints: units, sizes, imports, graph, readers."""
    units = sum(len(m.units) for m in plan.modules)
    report = [
        f"source: {plan.source.path.as_posix()} "
        f"({len(plan.source.lines)} lines, {len(plan.source.units)} units)",
        f"moving {units} units into {len(plan.modules)} modules; "
        f"{len(plan.residue_units)} units stay\n",
    ]
    for module in plan.modules:
        size = sum(unit.end - unit.start + 1 for unit in module.units)
        names = ", ".join(n for u in module.units for n in u.names)
        report += [
            f"{module.key}  ({size} lines, {len(module.units)} units)",
            f"  units: {names}",
        ]
        report += [f"    {s}" for s in module.imports] + [""]
    edges = (
        f"  {m.key} -> {', '.join(sorted(m.deps)) or '(leaf)'}" for m in plan.modules
    )
    report += ["graph:", *edges]
    report += [
        "\nresidue imports back:",
        *(f"  {s}" for s in plan.residue_imports or ["(none)"]),
    ]
    sites = sum(len(v) for v in plan.rewrites.values())
    report.append(f"\nreaders: {sites} sites in {len(plan.rewrites)} files")
    report += [
        f"  {path}:{site}" for path, group in plan.rewrites.items() for site in group
    ]
    return "\n".join(report)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Split a module into a package of modules."
    )
    parser.add_argument("assignment", type=Path, help="the assignment JSON")
    parser.add_argument(
        "--write", action="store_true", help="write instead of printing the plan"
    )
    parser.add_argument(
        "--check", action="store_true", help="print the plan (the default)"
    )
    args = parser.parse_args(argv)
    assignment = json.loads(args.assignment.read_text(encoding="utf-8"))
    try:
        plan = Plan(assignment, write=args.write and not args.check)
    except Refusal as refusal:
        print(f"refused:\n{refusal}", file=sys.stderr)
        return 1
    print(print_plan(plan))
    if plan.write:
        print("\nwrote:\n  " + "\n  ".join(write_plan(plan)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
