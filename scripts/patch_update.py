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
  3. Gates   — reviewed-packet freshness, full-entry audit, staleness
               (patch_regression), then pytest and golden compare. The
               baseline is re-captured only when every gate is green: a
               stale packet asset, a review-pending entry, or a stale wiki
               cache aborts the run before capture (issue #134).

Reviewed-packet gate (issue #134): the checked-in
``static/reviewed-packets.json`` must prove it was built from the current
sources — the ``data/champions.json`` sha256 and Axword Meraki kit sha256
receipts plus a current per-champion wiki revision receipt.  On a real patch
day the pull changes those sources and the gate fails closed with the exact
rebuild command; regenerate, re-review, and commit the packets before
re-running.  Sources resolve portably: ``--wiki-db`` / ``LCC_WIKI_DB`` and
``--axword-source`` / ``LCC_AXWORD_SOURCE``.

Interpreting the report and finishing the update is the `patch-update`
skill's job (.claude/skills/patch-update/SKILL.md).

Usage:
    python scripts/patch_update.py run             # pull + audit + rebuild + gates
    python scripts/patch_update.py audit           # re-print audit, no pull
    python scripts/patch_update.py detail NAME...  # full leaf diff for any
                                                   # champion/item vs HEAD
    python scripts/patch_update.py run --patch 16.16  # pin the staleness gate
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
from src.calculator.item_source import branch_losses, source_audit

GOLDEN_BASELINE = REPO_ROOT / "scripts" / "golden_baseline.json"
REVIEWED_PACKETS = REPO_ROOT / "static" / "reviewed-packets.json"
DEFAULT_AUDIT_OUTPUT = REPO_ROOT / "docs" / "wiki-full-entry-audit.json"
DEFAULT_STALENESS_OUT = REPO_ROOT / "data" / "staleness.json"
# Wiki noise: cosmetic/bookkeeping fields whose churn never affects math.
NOISE_SUBSTRINGS = ("icon", "releaseDate", "patchLastChanged", "price", "salePrice")

try:
    from build_reviewed_modules import (  # pylint: disable=import-error
        _wiki_revisions,
        resolve_axword_source,
        resolve_wiki_db,
    )
    from source_receipt import source_receipt
except ImportError:  # imported as scripts.patch_update in tests
    from scripts.build_reviewed_modules import (
        _wiki_revisions,
        resolve_axword_source,
        resolve_wiki_db,
    )
    from scripts.source_receipt import source_receipt


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
        lines.append("== Roster delta (new champions need a named module) ==")
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
            implemented = (
                " ** IMPLEMENTED — code must be updated **"
                if name in _ITEM_PARSE_CONFIG
                else ""
            )
            lines.append(f"  - {name}{implemented}")
    return lines


def item_source_lines(old_items, new_items):
    """Source-completeness section, plus whether the patch may proceed.

    Two things stop a patch here. An effect branch that disappeared is almost
    always a broken parse rather than a deleted mechanic, and a Riot-declared
    effect the Wiki does not carry is a source conflict — either could
    silently shrink what the calculator models. Both are releasable once
    reviewed: a verified removal goes in ``APPROVED_BRANCH_REMOVALS``, an
    explained divergence in ``ACKNOWLEDGED_SOURCE_CONFLICTS``, and one that is
    genuinely unsettled in ``OPEN_SOURCE_CONFLICTS``, where it is re-reported
    every patch day instead of quietly picking a source.
    """
    lines = ["== Item source completeness =="]
    blocking = False

    losses = branch_losses(old_items, new_items)
    unapproved = [loss for loss in losses if not loss["approved"]]
    for loss in losses:
        flag = "approved" if loss["approved"] else "BLOCKING"
        lines.append(f"  {flag}: {loss['effect']} — {loss['detail']}")
        if loss["explanation"]:
            lines.append(f"    {loss['explanation']}")
    blocking = blocking or bool(unapproved)

    audit = source_audit(new_items.values())
    flags = {"explained": "explained", "open": "OPEN REVIEW", "unreviewed": "BLOCKING"}
    for conflict in audit["conflicts"]:
        lines.append(
            f"  {flags[conflict['status']]} conflict: {conflict['item']} / "
            f"{conflict['effect']} is declared by Riot but absent from the "
            "Wiki item table"
        )
        lines.append(f"    {conflict['note']}")
    blocking = blocking or bool(audit["unreviewed_conflicts"])

    for warning in audit["warnings"]:
        lines.append(f"  note: {warning}")

    if len(lines) == 1:
        lines.append("  (every source branch is accounted for)")
    if blocking:
        lines.append(
            "  ** BLOCKING — verify each entry against Riot/CommunityDragon and "
            "the Wiki, then record it in item_source (APPROVED_BRANCH_REMOVALS "
            "or ACKNOWLEDGED_SOURCE_CONFLICTS) with how you confirmed it. **"
        )
    return lines, not blocking


def print_audit():
    """Print the full audit report (champions, items, deltas).

    Returns whether the source-completeness section is clear enough to
    proceed; the prose sections above it are informational.
    """
    old_champs, new_champs, old_items, new_items = load_old_and_new()
    print()
    print("#" * 70)
    print("# PATCH AUDIT (new data on disk vs last committed patch at git HEAD)")
    print("#" * 70)
    for line in champion_audit_lines(old_champs, new_champs):
        print(line)
    for line in item_audit_lines(old_items, new_items):
        print(line)
    source_lines, source_ok = item_source_lines(old_items, new_items)
    for line in source_lines:
        print(line)
    print()
    return source_ok


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
            print(
                f"  {path}:\n    OLD {_format_leaf(old_v)}\n    NEW {_format_leaf(new_v)}"
            )


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


def rebuild_static_artifacts():
    """Rebuild the derived catalogues the web UI fetches at runtime.

    app.js loads ability-catalog, bis-profiles, and effect-catalog directly, so
    a patch that refreshes data/ without rebuilding these leaves the UI serving
    the previous patch's abilities and item effects. Skipping this step is what
    left them stale before.

    bis-profiles is deliberately not rebuilt here: it merges an Axword Meraki
    kit reference from a sibling repo that supplies damage packets the wiki
    parser cannot read, and rebuilding without that repo silently drops them.
    Rebuild it by hand, with the sibling checked out, when its wiki inputs move.
    """
    print("== Rebuilding static catalogues ==", flush=True)
    for builder in (
        "build_ability_catalog.py",
        "build_effect_catalog.py",
        # Issue #163: entity receipts read the unified Atomizer item domain;
        # a red builder would leave stale receipts in the release tree.
        "build_receipts.py",
    ):
        result = subprocess.run(
            [sys.executable, f"scripts/{builder}"], cwd=REPO_ROOT, check=False
        )
        if result.returncode != 0:
            print(f"FAIL: scripts/{builder} exited {result.returncode}")
            return result.returncode

    auxiliary = (
        REPO_ROOT.parent
        / "lol-strength-analysis"
        / "src"
        / "data"
        / "generated"
        / "merakiAbilityKits.ts"
    )
    print(
        "NOTE: static/bis-profiles.json not rebuilt (needs the Axword Meraki\n"
        f"      sibling repo, {'present' if auxiliary.exists() else 'absent'}). "
        "Rebuild manually if its wiki\n"
        "      inputs changed:\n"
        "          python scripts/build_bis_profiles.py"
    )
    return 0


# ---------------------------------------------------------------------------
# Reviewed-packet freshness gate (issue #134)
# ---------------------------------------------------------------------------


def check_reviewed_packets_current(
    *,
    asset_path: Path | None = None,
    champions_source: Path | None = None,
    axword_source: Path | None = None,
    wiki_db: Path | None = None,
) -> list[str]:
    """Return staleness reasons for the checked-in reviewed-packet asset.

    Empty list means the asset proves it was built from the current sources:
    the ``data/champions.json`` and Axword kit sha256 receipts plus a current
    per-champion wiki revision receipt.  Any mismatch is a hard pre-capture
    failure — a frozen asset plus green tests must never re-bless stale
    numbers into the golden baseline.
    """
    asset_path = Path(asset_path or REVIEWED_PACKETS)
    champions_source = Path(champions_source or REPO_ROOT / "data" / "champions.json")
    axword_source = Path(axword_source or resolve_axword_source())
    wiki_db = Path(wiki_db or resolve_wiki_db())
    try:
        asset = json.loads(asset_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return [f"reviewed-packets.json is missing or unreadable ({asset_path}): {exc}"]
    problems: list[str] = []

    receipts = asset.get("source_receipts") or {}
    if not receipts:
        problems.append(
            "reviewed-packets.json carries no source receipts — rebuild it with "
            "scripts/build_reviewed_modules.py so patch day can prove currency"
        )
    expected_champions = source_receipt(champions_source, kind="tracked wiki cache")
    actual = receipts.get("champions.json") or {}
    if actual.get("sha256") != expected_champions["sha256"]:
        problems.append(
            "data/champions.json changed since the packet asset was reviewed "
            f"(asset sha256 {actual.get('sha256')!r} != current "
            f"{expected_champions['sha256']!r})"
        )
    if not axword_source.is_file():
        problems.append(
            f"Axword Meraki kit source not found ({axword_source}) — supply "
            "--axword-source or LCC_AXWORD_SOURCE"
        )
    else:
        expected_axword = source_receipt(
            axword_source, kind="Axword Meraki ability kits"
        )
        actual_axword = receipts.get("axword_source") or {}
        if actual_axword.get("sha256") != expected_axword["sha256"]:
            problems.append(
                "Axword Meraki kit source changed since the packet asset was "
                f"reviewed (asset sha256 {actual_axword.get('sha256')!r} != "
                f"current {expected_axword['sha256']!r})"
            )

    try:
        cached_names = {
            str(entry.get("name", "")).strip()
            for entry in json.loads(
                champions_source.read_text(encoding="utf-8")
            ).values()
            if isinstance(entry, dict)
        }
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        problems.append(f"champions.json is unreadable: {exc}")
        return problems

    asset_names = set(asset.get("champions") or {})
    for name in sorted(cached_names - asset_names):
        problems.append(
            f"{name} is in data/champions.json but missing from "
            "reviewed-packets.json"
        )
    for name in sorted(asset_names - cached_names):
        problems.append(
            f"{name} is in reviewed-packets.json but missing from "
            "data/champions.json"
        )

    try:
        revisions = _wiki_revisions(wiki_db)
    except RuntimeError as exc:
        problems.append(str(exc))
        return problems

    stale_revisions: list[str] = []
    missing_receipts: list[str] = []
    for name in sorted(asset_names & cached_names):
        entry = asset["champions"][name]
        sources = entry.get("sources") or []
        receipt = next(
            (
                source
                for source in sources
                if isinstance(source, dict) and source.get("revision_id")
            ),
            None,
        )
        if not receipt:
            missing_receipts.append(name)
            continue
        current = revisions.get(name)
        if current is None or current.get("revision_id") != receipt["revision_id"]:
            stale_revisions.append(name)
    if stale_revisions:
        preview = ", ".join(stale_revisions[:5])
        problems.append(
            f"{len(stale_revisions)} champion(s) carry a wiki revision that is "
            f"not current ({preview}{'...' if len(stale_revisions) > 5 else ''}) "
            "— rebuild reviewed packets"
        )
    if missing_receipts:
        preview = ", ".join(missing_receipts[:5])
        problems.append(
            f"{len(missing_receipts)} champion(s) carry no wiki revision "
            f"receipt ({preview}{'...' if len(missing_receipts) > 5 else ''})"
        )
    return problems


# ---------------------------------------------------------------------------
# Patch-day gates (issue #134): audit + staleness run before golden capture
# ---------------------------------------------------------------------------


def run_full_entry_audit(output: Path | None = None) -> int:
    """Run the full parent-entry audit (no --limit); non-zero aborts the run."""
    output = output or DEFAULT_AUDIT_OUTPUT
    print("== Gate: full parent-entry audit ==", flush=True)
    result = subprocess.run(
        [
            sys.executable,
            "scripts/full_entry_audit.py",
            "--output",
            str(output),
        ],
        cwd=REPO_ROOT,
        check=False,
    )
    if result.returncode == 2:
        print(
            "\nFAIL: the full-entry audit could not run (infrastructure). Point\n"
            "LCC_WIKI_QUERY / --query-tool at query_league_wiki.py and re-run.",
            flush=True,
        )
    elif result.returncode != 0:
        print(
            "\nFAIL: the full-entry audit found review-pending entries — resolve\n"
            "them before re-capturing golden.",
            flush=True,
        )
    return result.returncode


def run_staleness_gate(out: Path | None = None, patch: str | None = None) -> int:
    """Compare the wiki cache against game files; non-zero aborts the run."""
    out = out or DEFAULT_STALENESS_OUT
    print("== Gate: staleness vs game files (patch_regression check) ==", flush=True)
    command = [
        sys.executable,
        "scripts/patch_regression.py",
        "check",
        "--out",
        str(out),
    ]
    if patch:
        command += ["--patch", patch]
    result = subprocess.run(command, cwd=REPO_ROOT, check=False)
    if result.returncode == 2:
        print(
            "\nFAIL: staleness gate could not run — cdtb is missing. Install it\n"
            "and set CDTB_BIN, or pin the comparison with --patch <version>.",
            flush=True,
        )
    elif result.returncode != 0:
        print(
            "\nFAIL: the wiki cache is stale vs the game files — update the cache\n"
            "before re-capturing golden.",
            flush=True,
        )
    return result.returncode


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

    print(
        "== Gate: golden compare (diffs below must be explained in the commit) ==",
        flush=True,
    )
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


def run_full(
    *,
    wiki_db: Path | None = None,
    axword_source: Path | None = None,
    audit_output: Path | None = None,
    staleness_out: Path | None = None,
    patch: str | None = None,
):
    """Full patch-day run: pull, audit, rebuild catalogues, gates, capture.

    Order (issue #134 — golden capture stays last and conditional):
    source-completeness audit, catalogue rebuild, reviewed-packet freshness,
    full parent-entry audit, staleness vs game files, then pytest + capture.
    Any gate failure aborts before ``run_gates()`` so a stale packet asset or
    a review-pending entry can never be re-blessed into the new baseline.
    """
    clear_wiki_caches()
    pulled_patch = run_pull()
    print(f"\nPulled patch: {pulled_patch}")
    if not print_audit():
        print(
            "\nFAIL: the item cache lost source coverage. Resolve the BLOCKING\n"
            "entries above before rebuilding artifacts or re-capturing golden."
        )
        return 1
    rebuild_failed = rebuild_static_artifacts()
    if rebuild_failed:
        return rebuild_failed

    packet_problems = check_reviewed_packets_current(
        axword_source=axword_source, wiki_db=wiki_db
    )
    if packet_problems:
        print("\nFAIL: reviewed packets are stale (issue #134):", flush=True)
        for problem in packet_problems:
            print(f"  - {problem}", flush=True)
        print(
            "\nRebuild them with:\n"
            "    python scripts/build_reviewed_modules.py [--wiki-db PATH] "
            "[--axword-source PATH]\n"
            "then re-review the regenerated packets and commit them before "
            "re-running.",
            flush=True,
        )
        return 1

    audit_rc = run_full_entry_audit(audit_output)
    if audit_rc:
        return audit_rc
    staleness_rc = run_staleness_gate(staleness_out, patch)
    if staleness_rc:
        return staleness_rc
    return run_gates()


def main():
    """CLI entry point: run | audit | detail NAME..."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument(
        "--wiki-db",
        type=Path,
        default=None,
        help="Local League Wiki sqlite index (env LCC_WIKI_DB)",
    )
    run.add_argument(
        "--axword-source",
        type=Path,
        default=None,
        help="Axword Meraki kit source (env LCC_AXWORD_SOURCE)",
    )
    run.add_argument(
        "--audit-output",
        type=Path,
        default=None,
        help="full-entry audit receipt path (default docs/wiki-full-entry-audit.json)",
    )
    run.add_argument(
        "--staleness-out",
        type=Path,
        default=None,
        help="staleness receipt path (default data/staleness.json)",
    )
    run.add_argument(
        "--patch",
        default=None,
        help="pin the staleness gate to this patch instead of resolving cdtb",
    )
    commands.add_parser("audit")
    commands.add_parser("detail").add_argument("names", nargs="+")
    args = parser.parse_args()
    if args.command == "run":
        sys.exit(
            run_full(
                wiki_db=args.wiki_db,
                axword_source=args.axword_source,
                audit_output=args.audit_output,
                staleness_out=args.staleness_out,
                patch=args.patch,
            )
        )
    if args.command == "audit":
        sys.exit(0 if print_audit() else 1)
    print_detail(args.names)
    sys.exit(0)


if __name__ == "__main__":
    main()
