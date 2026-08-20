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

# Facts with one home outside the module: the review status is this
# contract's, and the packet spec rides the parser ``build_packet_module``
# returns.  A module restating either is a second home that can disagree
# with the first, so the restatement is refused rather than surveyed.
_RESTATED_FACTS = ("REVIEW_STATUS", "PACKET_SPEC")


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


def _present(carriers: tuple[tuple[str, Any, str], ...]) -> list[tuple[str, Any]]:
    """The carriers that hold something, as ``(label, value)`` rows.

    A packet champion carries its declarations on the artifacts
    ``build_packet_module`` compiled as well as on the module itself, so
    one fact can have three carriers.  A chain of ``getattr`` defaults is
    the wrong way to read them: Python evaluates a default *eagerly*, so a
    carrier that is present but empty wins over a non-empty one further
    down the chain and the declaration is discarded with no error — the
    silent shadowing this contract exists to kill.  So the carriers are
    surveyed instead: an empty carrier declares nothing and shadows
    nothing, and :func:`_agreeing` stops the import when two carriers that
    both declare something disagree, rather than one quietly winning.
    """
    return [
        (label, getattr(carrier, attribute))
        for label, carrier, attribute in carriers
        if getattr(carrier, attribute, None)
    ]


def _agreeing(module: ModuleType, declared: list[tuple[str, Any]], what: str) -> Any:
    """The one value every present carrier holds.

    Raises:
        ChampionModuleContractError: Two carriers disagree.
    """
    first_label, first = declared[0]
    for label, value in declared[1:]:
        if value != first:
            raise ChampionModuleContractError(
                f"{module.__name__} declares conflicting {what}: "
                f"{first_label} and {label} disagree"
            )
    return first


def _declared_cast_dependencies(
    module: ModuleType, parser: Callable[..., Any], slots: dict[str, Any]
) -> tuple[CastDependency, ...]:
    """The one declaration the module, its parser and its slot map agree on.

    Raises:
        ChampionModuleContractError: A carrier holds something other than
            a sequence of ``CastDependency``, or two carriers disagree.
    """
    declared = _present(
        (
            ("module CAST_DEPENDENCIES", module, "CAST_DEPENDENCIES"),
            ("parse_abilities.cast_dependencies", parser, "cast_dependencies"),
            ("SLOTS.cast_dependencies", slots, "cast_dependencies"),
        )
    )
    if not declared:
        return ()
    for label, value in declared:
        if not isinstance(value, (tuple, list)) or any(
            not isinstance(row, CastDependency) for row in value
        ):
            raise ChampionModuleContractError(
                f"{module.__name__} {label} must be a sequence of "
                "CastDependency declarations"
            )
    return tuple(
        _agreeing(
            module,
            [(label, tuple(value)) for label, value in declared],
            "cast dependencies",
        )
    )


def _packet_declaration(
    module: ModuleType, parser: Callable[..., Any], slots: dict[str, Any]
) -> tuple[dict[str, Any] | None, str | None]:
    """The reviewed packet evidence and the digest that pins it.

    ``build_packet_module`` verifies the module's ``PACKET_SHA256`` against
    the packet asset and stamps the accepted spec and digest on the parser
    it returns and on the slot map.  The parser is what runs, so its stamp
    is what the contract publishes; the module's own ``PACKET_SHA256`` is
    surveyed against it, never chained ahead of it.  A module that pins a
    digest its running parser does not carry has rebound
    ``parse_abilities`` away from the compiled one — the pin then guards
    nothing, so registration stops there (rule 7's fail-closed guarantee
    rests on this pin).

    Raises:
        ChampionModuleContractError: The carriers disagree, the pin is not
            a SHA-256 hex digest, the spec is not a dict, the two are not
            paired, or the module pins a digest its parser does not carry.
    """
    spec_rows = _present(
        (
            ("parse_abilities.packet_spec", parser, "packet_spec"),
            ("SLOTS.packet_spec", slots, "packet_spec"),
        )
    )
    digest_rows = _present(
        (
            ("module PACKET_SHA256", module, "PACKET_SHA256"),
            ("parse_abilities.packet_sha256", parser, "packet_sha256"),
            ("SLOTS.packet_sha256", slots, "packet_sha256"),
        )
    )
    packet_spec = (
        _agreeing(module, spec_rows, "packet declarations") if spec_rows else None
    )
    packet_sha256 = (
        _agreeing(module, digest_rows, "packet digests") if digest_rows else None
    )
    if (spec_rows or digest_rows) and getattr(parser, "packet_sha256", None) is None:
        raise ChampionModuleContractError(
            f"{module.__name__} pins a packet digest its parse_abilities does "
            "not carry: the parser was not the one build_packet_module "
            "compiled, so the pin guards nothing"
        )
    if packet_spec is not None and not isinstance(packet_spec, dict):
        raise ChampionModuleContractError(
            f"{module.__name__} packet spec must be a dict when stamped"
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
    return packet_spec, packet_sha256


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

    The engine applies the declaration through the ``cc_kinds`` argument
    of ``build_parser`` — or of ``build_packet_module``, which hands it on
    — and stamps it on the parser it returns.  That is a second carrier of
    one fact, so — exactly as with ``CAST_DEPENDENCIES`` — the two are
    surveyed rather than chained: a module that declares one thing and
    wires another stops the import instead of quietly running the wired
    one.  The error names the call the module actually compiles through,
    since a packet module must never call ``build_parser`` itself.

    Raises:
        ChampionModuleContractError: The declaration is malformed, names a
            slot the module does not emit, uses an unknown kind, or
            disagrees with what the module wired into its parser.
    """
    wiring = (
        "build_packet_module"
        if getattr(parser, "packet_sha256", None)
        else "build_parser"
    )
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
            f"{wiring}(..., cc_kinds=MODULE_CC) — an unwired declaration "
            "reviews nothing"
        )
    if wired is not None and dict(wired) != dict(declared):
        raise ChampionModuleContractError(
            f"{module.__name__} declares MODULE_CC {dict(declared)} but wired "
            f"{dict(wired)} into {wiring} — one declaration, one wiring"
        )
    return dict(declared)


def _refuse_restatements(module: ModuleType) -> None:
    """Stop a module that restates a fact whose home is elsewhere.

    Raises:
        ChampionModuleContractError: The module declares ``REVIEW_STATUS``
            or ``PACKET_SPEC``.
    """
    restated = [name for name in _RESTATED_FACTS if hasattr(module, name)]
    if restated:
        raise ChampionModuleContractError(
            f"{module.__name__} declares {restated}: the review status is the "
            f"contract's ({REVIEW_STATUS!r}) and the packet spec rides the "
            "parser build_packet_module returns, so a module restates neither"
        )


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
            "declare it only when an emitted slot is no_damage or partial"
        )

    packet_spec, packet_sha256 = _packet_declaration(module, parser, slots)
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
