"""Validated runtime contract for one named champion module.

The registry, public metadata, and audits all consume this object.  Champion
modules remain ordinary Python modules, but registration fails closed unless
the module publishes the complete parser/evidence contract.
"""

from __future__ import annotations

from types import ModuleType

from .contract_vocabulary import (
    REQUIRED_CHAMPION_SLOTS,
    VALID_COVERAGE,
    ChampionModuleContract,
    ChampionModuleContractError,
    DeclarationSites,
    default_coverage,
)
from .module_survey import (
    _cast_dependencies,
    _coverage_channels,
    _module_cc,
    _packet_declaration,
    _refuse_restatements,
    _require_list,
    _stat_conversion,
    _ultimate_recasts,
)


def contract_from_module(
    name: str, module_name: str, module: ModuleType
) -> ChampionModuleContract:
    """Validate *module* and return its immutable registry contract."""

    _refuse_restatements(module)
    parser = getattr(module, "parse_abilities", None)
    if not callable(parser):
        raise ChampionModuleContractError(
            f"{module.__name__} must declare callable parse_abilities"
        )

    slots = getattr(module, "SLOTS", None)
    if not isinstance(slots, dict) or not slots:
        raise ChampionModuleContractError(
            f"{module.__name__} must declare a non-empty SLOTS dict"
        )
    if any(not callable(slot_parser) for slot_parser in slots.values()):
        raise ChampionModuleContractError(
            f"{module.__name__} SLOTS values must all be callable"
        )

    options = _require_list(module, "OPTIONS")
    assumptions = _require_list(module, "ASSUMPTIONS")
    sources = _require_list(module, "SOURCES")
    if any(not isinstance(row, dict) for row in options):
        raise ChampionModuleContractError(
            f"{module.__name__} OPTIONS rows must be dictionaries"
        )
    if any(not isinstance(row, str) or not row.strip() for row in assumptions):
        raise ChampionModuleContractError(
            f"{module.__name__} ASSUMPTIONS rows must be non-empty strings"
        )
    if not sources or any(not isinstance(row, dict) or not row for row in sources):
        raise ChampionModuleContractError(
            f"{module.__name__} SOURCES must contain source dictionaries"
        )

    derived_coverage = default_coverage(slots)
    coverage = getattr(module, "MODULE_COVERAGE", None)
    if coverage is None:
        coverage = derived_coverage
    if not isinstance(coverage, dict) or set(coverage) != set(REQUIRED_CHAMPION_SLOTS):
        raise ChampionModuleContractError(
            f"{module.__name__} MODULE_COVERAGE must declare P/Q/W/E/R"
        )
    invalid_coverage = set(coverage.values()) - VALID_COVERAGE
    if invalid_coverage:
        raise ChampionModuleContractError(
            f"{module.__name__} MODULE_COVERAGE has invalid values: "
            f"{sorted(invalid_coverage)}"
        )
    if coverage is not derived_coverage and coverage == derived_coverage:
        raise ChampionModuleContractError(
            f"{module.__name__} MODULE_COVERAGE restates what its SLOTS derive; "
            "declare it only when an emitted slot is no_damage or partial, or "
            "an unemitted one is priced through a COVERAGE_CHANNELS channel"
        )

    coverage_channels = _coverage_channels(module, coverage, slots)
    sites = DeclarationSites(module, parser, slots)
    packet_spec, packet_sha256 = _packet_declaration(sites)
    cast_dependencies = _cast_dependencies(sites)
    cc_kinds = _module_cc(sites)
    stat_conversion = _stat_conversion(module)

    return ChampionModuleContract(
        name=name,
        module_name=module_name,
        module=module,
        parse_abilities=parser,
        slots=slots,
        options=tuple(options),
        assumptions=tuple(assumptions),
        sources=tuple(sources),
        coverage=dict(coverage),
        coverage_channels=coverage_channels,
        packet_spec=packet_spec,
        packet_sha256=packet_sha256,
        cast_dependencies=cast_dependencies,
        cc_kinds=cc_kinds,
        ultimate_recasts=_ultimate_recasts(module, slots),
        stat_conversion=stat_conversion,
    )
