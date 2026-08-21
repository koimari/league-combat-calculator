#!/usr/bin/env python3
"""Weekly patch-day ingestion orchestrator (roadmap-100.md §4's four
scriptable manual steps, wired into one cron-able command).

Subcommands:
    detect   Step 1 -- is a new patch live? Read-only, no side effects.
    fetch    Step 2 -- refresh data/gamefiles/ (patch_regression.py's cache)
             plus the tracked game-file authority pair (Gnar/GnarBig).
    bis      Step 3 -- rebuild static/bis-profiles.json (build_bis_profiles.py
             wrapper) with the LCC_AXWORD_SOURCE sibling-repo invariant check.
    packets  Step 4 -- regenerate reviewed packets to a scratch path and
             report per-champion drift against static/reviewed-packets.json.
             Never splices -- splicing a drifted champion stays a human,
             build_reviewed_modules.py-by-hand step (see docs/patch-day-runbook.md).
    all      detect, then -- only if a new patch is live -- fetch, bis,
             packets in order. Machine-readable end to end; intended for cron.

Every subcommand fails closed with a named reason on any missing dependency
or source and never proceeds on partial data. Nothing here commits, stages,
or splices a diff into a tracked file -- that stays Steps 3/4/6/7 of
docs/patch-day-runbook.md, i.e. human triage.

Usage (module form is required -- see "Import contract" below):
    python -m scripts.weekly_ingest detect
    python -m scripts.weekly_ingest fetch --patch 16.16 [--limit 20] [--force]
    python -m scripts.weekly_ingest bis --patch 16.16
    python -m scripts.weekly_ingest packets
    python -m scripts.weekly_ingest all

Import contract
---------------
This module imports its siblings **only** as ``scripts.X`` and never mutates
``sys.path``. That is load-bearing, not style:

``tests/test_patch_update.py`` puts ``<repo>/scripts`` on ``sys.path`` at
import time, so under full-suite ordering a bare ``import patch_regression``
resolves to a *second, distinct* module object from ``scripts.patch_regression``.
An earlier revision of this file had a ``try: import patch_regression /
except ImportError: from scripts import patch_regression`` fallback; whichever
name won the race decided which module object this file called. When the
top-level copy won, every test monkeypatch against ``scripts.patch_regression``
silently missed, ``resolve_patch`` hit the live network, ``run_all`` concluded
a new patch was live, and it ran the real pipeline against the module-level
DEFAULT_* paths -- clobbering data/bin/characters/gnarbig.bin.json,
static/bis-profiles.json and the whole data/gamefiles/ cache from a test run.

Two rules keep that dead:
  1. One import spelling (``scripts.X``), no ``sys.path`` manipulation here.
  2. Every network/filesystem edge is an explicit injected parameter
     (``cdtb_resolver``, ``cdragon_fetch``, ``game_file_downloader``,
     ``authority_downloader``, and every path), defaulted to the live value.
     Tests pass their own values; they never monkeypatch a module attribute
     and never rely on a DEFAULT_* constant.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from scripts import patch_regression
from scripts.build_bis_profiles import build_profiles
from scripts.build_reviewed_modules import (
    build as build_reviewed_packets,
    resolve_axword_source,
    resolve_wiki_db,
)
from scripts.patch_update import leaf_diffs
from scripts.source_receipt import source_sha256
from src.calculator.patch_identity import PatchIdentityError, canonical_patch

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_STALENESS = REPO_ROOT / "data" / "staleness.json"
DEFAULT_CHAMPIONS = REPO_ROOT / "data" / "champions.json"
DEFAULT_GAME_DIR = REPO_ROOT / "data" / "gamefiles"
DEFAULT_BIN_DIR = REPO_ROOT / "data" / "bin" / "characters"
DEFAULT_BIS_OUTPUT = REPO_ROOT / "static" / "bis-profiles.json"
DEFAULT_REVIEWED_PACKETS = REPO_ROOT / "static" / "reviewed-packets.json"

CDRAGON_CONTENT_METADATA = (
    "https://raw.communitydragon.org/latest/content-metadata.json"
)
USER_AGENT = patch_regression.USER_AGENT

# patch_regression._champion_dir is the canonical champion-name -> game-file
# directory mapping and has no public alias. Bound once here so the
# protected-access exemption lives in exactly one place.
_champion_dir = patch_regression._champion_dir  # pylint: disable=protected-access

# Tracked game-file authority pair: force-added despite the `data/bin/`
# gitignore rule so the Gnar Mega-form gate has committed ground truth
# (data/bin/README.md). `renata.bin.json` is a one-off provenance spot-check
# documented in that README and deliberately NOT git-tracked -- fetched here
# for the same spot-check, reported separately, never committed.
AUTHORITY_FILES: dict[str, dict[str, Any]] = {
    "gnar": {
        "url": "https://raw.communitydragon.org/{patch}/game/data/characters/gnar/gnar.bin.json",
        "tracked": True,
    },
    "gnarbig": {
        # Not its own WAD unit -- data/bin/README.md's documented fallback:
        # fetched from /latest/ rather than the pinned patch tag.
        "url": "https://raw.communitydragon.org/latest/game/data/characters/gnarbig/gnarbig.bin.json",
        "tracked": True,
    },
    "renata": {
        "url": "https://raw.communitydragon.org/{patch}/game/data/characters/renata/renata.bin.json",
        "tracked": False,
    },
}

# The git-tracked location of the authority pair. A fetch whose dest_dir
# resolves here is overwriting committed evidence; anywhere else is scratch.
TRACKED_AUTHORITY_DIR = REPO_ROOT / "data" / "bin" / "characters"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _sha256_bytes(data: bytes) -> str:
    """LF-normalised digest, matching source_receipt.source_sha256's convention."""
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def _sha256_path(path: Path) -> str | None:
    """source_sha256, but None for a file that does not (yet) exist."""
    if not path.is_file():
        return None
    return source_sha256(path)


def _git_head_sha256(relative_path: str) -> str | None:
    """sha256 of the LF-normalised bytes tracked at git HEAD, or None if untracked."""
    result = subprocess.run(
        ["git", "show", f"HEAD:{relative_path}"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return _sha256_bytes(result.stdout)


def _git_dirty_paths(
    relative_paths: list[str], *, repo_root: Path = REPO_ROOT
) -> list[str]:
    """Which of ``relative_paths`` have uncommitted index/worktree changes.

    Fails closed: a git invocation that cannot answer raises rather than
    reporting "clean" (a false "clean" is exactly the answer that would let a
    fetch overwrite un-committed human evidence).
    """
    if not relative_paths:
        return []
    result = subprocess.run(
        ["git", "status", "--porcelain", "--", *relative_paths],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "cannot determine whether the tracked authority files are dirty: "
            f"git status failed ({result.stderr.strip() or result.stdout.strip()})"
        )
    dirty = []
    for line in result.stdout.splitlines():
        entry = line[3:].strip()
        if entry:
            # rename entries read "old -> new"; the destination is what matters
            dirty.append(entry.split(" -> ")[-1].strip('"'))
    return sorted(dirty)


def authority_dirty_conflicts(
    dest_dir: Path,
    *,
    repo_root: Path = REPO_ROOT,
    tracked_dir: Path = TRACKED_AUTHORITY_DIR,
) -> list[str]:
    """Tracked authority files a fetch into ``dest_dir`` would clobber while dirty.

    Empty for any scratch destination -- only a fetch aimed at the committed
    ``data/bin/characters/`` location can destroy un-committed evidence.
    """
    if Path(dest_dir).resolve() != Path(tracked_dir).resolve():
        return []
    return _git_dirty_paths(
        [
            f"data/bin/characters/{name}.bin.json"
            for name, spec in AUTHORITY_FILES.items()
            if spec["tracked"]
        ],
        repo_root=repo_root,
    )


def jq_validate(path: Path, jq_bin: str = "jq") -> None:
    """Validate one fetched JSON file with `jq empty` -- fail closed on malformed JSON."""
    try:
        result = subprocess.run(
            [jq_bin, "empty", str(path)], capture_output=True, text=True, check=False
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"jq is not installed / not on PATH (jq_bin={jq_bin!r}): {exc}"
        ) from exc
    if result.returncode != 0:
        raise RuntimeError(
            f"jq validation failed for {path}: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )


def _download_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


# ---------------------------------------------------------------------------
# Step 1 -- detect: is a new patch live? (no side effects)
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
    for tests -- it must return the raw response body bytes.
    """
    if fetch is None:
        fetch = lambda: _download_bytes(CDRAGON_CONTENT_METADATA)
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
        "checked_at": datetime.now(timezone.utc).isoformat(),
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
# Step 2 -- fetch: refresh data/gamefiles/ + the tracked authority pair
# ---------------------------------------------------------------------------


def refresh_authority_files(
    patch: str,
    *,
    dest_dir: Path = DEFAULT_BIN_DIR,
    downloader: Callable[[str], bytes] | None = None,
    jq_bin: str = "jq",
) -> dict[str, Any]:
    """Refresh the Gnar/GnarBig/Renata game-file evidence, reporting sha256 deltas.

    Fails closed per file (404/malformed JSON/jq failure are collected, never
    silently skipped); the caller decides whether any failure blocks the run.
    """
    downloader = downloader or _download_bytes
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, Any] = {}
    failures: list[dict[str, str]] = []
    for name, spec in AUTHORITY_FILES.items():
        dest = dest_dir / f"{name}.bin.json"
        url = spec["url"].format(patch=patch)
        before = _sha256_path(dest)
        # The git-tracked path is fixed (data/bin/characters/<name>.bin.json)
        # regardless of dest_dir -- callers (tests) may fetch into a scratch
        # directory, but the HEAD comparison is always against the real
        # tracked location.
        head_sha = (
            _git_head_sha256(f"data/bin/characters/{name}.bin.json")
            if spec["tracked"]
            else None
        )
        try:
            data = downloader(url)
        except urllib.error.HTTPError as exc:
            failures.append(
                {
                    "file": name,
                    "url": url,
                    "reason": f"HTTP {exc.code} {exc.reason}",
                }
            )
            continue
        except (urllib.error.URLError, OSError) as exc:
            failures.append({"file": name, "url": url, "reason": str(exc)})
            continue
        if not data:
            failures.append({"file": name, "url": url, "reason": "empty response body"})
            continue
        try:
            json.loads(data)
        except ValueError as exc:
            failures.append(
                {"file": name, "url": url, "reason": f"malformed JSON: {exc}"}
            )
            continue
        dest.write_bytes(data)
        try:
            jq_validate(dest, jq_bin=jq_bin)
        except RuntimeError as exc:
            failures.append({"file": name, "url": url, "reason": str(exc)})
            continue
        after = _sha256_path(dest)
        dest_label = (
            str(dest.relative_to(REPO_ROOT))
            if dest.is_relative_to(REPO_ROOT)
            else str(dest)
        )
        files[name] = {
            "path": dest_label,
            "tracked": spec["tracked"],
            "sha256_before_fetch": before,
            "sha256_after_fetch": after,
            "changed_locally": before != after,
            "changed_vs_git_head": (
                (after != head_sha) if head_sha is not None else None
            ),
        }
    return {"files": files, "failures": failures, "ok": not failures}


def _champion_names(champions_path: Path = DEFAULT_CHAMPIONS) -> list[str]:
    try:
        raw = json.loads(Path(champions_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(
            f"champion cache unreadable ({champions_path}): {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise RuntimeError(f"champion cache is not a mapping ({champions_path})")
    return list(raw)


def refresh_gamefiles(
    patch: str,
    *,
    game_dir: Path = DEFAULT_GAME_DIR,
    champion_names: list[str] | None = None,
    champions_path: Path = DEFAULT_CHAMPIONS,
    limit: int | None = None,
    jq_bin: str = "jq",
    game_file_downloader: Callable[[str, Path, list[str]], Any] | None = None,
) -> dict[str, Any]:
    """Refresh data/gamefiles/ -- the exact cache patch_regression.py's `check` reads.

    Clears each destination before fetching: patch_regression._download()
    skips a file that already exists (its filenames are not patch-versioned),
    so a stale copy from a prior patch would otherwise be served silently to
    the next `patch_regression.py check` run -- the same reason
    patch_update.py clears the wiki pull cache before re-pulling.

    ``game_file_downloader`` defaults to ``patch_regression.download_game_files``
    so this refreshes the exact cache ``patch_regression.py check`` reads (same
    URLs, same atomic-write helper). It is a parameter, not a monkeypatch
    target: an injected fake is the only thing standing between a test and a
    full live roster download into the real ``data/gamefiles/``.
    """
    names = (
        list(champion_names)
        if champion_names is not None
        else _champion_names(champions_path)
    )
    if limit:
        names = names[:limit]
    if not names:
        raise RuntimeError("no champions to fetch (empty roster / --champions list)")

    download = game_file_downloader or patch_regression.download_game_files
    game_dir = Path(game_dir)
    champions_dir = game_dir / "characters"
    items_path = game_dir / "items.bin.json"
    champions_dir.mkdir(parents=True, exist_ok=True)

    before: dict[str, str | None] = {}
    for name in names:
        target = champions_dir / f"{_champion_dir(name)}.bin.json"
        before[name] = _sha256_path(target)
        if target.exists():
            target.unlink()
    items_before = _sha256_path(items_path)
    if items_path.exists():
        items_path.unlink()

    try:
        download(patch, game_dir, names)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"game-file fetch failed for patch {patch}: HTTP {exc.code} "
            f"{exc.reason} ({exc.url})"
        ) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise RuntimeError(f"game-file fetch failed for patch {patch}: {exc}") from exc

    changed = []
    unchanged = []
    for name in names:
        target = champions_dir / f"{_champion_dir(name)}.bin.json"
        jq_validate(target, jq_bin=jq_bin)
        after = _sha256_path(target)
        (changed if after != before[name] else unchanged).append(name)
    jq_validate(items_path, jq_bin=jq_bin)
    items_changed = _sha256_path(items_path) != items_before

    game_dir_label = (
        str(game_dir.relative_to(REPO_ROOT))
        if game_dir.is_relative_to(REPO_ROOT)
        else str(game_dir)
    )
    return {
        "patch": patch,
        "champion_count": len(names),
        "changed_champions": changed,
        "unchanged_champions": unchanged,
        "items_changed": items_changed,
        "game_dir": game_dir_label,
    }


def run_fetch(
    *,
    patch: str,
    game_dir: Path = DEFAULT_GAME_DIR,
    bin_dir: Path = DEFAULT_BIN_DIR,
    champions_path: Path = DEFAULT_CHAMPIONS,
    champion_names: list[str] | None = None,
    limit: int | None = None,
    jq_bin: str = "jq",
    authority_downloader: Callable[[str], bytes] | None = None,
    game_file_downloader: Callable[[str, Path, list[str]], Any] | None = None,
    dirty_check: Callable[[Path], list[str]] | None = None,
    force: bool = False,
) -> tuple[dict[str, Any], int]:
    """Returns (report, exit_code): 0 clean, 1 partial (some file failed), 2 hard error.

    Refuses (status "refused", exit 2) when the fetch is aimed at the committed
    ``data/bin/characters/`` pair and those files already carry uncommitted
    changes: a re-fetch would silently destroy hand-verified evidence mid-triage
    (the Gnar Mega delta gate reads exactly those bytes). ``force=True`` is the
    documented escape hatch for "yes, throw my local edits away".
    """
    if not force:
        check = dirty_check or authority_dirty_conflicts
        try:
            conflicts = check(bin_dir)
        except RuntimeError as exc:
            return {"status": "error", "reason": str(exc)}, 2
        if conflicts:
            return (
                {
                    "status": "refused",
                    "reason": (
                        "tracked game-file authority files have uncommitted "
                        "changes and this fetch would overwrite them: "
                        + ", ".join(conflicts)
                        + " -- commit or stash them, or re-run with --force"
                    ),
                    "dirty_paths": conflicts,
                    "patch": patch,
                },
                2,
            )

    try:
        gamefiles = refresh_gamefiles(
            patch,
            game_dir=game_dir,
            champion_names=champion_names,
            champions_path=champions_path,
            limit=limit,
            jq_bin=jq_bin,
            game_file_downloader=game_file_downloader,
        )
    except RuntimeError as exc:
        return {"status": "error", "reason": str(exc)}, 2

    authority = refresh_authority_files(
        patch, dest_dir=bin_dir, downloader=authority_downloader, jq_bin=jq_bin
    )
    report = {
        "status": "ok" if authority["ok"] else "partial",
        "patch": patch,
        "gamefiles": gamefiles,
        "authority_files": authority,
    }
    return report, (0 if authority["ok"] else 1)


# ---------------------------------------------------------------------------
# Step 3 -- bis: rebuild static/bis-profiles.json, guard the Meraki invariant
# ---------------------------------------------------------------------------


def run_bis(
    *,
    patch: str,
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
    without the sibling checked out -- or against a stale/trimmed copy of it
    -- must never silently write fewer packets than the checked-in asset.
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

    profiles = build(source, patch, axword_source)
    if not profiles["champions"]:
        raise RuntimeError(
            "rebuild produced zero champions -- refusing to write an empty "
            "BIS profiles asset"
        )
    merged = int(
        (profiles.get("auxiliary_source") or {}).get("merged_damage_packets", 0)
    )
    if merged == 0:
        raise RuntimeError(
            "auxiliary merge produced zero Meraki damage packets -- the "
            f"sibling repo kit source ({axword_source}) may be stale, absent "
            "in content, or the merge silently dropped them; refusing to write"
        )
    if baseline_count and merged < baseline_count:
        raise RuntimeError(
            f"Meraki packet invariant regressed: {merged} merged this run vs "
            f"{baseline_count} in the checked-in asset -- packets vanished; "
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
# Step 4 -- packets: regen to a scratch path, report drift, never splice
# ---------------------------------------------------------------------------


def diff_reviewed_packets(
    fresh: dict[str, Any], checked_in: dict[str, Any]
) -> dict[str, Any]:
    """Per-champion drift between a fresh reviewed-packet build and the checked-in asset.

    Compares each champion's ``slots`` sub-object only -- the packet contract
    the engine actually reads -- plus ``review_status`` (reviewed_packet vs
    generated_packet). Provenance fields (``sources``, receipts) legitimately
    change on every rebuild and are excluded from drift on purpose.
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


def run_packets(
    *,
    source: Path = DEFAULT_CHAMPIONS,
    axword_source: Path | None = None,
    wiki_db: Path | None = None,
    static_path: Path = DEFAULT_REVIEWED_PACKETS,
    tmp_output: Path | None = None,
    packet_builder: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Regenerate reviewed packets to a scratch path and report drift.

    Never writes ``static_path``: splicing a drifted champion's sub-object
    back in stays a human step through build_reviewed_modules.py, because the
    other suspected drifts have to be re-checked by hand first.
    """
    build = packet_builder or build_reviewed_packets
    axword_source = Path(axword_source) if axword_source else resolve_axword_source()
    wiki_db = Path(wiki_db) if wiki_db else resolve_wiki_db()
    static_path = Path(static_path)
    if not static_path.is_file():
        raise RuntimeError(f"checked-in reviewed packets not found: {static_path}")
    try:
        checked_in = json.loads(static_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"checked-in reviewed packets unreadable: {exc}") from exc

    scratch_dir: Path | None = None
    if tmp_output is None:
        scratch_dir = Path(tempfile.mkdtemp(prefix="weekly-ingest-packets-"))
        tmp_output = scratch_dir / "reviewed-packets.fresh.json"
    tmp_output = Path(tmp_output)

    # build (build_reviewed_modules.build) is already fail closed: missing
    # source/axword, or zero wiki revision receipts, raises RuntimeError naming
    # the exact gap. Let it propagate.
    build(Path(source), axword_source, tmp_output, wiki_db=wiki_db)
    fresh = json.loads(tmp_output.read_text(encoding="utf-8"))

    report = diff_reviewed_packets(fresh, checked_in)
    report["fresh_output"] = str(tmp_output)
    return report


# ---------------------------------------------------------------------------
# all -- detect, then (only if a new patch is live) fetch -> bis -> packets
# ---------------------------------------------------------------------------


def run_all(
    *,
    cdtb_bin: str | None = None,
    staleness_path: Path = DEFAULT_STALENESS,
    cdragon_fetch: Callable[[], bytes] | None = None,
    cdtb_resolver: Callable[..., str] | None = None,
    patch_override: str | None = None,
    fetch_kwargs: dict[str, Any] | None = None,
    bis_kwargs: dict[str, Any] | None = None,
    packets_kwargs: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], int]:
    """Cron entry point: detect, then fetch/bis/packets only when actionable."""
    detect, detect_rc = run_detect(
        cdtb_bin=cdtb_bin,
        staleness_path=staleness_path,
        cdragon_fetch=cdragon_fetch,
        cdtb_resolver=cdtb_resolver,
    )
    result: dict[str, Any] = {"detect": detect}
    if detect_rc == 2:
        result["status"] = "detect_failed"
        return result, 2
    if detect["status"] != "new_patch_available":
        result["status"] = "no_action_needed"
        return result, 0

    patch = patch_override or detect["live_patch"]
    try:
        fetch_report, fetch_rc = run_fetch(patch=patch, **(fetch_kwargs or {}))
        result["fetch"] = fetch_report
        if fetch_rc != 0:
            result["status"] = "fetch_failed"
            return result, fetch_rc

        result["bis"] = run_bis(patch=patch, **(bis_kwargs or {}))
        result["packets"] = run_packets(**(packets_kwargs or {}))
    except RuntimeError as exc:
        result["status"] = "error"
        result["reason"] = str(exc)
        return result, 2

    result["status"] = "ready_for_triage"
    return result, 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: parse one subcommand, print its JSON report, return its code.

    The live defaults (DEFAULT_* paths, real downloaders) are bound here and
    only here -- library callers and tests pass their own.
    """
    parser = argparse.ArgumentParser(
        prog="python -m scripts.weekly_ingest",
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    commands = parser.add_subparsers(dest="command", required=True)

    detect_cmd = commands.add_parser("detect", help="is a new patch live? (read-only)")
    detect_cmd.add_argument("--cdtb-bin", default=None, help="path to the cdtb CLI")
    detect_cmd.add_argument("--staleness-path", type=Path, default=DEFAULT_STALENESS)

    fetch_cmd = commands.add_parser("fetch", help="refresh game-file evidence")
    fetch_cmd.add_argument(
        "--patch", required=True, help="client patch label, e.g. 16.16"
    )
    fetch_cmd.add_argument("--game-dir", type=Path, default=DEFAULT_GAME_DIR)
    fetch_cmd.add_argument("--bin-dir", type=Path, default=DEFAULT_BIN_DIR)
    fetch_cmd.add_argument("--champions-path", type=Path, default=DEFAULT_CHAMPIONS)
    fetch_cmd.add_argument(
        "--champions", help="comma-separated champion names (default: full roster)"
    )
    fetch_cmd.add_argument("--limit", type=int, default=None)
    fetch_cmd.add_argument("--jq-bin", default="jq")
    fetch_cmd.add_argument(
        "--force",
        action="store_true",
        help=(
            "overwrite the tracked authority pair even when it has "
            "uncommitted changes (destroys those local edits)"
        ),
    )

    bis_cmd = commands.add_parser("bis", help="rebuild static/bis-profiles.json")
    bis_cmd.add_argument("--patch", required=True)
    bis_cmd.add_argument("--output", type=Path, default=DEFAULT_BIS_OUTPUT)
    bis_cmd.add_argument("--source", type=Path, default=DEFAULT_CHAMPIONS)
    bis_cmd.add_argument("--axword-source", type=Path, default=None)

    packets_cmd = commands.add_parser("packets", help="report reviewed-packet drift")
    packets_cmd.add_argument("--source", type=Path, default=DEFAULT_CHAMPIONS)
    packets_cmd.add_argument("--axword-source", type=Path, default=None)
    packets_cmd.add_argument("--wiki-db", type=Path, default=None)
    packets_cmd.add_argument(
        "--static-path", type=Path, default=DEFAULT_REVIEWED_PACKETS
    )

    all_cmd = commands.add_parser("all", help="detect, then fetch -> bis -> packets")
    all_cmd.add_argument("--cdtb-bin", default=None)
    all_cmd.add_argument("--staleness-path", type=Path, default=DEFAULT_STALENESS)
    all_cmd.add_argument(
        "--patch", default=None, help="override the detected live patch"
    )

    args = parser.parse_args(argv)

    if args.command == "detect":
        report, code = run_detect(
            cdtb_bin=args.cdtb_bin, staleness_path=args.staleness_path
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        return code

    if args.command == "fetch":
        champion_names = args.champions.split(",") if args.champions else None
        report, code = run_fetch(
            patch=args.patch,
            game_dir=args.game_dir,
            bin_dir=args.bin_dir,
            champions_path=args.champions_path,
            champion_names=champion_names,
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

    if args.command == "packets":
        try:
            report = run_packets(
                source=args.source,
                axword_source=args.axword_source,
                wiki_db=args.wiki_db,
                static_path=args.static_path,
            )
        except RuntimeError as exc:
            print(json.dumps({"status": "error", "reason": str(exc)}, indent=2))
            return 2
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["clean"] else 1

    # args.command == "all"
    report, code = run_all(
        cdtb_bin=args.cdtb_bin,
        staleness_path=args.staleness_path,
        patch_override=args.patch,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
