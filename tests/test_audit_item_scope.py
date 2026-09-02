"""Issue #166 — the full-entry release gate consumes item_source contracts.

A gate that re-parses ``modes``/``removed`` keys and effect branches itself
lets a cache-shape or acquisition-rule change make the audit a different
item/effect universe than runtime.  These tests pin the parity:
audit scope is the typed ``item_source.audit_scope`` policy, effect
enumeration/prose come from ``effect_entries()``/``branches()``/
``effect_text()``, and every stored description reaches the receipt exactly
once.
"""

from pathlib import Path

import pytest

from scripts import full_entry_audit as audit
from src.calculator.item_source import (
    audit_scope,
    is_ordinary_sr_item,
    sr_availability,
)

# ---------------------------------------------------------------------------
# Fixtures: one item per acquisition classification
# ---------------------------------------------------------------------------


def _item(**overrides):
    base = {
        "name": "Fixture Item",
        "modes": {"classic sr 5v5": True},
        "removed": False,
        "shop": {"purchasable": True, "prices": {"total": 100}},
    }
    base.update(overrides)
    return base


SHOP = _item()
QUEST_TRANSFORM = _item(
    shop={"purchasable": False, "prices": {"total": 3000}},
    acquisitionNote="Requires [[Serrated Dirk]] to transform",
)
CHAMPION_GRANTED = _item(championRestriction=["Kled"])
MAP_OR_SYSTEM = _item(rank=["TURRET"])
REMOVED = _item(removed=True, shop={"purchasable": False})
OFF_MAP = _item(modes={"aram": True})
MISSING_SOURCE = _item(modes={})


@pytest.mark.parametrize(
    ("item", "classification", "in_scope", "selectable"),
    [
        (SHOP, "shop", True, True),
        (QUEST_TRANSFORM, "quest_transform", True, False),
        (CHAMPION_GRANTED, "champion_granted", True, False),
        (MAP_OR_SYSTEM, "map_or_system", True, False),
        (REMOVED, "removed", False, False),
        (OFF_MAP, "off_map", False, False),
        (MISSING_SOURCE, "unknown_source", False, False),
    ],
)
def test_audit_scope_matches_runtime_availability(
    item, classification, in_scope, selectable
):
    """Runtime availability and audit classification cannot disagree."""
    availability = sr_availability(item)
    scope = audit_scope(item)
    assert scope.classification == classification
    assert scope.in_scope is in_scope
    assert is_ordinary_sr_item(item) is selectable
    # Invariants that make the two contracts consistent:
    if is_ordinary_sr_item(item):
        assert scope.in_scope
    if scope.in_scope:
        assert availability.on_summoners_rift
    if not availability.on_summoners_rift:
        assert not scope.in_scope


def test_gate_scope_uses_item_source_not_mode_keys():
    """The audit must not re-derive scope from mode/removed keys itself."""
    source = audit.__file__
    text = Path(source).read_text(encoding="utf-8")
    assert "effect_entries" in text
    assert "audit_scope" in text
    assert 'modes.get("classic sr 5v5")' not in text
    assert '"classic sr 5v5"' not in text


def test_audit_item_names_matches_typed_scope_on_real_cache():
    """Every in-scope cache item is audited; off-map/removed are not."""
    import json as _json
    from pathlib import Path

    root = Path(audit.__file__).resolve().parents[1]
    items = _json.loads((root / "data" / "items.json").read_text())
    expected = sorted(
        str(value.get("name", "")).strip()
        for value in items.values()
        if isinstance(value, dict) and value.get("name") and audit_scope(value).in_scope
    )
    assert audit.audit_item_names() == expected
    assert len(expected) == 237
    assert "Diadem of Songs" in expected  # quest transform stays in scope
    assert "Muramana" in expected
    assert "Seraph's Embrace" in expected


def test_expected_effects_uses_effect_entries_branches_and_text():
    """Enumeration and complete prose come from the item_source APIs."""
    record = {
        "passives": [
            {
                "name": "Reap",
                "branches": ["Grants gold per minion.", "Disables at 100 minions."],
                "stats": {},
            }
        ],
        "active": [{"name": "Bolt", "branches": ["Fires a bolt."], "stats": {}}],
    }
    expected = audit._expected_effects("item", record)
    assert expected["branches_present"] == ["active", "passive"]
    assert expected["effect_count"] == 2
    by_name = {row["name"]: row for row in expected["effects"]}
    reap = by_name["Reap"]
    assert reap["branch_count"] == 2
    # complete prose: both branches joined exactly once
    assert reap["descriptions"] == ["Grants gold per minion.\nDisables at 100 minions."]
    assert by_name["Bolt"]["descriptions"] == ["Fires a bolt."]


def test_every_stored_description_reaches_receipt_exactly_once():
    """Multi-branch passives/actives: no branch is dropped or duplicated."""
    passive_branches = [
        "First passive branch.",
        "Second passive branch.",
        "Third passive branch.",
    ]
    active_branches = ["First active branch.", "Second active branch."]
    record = {
        "passives": [{"name": "P", "branches": passive_branches, "stats": {}}],
        "active": [{"name": "A", "branches": active_branches, "stats": {}}],
    }
    expected = audit._expected_effects("item", record)
    texts = [d for row in expected["effects"] for d in row["descriptions"]]
    assert len(texts) == 2  # one complete text per entry
    for branch in passive_branches + active_branches:
        occurrences = sum(text.count(branch) for text in texts)
        assert occurrences == 1, f"{branch!r} appears {occurrences} times"
