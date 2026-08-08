"""Issue #162: public domain rules have one backend-owned contract."""

from pathlib import Path

import src.app as app_module
from src.calculator.bis import bis_objective_contract
from src.calculator.pipeline import rank_allocation_contract
from src.calculator.role_quests import role_quest_domain_contract

APP_JS = Path("static/js/app.js").read_text(encoding="utf-8")


def test_config_publishes_the_domain_contract_from_its_owners():
    response = app_module.app.test_client().get("/api/config")

    assert response.status_code == 200
    contract = response.get_json()["domain_contract"]
    assert contract["role_quest"] == role_quest_domain_contract()
    assert contract["rank_allocation"] == rank_allocation_contract()
    assert contract["bis_objectives"] == bis_objective_contract()


def test_role_contract_covers_every_role_and_quest_state():
    role_contract = role_quest_domain_contract()

    assert role_contract["roles"] == ["bottom", "jungle", "mid", "support", "top"]
    for rule_name in ("level_cap", "inventory_capacity", "boots_tier"):
        rule = role_contract[rule_name]
        assert rule["default"] is not None
        assert set(rule["by_role"]) == set(role_contract["roles"])
        for role in role_contract["roles"]:
            assert set(rule["by_role"][role]) == {"incomplete", "complete"}


def test_frontend_consumes_domain_contracts_and_the_fetched_boot_catalogue():
    assert "applyDomainContract(config.domain_contract || {})" in APP_JS
    assert "engine.boots = Array.isArray(bootCatalog) ? bootCatalog : [];" in APP_JS
    assert "engine.bootIds = new Set(engine.boots.map" in APP_JS
    assert "function roleInventoryCapacity(" in APP_JS
    assert "function roleLevelCap(" in APP_JS
    assert "function roleBootsTier(" in APP_JS
    assert "function isRoleBoot(" in APP_JS
    assert "function usesLevelDerivedRanks(" in APP_JS
    assert "function applyDomainContract(" in APP_JS
    assert "const SPINE_METRICS = [" not in APP_JS
    assert "const OBJECTIVES = {" not in APP_JS
    assert "const TIER_TWO_BOOTS" not in APP_JS
    assert "const TIER_THREE_BOOTS" not in APP_JS
    assert "const LEVEL_DERIVED_RANK_CHAMPIONS" not in APP_JS


def test_frontend_has_no_literal_boot_ids_or_rank_policy_names():
    for item_id in ("3006", "3009", "3008", "3158", "3111", "3047", "3020"):
        assert item_id not in APP_JS
    for item_id in ("3172", "3170", "3168", "3171", "3173", "3174", "3175"):
        assert item_id not in APP_JS
    assert '"Elise", "Jayce", "Karma", "Nidalee", "Udyr"' not in APP_JS
