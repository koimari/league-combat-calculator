"""Champion modules are the single runtime and review authority (issue #161)."""

import importlib
from pathlib import Path

import pytest

from src.calculator.champions import (
    _CUSTOM_CHAMPION_MODULES,
    get_champion_module_contract,
    parse_abilities,
    parse_synthetic_champion_abilities,
)
from src.calculator.champions.packet_module import (
    build_packet_module,
    packet_spec_sha256,
)

REQUIRED_SLOTS = {"P", "Q", "W", "E", "R"}


def test_every_registered_champion_satisfies_the_module_contract():
    """Every registry entry publishes one complete, internally consistent view."""
    for name, module_name in _CUSTOM_CHAMPION_MODULES.items():
        module = importlib.import_module(f"src.calculator.champions.{module_name}")
        contract = get_champion_module_contract(name)

        assert contract.name == name
        assert contract.module_name == module_name
        assert contract.parse_abilities is module.parse_abilities
        assert contract.slots is module.SLOTS
        assert contract.options == tuple(module.OPTIONS)
        assert contract.assumptions == tuple(module.ASSUMPTIONS)
        assert contract.sources == tuple(module.SOURCES)
        assert contract.coverage == module.MODULE_COVERAGE
        assert set(contract.coverage) == REQUIRED_SLOTS
        assert contract.review_status == module.REVIEW_STATUS == "reviewed_module"
        if contract.packet_spec is not None:
            assert contract.packet_sha256 == packet_spec_sha256(contract.packet_spec)


def test_jayce_runtime_and_published_review_metadata_share_one_module():
    """Jayce must not borrow status or sources from reviewed-packets.json."""
    from src.calculator.champions import jayce

    contract = get_champion_module_contract("Jayce")

    assert contract.parse_abilities is jayce.parse_abilities
    assert set(contract.slots) == set(jayce.SLOTS) == {"P", "Q", "W", "E", "R"}
    assert contract.sources == tuple(jayce.SOURCES)
    assert (
        contract.coverage
        == jayce.MODULE_COVERAGE
        == {
            "P": "no_damage",
            "Q": "modeled",
            "W": "modeled",
            "E": "modeled",
            "R": "modeled",
        }
    )
    assert contract.review_status == jayce.REVIEW_STATUS == "reviewed_module"


def test_synthetic_parser_is_explicit_and_dispatcher_fails_closed():
    fixture = {
        "name": "Synthetic Fixture",
        "abilities": {slot: [] for slot in REQUIRED_SLOTS},
    }

    with pytest.raises(KeyError, match="no registered champion module"):
        parse_abilities("Synthetic Fixture", fixture, 1, 0.0)

    assert parse_synthetic_champion_abilities(fixture, 1, 0.0) == {}


def test_review_campaign_batch_modules_and_imports_are_gone():
    champion_root = Path("src/calculator/champions")

    assert list(champion_root.glob("reviewed_batch_*.py")) == []
    for path in champion_root.glob("*.py"):
        assert "reviewed_batch_" not in path.read_text(encoding="utf-8"), path


def test_packet_compiler_contains_no_champion_name_override_registries():
    source = Path("src/calculator/champions/packet_module.py").read_text(
        encoding="utf-8"
    )

    assert "_PACKET_TICK_FIXES" not in source
    assert "_PACKET_ASSUMPTION_OVERRIDES" not in source
    assert "_SINGLE_HIT_EVENT_PACKETS" not in source


def test_packet_compiler_fails_closed_when_named_module_digest_drifts():
    with pytest.raises(RuntimeError, match="packet evidence drifted"):
        build_packet_module("Singed", "0" * 64)


def test_add_champion_skills_describe_the_same_single_module_flow():
    agents = Path(".agents/skills/add-champion/skill.md").read_text(encoding="utf-8")
    claude = Path(".claude/skills/add-champion/skill.md").read_text(encoding="utf-8")

    assert agents == claude
    assert "Two implementation lanes" not in agents
    assert "ChampionModuleContract" in agents
    assert "reviewed_batch_" not in agents
