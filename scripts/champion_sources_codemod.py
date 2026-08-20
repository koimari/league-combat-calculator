"""Move champion source receipts into one asset and read them from one place.

``dump`` prints every registered champion's runtime ``SOURCES`` as JSON: the
before/after probe that proves a receipt did not move.  ``migrate`` collects
those rows into ``static/champion-source-receipts.json``, retires the
``cp10_batch_*`` assets it supersedes, and rewrites the modules that spell
their rows inline onto ``load_champion_sources``.

    python scripts/champion_sources_codemod.py dump --output before.json
    python scripts/champion_sources_codemod.py migrate
    python scripts/champion_sources_codemod.py dump --output after.json
    diff before.json after.json
"""

from __future__ import annotations

import argparse
import ast
import importlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CHAMPIONS = ROOT / "src" / "calculator" / "champions"
STATIC = ROOT / "static"
RECEIPT_ASSET = STATIC / "champion-source-receipts.json"
LOADER_IMPORT = "from .source_receipts import load_champion_sources"
ROW_KEYS = ("label", "url", "revision_id", "revision_timestamp")

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _registry() -> dict[str, str]:
    from src.calculator.champions import _CHAMPION_MODULES

    return dict(_CHAMPION_MODULES)


def runtime_sources() -> dict[str, list[dict[str, Any]]]:
    """Every registered champion's ``SOURCES`` as the runtime sees it."""
    rows: dict[str, list[dict[str, Any]]] = {}
    for name, module_name in _registry().items():
        module = importlib.import_module(f"src.calculator.champions.{module_name}")
        rows[name] = [dict(row) for row in module.SOURCES]
    return rows


def _batch_rows() -> dict[str, list[dict[str, Any]]]:
    """The rows the retiring ``cp10_batch_*`` assets publish, by champion."""
    rows: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(STATIC.glob("cp10_batch_*_sources.json")):
        rows.update(json.loads(path.read_text(encoding="utf-8")))
    return rows


def _pins() -> dict[str, list[dict[str, Any]]]:
    """The reviewed pin for each champion: its runtime rows, or the batch
    asset's when that carries the same page at more precision."""
    batch = _batch_rows()
    pins: dict[str, list[dict[str, Any]]] = {}
    for name, rows in runtime_sources().items():
        candidate = batch.get(name)
        if candidate is not None and candidate != rows:
            pages = {(row["url"], row["revision_id"]) for row in candidate}
            if not all((row["url"], row["revision_id"]) in pages for row in rows):
                raise SystemExit(
                    f"{name}: the module and the batch asset cite different "
                    "revisions of the same page — reconcile them by hand"
                )
            rows = candidate
        pins[name] = [{key: row[key] for key in ROW_KEYS} for row in rows]
    return pins


def _sources_statement(tree: ast.Module) -> ast.Assign | None:
    """The module-level ``SOURCES = ...`` statement, if the module spells one."""
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "SOURCES"
            for target in node.targets
        ):
            return node
    return None


def _header_end(tree: ast.Module) -> int:
    """Last line of the module's opening import block."""
    end = 0
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            end = node.end_lineno or node.lineno
        elif not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
            break
    return end


# Names the rewrite orphans: the receipt-shape helper the literal rows called,
# and the carrier a packet module bound the loaded rows to.
ORPHANED = ("source_row", "_packet_sources")


def _prune_orphans(lines: list[str]) -> list[str]:
    """Drop the imports and bindings this rewrite left with no reader."""
    for name in ORPHANED:
        text = "".join(lines)
        if name not in text:
            continue
        if any(
            isinstance(node, ast.Name)
            and node.id == name
            and isinstance(node.ctx, ast.Load)
            for node in ast.walk(ast.parse(text))
        ):
            continue
        kept = []
        for line in lines:
            stripped = line.strip()
            if stripped in (f"{name},", f"from .module_helpers import {name}"):
                continue
            if stripped.startswith(f"{name} = "):
                continue
            if stripped.startswith("from .module_helpers import "):
                imported = [
                    part.strip()
                    for part in stripped.split("import", 1)[1].split(",")
                    if part.strip() and part.strip() != name
                ]
                line = "from .module_helpers import " + ", ".join(imported) + "\n"
            kept.append(line)
        lines = kept
    return lines


def rewrite_module(path: Path, name: str) -> bool:
    """Point one module's ``SOURCES`` at the asset. True when it changed."""
    text = path.read_text(encoding="utf-8", newline="")
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.replace("\r\n", "\n").splitlines(keepends=True)
    tree = ast.parse("".join(lines))
    statement = _sources_statement(tree)
    if statement is None:
        return False

    start = statement.lineno - 1
    stop = statement.end_lineno or statement.lineno
    if isinstance(statement.value, ast.BinOp):
        # ``SOURCES = list(SOURCES) + [extra]`` after ``build_packet_module``:
        # the extra rows are in the asset now, so the whole statement goes.
        while stop < len(lines) and not lines[stop].strip():
            stop += 1
        lines[start:stop] = []
    else:
        lines[start:stop] = [f'SOURCES = load_champion_sources("{name}"){newline[-1]}']
        if LOADER_IMPORT not in "".join(lines):
            header = _header_end(tree)
            lines.insert(header, f"{LOADER_IMPORT}\n")

    lines = _prune_orphans(lines)
    rewritten = "".join(lines)
    if newline == "\r\n":
        rewritten = rewritten.replace("\n", "\r\n")
    if rewritten == text:
        return False
    path.write_text(rewritten, encoding="utf-8", newline="")
    return True


def migrate() -> None:
    pins = _pins()
    RECEIPT_ASSET.write_text(
        json.dumps(pins, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    retired = sorted(STATIC.glob("cp10_batch_*_sources.json"))
    for path in retired:
        path.unlink()
    changed = [
        module_name
        for name, module_name in sorted(_registry().items())
        if rewrite_module(CHAMPIONS / f"{module_name}.py", name)
    ]
    print(f"{len(pins)} champions pinned in {RECEIPT_ASSET.relative_to(ROOT)}")
    print(f"{len(retired)} retired assets removed")
    print(f"{len(changed)} modules rewritten: {', '.join(changed)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    dump = commands.add_parser("dump", help="print runtime SOURCES as JSON")
    dump.add_argument("--output", type=Path)
    commands.add_parser("migrate", help="write the asset and rewrite the modules")
    args = parser.parse_args(argv)

    if args.command == "dump":
        payload = json.dumps(
            runtime_sources(), indent=2, sort_keys=True, ensure_ascii=False
        )
        if args.output:
            args.output.write_text(payload + "\n", encoding="utf-8", newline="\n")
        else:
            print(payload)
        return 0
    migrate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
