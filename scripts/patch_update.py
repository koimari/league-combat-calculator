"""Patch-day pipeline: re-pull wiki data, audit what we implement, run the gates.

When a new LoL patch drops, this script does the mechanical part of the
update so the judgment part (deciding whether code must change, explaining
golden diffs in the commit) starts from a focused report:

  1. Pull    — clear lolstaticdata's page caches (a stale cache silently
               "re-pulls" the old patch) and run data_updater.update_data().
  2. Audit   — diff the new data against the last committed data (git HEAD;
               data/ is tracked, so HEAD *is* the previous patch). Detail is
               limited to what the calculator implements: registered
               champions and items in the parse config, plus net-new /
               removed items shop-wide and a roster add/remove roll-call.
  3. Gates   — pytest, then golden compare (diffs printed so the commit can
               explain them). If pytest is green the baseline is re-captured
               in place; if it is red, hand-validated expectations drifted
               and a human/Claude must update them first.

Interpreting the report and finishing the update is the `patch-update`
skill's job (.claude/skills/patch-update/SKILL.md).

Usage:
    python scripts/patch_update.py run             # pull + audit + gates
    python scripts/patch_update.py audit           # re-print audit, no pull
    python scripts/patch_update.py detail NAME...  # full leaf diff for any
                                                   # champion/item vs HEAD
"""

import argparse
import json
import numbers
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.calculator.champions import registered_champion_names
from src.calculator.passive_parser import _ITEM_PARSE_CONFIG
from src.calculator.item_effects import _STATIC_VALUE_KEYS_BY_ITEM

GOLDEN_BASELINE = REPO_ROOT / "scripts" / "golden_baseline.json"
# Wiki noise: cosmetic/bookkeeping fields whose churn never affects math.
NOISE_SUBSTRINGS = ("icon", "releaseDate", "patchLastChanged", "price", "salePrice")


# ---------------------------------------------------------------------------
# Diff primitives
# ---------------------------------------------------------------------------


def leaf_diffs(old, new, path=""):
    """Yield (path, old_value, new_value) for every changed leaf.

    Containers recurse; a missing side is reported as None; list length
    changes get their own "(len)" entry plus per-index diffs over the
    common prefix.
    """
    if isinstance(old, dict) and isinstance(new, dict):
        for key in sorted(set(old) | set(new)):
            yield from leaf_diffs(old.get(key), new.get(key), f"{path}.{key}")
    elif isinstance(old, list) and isinstance(new, list):
        if len(old) != len(new):
            yield (f"{path}(len)", len(old), len(new))
        for index, (o, n) in enumerate(zip(old, new)):
            yield from leaf_diffs(o, n, f"{path}[{index}]")
    elif old != new:
        yield (path, old, new)


def drop_noise(diffs):
    """Drop diffs on cosmetic/bookkeeping paths (icons, dates, prices)."""
    return [d for d in diffs if not any(s in d[0] for s in NOISE_SUBSTRINGS)]


def is_numeric_diff(diff):
    """True when the changed leaf is a number (or a string that parses as one).

    Numeric diffs are the ones that can move calculations; prose diffs
    (descriptions, notes) usually cannot — but for registered champions the
    golden gate is the real arbiter, since custom modules may regex prose.
    """

    def numeric(value):
        if value is None:
            return True  # added/removed alongside a numeric sibling
        if isinstance(value, bool):
            return False
        if isinstance(value, numbers.Number):
            return True
        if isinstance(value, str):
            try:
                float(value)
                return True
            except ValueError:
                return False
        return False

    _, old, new = diff
    return numeric(old) and numeric(new)


def name_delta(old_by_name, new_by_name):
    """(added, removed) name lists between two name-keyed dicts."""
    added = sorted(set(new_by_name) - set(old_by_name))
    removed = sorted(set(old_by_name) - set(new_by_name))
    return added, removed


# ---------------------------------------------------------------------------
# Data loading (new = disk cache, old = last committed patch)
# ---------------------------------------------------------------------------


def _load_current(filename):
    """Load a data file from the on-disk cache (the freshly pulled patch)."""
    with open(REPO_ROOT / "data" / filename, encoding="utf-8") as f:
        return json.load(f)


def _load_head(filename):
    """Load the last committed version of a data file via git."""
    result = subprocess.run(
        ["git", "show", f"HEAD:data/{filename}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def _by_display_name(entries):
    """Re-key a champions/items dict by its entries' display names."""
    return {entry.get("name", key): entry for key, entry in entries.items()}


def load_old_and_new():
    """Returns (old_champs, new_champs, old_items, new_items), name-keyed."""
    return (
        _by_display_name(_load_head("champions.json")),
        _by_display_name(_load_current("champions.json")),
        _by_display_name(_load_head("items.json")),
        _by_display_name(_load_current("items.json")),
    )


# ---------------------------------------------------------------------------
# Audit report
# ---------------------------------------------------------------------------


def _format_leaf(value):
    text = repr(value)
    return text if len(text) <= 200 else text[:197] + "..."


def _detail_lines(diffs):
    """Numeric diffs verbatim, prose diffs summarized to their paths."""
    lines = []
    numeric = [d for d in diffs if is_numeric_diff(d)]
    prose = [d for d in diffs if not is_numeric_diff(d)]
    for path, old, new in numeric:
        lines.append(f"    NUMERIC {path}: {_format_leaf(old)} -> {_format_leaf(new)}")
    for path, _, _ in prose:
        lines.append(f"    text    {path}")
    return lines


def champion_audit_lines(old_champs, new_champs):
    """Audit section for registered champions plus the roster delta."""
    lines = ["== Registered champions =="]
    for name in registered_champion_names():
        diffs = drop_noise(list(leaf_diffs(old_champs.get(name), new_champs.get(name))))
        if not diffs:
            continue
        flag = "NEEDS REVIEW" if any(is_numeric_diff(d) for d in diffs) else "text-only"
        lines.append(f"  {name} ({flag}):")
        lines.extend(_detail_lines(diffs))
    if len(lines) == 1:
        lines.append("  (no changes)")

    added, removed = name_delta(old_champs, new_champs)
    if added or removed:
        lines.append("== Roster delta (generic path handles new champions) ==")
        for name in added:
            lines.append(f"  + {name}")
        for name in removed:
            lines.append(f"  - {name}")
    return lines


def item_audit_lines(old_items, new_items):
    """Audit section for configured items plus the shop-wide add/remove delta."""
    lines = ["== Configured items =="]
    for name in sorted(_ITEM_PARSE_CONFIG):
        diffs = drop_noise(list(leaf_diffs(old_items.get(name), new_items.get(name))))
        if not diffs:
            continue
        flag = "NEEDS REVIEW" if any(is_numeric_diff(d) for d in diffs) else "text-only"
        lines.append(f"  {name} ({flag}):")
        lines.extend(_detail_lines(diffs))
        static_keys = _STATIC_VALUE_KEYS_BY_ITEM.get(name)
        if static_keys:
            lines.append(
                f"    NOTE: code-owned values {sorted(static_keys)} — verify "
                "against the new wiki text (item_effects._OFFLINE_ITEM_EFFECTS)"
            )
    if len(lines) == 1:
        lines.append("  (no changes)")

    added, removed = name_delta(old_items, new_items)
    if added or removed:
        lines.append("== Shop delta ==")
        for name in added:
            lines.append(f"  + {name} (new item — consider /add-item-effect)")
        for name in removed:
            implemented = " ** IMPLEMENTED — code must be updated **" \
                if name in _ITEM_PARSE_CONFIG else ""
            lines.append(f"  - {name}{implemented}")
    return lines


def print_audit():
    """Print the full audit report (champions, items, deltas)."""
    old_champs, new_champs, old_items, new_items = load_old_and_new()
    print()
    print("#" * 70)
    print("# PATCH AUDIT (new data on disk vs last committed patch at git HEAD)")
    print("#" * 70)
    for line in champion_audit_lines(old_champs, new_champs):
        print(line)
    for line in item_audit_lines(old_items, new_items):
        print(line)
    print()


def print_detail(names):
    """Full leaf diffs vs HEAD for arbitrary champions/items by display name."""
    old_champs, new_champs, old_items, new_items = load_old_and_new()
    for name in names:
        if name in new_champs or name in old_champs:
            old, new = old_champs.get(name), new_champs.get(name)
        elif name in new_items or name in old_items:
            old, new = old_items.get(name), new_items.get(name)
        else:
            print(f"== {name}: not found in champions or items ==")
            continue
        print(f"== {name} ==")
        diffs = drop_noise(list(leaf_diffs(old, new)))
        if not diffs:
            print("  (no changes)")
        for path, old_v, new_v in diffs:
            print(f"  {path}:\n    OLD {_format_leaf(old_v)}\n    NEW {_format_leaf(new_v)}")


# ---------------------------------------------------------------------------
# Pull
# ---------------------------------------------------------------------------


def clear_wiki_caches():
    """Delete lolstaticdata's page caches so the pull fetches the new patch."""
    for cache_dir in ("__cache__", "__wiki__"):
        path = REPO_ROOT / "vendor" / "lolstaticdata" / cache_dir
        if path.exists():
            shutil.rmtree(path)
            print(f"Cleared {path.relative_to(REPO_ROOT)}")


def run_pull():
    """Stream data_updater.update_data(), returning the new patch string.

    Modifier-parse ERROR spam from lolstaticdata (Bard chimes, Jhin crit
    lines, ...) is normal and does not mean data was dropped; the summary
    lines report actual skips.
    """
    from src.calculator.data_updater import update_data

    patch = None
    for event in update_data():
        phase, status = event.get("phase"), event.get("status", "")
        current, total = event.get("current"), event.get("total")
        is_progress_tick = phase == "champions" and current not in (None, total)
        if is_progress_tick and current % 20 != 0 and "Skipped" not in status:
            continue  # keep the champion-by-champion spam down
        progress = f" [{current}/{total}]" if current is not None else ""
        print(f"{phase}{progress}: {status}", flush=True)
        if phase == "done":
            patch = event.get("patch")
        if phase == "error":
            raise RuntimeError(status)
    return patch


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------


def run_gates():
    """pytest, golden compare, and (only on green tests) baseline re-capture.

    Returns process exit code: 0 when tests pass and the baseline was
    re-captured, 1 when tests fail (expectations drifted — fix them, then
    re-run `audit` and capture manually).
    """
    print("== Gate: pytest ==", flush=True)
    tests = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"], cwd=REPO_ROOT, check=False
    )

    print("== Gate: golden compare (diffs below must be explained in the commit) ==",
          flush=True)
    # Diffs are expected after a real patch; the compare's exit code is
    # informational here, so no check.
    subprocess.run(
        [sys.executable, "scripts/golden_snapshot.py", "compare", str(GOLDEN_BASELINE)],
        cwd=REPO_ROOT,
        check=False,
    )

    if tests.returncode != 0:
        print(
            "\nFAIL: pytest is red — hand-validated expectations drifted with the\n"
            "patch. Update them with documented derivations, then re-capture:\n"
            f"    python scripts/golden_snapshot.py capture {GOLDEN_BASELINE}"
        )
        return 1

    print("== Re-capturing golden baseline (tests green) ==", flush=True)
    capture = subprocess.run(
        [sys.executable, "scripts/golden_snapshot.py", "capture", str(GOLDEN_BASELINE)],
        cwd=REPO_ROOT,
        check=False,
    )
    return capture.returncode


def run_full():
    """Full patch-day run: clear caches, pull, audit, gates."""
    clear_wiki_caches()
    patch = run_pull()
    print(f"\nPulled patch: {patch}")
    print_audit()
    return run_gates()


def main():
    """CLI entry point: run | audit | detail NAME..."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("run")
    commands.add_parser("audit")
    commands.add_parser("detail").add_argument("names", nargs="+")
    args = parser.parse_args()
    if args.command == "run":
        sys.exit(run_full())
    if args.command == "audit":
        print_audit()
        sys.exit(0)
    print_detail(args.names)
    sys.exit(0)


if __name__ == "__main__":
    main()
