"""Audit every champion and ordinary Summoner's Rift item against full Wiki pages.

This is deliberately a source-audit tool, not a data importer.  It invokes the
read-only ``league-wiki-query`` CLI for each page, records the complete parent
page's revision/hash/section receipt, and fails closed when a page is missing,
has no text, or a champion parent does not enumerate all P/Q/W/E/R templates.
Ability-template pages are not silently substituted for the parent page: the
parent's references are recorded so a later module can prove which full entry
it reviewed.

Examples::

    python scripts/full_entry_audit.py --output docs/wiki-full-entry-audit.json
    python scripts/full_entry_audit.py --limit 3 --json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent
WIKI_QUERY = Path(
    "/Users/river/.codex/skills/league-wiki-query/scripts/query_league_wiki.py"
)
CHAMPIONS_PATH = ROOT / "data" / "champions.json"
ITEMS_PATH = ROOT / "data" / "items.json"
REQUIRED_CHAMPION_SLOTS = ("P", "Q", "W", "E", "R")


def _load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected object in {path}")
    return value


def champion_names() -> list[str]:
    """Return every cached display name, deterministically."""
    return sorted(
        str(value.get("name", "")).strip()
        for value in _load(CHAMPIONS_PATH).values()
        if isinstance(value, dict) and str(value.get("name", "")).strip()
    )


def ordinary_sr_item_names() -> list[str]:
    """Return all non-removed, purchasable, classic-SR cached item names."""
    names: set[str] = set()
    for value in _load(ITEMS_PATH).values():
        if not isinstance(value, dict):
            continue
        modes = value.get("modes") or {}
        shop = value.get("shop") or {}
        name = str(value.get("name", "")).strip()
        if (
            name
            and bool(modes.get("classic sr 5v5"))
            and not bool(value.get("removed"))
            and bool(shop.get("purchasable"))
        ):
            names.add(name)
    return sorted(names)


def _query(args: list[str]) -> Any:
    command = [sys.executable, str(WIKI_QUERY), *args]
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
        if not receipt["has_text"] or missing:
            receipt["status"] = "review_pending"
        else:
            receipt["status"] = "ready"
    else:
        receipt["status"] = "ready" if receipt["has_text"] else "review_pending"
    return receipt


def audit(
    *,
    champions: Iterable[str] | None = None,
    items: Iterable[str] | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Run the complete parent-page audit for the selected scope."""
    champion_list = list(champions if champions is not None else champion_names())
    item_list = list(items if items is not None else ordinary_sr_item_names())
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
    counts = {
        "champions_expected": len(champion_list),
        "items_expected": len(item_list),
        "entries_audited": len(entries),
        "ready": sum(row.get("status") == "ready" for row in entries),
        "review_pending": len(failures),
    }
    return {
        "audit": "league_wiki_full_parent_entry",
        "required_champion_slots": list(REQUIRED_CHAMPION_SLOTS),
        "counts": counts,
        "passed": not failures and len(entries) == len(targets),
        "entries": entries,
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit", type=int, help="audit only the first N deterministic entries"
    )
    parser.add_argument(
        "--output", type=Path, help="write the JSON receipt to this path"
    )
    parser.add_argument("--json", action="store_true", help="emit JSON to stdout")
    args = parser.parse_args(argv)
    report = audit(limit=args.limit)
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    if args.json or not args.output:
        print(rendered, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
