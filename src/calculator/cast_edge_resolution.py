"""Declared edges merged over inferred ones, and the topological order they admit."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .cast_dependency import (
    CastDependency,
    ConflictingInferenceError,
    MissingLatentReasonError,
    SuppressedInference,
    active_dependencies,
)
from .cast_edge_inference import detect_setup_consume_edges
from .cast_edge_markers import _Edge
from .champions import get_champion_cast_dependencies


@dataclass(frozen=True)
class DependencyReceipt:
    """What the merge did, for ``scripts/cast_dependency_audit.py``.

    Six ledgers of display rows, each opening with the pair it is about;
    the audit joins its declaration ledgers on that prefix.

    Attributes:
        active: Declarations both of whose endpoints are live in this
            parse — the ones that constrained the order.
        inactive: Declarations naming a slot this parse does not have
            (Syndra's Q2 below 40 splinters), with the absent endpoint
            named.  Not a failure: they simply constrain nothing.
        suppressed: Inferred edges a declaration's nested suppression
            dropped, with the suppression's own reason.
        latent: Suppressions that matched no inferred edge, with the
            ``latent_reason`` that says why the opposed inference is
            absent from this tree.
        confirmed_by_inference: Declarations the detector independently
            derived — the two surfaces agreed.
        conflicts: Oppositions between a declaration and an inference,
            each naming the suppression that covered it.  An *uncovered*
            opposition never reaches a receipt: it raises (D-82).

    Every ledger is empty for a champion that declares nothing.
    """

    active: tuple[str, ...] = ()
    inactive: tuple[str, ...] = ()
    suppressed: tuple[str, ...] = ()
    latent: tuple[str, ...] = ()
    confirmed_by_inference: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()


def _declaration_sentence(dep: CastDependency) -> str:
    """The declaration as one sourced sentence, for edges and receipts."""
    return (
        f"{dep.slot} requires {dep.requires} (declared {dep.kind}): "
        f"{dep.reason} [source: {dep.source}]"
    )


def _matching_suppression(
    dep: CastDependency, edge: _Edge
) -> SuppressedInference | None:
    """The nested suppression covering *edge*, or ``None``.

    Scope is structural (D-81): a suppression is its parent's exact
    reverse pair, so only the inferred *kind* is left to match.
    """
    for suppression in dep.suppresses:
        if suppression.triple == (
            edge.setup,
            edge.consume,
            edge.kind,
        ):
            return suppression
    return None


def merge_declared_edges(
    champion_name: str,
    inferred: Sequence[_Edge],
    declarations: Sequence[CastDependency],
    live_slots: Collection[str],
) -> tuple[list[_Edge], DependencyReceipt]:
    """Fold declarations over inferred edges under the precedence table.

    Args:
        champion_name: For the failure messages and receipt rows.
        inferred: What :func:`detect_setup_consume_edges` derived.
        declarations: The module's validated ``CAST_DEPENDENCIES``.
        live_slots: The slots this parse actually has, which decides
            which declarations are active.

    Returns:
        ``(edges, receipt)`` — the declared edges first, then every
        inferred edge that survived, each carrying its ``origin``.

    Raises:
        ConflictingInferenceError: An inferred edge opposes an active
            declaration and no suppression covers it.  "Declared always
            wins" would settle a real modelling disagreement silently in
            the module's favour (D-82).
        MissingLatentReasonError: A suppression matched nothing and says
            nothing about why — a claim about an inference nobody can
            see.
    """
    if not declarations:
        return list(inferred), DependencyReceipt()

    active = active_dependencies(declarations, live_slots)
    active_pairs = {(dep.slot, dep.requires) for dep in active}
    inactive_rows = [
        f"{dep.slot} requires {dep.requires} ({dep.kind}) is inactive — "
        f"{_absent_endpoints(dep, live_slots)} not in this parse"
        for dep in declarations
        if (dep.slot, dep.requires) not in active_pairs
    ]

    surviving = list(inferred)
    declared: list[_Edge] = []
    active_rows: list[str] = []
    suppressed_rows: list[str] = []
    latent_rows: list[str] = []
    confirmed_rows: list[str] = []
    conflict_rows: list[str] = []

    for dep in active:
        forward = (dep.requires, dep.slot)
        reverse = (dep.slot, dep.requires)
        confirmations = [e for e in surviving if (e.setup, e.consume) == forward]
        oppositions = [e for e in surviving if (e.setup, e.consume) == reverse]
        matched: set[tuple[str, str, str]] = set()

        for edge in oppositions:
            suppression = _matching_suppression(dep, edge)
            if suppression is None:
                raise ConflictingInferenceError(
                    f"{champion_name}: the detector infers {edge.setup} -> "
                    f"{edge.consume} ({edge.kind}: {edge.cite}), which opposes "
                    f"the declaration {_declaration_sentence(dep)}. Nothing "
                    "suppresses it, so the two surfaces disagree about the "
                    "mechanic: either the module's declaration is wrong, or "
                    "it must nest a SuppressedInference naming "
                    f"{edge.kind!r} and saying why the inference reads the "
                    "mechanic backwards."
                )
            matched.add(suppression.triple)
            suppressed_rows.append(
                f"{edge.setup} -> {edge.consume} ({edge.kind}) suppressed by "
                f"{dep.slot} requires {dep.requires}: {suppression.reason}"
            )
            conflict_rows.append(
                f"{edge.setup} -> {edge.consume} ({edge.kind}) opposes "
                f"{dep.slot} requires {dep.requires} — covered by the "
                "declaration's own suppression"
            )

        for suppression in dep.suppresses:
            triple = suppression.triple
            if triple in matched:
                continue
            if suppression.latent_reason is None:
                raise MissingLatentReasonError(
                    f"{champion_name}: the suppression of {suppression.setup} -> "
                    f"{suppression.consume} ({suppression.kind}) matched no "
                    "inferred edge in this parse and declares no "
                    "latent_reason. Either the inference it opposes is gone "
                    "and the suppression should say so, or the suppression "
                    "names the wrong kind."
                )
            latent_rows.append(
                f"{suppression.setup} -> {suppression.consume} "
                f"({suppression.kind}) is latent: {suppression.latent_reason}"
            )

        confirmed_rows.extend(
            f"{dep.slot} requires {dep.requires} is confirmed by the "
            f"inferred {edge.setup} -> {edge.consume} ({edge.kind})"
            for edge in confirmations
        )

        dropped = {id(edge) for edge in oppositions + confirmations}
        surviving = [edge for edge in surviving if id(edge) not in dropped]
        declared.append(
            _Edge(
                dep.requires,
                dep.slot,
                dep.kind,
                _declaration_sentence(dep),
                origin="declared",
            )
        )
        active_rows.append(_declaration_sentence(dep))

    return declared + surviving, DependencyReceipt(
        active=tuple(active_rows),
        inactive=tuple(inactive_rows),
        suppressed=tuple(suppressed_rows),
        latent=tuple(latent_rows),
        confirmed_by_inference=tuple(confirmed_rows),
        conflicts=tuple(conflict_rows),
    )


def _absent_endpoints(dep: CastDependency, live_slots: Collection[str]) -> str:
    """Which endpoint of an inactive declaration this parse lacks."""
    absent = [slot for slot in (dep.slot, dep.requires) if slot not in live_slots]
    return " and ".join(absent) if absent else "no endpoint"


def resolved_edges(
    champion_name: str,
    ability_damages: Mapping[str, Any],
    champion_data: Mapping[str, Any],
    option_keys: Mapping[str, list[str]],
    *,
    declarations: Sequence[CastDependency] | None = None,
) -> tuple[tuple[_Edge, ...], DependencyReceipt]:
    """The one public detect→merge surface.

    Production and the test suites both enter here, so the ordering constraints a
    champion actually runs under cannot drift from the ones a test inspects.

    *option_keys* is ``slot -> option keys`` from the module's rotation
    declarations, as :func:`detect_setup_consume_edges` reads it, and
    *declarations* is the module's ``CAST_DEPENDENCIES``, looked up from the
    validated contract when omitted.  Returns every edge with its ``origin``,
    and a receipt of what the merge did.
    """
    if declarations is None:

        declarations = get_champion_cast_dependencies(champion_name)
    inferred = detect_setup_consume_edges(
        champion_name, ability_damages, champion_data, option_keys
    )
    live_slots = {
        slot for slot in ability_damages if isinstance(ability_damages[slot], Mapping)
    }
    merged, receipt = merge_declared_edges(
        champion_name, inferred, declarations, live_slots
    )
    return tuple(merged), receipt


def _kahn_order(
    slots: list[str], edges: Iterable[_Edge], tie_key: Any
) -> list[str] | None:
    successors: dict[str, list[str]] = {s: [] for s in slots}
    indegree = dict.fromkeys(slots, 0)
    for e in edges:
        if e.setup in successors and e.consume in successors:
            successors[e.setup].append(e.consume)
            indegree[e.consume] += 1
    ready = sorted([s for s in slots if indegree[s] == 0], key=tie_key)
    order: list[str] = []
    while ready:
        s = ready.pop(0)
        order.append(s)
        for nxt in successors[s]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                ready.append(nxt)
                ready.sort(key=tie_key)
    return order if len(order) == len(slots) else None
