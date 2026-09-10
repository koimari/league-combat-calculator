"""Exercise refresh failures against temporary source and active-index paths."""

import json
import os
import plistlib
import selectors
import sqlite3
import subprocess
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.install_wiki_refresh import job
from scripts.wiki_refresh import refresh as refresh_source
from scripts.wiki_refresh import run_audit, scheduled_refresh

posix_lock = pytest.mark.skipif(
    os.name != "posix", reason="launchd refresh uses POSIX locks"
)


def refresh(**kwargs):
    return refresh_source(audit_report=lambda **_: {"passed": True}, **kwargs)


def _database(path, vault):
    with sqlite3.connect(path) as connection:
        connection.executescript(
            "CREATE TABLE meta (key TEXT, value TEXT);"
            "CREATE TABLE pages (namespace INT, has_text INT, revision_id INT, "
            "revision_timestamp TEXT);"
            "INSERT INTO pages VALUES (0, 1, 42, '2026-09-08');"
            "CREATE TABLE sections (body TEXT);"
            "INSERT INTO sections VALUES ('source text');"
        )
        connection.executemany(
            "INSERT INTO meta VALUES (?, ?)",
            [("snapshot_complete", "true"), ("vault_path", json.dumps(str(vault)))],
        )


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source"
    tools = root / "lol_kills" / "knowledge"
    tools.mkdir(parents=True)
    for name in ("league_wiki_vault.py", "league_wiki_db.py"):
        (tools / name).touch()
    return root


def _runner(_root, module, args):
    vault = Path(args[args.index("--vault") + 1])
    if args[0] == "inventory":
        vault.mkdir(parents=True, exist_ok=True)
        return {"page_count": 1, "pages_by_namespace": {"0": 1, "6": 1}}
    if args[0] == "snapshot":
        (vault / "document").write_text("new source", encoding="utf-8")
        return {"complete": True, "error_pages": 0, "written_pages": 1}
    if module == "league_wiki_db":
        _database(Path(args[args.index("--database") + 1]), vault)
    return {}


@posix_lock
def test_review_drift_publishes_only_source_index(source, tmp_path):
    active = tmp_path / "active.sqlite3"
    active.write_bytes(b"legacy revision index")
    report = refresh(
        source_root=source,
        database=active,
        runner=_runner,
        packet_report=lambda **_: {"clean": False, "problems": ["revision changed"]},
    )
    assert report["review_required"] is True
    assert report["formula_authority"] is False
    assert Path(report["vault"]).joinpath("document").read_text() == "new source"
    with sqlite3.connect(active) as connection:
        assert connection.execute("SELECT revision_id FROM pages").fetchone()[0] == 42


@posix_lock
def test_template_changes_need_review_even_with_clean_packets(source, tmp_path):
    report = refresh(
        source_root=source,
        database=tmp_path / "active.sqlite3",
        runner=_runner,
        packet_report=lambda **_: {"clean": True},
    )
    assert report["source_pages_written"] == 1
    assert report["review_required"] is True


@posix_lock
def test_missing_packet_inputs_preserve_active_index(source, tmp_path):
    active = tmp_path / "active.sqlite3"
    active.write_bytes(b"accepted")
    with pytest.raises(ValueError, match="could not rebuild"):
        refresh(
            source_root=source,
            database=active,
            runner=_runner,
            packet_report=lambda **_: {
                "clean": False,
                "rebuild_skipped": "missing Axword source",
            },
        )
    assert active.read_bytes() == b"accepted"


@posix_lock
@pytest.mark.parametrize("stage", ["snapshot", "build", "packets"])
def test_failed_stage_keeps_active_index_and_seed(source, tmp_path, stage):
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "document").write_text("accepted source", encoding="utf-8")
    active = tmp_path / "active.sqlite3"
    _database(active, seed)
    original = active.read_bytes()

    def runner(root, module, args):
        if args[0] == stage:
            raise RuntimeError("stage failed")
        return _runner(root, module, args)

    def packets(**_):
        if stage == "packets":
            raise RuntimeError("stage failed")
        return {"clean": True}

    with pytest.raises(RuntimeError, match="stage failed"):
        refresh(
            source_root=source, database=active, runner=runner, packet_report=packets
        )
    assert active.read_bytes() == original
    assert (seed / "document").read_text() == "accepted source"
    refresh(
        source_root=source,
        database=active,
        runner=_runner,
        packet_report=lambda **_: {"clean": True},
    )


@posix_lock
def test_acquisition_errors_cannot_reuse_old_text_as_success(source, tmp_path):
    active = tmp_path / "active.sqlite3"
    active.write_bytes(b"active")

    def runner(root, module, args):
        result = _runner(root, module, args)
        if args[0] == "snapshot":
            result["error_pages"] = 1
        return result

    with pytest.raises(ValueError, match="acquisition failed"):
        refresh(
            source_root=source,
            database=active,
            runner=runner,
            packet_report=lambda **_: pytest.fail("report ran"),
        )
    assert active.read_bytes() == b"active"


@posix_lock
def test_killed_refresh_releases_lock_for_next_attempt(source, tmp_path):
    active = tmp_path / "active.sqlite3"
    script = """
import sys
import time
from pathlib import Path
from scripts.wiki_refresh import refresh

def hold_the_lock(*args):
    print("locked", flush=True)
    time.sleep(60)

refresh(source_root=Path(sys.argv[1]), database=Path(sys.argv[2]),
        runner=hold_the_lock, packet_report=lambda **_: {},
        audit_report=lambda **_: {})
"""
    with subprocess.Popen(
        [sys.executable, "-c", script, str(source), str(active)],
        cwd=Path(__file__).resolve().parents[1],
        stdout=subprocess.PIPE,
        text=True,
    ) as child:
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(child.stdout, selectors.EVENT_READ)
                assert selector.select(timeout=10), "refresh never reported its lock"
            line = child.stdout.readline().strip()
            assert line == "locked", "refresh exited before acquiring its lock"
            with pytest.raises(BlockingIOError):
                refresh(
                    source_root=source,
                    database=active,
                    runner=lambda *_: pytest.fail("concurrent download ran"),
                    packet_report=lambda **_: {},
                )
            child.kill()
            child.wait(timeout=10)
            result = refresh(
                source_root=source,
                database=active,
                runner=_runner,
                packet_report=lambda **_: {"clean": True},
            )
            assert result["database"] == str(active)
        finally:
            child.kill()


@pytest.mark.parametrize("day", [date(2026, 9, 8), date(2026, 9, 2)])
def test_schedule_skips_other_dates(tmp_path, day):
    result = scheduled_refresh(
        anchor=date(2026, 9, 9),
        today=day,
        state_dir=tmp_path,
        action=lambda: pytest.fail("refresh ran"),
    )
    assert result["skipped"] == "outside_fortnight"


def test_schedule_records_failure_and_prevents_duplicate_attempt(tmp_path):
    def fail():
        raise RuntimeError("download interrupted")

    args = {
        "anchor": date(2026, 9, 9),
        "today": date(2026, 9, 23),
        "state_dir": tmp_path,
    }
    with pytest.raises(RuntimeError):
        scheduled_refresh(**args, action=fail)
    assert json.loads((tmp_path / "2026-09-23.json").read_text())["status"] == "failed"
    result = scheduled_refresh(**args, action=lambda: pytest.fail("retried"))
    assert result["skipped"] == "already_attempted"


def test_schedule_records_completed_review_report(tmp_path):
    report = {"review_required": True, "formula_authority": False}
    scheduled_refresh(
        anchor=date(2026, 9, 9),
        today=date(2026, 9, 9),
        state_dir=tmp_path,
        action=lambda: report,
    )
    record = json.loads((tmp_path / "2026-09-09.json").read_text())
    assert record["status"] == "review_required"
    assert record["report"] == report


def test_delayed_wakeup_catches_up_once_for_the_due_period(tmp_path):
    report = {"review_required": False}
    scheduled_refresh(
        anchor=date(2026, 9, 9),
        today=date(2026, 9, 10),
        state_dir=tmp_path,
        action=lambda: report,
    )
    assert (tmp_path / "2026-09-09.json").exists()
    result = scheduled_refresh(
        anchor=date(2026, 9, 9),
        today=date(2026, 9, 16),
        state_dir=tmp_path,
        action=lambda: pytest.fail("duplicate period"),
    )
    assert result["skipped"] == "already_attempted"


def test_launchd_command_round_trips_with_spaces(tmp_path):
    value = job(
        repo=tmp_path / "a repo",
        python=tmp_path / "python",
        source=tmp_path / "source repo",
        logs=tmp_path / "logs",
        axword=tmp_path / "kit.ts",
        seed=tmp_path / "vault",
        anchor=date(2026, 9, 9),
    )
    assert plistlib.loads(plistlib.dumps(value)) == value
    assert value["StartCalendarInterval"] == {"Weekday": 3, "Hour": 9, "Minute": 0}
    assert value["ProgramArguments"][1] == str(
        tmp_path / "a repo/scripts/patch_update.py"
    )
    assert "--scheduled" in value["ProgramArguments"]
    assert value["RunAtLoad"] is True


def test_audit_infrastructure_failure_is_distinct_from_review_drift(tmp_path):
    candidate = tmp_path / "candidate.sqlite3"

    def runner(_command, **kwargs):
        assert kwargs["env"]["SCRYGLASS_LEAGUE_WIKI_DB"] == str(candidate)
        return SimpleNamespace(
            returncode=1,
            stdout=json.dumps({"passed": False, "infrastructure": {"ok": False}}),
            stderr="",
        )

    with pytest.raises(RuntimeError, match="could not read"):
        run_audit(wiki_db=candidate, runner=runner)
