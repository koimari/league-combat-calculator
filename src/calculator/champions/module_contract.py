"""Validated runtime contract for one named champion module.

The registry, public metadata, and audits all consume this object.  Champion
modules remain ordinary Python modules, but registration fails closed unless
the module publishes the complete parser/evidence contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from string import hexdigits
from types import ModuleType
from typing import Any, Callable

REQUIRED_CHAMPION_SLOTS = ("P", "Q", "W", "E", "R")
VALID_COVERAGE = frozenset({"modeled", "no_damage", "out_of_scope"})


class ChampionModuleContractError(ValueError):
    """A registered champion module does not publish a valid contract."""


@dataclass(frozen=True, slots=True)
class ChampionModuleContract:  # pylint: disable=too-many-instance-attributes
    """The single runtime and review view of one registered champion."""

    name: str
    module_name: str
    module: ModuleType
    parse_abilities: Callable[..., dict[str, dict[str, Any]]]
    slots: dict[str, Callable[..., Any]]
    options: tuple[dict[str, Any], ...]
    assumptions: tuple[str, ...]
    sources: tuple[dict[str, Any], ...]
    coverage: dict[str, str]
    review_status: str
    cc_review_status: str | None = None
    packet_spec: dict[str, Any] | None = None
    packet_sha256: str | None = None


def _require_list(module: ModuleType, field: str) -> list[Any]:
    value = getattr(module, field, None)
    if not isinstance(value, list):
        raise ChampionModuleContractError(
            f"{module.__name__} must declare {field} as a list"
        )
    return value


def _validated_cc_review_status(
    module: ModuleType,
    parser: Callable[..., dict[str, dict[str, Any]]],
) -> str | None:
    """Return the explicit module CC review status after contract checks."""
    cc_review_status = getattr(module, "CC_REVIEW_STATUS", None)
    if cc_review_status not in {None, "reviewed_no_cc"}:
        raise ChampionModuleContractError(
            f"{module.__name__} CC_REVIEW_STATUS must be 'reviewed_no_cc' "
            "when declared"
        )
    if getattr(parser, "cc_review_status", None) != cc_review_status:
        raise ChampionModuleContractError(
            f"{module.__name__} CC_REVIEW_STATUS must match its parser contract"
        )
    return cc_review_status


def contract_from_module(
    name: str, module_name: str, module: ModuleType
) -> ChampionModuleContract:
    """Validate *module* and return its immutable registry contract."""

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

    coverage = getattr(module, "MODULE_COVERAGE", None)
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

    review_status = getattr(module, "REVIEW_STATUS", None)
    if review_status != "reviewed_module":
        raise ChampionModuleContractError(
            f"{module.__name__} REVIEW_STATUS must be 'reviewed_module'"
        )

    cc_review_status = _validated_cc_review_status(module, parser)

    packet_spec = getattr(
        module,
        "PACKET_SPEC",
        getattr(parser, "packet_spec", getattr(slots, "packet_spec", None)),
    )
    if packet_spec is not None and not isinstance(packet_spec, dict):
        raise ChampionModuleContractError(
            f"{module.__name__} PACKET_SPEC must be a dict when declared"
        )
    packet_sha256 = getattr(
        module,
        "PACKET_SHA256",
        getattr(parser, "packet_sha256", getattr(slots, "packet_sha256", None)),
    )
    if (packet_spec is None) != (packet_sha256 is None):
        raise ChampionModuleContractError(
            f"{module.__name__} packet declaration and digest must be paired"
        )
    if packet_sha256 is not None and (
        not isinstance(packet_sha256, str)
        or len(packet_sha256) != 64
        or any(character not in hexdigits for character in packet_sha256)
    ):
        raise ChampionModuleContractError(
            f"{module.__name__} PACKET_SHA256 must be a SHA-256 hex digest"
        )

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
        review_status=review_status,
        cc_review_status=cc_review_status,
        packet_spec=packet_spec,
        packet_sha256=packet_sha256,
    )
