"""Tests for the weekly patch-day ingestion orchestrator (scripts/weekly_ingest.py).

Covers the four subcommands' pure logic (patch comparison, sha256 diffing,
drift diffing, the Meraki-packet invariant) plus the fail-closed contract on
every subcommand. All network paths are injected: no test in this file makes a
live network call and no test writes anything outside ``tmp_path``.

Hermeticity contract (2026-08-20)
---------------------------------
Two rules, both enforced by tests in this file rather than by convention:

1. **Inject, never monkeypatch a module attribute.** ``tests/test_patch_update.py``
   puts ``<repo>/scripts`` on ``sys.path`` at import time, so under full-suite
   ordering a bare ``import patch_regression`` inside ``scripts/weekly_ingest.py``
   used to bind a *second, distinct* module object from ``scripts.patch_regression``.
   Every ``monkeypatch``-of-a-``patch_regression``-attribute in this file then
   missed the object the code called: ``resolve_patch`` reached the live
   network, ``run_all`` concluded a new patch was live, and it ran the real
   pipeline against ``weekly_ingest``'s module-level DEFAULT_* paths --
   overwriting ``data/bin/characters/gnarbig.bin.json``,
   ``static/bis-profiles.json`` and the whole ``data/gamefiles/`` cache from a
   unit-test run. Injected callables have no second identity to miss.
2. **Every test is tripwired.** ``real_tree_tripwire`` below diffs the real
   repository before and after each test and fails the test that dirtied it.
"""

from __future__ import annotations

import importlib
import json
import sqlite3
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest

import scripts.patch_regression as patch_regression
import scripts.weekly_ingest as weekly_ingest

ROOT = Path(__file__).resolve().parents[1]

# Real-tree paths this module's subject can write. data/gamefiles/ is
# gitignored, so `git status` alone would not notice it being rewritten --
# it gets its own stat fingerprint in the tripwire.
_WATCHED_REAL_PATHS = (
    ROOT / "data" / "gamefiles",
    ROOT / "data" / "bin" / "characters",
    ROOT / "static" / "bis-profiles.json",
    ROOT / "static" / "reviewed-packets.json",
)


# ---------------------------------------------------------------------------
# Hermeticity tripwire
# ---------------------------------------------------------------------------


def _git_status_porcelain() -> frozenset[str]:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return frozenset(line for line in result.stdout.splitlines() if line.strip())


def _watched_fingerprint() -> frozenset[tuple[str, int, int]]:
    """(path, size, mtime_ns) for every file under the at-risk real-tree paths."""
    entries: set[tuple[str, int, int]] = set()
    for root in _WATCHED_REAL_PATHS:
        if root.is_file():
            stat = root.stat()
            entries.add((str(root), stat.st_size, stat.st_mtime_ns))
        elif root.is_dir():
            for path in root.rglob("*"):
                if path.is_file():
                    stat = path.stat()
                    entries.add((str(path), stat.st_size, stat.st_mtime_ns))
    return frozenset(entries)


@pytest.fixture(autouse=True)
def real_tree_tripwire():
    """Fail any test in this file that mutates the real repository tree.

    The hermeticity bug this guards against was silent: the assertions failed
    for unrelated-looking reasons ("KeyError: 'ahri_existed'") while the actual
    damage -- a clobbered, truncated ``data/bin/characters/gnarbig.bin.json``
    and a rewritten ``static/bis-profiles.json`` -- was only visible in
    ``git status`` afterwards. Anything this file writes outside ``tmp_path``
    is a bug in the test, not an acceptable side effect.
    """
    before_git = _git_status_porcelain()
    before_files = _watched_fingerprint()
    yield
    after_git = _git_status_porcelain()
    after_files = _watched_fingerprint()
    if after_git == before_git and after_files == before_files:
        return
    changed_paths = sorted({entry[0] for entry in after_files ^ before_files})
    pytest.fail(
        "this test mutated the real repository tree -- weekly_ingest tests must "
        "be hermetic (tmp_path only).\n"
        f"  git entries appearing:   {sorted(after_git - before_git)}\n"
        f"  git entries disappearing:{sorted(before_git - after_git)}\n"
        f"  watched files touched:   {changed_paths[:20]}"
    )


# ---------------------------------------------------------------------------
# Shared fixtures / injected doubles
# ---------------------------------------------------------------------------


def _never_called(*_args, **_kwargs):
    """A downloader that must not run -- proves a guard fired before any fetch."""
    raise AssertionError("network path reached in a test that must not fetch")


def _write_champions(tmp_path: Path, names=("Fixture", "Other")) -> Path:
    path = tmp_path / "champions.json"
    payload = {name.lower(): {"name": name, "abilities": {}} for name in names}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_axword(tmp_path: Path) -> Path:
    """A Fixture kit carrying one Q damage packet (for the build_bis_profiles
    auxiliary merge -- see test_champions_with_q_ability, its wiki-side pair).
    """
    path = tmp_path / "merakiAbilityKits.ts"
    path.write_text(
        "export const MERAKI_ABILITY_KITS = {\n"
        '  "Fixture": {"name": "Fixture", "abilities": [{"slot": "Q", '
        '"name": "Test Q", "damage": {"base": [10, 20, 30, 40, 50], '
        '"type": "physical", "ratios": [{"stat": "ad", "values": [1.0]}]}}]}\n'
        "}\n"
        "\n"
        # No braces in the IDS constant's value: build_bis_profiles.py's
        # _load_meraki_kits() slices up to the LAST "}" in the whole file
        # (unlike build_reviewed_modules.py's marker-bounded _load_axword()),
        # so this fixture must satisfy both parsers' conventions at once.
        "export const MERAKI_ABILITY_KIT_IDS = 0;\n",
        encoding="utf-8",
    )
    return path


def _write_champions_with_q_ability(tmp_path: Path, names=("Fixture",)) -> Path:
    """A champion cache with an empty-packet Q slot -- the merge target the
    Axword auxiliary fixture (_write_axword) fills in."""
    path = tmp_path / "champions-with-q.json"
    payload = {
        name.lower(): {
            "name": name,
            "abilities": {
                "P": [],
                "Q": [{"name": "Test Q", "effects": []}],
                "W": [],
                "E": [],
                "R": [],
            },
        }
        for name in names
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_wiki_db(tmp_path: Path, receipts=None, name="wiki.sqlite3") -> Path:
    db = tmp_path / name
    conn = sqlite3.connect(db)
    conn.execute("DROP TABLE IF EXISTS pages")
    conn.execute(
        "CREATE TABLE pages ("
        "title TEXT, revision_id INTEGER, revision_timestamp TEXT, namespace INTEGER)"
    )
    for title, revision in (receipts or {}).items():
        conn.execute(
            "INSERT INTO pages VALUES (?, ?, '2026-01-01T00:00:00Z', 0)",
            (title, revision),
        )
    conn.commit()
    conn.close()
    return db


def _write_staleness(tmp_path: Path, patch: str) -> Path:
    path = tmp_path / "staleness.json"
    path.write_text(json.dumps({"patch": patch}), encoding="utf-8")
    return path


def _fake_game_file_downloader(_patch, target_dir, names):
    """Stand-in for patch_regression.download_game_files (writes, never fetches)."""
    target_dir = Path(target_dir)
    (target_dir / "characters").mkdir(parents=True, exist_ok=True)
    for name in names:
        (target_dir / "characters" / f"{name.lower()}.bin.json").write_text(
            json.dumps({"name": name}), encoding="utf-8"
        )
    (target_dir / "items.bin.json").write_text(json.dumps({"items": []}))
    return target_dir


def _scratch_git_repo(tmp_path: Path) -> Path:
    """A throwaway git repo carrying a committed authority pair.

    Lets the dirty-tree guard be tested end to end -- real ``git status``
    parsing included -- without ever dirtying the real repository.
    """
    repo = tmp_path / "scratch-repo"
    characters = repo / "data" / "bin" / "characters"
    characters.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "tests@example.test"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "tests"], cwd=repo, check=True)
    for name in ("gnar", "gnarbig"):
        (characters / f"{name}.bin.json").write_text('{"v": 1}', encoding="utf-8")
    # `git add -A` is safe here and only here: `repo` is a scratch repository
    # under tmp_path, not the project checkout.
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "seed"], cwd=repo, check=True)
    return repo


class _HTTPErrorFactory:
    @staticmethod
    def make(code=404, reason="Not Found", url="https://example.test/x"):
        return urllib.error.HTTPError(url, code, reason, hdrs=None, fp=None)


# ---------------------------------------------------------------------------
# Import hygiene: exactly one module identity, no sys.path mutation
# ---------------------------------------------------------------------------


class TestImportHygiene:
    def test_module_never_mutates_sys_path(self):
        """A script that edits sys.path is how the second identity got created."""
        source = (ROOT / "scripts" / "weekly_ingest.py").read_text(encoding="utf-8")
        mutations = [
            line.strip()
            for line in source.splitlines()
            if any(
                token in line
                for token in (
                    "sys.path.insert",
                    "sys.path.append",
                    "sys.path.extend",
                    "sys.path =",
                    "sys.path +=",
                )
            )
        ]
        assert mutations == []

    def test_scripts_dir_on_sys_path_cannot_create_a_second_sibling_identity(
        self, monkeypatch
    ):
        """The exact full-suite hazard, reproduced then asserted away.

        tests/test_patch_update.py prepends <repo>/scripts to sys.path, which
        makes a bare ``patch_regression`` importable as a distinct module. The
        orchestrator must still call the ``scripts.`` one.
        """
        had_impostor = "patch_regression" in sys.modules
        monkeypatch.syspath_prepend(str(ROOT / "scripts"))
        try:
            impostor = importlib.import_module("patch_regression")
            # sanity: the hazard is real -- these are genuinely two objects
            assert impostor is not patch_regression
            reloaded = importlib.reload(weekly_ingest)
            assert reloaded.patch_regression is patch_regression
            assert reloaded.build_profiles.__module__ == "scripts.build_bis_profiles"
            assert (
                reloaded.build_reviewed_packets.__module__
                == "scripts.build_reviewed_modules"
            )
            assert reloaded.leaf_diffs.__module__ == "scripts.patch_update"
            assert reloaded.source_sha256.__module__ == "scripts.source_receipt"
        finally:
            if not had_impostor:
                sys.modules.pop("patch_regression", None)

    def test_this_file_injects_rather_than_patching_module_attributes(self):
        """No monkeypatched module attributes and no DEFAULT_* reliance here."""
        source = Path(__file__).read_text(encoding="utf-8")
        # Needles are assembled at runtime so this assertion does not match
        # its own source line.
        setattr_call = "monkeypatch" + ".setattr("
        default_constant = "weekly_ingest." + "DEFAULT_"
        assert setattr_call not in source
        assert default_constant not in source

    def test_runnable_as_a_module(self):
        """`python -m scripts.weekly_ingest` is the documented invocation."""
        result = subprocess.run(
            [sys.executable, "-m", "scripts.weekly_ingest", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "python -m scripts.weekly_ingest" in result.stdout


# ---------------------------------------------------------------------------
# Step 1: detect (pure comparison + patch resolution)
# ---------------------------------------------------------------------------


class TestExtractClientPatch:
    def test_parses_the_cdragon_content_metadata_shape(self):
        version = "16.16.8049184+branch.releases-16-16.content.release"
        assert weekly_ingest._extract_client_patch(version) == "16.16"

    def test_single_digit_minor_is_kept_unpadded(self):
        assert weekly_ingest._extract_client_patch("16.5.1234") == "16.5"

    def test_unrecognized_string_raises(self):
        with pytest.raises(RuntimeError, match="unrecognized"):
            weekly_ingest._extract_client_patch("not-a-version")


class TestFetchCdragonLivePatch:
    def test_happy_path_returns_client_patch(self):
        fetch = lambda: json.dumps({"version": "16.16.8049184+x"}).encode()
        assert weekly_ingest.fetch_cdragon_live_patch(fetch) == "16.16"

    def test_missing_version_field_fails_closed(self):
        fetch = lambda: json.dumps({"nope": True}).encode()
        with pytest.raises(RuntimeError, match="no 'version' field"):
            weekly_ingest.fetch_cdragon_live_patch(fetch)

    def test_http_error_fails_closed_with_status(self):
        def fetch():
            raise _HTTPErrorFactory.make(code=503, reason="Service Unavailable")

        with pytest.raises(RuntimeError, match="503"):
            weekly_ingest.fetch_cdragon_live_patch(fetch)

    def test_malformed_json_fails_closed(self):
        fetch = lambda: b"{not json"
        with pytest.raises(RuntimeError, match="content-metadata fetch failed"):
            weekly_ingest.fetch_cdragon_live_patch(fetch)


class TestResolveLivePatch:
    def test_prefers_cdtb_when_available(self):
        patch, source = weekly_ingest.resolve_live_patch(
            cdtb_resolver=lambda *_a, **_k: "16.16",
            cdragon_fetch=_never_called,
        )
        assert (patch, source) == ("16.16", "cdtb")

    def test_falls_back_to_cdragon_when_cdtb_missing(self):
        def boom(*_a, **_k):
            raise RuntimeError("cdtb not found")

        fetch = lambda: json.dumps({"version": "16.16.999+x"}).encode()
        patch, source = weekly_ingest.resolve_live_patch(
            cdtb_resolver=boom, cdragon_fetch=fetch
        )
        assert (patch, source) == ("16.16", "communitydragon_content_metadata")

    def test_default_resolver_is_the_scripts_package_one(self):
        """The live default must be the single ``scripts.`` identity."""
        assert weekly_ingest.patch_regression.resolve_patch is (
            patch_regression.resolve_patch
        )


class TestReadCachedPatch:
    def test_reads_the_patch_field(self, tmp_path):
        path = _write_staleness(tmp_path, "16.15")
        assert weekly_ingest.read_cached_patch(path) == "16.15"

    def test_missing_file_fails_closed(self, tmp_path):
        with pytest.raises(RuntimeError, match="unreadable"):
            weekly_ingest.read_cached_patch(tmp_path / "absent.json")

    def test_missing_patch_field_fails_closed(self, tmp_path):
        path = tmp_path / "staleness.json"
        path.write_text(json.dumps({"checked_at": "x"}), encoding="utf-8")
        with pytest.raises(RuntimeError, match="no 'patch' field"):
            weekly_ingest.read_cached_patch(path)


class TestDetectReport:
    def test_same_patch_is_current(self):
        report = weekly_ingest.detect_report("16.16", "cdtb", "16.16")
        assert report["status"] == "current"
        assert report["live_patch"] == "16.16"
        assert report["cached_patch"] == "16.16"

    def test_different_patch_is_new_patch_available(self):
        report = weekly_ingest.detect_report("16.16", "cdtb", "16.15")
        assert report["status"] == "new_patch_available"

    def test_public_and_client_labels_normalize_to_the_same_identity(self):
        """26.16 (public) and 16.16 (client) name the same patch."""
        report = weekly_ingest.detect_report("16.16", "cdtb", "26.16")
        assert report["status"] == "current"

    def test_malformed_label_fails_closed(self):
        with pytest.raises(RuntimeError, match="cannot compare patch labels"):
            weekly_ingest.detect_report("not-a-patch", "cdtb", "16.16")


class TestRunDetect:
    def test_current_returns_exit_0(self, tmp_path):
        staleness = _write_staleness(tmp_path, "16.15")
        report, code = weekly_ingest.run_detect(
            staleness_path=staleness,
            cdtb_resolver=lambda *_a, **_k: "16.15",
            cdragon_fetch=_never_called,
        )
        assert code == 0
        assert report["status"] == "current"

    def test_new_patch_returns_exit_1(self, tmp_path):
        staleness = _write_staleness(tmp_path, "16.15")
        report, code = weekly_ingest.run_detect(
            staleness_path=staleness,
            cdtb_resolver=lambda *_a, **_k: "16.16",
            cdragon_fetch=_never_called,
        )
        assert code == 1
        assert report["status"] == "new_patch_available"

    def test_no_side_effects_on_disk(self, tmp_path):
        """detect is read-only: it must not write anything under tmp_path."""
        staleness = _write_staleness(tmp_path, "16.15")
        before = sorted(p.name for p in tmp_path.iterdir())
        weekly_ingest.run_detect(
            staleness_path=staleness,
            cdtb_resolver=lambda *_a, **_k: "16.16",
            cdragon_fetch=_never_called,
        )
        after = sorted(p.name for p in tmp_path.iterdir())
        assert before == after

    def test_infra_failure_returns_exit_2(self, tmp_path):
        def boom(*_a, **_k):
            raise RuntimeError("cdtb not found")

        def fetch_boom():
            raise _HTTPErrorFactory.make(code=500, reason="Internal Server Error")

        staleness = _write_staleness(tmp_path, "16.15")
        report, code = weekly_ingest.run_detect(
            staleness_path=staleness, cdtb_resolver=boom, cdragon_fetch=fetch_boom
        )
        assert code == 2
        assert report["status"] == "error"

    def test_missing_staleness_file_is_infra_failure(self, tmp_path):
        report, code = weekly_ingest.run_detect(
            staleness_path=tmp_path / "absent.json",
            cdtb_resolver=lambda *_a, **_k: "16.16",
            cdragon_fetch=_never_called,
        )
        assert code == 2
        assert report["status"] == "error"


# ---------------------------------------------------------------------------
# Step 2: fetch (jq validation + sha256 diffing + fail-closed on failure)
# ---------------------------------------------------------------------------


class TestJqValidate:
    def test_valid_json_passes(self, tmp_path):
        path = tmp_path / "ok.json"
        path.write_text('{"a": 1}', encoding="utf-8")
        weekly_ingest.jq_validate(path)  # must not raise

    def test_malformed_json_fails_closed(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(RuntimeError, match="jq validation failed"):
            weekly_ingest.jq_validate(path)

    def test_missing_jq_binary_fails_closed_with_actionable_message(self, tmp_path):
        path = tmp_path / "ok.json"
        path.write_text('{"a": 1}', encoding="utf-8")
        with pytest.raises(RuntimeError, match="jq is not installed"):
            weekly_ingest.jq_validate(path, jq_bin="definitely-not-a-real-binary-xyz")


class TestRefreshAuthorityFiles:
    def test_fetches_all_three_files_and_reports_sha256(self, tmp_path):
        payloads = {
            "gnar": b'{"gnar": 1}',
            "gnarbig": b'{"gnarbig": 1}',
            "renata": b'{"renata": 1}',
        }

        def downloader(url):
            # Longest name first: "gnar" is a substring of "gnarbig"'s URL.
            for name in sorted(payloads, key=len, reverse=True):
                if name in url:
                    return payloads[name]
            raise AssertionError(f"unexpected url: {url}")

        report = weekly_ingest.refresh_authority_files(
            "16.16", dest_dir=tmp_path, downloader=downloader
        )
        assert report["ok"] is True
        assert set(report["files"]) == {"gnar", "gnarbig", "renata"}
        for name, payload in payloads.items():
            entry = report["files"][name]
            assert entry["sha256_before_fetch"] is None
            assert entry["sha256_after_fetch"] == weekly_ingest._sha256_bytes(payload)
            assert entry["changed_locally"] is True
        assert report["files"]["gnar"]["tracked"] is True
        assert report["files"]["renata"]["tracked"] is False

    def test_unchanged_refetch_reports_changed_locally_false(self, tmp_path):
        def downloader(_url):
            return b'{"stable": 1}'

        weekly_ingest.refresh_authority_files(
            "16.16", dest_dir=tmp_path, downloader=downloader
        )
        second = weekly_ingest.refresh_authority_files(
            "16.16", dest_dir=tmp_path, downloader=downloader
        )
        for entry in second["files"].values():
            assert entry["changed_locally"] is False

    def test_http_404_is_collected_as_a_failure_not_raised(self, tmp_path):
        def downloader(url):
            if "gnarbig" in url:
                raise _HTTPErrorFactory.make(code=404, reason="Not Found", url=url)
            return b'{"ok": 1}'

        report = weekly_ingest.refresh_authority_files(
            "16.16", dest_dir=tmp_path, downloader=downloader
        )
        assert report["ok"] is False
        assert len(report["failures"]) == 1
        assert report["failures"][0]["file"] == "gnarbig"
        assert "404" in report["failures"][0]["reason"]
        # the two files that succeeded are still reported
        assert set(report["files"]) == {"gnar", "renata"}

    def test_malformed_json_response_is_a_failure_not_a_write(self, tmp_path):
        def downloader(_url):
            return b"{not json"

        report = weekly_ingest.refresh_authority_files(
            "16.16", dest_dir=tmp_path, downloader=downloader
        )
        assert report["ok"] is False
        assert not (tmp_path / "gnar.bin.json").exists()

    def test_tracked_file_diffs_against_git_head(self, tmp_path):
        """gnar.bin.json is git-tracked; a fetch matching HEAD reports no drift."""
        head_bytes = (
            ROOT / "data" / "bin" / "characters" / "gnar.bin.json"
        ).read_bytes()

        def downloader(url):
            if "gnarbig" in url:
                return b'{"gnarbig": 1}'
            if "renata" in url:
                return b'{"renata": 1}'
            return head_bytes

        report = weekly_ingest.refresh_authority_files(
            "16.16", dest_dir=tmp_path, downloader=downloader
        )
        assert report["files"]["gnar"]["changed_vs_git_head"] is False
        # renata is not git-tracked -- there is no HEAD copy to diff against
        assert report["files"]["renata"]["changed_vs_git_head"] is None


# ---------------------------------------------------------------------------
# Step 2 guard: refuse to clobber a dirty tracked authority pair
# ---------------------------------------------------------------------------


class TestAuthorityDirtyGuard:
    def test_no_paths_is_clean(self):
        assert weekly_ingest._git_dirty_paths([]) == []

    def test_clean_tracked_pair_reports_no_conflict(self, tmp_path):
        repo = _scratch_git_repo(tmp_path)
        characters = repo / "data" / "bin" / "characters"
        assert (
            weekly_ingest.authority_dirty_conflicts(
                characters, repo_root=repo, tracked_dir=characters
            )
            == []
        )

    def test_dirty_tracked_file_is_reported(self, tmp_path):
        repo = _scratch_git_repo(tmp_path)
        characters = repo / "data" / "bin" / "characters"
        (characters / "gnarbig.bin.json").write_text('{"v": 2}', encoding="utf-8")
        assert weekly_ingest.authority_dirty_conflicts(
            characters, repo_root=repo, tracked_dir=characters
        ) == ["data/bin/characters/gnarbig.bin.json"]

    def test_scratch_destination_is_never_a_conflict(self, tmp_path):
        """A fetch into a scratch dir cannot destroy committed evidence."""
        repo = _scratch_git_repo(tmp_path)
        characters = repo / "data" / "bin" / "characters"
        (characters / "gnarbig.bin.json").write_text('{"v": 2}', encoding="utf-8")
        assert (
            weekly_ingest.authority_dirty_conflicts(
                tmp_path / "elsewhere", repo_root=repo, tracked_dir=characters
            )
            == []
        )

    def test_unanswerable_git_query_fails_closed(self, tmp_path):
        outside = tmp_path / "not-a-repo"
        outside.mkdir()
        probe = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=outside,
            capture_output=True,
            check=False,
        )
        if probe.returncode == 0:
            pytest.skip("tmp_path lives inside a git repository on this machine")
        with pytest.raises(RuntimeError, match="cannot determine whether"):
            weekly_ingest._git_dirty_paths(
                ["data/bin/characters/gnar.bin.json"], repo_root=outside
            )

    def test_run_fetch_refuses_before_touching_anything(self, tmp_path):
        report, code = weekly_ingest.run_fetch(
            patch="16.16",
            champions_path=_write_champions(tmp_path, ("Ahri",)),
            game_dir=tmp_path / "gamefiles",
            bin_dir=tmp_path / "bin",
            dirty_check=lambda _dest: ["data/bin/characters/gnarbig.bin.json"],
            game_file_downloader=_never_called,
            authority_downloader=_never_called,
        )
        assert code == 2
        assert report["status"] == "refused"
        assert report["dirty_paths"] == ["data/bin/characters/gnarbig.bin.json"]
        assert "--force" in report["reason"]
        # refused before creating even the destination directories
        assert not (tmp_path / "gamefiles").exists()
        assert not (tmp_path / "bin").exists()

    def test_force_overrides_the_refusal(self, tmp_path):
        report, code = weekly_ingest.run_fetch(
            patch="16.16",
            champions_path=_write_champions(tmp_path, ("Ahri",)),
            game_dir=tmp_path / "gamefiles",
            bin_dir=tmp_path / "bin",
            dirty_check=_never_called,  # not even consulted under --force
            game_file_downloader=_fake_game_file_downloader,
            authority_downloader=lambda _url: b"{}",
            force=True,
        )
        assert code == 0
        assert report["status"] == "ok"

    def test_unanswerable_dirty_check_blocks_the_fetch(self, tmp_path):
        def boom(_dest):
            raise RuntimeError("git status failed")

        report, code = weekly_ingest.run_fetch(
            patch="16.16",
            champions_path=_write_champions(tmp_path, ("Ahri",)),
            game_dir=tmp_path / "gamefiles",
            bin_dir=tmp_path / "bin",
            dirty_check=boom,
            game_file_downloader=_never_called,
            authority_downloader=_never_called,
        )
        assert code == 2
        assert report["status"] == "error"


class TestChampionNames:
    def test_reads_keys_from_the_cache(self, tmp_path):
        path = _write_champions(tmp_path, ("Ahri", "Zed"))
        assert set(weekly_ingest._champion_names(path)) == {"ahri", "zed"}

    def test_missing_cache_fails_closed(self, tmp_path):
        with pytest.raises(RuntimeError, match="unreadable"):
            weekly_ingest._champion_names(tmp_path / "absent.json")


class TestRefreshGamefiles:
    def test_delegates_to_the_injected_downloader_and_reports_changes(self, tmp_path):
        champions = _write_champions(tmp_path, ("Ahri", "Zed"))
        report = weekly_ingest.refresh_gamefiles(
            "16.16",
            game_dir=tmp_path / "gamefiles",
            champions_path=champions,
            game_file_downloader=_fake_game_file_downloader,
        )
        assert report["champion_count"] == 2
        assert set(report["changed_champions"]) == {"ahri", "zed"}
        assert report["items_changed"] is True

    def test_clears_stale_copy_before_fetching(self, tmp_path):
        """A prior patch's cached bin must not be silently served for the new patch."""
        champions = _write_champions(tmp_path, ("Ahri",))
        game_dir = tmp_path / "gamefiles"
        (game_dir / "characters").mkdir(parents=True)
        stale_path = game_dir / "characters" / "ahri.bin.json"
        stale_path.write_text(json.dumps({"stale": True}), encoding="utf-8")
        seen_existing = {}

        def recording_download(_patch, target_dir, names):
            target_dir = Path(target_dir)
            seen_existing["ahri_existed"] = (
                target_dir / "characters" / "ahri.bin.json"
            ).exists()
            (target_dir / "characters").mkdir(parents=True, exist_ok=True)
            for name in names:
                (target_dir / "characters" / f"{name.lower()}.bin.json").write_text(
                    json.dumps({"fresh": True})
                )
            (target_dir / "items.bin.json").write_text(json.dumps({}))
            return target_dir

        weekly_ingest.refresh_gamefiles(
            "16.16",
            game_dir=game_dir,
            champions_path=champions,
            game_file_downloader=recording_download,
        )
        assert seen_existing["ahri_existed"] is False
        assert json.loads(stale_path.read_text())["fresh"] is True

    def test_empty_roster_fails_closed(self, tmp_path):
        champions = _write_champions(tmp_path, ())
        with pytest.raises(RuntimeError, match="no champions to fetch"):
            weekly_ingest.refresh_gamefiles(
                "16.16",
                game_dir=tmp_path / "gamefiles",
                champions_path=champions,
                game_file_downloader=_never_called,
            )

    def test_http_error_fails_closed(self, tmp_path):
        champions = _write_champions(tmp_path, ("Ahri",))

        def failing_download(_patch, _target_dir, _names):
            raise _HTTPErrorFactory.make(code=404, reason="Not Found")

        with pytest.raises(RuntimeError, match="game-file fetch failed"):
            weekly_ingest.refresh_gamefiles(
                "16.16",
                game_dir=tmp_path / "gamefiles",
                champions_path=champions,
                game_file_downloader=failing_download,
            )

    def test_default_downloader_is_the_scripts_package_one(self):
        """The live default must be the single ``scripts.`` identity."""
        assert weekly_ingest.patch_regression.download_game_files is (
            patch_regression.download_game_files
        )


class TestRunFetch:
    def test_hard_failure_in_gamefiles_returns_exit_2(self, tmp_path):
        report, code = weekly_ingest.run_fetch(
            patch="16.16",
            champions_path=tmp_path / "absent.json",
            game_dir=tmp_path / "gamefiles",
            bin_dir=tmp_path / "bin",
            game_file_downloader=_never_called,
            authority_downloader=_never_called,
        )
        assert code == 2
        assert report["status"] == "error"

    def test_partial_authority_failure_returns_exit_1(self, tmp_path):
        def flaky_downloader(url):
            if "gnarbig" in url:
                raise _HTTPErrorFactory.make(code=404)
            return b"{}"

        report, code = weekly_ingest.run_fetch(
            patch="16.16",
            champions_path=_write_champions(tmp_path, ("Ahri",)),
            game_dir=tmp_path / "gamefiles",
            bin_dir=tmp_path / "bin",
            game_file_downloader=_fake_game_file_downloader,
            authority_downloader=flaky_downloader,
        )
        assert code == 1
        assert report["status"] == "partial"

    def test_clean_run_returns_exit_0(self, tmp_path):
        report, code = weekly_ingest.run_fetch(
            patch="16.16",
            champions_path=_write_champions(tmp_path, ("Ahri",)),
            game_dir=tmp_path / "gamefiles",
            bin_dir=tmp_path / "bin",
            game_file_downloader=_fake_game_file_downloader,
            authority_downloader=lambda _url: b"{}",
        )
        assert code == 0
        assert report["status"] == "ok"


# ---------------------------------------------------------------------------
# Step 3: bis (Meraki packet invariant)
# ---------------------------------------------------------------------------


class TestRunBis:
    def test_missing_axword_source_fails_closed(self, tmp_path):
        champions = _write_champions(tmp_path)
        with pytest.raises(RuntimeError, match="Axword Meraki kit source not found"):
            weekly_ingest.run_bis(
                patch="26.16",
                source=champions,
                axword_source=tmp_path / "absent-merakiAbilityKits.ts",
                output=tmp_path / "out.json",
                baseline=None,
            )

    def test_missing_champion_cache_fails_closed(self, tmp_path):
        axword = _write_axword(tmp_path)
        with pytest.raises(RuntimeError, match="champion cache not found"):
            weekly_ingest.run_bis(
                patch="26.16",
                source=tmp_path / "absent.json",
                axword_source=axword,
                output=tmp_path / "out.json",
                baseline=None,
            )

    def test_zero_merged_packets_fails_closed(self, tmp_path):
        """An axword source with no matching champion supplies zero packets."""
        champions = _write_champions(tmp_path, ("Unrelated",))
        axword = _write_axword(tmp_path)  # only knows "Fixture"
        with pytest.raises(RuntimeError, match="zero Meraki damage packets"):
            weekly_ingest.run_bis(
                patch="26.16",
                source=champions,
                axword_source=axword,
                output=tmp_path / "out.json",
                baseline=None,
            )
        assert not (tmp_path / "out.json").exists()

    def test_regression_against_baseline_fails_closed(self, tmp_path):
        champions = _write_champions_with_q_ability(tmp_path)
        axword = _write_axword(tmp_path)
        baseline = tmp_path / "baseline.json"
        baseline.write_text(
            json.dumps({"auxiliary_source": {"merged_damage_packets": 999}}),
            encoding="utf-8",
        )
        with pytest.raises(RuntimeError, match="invariant regressed"):
            weekly_ingest.run_bis(
                patch="26.16",
                source=champions,
                axword_source=axword,
                output=tmp_path / "out.json",
                baseline=baseline,
            )

    def test_successful_rebuild_writes_output(self, tmp_path):
        champions = _write_champions_with_q_ability(tmp_path)
        axword = _write_axword(tmp_path)
        output = tmp_path / "bis-profiles.json"
        result = weekly_ingest.run_bis(
            patch="26.16",
            source=champions,
            axword_source=axword,
            output=output,
            baseline=None,
        )
        assert output.is_file()
        assert result["merged_damage_packets"] > 0
        written = json.loads(output.read_text(encoding="utf-8"))
        assert written["champion_count"] == 1


# ---------------------------------------------------------------------------
# Step 4: packets (drift diff, never splices)
# ---------------------------------------------------------------------------


class TestDiffReviewedPackets:
    def test_identical_slots_are_clean(self):
        checked_in = {
            "champions": {
                "Ahri": {
                    "review_status": "reviewed_packet",
                    "slots": {"Q": {"base": [1]}},
                }
            }
        }
        fresh = {
            "champions": {
                "Ahri": {
                    "review_status": "reviewed_packet",
                    "slots": {"Q": {"base": [1]}},
                }
            }
        }
        report = weekly_ingest.diff_reviewed_packets(fresh, checked_in)
        assert report["clean"] is True
        assert report["drifted"] == []

    def test_numeric_slot_change_is_reported(self):
        checked_in = {
            "champions": {
                "Poppy": {
                    "review_status": "reviewed_packet",
                    "slots": {"Q": {"ratios": [{"stat": "bonusAd", "values": [1.0]}]}},
                }
            }
        }
        fresh = {
            "champions": {
                "Poppy": {
                    "review_status": "reviewed_packet",
                    "slots": {"Q": {"ratios": [{"stat": "bonusAd", "values": [0.75]}]}},
                }
            }
        }
        report = weekly_ingest.diff_reviewed_packets(fresh, checked_in)
        assert report["clean"] is False
        assert report["drifted_champion_count"] == 1
        assert report["drifted"][0]["champion"] == "Poppy"

    def test_review_status_change_is_reported_separately_from_slot_drift(self):
        checked_in = {
            "champions": {
                "Bard": {
                    "review_status": "reviewed_packet",
                    "slots": {"Q": {"base": [1]}},
                }
            }
        }
        fresh = {
            "champions": {
                "Bard": {
                    "review_status": "generated_packet",
                    "slots": {"Q": {"base": [1]}},
                }
            }
        }
        report = weekly_ingest.diff_reviewed_packets(fresh, checked_in)
        assert report["clean"] is False
        assert report["drifted"] == []  # slots themselves did not change
        assert report["review_status_changes"] == [
            {
                "champion": "Bard",
                "checked_in": "reviewed_packet",
                "fresh": "generated_packet",
            }
        ]

    def test_champion_dropped_from_rebuild_is_reported(self):
        checked_in = {
            "champions": {"Zed": {"review_status": "reviewed_packet", "slots": {}}}
        }
        fresh = {"champions": {}}
        report = weekly_ingest.diff_reviewed_packets(fresh, checked_in)
        assert report["champions_missing_from_rebuild"] == ["Zed"]
        assert report["clean"] is False

    def test_new_champion_in_rebuild_is_reported(self):
        checked_in = {"champions": {}}
        fresh = {
            "champions": {"Zaahen": {"review_status": "reviewed_packet", "slots": {}}}
        }
        report = weekly_ingest.diff_reviewed_packets(fresh, checked_in)
        assert report["champions_new_in_rebuild"] == ["Zaahen"]
        assert report["clean"] is False

    def test_metadata_only_field_changes_are_not_drift(self):
        """`sources`/receipts churn every rebuild; they must not count as drift."""
        checked_in = {
            "champions": {
                "Ahri": {
                    "review_status": "reviewed_packet",
                    "slots": {"Q": {"base": [1]}},
                    "sources": [{"revision_id": 1}],
                }
            }
        }
        fresh = {
            "champions": {
                "Ahri": {
                    "review_status": "reviewed_packet",
                    "slots": {"Q": {"base": [1]}},
                    "sources": [{"revision_id": 2}],
                }
            }
        }
        report = weekly_ingest.diff_reviewed_packets(fresh, checked_in)
        assert report["clean"] is True


class TestRunPackets:
    def test_missing_static_asset_fails_closed(self, tmp_path):
        with pytest.raises(RuntimeError, match="checked-in reviewed packets not found"):
            weekly_ingest.run_packets(
                source=_write_champions(tmp_path),
                axword_source=_write_axword(tmp_path),
                wiki_db=_write_wiki_db(tmp_path, {"Fixture": 1}),
                static_path=tmp_path / "absent.json",
            )

    def test_missing_wiki_db_fails_closed(self, tmp_path):
        static_path = tmp_path / "reviewed-packets.json"
        static_path.write_text(json.dumps({"champions": {}}), encoding="utf-8")
        with pytest.raises(RuntimeError, match="Local League Wiki cache not found"):
            weekly_ingest.run_packets(
                source=_write_champions(tmp_path, ("Fixture",)),
                axword_source=_write_axword(tmp_path),
                wiki_db=tmp_path / "absent.sqlite3",
                static_path=static_path,
            )

    def test_never_writes_the_static_path(self, tmp_path):
        """Regenerated packets land in a scratch file; static/reviewed-packets.json is untouched."""
        static_path = tmp_path / "reviewed-packets.json"
        original = json.dumps({"champions": {}})
        static_path.write_text(original, encoding="utf-8")

        weekly_ingest.run_packets(
            source=_write_champions(tmp_path, ("Fixture",)),
            axword_source=_write_axword(tmp_path),
            wiki_db=_write_wiki_db(tmp_path, {"Fixture": 1}),
            static_path=static_path,
            tmp_output=tmp_path / "fresh-packets.json",
        )
        assert static_path.read_text(encoding="utf-8") == original

    def test_reports_drift_against_the_checked_in_asset(self, tmp_path):
        static_path = tmp_path / "reviewed-packets.json"
        static_path.write_text(
            json.dumps(
                {
                    "champions": {
                        "Fixture": {
                            "review_status": "reviewed_packet",
                            "slots": {"P": {"kind": "impossible_stale_value"}},
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        report = weekly_ingest.run_packets(
            source=_write_champions(tmp_path, ("Fixture",)),
            axword_source=_write_axword(tmp_path),
            wiki_db=_write_wiki_db(tmp_path, {"Fixture": 1}),
            static_path=static_path,
            tmp_output=tmp_path / "fresh-packets.json",
        )
        assert report["clean"] is False
        assert any(d["champion"] == "Fixture" for d in report["drifted"])


# ---------------------------------------------------------------------------
# all: orchestration + short-circuiting
# ---------------------------------------------------------------------------


class TestRunAll:
    def test_current_patch_skips_everything(self, tmp_path):
        staleness = _write_staleness(tmp_path, "16.15")
        report, code = weekly_ingest.run_all(
            staleness_path=staleness,
            cdtb_resolver=lambda *_a, **_k: "16.15",
            cdragon_fetch=_never_called,
        )
        assert code == 0
        assert report["status"] == "no_action_needed"
        assert "fetch" not in report

    def test_detect_infra_failure_short_circuits(self, tmp_path):
        def boom(*_a, **_k):
            raise RuntimeError("cdtb not found")

        def fetch_boom():
            raise _HTTPErrorFactory.make(code=500)

        staleness = _write_staleness(tmp_path, "16.15")
        report, code = weekly_ingest.run_all(
            staleness_path=staleness, cdtb_resolver=boom, cdragon_fetch=fetch_boom
        )
        assert code == 2
        assert report["status"] == "detect_failed"

    def test_new_patch_runs_fetch_then_stops_on_bis_failure(self, tmp_path):
        staleness = _write_staleness(tmp_path, "16.15")
        champions = _write_champions(tmp_path, ("Fixture",))

        report, code = weekly_ingest.run_all(
            staleness_path=staleness,
            cdtb_resolver=lambda *_a, **_k: "16.16",
            cdragon_fetch=_never_called,
            fetch_kwargs={
                "champions_path": champions,
                "game_dir": tmp_path / "gamefiles",
                "bin_dir": tmp_path / "bin",
                "game_file_downloader": _fake_game_file_downloader,
                "authority_downloader": lambda _url: b"{}",
            },
            bis_kwargs={
                "source": champions,
                "axword_source": tmp_path / "absent-merakiAbilityKits.ts",
                "output": tmp_path / "bis-profiles.json",
                "baseline": None,
            },
            packets_kwargs={"static_path": tmp_path / "never-reached.json"},
        )
        assert code == 2
        assert report["status"] == "error"
        assert "fetch" in report  # fetch completed before bis failed
        assert "bis" not in report
