"""Front-door tests for the domain-specific atomizer adapters."""

from src.calculator.atomizer_domains import atomize_item


def test_item_domain_keeps_passive_and_active_evidence_separate() -> None:
    atoms = atomize_item(
        {
            "name": "Test Buckler",
            "stats": {},
            "shop": {"prices": {}},
            "passives": [{"name": "Shield", "branches": ["Grants a shield."]}],
            "active": [{"name": "Dash", "branches": ["Dash to a target."]}],
        }
    )
    evidence = {entry for atom in atoms for entry in atom["evidence"]}

    assert "passive:Shield@kw:shield" in evidence
    assert "active:Dash@kw:dash" in evidence


def test_the_rune_catalog_holds_every_rune_and_no_page_table() -> None:
    """Every cached rune keys by its cache key, and the two page tables
    (shards, adaptive_force) are page-level facts, not runes."""
    import json
    from pathlib import Path

    from src.calculator.atomizer_domains import atomize_rune_catalog

    path = Path(__file__).resolve().parents[1] / "data" / "runes.json"
    runes = json.loads(path.read_text(encoding="utf-8"))
    atoms = atomize_rune_catalog(runes)

    from src.calculator.rune_parser import RESERVED_CACHE_KEYS

    assert set(atoms) == set(runes) - set(RESERVED_CACHE_KEYS)
    assert "?" not in atoms
