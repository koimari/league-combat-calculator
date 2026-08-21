"""Audit every champion and ordinary Summoner's Rift item against full Wiki pages.

This is deliberately a source-audit tool, not a data importer.  It invokes the
read-only ``league-wiki-query`` CLI for each page, records the complete parent
page's revision/hash/section receipt, and fails closed when a page is missing,
has no text, or a champion parent does not enumerate all P/Q/W/E/R templates.
Ability-template pages are not silently substituted for the parent page: the
parent's references are recorded so a later module can prove which full entry
it reviewed.

The wiki query CLI is portable (issue #134): ``--query-tool`` /
``LCC_WIKI_QUERY``, then PATH, then the repo-relative vendor checkout.  A
missing tool is an infrastructure failure (exit 2) reported before any entry
is audited — never as per-entry ``review_pending``.

Examples::

    python scripts/full_entry_audit.py --output docs/wiki-full-entry-audit.json
    python scripts/full_entry_audit.py --limit 3 --json
    LCC_WIKI_QUERY=/path/to/query_league_wiki.py python scripts/full_entry_audit.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent
# The audit is invoked both as ``python scripts/...`` and as an imported
# module.  Put the project root on the import path before any champion module
# checks so the source-receipt audit cannot depend on the caller's cwd.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from gate_receipt import build_receipt
except ImportError:  # imported as scripts.full_entry_audit in tests
    from scripts.gate_receipt import build_receipt

from src.calculator.champions.module_contract import REQUIRED_CHAMPION_SLOTS

CHAMPIONS_PATH = ROOT / "data" / "champions.json"
ITEMS_PATH = ROOT / "data" / "items.json"
PACKET_MANIFEST_PATH = ROOT / "static" / "reviewed-packets.json"

# Resolved path of the read-only ``league-wiki-query`` CLI.  No developer-home
# default (issue #134): resolution order is --query-tool / LCC_WIKI_QUERY,
# then PATH, then the repo-relative vendor checkout.
QUERY_TOOL: Path | None = None


class InfrastructureError(RuntimeError):
    """A required external tool is missing or broken — not an entry finding.

    Kept distinct from per-entry ``review_pending`` so a machine-level
    failure can never masquerade as "entry needs review".
    """


def resolve_query_tool(cli_value: str | Path | None = None) -> Path:
    """Resolve the wiki query CLI or raise one actionable InfrastructureError."""
    raw = cli_value or os.environ.get("LCC_WIKI_QUERY")
    if raw:
        path = Path(str(raw)).expanduser()
        if not path.is_file():
            raise InfrastructureError(
                f"Wiki query tool not found: {path}\n"
                "Supply it with --query-tool or the LCC_WIKI_QUERY "
                "environment variable."
            )
        return path
    on_path = shutil.which("query_league_wiki.py")
    if on_path:
        return Path(on_path)
    vendor = ROOT / "vendor" / "league-wiki-query" / "scripts" / "query_league_wiki.py"
    if vendor.is_file():
        return vendor
    raise InfrastructureError(
        "Wiki query tool (query_league_wiki.py) not found.\n"
        "Install the league-wiki-query skill and point at it with "
        "--query-tool or LCC_WIKI_QUERY, add it to PATH, or vendor it at "
        "vendor/league-wiki-query/scripts/query_league_wiki.py."
    )


def _load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected object in {path}")
    return value


def _max_revision(rows: Iterable[Any]) -> int | None:
    """Largest integer revision receipt in *rows*, or None when absent."""
    revisions = [
        row["revision_id"]
        for row in rows
        if isinstance(row, dict)
        and isinstance(row.get("revision_id"), int)
        and not isinstance(row.get("revision_id"), bool)
    ]
    return max(revisions) if revisions else None


def _champion_module_receipt(name: str) -> dict[str, Any]:
    """Describe one validated runtime module and check packet evidence drift.

    Packet-backed modules fail closed on digest drift.  Hand-authored modules
    pin the revision they were reviewed against, so a newer manifest receipt
    is reported as an advisory ``stale_review_sources`` field — never a
    failure, since the pinned row honestly describes the reviewed revision.
    """
    manifest = _load(PACKET_MANIFEST_PATH)
    manifest_champion = (manifest.get("champions") or {}).get(name)
    try:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from src.calculator.champions import get_champion_module_contract
        from src.calculator.champions.packet_module import packet_spec_sha256

        contract = get_champion_module_contract(name)
    except (ImportError, KeyError, TypeError, ValueError) as exc:
        return {"name": name, "status": "review_pending", "error": str(exc)}

    coverage = contract.coverage
    runtime_slots = [slot for slot in REQUIRED_CHAMPION_SLOTS if slot in contract.slots]
    slot_coverage = [
        {
            "slot": slot,
            "name": slot,
            "kind": "runtime_slot" if slot in contract.slots else "declared_boundary",
            "status": coverage[slot],
            "reason": (
                "Slot behavior is owned by the named champion module."
                if slot in contract.slots
                else "The named champion module declares this slot boundary explicitly."
            ),
            "source": None,
            "issue_refs": [],
        }
        for slot in REQUIRED_CHAMPION_SLOTS
    ]
    manifest_packet_sha256 = (
        packet_spec_sha256(manifest_champion)
        if isinstance(manifest_champion, dict)
        else None
    )
    packet_drift = contract.packet_sha256 is not None and (
        contract.packet_sha256 != manifest_packet_sha256
        or contract.packet_spec != manifest_champion
    )
    stale_sources = None
    if contract.packet_sha256 is None and isinstance(manifest_champion, dict):
        module_revision = _max_revision(contract.sources)
        manifest_revision = _max_revision(manifest_champion.get("sources") or [])
        if (
            module_revision is not None
            and manifest_revision is not None
            and manifest_revision > module_revision
        ):
            stale_sources = {
                "module_revision_id": module_revision,
                "manifest_revision_id": manifest_revision,
            }
    ready = (
        contract.review_status == "reviewed_module"
        and bool(contract.sources)
        and set(coverage) == set(REQUIRED_CHAMPION_SLOTS)
        and not packet_drift
    )
    return {
        "name": name,
        "module": contract.module_name,
        "registration": contract.review_status,
        "review_status": contract.review_status,
        "manifest_review_status": (
            manifest_champion.get("review_status")
            if isinstance(manifest_champion, dict)
            else None
        ),
        "slots": list(REQUIRED_CHAMPION_SLOTS),
        "runtime_slots": runtime_slots,
        "slot_coverage": slot_coverage,
        "missing_slots": [],
        "invalid_slots": [],
        "source_receipts": len(contract.sources),
        "packet_evidence": contract.packet_spec is not None,
        "packet_sha256": contract.packet_sha256,
        "status": "ready" if ready else "review_pending",
        **({"stale_review_sources": stale_sources} if stale_sources else {}),
        **(
            {"error": "packet declaration drift between module and reviewed evidence"}
            if packet_drift
            else {}
        ),
    }


def champion_names() -> list[str]:
    """Return every cached display name, deterministically."""
    return sorted(
        str(value.get("name", "")).strip()
        for value in _load(CHAMPIONS_PATH).values()
        if isinstance(value, dict) and str(value.get("name", "")).strip()
    )


def audit_item_names() -> list[str]:
    """Return every item record the full-entry gate must audit.

    The audit scope is the typed :func:`item_source.audit_scope` policy:
    every item available on Summoner's Rift — including quest transforms
    (Diadem of Songs, Muramana) and non-purchasable map/system records —
    is in scope, while off-map and removed records are not.  The gate never
    parses ``modes``/``removed`` keys itself.
    """
    from src.calculator.item_source import audit_scope

    names: set[str] = set()
    for value in _load(ITEMS_PATH).values():
        if not isinstance(value, dict):
            continue
        if audit_scope(value).in_scope:
            name = str(value.get("name", "")).strip()
            if name:
                names.add(name)
    return sorted(names)


def _cached_record(kind: str, name: str) -> dict[str, Any] | None:
    """Return the tracked cache record used by the runtime for one entry."""
    path = CHAMPIONS_PATH if kind == "champion" else ITEMS_PATH
    values = _load(path).values()
    for value in values:
        if isinstance(value, dict) and str(value.get("name", "")).strip() == name:
            return value
    return None


def _runtime_entry_receipt(kind: str, name: str) -> dict[str, Any]:
    """Attach the app's explicit reasoning for the entire Wiki entry.

    A page hash alone proves provenance, not coverage.  The audit therefore
    requires a checked-in runtime reason for every full item entry and a
    reviewed five-slot module receipt for every champion entry.
    """
    record = _cached_record(kind, name)
    if record is None:
        return {
            # Direct unit tests may exercise a synthetic Wiki page that is
            # intentionally absent from the tracked cache.  The production
            # ``audit()`` target lists are always derived from that cache, so
            # this branch never weakens the full inventory gate.
            "ready": True,
            "status": "untracked_fixture",
            "reason": "Synthetic page audit; no runtime cache record requested.",
        }
    if kind == "item":
        from src.calculator.item_coverage import ATTACKER_LANES, item_model_coverage
        from src.calculator.item_effects import ITEM_EFFECTS

        coverage = item_model_coverage(
            str(record.get("name", "")), ATTACKER_LANES
        ).as_payload()
        return {
            "ready": bool(str(coverage.get("reason", "")).strip())
            and coverage.get("status") != "review_pending",
            "status": coverage.get("status"),
            "optimizer_eligible": coverage.get("optimizer_eligible"),
            "calculation_eligible": coverage.get("calculation_eligible"),
            "outcome_dimensions": coverage.get("outcome_dimensions", []),
            "review_issue_refs": coverage.get("review_issue_refs", []),
            "reason": coverage.get("reason"),
            "registry_effect_type": ITEM_EFFECTS.get(name, {}).get("type"),
        }
    module = _champion_module_receipt(name)
    return {
        "ready": module.get("status") == "ready",
        "status": module.get("status"),
        "module": module.get("module"),
        "registration": module.get("registration"),
        "review_status": module.get("review_status"),
        "manifest_review_status": module.get("manifest_review_status"),
        "source_receipts": module.get("source_receipts", 0),
        "slots": module.get("slots", []),
        "slot_coverage": module.get("slot_coverage", []),
        "issue_refs": [15, 18] if module.get("status") != "ready" else [],
        "reason": (
            "Full parent entry plus passive/Q/W/E/R source receipts are "
            "required by the reviewed champion module."
            if module.get("status") == "ready"
            else str(
                module.get(
                    "error",
                    "Champion has no complete validated named-module contract.",
                )
            )
        ),
    }


def _compact_text(value: Any, limit: int = 280) -> str:
    """Keep source-derived expectations readable without copying full pages."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _expected_effects(kind: str, record: dict[str, Any] | None) -> dict[str, Any]:
    """Summarise what the cached source says the runtime must account for.

    The full Wiki page receipt proves which document was read; this compact
    expectation ledger makes the reasoning actionable by naming every cached
    passive/active (or champion ability slot), its descriptions, and the
    runtime gap that still blocks it.  It intentionally does not claim that a
    description is a formula or that a module is certified merely because a
    name is present.
    """
    if not isinstance(record, dict):
        return {
            "source_record": "missing",
            "effects": [],
            "runtime_gaps": ["no cached runtime record"],
        }
    if kind == "item":
        from src.calculator.item_source import branches, effect_entries, effect_text

        effects: list[dict[str, Any]] = []
        kinds: list[str] = []
        for branch, entry in effect_entries(record):
            if not isinstance(entry, dict):
                continue
            prose = effect_text(entry)
            descriptions = [prose] if prose else []
            kinds.append(branch)

            def _nonzero_stat(value: Any) -> bool:
                if not isinstance(value, dict):
                    return False
                for field in (
                    "flat",
                    "percent",
                    "perLevel",
                    "percentPerLevel",
                    "percentBase",
                    "percentBonus",
                ):
                    try:
                        if float(value.get(field, 0) or 0) != 0:
                            return True
                    except (TypeError, ValueError):
                        continue
                return False

            stat_keys = sorted(
                str(key)
                for key, value in (entry.get("stats") or {}).items()
                if isinstance(value, dict) and _nonzero_stat(value)
            )
            effects.append(
                {
                    "branch": branch,
                    "name": _compact_text(entry.get("name") or branch),
                    "descriptions": descriptions,
                    "branch_count": len(branches(entry)),
                    "stat_fields": stat_keys,
                    "cooldown": entry.get("cooldown"),
                    "range": entry.get("range"),
                    "has_cooldown": entry.get("cooldown") is not None,
                    "has_range": entry.get("range") is not None,
                }
            )
        return {
            "source_record": "cached_item_entry",
            "branches_present": sorted(set(kinds)),
            "effects": effects,
            "effect_count": len(effects),
        }
    abilities = record.get("abilities") or {}
    effects = []
    for slot in REQUIRED_CHAMPION_SLOTS:
        variants = abilities.get(slot) or []
        if not isinstance(variants, list):
            variants = [variants]
        rows = []
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            descriptions = []
            for effect in variant.get("effects") or []:
                if isinstance(effect, dict):
                    descriptions.append(_compact_text(effect.get("description")))
                elif effect:
                    descriptions.append(_compact_text(effect))
            rows.append(
                {
                    "name": _compact_text(variant.get("name") or slot),
                    "description_count": len(
                        [value for value in descriptions if value]
                    ),
                    "descriptions": [value for value in descriptions if value],
                    "effect_count": len(variant.get("effects") or []),
                }
            )
        effects.append({"slot": slot, "variants": rows, "variant_count": len(rows)})
    return {
        "source_record": "cached_champion_entry",
        "required_slots": list(REQUIRED_CHAMPION_SLOTS),
        "effects": effects,
        "effect_count": sum(row["variant_count"] for row in effects),
    }


def _item_effect_coverage(
    expected: dict[str, Any], runtime: dict[str, Any]
) -> list[dict[str, Any]]:
    """Attach a path-aware verdict to every cached passive/active branch."""
    status = str(runtime.get("status") or "review_pending")
    reason = str(runtime.get("reason") or "No runtime coverage reason was recorded.")
    issue_refs = [int(value) for value in runtime.get("review_issue_refs", [])]
    rows: list[dict[str, Any]] = []
    for effect in expected.get("effects", []):
        if status == "withheld":
            verdict = "withheld"
        elif status == "stats_only":
            verdict = "stats_only" if effect.get("stat_fields") else "out_of_scope"
        elif status == "modeled_state":
            verdict = "modeled_state"
        elif status == "review_pending":
            verdict = "review_pending"
        else:
            verdict = "modeled"
        rows.append(
            {
                "branch": effect.get("branch"),
                "name": effect.get("name"),
                "verdict": verdict,
                "reason": reason,
                "issue_refs": issue_refs,
                "paths": {
                    "manual_attacker": bool(runtime.get("calculation_eligible")),
                    "enemy_target": bool(runtime.get("calculation_eligible")),
                    "ally_roster": bool(runtime.get("calculation_eligible")),
                    "optimizer": bool(runtime.get("optimizer_eligible")),
                    "api": True,
                    "frontend": True,
                },
            }
        )
    return rows


def _query(args: list[str]) -> Any:
    tool = QUERY_TOOL or resolve_query_tool()
    command = [sys.executable, str(tool), *args]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(detail or f"Wiki query failed: {' '.join(command)}")
    return json.loads(completed.stdout)


def _section_receipt(page_id: int) -> list[dict[str, Any]]:
    sections = _query(["sections", "--page-id", str(page_id)])
    if not isinstance(sections, list):
        raise ValueError(f"Wiki sections result for {page_id} is not a list")
    return [
        {
            "heading": row.get("heading"),
            "level": row.get("level"),
            "ordinal": row.get("ordinal"),
            "start_line": row.get("start_line"),
            "end_line": row.get("end_line"),
        }
        for row in sections
        if isinstance(row, dict)
    ]


def _champion_template_refs(wikitext: str) -> dict[str, str]:
    refs: dict[str, str] = {}
    for match in re.finditer(
        r"\{\{\s*Data\s+[^/{}]+/(?P<slot>[IQWER])\s*\|",
        wikitext,
        flags=re.IGNORECASE,
    ):
        slot = match.group("slot").upper()
        refs["P" if slot == "I" else slot] = match.group(0).strip()
    return refs


def _template_receipt(champion: str, slot: str) -> dict[str, Any]:
    """Read one namespace-10 ability template for the parent champion."""
    template_slot = "I" if slot == "P" else slot
    title = f"Template:Data {champion}/{template_slot}"
    page = _query(["page", "--title", title, "--namespace", "10"])
    if not isinstance(page, dict):
        raise ValueError(f"Wiki ability template result for {title!r} is not an object")
    wikitext = str(page.get("wikitext") or "")
    return {
        "slot": slot,
        "template_title": page.get("title", title),
        "page_id": page.get("page_id"),
        "namespace": page.get("namespace"),
        "source_url": page.get("source_url"),
        "revision_id": page.get("revision_id"),
        "revision_timestamp": page.get("revision_timestamp"),
        "content_sha256": page.get("content_sha256"),
        "document_sha256": page.get("document_sha256"),
        "has_text": bool(page.get("has_text")) and bool(wikitext),
        "wikitext_chars": len(wikitext),
    }


def audit_entry(kind: str, name: str) -> dict[str, Any]:
    """Audit one complete parent page and return its provenance receipt."""
    page = _query(["page", "--title", name, "--namespace", "0"])
    if not isinstance(page, dict):
        raise ValueError(f"Wiki page result for {name!r} is not an object")
    wikitext = str(page.get("wikitext") or "")
    receipt: dict[str, Any] = {
        "kind": kind,
        "name": name,
        "title": page.get("title"),
        "page_id": page.get("page_id"),
        "namespace": page.get("namespace"),
        "source_url": page.get("source_url"),
        "revision_id": page.get("revision_id"),
        "revision_timestamp": page.get("revision_timestamp"),
        "content_sha256": page.get("content_sha256"),
        "document_sha256": page.get("document_sha256"),
        "has_text": bool(page.get("has_text")) and bool(wikitext),
        "wikitext_chars": len(wikitext),
        "sections": _section_receipt(int(page["page_id"])),
    }
    runtime = _runtime_entry_receipt(kind, name)
    expected = _expected_effects(kind, _cached_record(kind, name))
    if kind == "item":
        from src.calculator.item_source import audit_scope

        scope = audit_scope(_cached_record(kind, name) or {})
        receipt["audit_scope"] = {
            "in_scope": scope.in_scope,
            "classification": scope.classification,
            "reason": scope.reason,
        }
        status = str(runtime.get("status") or "")
        expected["effect_coverage"] = _item_effect_coverage(expected, runtime)
        expected["runtime_gaps"] = (
            [str(runtime.get("reason"))]
            if status in {"withheld", "review_pending"} and runtime.get("reason")
            else []
        )
    else:
        expected["slot_coverage"] = list(runtime.get("slot_coverage", []))
        expected["runtime_gaps"] = (
            []
            if runtime.get("ready")
            else [str(runtime.get("reason") or "champion module receipt is incomplete")]
        )
    expected_json = json.dumps(expected, ensure_ascii=False, sort_keys=True)
    receipt["full_entry_review"] = {
        "required": True,
        "parent_entry_read": receipt["has_text"],
        "runtime_reasoned": runtime.get("ready", False),
        "runtime": runtime,
        "expected_effects": expected,
        "expected_effects_sha256": hashlib.sha256(
            expected_json.encode("utf-8")
        ).hexdigest(),
    }
    if kind == "champion":
        refs = _champion_template_refs(wikitext)
        receipt["ability_template_refs"] = refs
        ability_templates: list[dict[str, Any]] = []
        missing: list[str] = []
        for slot in REQUIRED_CHAMPION_SLOTS:
            try:
                template = _template_receipt(name, slot)
            except (RuntimeError, KeyError, TypeError, ValueError) as exc:
                template = {
                    "slot": slot,
                    "template_title": f"Template:Data {name}/{('I' if slot == 'P' else slot)}",
                    "has_text": False,
                    "error": str(exc),
                }
            ability_templates.append(template)
            if not template.get("has_text"):
                missing.append(slot)
        receipt["ability_templates"] = ability_templates
        # Parent pages occasionally use a named ability template instead of
        # the conventional Q/W/E/R shorthand.  The namespace-10 receipts are
        # authoritative for slot completeness, while the parent refs remain
        # evidence of what the full entry itself rendered.
        receipt["missing_ability_slots"] = missing
        if not receipt["has_text"] or missing or not runtime.get("ready", False):
            receipt["status"] = "review_pending"
        else:
            receipt["status"] = "ready"
    else:
        receipt["status"] = (
            "ready"
            if receipt["has_text"] and runtime.get("ready", False)
            else "review_pending"
        )
    return receipt


def audit(
    *,
    champions: Iterable[str] | None = None,
    items: Iterable[str] | None = None,
    limit: int | None = None,
    query_tool: str | Path | None = None,
) -> dict[str, Any]:
    """Run the complete parent-page audit for the selected scope.

    Pre-flights the query tool: a missing/broken tool raises
    :class:`InfrastructureError` before any entry is audited, so a machine
    failure is never reported as per-entry ``review_pending``.
    """
    global QUERY_TOOL
    tool = Path(query_tool) if query_tool else (QUERY_TOOL or resolve_query_tool())
    if not tool.is_file():
        raise InfrastructureError(
            f"Wiki query tool not found: {tool}\n"
            "Supply it with --query-tool or the LCC_WIKI_QUERY environment "
            "variable."
        )
    QUERY_TOOL = tool
    champion_list = list(champions if champions is not None else champion_names())
    item_list = list(items if items is not None else audit_item_names())
    entries: list[dict[str, Any]] = []
    targets = [("champion", name) for name in champion_list] + [
        ("item", name) for name in item_list
    ]
    if limit is not None:
        targets = targets[: max(0, limit)]
    failures: list[dict[str, Any]] = []
    for kind, name in targets:
        try:
            receipt = audit_entry(kind, name)
        except (RuntimeError, KeyError, TypeError, ValueError) as exc:
            receipt = {
                "kind": kind,
                "name": name,
                "status": "review_pending",
                "error": str(exc),
            }
        entries.append(receipt)
        if receipt.get("status") != "ready":
            failures.append(receipt)
    module_entries: list[dict[str, Any]] = []
    module_failures: list[dict[str, Any]] = []
    for name in champion_list:
        module_receipt = _champion_module_receipt(name)
        module_entries.append(module_receipt)
        if module_receipt.get("status") != "ready":
            module_failures.append(module_receipt)
    counts = {
        "champions_expected": len(champion_list),
        "items_expected": len(item_list),
        "entries_audited": len(entries),
        "ready": sum(row.get("status") == "ready" for row in entries),
        "review_pending": len(failures),
        "champion_modules_expected": len(champion_list),
        "champion_modules_ready": len(module_entries) - len(module_failures),
        "champion_modules_review_pending": len(module_failures),
    }
    passed = (
        not failures
        and not module_failures
        and len(entries) == len(targets)
        and len(module_entries) == len(champion_list)
    )
    # Envelope: the gate's contract units are the full expected
    # scope — every audited target plus every champion module receipt.  A
    # --limit run that only audits part of the scope therefore cannot pass.
    total = len(targets) + len(champion_list)
    failed = (
        len(failures)
        + len(module_failures)
        + max(0, len(targets) - len(entries))
        + max(0, len(champion_list) - len(module_entries))
    )
    report = build_receipt(
        matrix="league_wiki_full_parent_entry",
        passed=passed,
        passed_count=total - failed,
        failed_count=failed,
        total_count=total,
        withheld_count=0,
        failures=failures,
        extra={
            "audit": "league_wiki_full_parent_entry",
            "required_champion_slots": list(REQUIRED_CHAMPION_SLOTS),
            "entries": entries,
            "champion_modules": module_entries,
            "champion_module_failures": module_failures,
            "infrastructure": {"ok": True, "query_tool": str(tool)},
        },
    )
    # The detailed per-scope counts stay addressable for existing consumers.
    report["counts"].update(counts)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit", type=int, help="audit only the first N deterministic entries"
    )
    parser.add_argument(
        "--output", type=Path, help="write the JSON receipt to this path"
    )
    parser.add_argument("--json", action="store_true", help="emit JSON to stdout")
    parser.add_argument(
        "--query-tool",
        type=Path,
        help="path to query_league_wiki.py (env LCC_WIKI_QUERY; default: "
        "PATH, then vendor/league-wiki-query/scripts/)",
    )
    args = parser.parse_args(argv)
    # Pre-flight: a missing query tool is an infrastructure failure (exit 2),
    # distinct from a gate that found review-pending entries (exit 1).
    try:
        tool = resolve_query_tool(args.query_tool)
    except InfrastructureError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    report = audit(limit=args.limit, query_tool=tool)
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    if args.json or not args.output:
        print(rendered, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
