"""The patch-day orchestrator: detect, re-pull, rebuild, gate, re-capture.

When a new LoL patch drops, this script does the mechanical part of the
update so the judgment part (deciding whether code must change, explaining
golden diffs in the commit) starts from a focused report:

  1. Pull    — clear lolstaticdata's page caches (a stale cache silently
               "re-pulls" the old patch) and run data_updater.update_data(),
               then refresh data/economics-sourced.json from DDragon for the
               release the new cache pins (refresh_economics_data).
  2. Audit   — diff the new data against the last committed data (git HEAD;
               data/ is tracked, so HEAD *is* the previous patch). Detail is
               limited to what the calculator implements: registered
               champions and items in the parse config, plus net-new /
               removed items shop-wide and a roster add/remove roll-call.
               The economics file is audited for currency the same way.
  3. Rebuild — the derived catalogues the browser fetches, static/bis-profiles.json
               included.
  4. Gates   — reviewed-packet currency, full-entry audit, a game-file refresh,
               staleness (patch_regression), the coverage census, then pytest
               and golden compare. The baseline is re-captured only when every
               gate is green: a stale packet asset, a review-pending entry,
               a stale wiki cache, or an unacknowledged coverage frontier
               entry aborts the run before capture.

Reviewed-packet gate: the checked-in ``static/reviewed-packets.json`` must
prove *both* that it was built from the current sources (the
``data/champions.json`` sha256 and Axword Meraki kit sha256 receipts plus a
current per-champion wiki revision receipt) *and* that a fresh build still
reproduces its slot declarations.  The two catch disjoint drift — changed
sources versus a changed builder — so both run and report together
(``reviewed_packet_report``).  On a real patch day the pull changes those
sources and the gate fails closed with the exact rebuild command; regenerate,
re-review, and commit the packets before re-running.  Sources resolve
portably: ``--wiki-db`` / ``LCC_WIKI_DB`` and ``--axword-source`` /
``LCC_AXWORD_SOURCE``.

This file is the one entry point and owns the report prose, the gates and the
parser.  The mechanisms underneath — digests, git reads, downloads, leaf diffs,
cache loading and the game-file refresh — are ``scripts/patch_mechanics.py``,
which has no CLI, so a test can drive a mechanism without driving the day.

Interpreting the report and finishing the update is the `patch-update`
skill's job (.claude/skills/patch-update/SKILL.md).

Usage:
    python scripts/patch_update.py run             # the full day-0 pipeline
    python scripts/patch_update.py detect          # is a new patch live? (read-only)
    python scripts/patch_update.py audit           # re-print audit, no pull
    python scripts/patch_update.py detail NAME...  # full leaf diff for any
                                                   # champion/item vs HEAD
    python scripts/patch_update.py fetch --patch 16.16   # game-file evidence only
    python scripts/patch_update.py bis                   # bis-profiles only
    python scripts/patch_update.py packets               # packet currency only
    python scripts/patch_update.py run --patch 26.16     # public patch label

``detect`` exits 1 when a new patch is live, so cron is
``detect; [ $? -eq 1 ] && ... run``.

Import contract
---------------
Siblings are imported **only** as ``scripts.X``, and the only ``sys.path``
entry this file adds is the repo root (needed to run as ``python
scripts/patch_update.py``).  Putting ``<repo>/scripts`` on the path as well
would make a bare ``import patch_regression`` bind a *second, distinct*
module object; the fine-grained game-file calls below would then run against
a module no test can reach, downloading a live roster into the real
``data/gamefiles/``.  Every network and filesystem edge is additionally an
injected parameter defaulted to the live value, so tests supply their own
rather than monkeypatching a module attribute.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts import patch_regression
from scripts.build_bis_profiles import build_profiles
from scripts.build_reviewed_modules import (
    _wiki_revisions,
    resolve_axword_source,
    resolve_wiki_db,
)
from scripts.build_reviewed_modules import (
    build as build_reviewed_packets,
)
from scripts.patch_mechanics import (
    DEFAULT_BIN_DIR,
    DEFAULT_CHAMPIONS,
    DEFAULT_GAME_DIR,
    _download_bytes,
    drop_noise,
    is_numeric_diff,
    leaf_diffs,
    load_old_and_new,
    name_delta,
    run_fetch,
)
from scripts.refresh_economics_data import stale_reasons
from scripts.source_receipt import cache_patch, source_receipt
from src.calculator.champions import registered_champion_names
from src.calculator.item_effects import (
    _STATIC_VALUE_KEYS_BY_ITEM,
    ALLY_ITEM_EFFECTS,
)
from src.calculator.item_source import branch_losses, source_audit
from src.calculator.passive_parser import _ITEM_PARSE_CONFIG
from src.calculator.patch_identity import (
    PatchIdentityError,
    canonical_patch,
    client_patch,
)

GOLDEN_BASELINE = REPO_ROOT / "scripts" / "golden_baseline.json"
REVIEWED_PACKETS = REPO_ROOT / "static" / "reviewed-packets.json"
#: Cached-data defects whose only fix route is a re-pull, so this run is their
#: scheduled home and the audit prints them.
ESCALATED_CACHED_DATA = (
    REPO_ROOT / "docs" / "receipts" / "escalated-defects-cached-data.json"
)
DEFAULT_AUDIT_OUTPUT = REPO_ROOT / "docs" / "wiki-full-entry-audit.json"
DEFAULT_STALENESS = REPO_ROOT / "data" / "staleness.json"
DEFAULT_CENSUS_OUTPUT = REPO_ROOT / "docs" / "coverage-census.json"
DEFAULT_BIS_OUTPUT = REPO_ROOT / "static" / "bis-profiles.json"
ECONOMICS_TABLES = REPO_ROOT / "data" / "economics-sourced.json"
CDRAGON_CONTENT_METADATA = (
    "https://raw.communitydragon.org/latest/content-metadata.json"
)
# The two provenance keys every hand-authored ally record carries; the rest
# of the record is the sourced numbers patch day must re-read.
_ALLY_SOURCE_KEYS = frozenset({"source_url", "source_revision_id"})


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


def _flagged_diff_lines(
    name: str, old: Mapping[str, Any], new: Mapping[str, Any]
) -> list[str]:
    """One entry's audit lines, flagged for numeric change; none when unchanged."""
    diffs = drop_noise(list(leaf_diffs(old, new)))
    if not diffs:
        return []
    flag = "NEEDS REVIEW" if any(is_numeric_diff(d) for d in diffs) else "text-only"
    return [f"  {name} ({flag}):", *_detail_lines(diffs)]


def champion_audit_lines(
    old_champs: Mapping[str, Any], new_champs: Mapping[str, Any]
) -> list[str]:
    """Audit section for registered champions plus the roster delta."""
    lines = ["== Registered champions =="]
    for name in registered_champion_names():
        entry_lines = _flagged_diff_lines(
            name, old_champs.get(name), new_champs.get(name)
        )
        if not entry_lines:
            continue
        lines.extend(entry_lines)
    if len(lines) == 1:
        lines.append("  (no changes)")

    added, removed = name_delta(old_champs, new_champs)
    if added or removed:
        lines.append("== Roster delta (new champions need a named module) ==")
        lines.extend(f"  + {name}" for name in added)
        lines.extend(f"  - {name}" for name in removed)
    return lines


def item_audit_lines(
    old_items: Mapping[str, Any], new_items: Mapping[str, Any]
) -> list[str]:
    """Audit section for configured items plus the shop-wide add/remove delta."""
    lines = ["== Configured items =="]
    for name in sorted(_ITEM_PARSE_CONFIG):
        entry_lines = _flagged_diff_lines(
            name, old_items.get(name), new_items.get(name)
        )
        if not entry_lines:
            continue
        lines.extend(entry_lines)
        static_keys = _STATIC_VALUE_KEYS_BY_ITEM.get(name)
        if static_keys:
            lines.append(
                f"    NOTE: code-owned values {sorted(static_keys)} — verify "
                "against the new wiki text (item_effects._REFERENCE_ITEM_EFFECTS)"
            )
    if len(lines) == 1:
        lines.append("  (no changes)")

    added, removed = name_delta(old_items, new_items)
    if added or removed:
        lines.append("== Shop delta ==")
        lines.extend(
            f"  + {name} (new item — consider /add-item-effect)" for name in added
        )
        for name in removed:
            implemented = (
                " ** IMPLEMENTED — code must be updated **"
                if name in _ITEM_PARSE_CONFIG
                else ""
            )
            lines.append(f"  - {name}{implemented}")
    return lines


def item_source_lines(
    old_items: Mapping[str, Any], new_items: Mapping[str, Any]
) -> tuple[list[str], bool]:
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

    lines.extend(f"  note: {warning}" for warning in audit["warnings"])

    if len(lines) == 1:
        lines.append("  (every source branch is accounted for)")
    if blocking:
        lines.append(
            "  ** BLOCKING — verify each entry against Riot/CommunityDragon and "
            "the Wiki, then record it in item_source (APPROVED_BRANCH_REMOVALS "
            "or ACKNOWLEDGED_SOURCE_CONFLICTS) with how you confirmed it. **"
        )
    return lines, not blocking


def _authored_keys(record: Mapping[str, Any]):
    """The hand-typed numeric keys of one ALLY_ITEM_EFFECTS record."""
    return sorted(key for key in record if key not in _ALLY_SOURCE_KEYS)


def ally_effect_lines(
    old_items: Mapping[str, Any], new_items: Mapping[str, Any]
) -> tuple[list[str], bool]:
    """Audit section for the hand-authored cross-participant item values.

    ``ALLY_ITEM_EFFECTS`` is typed by hand from the Wiki and is where four of
    the six ``damage_modifier`` producers read their numbers.  A data refresh
    rewrites ``data/items.json`` and leaves this table exactly where it was:
    it is refresh-**inert**, which is worse than stale-cached, because a
    stale cache at least shows up as a diff while an inert table shows up as
    nothing at all (D-47).  So patch day prints, for every item in that
    table, whether the cached entry it was read from moved.

    Blocking is reserved for an item that left the shop entirely, where the
    hand-authored record now prices something that does not exist.  A moved
    entry is NEEDS REVIEW: the audit's job is to put the numbers in front of
    a human, and ``item_source`` owns the release gate.
    """
    lines = ["== Hand-authored ally item effects =="]
    blocking = False
    for name in sorted(ALLY_ITEM_EFFECTS):
        record = ALLY_ITEM_EFFECTS[name]
        if name not in new_items:
            blocking = True
            lines.append(
                f"  BLOCKING: {name} is no longer in the cached shop, but "
                f"ALLY_ITEM_EFFECTS still prices {_authored_keys(record)}"
            )
            continue
        entry_lines = _flagged_diff_lines(
            name, old_items.get(name), new_items.get(name)
        )
        if not entry_lines:
            continue
        lines.extend(entry_lines)
        lines.append(
            f"    NOTE: hand-authored values {_authored_keys(record)} do not "
            "refresh — re-read the Wiki entry and update "
            "item_effects.ALLY_ITEM_EFFECTS (with its source_revision_id)"
        )
    if len(lines) == 1:
        lines.append("  (every hand-authored ally value's cached entry is unchanged)")
    if blocking:
        lines.append(
            "  ** BLOCKING — an item priced by ALLY_ITEM_EFFECTS left the shop; "
            "remove or re-source its record before continuing. **"
        )
    return lines, not blocking


def escalated_cached_data_lines(receipt_path: Path | None = None) -> list[str]:
    """Audit section for the cached-data defects waiting on a re-pull.

    ``docs/receipts/escalated-defects-cached-data.json`` holds defects in
    cached wiki text that no lane may fix in place: ``data/`` has one writer,
    so hand-editing the cache is a fix the next pull silently reverts.  Their
    scheduled home is therefore this run — it is the only act that rewrites
    the text, and its rebuild step regenerates the two consumers the entries
    name.  A filed defect nobody is told about on the one day somebody can
    act on it is a receipt with a filename, so the run prints them.

    Informational, never blocking: neither defect reaches a damage number
    (rule 5 keeps every runtime item value in ``item_effects.py``), and a
    section that blocked on an upstream text would block every patch day
    until the wiki changed.
    """
    path = receipt_path or ESCALATED_CACHED_DATA
    lines = ["== Cached-data defects scheduled on this run =="]
    if not path.exists():
        lines.append(f"  (no receipt at {path.name})")
        return lines
    receipt = json.loads(path.read_text(encoding="utf-8"))
    for defect in receipt.get("defects", ()):
        home = defect.get("scheduled_home", {})
        lines.append(f"  {defect['id']} (filed {defect['dated']}):")
        lines.append(f"    {defect['what']}")
        lines.append(f"    fires on: {home.get('what_fires_it', '(no home named)')}")
        lines.append(f"    closes by: {home.get('how_it_closes_from_there', '')}")
    if len(lines) == 1:
        lines.append("  (none open)")
    return lines


def economics_lines(
    tables: Mapping[str, Any], new_items: Mapping[str, Any], ddragon_version: str | None
) -> tuple[list[str], bool]:
    """Audit section for the sourced gold table the purchase optimizer prices from.

    ``data/economics-sourced.json`` is DDragon's item gold table pinned to one
    release, written only by ``refresh_economics_data.py``.  A pull that moves
    the cache without it leaves every purchase plan priced at the previous
    patch, and the runtime fails closed on an item it does not carry, so any
    reason the file is not current for the new cache blocks the run.
    """
    lines = ["== Item economics (data/economics-sourced.json) =="]
    reasons = stale_reasons(tables, new_items, ddragon_version)
    lines.extend(f"  BLOCKING: {reason}" for reason in reasons)
    if reasons:
        lines.append(
            "  ** BLOCKING — run scripts/refresh_economics_data.py, or record a "
            "reviewed total divergence in its ACKNOWLEDGED_TOTAL_DIVERGENCES. **"
        )
    else:
        lines.append(
            f"  (current for DDragon {ddragon_version}: every ordinary item priced)"
        )
    return lines, not reasons


def print_audit() -> bool:
    """Print the full audit report (champions, items, deltas).

    Returns whether the source-completeness, hand-authored ally, and item
    economics sections are clear enough to proceed; the prose sections above
    them are informational.
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
    ally_lines, ally_ok = ally_effect_lines(old_items, new_items)
    for line in ally_lines:
        print(line)
    economics, economics_ok = economics_lines(
        json.loads(ECONOMICS_TABLES.read_text(encoding="utf-8")),
        new_items,
        patch_regression.extract_ddragon_version(new_champs),
    )
    for line in economics:
        print(line)
    for line in escalated_cached_data_lines():
        print(line)
    print()
    return source_ok and ally_ok and economics_ok


def print_detail(names: Iterable[str]) -> None:
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
# Detect: is a new patch live? (read-only, no side effects)
# ---------------------------------------------------------------------------


def _extract_client_patch(version_text: str) -> str:
    """Pull a 'MM.mm' client patch label out of a CDragon version string.

    e.g. "16.16.8049184+branch.releases-16-16.content.release" -> "16.16".
    """
    match = re.match(r"^(\d{2})\.(\d{1,2})\b", version_text.strip())
    if not match:
        raise RuntimeError(
            f"unrecognized CommunityDragon version string: {version_text!r}"
        )
    return f"{match.group(1)}.{match.group(2)}"


def fetch_cdragon_live_patch(fetch: Callable[[], bytes] | None = None) -> str:
    """Resolve the live client patch via CDragon's content-metadata endpoint.

    Fallback path when cdtb is not importable/on PATH (verified 2026-08-20:
    cdtb is absent from both .venv and PATH on this machine, so this is the
    live path in practice, not a theoretical one). ``fetch`` is injectable
    for tests — it must return the raw response body bytes.
    """
    if fetch is None:

        def fetch():
            return _download_bytes(CDRAGON_CONTENT_METADATA)

    try:
        payload = json.loads(fetch())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"CommunityDragon content-metadata fetch failed: HTTP {exc.code} "
            f"{exc.reason} ({exc.url})"
        ) from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise RuntimeError(
            f"CommunityDragon content-metadata fetch failed: {exc}"
        ) from exc
    version = payload.get("version") if isinstance(payload, dict) else None
    if not version:
        raise RuntimeError(
            f"CommunityDragon content-metadata carried no 'version' field: {payload!r}"
        )
    return _extract_client_patch(str(version))


def resolve_live_patch(
    *,
    cdtb_bin: str | None = None,
    cdragon_fetch: Callable[[], bytes] | None = None,
    cdtb_resolver: Callable[..., str] | None = None,
) -> tuple[str, str]:
    """The live client patch as ``(patch, source)``, cdtb first and CDragon
    content-metadata as the fallback.  ``cdtb_resolver`` is the injectable
    seam for the cdtb probe, so tests need no monkeypatching."""
    resolver = cdtb_resolver or patch_regression.resolve_patch
    try:
        return resolver(cdtb_bin), "cdtb"
    except RuntimeError:
        pass
    return fetch_cdragon_live_patch(cdragon_fetch), "communitydragon_content_metadata"


def read_cached_patch(staleness_path: Path = DEFAULT_STALENESS) -> str:
    """Read the last-recorded patch from the committed staleness report."""
    staleness_path = Path(staleness_path)
    try:
        raw = json.loads(staleness_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(
            f"cached staleness report unreadable ({staleness_path}): {exc}"
        ) from exc
    patch = raw.get("patch") if isinstance(raw, dict) else None
    if not patch:
        raise RuntimeError(f"{staleness_path} carries no 'patch' field")
    return str(patch)


def detect_report(
    live_patch: str, live_source: str, cached_patch: str
) -> dict[str, Any]:
    """Pure comparison: normalises both labels through patch_identity and compares."""
    try:
        live_identity = canonical_patch(live_patch)
        cached_identity = canonical_patch(cached_patch)
    except PatchIdentityError as exc:
        raise RuntimeError(f"cannot compare patch labels: {exc}") from exc
    is_new = live_identity.client_patch != cached_identity.client_patch
    return {
        "status": "new_patch_available" if is_new else "current",
        "live_patch": live_identity.client_patch,
        "live_patch_source": live_source,
        "cached_patch": cached_identity.client_patch,
        "checked_at": datetime.now(UTC).isoformat(),
    }


def run_detect(
    *,
    cdtb_bin: str | None = None,
    staleness_path: Path = DEFAULT_STALENESS,
    cdragon_fetch: Callable[[], bytes] | None = None,
    cdtb_resolver: Callable[..., str] | None = None,
) -> tuple[dict[str, Any], int]:
    """Returns (report, exit_code): 0 current, 1 new patch available, 2 infra failure."""
    try:
        live_patch, live_source = resolve_live_patch(
            cdtb_bin=cdtb_bin,
            cdragon_fetch=cdragon_fetch,
            cdtb_resolver=cdtb_resolver,
        )
        cached_patch = read_cached_patch(staleness_path)
        report = detect_report(live_patch, live_source, cached_patch)
    except RuntimeError as exc:
        return {"status": "error", "reason": str(exc)}, 2
    return report, (1 if report["status"] == "new_patch_available" else 0)


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


def run_pull() -> str | None:
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


def refresh_economics() -> int:
    """Re-pull DDragon's gold table for the pulled cache; non-zero aborts the run."""
    print("== Refreshing item economics (refresh_economics_data) ==", flush=True)
    result = subprocess.run(
        [sys.executable, "scripts/refresh_economics_data.py"],
        cwd=REPO_ROOT,
        check=False,
    )
    if result.returncode != 0:
        print(
            "\nFAIL: data/economics-sourced.json was not refreshed — DDragon may not\n"
            "have published the release the new cache pins yet. Re-run when it has;\n"
            "the economy engine must not price the new patch from the old table.",
            flush=True,
        )
    return result.returncode


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------


def rebuild_static_artifacts() -> int:
    """Rebuild the derived catalogues the web UI fetches at runtime.

    app.js loads data.json, ability-catalog, bis-profiles, and effect-catalog
    directly, so a patch that refreshes data/ without rebuilding these leaves
    the UI serving the previous patch's champions, abilities and item effects.
    Skipping this step is what left them stale before.

    bis-profiles is rebuilt here too.  It merges an Axword Meraki kit reference
    from a sibling repo supplying damage packets the wiki parser cannot read,
    so ``run_bis`` guards it: an absent kit source, zero champions, zero merged
    packets, or a merged count below the checked-in asset each refuse to write.
    Those invariants are why the rebuild belongs in the run — without them a
    build against a missing sibling drops the packets in silence.
    """
    print("== Rebuilding static catalogues ==", flush=True)
    for builder in (
        "build_static_data.py",
        "build_ability_catalog.py",
        "build_effect_catalog.py",
        # Writes only gitignored trees; it runs here because it fails closed
        # when the unified item-atom domain disagrees with the Atomizer manifest.
        "build_receipts.py",
        # Not a UI catalogue: data/onhit-matrix.json is the wiki's own on-hit
        # application reading, and tests/test_spellblade_on_hit_matrix.py holds
        # it against each module's declaration.  Re-read from the fresh cache
        # here so a patch that flips an ability's on-hit phrasing turns that
        # test red instead of being compared against the previous patch.
        "build_onhit_matrix.py",
    ):
        result = subprocess.run(
            [sys.executable, f"scripts/{builder}"], cwd=REPO_ROOT, check=False
        )
        if result.returncode != 0:
            print(f"FAIL: scripts/{builder} exited {result.returncode}")
            return result.returncode

    print("== Rebuilding static/bis-profiles.json ==", flush=True)
    try:
        # The stamp comes from run_bis's default (source_receipt.cache_patch(),
        # the one home for "the patch the cache pins"), never a caller label
        # in a different version format.
        report = run_bis()
    except RuntimeError as exc:
        print(f"FAIL: bis-profiles rebuild refused: {exc}")
        return 1
    print(
        f"  {report['output']}: {report['champion_count']} champions, "
        f"{report['merged_damage_packets']} merged Meraki damage packets "
        f"(checked-in asset carried {report['baseline_merged_damage_packets']})"
    )
    return 0


# ---------------------------------------------------------------------------
# bis-profiles rebuild
# ---------------------------------------------------------------------------


def run_bis(
    *,
    patch: str | None = None,
    output: Path = DEFAULT_BIS_OUTPUT,
    source: Path = DEFAULT_CHAMPIONS,
    axword_source: Path | None = None,
    baseline: Path | None = DEFAULT_BIS_OUTPUT,
    profile_builder: Callable[[Path, str, Path], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Rebuild static/bis-profiles.json (build_bis_profiles.py wrapper).

    Fails closed if the Axword Meraki merge invariant regresses: the sibling
    repo (LCC_AXWORD_SOURCE) supplies damage packets the wiki parser cannot
    read (24 as of 2026-08-20, tests/test_bis_profiles.py), and a rebuild run
    without the sibling checked out — or against a stale/trimmed copy of it
    — must never silently write fewer packets than the checked-in asset.

    ``patch`` defaults to the patch the cache pins, so a rebuild cannot stamp
    a stale version onto the asset.
    """
    build = profile_builder or build_profiles
    axword_source = Path(axword_source) if axword_source else resolve_axword_source()
    source = Path(source)
    if not axword_source.is_file():
        raise RuntimeError(
            f"Axword Meraki kit source not found: {axword_source}\n"
            "Supply --axword-source or the LCC_AXWORD_SOURCE environment "
            "variable (repo convention: the sibling lol-strength-analysis checkout)."
        )
    if not source.is_file():
        raise RuntimeError(f"champion cache not found: {source}")

    baseline_count = 0
    baseline_path = Path(baseline) if baseline else None
    if baseline_path and baseline_path.is_file():
        try:
            baseline_doc = json.loads(baseline_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            baseline_doc = {}
        baseline_count = int(
            (baseline_doc.get("auxiliary_source") or {}).get("merged_damage_packets", 0)
        )

    profiles = build(source, patch or cache_patch(), axword_source)
    if not profiles["champions"]:
        raise RuntimeError(
            "rebuild produced zero champions — refusing to write an empty "
            "BIS profiles asset"
        )
    merged = int(
        (profiles.get("auxiliary_source") or {}).get("merged_damage_packets", 0)
    )
    if merged == 0:
        raise RuntimeError(
            "auxiliary merge produced zero Meraki damage packets — the "
            f"sibling repo kit source ({axword_source}) may be stale, absent "
            "in content, or the merge silently dropped them; refusing to write"
        )
    if baseline_count and merged < baseline_count:
        raise RuntimeError(
            f"Meraki packet invariant regressed: {merged} merged this run vs "
            f"{baseline_count} in the checked-in asset — packets vanished; "
            "refusing to write"
        )

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(profiles, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return {
        "output": str(output),
        "champion_count": profiles["champion_count"],
        "merged_damage_packets": merged,
        "baseline_merged_damage_packets": baseline_count,
    }


# ---------------------------------------------------------------------------
# Reviewed-packet currency gate: source receipts + a rebuild that reproduces
# ---------------------------------------------------------------------------


def _receipt_problems(
    asset_path: Path,
    champions_source: Path,
    axword_source: Path,
    wiki_db: Path,
) -> list[str]:
    """Reasons the asset's source receipts do not match the tree's sources.

    Empty list means the asset proves it was built from the current sources:
    the ``data/champions.json`` and Axword kit sha256 receipts plus a current
    per-champion wiki revision receipt.
    """
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
    problems.extend(
        f"{name} is in data/champions.json but missing from " "reviewed-packets.json"
        for name in sorted(cached_names - asset_names)
    )
    problems.extend(
        f"{name} is in reviewed-packets.json but missing from " "data/champions.json"
        for name in sorted(asset_names - cached_names)
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


def diff_reviewed_packets(
    fresh: dict[str, Any], checked_in: dict[str, Any]
) -> dict[str, Any]:
    """Per-champion drift between a fresh reviewed-packet build and the checked-in asset.

    Compares each champion's ``slots`` sub-object only — the packet contract
    the engine actually reads — plus ``review_status`` (reviewed_packet vs
    generated_packet). Provenance fields (``sources``, receipts) legitimately
    change on every rebuild and are excluded from drift on purpose; the source
    receipts are what ``_receipt_problems`` answers for.
    """
    fresh_champs = fresh.get("champions", {}) if isinstance(fresh, dict) else {}
    checked_champs = (
        checked_in.get("champions", {}) if isinstance(checked_in, dict) else {}
    )
    names = sorted(set(fresh_champs) | set(checked_champs))
    drifted = []
    review_status_changes = []
    missing = []
    added = []
    for name in names:
        fresh_entry = fresh_champs.get(name)
        checked_entry = checked_champs.get(name)
        if fresh_entry is None:
            missing.append(name)  # rebuild dropped a champion entirely
            continue
        if checked_entry is None:
            added.append(name)  # champion is new since the checked-in asset
            continue
        if fresh_entry.get("review_status") != checked_entry.get("review_status"):
            review_status_changes.append(
                {
                    "champion": name,
                    "checked_in": checked_entry.get("review_status"),
                    "fresh": fresh_entry.get("review_status"),
                }
            )
        slot_diffs = list(
            leaf_diffs(checked_entry.get("slots"), fresh_entry.get("slots"))
        )
        if slot_diffs:
            drifted.append(
                {
                    "champion": name,
                    "diff_count": len(slot_diffs),
                    "diffs": [
                        {"path": path, "checked_in": old, "fresh": new}
                        for path, old, new in slot_diffs[:20]
                    ],
                    "truncated": len(slot_diffs) > 20,
                }
            )
    return {
        "champion_count": len(names),
        "drifted_champion_count": len(drifted),
        "drifted": drifted,
        "review_status_changes": review_status_changes,
        "champions_missing_from_rebuild": missing,
        "champions_new_in_rebuild": added,
        "clean": not (drifted or review_status_changes or missing or added),
    }


def reviewed_packet_report(
    *,
    asset_path: Path | None = None,
    champions_source: Path | None = None,
    axword_source: Path | None = None,
    wiki_db: Path | None = None,
    rebuild: bool = True,
    tmp_output: Path | None = None,
    packet_builder: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """One currency verdict on ``static/reviewed-packets.json``, from two checks.

    They catch disjoint drift, so neither replaces the other and neither is
    made redundant by the import-time ``PACKET_SHA256`` pin (which proves only
    that the 76 packet-backed modules accepted *this* asset, and says nothing
    about whether the asset itself is current):

    * source receipts — the asset was built from different sources than the
      tree now carries (champions.json / Axword kit sha256, per-champion wiki
      revision, roster membership). Catches a data pull; costs a hash.
    * rebuild drift — a fresh build disagrees with the asset's ``slots``.
      Catches a changed *builder* with the sources unchanged, which no receipt
      can see.

    Never writes ``asset_path``: splicing a drifted champion's sub-object back
    in stays a human step through build_reviewed_modules.py, because the other
    suspected drifts have to be re-checked by hand first.
    """
    asset_path = Path(asset_path or REVIEWED_PACKETS)
    champions_source = Path(champions_source or DEFAULT_CHAMPIONS)
    axword_source = Path(axword_source or resolve_axword_source())
    wiki_db = Path(wiki_db or resolve_wiki_db())

    receipts = _receipt_problems(asset_path, champions_source, axword_source, wiki_db)
    report: dict[str, Any] = {
        "asset": str(asset_path),
        "receipt_problems": receipts,
        "rebuild": None,
        "rebuild_skipped": None,
    }
    problems = list(receipts)

    if not rebuild:
        report["rebuild_skipped"] = "rebuild diff not requested"
    else:
        try:
            checked_in = json.loads(asset_path.read_text(encoding="utf-8"))
            fresh = _build_fresh_packets(
                champions_source,
                axword_source,
                wiki_db,
                tmp_output=tmp_output,
                packet_builder=packet_builder,
            )
        except (OSError, ValueError, RuntimeError) as exc:
            # The sources the rebuild needs are the same ones the receipt check
            # already named; record why it could not run rather than inventing
            # a clean verdict.
            report["rebuild_skipped"] = str(exc)
            problems.append(f"reviewed-packet rebuild could not run: {exc}")
        else:
            drift = diff_reviewed_packets(fresh, checked_in)
            report["rebuild"] = drift
            if not drift["clean"]:
                problems.append(
                    f"a fresh reviewed-packet build no longer reproduces the "
                    f"checked-in asset: {drift['drifted_champion_count']} "
                    f"champion(s) drifted, "
                    f"{len(drift['review_status_changes'])} review-status "
                    f"change(s), "
                    f"{len(drift['champions_missing_from_rebuild'])} dropped, "
                    f"{len(drift['champions_new_in_rebuild'])} new"
                )

    report["problems"] = problems
    report["clean"] = not problems
    return report


def _build_fresh_packets(
    champions_source: Path,
    axword_source: Path,
    wiki_db: Path,
    *,
    tmp_output: Path | None = None,
    packet_builder: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Regenerate the reviewed packets to a scratch path and read them back."""
    build = packet_builder or build_reviewed_packets
    if tmp_output is None:
        tmp_output = (
            Path(tempfile.mkdtemp(prefix="patch-update-packets-"))
            / "reviewed-packets.fresh.json"
        )
    tmp_output = Path(tmp_output)
    # build (build_reviewed_modules.build) is already fail closed: missing
    # source/axword, or zero wiki revision receipts, raises RuntimeError naming
    # the exact gap. Let it propagate.
    build(Path(champions_source), axword_source, tmp_output, wiki_db=wiki_db)
    return json.loads(tmp_output.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Patch-day gates: audit + staleness run before golden capture
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
    """Compare the wiki cache against game files; non-zero aborts the run.

    ``patch_regression`` is reached one way throughout this module — imported,
    never shelled out to — because the game-file refresh above needs its
    ``champion_dir`` mapping and ``download_game_files`` at function
    granularity, and a second integration style for the same dependency would
    put that mapping in two places.  ``main`` returns 0/1/2, so it composes
    as a gate directly (a corrupt cache can still raise out of it).
    """
    out = out or DEFAULT_STALENESS
    print("== Gate: staleness vs game files (patch_regression check) ==", flush=True)
    argv = ["check", "--out", str(out)]
    if patch:
        try:
            patch = client_patch(patch)
        except ValueError as exc:
            print(f"\nFAIL: invalid public patch label: {exc}", flush=True)
            return 2
        argv += ["--patch", patch]
    try:
        returncode = patch_regression.main(argv)
    except OSError as exc:
        print(f"\nFAIL: staleness gate could not read its inputs: {exc}", flush=True)
        return 2
    if returncode == 2:
        print(
            "\nFAIL: staleness gate could not run — cdtb is missing. Install it\n"
            "and set CDTB_BIN, or pin the comparison with --patch <version>.",
            flush=True,
        )
    elif returncode != 0:
        print(
            "\nFAIL: the wiki cache is stale vs the game files — update the cache\n"
            "before re-capturing golden.",
            flush=True,
        )
    return returncode


def run_coverage_census(output: Path | None = None) -> int:
    """Sweep every champion x mode/item/keystone cell and refresh its receipt.

    The receipt legitimately moves on patch day, since new items and champions
    change the counts, so the gate is the sweep's own verdict: non-zero means a
    frontier entry no residue row acknowledges, or an acknowledgement that fails
    to reproduce, and it aborts the run.
    """
    output = output or DEFAULT_CENSUS_OUTPUT
    print("== Gate: coverage census (full sweep, ~10 min) ==", flush=True)
    result = subprocess.run(
        [sys.executable, "scripts/coverage_census.py", "run", "--output", str(output)],
        cwd=REPO_ROOT,
        check=False,
    )
    if result.returncode != 0:
        print(
            "\nFAIL: the coverage census reports a frontier entry nothing acknowledges\n"
            "(or a docs/coverage-residue.json row that no longer reproduces) — close\n"
            "it or record it before re-capturing golden.",
            flush=True,
        )
    return result.returncode


def run_gates() -> int:
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


def run_gamefile_refresh(
    patch: str | None,
    *,
    force: bool = False,
    resolver: Callable[[], str] | None = None,
    fetch: Callable[..., tuple[dict[str, Any], int]] | None = None,
) -> int:
    """Re-download data/gamefiles/ before the staleness gate compares against it.

    Not optional and not a convenience: ``patch_regression._download`` skips
    any file that already exists and its filenames are not patch-versioned, so
    without this clearing refresh the staleness gate silently re-compares the
    new wiki cache against the *previous* patch's game files.  Same hazard, and
    the same remedy, as clearing the wiki page cache before the pull.
    """
    print("== Gate: refreshing game-file evidence ==", flush=True)
    if patch:
        try:
            patch = client_patch(patch)
        except ValueError as exc:
            print(f"\nFAIL: invalid public patch label: {exc}", flush=True)
            return 2
    else:
        # Resolve with the same resolver the staleness gate uses so the
        # refresh cannot download a roster the gate then refuses to compare
        # (cdtb absent fails HERE, before any network work).
        try:
            patch = (resolver or patch_regression.resolve_patch)()
        except RuntimeError as exc:
            print(f"\nFAIL: cannot resolve the live patch: {exc}", flush=True)
            return 2
    report, returncode = (fetch or run_fetch)(patch=patch, force=force)
    print(json.dumps(report, indent=2, sort_keys=True), flush=True)
    if returncode:
        print(
            "\nFAIL: the game-file evidence refresh did not complete — the\n"
            "staleness gate would compare against a stale or partial cache.",
            flush=True,
        )
    return returncode


def run_full(
    *,
    wiki_db: Path | None = None,
    axword_source: Path | None = None,
    audit_output: Path | None = None,
    staleness_out: Path | None = None,
    patch: str | None = None,
) -> int:
    """Full patch-day run: pull, audit, rebuild catalogues, gates, capture.

    Order (issue #134 — golden capture stays last and conditional): wiki pull,
    economics refresh, source-completeness audit, catalogue rebuild
    (bis-profiles included), reviewed-packet currency, full parent-entry audit,
    game-file refresh, staleness vs game files, coverage census, then pytest +
    capture.  Any gate failure aborts before ``run_gates()`` so a stale packet
    asset or a review-pending entry can never be re-blessed into the new
    baseline.
    """
    clear_wiki_caches()
    pulled_patch = run_pull()
    print(f"\nPulled patch: {pulled_patch}")
    refresh_rc = refresh_economics()
    if refresh_rc:
        return refresh_rc
    if not print_audit():
        print(
            "\nFAIL: the audit found BLOCKING entries. Resolve them above before\n"
            "rebuilding artifacts or re-capturing golden."
        )
        return 1
    rebuild_failed = rebuild_static_artifacts()
    if rebuild_failed:
        return rebuild_failed

    packets = reviewed_packet_report(axword_source=axword_source, wiki_db=wiki_db)
    if not packets["clean"]:
        print("\nFAIL: reviewed packets are not current (issue #134):", flush=True)
        for problem in packets["problems"]:
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
    gamefile_rc = run_gamefile_refresh(patch)
    if gamefile_rc:
        return gamefile_rc
    staleness_rc = run_staleness_gate(staleness_out, patch)
    if staleness_rc:
        return staleness_rc
    census_rc = run_coverage_census()
    if census_rc:
        return census_rc
    return run_gates()


def _add_run_arguments(run: argparse.ArgumentParser) -> None:
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
        help="pin the game-file and staleness gates to this patch instead of cdtb",
    )


def _build_parser() -> argparse.ArgumentParser:
    """The one CLI: run | detect | audit | detail | fetch | bis | packets."""
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    commands = parser.add_subparsers(dest="command", required=True)
    _add_run_arguments(commands.add_parser("run", help="the full day-0 pipeline"))
    commands.add_parser("audit", help="re-print the audit, no pull")
    commands.add_parser("detail", help="full leaf diff vs HEAD").add_argument(
        "names", nargs="+"
    )

    detect = commands.add_parser("detect", help="is a new patch live? (read-only)")
    detect.add_argument("--cdtb-bin", default=None, help="path to the cdtb CLI")
    detect.add_argument("--staleness-path", type=Path, default=DEFAULT_STALENESS)

    fetch = commands.add_parser("fetch", help="refresh game-file evidence")
    fetch.add_argument("--patch", required=True, help="client patch label, e.g. 16.16")
    fetch.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    fetch.add_argument("--bin-dir", type=Path, default=DEFAULT_BIN_DIR)
    fetch.add_argument("--champions-path", type=Path, default=DEFAULT_CHAMPIONS)
    fetch.add_argument(
        "--champions", help="comma-separated champion names (default: full roster)"
    )
    fetch.add_argument("--limit", type=int, default=None)
    fetch.add_argument("--jq-bin", default="jq")
    fetch.add_argument(
        "--force",
        action="store_true",
        help=(
            "overwrite the tracked authority pair even when it has "
            "uncommitted changes (destroys those local edits)"
        ),
    )

    bis = commands.add_parser("bis", help="rebuild static/bis-profiles.json")
    bis.add_argument("--patch", default=None, help="default: the patch the cache pins")
    bis.add_argument("--output", type=Path, default=DEFAULT_BIS_OUTPUT)
    bis.add_argument("--source", type=Path, default=DEFAULT_CHAMPIONS)
    bis.add_argument("--axword-source", type=Path, default=None)

    packets = commands.add_parser("packets", help="reviewed-packet currency report")
    packets.add_argument("--source", type=Path, default=DEFAULT_CHAMPIONS)
    packets.add_argument("--axword-source", type=Path, default=None)
    packets.add_argument("--wiki-db", type=Path, default=None)
    packets.add_argument("--static-path", type=Path, default=REVIEWED_PACKETS)
    packets.add_argument(
        "--no-rebuild",
        action="store_true",
        help="check the source receipts only; skip the rebuild-and-diff half",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse one subcommand, run it, return its exit code.

    The live defaults (DEFAULT_* paths, real downloaders) are bound here and
    only here — library callers and tests pass their own.  ``run``, ``audit``
    and ``detail`` print for a human; ``detect``, ``fetch``, ``bis`` and
    ``packets`` print one JSON report so they compose with ``jq``.
    """
    args = _build_parser().parse_args(argv)

    if args.command == "run":
        return run_full(
            wiki_db=args.wiki_db,
            axword_source=args.axword_source,
            audit_output=args.audit_output,
            staleness_out=args.staleness_out,
            patch=args.patch,
        )
    if args.command == "audit":
        return 0 if print_audit() else 1
    if args.command == "detail":
        print_detail(args.names)
        return 0

    if args.command == "detect":
        report, code = run_detect(
            cdtb_bin=args.cdtb_bin, staleness_path=args.staleness_path
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        return code

    if args.command == "fetch":
        report, code = run_fetch(
            patch=args.patch,
            game_dir=args.game_dir,
            bin_dir=args.bin_dir,
            champions_path=args.champions_path,
            champion_names=args.champions.split(",") if args.champions else None,
            limit=args.limit,
            jq_bin=args.jq_bin,
            force=args.force,
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        return code

    if args.command == "bis":
        try:
            report = run_bis(
                patch=args.patch,
                output=args.output,
                source=args.source,
                axword_source=args.axword_source,
            )
        except RuntimeError as exc:
            print(json.dumps({"status": "error", "reason": str(exc)}, indent=2))
            return 2
        print(json.dumps({"status": "ok", **report}, indent=2, sort_keys=True))
        return 0

    report = reviewed_packet_report(
        asset_path=args.static_path,
        champions_source=args.source,
        axword_source=args.axword_source,
        wiki_db=args.wiki_db,
        rebuild=not args.no_rebuild,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["clean"]:
        return 1
    # "clean" with the rebuild half skipped is an incomplete check, not a
    # certified pass: 2 means could-not-fully-run, as run_packets always did.
    if not args.no_rebuild and report.get("rebuild_skipped"):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
