"""Rewrite coverage-evidence symbol paths when a symbol is renamed.

``item_coverage.py`` names the implementing symbol of every coverage claim by
dotted path, and ``tests/coverage_resolver.py`` resolves each one against the
tree on every run — so renaming a function there, including a private helper,
turns those claims red.  That is the check working; this is the codemod that
answers it, so a rename stays a rename instead of a hand-edit across a 2.3k
line table.

    python scripts/rename_evidence.py damage._add_burn_damage damage._add_burn
    python scripts/rename_evidence.py --check <old> <new>   # report, write nothing
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Every file that authors a ``Symbol.path``.  One entry today; a second
#: authoring home would be the drift this codemod exists to make cheap.
EVIDENCE_HOMES = (Path("src") / "calculator" / "item_coverage.py",)


def rewrite(text: str, old: str, new: str) -> tuple[str, int]:
    """Replace the quoted dotted path *old* with *new*; return text and count."""
    quoted_old, quoted_new = f'"{old}"', f'"{new}"'
    return text.replace(quoted_old, quoted_new), text.count(quoted_old)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("old", help="dotted path as it is written today")
    parser.add_argument("new", help="dotted path it becomes")
    parser.add_argument(
        "--check", action="store_true", help="report the rewrites, write nothing"
    )
    args = parser.parse_args(argv)

    total = 0
    for relative in EVIDENCE_HOMES:
        path = REPO_ROOT / relative
        text = path.read_text(encoding="utf-8")
        rewritten, count = rewrite(text, args.old, args.new)
        total += count
        if count and not args.check:
            path.write_text(rewritten, encoding="utf-8")
        if count:
            print(f"{relative.as_posix()}: {count} evidence path(s)")
    if not total:
        print(f"no evidence path names {args.old!r}", file=sys.stderr)
        return 1
    print(f"{'would rewrite' if args.check else 'rewrote'} {total} evidence path(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
