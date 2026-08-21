"""Tests for the read-only full Wiki parent-entry audit."""

from copy import deepcopy

from scripts import full_entry_audit as audit


def test_champion_audit_requires_parent_and_all_namespace_10_templates(monkeypatch):
    calls = []

    def fake_query(args):
        calls.append(args)
        if args[0] == "sections":
            return []
        title = args[2]
        if args[0] == "page" and args[4] == "0":
            return {
                "title": title,
                "page_id": 10,
                "namespace": 0,
                "source_url": "https://wiki.example/champion",
                "revision_id": 123,
                "revision_timestamp": "2026-01-01T00:00:00Z",
                "content_sha256": "content",
                "document_sha256": "document",
                "has_text": 1,
                "wikitext": (
                    "== Abilities ==\n"
                    "{{Data Fixture/I|Ability}}\n"
                    "{{Data Fixture/Q|Ability}}\n"
                ),
            }
        return {
            "title": title,
            "page_id": 20,
            "namespace": 10,
            "source_url": "https://wiki.example/template",
            "revision_id": 456,
            "revision_timestamp": "2026-01-01T00:00:00Z",
            "content_sha256": "template-content",
            "document_sha256": "template-document",
            "has_text": 1,
            "wikitext": "{{Data template}}",
        }

    monkeypatch.setattr(audit, "_query", fake_query)
    receipt = audit.audit_entry("champion", "Fixture")
    assert receipt["status"] == "ready"
    assert receipt["missing_ability_slots"] == []
    assert {row["slot"] for row in receipt["ability_templates"]} == {
        "P",
        "Q",
        "W",
        "E",
        "R",
    }
    assert any(args[:2] == ["page", "--title"] for args in calls)


def test_item_scope_includes_transformed_and_non_purchasable_records(monkeypatch):
    monkeypatch.setattr(
        audit,
        "_load",
        lambda _path: {
            "one": {
                "name": "One",
                "modes": {"classic sr 5v5": True},
                "removed": False,
                "shop": {"purchasable": True},
            },
            "two": {
                "name": "Two",
                "modes": {"classic sr 5v5": True},
                "removed": True,
                "shop": {"purchasable": True},
            },
            "three": {
                "name": "Three",
                "modes": {"classic sr 5v5": True},
                "removed": False,
                "shop": {"purchasable": False},
            },
        },
    )
    assert audit.audit_item_names() == ["One", "Three"]


def test_champion_module_receipts_cover_every_cached_champion():
    """The full-entry gate reports every cached champion as a reviewed module."""
    from src.calculator.champions import registered_champion_names

    names = audit.champion_names()
    assert len(names) == len(registered_champion_names())
    receipts = [audit._champion_module_receipt(name) for name in names]
    assert sum(receipt["status"] == "ready" for receipt in receipts) == len(names)
    assert sum(receipt["status"] == "review_pending" for receipt in receipts) == 0
    assert all(receipt["status"] == "ready" for receipt in receipts)
    assert all(
        receipt["registration"] == "reviewed_module" and receipt["slot_coverage"]
        for receipt in receipts
        if receipt["status"] == "ready"
    )
    assert all(
        set(receipt["slots"]) == {"P", "Q", "W", "E", "R"} for receipt in receipts
    )


def test_jayce_audit_receipt_comes_from_his_named_module_contract():
    """Jayce's runtime slots/coverage cannot be borrowed from the manifest."""
    receipt = audit._champion_module_receipt("Jayce")

    assert receipt["status"] == "ready"
    assert receipt["registration"] == "reviewed_module"
    assert receipt["runtime_slots"] == ["P", "Q", "W", "E", "R"]
    assert {row["slot"]: row["status"] for row in receipt["slot_coverage"]} == {
        "P": "no_damage",
        "Q": "modeled",
        "W": "modeled",
        "E": "modeled",
        "R": "modeled",
    }


def test_packet_backed_module_audit_fails_if_evidence_manifest_drifts(monkeypatch):
    """Resolved packet declarations are pinned in the module contract."""
    original_load = audit._load
    manifest = deepcopy(original_load(audit.PACKET_MANIFEST_PATH))
    manifest["champions"]["Singed"]["slots"]["E"]["kind"] = "no_damage"

    def fake_load(path):
        if path == audit.PACKET_MANIFEST_PATH:
            return manifest
        return original_load(path)

    monkeypatch.setattr(audit, "_load", fake_load)
    receipt = audit._champion_module_receipt("Singed")

    assert receipt["status"] == "review_pending"
    assert "packet declaration drift" in receipt["error"]


def test_hand_authored_module_stale_sources_are_advisory(monkeypatch):
    """A newer manifest revision flags hand-authored receipts without failing.

    Packet-backed modules fail closed on digest drift; hand-authored modules
    pin the revision they were reviewed against.  When a patch re-pull bumps
    the manifest receipt, the audit reports the stale review instead of
    silently letting the pinned row look current.
    """
    assert "stale_review_sources" not in audit._champion_module_receipt("Aatrox")

    original_load = audit._load
    manifest = deepcopy(original_load(audit.PACKET_MANIFEST_PATH))
    rows = manifest["champions"]["Aatrox"]["sources"]
    reviewed_revision = max(row["revision_id"] for row in rows)
    for row in rows:
        row["revision_id"] = reviewed_revision + 1

    def fake_load(path):
        if path == audit.PACKET_MANIFEST_PATH:
            return manifest
        return original_load(path)

    monkeypatch.setattr(audit, "_load", fake_load)
    receipt = audit._champion_module_receipt("Aatrox")

    assert receipt["status"] == "ready"
    assert receipt["stale_review_sources"] == {
        "module_revision_id": reviewed_revision,
        "manifest_revision_id": reviewed_revision + 1,
    }


def test_full_item_scope_includes_transformed_records():
    names = audit.audit_item_names()
    assert len(names) == 237
    assert "Diadem of Songs" in names
    assert "Muramana" in names
    assert "Seraph's Embrace" in names


def test_expected_effects_names_every_item_branch_and_champion_slot():
    item = audit._expected_effects(
        "item",
        {
            "passives": [
                {"name": "Passive", "branches": ["Deals damage."], "stats": {}}
            ],
            "active": [
                {"name": "Active", "branches": ["Grants a shield."], "stats": {}}
            ],
        },
    )
    assert item["effect_count"] == 2
    assert {row["name"] for row in item["effects"]} == {"Passive", "Active"}
    assert all("descriptions" in row for row in item["effects"])
    champion = audit._expected_effects(
        "champion",
        {
            "abilities": {
                slot: [
                    {"name": f"{slot} ability", "effects": [{"description": "text"}]}
                ]
                for slot in audit.REQUIRED_CHAMPION_SLOTS
            }
        },
    )
    assert [row["slot"] for row in champion["effects"]] == list(
        audit.REQUIRED_CHAMPION_SLOTS
    )
    assert all(row["variant_count"] == 1 for row in champion["effects"])


def test_full_entry_audit_emits_the_gate_receipt_envelope():
    """The audit receipt carries the shared envelope (issue #139)."""
    from scripts.gate_receipt import SCHEMA_VERSION, validate_receipt

    report = audit.audit(champions=[], items=[], query_tool=__file__)
    validate_receipt(report)
    assert report["schema_version"] == SCHEMA_VERSION
    assert type(report["passed"]) is bool
    assert report["counts"]["total"] == 0
    assert report["counts"]["failed"] == 0
    assert report["failures"] == []
    # The detailed per-scope counts remain addressable alongside the envelope.
    assert report["counts"]["champions_expected"] == 0


def test_item_effect_receipt_keeps_each_branch_and_runtime_path_visible():
    expected = audit._expected_effects(
        "item",
        {
            "passives": [
                {
                    "name": "Cleave",
                    "branches": [
                        "Primary: hits nearby enemies.",
                        "Secondary: also slows.",
                    ],
                    "stats": {},
                }
            ]
        },
    )
    runtime = {
        "status": "withheld",
        "reason": "Secondary target timing is not modeled.",
        "review_issue_refs": [43],
        "calculation_eligible": False,
        "optimizer_eligible": False,
    }

    rows = audit._item_effect_coverage(expected, runtime)

    assert len(rows) == 1
    assert rows[0]["verdict"] == "withheld"
    assert rows[0]["issue_refs"] == [43]
    assert rows[0]["paths"] == {
        "manual_attacker": False,
        "enemy_target": False,
        "ally_roster": False,
        "optimizer": False,
        "api": True,
        "frontend": True,
    }
