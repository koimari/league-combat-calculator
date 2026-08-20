"""Validated runtime contract for one named champion module.

The registry, public metadata, and audits all consume this object.  Champion
modules remain ordinary Python modules, but registration fails closed unless
the module publishes the complete parser/evidence contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from string import hexdigits
from types import ModuleType
from typing import Any, Callable

from ..ability_spec import CC_KIND_VOCABULARY
from ..cast_dependency import (
    CastDependency,
    validate_cast_dependencies,
    validate_cast_order_declaration,
)

REQUIRED_CHAMPION_SLOTS = ("P", "Q", "W", "E", "R")
VALID_COVERAGE = frozenset({"modeled", "no_damage", "out_of_scope"})
REVIEW_STATUS = "reviewed_module"


def default_coverage(slots: dict[str, Any]) -> dict[str, str]:
    """The five-slot coverage a module's ``SLOTS`` map implies.

    A slot the module emits is ``modeled``; one it does not is
    ``out_of_scope``.  A module whose emitted slots include a declared
    zero-damage or partial slot states that itself with ``MODULE_COVERAGE``.
    """
    return {
        slot: ("modeled" if slot in slots else "out_of_scope")
        for slot in REQUIRED_CHAMPION_SLOTS
    }


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
    review_status: str = REVIEW_STATUS
    packet_spec: dict[str, Any] | None = None
    packet_sha256: str | None = None
    cast_dependencies: tuple[CastDependency, ...] = ()
    cc_kinds: dict[str, str] = field(default_factory=dict)


def _declared_cast_dependencies(
    module: ModuleType, parser: Callable[..., Any], slots: dict[str, Any]
) -> tuple[CastDependency, ...]:
    """The one declaration the module, its parser and its slot map agree on.

    A packet champion may carry its declaration on the artifacts
    ``build_packet_module`` compiled instead of restating it beside them,
    so three carriers can hold it.  ``PACKET_SPEC`` reads its three places
    as a chain of ``getattr`` defaults, and Python evaluates a default
    *eagerly*: a carrier that is present but empty wins over a non-empty
    one further down the chain and the declaration is discarded with no
    error.  That is precisely the silent failure this campaign exists to
    kill, so the lookup here is a survey rather than a chain — an empty
    carrier declares nothing and therefore shadows nothing, and two
    carriers that both declare something and disagree stop the import
    instead of one of them quietly winning.

    Raises:
        ChampionModuleContractError: A carrier holds something other than
            a sequence of ``CastDependency``, or two carriers disagree.
    """
    carriers = (
        ("module CAST_DEPENDENCIES", module, "CAST_DEPENDENCIES"),
        ("parse_abilities.cast_dependencies", parser, "cast_dependencies"),
        ("SLOTS.cast_dependencies", slots, "cast_dependencies"),
    )
    declared = [
        (label, getattr(carrier, attribute))
        for label, carrier, attribute in carriers
        if getattr(carrier, attribute, None)
    ]
    if not declared:
        return ()

    rows: list[tuple[str, tuple[CastDependency, ...]]] = []
    for label, value in declared:
        if not isinstance(value, (tuple, list)) or any(
            not isinstance(row, CastDependency) for row in value
        ):
            raise ChampionModuleContractError(
                f"{module.__name__} {label} must be a sequence of "
                "CastDependency declarations"
            )
        rows.append((label, tuple(value)))

    first_label, first = rows[0]
    for label, other in rows[1:]:
        if other != first:
            raise ChampionModuleContractError(
                f"{module.__name__} declares conflicting cast dependencies: "
                f"{first_label} and {label} disagree"
            )
    return first


def _cast_dependencies(
    module: ModuleType, parser: Callable[..., Any], slots: dict[str, Any]
) -> tuple[CastDependency, ...]:
    """The module's declared ordering prerequisites, validated at import.

    Both validators run against *this module's own* slot surface, never a
    global slot list: a synthetic key like Syndra's ``Q2`` is legal
    because the module declares it.  ``CAST_ORDER`` is validated by the
    same gate (P5-d) rather than by the bare ``getattr`` that reads it at
    runtime, so a module declaring an order contradicting a dependency it
    also declares fails at import instead of surprising later.

    Every check is gated on the module declaring something (D-85): a
    champion that declares no dependency reaches no new failure mode.

    Raises:
        ChampionModuleContractError: The declaration is malformed or the
            carriers disagree.
        CastDependencyError: One of the typed import-time failures.
    """
    dependencies = _declared_cast_dependencies(module, parser, slots)
    if not dependencies:
        return ()
    slot_surface = set(slots)
    validate_cast_dependencies(
        dependencies, slot_surface=slot_surface, module=module.__name__
    )
    cast_order = getattr(module, "CAST_ORDER", None)
    if cast_order:
        validate_cast_order_declaration(
            cast_order,
            dependencies,
            slot_surface=slot_surface,
            module=module.__name__,
        )
    return dependencies


def _module_cc(
    module: ModuleType, parser: Callable[..., Any], slots: dict[str, Any]
) -> dict[str, str]:
    """The module's reviewed crowd control, one entry per slot it emits.

    ``MODULE_CC`` is the single declaration site for a kit's crowd-control
    facts (D-6): ``{slot: kind}`` with kinds from
    :data:`ability_spec.CC_KIND_VOCABULARY`, where ``"none"`` is a reviewed
    *absence* of control and an **absent slot is unreviewed** — the two
    are different answers and only the first one clears the Fimbulwinter /
    Imperial Mandate control token.

    A slot the module does not emit is a declaration with no referent, and
    a kind outside the vocabulary is a typo that would author a no-op stun,
    so both stop registration here rather than at some later reader.

    The engine applies the declaration through ``build_parser``'s
    ``cc_kinds`` argument, which stamps it on the parser it returns.  That
    is a second carrier of one fact, so — exactly as with
    ``CAST_DEPENDENCIES`` — the two are surveyed rather than chained: a
    module that declares one thing and wires another stops the import
    instead of quietly running the wired one.

    Raises:
        ChampionModuleContractError: The declaration is malformed, names a
            slot the module does not emit, uses an unknown kind, or
            disagrees with what the module wired into its parser.
    """
    declared = getattr(module, "MODULE_CC", None)
    if declared is None:
        declared = {}
    if not isinstance(declared, dict):
        raise ChampionModuleContractError(
            f"{module.__name__} MODULE_CC must be a dict of slot -> cc kind"
        )
    unknown_slots = sorted(set(declared) - set(slots))
    if unknown_slots:
        raise ChampionModuleContractError(
            f"{module.__name__} MODULE_CC declares slot(s) {unknown_slots} "
            f"the module does not emit (its slots are {sorted(slots)})"
        )
    invalid = sorted(
        f"{slot}={kind!r}"
        for slot, kind in declared.items()
        if not isinstance(kind, str) or kind not in CC_KIND_VOCABULARY
    )
    if invalid:
        raise ChampionModuleContractError(
            f"{module.__name__} MODULE_CC has invalid cc kind(s) {invalid} "
            "(known kinds are defined by ability_spec.CC_KIND_VOCABULARY)"
        )
    wired = getattr(parser, "cc_kinds", None)
    if declared and wired is None:
        raise ChampionModuleContractError(
            f"{module.__name__} declares MODULE_CC but never wired it into "
            "build_parser(..., cc_kinds=MODULE_CC) — an unwired declaration "
            "reviews nothing"
        )
    if wired is not None and dict(wired) != dict(declared):
        raise ChampionModuleContractError(
            f"{module.__name__} declares MODULE_CC {dict(declared)} but wired "
            f"{dict(wired)} into build_parser — one declaration, one wiring"
        )
    return dict(declared)


def _require_list(module: ModuleType, field_name: str) -> list[Any]:
    value = getattr(module, field_name, None)
    if not isinstance(value, list):
        raise ChampionModuleContractError(
            f"{module.__name__} must declare {field_name} as a list"
        )
    return value


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
    if coverage is None:
        coverage = default_coverage(slots)
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

    cast_dependencies = _cast_dependencies(module, parser, slots)
    cc_kinds = _module_cc(module, parser, slots)

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
        packet_spec=packet_spec,
        packet_sha256=packet_sha256,
        cast_dependencies=cast_dependencies,
        cc_kinds=cc_kinds,
    )
