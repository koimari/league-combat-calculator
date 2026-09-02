"""Patch-day mechanics: digests, git reads, downloads, diffs, cache refresh.

No CLI and no printing.  ``patch_update.py`` is the one entry point and owns
the report prose, the gates and the argument parser; everything here is a
function it calls, so a test can drive a mechanism without driving the day.

Every network and filesystem edge is an injected parameter defaulted to the
live value, which is what keeps a test off the real ``data/gamefiles/``.
"""

import hashlib
import json
import numbers
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

from scripts import patch_regression
from scripts.source_receipt import source_sha256

DEFAULT_CHAMPIONS = REPO_ROOT / "data" / "champions.json"
DEFAULT_GAME_DIR = REPO_ROOT / "data" / "gamefiles"
DEFAULT_BIN_DIR = REPO_ROOT / "data" / "bin" / "characters"
USER_AGENT = patch_regression.USER_AGENT
# Wiki noise: cosmetic/bookkeeping fields whose churn never affects math.
NOISE_SUBSTRINGS = ("icon", "releaseDate", "patchLastChanged", "price", "salePrice")

# Tracked game-file authority pair: force-added despite the `data/bin/`
# gitignore rule so the Gnar Mega-form gate has committed ground truth
# (data/bin/README.md). `renata.bin.json` is a one-off provenance spot-check
# documented in that README and deliberately NOT git-tracked — fetched here
# for the same spot-check, reported separately, never committed.
AUTHORITY_FILES: dict[str, dict[str, Any]] = {
    "gnar": {
        "url": "https://raw.communitydragon.org/{patch}/game/data/characters/gnar/gnar.bin.json",
        "tracked": True,
    },
    "gnarbig": {
        # Not its own WAD unit — data/bin/README.md's documented fallback:
        # fetched from /latest/ rather than the pinned patch tag.
        "url": "https://raw.communitydragon.org/latest/game/data/characters/gnarbig/gnarbig.bin.json",
        "tracked": True,
    },
    "renata": {
        "url": "https://raw.communitydragon.org/{patch}/game/data/characters/renata/renata.bin.json",
        "tracked": False,
    },
}


# ---------------------------------------------------------------------------
# Digest / git / download helpers
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
    tracked_dir: Path = DEFAULT_BIN_DIR,
) -> list[str]:
    """Tracked authority files a fetch into ``dest_dir`` would clobber while dirty.

    Empty for any scratch destination — only a fetch aimed at the committed
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
    """Validate one fetched JSON file with `jq empty` — fail closed on malformed JSON."""
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
# Diff primitives
# ---------------------------------------------------------------------------

#: One changed leaf: (dotted path, old value, new value); a missing side is None.
LeafChange = tuple[str, object, object]
#: A champions/items table re-keyed by display name.
NameKeyed = dict[str, dict[str, Any]]


def leaf_diffs(old: object, new: object, path: str = "") -> Iterator[LeafChange]:
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
        for index, (o, n) in enumerate(zip(old, new, strict=False)):
            yield from leaf_diffs(o, n, f"{path}[{index}]")
    elif old != new:
        yield (path, old, new)


def drop_noise(diffs: Iterable[LeafChange]) -> list[LeafChange]:
    """Drop diffs on cosmetic/bookkeeping paths (icons, dates, prices)."""
    return [d for d in diffs if not any(s in d[0] for s in NOISE_SUBSTRINGS)]


def is_numeric_diff(diff: LeafChange) -> bool:
    """True when the changed leaf is a number (or a string that parses as one).

    Numeric diffs are the ones that can move calculations; prose diffs
    (descriptions, notes) usually cannot — but for registered champions the
    golden gate is the real arbiter, since custom modules may regex prose.
    """

    def numeric(value: object) -> bool:
        if value is None:
            return True  # added/removed alongside a numeric sibling
        if isinstance(value, bool):
            return False
        if isinstance(value, numbers.Number):
            return True
        if isinstance(value, str):
            try:
                float(value)
            except ValueError:
                return False
            return True
        return False

    _, old, new = diff
    return numeric(old) and numeric(new)


def name_delta(
    old_by_name: Mapping[str, Any], new_by_name: Mapping[str, Any]
) -> tuple[list[str], list[str]]:
    """(added, removed) name lists between two name-keyed dicts."""
    added = sorted(set(new_by_name) - set(old_by_name))
    removed = sorted(set(old_by_name) - set(new_by_name))
    return added, removed


# ---------------------------------------------------------------------------
# Data loading (new = disk cache, old = last committed patch)
# ---------------------------------------------------------------------------


def _load_current(filename: str) -> dict[str, Any]:
    """Load a data file from the on-disk cache (the freshly pulled patch)."""
    with (REPO_ROOT / "data" / filename).open(encoding="utf-8") as f:
        return json.load(f)


def _load_head(filename: str) -> dict[str, Any]:
    """Load the last committed version of a data file via git."""
    result = subprocess.run(
        ["git", "show", f"HEAD:data/{filename}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def _by_display_name(entries: Mapping[str, dict[str, Any]]) -> NameKeyed:
    """Re-key a champions/items dict by its entries' display names."""
    return {entry.get("name", key): entry for key, entry in entries.items()}


def load_old_and_new() -> tuple[NameKeyed, NameKeyed, NameKeyed, NameKeyed]:
    """Returns (old_champs, new_champs, old_items, new_items), name-keyed."""
    return (
        _by_display_name(_load_head("champions.json")),
        _by_display_name(_load_current("champions.json")),
        _by_display_name(_load_head("items.json")),
        _by_display_name(_load_current("items.json")),
    )


# ---------------------------------------------------------------------------
# Game-file evidence: refresh data/gamefiles/ + the tracked authority pair
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
        # regardless of dest_dir — callers (tests) may fetch into a scratch
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
    """Refresh data/gamefiles/ — the exact cache the staleness gate reads.

    Clears each destination before fetching: patch_regression._download()
    skips a file that already exists (its filenames are not patch-versioned),
    so a stale copy from a prior patch would otherwise be served silently to
    the staleness gate — the same reason the wiki pull cache is cleared before
    re-pulling.

    ``game_file_downloader`` defaults to ``patch_regression.download_game_files``
    so this refreshes the exact cache the staleness gate reads (same URLs, same
    atomic-write helper). It is a parameter, not a monkeypatch target: an
    injected fake is the only thing standing between a test and a full live
    roster download into the real ``data/gamefiles/``.
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
        target = champions_dir / f"{patch_regression.champion_dir(name)}.bin.json"
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
        target = champions_dir / f"{patch_regression.champion_dir(name)}.bin.json"
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
                        + " — commit or stash them, or re-run with --force"
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
