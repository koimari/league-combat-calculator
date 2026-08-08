"""Issue #134: patch day is portable and fails closed on stale reviewed packets.

Covers the four patch-day scripts' portability contract (no developer-home
defaults), the fail-closed reviewed-packet chain (missing wiki DB, zero
receipts, revision-less champions never labeled reviewed), the audit's
distinct infrastructure-failure signal, the cdtb failure path, and the
patch-day pipeline gates that run before golden capture.
"""

import json
import sqlite3
from pathlib import Path

import pytest

import scripts.build_reviewed_modules as brm
import scripts.full_entry_audit as audit
import scripts.patch_regression as patch_regression
import scripts.patch_update as patch_update
from scripts.source_receipt import source_receipt

ROOT = Path(__file__).resolve().parents[1]

PATCH_DAY_SCRIPTS = (
    "build_reviewed_modules.py",
    "full_entry_audit.py",
    "patch_regression.py",
    "patch_update.py",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_axword(tmp_path: Path) -> Path:
    path = tmp_path / "merakiAbilityKits.ts"
    path.write_text(
        "export const MERAKI_ABILITY_KITS = {\n"
        '  "Fixture": {"abilities": []}\n'
        "}\n"
        "\n"
        "export const MERAKI_ABILITY_KIT_IDS = {}\n",
        encoding="utf-8",
    )
    return path


def _write_champions(tmp_path: Path, names=("Fixture", "Other")) -> Path:
    path = tmp_path / "champions.json"
    payload = {name.lower(): {"name": name, "abilities": {}} for name in names}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_wiki_db(tmp_path: Path, receipts=None, name="wiki.sqlite3") -> Path:
    """Create a minimal ``pages``-shaped wiki index."""
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


def _asset_with_receipts(
    champions_path: Path, axword_path: Path, revisions: dict
) -> dict:
    """A packet asset that correctly embeds receipts for the given sources."""
    return {
        "schema_version": 1,
        "patch": "26.16",
        "source_receipts": {
            "champions.json": source_receipt(champions_path, kind="tracked wiki cache"),
            "axword_source": source_receipt(
                axword_path, kind="Axword Meraki ability kits"
            ),
        },
        "champions": {
            name: {
                "review_status": "reviewed_packet",
                "sources": [
                    {
                        "label": "Local League Wiki cache",
                        "url": f"https://wiki.leagueoflegends.com/en-us/{name}",
                        "revision_id": revision,
                        "revision_timestamp": "2026-01-01T00:00:00Z",
                    }
                ],
            }
            for name, revision in revisions.items()
        },
    }


# ---------------------------------------------------------------------------
# Portability
# ---------------------------------------------------------------------------


def test_no_developer_home_paths_in_patch_day_tools():
    """No script may carry a developer-home absolute default (acceptance gate)."""
    for name in PATCH_DAY_SCRIPTS:
        text = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert '"/Users/' not in text, f"{name} hardcodes a /Users/ path"
        assert "'/Users/" not in text, f"{name} hardcodes a /Users/ path"
        assert '"/home/' not in text, f"{name} hardcodes a /home/ path"
        assert '"~/' not in text, f"{name} hardcodes a ~ path"
        assert "'~/" not in text, f"{name} hardcodes a ~ path"


# ---------------------------------------------------------------------------
# build_reviewed_modules: fail closed on missing prerequisites
# ---------------------------------------------------------------------------


def test_build_fails_closed_when_wiki_db_missing(tmp_path):
    champions = _write_champions(tmp_path)
    axword = _write_axword(tmp_path)
    output = tmp_path / "out" / "reviewed-packets.json"
    missing = tmp_path / "missing.sqlite3"
    with pytest.raises(RuntimeError, match="--wiki-db|LCC_WIKI_DB"):
        brm.build(champions, axword, output, wiki_db=missing)
    assert not output.exists(), "no output may be written on a missing wiki DB"


def test_build_aborts_on_zero_revision_receipts(tmp_path):
    champions = _write_champions(tmp_path)
    axword = _write_axword(tmp_path)
    db = _write_wiki_db(tmp_path, {})
    output = tmp_path / "reviewed-packets.json"
    with pytest.raises(RuntimeError, match="zero revision receipts"):
        brm.build(champions, axword, output, wiki_db=db)
    assert not output.exists()


def test_revisionless_packets_never_labeled_reviewed(tmp_path):
    champions = _write_champions(tmp_path, ("Fixture", "Other"))
    axword = _write_axword(tmp_path)
    db = _write_wiki_db(tmp_path, {"Fixture": 123})
    output = tmp_path / "reviewed-packets.json"
    brm.build(champions, axword, output, wiki_db=db)

    asset = json.loads(output.read_text(encoding="utf-8"))
    assert asset["champions"]["Fixture"]["review_status"] == "reviewed_packet"
    assert asset["champions"]["Other"]["review_status"] == "generated_packet"
    other_sources = asset["champions"]["Other"]["sources"]
    assert not any(source.get("revision_id") for source in other_sources)
    fixture_sources = asset["champions"]["Fixture"]["sources"]
    assert fixture_sources[0]["revision_id"] == 123
    # The asset now embeds machine-readable source receipts (no hardcoded patch).
    assert asset["source_receipts"]["champions.json"]["sha256"]
    assert asset["source_receipts"]["axword_source"]["sha256"]
    assert asset["patch"] == "unknown"  # fixture icons carry no ddragon version


def test_build_missing_axword_source_is_one_actionable_failure(tmp_path):
    champions = _write_champions(tmp_path)
    db = _write_wiki_db(tmp_path, {"Fixture": 123})
    output = tmp_path / "reviewed-packets.json"
    with pytest.raises(RuntimeError, match="axword|LCC_AXWORD_SOURCE"):
        brm.build(
            champions,
            tmp_path / "absent-merakiAbilityKits.ts",
            output,
            wiki_db=db,
        )
    assert not output.exists()


# ---------------------------------------------------------------------------
# full_entry_audit: distinct infrastructure failure + pre-flight
# ---------------------------------------------------------------------------


def test_audit_fails_fast_and_distinctly_when_query_tool_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "QUERY_TOOL", None)
    monkeypatch.setenv("LCC_WIKI_QUERY", str(tmp_path / "missing_query_league_wiki.py"))
    with pytest.raises(audit.InfrastructureError):
        audit.audit(limit=1)
    rc = audit.main(["--limit", "1", "--json"])
    assert rc == 2, "infrastructure failure must exit 2, not a review-pending 1"


def test_audit_report_marks_infrastructure_ok(tmp_path, monkeypatch):
    tool = tmp_path / "query_league_wiki.py"
    tool.write_text("", encoding="utf-8")
    monkeypatch.setattr(audit, "QUERY_TOOL", None)
    report = audit.audit(champions=[], items=[], query_tool=tool)
    assert report["infrastructure"] == {"ok": True, "query_tool": str(tool)}
    assert report["passed"] is True


# ---------------------------------------------------------------------------
# patch_regression: actionable cdtb failure
# ---------------------------------------------------------------------------


def test_resolve_patch_without_cdtb_raises_actionable_error():
    with pytest.raises(RuntimeError, match="CDTB_BIN|--patch"):
        patch_regression.resolve_patch(cdtb_bin="/nonexistent/cdtb")


def test_patch_regression_main_exits_2_when_cdtb_missing(monkeypatch, tmp_path):
    def boom(*_args, **_kwargs):
        raise RuntimeError(
            "cdtb not found — install it and set CDTB_BIN, or pin with --patch <version>"
        )

    monkeypatch.setattr(patch_regression, "resolve_patch", boom)
    rc = patch_regression.main(
        [
            "check",
            "--cache-dir",
            str(tmp_path),
            "--data-dir",
            str(tmp_path),
            "--out",
            str(tmp_path / "staleness.json"),
        ]
    )
    assert rc == 2


# ---------------------------------------------------------------------------
# Reviewed-packet freshness gate (fixture-driven)
# ---------------------------------------------------------------------------


def _fresh_sources(tmp_path):
    champions = _write_champions(tmp_path, ("Fixture",))
    axword = _write_axword(tmp_path)
    db = _write_wiki_db(tmp_path, {"Fixture": 123})
    asset_path = tmp_path / "reviewed-packets.json"
    asset_path.write_text(
        json.dumps(_asset_with_receipts(champions, axword, {"Fixture": 123})),
        encoding="utf-8",
    )
    return asset_path, champions, axword, db


def test_packet_freshness_gate_passes_when_asset_matches_sources(tmp_path):
    asset_path, champions, axword, db = _fresh_sources(tmp_path)
    problems = patch_update.check_reviewed_packets_current(
        asset_path=asset_path,
        champions_source=champions,
        axword_source=axword,
        wiki_db=db,
    )
    assert problems == []


def test_packet_freshness_gate_detects_changed_champion_data(tmp_path):
    """A patch that changes a packet-backed champion fails the gate."""
    asset_path, champions, axword, db = _fresh_sources(tmp_path)
    mutated = tmp_path / "champions-mutated.json"
    payload = json.loads(champions.read_text(encoding="utf-8"))
    payload["fixture"]["abilities"] = {
        "Q": [{"name": "Pulse", "effects": []}]
    }  # the patch moved a number
    mutated.write_text(json.dumps(payload), encoding="utf-8")

    problems = patch_update.check_reviewed_packets_current(
        asset_path=asset_path,
        champions_source=mutated,
        axword_source=axword,
        wiki_db=db,
    )
    assert any("data/champions.json changed" in problem for problem in problems)


def test_packet_freshness_gate_detects_stale_wiki_revision(tmp_path):
    asset_path, champions, axword, db = _fresh_sources(tmp_path)
    moved = _write_wiki_db(tmp_path, {"Fixture": 999})  # wiki page was re-edited
    problems = patch_update.check_reviewed_packets_current(
        asset_path=asset_path,
        champions_source=champions,
        axword_source=axword,
        wiki_db=moved,
    )
    assert any("not current" in problem for problem in problems)


def test_packet_freshness_gate_detects_receiptless_asset(tmp_path):
    champions = _write_champions(tmp_path, ("Fixture",))
    axword = _write_axword(tmp_path)
    db = _write_wiki_db(tmp_path, {"Fixture": 123})
    asset_path = tmp_path / "reviewed-packets.json"
    asset_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "patch": "16.15",
                "champions": {
                    "Fixture": {
                        "review_status": "reviewed_packet",
                        "sources": [
                            {
                                "label": "Local League Wiki cache",
                                "url": "https://wiki.leagueoflegends.com/en-us/Fixture",
                                "revision_id": 123,
                                "revision_timestamp": "2026-01-01T00:00:00Z",
                            }
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    problems = patch_update.check_reviewed_packets_current(
        asset_path=asset_path,
        champions_source=champions,
        axword_source=axword,
        wiki_db=db,
    )
    assert any("no source receipts" in problem for problem in problems)


# ---------------------------------------------------------------------------
# patch_update.run_full: gates run before golden capture
# ---------------------------------------------------------------------------


def test_patch_update_run_aborts_before_capture_on_stale_packet(monkeypatch):
    """Acceptance criterion: a stale packet aborts run_full before run_gates."""
    gate_calls = []

    monkeypatch.setattr(patch_update, "clear_wiki_caches", lambda: None)
    monkeypatch.setattr(patch_update, "run_pull", lambda: "26.16")
    monkeypatch.setattr(patch_update, "print_audit", lambda: True)
    monkeypatch.setattr(patch_update, "rebuild_static_artifacts", lambda: 0)
    monkeypatch.setattr(
        patch_update,
        "check_reviewed_packets_current",
        lambda **kwargs: [
            "data/champions.json changed since the packet asset was reviewed"
        ],
    )

    def run_gates():
        gate_calls.append("run_gates")
        return 0

    monkeypatch.setattr(patch_update, "run_gates", run_gates)

    rc = patch_update.run_full()
    assert rc == 1
    assert gate_calls == [], "golden capture must never run on a stale packet"


def test_patch_update_run_aborts_before_capture_on_review_pending(monkeypatch):
    gate_calls = []

    monkeypatch.setattr(patch_update, "clear_wiki_caches", lambda: None)
    monkeypatch.setattr(patch_update, "run_pull", lambda: "26.16")
    monkeypatch.setattr(patch_update, "print_audit", lambda: True)
    monkeypatch.setattr(patch_update, "rebuild_static_artifacts", lambda: 0)
    monkeypatch.setattr(patch_update, "check_reviewed_packets_current", lambda **kw: [])
    monkeypatch.setattr(patch_update, "run_full_entry_audit", lambda output=None: 1)

    def run_gates():
        gate_calls.append("run_gates")
        return 0

    monkeypatch.setattr(patch_update, "run_gates", run_gates)

    rc = patch_update.run_full()
    assert rc == 1
    assert gate_calls == []


def test_patch_update_run_green_path_invokes_all_gates_then_capture(monkeypatch):
    order = []

    monkeypatch.setattr(patch_update, "clear_wiki_caches", lambda: None)
    monkeypatch.setattr(patch_update, "run_pull", lambda: "26.16")
    monkeypatch.setattr(patch_update, "print_audit", lambda: True)
    monkeypatch.setattr(
        patch_update, "rebuild_static_artifacts", lambda: order.append("rebuild") or 0
    )
    monkeypatch.setattr(
        patch_update,
        "check_reviewed_packets_current",
        lambda **kwargs: order.append("packets") or [],
    )
    monkeypatch.setattr(
        patch_update,
        "run_full_entry_audit",
        lambda output=None: order.append("audit") or 0,
    )
    monkeypatch.setattr(
        patch_update,
        "run_staleness_gate",
        lambda out=None, patch=None: order.append("staleness") or 0,
    )
    monkeypatch.setattr(patch_update, "run_gates", lambda: order.append("capture") or 0)

    rc = patch_update.run_full(patch="26.16")
    assert rc == 0
    assert order == ["rebuild", "packets", "audit", "staleness", "capture"]
