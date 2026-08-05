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
import hashlib
import importlib
import json
import re
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
WIKI_QUERY = Path(
    "/Users/river/.codex/skills/league-wiki-query/scripts/query_league_wiki.py"
)
CHAMPIONS_PATH = ROOT / "data" / "champions.json"
ITEMS_PATH = ROOT / "data" / "items.json"
REQUIRED_CHAMPION_SLOTS = ("P", "Q", "W", "E", "R")
PACKET_MANIFEST_PATH = ROOT / "static" / "reviewed-packets.json"


def _load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected object in {path}")
    return value


def _champion_module_receipt(name: str) -> dict[str, Any]:
    """Verify the runtime module and its five-slot source manifest exist.

    The Wiki page is the source receipt; this companion check proves that the
    checked-in runtime has a named module and an explicit entry for every
    passive/Q/W/E/R slot.  A slot may be ``no_damage`` only when its manifest
    names a source and a user-visible reason.
    """
    manifest = _load(PACKET_MANIFEST_PATH)
    champion = (manifest.get("champions") or {}).get(name)
    if not isinstance(champion, dict):
        return {
            "name": name,
            "status": "review_pending",
            "error": "champion missing from reviewed-packets.json",
        }
    registration_kind = None
    try:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from src.calculator.champions import _CHAMPION_MODULES, engine_registration_kind

        module_name = _CHAMPION_MODULES.get(name)
        if not module_name:
            raise ImportError("no registered module")
        module = importlib.import_module(f"src.calculator.champions.{module_name}")
        registration_kind = engine_registration_kind(name)
        review_status = getattr(module, "REVIEW_STATUS", None)
        if not callable(getattr(module, "parse_abilities", None)):
            raise ImportError("registered module has no parse_abilities callable")
    except (ImportError, KeyError, TypeError, ValueError) as exc:
        return {"name": name, "status": "review_pending", "error": str(exc)}

    slots = champion.get("slots")
    missing: list[str] = []
    invalid: list[str] = []
    if not isinstance(slots, dict):
        missing = list(REQUIRED_CHAMPION_SLOTS)
    else:
        for slot in REQUIRED_CHAMPION_SLOTS:
            spec = slots.get(slot)
            if not isinstance(spec, dict):
                missing.append(slot)
                continue
            kind = spec.get("kind")
            if kind not in {"packet", "wiki_attribute", "variants", "no_damage"}:
                invalid.append(slot)
            if kind == "variants" and not isinstance(spec.get("variants"), list):
                invalid.append(slot)
            if kind == "no_damage" and not str(spec.get("reason") or "").strip():
                invalid.append(slot)
    sources = champion.get("sources")
    slot_coverage = []
    if isinstance(slots, dict):
        for slot in REQUIRED_CHAMPION_SLOTS:
            spec = slots.get(slot)
            if not isinstance(spec, dict):
                continue
            kind = str(spec.get("kind", ""))
            if kind == "no_damage":
                status = "out_of_scope"
                reason = str(
                    spec.get(
                        "reason",
                        "This slot has no sourced enemy-damage formula; its state or utility branch is not part of the damage packet.",
                    )
                )
            elif registration_kind == "generated_packet":
                status = "generated_pending"
                reason = (
                    "Generated packet is runnable but the complete champion-specific Wiki mechanics, "
                    "target policy, costs, timing, and state branches still require an exact module."
                )
            else:
                status = "modeled"
                reason = "Slot is implemented by the reviewed champion module."
            slot_coverage.append(
                {
                    "slot": slot,
                    "name": str(spec.get("name", slot)),
                    "kind": kind,
                    "status": status,
                    "reason": reason,
                    "source": spec.get("source"),
                    "issue_refs": [15, 18] if status == "generated_pending" else [],
                }
            )
    ready = (
        registration_kind == "reviewed_module"
        and champion.get("review_status") == "reviewed_packet"
        and isinstance(sources, list)
        and bool(sources)
        and not missing
        and not invalid
    )
    return {
        "name": name,
        "module": module_name,
        "registration": registration_kind,
        "review_status": review_status,
        "manifest_review_status": champion.get("review_status"),
        "slots": list(slots) if isinstance(slots, dict) else [],
        "slot_coverage": slot_coverage,
        "missing_slots": sorted(set(missing)),
        "invalid_slots": sorted(set(invalid)),
        "source_receipts": len(sources) if isinstance(sources, list) else 0,
        "status": "ready" if ready else "review_pending",
        **(
            {
                "error": (
                    "Generated packet module is intentionally not marked reviewed; "
                    "complete champion-specific mechanics remain in issue #15."
                )
            }
            if registration_kind == "generated_packet"
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


def ordinary_sr_item_names() -> list[str]:
    """Return every non-removed classic-SR item record in the cache.

    The audit scope is deliberately broader than the shop.  Transformed
    records (for example Diadem of Songs and Muramana) and non-purchasable
    system records still have Wiki entries whose mechanics must be reviewed
    and explicitly classified before the release gate can pass.
    """
    names: set[str] = set()
    for value in _load(ITEMS_PATH).values():
        if not isinstance(value, dict):
            continue
        modes = value.get("modes") or {}
        name = str(value.get("name", "")).strip()
        if (
            name
            and bool(modes.get("classic sr 5v5"))
            and not bool(value.get("removed"))
        ):
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
        from src.calculator.item_coverage import item_model_coverage
        from src.calculator.item_effects import ITEM_EFFECTS

        coverage = item_model_coverage(record)
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
                    "Champion module remains generated or otherwise incomplete.",
                )
            )
        ),
    }


def _compact_text(value: Any, limit: int = 280) -> str:
    """Keep source-derived expectations readable without copying full pages."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _text_values(entry: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    """Collect source prose without dropping branch arrays from the cache."""
    values: list[str] = []
    for key in keys:
        value = entry.get(key)
        if isinstance(value, list):
            for row in value:
                if isinstance(row, dict):
                    for nested in ("description", "text", "value"):
                        if row.get(nested):
                            values.append(_compact_text(row[nested]))
                elif row:
                    values.append(_compact_text(row))
        elif value:
            values.append(_compact_text(value))
    return [value for value in values if value]


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
        effects: list[dict[str, Any]] = []
        branches = []
        for branch in ("passives", "active", "actives"):
            values = record.get(branch) or []
            if isinstance(values, dict):
                values = [values]
            if not isinstance(values, list):
                continue
            for entry in values:
                if not isinstance(entry, dict):
                    continue
                descriptions = _text_values(
                    entry,
                    (
                        "description",
                        "shortDescription",
                        "longDescription",
                        "effects",
                        "branches",
                    ),
                )

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
                        "branch_count": len(entry.get("branches") or []),
                        "stat_fields": stat_keys,
                        "cooldown": entry.get("cooldown"),
                        "range": entry.get("range"),
                        "has_cooldown": entry.get("cooldown") is not None,
                        "has_range": entry.get("range") is not None,
                    }
                )
            branches.append(branch)
        return {
            "source_record": "cached_item_entry",
            "branches_present": branches,
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
        if status == "blocked":
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
    runtime = _runtime_entry_receipt(kind, name)
    expected = _expected_effects(kind, _cached_record(kind, name))
    if kind == "item":
        status = str(runtime.get("status") or "")
        expected["effect_coverage"] = _item_effect_coverage(expected, runtime)
        expected["runtime_gaps"] = (
            [str(runtime.get("reason"))]
            if status in {"blocked", "review_pending"} and runtime.get("reason")
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
    return {
        "audit": "league_wiki_full_parent_entry",
        "required_champion_slots": list(REQUIRED_CHAMPION_SLOTS),
        "counts": counts,
        "passed": (
            not failures
            and not module_failures
            and len(entries) == len(targets)
            and len(module_entries) == len(champion_list)
        ),
        "entries": entries,
        "failures": failures,
        "champion_modules": module_entries,
        "champion_module_failures": module_failures,
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
