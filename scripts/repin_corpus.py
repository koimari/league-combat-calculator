"""The E9 practice corpus and its one writer.

Every scenario outside ``LEGACY_SCENARIO_IDS`` is asserted on every run.  A
receipt the engine stops reproducing fails on its own numbers, which is the
whole gate; there is no selection that could quietly shrink to nothing, and
nothing here reads repository history.  A scenario's ``sha`` records the
commit its receipt was last probed at, which is provenance a reader can
follow, never a filter.

Re-pinning re-probes: ``repin`` drives every such scenario through
``/api/calculate`` and refuses to stamp a scenario whose receipt fails to
reproduce, so the writer can never launder a broken receipt into a fresh pin.

``--check`` is the commit gate.  It fails on a missing pin and on a corpus that
has shrunk away from the count ``docs/receipts/campaign-fingerprints.json``
pins or from the set ``tests/test_e9_corpus.py`` parametrizes, so silence
cannot be mistaken for success.

Usage:
    python scripts/repin_corpus.py --check    # gate: verify, write nothing
    python scripts/repin_corpus.py            # re-probe and re-pin
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Collection, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

CORPUS_PATH = REPO_ROOT / "data" / "practice-corpus" / "scenarios.json"
FINGERPRINTS_PATH = REPO_ROOT / "docs" / "receipts" / "campaign-fingerprints.json"

# The four pre-E-series receipts.  Their expected values predate the E-series
# rework, so they are re-verified only by a deliberate re-capture rather than
# on every run.  Enumerated here, once, for both the reader and the writer.
LEGACY_SCENARIO_IDS = frozenset(
    {
        "cp21-ziggs-outer-blast",
        "cp21-bis-utility-ahri",
        "e0-vladimir-sanguine-pool-heal",
        "vladimir-hemoplague-multitarget",
    }
)


# ---------------------------------------------------------------------------
# The corpus
# ---------------------------------------------------------------------------


def load_corpus(path: Path = CORPUS_PATH) -> dict[str, Any]:
    """The corpus document."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_corpus(corpus: Mapping[str, Any], path: Path = CORPUS_PATH) -> None:
    """Rewrite the corpus in its committed formatting (1-space indent, escaped)."""
    Path(path).write_text(json.dumps(corpus, indent=1) + "\n", encoding="utf-8")


def non_legacy_scenarios(corpus: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every scenario the suite executes, minus ``LEGACY_SCENARIO_IDS``."""
    return [s for s in corpus["scenarios"] if s["id"] not in LEGACY_SCENARIO_IDS]


def parametrized_ids() -> tuple[str, ...]:
    """The scenario ids ``tests/test_e9_corpus.py`` parametrizes."""
    return tuple(s["id"] for s in non_legacy_scenarios(load_corpus()))


def expected_non_legacy_count() -> int | None:
    """``corpus.non_legacy_count`` from the fingerprints receipt, or ``None``.

    ``None`` falls through to the parametrized-set equality below, which
    pins the same number by identity.
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
    parametrized: Collection[str],
    expected_count: int | None = None,
) -> tuple[str, ...]:
    """Every reason ``--check`` should fail; an empty tuple is the pass condition.

    Two failure families, both required: a scenario that carries no provenance
    at all, and an executed set that has shrunk.  Without the second family a
    corpus somebody deleted rows from reports green.
    """
    reasons: list[str] = []
    governed = non_legacy_scenarios(corpus)
    reasons.extend(
        f"{scenario['id']} is missing its pinned SHA"
        for scenario in governed
        if not scenario.get("sha")
    )

    executed = tuple(s["id"] for s in governed)
    if not executed:
        reasons.append(
            "the corpus holds 0 non-legacy scenarios -- the suite would pass "
            "by asserting nothing"
        )
    if expected_count is not None and len(executed) != expected_count:
        reasons.append(
            f"the corpus executes {len(executed)} non-legacy scenarios but the "
            f"fingerprints receipt pins corpus.non_legacy_count at {expected_count}"
        )
    if set(executed) != set(parametrized):
        missing = sorted(set(parametrized) - set(executed))
        extra = sorted(set(executed) - set(parametrized))
        reasons.append(
            "the executed set does not match the set test_e9_corpus "
            f"parametrizes (missing {missing}, unexpected {extra})"
        )
    return tuple(reasons)


# ---------------------------------------------------------------------------
# The writer
# ---------------------------------------------------------------------------


def _head_commit() -> str:
    """The commit a re-probe stamps, or ``""`` when git cannot say.

    The one git call in this module, and it names HEAD: nothing above reads a
    commit at all, so the corpus gate runs on a shallow checkout.
    """
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def reprobe_failures(
    scenarios: Iterable[Mapping[str, Any]],
) -> tuple[tuple[str, str], ...]:
    """``(id, message)`` for every scenario whose receipt fails to reproduce.

    The receipt kinds live once, in ``tests/test_e9_corpus.py``; the writer
    borrows them rather than growing a second copy that could disagree.
    """
    from tests.test_e9_corpus import (  # sightline-ok: 35 - borrows the suite's receipts
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
            failures.append((scenario["id"], (str(exc).splitlines() or [repr(exc)])[0]))
    return tuple(failures)


def repin(
    *,
    check: bool,
    corpus_path: Path = CORPUS_PATH,
    parametrized: Sequence[str] | None = None,
) -> int:
    """Re-probe and rewrite every executed sha; ``check`` writes nothing."""
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
        reasons = check_pins(corpus, parametrized=ids, expected_count=expected_count)
        for reason in reasons:
            print(f"corpus pin: {reason}", file=sys.stderr)
        if reasons:
            return 1
        print(f"corpus pin: {len(ids)} non-legacy scenarios executed")
        return 0

    target = _head_commit()
    if not target:
        print("corpus pin: cannot resolve HEAD", file=sys.stderr)
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
        help="verify the pins and the executed set; write nothing",
    )
    parser.add_argument(
        "--corpus", type=Path, default=CORPUS_PATH, help=argparse.SUPPRESS
    )
    args = parser.parse_args(argv)
    return repin(check=args.check, corpus_path=args.corpus)


if __name__ == "__main__":
    raise SystemExit(main())
