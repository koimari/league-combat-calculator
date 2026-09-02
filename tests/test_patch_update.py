"""Tests for the patch-day orchestrator (scripts/patch_update.py).

Covers the audit helpers (leaf diffs, item-source/ally/economics gating) and
the ingestion subcommands' pure logic (patch comparison, sha256 diffing,
packet-currency reporting, the Meraki-packet invariant) plus the fail-closed
contract on every subcommand. All network paths are injected: no test in this
file makes a live network call and no test writes anything outside
``tmp_path``.

Hermeticity contract (2026-08-20)
---------------------------------
Two rules, both enforced by tests in this file rather than by convention:

1. **Inject, never monkeypatch a module attribute.** A bare
   ``import patch_regression`` (which any test putting ``<repo>/scripts`` on
   ``sys.path`` makes possible) binds a *second, distinct* module object from
   ``scripts.patch_regression``. Every ``monkeypatch``-of-a-
   ``patch_regression``-attribute would then miss the object the code called:
   ``resolve_patch`` reaches the live network, the orchestrator concludes a new
   patch is live, and it runs the real pipeline against the module-level
   DEFAULT_* paths -- overwriting ``data/bin/characters/gnarbig.bin.json``,
   ``static/bis-profiles.json`` and the whole ``data/gamefiles/`` cache from a
   unit-test run. Injected callables have no second identity to miss.
2. **Every test is tripwired.** ``real_tree_tripwire`` below diffs the real
   repository before and after each test and fails the test that dirtied it.
"""

from __future__ import annotations

import importlib
import json
import shutil
import sqlite3
import subprocess
import sys
import urllib.error
from pathlib import Path
from typing import Any

import pytest

from scripts import patch_mechanics, patch_regression, patch_update
from scripts.patch_mechanics import (
    drop_noise,
    is_numeric_diff,
    leaf_diffs,
    name_delta,
)
from scripts.patch_update import (
    ECONOMICS_TABLES,
    ally_effect_lines,
    economics_lines,
    item_source_lines,
)
from src.calculator import item_effects
from src.calculator.champions import registered_champion_names
from src.calculator.data_fetcher import fetch_item_data

# ``patch_update`` validates every fetched file with ``jq empty`` and fails
# closed when the binary is absent -- which is the behaviour
# ``test_missing_jq_binary_fails_closed_with_actionable_message`` pins.  On a
# machine without jq the rest of the fetch surface cannot be exercised at
# all, so it skips rather than reporting the missing tool as a defect.  CI
# installs jq, where these run.
requires_jq = pytest.mark.skipif(
    shutil.which("jq") is None, reason="jq is not installed on this machine"
)

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
        "this test mutated the real repository tree -- patch_update tests must "
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


# MERGE: the champion catalogue now fails closed when a validated module has
# no cached row -- a module whose row vanished would leave the engine's own
# attacker out of the picker.  ``run_bis`` builds that catalogue, so a fixture
# cache has to be a cache the roster agrees with: every registered champion
# gets a bare row, and the named fixtures are what the test is about.
_REGISTERED = tuple(registered_champion_names())


def _roster_rows(names) -> dict:
    rows = {name.lower(): {"name": name, "abilities": {}} for name in _REGISTERED}
    rows.update({name.lower(): {"name": name, "abilities": {}} for name in names})
    return rows


def _write_champions(tmp_path: Path, names=("Fixture", "Other"), *, roster=False):
    """A fixture champion cache.

    ``roster=True`` adds a bare row for every registered champion, which the
    catalogue build below requires; the callers that read the key set back
    leave it off.
    """
    path = tmp_path / "champions.json"
    rows = (
        _roster_rows(names)
        if roster
        else {name.lower(): {"name": name, "abilities": {}} for name in names}
    )
    path.write_text(json.dumps(rows), encoding="utf-8")
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
    payload = _roster_rows(())
    payload.update(
        {
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
    )
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
    def test_module_adds_only_the_repo_root_to_sys_path(self):
        """Adding <repo>/scripts is how the second sibling identity got created.

        The orchestrator runs as ``python scripts/patch_update.py``, so it has
        to put the repo root on the path to reach ``src`` and ``scripts`` as
        packages. Adding the ``scripts`` directory itself is the forbidden one:
        it makes a bare ``patch_regression`` importable alongside
        ``scripts.patch_regression``.
        """
        source = (ROOT / "scripts" / "patch_update.py").read_text(encoding="utf-8")
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
        assert mutations == ["sys.path.insert(0, str(REPO_ROOT))"]

    def test_siblings_are_imported_only_as_scripts_dot_x(self):
        """One import spelling: no bare `import <sibling>` / `from <sibling> import`."""
        source = (ROOT / "scripts" / "patch_update.py").read_text(encoding="utf-8")
        siblings = {
            path.stem
            for path in (ROOT / "scripts").glob("*.py")
            if path.stem not in ("__init__", "patch_update")
        }
        offenders = [
            line.strip()
            for line in source.splitlines()
            for sibling in siblings
            if line.startswith((f"import {sibling}", f"from {sibling} import"))
        ]
        assert offenders == []

    def test_scripts_dir_on_sys_path_cannot_create_a_second_sibling_identity(
        self, monkeypatch
    ):
        """The exact full-suite hazard, reproduced then asserted away.

        Several test modules prepend <repo>/scripts to sys.path, which makes a
        bare ``patch_regression`` importable as a distinct module. The
        orchestrator must still call the ``scripts.`` one.
        """
        had_impostor = "patch_regression" in sys.modules
        monkeypatch.syspath_prepend(str(ROOT / "scripts"))
        try:
            impostor = importlib.import_module("patch_regression")
            # sanity: the hazard is real -- these are genuinely two objects
            assert impostor is not patch_regression
            reloaded = importlib.reload(patch_update)
            assert reloaded.patch_regression is patch_regression
            assert reloaded.build_profiles.__module__ == "scripts.build_bis_profiles"
            assert (
                reloaded.build_reviewed_packets.__module__
                == "scripts.build_reviewed_modules"
            )
            assert reloaded.leaf_diffs.__module__ == "scripts.patch_mechanics"
            assert reloaded.source_receipt.__module__ == "scripts.source_receipt"
        finally:
            if not had_impostor:
                sys.modules.pop("patch_regression", None)

    def test_this_file_injects_rather_than_patching_module_attributes(self):
        """No monkeypatched module attributes and no DEFAULT_* reliance here."""
        source = Path(__file__).read_text(encoding="utf-8")
        # Needles are assembled at runtime so this assertion does not match
        # its own source line.
        setattr_call = "monkeypatch" + ".setattr("
        default_constant = "patch_update." + "DEFAULT_"
        assert setattr_call not in source
        assert default_constant not in source

    @pytest.mark.parametrize(
        "invocation",
        [["scripts/patch_update.py"], ["-m", "scripts.patch_update"]],
        ids=("script-path", "module-form"),
    )
    def test_every_subcommand_parses_from_either_invocation(self, invocation):
        """The documented script form and the module form both reach the CLI."""
        for command in (
            "",
            "run",
            "audit",
            "detail",
            "detect",
            "fetch",
            "bis",
            "packets",
        ):
            argv = [sys.executable, *invocation]
            if command:
                argv.append(command)
            result = subprocess.run(
                [*argv, "--help"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            assert result.returncode == 0, f"{command or '<root>'}: {result.stderr}"


# ---------------------------------------------------------------------------
# Step 1: detect (pure comparison + patch resolution)
# ---------------------------------------------------------------------------


class TestExtractClientPatch:
    def test_parses_the_cdragon_content_metadata_shape(self):
        version = "16.16.8049184+branch.releases-16-16.content.release"
        assert patch_update._extract_client_patch(version) == "16.16"

    def test_single_digit_minor_is_kept_unpadded(self):
        assert patch_update._extract_client_patch("16.5.1234") == "16.5"

    def test_unrecognized_string_raises(self):
        with pytest.raises(RuntimeError, match="unrecognized"):
            patch_update._extract_client_patch("not-a-version")


class TestFetchCdragonLivePatch:
    def test_happy_path_returns_client_patch(self):
        def fetch():
            return json.dumps({"version": "16.16.8049184+x"}).encode()

        assert patch_update.fetch_cdragon_live_patch(fetch) == "16.16"

    def test_missing_version_field_fails_closed(self):
        def fetch():
            return json.dumps({"nope": True}).encode()

        with pytest.raises(RuntimeError, match="no 'version' field"):
            patch_update.fetch_cdragon_live_patch(fetch)

    def test_http_error_fails_closed_with_status(self):
        def fetch():
            raise _HTTPErrorFactory.make(code=503, reason="Service Unavailable")

        with pytest.raises(RuntimeError, match="503"):
            patch_update.fetch_cdragon_live_patch(fetch)

    def test_malformed_json_fails_closed(self):
        def fetch():
            return b"{not json"

        with pytest.raises(RuntimeError, match="content-metadata fetch failed"):
            patch_update.fetch_cdragon_live_patch(fetch)


class TestResolveLivePatch:
    def test_prefers_cdtb_when_available(self):
        patch, source = patch_update.resolve_live_patch(
            cdtb_resolver=lambda *_a, **_k: "16.16",
            cdragon_fetch=_never_called,
        )
        assert (patch, source) == ("16.16", "cdtb")

    def test_falls_back_to_cdragon_when_cdtb_missing(self):
        def boom(*_a, **_k):
            raise RuntimeError("cdtb not found")

        def fetch():
            return json.dumps({"version": "16.16.999+x"}).encode()

        patch, source = patch_update.resolve_live_patch(
            cdtb_resolver=boom, cdragon_fetch=fetch
        )
        assert (patch, source) == ("16.16", "communitydragon_content_metadata")

    def test_default_resolver_is_the_scripts_package_one(self):
        """The live default must be the single ``scripts.`` identity."""
        assert patch_update.patch_regression.resolve_patch is (
            patch_regression.resolve_patch
        )


class TestReadCachedPatch:
    def test_reads_the_patch_field(self, tmp_path):
        path = _write_staleness(tmp_path, "16.15")
        assert patch_update.read_cached_patch(path) == "16.15"

    def test_missing_file_fails_closed(self, tmp_path):
        with pytest.raises(RuntimeError, match="unreadable"):
            patch_update.read_cached_patch(tmp_path / "absent.json")

    def test_missing_patch_field_fails_closed(self, tmp_path):
        path = tmp_path / "staleness.json"
        path.write_text(json.dumps({"checked_at": "x"}), encoding="utf-8")
        with pytest.raises(RuntimeError, match="no 'patch' field"):
            patch_update.read_cached_patch(path)


class TestDetectReport:
    def test_same_patch_is_current(self):
        report = patch_update.detect_report("16.16", "cdtb", "16.16")
        assert report["status"] == "current"
        assert report["live_patch"] == "16.16"
        assert report["cached_patch"] == "16.16"

    def test_different_patch_is_new_patch_available(self):
        report = patch_update.detect_report("16.16", "cdtb", "16.15")
        assert report["status"] == "new_patch_available"

    def test_public_and_client_labels_normalize_to_the_same_identity(self):
        """26.16 (public) and 16.16 (client) name the same patch."""
        report = patch_update.detect_report("16.16", "cdtb", "26.16")
        assert report["status"] == "current"

    def test_malformed_label_fails_closed(self):
        with pytest.raises(RuntimeError, match="cannot compare patch labels"):
            patch_update.detect_report("not-a-patch", "cdtb", "16.16")


class TestRunDetect:
    def test_current_returns_exit_0(self, tmp_path):
        staleness = _write_staleness(tmp_path, "16.15")
        report, code = patch_update.run_detect(
            staleness_path=staleness,
            cdtb_resolver=lambda *_a, **_k: "16.15",
            cdragon_fetch=_never_called,
        )
        assert code == 0
        assert report["status"] == "current"

    def test_new_patch_returns_exit_1(self, tmp_path):
        staleness = _write_staleness(tmp_path, "16.15")
        report, code = patch_update.run_detect(
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
        patch_update.run_detect(
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
        report, code = patch_update.run_detect(
            staleness_path=staleness, cdtb_resolver=boom, cdragon_fetch=fetch_boom
        )
        assert code == 2
        assert report["status"] == "error"

    def test_missing_staleness_file_is_infra_failure(self, tmp_path):
        report, code = patch_update.run_detect(
            staleness_path=tmp_path / "absent.json",
            cdtb_resolver=lambda *_a, **_k: "16.16",
            cdragon_fetch=_never_called,
        )
        assert code == 2
        assert report["status"] == "error"


# ---------------------------------------------------------------------------
# Step 2: fetch (jq validation + sha256 diffing + fail-closed on failure)
# ---------------------------------------------------------------------------


@requires_jq
class TestJqValidate:
    def test_valid_json_passes(self, tmp_path):
        path = tmp_path / "ok.json"
        path.write_text('{"a": 1}', encoding="utf-8")
        patch_mechanics.jq_validate(path)  # must not raise

    def test_malformed_json_fails_closed(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(RuntimeError, match="jq validation failed"):
            patch_mechanics.jq_validate(path)

    def test_missing_jq_binary_fails_closed_with_actionable_message(self, tmp_path):
        path = tmp_path / "ok.json"
        path.write_text('{"a": 1}', encoding="utf-8")
        with pytest.raises(RuntimeError, match="jq is not installed"):
            patch_mechanics.jq_validate(path, jq_bin="definitely-not-a-real-binary-xyz")


@requires_jq
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

        report = patch_mechanics.refresh_authority_files(
            "16.16", dest_dir=tmp_path, downloader=downloader
        )
        assert report["ok"] is True
        assert set(report["files"]) == {"gnar", "gnarbig", "renata"}
        for name, payload in payloads.items():
            entry = report["files"][name]
            assert entry["sha256_before_fetch"] is None
            assert entry["sha256_after_fetch"] == patch_mechanics._sha256_bytes(payload)
            assert entry["changed_locally"] is True
        assert report["files"]["gnar"]["tracked"] is True
        assert report["files"]["renata"]["tracked"] is False

    def test_unchanged_refetch_reports_changed_locally_false(self, tmp_path):
        def downloader(_url):
            return b'{"stable": 1}'

        patch_mechanics.refresh_authority_files(
            "16.16", dest_dir=tmp_path, downloader=downloader
        )
        second = patch_mechanics.refresh_authority_files(
            "16.16", dest_dir=tmp_path, downloader=downloader
        )
        for entry in second["files"].values():
            assert entry["changed_locally"] is False

    def test_http_404_is_collected_as_a_failure_not_raised(self, tmp_path):
        def downloader(url):
            if "gnarbig" in url:
                raise _HTTPErrorFactory.make(code=404, reason="Not Found", url=url)
            return b'{"ok": 1}'

        report = patch_mechanics.refresh_authority_files(
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

        report = patch_mechanics.refresh_authority_files(
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

        report = patch_mechanics.refresh_authority_files(
            "16.16", dest_dir=tmp_path, downloader=downloader
        )
        assert report["files"]["gnar"]["changed_vs_git_head"] is False
        # renata is not git-tracked -- there is no HEAD copy to diff against
        assert report["files"]["renata"]["changed_vs_git_head"] is None


# ---------------------------------------------------------------------------
# Step 2 guard: refuse to clobber a dirty tracked authority pair
# ---------------------------------------------------------------------------


@requires_jq
class TestAuthorityDirtyGuard:
    def test_no_paths_is_clean(self):
        assert patch_mechanics._git_dirty_paths([]) == []

    def test_clean_tracked_pair_reports_no_conflict(self, tmp_path):
        repo = _scratch_git_repo(tmp_path)
        characters = repo / "data" / "bin" / "characters"
        assert (
            patch_mechanics.authority_dirty_conflicts(
                characters, repo_root=repo, tracked_dir=characters
            )
            == []
        )

    def test_dirty_tracked_file_is_reported(self, tmp_path):
        repo = _scratch_git_repo(tmp_path)
        characters = repo / "data" / "bin" / "characters"
        (characters / "gnarbig.bin.json").write_text('{"v": 2}', encoding="utf-8")
        assert patch_mechanics.authority_dirty_conflicts(
            characters, repo_root=repo, tracked_dir=characters
        ) == ["data/bin/characters/gnarbig.bin.json"]

    def test_scratch_destination_is_never_a_conflict(self, tmp_path):
        """A fetch into a scratch dir cannot destroy committed evidence."""
        repo = _scratch_git_repo(tmp_path)
        characters = repo / "data" / "bin" / "characters"
        (characters / "gnarbig.bin.json").write_text('{"v": 2}', encoding="utf-8")
        assert (
            patch_mechanics.authority_dirty_conflicts(
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
            patch_mechanics._git_dirty_paths(
                ["data/bin/characters/gnar.bin.json"], repo_root=outside
            )

    def test_run_fetch_refuses_before_touching_anything(self, tmp_path):
        report, code = patch_mechanics.run_fetch(
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
        report, code = patch_mechanics.run_fetch(
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

        report, code = patch_mechanics.run_fetch(
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
        assert set(patch_mechanics._champion_names(path)) == {"ahri", "zed"}

    def test_missing_cache_fails_closed(self, tmp_path):
        with pytest.raises(RuntimeError, match="unreadable"):
            patch_mechanics._champion_names(tmp_path / "absent.json")


@requires_jq
class TestRefreshGamefiles:
    def test_delegates_to_the_injected_downloader_and_reports_changes(self, tmp_path):
        champions = _write_champions(tmp_path, ("Ahri", "Zed"))
        report = patch_mechanics.refresh_gamefiles(
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

        patch_mechanics.refresh_gamefiles(
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
            patch_mechanics.refresh_gamefiles(
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
            patch_mechanics.refresh_gamefiles(
                "16.16",
                game_dir=tmp_path / "gamefiles",
                champions_path=champions,
                game_file_downloader=failing_download,
            )

    def test_default_downloader_is_the_scripts_package_one(self):
        """The live default must be the single ``scripts.`` identity."""
        assert patch_update.patch_regression.download_game_files is (
            patch_regression.download_game_files
        )


class TestRunGamefileRefresh:
    def test_resolver_failure_returns_2_before_any_network_work(self, capsys):
        # The refresh resolves with the SAME resolver the staleness gate
        # uses; when it is unavailable the step fails before run_fetch can
        # download anything.
        def _no_resolver():
            raise RuntimeError("cdtb not found")

        def _never_fetch(**kwargs):
            raise AssertionError("run_fetch must not be called")

        rc = patch_update.run_gamefile_refresh(
            None, resolver=_no_resolver, fetch=_never_fetch
        )
        assert rc == 2
        assert "cannot resolve the live patch" in capsys.readouterr().out


@requires_jq
class TestRunFetch:
    def test_hard_failure_in_gamefiles_returns_exit_2(self, tmp_path):
        report, code = patch_mechanics.run_fetch(
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

        report, code = patch_mechanics.run_fetch(
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
        report, code = patch_mechanics.run_fetch(
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
            patch_update.run_bis(
                patch="26.16",
                source=champions,
                axword_source=tmp_path / "absent-merakiAbilityKits.ts",
                output=tmp_path / "out.json",
                baseline=None,
            )

    def test_missing_champion_cache_fails_closed(self, tmp_path):
        axword = _write_axword(tmp_path)
        with pytest.raises(RuntimeError, match="champion cache not found"):
            patch_update.run_bis(
                patch="26.16",
                source=tmp_path / "absent.json",
                axword_source=axword,
                output=tmp_path / "out.json",
                baseline=None,
            )

    def test_zero_merged_packets_fails_closed(self, tmp_path):
        """An axword source with no matching champion supplies zero packets."""
        champions = _write_champions(tmp_path, ("Unrelated",), roster=True)
        axword = _write_axword(tmp_path)  # only knows "Fixture"
        with pytest.raises(RuntimeError, match="zero Meraki damage packets"):
            patch_update.run_bis(
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
            patch_update.run_bis(
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
        result = patch_update.run_bis(
            patch="26.16",
            source=champions,
            axword_source=axword,
            output=output,
            baseline=None,
        )
        assert output.is_file()
        assert result["merged_damage_packets"] > 0
        written = json.loads(output.read_text(encoding="utf-8"))
        assert written["champion_count"] == len(_REGISTERED) + 1


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
        report = patch_update.diff_reviewed_packets(fresh, checked_in)
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
        report = patch_update.diff_reviewed_packets(fresh, checked_in)
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
        report = patch_update.diff_reviewed_packets(fresh, checked_in)
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
        report = patch_update.diff_reviewed_packets(fresh, checked_in)
        assert report["champions_missing_from_rebuild"] == ["Zed"]
        assert report["clean"] is False

    def test_new_champion_in_rebuild_is_reported(self):
        checked_in = {"champions": {}}
        fresh = {
            "champions": {"Zaahen": {"review_status": "reviewed_packet", "slots": {}}}
        }
        report = patch_update.diff_reviewed_packets(fresh, checked_in)
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
        report = patch_update.diff_reviewed_packets(fresh, checked_in)
        assert report["clean"] is True


def _built_asset(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    """A checked-in asset produced by the real builder from fixture sources.

    Returns ``(asset_path, champions, axword, wiki_db)``. Both halves of
    ``reviewed_packet_report`` are clean against it, which is what lets the
    tests below break exactly one half at a time.
    """
    champions = _write_champions(tmp_path, ("Fixture",))
    axword = _write_axword(tmp_path)
    wiki_db = _write_wiki_db(tmp_path, {"Fixture": 1})
    asset_path = tmp_path / "reviewed-packets.json"
    patch_update.build_reviewed_packets(champions, axword, asset_path, wiki_db=wiki_db)
    return asset_path, champions, axword, wiki_db


class TestReviewedPacketReport:
    """One verdict, two checks that catch disjoint drift.

    The source receipts see a changed *source* (a data pull); the rebuild diff
    sees a changed *builder* with the sources unchanged. Neither is redundant
    with the other, nor with the import-time ``PACKET_SHA256`` pin, which only
    proves that the packet-backed modules accepted *this* asset.
    """

    def test_a_freshly_built_asset_is_clean_on_both_halves(self, tmp_path):
        asset_path, champions, axword, wiki_db = _built_asset(tmp_path)
        report = patch_update.reviewed_packet_report(
            asset_path=asset_path,
            champions_source=champions,
            axword_source=axword,
            wiki_db=wiki_db,
            tmp_output=tmp_path / "fresh-packets.json",
        )
        assert report["receipt_problems"] == []
        assert report["rebuild"]["clean"] is True
        assert report["clean"] is True

    def test_slot_drift_is_caught_by_the_rebuild_half_alone(self, tmp_path):
        """A changed builder leaves every source receipt intact."""
        asset_path, champions, axword, wiki_db = _built_asset(tmp_path)
        asset = json.loads(asset_path.read_text(encoding="utf-8"))
        asset["champions"]["Fixture"]["slots"]["P"] = {"kind": "impossible_stale_value"}
        asset_path.write_text(json.dumps(asset), encoding="utf-8")

        report = patch_update.reviewed_packet_report(
            asset_path=asset_path,
            champions_source=champions,
            axword_source=axword,
            wiki_db=wiki_db,
            tmp_output=tmp_path / "fresh-packets.json",
        )
        assert report["receipt_problems"] == []
        assert report["rebuild"]["clean"] is False
        assert any(
            entry["champion"] == "Fixture" for entry in report["rebuild"]["drifted"]
        )
        assert report["clean"] is False

    def test_receipt_drift_is_caught_by_the_receipt_half_alone(self, tmp_path):
        """A changed source leaves the rebuilt slots identical."""
        asset_path, champions, axword, wiki_db = _built_asset(tmp_path)
        asset = json.loads(asset_path.read_text(encoding="utf-8"))
        asset["source_receipts"]["champions.json"]["sha256"] = "0" * 64
        asset_path.write_text(json.dumps(asset), encoding="utf-8")

        report = patch_update.reviewed_packet_report(
            asset_path=asset_path,
            champions_source=champions,
            axword_source=axword,
            wiki_db=wiki_db,
            tmp_output=tmp_path / "fresh-packets.json",
        )
        assert any(
            "champions.json changed" in problem
            for problem in report["receipt_problems"]
        )
        assert report["rebuild"]["clean"] is True
        assert report["clean"] is False

    def test_no_rebuild_reports_the_receipt_half_only(self, tmp_path):
        asset_path, champions, axword, wiki_db = _built_asset(tmp_path)
        report = patch_update.reviewed_packet_report(
            asset_path=asset_path,
            champions_source=champions,
            axword_source=axword,
            wiki_db=wiki_db,
            rebuild=False,
        )
        assert report["rebuild"] is None
        assert report["rebuild_skipped"] == "rebuild diff not requested"
        assert report["clean"] is True

    def test_missing_asset_fails_closed_without_raising(self, tmp_path):
        report = patch_update.reviewed_packet_report(
            asset_path=tmp_path / "absent.json",
            champions_source=_write_champions(tmp_path),
            axword_source=_write_axword(tmp_path),
            wiki_db=_write_wiki_db(tmp_path, {"Fixture": 1}),
            tmp_output=tmp_path / "fresh-packets.json",
        )
        assert report["clean"] is False
        assert any(
            "missing or unreadable" in problem for problem in report["receipt_problems"]
        )

    def test_missing_wiki_db_fails_closed_on_both_halves(self, tmp_path):
        asset_path = tmp_path / "reviewed-packets.json"
        asset_path.write_text(json.dumps({"champions": {}}), encoding="utf-8")
        report = patch_update.reviewed_packet_report(
            asset_path=asset_path,
            champions_source=_write_champions(tmp_path, ("Fixture",)),
            axword_source=_write_axword(tmp_path),
            wiki_db=tmp_path / "absent.sqlite3",
            tmp_output=tmp_path / "fresh-packets.json",
        )
        assert report["clean"] is False
        assert any(
            "Local League Wiki cache not found" in problem
            for problem in report["receipt_problems"]
        )
        assert "Local League Wiki cache not found" in report["rebuild_skipped"]

    def test_never_writes_the_asset(self, tmp_path):
        """The rebuild lands in a scratch file; the checked-in asset is untouched."""
        asset_path, champions, axword, wiki_db = _built_asset(tmp_path)
        original = asset_path.read_text(encoding="utf-8")
        patch_update.reviewed_packet_report(
            asset_path=asset_path,
            champions_source=champions,
            axword_source=axword,
            wiki_db=wiki_db,
            tmp_output=tmp_path / "fresh-packets.json",
        )
        assert asset_path.read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# Audit report helpers
# ---------------------------------------------------------------------------


class TestLeafDiffs:
    def test_changed_leaf_reports_path_old_new(self) -> None:
        old = {"stats": {"ad": 60, "hp": 600}}
        new = {"stats": {"ad": 62, "hp": 600}}
        assert list(leaf_diffs(old, new)) == [(".stats.ad", 60, 62)]

    def test_nested_list_changes_include_index(self) -> None:
        old = {"values": [10, 20, 30]}
        new = {"values": [10, 25, 30]}
        assert list(leaf_diffs(old, new)) == [(".values[1]", 20, 25)]

    def test_list_length_change_reported_and_common_prefix_compared(self) -> None:
        old = {"builds": [1, 2, 3]}
        new = {"builds": [1, 9]}
        diffs = list(leaf_diffs(old, new))
        assert (".builds(len)", 3, 2) in diffs
        assert (".builds[1]", 2, 9) in diffs

    def test_added_and_missing_keys_diff_against_none(self) -> None:
        assert list(leaf_diffs({}, {"new": 5})) == [(".new", None, 5)]
        assert list(leaf_diffs({"old": 5}, {})) == [(".old", 5, None)]

    def test_identical_structures_yield_nothing(self) -> None:
        data = {"a": [1, {"b": "x"}]}
        assert list(leaf_diffs(data, data)) == []


class TestDropNoise:
    def test_icon_and_patch_stamp_paths_are_dropped(self) -> None:
        diffs = [
            (".icon", "a.png", "b.png"),
            (".patchLastChanged", "26.13", "26.14"),
            (".abilities.Q[0].icon", "a", "b"),
            (".stats.ad", 60, 62),
        ]
        assert drop_noise(diffs) == [(".stats.ad", 60, 62)]

    def test_price_fields_are_dropped(self) -> None:
        diffs = [(".shop.prices.total", 3000, 3100), (".stats.ap", 70, 60)]
        assert drop_noise(diffs) == [(".stats.ap", 70, 60)]


class TestIsNumericDiff:
    def test_number_leaves_are_numeric(self) -> None:
        assert is_numeric_diff((".x", 60, 58))
        assert is_numeric_diff((".x", 87.5, 70))
        assert is_numeric_diff((".x", None, 5))

    def test_numeric_strings_are_numeric(self) -> None:
        assert is_numeric_diff((".width", "110", "220"))

    def test_prose_leaves_are_not_numeric(self) -> None:
        assert not is_numeric_diff((".notes", "old text 40", "new text 30"))

    def test_length_markers_are_numeric(self) -> None:
        assert is_numeric_diff((".buildsInto(len)", 32, 33))


class TestNameDelta:
    def test_reports_added_and_removed_names(self) -> None:
        old = {"Kindlegem": {}, "Fiendish Codex": {}, "Old Relic": {}}
        new = {"Kindlegem": {}, "Fiendish Codex": {}, "New Toy": {}}
        added, removed = name_delta(old, new)
        assert added == ["New Toy"]
        assert removed == ["Old Relic"]

    def test_no_changes_gives_empty_lists(self) -> None:
        assert name_delta({"A": {}}, {"A": {}}) == ([], [])


class TestItemSourceGate:
    """Patch day stops when the cache loses source coverage."""

    @staticmethod
    def _item(name, effect_name, branch_texts, riot=""):
        return {
            "name": name,
            "riotDescription": riot,
            "passives": [{"name": effect_name, "branches": list(branch_texts)}],
            "active": [],
        }

    def test_unchanged_cache_passes(self) -> None:
        items = {"Cull": self._item("Cull", "Reap", ["gold", "payout"])}
        lines, ok = item_source_lines(items, items)

        assert ok is True
        assert any("accounted for" in line for line in lines)

    def test_lost_branch_blocks_the_patch(self) -> None:
        old = {"Cull": self._item("Cull", "Reap", ["gold", "payout"])}
        new = {"Cull": self._item("Cull", "Reap", ["gold"])}
        lines, ok = item_source_lines(old, new)

        assert ok is False
        assert any("BLOCKING" in line and "Reap" in line for line in lines)

    def test_item_leaving_the_shop_is_the_shop_delta_not_a_loss(self) -> None:
        old = {"Cull": self._item("Cull", "Reap", ["gold", "payout"])}
        lines, ok = item_source_lines(old, {})

        assert ok is True
        assert not any("Reap" in line for line in lines)

    def test_unreviewed_source_conflict_blocks_the_patch(self) -> None:
        items = {
            "Cull": self._item(
                "Cull", "Reap", ["gold"], riot="<passive>Unrecorded Reaping</passive>"
            )
        }
        lines, ok = item_source_lines(items, items)

        assert ok is False
        assert any("Unrecorded Reaping" in line for line in lines)

    def test_reviewed_removal_releases_the_patch(self, monkeypatch) -> None:
        from src.calculator import item_source

        monkeypatch.setitem(
            item_source.APPROVED_BRANCH_REMOVALS,
            "Cull / passive Reap",
            "Patch 26.16 folded the payout into the gold branch.",
        )
        old = {"Cull": self._item("Cull", "Reap", ["gold", "payout"])}
        new = {"Cull": self._item("Cull", "Reap", ["gold"])}
        lines, ok = item_source_lines(old, new)

        assert ok is True
        assert any("approved" in line for line in lines)


class TestAllyEffectLines:
    """D-47: the hand-authored ally table is refresh-inert, so patch day says so."""

    def _shop(self, **moved):
        """A cached shop holding every hand-authored item, some values moved."""
        return {
            name: {
                "name": name,
                "stats": {
                    "abilityPower": {
                        "flat": (
                            moved.get("ap", 0.0) if name == moved.get("item") else 0.0
                        )
                    }
                },
            }
            for name in item_effects.ALLY_ITEM_EFFECTS
        }

    def test_an_unchanged_cached_entry_says_so_and_does_not_block(self) -> None:
        cached = self._shop()
        lines, ok = ally_effect_lines(cached, cached)
        assert ok
        assert lines[-1].endswith("cached entry is unchanged)")

    def test_a_numeric_move_is_flagged_with_the_keys_that_cannot_refresh(self) -> None:
        lines, ok = ally_effect_lines(
            self._shop(), self._shop(item="Abyssal Mask", ap=5.0)
        )
        assert ok, "a moved entry is review, not a release block"
        assert any("Abyssal Mask (NEEDS REVIEW)" in line for line in lines)
        assert any("magic_damage_amp" in line for line in lines)
        assert any(
            "do not\n    refresh" in line or "do not refresh" in line for line in lines
        )

    def test_an_item_that_left_the_shop_blocks(self) -> None:
        """The only branch that can stop a patch: a record pricing nothing."""
        shop = self._shop()
        without = {k: v for k, v in shop.items() if k != "Abyssal Mask"}
        lines, ok = ally_effect_lines(shop, without)
        assert not ok
        assert any(
            "BLOCKING: Abyssal Mask is no longer in the cached shop" in line
            for line in lines
        )
        assert any("** BLOCKING" in line for line in lines)

    def test_every_hand_authored_item_is_audited(self) -> None:
        """No member of the table is exempt from the section."""
        lines, ok = ally_effect_lines(self._shop(), {})
        assert not ok
        blocked = {
            line.split("BLOCKING: ")[1].split(" is no longer")[0]
            for line in lines
            if "BLOCKING: " in line and " is no longer" in line
        }
        assert blocked == set(item_effects.ALLY_ITEM_EFFECTS)


class TestEconomicsLines:
    """The sourced gold table must be current for the cache it prices."""

    def _tables(self) -> dict[str, Any]:
        import json

        return json.loads(ECONOMICS_TABLES.read_text(encoding="utf-8"))

    def test_a_current_table_says_so_and_does_not_block(self) -> None:
        tables = self._tables()
        lines, ok = economics_lines(
            tables, fetch_item_data(), tables["patch"]["ddragon"]
        )
        assert ok
        assert lines[-1].endswith("every ordinary item priced)")

    def test_a_table_pinned_to_another_release_blocks(self) -> None:
        lines, ok = economics_lines(self._tables(), fetch_item_data(), "99.1.1")
        assert not ok
        assert any(line.startswith("  BLOCKING: pinned to DDragon ") for line in lines)
        assert lines[-1].startswith("  ** BLOCKING")
