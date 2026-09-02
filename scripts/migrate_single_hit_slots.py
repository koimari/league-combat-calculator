"""Move a hand-assigned ``single_hit`` certification onto ``single_hit_slots``.

A champion module states "this cast is one landing" in two shapes.  A packet
module names the slot in ``build_packet_module(..., single_hit_slots=...)``
and the compiler stamps it; a custom parser writes
``entry["event_order_certified"] = "single_hit"`` itself.  The second shape
predates the first, and where a wrapper sits on top of a one-hit packet row
the two say exactly the same thing in two places.

This migrates only the sites where they provably do.  A site qualifies when
all four hold, and the script refuses to touch anything else:

1. the assignment is a direct statement of its function's body -- not inside
   an ``if``, a loop or a ``try``, where the certification is conditional and
   ``single_hit_slots`` (all-or-nothing per slot) cannot express it;
2. the module compiles through ``build_packet_module``;
3. the slot reaches the parser through ``slot_wrappers``, which keeps the
   compiled parser underneath -- a ``slot_parsers`` slot *discards* it, so
   naming that slot would certify nothing in silence;
4. ``packet_module._single_hit_row`` accepts the slot's reviewed packet spec,
   which is the same check ``build_packet_module`` runs at import.

Usage::

    python scripts/migrate_single_hit_slots.py            # report only
    python scripts/migrate_single_hit_slots.py --apply    # rewrite

Byte-preserving: files are read and written with ``newline=""`` so this
tree's CRLF endings survive, and only the lines it names are touched.
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHAMPIONS = ROOT / "src" / "calculator" / "champions"

sys.path.insert(0, str(ROOT))

from src.calculator.champions.packet_module import (
    _packet_specs,
    _single_hit_row,
)

CERTIFICATION = "single_hit"
KEY = "event_order_certified"


@dataclass(frozen=True)
class Site:
    """One hand-assigned certification and the verdict on migrating it."""

    path: Path
    lineno: int
    slot: str | None
    verdict: str
    reason: str


def _packets() -> dict[str, dict]:
    """The reviewed packet map, read through the compiler's own loader."""
    return _packet_specs()


def _is_certification(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Subscript)
        and isinstance(node.targets[0].slice, ast.Constant)
        and node.targets[0].slice.value == KEY
        and isinstance(node.value, ast.Constant)
        and node.value.value == CERTIFICATION
    )


def _direct_body_statements(tree: ast.AST) -> set[int]:
    """Line numbers of certifications that are direct function-body statements."""
    unconditional: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for statement in node.body:
            if _is_certification(statement):
                unconditional.add(statement.lineno)
    return unconditional


def _enclosing_functions(tree: ast.AST) -> dict[int, list[str]]:
    """Function names enclosing each certification line, innermost last."""
    found: dict[int, list[str]] = {}

    def walk(node: ast.AST, stack: list[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                walk(child, [*stack, child.name])
            else:
                if isinstance(child, ast.stmt) and _is_certification(child):
                    found[child.lineno] = stack
                walk(child, stack)

    walk(tree, [])
    return found


def _packet_call(tree: ast.AST) -> ast.Call | None:
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "build_packet_module"
        ):
            return node
    return None


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _slot_map(call: ast.Call, name: str) -> dict[str, str]:
    """``{slot: parser name}`` for a ``slot_parsers``/``slot_wrappers`` dict."""
    node = _keyword(call, name)
    if not isinstance(node, ast.Dict):
        return {}
    resolved: dict[str, str] = {}
    for key, value in zip(node.keys, node.values, strict=False):
        if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
            continue
        if isinstance(value, ast.Name):
            resolved[key.value] = value.id
        elif isinstance(value, ast.Lambda):
            resolved[key.value] = "<lambda>"
    return resolved


def _named_slots(call: ast.Call) -> set[str]:
    node = _keyword(call, "single_hit_slots")
    slots: set[str] = set()
    for child in ast.walk(node) if node is not None else ():
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            slots.add(child.value)
    return slots


def _champion_name(call: ast.Call) -> str | None:
    if call.args and isinstance(call.args[0], ast.Constant):
        return str(call.args[0].value)
    return None


def survey(path: Path, packets: Mapping[str, dict]) -> list[Site]:
    """Every certification in *path*, each with its migration verdict."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    lines = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.stmt) and _is_certification(node)
    ]
    if not lines:
        return []
    unconditional = _direct_body_statements(tree)
    enclosing = _enclosing_functions(tree)
    call = _packet_call(tree)
    wrappers = _slot_map(call, "slot_wrappers") if call else {}
    champion = _champion_name(call) if call else None
    spec = packets.get(champion or "", {}).get("slots", {})
    ticked = set(_slot_map(call, "wiki_attribute_tick_fixes")) if call else set()

    sites: list[Site] = []
    for lineno in sorted(lines):
        if call is None:
            sites.append(
                Site(path, lineno, None, "bespoke", "module does not build a packet")
            )
            continue
        if lineno not in unconditional:
            sites.append(
                Site(path, lineno, None, "bespoke", "certification is conditional")
            )
            continue
        owners = enclosing.get(lineno, [])
        slot = next(
            (
                slot
                for slot, parser in wrappers.items()
                if parser in owners and slot not in ticked
            ),
            None,
        )
        if slot is None:
            sites.append(
                Site(path, lineno, None, "bespoke", "slot is not a slot_wrappers slot")
            )
            continue
        if not _single_hit_row(spec.get(slot), ticked=False):
            sites.append(
                Site(path, lineno, slot, "bespoke", "packet row is not one hit")
            )
            continue
        sites.append(
            Site(path, lineno, slot, "mechanical", "wrapper over a one-hit row")
        )
    return sites


def _rewrite(path: Path, sites: Iterable[Site]) -> None:
    """Delete the named lines and name their slots in ``single_hit_slots``."""
    text = path.read_text(encoding="utf-8", newline="")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    call = _packet_call(tree)
    assert call is not None
    slots = _named_slots(call) | {site.slot for site in sites if site.slot}
    rendered = "frozenset({{{}}})".format(
        ", ".join(f'"{slot}"' for slot in sorted(slots))
    )

    keep = {site.lineno for site in sites}
    physical = text.splitlines(keepends=True)
    body = "".join(
        line for number, line in enumerate(physical, 1) if number not in keep
    )

    existing = _keyword(call, "single_hit_slots")
    if existing is not None:
        old = ast.get_source_segment(path.read_text(encoding="utf-8"), existing)
        assert old is not None
        body = body.replace(
            f"single_hit_slots={old}", f"single_hit_slots={rendered}", 1
        )
    else:
        anchor = next(
            marker
            for marker in ("slot_parsers=", "slot_wrappers=", "cc_kinds=")
            if marker in body
        )
        indent = " " * 4
        body = body.replace(
            f"{indent}{anchor}",
            (
                f"{indent}single_hit_slots={rendered},\r\n{indent}{anchor}"
                if "\r\n" in body
                else f"{indent}single_hit_slots={rendered},\n{indent}{anchor}"
            ),
            1,
        )
    path.write_text(body, encoding="utf-8", newline="")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="rewrite the modules")
    args = parser.parse_args()

    packets = _packets()
    surveyed = [
        site
        for path in sorted(CHAMPIONS.glob("*.py"), key=lambda row: row.name)
        for site in survey(path, packets)
    ]
    mechanical = [site for site in surveyed if site.verdict == "mechanical"]
    bespoke = [site for site in surveyed if site.verdict == "bespoke"]

    for site in mechanical:
        print(f"MECHANICAL {site.path.name}:{site.lineno} slot {site.slot}")
    print(f"mechanical={len(mechanical)} bespoke={len(bespoke)}")

    if args.apply:
        by_file: dict[Path, list[Site]] = {}
        for site in mechanical:
            by_file.setdefault(site.path, []).append(site)
        for path, sites in by_file.items():
            _rewrite(path, sites)
            print(f"rewrote {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
