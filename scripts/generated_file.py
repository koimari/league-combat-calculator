"""The --write / --check entry point a script that generates one file shares."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path


def write_or_check(
    argv: list[str] | None = None,
    *,
    description: str,
    target: Path,
    root: Path,
    render: Callable[[], str],
    stale: str,
    fresh: str,
) -> int:
    """Write the rendered file under --write; under --check, say whether it matches."""
    parser = argparse.ArgumentParser(description=description)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    text = render()
    if args.write:
        target.write_text(text, encoding="utf-8")
        print(f"wrote {target.relative_to(root)}")
        return 0
    current = target.read_text(encoding="utf-8") if target.exists() else ""
    if current != text:
        print(stale)
        return 1
    print(fresh)
    return 0
