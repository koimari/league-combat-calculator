"""Tests for the read-only full Wiki parent-entry audit."""

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


def test_item_scope_excludes_removed_or_non_purchasable_items(monkeypatch):
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
    assert audit.ordinary_sr_item_names() == ["One"]


def test_champion_module_receipts_cover_every_cached_champion():
    """The full-entry gate cannot pass while a registered module is missing."""
    names = audit.champion_names()
    assert len(names) == 173
    receipts = [audit._champion_module_receipt(name) for name in names]
    assert all(receipt["status"] == "ready" for receipt in receipts)
    assert all(
        set(receipt["slots"]) == {"P", "Q", "W", "E", "R"} for receipt in receipts
    )
