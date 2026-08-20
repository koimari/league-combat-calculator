"""Champion modules are the single runtime and review authority (issue #161)."""

import importlib
from pathlib import Path
from types import ModuleType

import pytest

from src.calculator.ability_spec import CC_KIND_VOCABULARY
from src.calculator.champions import (
    _CUSTOM_CHAMPION_MODULES,
    get_champion_module_contract,
    parse_abilities,
    parse_synthetic_champion_abilities,
)
from src.calculator.champions.module_contract import (
    ChampionModuleContractError,
    contract_from_module,
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
    assert set(contract.slots) == set(jayce.SLOTS) == {"Q", "W", "E", "R"}
    assert contract.sources == tuple(jayce.SOURCES)
    assert (
        contract.coverage
        == jayce.MODULE_COVERAGE
        == {
            "P": "out_of_scope",
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


class TestModuleCcDeclaration:
    """``MODULE_CC`` is the one place a kit's crowd control is stated.

    ``{slot: kind}``, kinds from ``CC_KIND_VOCABULARY``, and an **absent**
    slot means unreviewed — which is a different answer from ``"none"``,
    the reviewed absence of control that clears the Fimbulwinter/Imperial
    Mandate token.  Everything a module says here has to be about a slot
    it emits and a kind the engine knows, or registration stops.
    """

    @staticmethod
    def _wired_parser(cc_kinds=None):
        """A stand-in for what ``build_parser`` returns, wiring included."""

        def parse_abilities(*args, **kwargs):
            return {}

        if cc_kinds is not None:
            parse_abilities.cc_kinds = cc_kinds
        return parse_abilities

    @staticmethod
    def _module(**overrides):
        """A minimal module object that satisfies the rest of the contract."""
        module = ModuleType("fake_champion")
        module.parse_abilities = lambda *args, **kwargs: {}
        module.SLOTS = {"Q": lambda ctx: None, "W": lambda ctx: None}
        module.OPTIONS = []
        module.ASSUMPTIONS = ["one"]
        module.SOURCES = [{"label": "cache"}]
        module.MODULE_COVERAGE = dict.fromkeys("PQWER", "out_of_scope")
        module.REVIEW_STATUS = "reviewed_module"
        for key, value in overrides.items():
            setattr(module, key, value)
        return module

    def _contract(self, **overrides):
        return contract_from_module("Fake", "fake_champion", self._module(**overrides))

    def test_a_module_declaring_nothing_reviews_nothing(self):
        assert self._contract().cc_kinds == {}

    def test_a_declaration_survives_onto_the_contract(self):
        declared = {"Q": "stun", "W": "none"}
        contract = self._contract(
            MODULE_CC=declared, parse_abilities=self._wired_parser(declared)
        )
        assert contract.cc_kinds == declared

    def test_a_slot_the_module_does_not_emit_is_refused(self):
        with pytest.raises(ChampionModuleContractError, match=r"\['E'\]"):
            self._contract(MODULE_CC={"E": "stun"})

    def test_an_unknown_kind_is_refused(self):
        with pytest.raises(ChampionModuleContractError, match="stunn"):
            self._contract(MODULE_CC={"Q": "stunn"})

    def test_a_non_mapping_declaration_is_refused(self):
        with pytest.raises(ChampionModuleContractError, match="must be a dict"):
            self._contract(MODULE_CC=["Q"])

    def test_a_declaration_nobody_wired_is_refused(self):
        """The silent no-op this whole shape exists to prevent: a module
        that states its kit's control and never hands it to the engine
        would review nothing while reading as reviewed."""
        with pytest.raises(ChampionModuleContractError, match="never wired"):
            self._contract(MODULE_CC={"Q": "none"})

    def test_a_declaration_disagreeing_with_its_wiring_is_refused(self):
        """Two carriers of one fact must not silently diverge — the same
        rule ``CAST_DEPENDENCIES`` obeys."""
        with pytest.raises(ChampionModuleContractError, match="one declaration"):
            self._contract(
                MODULE_CC={"Q": "stun"},
                parse_abilities=self._wired_parser({"Q": "none"}),
            )

    def test_the_pilots_declare_what_they_wired(self):
        """The wave's four migrated modules, read off the live registry.

        A pilot's declaration grows as the rest of its kit is reviewed, so
        what is pinned here is the fact each migration established — the
        kind, on the slot the wave read it off — not the size of the dict
        that has since grown around it.  Corki's P dropped out: Hextech
        Munitions delivers on the auto stream, so its row authors no
        ability event and the engine refuses a declaration there.
        """
        assert get_champion_module_contract("Corki").cc_kinds == {
            slot: "none" for slot in ("Q", "W", "E", "R")
        }
        for name, slot, kind in (
            ("Syndra", "E", "stun"),
            ("Ahri", "E", "immobilize"),
            ("Pantheon", "W", "stun"),
        ):
            assert get_champion_module_contract(name).cc_kinds[slot] == kind

    def test_a_packet_module_wires_its_declaration_the_same_way(self):
        """A packet champion reviews its control in ``MODULE_CC`` too: the
        packet is the evidence, the declaration is what the module says
        about it, and both reach the same one application in the engine."""
        parser, slots, *_ = build_packet_module(
            "Singed",
            packet_spec_sha256(get_champion_module_contract("Singed").packet_spec),
            cc_kinds={"Q": "none"},
        )
        assert "Q" in slots
        assert parser.cc_kinds == {"Q": "none"}

    def test_every_declared_kind_is_in_the_vocabulary(self):
        """Roster-wide: no module may reach the registry with a typo."""
        for name in _CUSTOM_CHAMPION_MODULES:
            contract = get_champion_module_contract(name)
            assert set(contract.cc_kinds) <= set(contract.slots), name
            assert set(contract.cc_kinds.values()) <= CC_KIND_VOCABULARY, name


def test_add_champion_skills_describe_the_same_single_module_flow():
    agents = Path(".agents/skills/add-champion/skill.md").read_text(encoding="utf-8")
    claude = Path(".claude/skills/add-champion/skill.md").read_text(encoding="utf-8")

    assert agents == claude
    assert "Two implementation lanes" not in agents
    assert "ChampionModuleContract" in agents
    assert "reviewed_batch_" not in agents
