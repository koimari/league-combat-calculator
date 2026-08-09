"""Front-door tests for the domain-specific atomizer adapters."""

from src.calculator.atomizer_domains import atomize_item


def test_item_domain_keeps_passive_and_active_evidence_separate() -> None:
    atoms = atomize_item(
        {
            "name": "Test Buckler",
            "passives": [{"name": "Shield", "branches": ["Grants a shield."]}],
            "active": [{"name": "Dash", "branches": ["Dash to a target."]}],
        }
    )
    evidence = {entry for atom in atoms for entry in atom["evidence"]}

    assert "passive:Shield@kw:shield" in evidence
    assert "active:Dash@kw:dash" in evidence
