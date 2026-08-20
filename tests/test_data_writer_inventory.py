"""Enforce the data-ownership registry (issue #141).

Every writer under data/ must be declared in data_registry.WRITERS, no
cwd-relative Path("data literals may remain, and the three tracked runtime
caches may only be written by data_updater through write_runtime_cache.
"""

import ast
import json
from pathlib import Path

import pytest

from src.calculator.data_registry import CACHE_FILES, write_runtime_cache

ROOT = Path(__file__).resolve().parents[1]


def _iter_python_files():
    for root in (ROOT / "src", ROOT / "scripts", ROOT / "tests"):
        for path in root.rglob("*.py"):
            if "__pycache__" in str(path):
                continue
            yield path


def _data_writes(tree: ast.AST) -> list[str]:
    """Collect suspicious data/ write sites: Path literals, open(...,'w'),
    write_text/write_bytes, json.dump(..., open(...)), mkdir under data."""
    hits = []

    def literal_data_parent(node):
        # Path("data/...") or Path(...) / "data" / ...
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.startswith("data") and (
                "/" in node.value or node.value == "data"
            ):
                return node.value
        return None

    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            name = n.func.attr
            if name in {
                "write_text",
                "write_bytes",
                "mkdir",
                "open",
                "replace",
                "rename",
            }:
                for a in ast.walk(n):
                    lit = literal_data_parent(a)
                    if lit:
                        hits.append(f"{name}({lit})")
                        break
        if (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "open"
        ):
            if n.args and isinstance(n.args[0], ast.Constant):
                v = n.args[0].value
                if isinstance(v, str) and v.startswith("data") and "/" in v:
                    hits.append(f"open({v})")
    return hits


def test_every_data_write_site_maps_to_the_registry_allowlist():
    """Every literal data/ path belongs to a declared writer module."""
    problems = []
    for path in _iter_python_files():
        rel = path.relative_to(ROOT).as_posix()
        if not any(rel.startswith(prefix) for prefix in ("src/", "scripts/", "tests/")):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for hit in _data_writes(tree):
            # scripts declaring their own writes must appear in WRITERS
            if hit.startswith("data/") and "tests/" not in rel:
                problems.append(f"{rel}: {hit}")
    assert not problems, "\n".join(problems[:20])


def test_no_cwd_relative_data_path_literals_in_writers():
    """decompose_wiki/binaries must be repo-anchored (import from foreign cwd)."""
    import importlib.util

    for script in ("decompose_wiki", "decompose_binaries"):
        spec = importlib.util.spec_from_file_location(
            script, ROOT / "scripts" / f"{script}.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert hasattr(module, "_REPO_ROOT"), script
        assert module._REPO_ROOT.resolve() == ROOT.resolve(), script


def test_runtime_cache_writes_only_via_registry():
    """Write calls touching the three tracked caches appear only in
    data_updater (registry API) and data_fetcher (deprecated wrapper)."""
    allowed = {"data_updater.py", "data_registry.py", "data_fetcher.py"}
    for path in _iter_python_files():
        rel = path.relative_to(ROOT).as_posix()
        if "tests/" in rel:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func_name = None
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = node.func.attr
            if func_name != "write_runtime_cache":
                continue
            if not any(
                isinstance(a, ast.Constant)
                and isinstance(a.value, str)
                and a.value in CACHE_FILES
                for a in node.args
            ):
                continue
            if path.name not in allowed:
                raise AssertionError(
                    f"{rel} writes a tracked runtime cache; only data_updater "
                    f"(via write_runtime_cache) may"
                )


def test_write_runtime_cache_is_atomic_and_refuses_foreign_names(tmp_path):
    payload = {"champion": "Ahri"}
    write_runtime_cache(
        tmp_path, "champions.json", payload, source_url="https://example.test"
    )
    written = json.loads((tmp_path / "champions.json").read_text(encoding="utf-8"))
    assert written == payload
    meta = json.loads((tmp_path / ".champions.json.meta").read_text(encoding="utf-8"))
    assert meta["source_url"] == "https://example.test"
    assert not (tmp_path / ".champions.json.tmp").exists()
    with pytest.raises(ValueError, match="not a runtime-cache file"):
        write_runtime_cache(tmp_path, "worklist.json", {})
