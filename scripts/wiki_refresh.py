"""Refresh a source vault and its query index before reporting packet drift."""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable


def scheduled_refresh(
    *, anchor: date, state_dir: Path, action: Callable, today: date | None = None
) -> dict:
    """Attempt the most recent due period once, including delayed wakeups."""
    today = today or date.today()
    if anchor.weekday() != 2:
        raise ValueError("The fortnight anchor must be a Wednesday")
    elapsed = (today - anchor).days
    if elapsed < 0:
        return {"skipped": "outside_fortnight", "date": today.isoformat()}
    due = anchor + timedelta(days=elapsed // 14 * 14)
    state_dir.mkdir(parents=True, exist_ok=True)
    receipt = state_dir / f"{due.isoformat()}.json"
    record = {
        "due_date": due.isoformat(),
        "attempted_at": datetime.now(timezone.utc).isoformat(),
        "status": "running",
    }
    try:
        with receipt.open("x", encoding="utf-8") as handle:
            json.dump(record, handle)
    except FileExistsError:
        return {"skipped": "already_attempted", "receipt": str(receipt)}
    try:
        report = action()
        record.update(
            status="review_required" if report["review_required"] else "complete",
            report=report,
        )
        return report
    except Exception as exc:
        record.update(status="failed", error=str(exc))
        raise
    finally:
        temporary = receipt.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, receipt)


def run_source(root: Path, module: str, arguments: list[str]) -> dict:
    """Run the source owner's CLI with explicit output paths."""
    result = subprocess.run(
        [sys.executable, "-m", f"lol_kills.knowledge.{module}", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def inspect_database(database: Path) -> dict:
    """Check index integrity and expose the source vault for the next refresh."""
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("Wiki index integrity check failed")
        meta = {
            key: json.loads(value)
            for key, value in connection.execute("SELECT key, value FROM meta")
        }
        count = connection.execute(
            "SELECT COUNT(*) FROM pages WHERE namespace = 0 AND has_text = 1 "
            "AND revision_id > 0 AND revision_timestamp IS NOT NULL"
        ).fetchone()[0]
        sections = connection.execute("SELECT COUNT(*) FROM sections").fetchone()[0]
        if meta.get("snapshot_complete") is not True or not count or not sections:
            raise ValueError(
                "Wiki index has incomplete source or empty article/section data"
            )
        return meta


def run_audit(*, wiki_db: Path, runner: Callable = subprocess.run) -> dict:
    """Run the full-entry audit against the candidate rich index."""
    repo = Path(__file__).resolve().parent.parent
    environment = {**os.environ, "SCRYGLASS_LEAGUE_WIKI_DB": str(wiki_db)}
    result = runner(
        [
            sys.executable,
            str(repo / "scripts/full_entry_audit.py"),
            "--json",
            "--query-tool",
            str(repo / "vendor/league-wiki-query/scripts/query_league_wiki.py"),
        ],
        cwd=repo,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(f"Full-entry audit failed: {result.stderr}")
    report = json.loads(result.stdout)
    if "passed" not in report:
        raise ValueError("Full-entry audit returned no verdict")
    if report.get("infrastructure", {}).get("ok") is False:
        raise RuntimeError("Full-entry audit could not read its source index")
    return report


def refresh(
    *,
    source_root: Path,
    database: Path,
    packet_report: Callable,
    audit_report: Callable,
    seed_vault: Path | None = None,
    runner: Callable = run_source,
) -> dict:
    """Stage each refresh and replace the active index after all steps succeed."""
    source_root = source_root.expanduser().resolve()
    database = database.expanduser().absolute()
    for name in ("league_wiki_vault.py", "league_wiki_db.py"):
        if not (source_root / "lol_kills" / "knowledge" / name).is_file():
            raise ValueError(
                f"Missing source tool: {source_root}/lol_kills/knowledge/{name}"
            )
    if database.is_symlink():
        raise ValueError("Choose a local index output; the active path is a symlink")
    database.parent.mkdir(parents=True, exist_ok=True)
    lock = database.with_name(database.name + ".refresh-lock")
    lock.mkdir()
    generation = None
    try:
        if database.exists():
            try:
                active_vault = Path(inspect_database(database)["vault_path"])
                if active_vault.is_dir():
                    seed_vault = active_vault
            except (sqlite3.Error, ValueError, KeyError):
                # A legacy revision-only index has no reusable source vault.
                pass
        generation = Path(
            tempfile.mkdtemp(prefix="wiki-generation-", dir=database.parent)
        )
        vault = generation / "vault"
        if seed_vault is not None:
            runner(
                source_root,
                "league_wiki_vault",
                ["validate", "--vault", str(seed_vault), "--require-complete"],
            )
            shutil.copytree(seed_vault, vault)
        common = ["--vault", str(vault)]
        inventory = runner(
            source_root,
            "league_wiki_vault",
            ["inventory", *common, "--all-content-namespaces"],
        )
        if not inventory.get("page_count"):
            raise ValueError("Wiki inventory is empty")
        namespaces = ",".join(
            key for key in inventory["pages_by_namespace"] if int(key) != 6
        )
        if not namespaces:
            raise ValueError("Wiki inventory has no text namespaces")
        snapshot = runner(
            source_root,
            "league_wiki_vault",
            ["snapshot", *common, "--namespace", namespaces],
        )
        if snapshot.get("error_pages") or snapshot.get("complete") is not True:
            raise ValueError(
                "Wiki acquisition failed or returned an incomplete snapshot"
            )
        runner(source_root, "league_wiki_vault", ["finalize", *common])
        candidate = generation / "league-wiki.sqlite3"
        index = runner(
            source_root,
            "league_wiki_db",
            ["build", *common, "--database", str(candidate)],
        )
        inspect_database(candidate)
        packets = packet_report(wiki_db=candidate)
        if packets.get("rebuild_skipped"):
            raise ValueError(
                f"Packet report could not rebuild: {packets['rebuild_skipped']}"
            )
        audit = audit_report(wiki_db=candidate)
        index["database"] = str(database)
        changed_pages = snapshot["written_pages"]
        report = {
            "database": str(database),
            "vault": str(vault),
            "inventory": inventory,
            "snapshot": snapshot,
            "index": index,
            "packets": packets,
            "full_entry_audit": audit,
            "source_pages_written": changed_pages,
            "review_required": bool(changed_pages)
            or not packets["clean"]
            or not audit["passed"],
            "formula_authority": False,
        }
        (generation / "report.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        os.replace(candidate, database)
        return report
    except Exception as exc:
        if generation is not None:
            (generation / "failure.txt").write_text(str(exc) + "\n", encoding="utf-8")
        raise
    finally:
        lock.rmdir()
