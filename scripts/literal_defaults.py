"""Rule-5 lint: literal defaults standing in for a cached-data read.

Flags ``x.get("key", <literal>)``, ``<expr> or <literal>`` and
``getattr(o, "attr", <literal>)``.  Two shapes are exempt by shape, not by a
list, because neither reads a named field of cached data:

* ``x.get(<computed key>, <identity element>)`` — an index into a local
  accumulator, where absence is the normal state.  ``ability_damages`` is
  carved out: its keys are champion slots and its home is ``ability_atoms``.
* ``<expr> or <literal>`` where ``<expr>`` is not itself a ``.get()`` — a
  None-coalesce on an Optional value, not a default for missing data.

    python scripts/literal_defaults.py            # the whole package
    python scripts/literal_defaults.py <paths>    # files or directories

The CLI reports every site it finds and exits 1 on any, tagging each with the
baseline bucket that licenses it or ``-`` for one outside the covered roots.
``literal_defaults_baseline.txt`` beside this file holds the covered roots and
the frozen sites; ``tests/test_literal_defaults.py`` is the gate that holds a
fresh scan against it.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import NamedTuple

#: Scanned when the CLI is given no paths — the rule's whole subject.
PACKAGE = Path(__file__).resolve().parent.parent / "src" / "calculator"

#: The frozen sites, the covered roots and what each bucket licenses.
BASELINE = Path(__file__).resolve().parent / "literal_defaults_baseline.txt"

_REASON = re.compile(r"^# ([A-Z][A-Z_]+): (.*)$")
_CONTINUATION = re.compile(r"^#     (.*)$")

_EMPTY_FACTORIES = frozenset({"dict", "list", "set", "tuple", "frozenset"})
# The one receiver whose computed keys are still cached data: champion slots.
_PAYLOAD_RECEIVERS = frozenset({"ability_damages"})


class Finding(NamedTuple):
    """One flagged site: where it is, what it reads, what it falls back to."""

    path: str
    line: int
    kind: str
    key: str
    default: str
    expression: str
    enclosing: str


def _is_literal(node: ast.AST) -> bool:
    """True for a value baked into the source rather than read from data."""
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.UnaryOp):
        return _is_literal(node.operand)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set, ast.Dict)):
        return all(map(_is_literal, _children(node)))
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _EMPTY_FACTORIES
        and not node.args
        and not node.keywords
    )


def _children(node: ast.AST) -> list[ast.expr]:
    """The value sub-expressions of a container literal."""
    return [kid for kid in ast.iter_child_nodes(node) if isinstance(kid, ast.expr)]


def _identity_element(node: ast.AST) -> bool:
    """True for the zero of a type: a number, a bool, or an empty container."""
    if isinstance(node, ast.Constant):
        return not isinstance(node.value, str)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set, ast.Dict)):
        return not _children(node)
    return True


def _text(node: ast.AST, source: str) -> str:
    """The source of one node, whitespace-collapsed onto a single line."""
    segment = ast.get_source_segment(source, node)
    return " ".join((segment if segment is not None else ast.unparse(node)).split())


def _is_get_call(node: ast.AST) -> bool:
    """True for any ``<expr>.get(...)`` call."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
    )


def _receiver_name(func: ast.Attribute) -> str:
    """The last name component of a ``.get()`` receiver path."""
    value = func.value
    if isinstance(value, ast.Attribute):
        return value.attr
    return value.id if isinstance(value, ast.Name) else ""


def _enclosing(tree: ast.AST) -> dict[int, str]:
    """Source line to innermost enclosing function or class name."""
    scope: dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for line in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                scope[line] = node.name
    return scope


def _string_constants(tree: ast.Module) -> dict[str, str]:
    """Every top-level ``NAME = "text"`` binding in one module."""
    found: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            target, value = node.target, node.value
        else:
            continue
        if (
            isinstance(target, ast.Name)
            and isinstance(value, ast.Constant)
            and isinstance(value.value, str)
        ):
            found[target.id] = value.value
    return found


def _imported_module(path: Path, node: ast.ImportFrom) -> Path | None:
    """The package file a relative ``from`` import reads, if it is one."""
    if not node.level:
        return None
    base = path.parent
    for _ in range(node.level - 1):
        base = base.parent
    dotted = base.joinpath(*(node.module.split(".") if node.module else ()))
    for candidate in (dotted.with_suffix(".py"), dotted / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def _named_keys(path: Path, tree: ast.Module) -> dict[str, str]:
    """The string constants one module can name a key by: its own, and imported.

    ``options.get(W_CHARGE, 0)`` is a named-key read exactly like
    ``options.get("w_charge", 0)``; without this the name reads as an index
    and the literal fallback is invisible.
    """
    names = _string_constants(tree)
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        module = _imported_module(path, node)
        if module is None:
            continue
        constants = _string_constants(
            ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        )
        for alias in node.names:
            if alias.name in constants:
                names[alias.asname or alias.name] = constants[alias.name]
    return names


def _resolved_key(key: ast.AST | None, names: Mapping[str, str]) -> ast.AST | None:
    """*key* with a named string constant replaced by its literal."""
    if isinstance(key, ast.Name) and key.id in names:
        return ast.copy_location(ast.Constant(names[key.id]), key)
    return key


def _indexing(get_call: ast.Call, key: ast.AST | None, default: ast.AST) -> bool:
    """True when the read is an index into an accumulator, not a field read."""
    named = isinstance(key, ast.Constant) and isinstance(key.value, str)
    return (
        not named
        and _identity_element(default)
        and _receiver_name(get_call.func) not in _PAYLOAD_RECEIVERS
    )


def _flagged(
    node: ast.AST, names: Mapping[str, str]
) -> tuple[str, ast.AST | None, ast.AST] | None:
    """The (kind, key, default) this node reads behind a literal fallback.

    A key spelled by a named string constant is judged and reported as the
    literal it names.
    """
    if _is_get_call(node) and len(node.args) == 2 and not node.keywords:
        default = node.args[1]
        key = _resolved_key(node.args[0], names)
        if _is_literal(default) and not _indexing(node, key, default):
            return "dict.get", key, default
        return None
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and (
            node.func.id == "getattr"
            and len(node.args) == 3
            and not node.keywords
            and _is_literal(node.args[2])
        )
    ):
        return "getattr", node.args[1], node.args[2]
    if (
        isinstance(node, ast.BoolOp)
        and isinstance(node.op, ast.Or)
        and _is_literal(node.values[-1])
        and _is_get_call(node.values[-2])
    ):
        coalesced = node.values[-2]
        key = _resolved_key(coalesced.args[0], names) if coalesced.args else None
        if not _indexing(coalesced, key, node.values[-1]):
            return "or-default", key, node.values[-1]
    return None


def _key_text(key: ast.AST | None, source: str) -> str:
    """A key as the baseline spells it; a resolved name as its literal."""
    if key is None:
        return ""
    segment = ast.get_source_segment(source, key)
    if isinstance(key, ast.Constant) and segment is not None and segment.isidentifier():
        return json.dumps(key.value)
    return _text(key, source)


def scan(paths: Iterable[Path]) -> list[Finding]:
    """Every flagged site in the given files, in source order."""
    findings: list[Finding] = []
    for path in paths:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        scope = _enclosing(tree)
        names = _named_keys(path, tree)
        for node in ast.walk(tree):
            flagged = _flagged(node, names)
            if flagged is None:
                continue
            kind, key, default = flagged
            findings.append(
                Finding(
                    str(path),
                    node.lineno,
                    kind,
                    _key_text(key, source),
                    _text(default, source),
                    _text(node, source),
                    scope.get(node.lineno, "<module>"),
                )
            )
    return sorted(findings, key=lambda f: (f.path, f.line, f.expression))


def targets(raw_paths: Iterable[str]) -> Iterator[Path]:
    """Expand file and directory arguments to Python files."""
    for raw in raw_paths:
        path = Path(raw)
        yield from sorted(path.rglob("*.py")) if path.is_dir() else iter((path,))


def frozen_key(finding: Finding) -> tuple[str, str, str, str]:
    """A site's identity in the baseline: module, function, kind, key."""
    return (
        Path(finding.path).resolve().relative_to(PACKAGE).as_posix(),
        finding.enclosing,
        finding.kind,
        finding.key,
    )


def scanned_rows(paths: Iterable[Path]) -> frozenset[tuple[str, str, str, str, int]]:
    """Every site in ``paths``, keyed and counted the way the baseline is."""
    occurrences = Counter(map(frozen_key, scan(paths)))
    return frozenset((*key, count) for key, count in occurrences.items())


class Site(NamedTuple):
    """One frozen row: the bucket that licenses it, and what it is."""

    bucket: str
    module: str
    enclosing: str
    kind: str
    key: str
    count: int

    def line(self) -> str:
        """This row as it is spelled in the baseline file."""
        return f"{'|'.join(self[:5])} {self.count}"


class Baseline(NamedTuple):
    """What ``literal_defaults_baseline.txt`` declares."""

    roots: tuple[str, ...]
    payload_receivers: tuple[str, ...]
    payload_scope: tuple[str, ...]
    er5_tail_ceiling: int
    reasons: Mapping[str, str]
    sites: frozenset[Site]

    def covered_files(self, roots: Iterable[str] | None = None) -> list[Path]:
        """Every ``.py`` the given roots hold, the covered set by default."""
        chosen = self.roots if roots is None else roots
        return sorted(targets(str(PACKAGE / root) for root in chosen))

    def er5_tail(self) -> tuple[str, ...]:
        """Every package module the covered roots do not reach."""
        covered = {path.resolve() for path in self.covered_files()}
        return tuple(
            sorted(
                path.relative_to(PACKAGE).as_posix()
                for path in PACKAGE.rglob("*.py")
                if path.resolve() not in covered
            )
        )

    def frozen_rows(self) -> frozenset[tuple[str, str, str, str, int]]:
        """The frozen sites keyed the way ``scanned_rows`` keys a fresh scan."""
        return frozenset(site[1:] for site in self.sites)


def _reasons(lines: Iterable[str]) -> dict[str, str]:
    """Each ``# BUCKET: ...`` header paragraph, continuations folded in."""
    reasons: dict[str, str] = {}
    current = ""
    for line in lines:
        named = _REASON.match(line)
        continued = _CONTINUATION.match(line)
        if named:
            current = named.group(1)
            reasons[current] = named.group(2)
        elif current and continued:
            reasons[current] += " " + continued.group(1)
        elif not named:
            current = ""
    return reasons


def load_baseline(path: Path = BASELINE) -> Baseline:
    """Parse the baseline file: covered roots, pinned zeros, frozen sites."""
    lines = path.read_text(encoding="utf-8").splitlines()
    declared: dict[str, list[str]] = {
        "root": [],
        "payload-receiver": [],
        "payload-scope": [],
        "er5-tail-ceiling": [],
    }
    sites: set[Site] = set()
    for line in lines:
        if line.startswith("#") or not line.strip():
            continue
        body, _, count = line.rpartition(" ")
        kind, _, rest = (body or line).partition("|")
        if kind in declared:
            declared[kind].append(line.partition("|")[2])
        else:
            sites.add(Site(kind, *rest.split("|"), int(count)))
    return Baseline(
        tuple(declared["root"]),
        tuple(declared["payload-receiver"]),
        tuple(declared["payload-scope"]),
        int(declared["er5-tail-ceiling"][0]),
        _reasons(lines),
        frozenset(sites),
    )


if __name__ == "__main__":
    _BUCKETS = {site[1:5]: site.bucket for site in load_baseline().sites}
    _FOUND = scan(targets(sys.argv[1:] or [str(PACKAGE)]))
    for _row in _FOUND:
        _BUCKET = _BUCKETS.get(frozen_key(_row), "-")
        print(f"{_row.path}:{_row.line} [{_row.kind}] [{_BUCKET}] {_row.expression}")
    print(f"total {len(_FOUND)}", file=sys.stderr)
    raise SystemExit(1 if _FOUND else 0)
