"""The E9 practice corpus's staleness anchor and its one writer.

The corpus pins every receipt to an *engine* rather than to a commit: a
scenario is asserted only while the ``src/`` tree it was verified against is
the tree the suite is running.  This module owns that anchor and is the only
writer of ``data/practice-corpus/scenarios.json``.

The anchor is the ``src/`` tree at the **merge base with ``main``** — never
HEAD's.  Anchored at HEAD, the gate demanded a value that cannot exist until
after the commit producing it exists, so every ``src/`` edit deselected the
whole corpus and the suite reported green over nothing; and two branches
editing ``src/`` wrote two different shas into one field and conflicted on
every merge.  Against the merge base the pin is stable for a whole branch, and
a scenario whose receipt an in-branch change breaks stays *executed* and fails
loudly on its own numbers — which is the gate the corpus was always meant to
be.

A scenario's ``sha`` therefore records the anchor commit its receipt is filed
under, not the commit it happened to be probed at.  Re-pinning re-probes:
``repin`` drives every non-legacy scenario through ``/api/calculate`` and
refuses to stamp a scenario whose receipt no longer reproduces, so the writer
can never launder a broken receipt into a fresh pin.

``--check`` is the commit gate.  It fails on a stale pin and on an empty or
short selection, so silence cannot be mistaken for success.

Usage:
    python scripts/repin_corpus.py --check    # gate: verify, write nothing
    python scripts/repin_corpus.py            # re-probe and re-pin
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Collection, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

CORPUS_PATH = REPO_ROOT / "data" / "practice-corpus" / "scenarios.json"
FINGERPRINTS_PATH = REPO_ROOT / "docs" / "receipts" / "campaign-fingerprints.json"

# The four pre-E-series receipts.  Their expected values predate the E-series
# rework, so they are exempt from the anchor and re-verified only by a
# deliberate re-capture.  Enumerated here, once, for both readers and the
# writer.
LEGACY_SCENARIO_IDS = frozenset(
    {
        "cp21-ziggs-outer-blast",
        "cp21-bis-utility-ahri",
        "e0-vladimir-sanguine-pool-heal",
        "vladimir-hemoplague-multitarget",
    }
)


# ---------------------------------------------------------------------------
# The anchor
# ---------------------------------------------------------------------------


def _git(*args: str) -> str:
    """One git command's stdout, or ``""`` when git rejects the request."""
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


@lru_cache(maxsize=None)
def src_tree_sha(commit: str) -> str:
    """The ``src/`` tree object at ``commit``, or ``""`` if it is unknown here.

    Comparing ``src`` trees rather than commits is the exact check: a receipt
    is valid iff the engine it was verified against is byte-identical to the
    engine being run, and the corpus commit itself touches only data and docs.
    """
    return _git("rev-parse", f"{commit}:src")


@lru_cache(maxsize=None)
def anchor_commit(*, base: str = "main") -> str:
    """The merge-base commit with ``base`` — the current branch's window start."""
    merge_base = _git("merge-base", "HEAD", base)
    if not merge_base:
        raise RuntimeError(
            f"no merge base between HEAD and {base!r}; the corpus anchor is undefined"
        )
    return merge_base


def anchor_src_sha(*, base: str = "main") -> str:
    """The ``src/`` tree object at the merge base — the corpus's staleness anchor.

    The single anchor: both readers in ``tests/test_e9_corpus.py`` and this
    module's writer resolve staleness through this one call.
    """
    return src_tree_sha(anchor_commit(base=base))


# ---------------------------------------------------------------------------
# The corpus and its executed selection
# ---------------------------------------------------------------------------


def load_corpus(path: Path = CORPUS_PATH) -> dict[str, Any]:
    """The corpus document."""
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def write_corpus(corpus: Mapping[str, Any], path: Path = CORPUS_PATH) -> None:
    """Rewrite the corpus in its committed formatting (1-space indent, escaped)."""
    Path(path).write_text(json.dumps(corpus, indent=1) + "\n", encoding="utf-8")


def non_legacy_scenarios(corpus: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every scenario the anchor governs — the four legacy receipts excluded."""
    return [s for s in corpus["scenarios"] if s["id"] not in LEGACY_SCENARIO_IDS]


def pinned_scenarios(
    corpus: Mapping[str, Any], *, anchor: str | None = None
) -> list[dict[str, Any]]:
    """The scenarios the suite executes: those pinned at the anchor engine."""
    target = anchor_src_sha() if anchor is None else anchor
    return [
        s
        for s in corpus["scenarios"]
        if s.get("sha") and src_tree_sha(s["sha"]) == target
    ]


def parametrized_ids() -> tuple[str, ...]:
    """The scenario ids ``tests/test_e9_corpus.py`` parametrizes (R-22)."""
    from tests.test_e9_corpus import _PINNED  # local: keeps the import edge one-way

    return tuple(s["id"] for s in _PINNED)


def expected_non_legacy_count() -> int | None:
    """``corpus.non_legacy_count`` from the fingerprints receipt, or ``None``.

    The receipt is captured by slice 0A.2.  Until it exists the count clause
    falls through to the parametrized-set equality below, which pins the same
    number by identity.
    """
    if not FINGERPRINTS_PATH.exists():
        return None
    with FINGERPRINTS_PATH.open(encoding="utf-8") as handle:
        fingerprints = json.load(handle)
    corpus_block = fingerprints.get("corpus") or {}
    count = corpus_block.get("non_legacy_count")
    return count if isinstance(count, int) else None


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


def check_pins(
    corpus: Mapping[str, Any],
    *,
    anchor: str,
    parametrized: Collection[str],
    expected_count: int | None = None,
) -> tuple[str, ...]:
    """Every reason ``--check`` should fail; an empty tuple is the pass condition.

    Two failure families, both required: a pin that no longer names the anchor
    engine, and a selection that is empty or short.  Without the second family
    a corpus that selects nothing reports green.
    """
    reasons: list[str] = []
    for scenario in non_legacy_scenarios(corpus):
        sha = scenario.get("sha")
        if not sha:
            reasons.append(f"{scenario['id']} is missing its pinned SHA")
            continue
        tree = src_tree_sha(sha)
        if not tree:
            reasons.append(
                f"{scenario['id']} is pinned at {sha}, a commit this repository "
                "does not have -- its engine cannot be resolved"
            )
        elif tree != anchor:
            reasons.append(
                f"{scenario['id']} is pinned at {sha} (src {tree}) but the anchor "
                f"engine is {anchor} -- re-probe the receipt and run "
                "`python scripts/repin_corpus.py`"
            )

    selected = pinned_scenarios(corpus, anchor=anchor)
    selected_ids = tuple(
        s["id"] for s in selected if s["id"] not in LEGACY_SCENARIO_IDS
    )
    total = len(non_legacy_scenarios(corpus))
    if not selected_ids:
        reasons.append(
            f"the corpus executes 0 of its {total} non-legacy scenarios -- the "
            "suite would pass by asserting nothing"
        )
    if expected_count is not None and len(selected_ids) != expected_count:
        reasons.append(
            f"the corpus executes {len(selected_ids)} non-legacy scenarios but the "
            f"fingerprints receipt pins corpus.non_legacy_count at {expected_count}"
        )
    if set(selected_ids) != set(parametrized):
        missing = sorted(set(parametrized) - set(selected_ids))
        extra = sorted(set(selected_ids) - set(parametrized))
        reasons.append(
            "the executed selection does not match the set test_e9_corpus "
            f"parametrizes (missing {missing}, unexpected {extra})"
        )
    return tuple(reasons)


# ---------------------------------------------------------------------------
# The writer
# ---------------------------------------------------------------------------


def reprobe_failures(
    scenarios: Iterable[Mapping[str, Any]],
) -> tuple[tuple[str, str], ...]:
    """``(id, message)`` for every scenario whose receipt no longer reproduces.

    The receipt kinds live once, in ``tests/test_e9_corpus.py``; the writer
    borrows them rather than growing a second copy that could disagree.
    """
    from tests.test_e9_corpus import (  # local: keeps the import edge one-way
        _KIND_ASSERTIONS,
        _run_calculate,
    )

    failures: list[tuple[str, str]] = []
    for scenario in scenarios:
        expected = scenario["expected"]
        kind = expected["kind"]
        if kind not in _KIND_ASSERTIONS:
            failures.append((scenario["id"], f"unknown receipt kind {kind!r}"))
            continue
        try:
            _KIND_ASSERTIONS[kind](_run_calculate(scenario["setup"]), expected)
        except AssertionError as exc:
            failures.append((scenario["id"], str(exc).splitlines()[0]))
    return tuple(failures)


def repin(
    *,
    at: str = "merge-base",
    check: bool,
    base: str = "main",
    corpus_path: Path = CORPUS_PATH,
    parametrized: Sequence[str] | None = None,
) -> int:
    """Re-probe and rewrite every non-legacy sha; ``check`` verifies and writes nothing.

    ``at`` defaults to the anchor, never HEAD: writing HEAD's sha while
    comparing against the merge base makes ``--check`` fail the moment ``src/``
    diverges, including on a comment-only commit.
    """
    anchor = anchor_src_sha(base=base)
    corpus = load_corpus(corpus_path)

    if check:
        expected_count = expected_non_legacy_count()
        if expected_count is None:
            print(
                f"note: {FINGERPRINTS_PATH.name} carries no corpus.non_legacy_count "
                "yet (slice 0A.2); the count clause falls through to the "
                "parametrized-set equality.",
                file=sys.stderr,
            )
        ids = parametrized_ids() if parametrized is None else tuple(parametrized)
        reasons = check_pins(
            corpus, anchor=anchor, parametrized=ids, expected_count=expected_count
        )
        for reason in reasons:
            print(f"corpus pin: {reason}", file=sys.stderr)
        if reasons:
            return 1
        print(f"corpus pin: {len(ids)} non-legacy scenarios executed at {anchor}")
        return 0

    target = anchor_commit(base=base) if at == "merge-base" else _git("rev-parse", at)
    if not target:
        print(f"corpus pin: cannot resolve {at!r}", file=sys.stderr)
        return 1
    if src_tree_sha(target) != anchor:
        print(
            f"corpus pin: {at!r} resolves to {target}, whose src/ tree is not the "
            f"anchor {anchor} -- the pin would be born stale",
            file=sys.stderr,
        )
        return 1

    governed = non_legacy_scenarios(corpus)
    failures = reprobe_failures(governed)
    for scenario_id, message in failures:
        print(f"corpus re-probe: {scenario_id}: {message}", file=sys.stderr)
    if failures:
        print(
            f"corpus pin: {len(failures)} receipt(s) no longer reproduce; nothing "
            "written -- fix the engine or re-capture the receipt deliberately",
            file=sys.stderr,
        )
        return 1

    for scenario in governed:
        scenario["sha"] = target
    write_corpus(corpus, corpus_path)
    print(f"corpus pin: {len(governed)} scenarios re-probed and pinned at {target}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the pins and the executed selection; write nothing",
    )
    parser.add_argument(
        "--at",
        default="merge-base",
        help="revision to pin at (default: the merge-base anchor)",
    )
    parser.add_argument(
        "--base", default="main", help="branch the anchor is the merge base with"
    )
    parser.add_argument(
        "--corpus", type=Path, default=CORPUS_PATH, help=argparse.SUPPRESS
    )
    args = parser.parse_args(argv)
    return repin(at=args.at, check=args.check, base=args.base, corpus_path=args.corpus)


if __name__ == "__main__":
    raise SystemExit(main())
