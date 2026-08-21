"""Module-declared cast-ordering prerequisites — the rotation lane's vocabulary leaf.

Two surfaces make ordering claims and they must never be confused. A
champion module *declares* what its own kit requires ("Scatter the Weak
stuns only enemies a scattered Dark Sphere passes through", so E requires
Q); the rotation resolver separately *infers* ordering from the markers it
parses out of the wiki text. So there are two closed vocabularies, asserted
disjoint: ``DEPENDENCY_KINDS`` is what a module may assert about its own
kit, ``INFERRED_EDGE_KINDS`` is what the detector may conclude, and every
merged edge carries an ``origin`` naming which surface produced it.

This module is a leaf: standard library only, nothing from
``src.calculator``. That is what lets ``rotation_resolver``,
``champions/module_contract``, ``champions/packet_module``,
``champions/__init__`` and ``pipeline`` share one vocabulary without the
champion package owning the generic resolver's taxonomy. It is the
rotation-side sibling of ``ability_spec.py``.

Recast parentage has exactly one authority: ``recast_of`` on the parsed
ability entry. There is deliberately **no** parent-slot table here: a hand
table restating a fact the parse already carries is a second authority.
``orderable_slots`` reads the stamp, and a synthetic slot carrying none
*raises* rather than being linked by name.
"""

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

BASE_CAST_SLOTS: tuple[str, ...] = ("P", "Q", "W", "E", "R")

# What a champion module may assert about its own kit. Four kinds: three
# say "this slot's effect does not exist unless that slot ran first"
# (a stun that needs a sphere, damage that needs a mark, a cast that needs
# a resource), and ``recast_of`` says the second slot is the first's
# recast. They name mechanics, never scheduling preferences — a DPS
# tie-break is not a dependency and has no spelling here.
DEPENDENCY_KINDS: frozenset[str] = frozenset(
    {
        "cc_enabler",
        "damage_enabler",
        "resource_enabler",
        "recast_of",
    }
)

# The resolver's own taxonomy, moved verbatim from the closed set
# ``detect_setup_consume_edges`` can emit. A module may not spell one of
# these: an inferred kind classifies a parsed marker, a declared kind is a
# module's assertion, and one vocabulary would blur which surface owns the
# claim.
INFERRED_EDGE_KINDS: frozenset[str] = frozenset(
    {
        "dot_consume",
        "stack_consume",
        "mark_consume",
        "mark_applier",
        "detonate",
        "enhanced_consume",
        "execute",
        "recast",
        "shred",
        "buff",
        "cc_setup",
        "amp",
    }
)


class CastDependencyError(ValueError):
    """Base for every declared-cast-dependency failure.

    A ``ValueError`` so the request boundary keeps mapping a malformed
    user order to a 4xx without a new handler.
    """


# ── import-time: a module's declaration is malformed ──────────────────────


class UnknownSlotError(CastDependencyError):
    """A declaration names a slot this module's own slot map does not have.

    Also raised for a synthetic slot that is neither a base cast slot nor
    stamped ``recast_of``: parentage is never guessed from a name.
    """


class SelfDependencyError(CastDependencyError):
    """A slot declares that it requires itself."""


class DuplicateDependencyError(CastDependencyError):
    """A declaration repeats itself.

    The same ordered pair declared twice, the same suppression triple
    nested twice, or a slot repeated inside ``CAST_ORDER``.
    """


class UnknownDependencyKindError(CastDependencyError):
    """A declared ``kind`` is outside ``DEPENDENCY_KINDS``."""


class UnsourcedDependencyError(CastDependencyError):
    """A declaration carries no written justification.

    An empty ``reason``, an empty ``source``, or a ``source`` that is not
    ``"<wiki url>@<revision_id>"``. A free-text string checked only for
    non-emptiness would accept four plausible sentences, so the shape is
    checked here.  The shape is all
    a stdlib leaf can check: resolving the revision itself against the
    committed wiki audit is
    ``scripts/cast_dependency_audit.py``'s, gated by
    ``tests/test_cast_dependency_audit.py``.
    """


class SuppressionScopeError(CastDependencyError):
    """A nested suppression is not its parent's exact reverse pair.

    From ``CastDependency(slot="E", requires="Q")`` it must be impossible
    to express a suppression of ``E→W``; structure, not review, is what
    prevents a silently broadened suppression.
    """


class UnknownInferredKindError(CastDependencyError):
    """A suppression names a kind outside ``INFERRED_EDGE_KINDS``."""


class MissingLatentReasonError(CastDependencyError):
    """A suppression that suppresses nothing does not say why.

    Two halves. Here, at import: a ``latent_reason`` that is present but
    blank. At merge, in ``rotation_resolver``: a suppression matching no
    inferred edge whose ``latent_reason`` is ``None``. Both are the same
    defect — a claim about an inference nobody can see — and the merge is
    the only surface that knows which suppressions matched.
    """


class DeclaredCycleError(CastDependencyError):
    """The declared graph alone is cyclic, so no order can satisfy it."""


# ── resolve-time: declarations and inferences disagree ────────────────────


class ConflictingInferenceError(CastDependencyError):
    """An inferred edge opposes an active declaration with no suppression.

    "Declared always wins" would resolve a real modelling disagreement
    silently in the module's favour.
    """


class ResolvedCycleError(CastDependencyError):
    """The merged declared-plus-inferred graph is cyclic for a declaring champion."""


# ── request-time: a caller asked for an impossible order ──────────────────


class CustomOrderViolatesDependencyError(CastDependencyError):
    """A requested cast order inverts an active declared dependency.

    A declared dependency states impossibility, not preference: an illegal
    order makes the engine author a ``cc_kind="stun"`` that cannot exist,
    and an amplifier then prices off a stun that never happened. The
    dependency travels on the exception so the request boundary can put
    its ``reason`` and ``source`` in the response body.
    """

    def __init__(self, dependency: "CastDependency", order: Sequence[str]) -> None:
        self.dependency = dependency
        self.order = tuple(order)
        super().__init__(
            f"cast order {list(order)} places {dependency.slot} before "
            f"{dependency.requires}, but {dependency.slot} requires "
            f"{dependency.requires} ({dependency.kind}): {dependency.reason} "
            f"[source: {dependency.source}]"
        )


@dataclass(frozen=True, slots=True)
class SuppressedInference:
    """One inferred edge a declaration overrides, and why the inference reads
    the mechanic backwards.

    Attributes:
        setup: The inferred edge's setup slot — always the parent's ``slot``.
        consume: The inferred edge's consume slot — always the parent's
            ``requires``.
        kind: Which inferred kind is being overridden; a member of
            ``INFERRED_EDGE_KINDS``.
        reason: Why the inference reads the mechanic backwards.
        latent_reason: Set when the opposed inference does not exist in the
            current tree, so the suppression is a documented latency rather
            than an active override.
    """

    setup: str
    consume: str
    kind: str
    reason: str
    latent_reason: str | None = None


@dataclass(frozen=True, slots=True)
class CastDependency:
    """One module-declared ordering prerequisite between two of its own cast slots.

    ``slot`` requires ``requires``, so the derived order places
    ``requires`` first.

    Attributes:
        slot: The dependent slot.
        requires: The slot that must be cast first.
        kind: A member of ``DEPENDENCY_KINDS``.
        reason: The mechanic, in prose, as reviewed.
        source: ``"<wiki url>@<revision_id>"``, shape-validated at import.
        suppresses: Inferred edges this declaration overrides, each one
            structurally the exact reverse pair.
    """

    slot: str
    requires: str
    kind: str
    reason: str
    source: str
    suppresses: tuple[SuppressedInference, ...] = ()


def validate_cast_dependencies(
    deps: Iterable[CastDependency],
    *,
    slot_surface: Collection[str],
    module: str,
) -> None:
    """Import gate for a module's ``CAST_DEPENDENCIES``.

    Checks slot membership against *this module's own* slot surface (so a
    synthetic key like ``Q2`` is legal because the module declares it),
    the kind vocabulary, non-empty reason and well-shaped source, pair
    uniqueness, suppression scope, and acyclicity of the declared graph
    alone.

    Args:
        deps: The module's declarations.
        slot_surface: The keys of the module's own slot map.
        module: The module name, for the failure message.

    Raises:
        CastDependencyError: One of the nine import-time subclasses.
    """
    declarations = tuple(deps)
    seen_pairs: set[tuple[str, str]] = set()
    for dep in declarations:
        _validate_endpoints(dep, slot_surface=slot_surface, module=module)
        if dep.kind not in DEPENDENCY_KINDS:
            raise UnknownDependencyKindError(
                f"{module}: {dep.slot} requires {dep.requires} declares kind "
                f"{dep.kind!r}, which is not one of "
                f"{sorted(DEPENDENCY_KINDS)}"
            )
        _validate_justification(dep, module=module)
        pair = (dep.slot, dep.requires)
        if pair in seen_pairs:
            raise DuplicateDependencyError(
                f"{module}: {dep.slot} requires {dep.requires} is declared twice"
            )
        seen_pairs.add(pair)
        _validate_suppressions(dep, module=module)

    cycle = _first_declared_cycle(declarations)
    if cycle is not None:
        raise DeclaredCycleError(
            f"{module}: declared dependencies are cyclic: {' -> '.join(cycle)}"
        )


def validate_cast_order_declaration(
    order: Sequence[str],
    deps: Iterable[CastDependency],
    *,
    slot_surface: Collection[str],
    module: str,
) -> None:
    """Import gate for a module's ``CAST_ORDER``.

    A subset permutation of the module's own slot surface satisfying the
    module's own declarations, so a contradiction fails at import.

    Raises:
        UnknownSlotError: The order names a slot outside the surface.
        DuplicateDependencyError: The order repeats a slot.
        CustomOrderViolatesDependencyError: The order inverts one of the
            module's own declarations.
    """
    seen: set[str] = set()
    for slot in order:
        if slot not in slot_surface:
            raise UnknownSlotError(
                f"{module}: CAST_ORDER names {slot!r}, which is not one of this "
                f"module's slots {sorted(slot_surface)}"
            )
        if slot in seen:
            raise DuplicateDependencyError(f"{module}: CAST_ORDER repeats {slot!r}")
        seen.add(slot)
    check_order_satisfies_dependencies(order, deps, seen)


def active_dependencies(
    deps: Iterable[CastDependency],
    live_slots: Collection[str],
) -> tuple[CastDependency, ...]:
    """The declarations both of whose endpoints exist in this parse."""
    return tuple(
        dep for dep in deps if dep.slot in live_slots and dep.requires in live_slots
    )


def orderable_slots(slot_surface: Mapping[str, Mapping[str, Any]]) -> tuple[str, ...]:
    """What a request may name: the surface minus P, minus every recast slot.

    Recast slots ride their parent's casts, so naming one in a requested
    order would schedule it independently. Parentage comes from
    ``recast_of`` on the parsed entry and nowhere else, so a slot that is
    neither a base cast slot nor ``recast_of``-stamped raises rather than
    being linked by name. Returned in ``BASE_CAST_SLOTS`` order, so the
    result never depends on parse order.

    Raises:
        UnknownSlotError: A synthetic slot carries no ``recast_of`` stamp.
    """
    orderable: set[str] = set()
    for slot, entry in slot_surface.items():
        if slot == "P" or _recast_parent(entry):
            continue
        if slot not in BASE_CAST_SLOTS:
            raise UnknownSlotError(
                f"slot {slot!r} is neither a base cast slot nor stamped "
                "recast_of; recast parentage has one authority and it is "
                "the parsed entry, never the slot's name"
            )
        orderable.add(slot)
    return tuple(slot for slot in BASE_CAST_SLOTS if slot in orderable)


def expand_user_order(
    user_order: Sequence[str],
    live_slots: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """Reinsert each live recast slot immediately after its parent.

    ``["Q", "W", "E", "R"]`` becomes ``["Q", "Q2", "W", "E", "R"]`` when
    Q2 is live. Without this a requested order silently drops every recast
    row from the damage breakdown.

    Args:
        user_order: The requested order over orderable slots.
        live_slots: Parsed ability entries by slot for this parse.

    Returns:
        The requested order with live recasts folded in, chains included
        and already-named slots never duplicated.
    """
    children: dict[str, list[str]] = {}
    for slot, entry in live_slots.items():
        parent = _recast_parent(entry)
        if parent:
            children.setdefault(parent, []).append(slot)
    for kids in children.values():
        kids.sort()

    placed = set(user_order)
    expanded: list[str] = []
    for slot in user_order:
        expanded.append(slot)
        pending = list(children.get(slot, ()))
        while pending:
            child = pending.pop(0)
            if child in placed:
                continue
            placed.add(child)
            expanded.append(child)
            pending = list(children.get(child, ())) + pending
    return expanded


def check_order_satisfies_dependencies(
    order: Sequence[str],
    deps: Iterable[CastDependency],
    live_slots: Collection[str],
) -> None:
    """Reject an order that inverts an active declared dependency.

    The refusal quotes the dependency's own ``reason`` and ``source``, so it
    names the mechanic rather than the rule that caught it.
    """
    position = {slot: index for index, slot in enumerate(order)}
    for dep in active_dependencies(deps, live_slots):
        if dep.slot not in position or dep.requires not in position:
            continue
        if position[dep.requires] > position[dep.slot]:
            raise CustomOrderViolatesDependencyError(dep, order)


# ── internals ─────────────────────────────────────────────────────────────


def _recast_parent(entry: Mapping[str, Any]) -> str | None:
    """The slot a parsed ability entry is a recast of, or ``None``."""
    parent = entry.get("recast_of")
    return parent if isinstance(parent, str) and parent else None


def _validate_endpoints(
    dep: CastDependency, *, slot_surface: Collection[str], module: str
) -> None:
    """Both endpoints are this module's own slots, and they differ."""
    for role, slot in (("slot", dep.slot), ("requires", dep.requires)):
        if slot not in slot_surface:
            raise UnknownSlotError(
                f"{module}: dependency {role}={slot!r} is not one of this "
                f"module's slots {sorted(slot_surface)}"
            )
    if dep.slot == dep.requires:
        raise SelfDependencyError(f"{module}: {dep.slot} requires itself")


def _validate_justification(dep: CastDependency, *, module: str) -> None:
    """Non-empty reason and a ``<url>@<revision_id>`` source."""
    if not dep.reason.strip():
        raise UnsourcedDependencyError(
            f"{module}: {dep.slot} requires {dep.requires} carries no reason"
        )
    if not _is_sourced(dep.source):
        raise UnsourcedDependencyError(
            f"{module}: {dep.slot} requires {dep.requires} carries source "
            f"{dep.source!r}, which is not '<wiki url>@<revision_id>'"
        )


def _is_sourced(source: str) -> bool:
    """Whether *source* has the ``"<http(s) url>@<revision_id>"`` shape."""
    url, separator, revision = source.rpartition("@")
    return bool(
        separator
        and url.startswith(("http://", "https://"))
        and len(url) > len("https://")
        and revision.isdigit()
    )


def _validate_suppressions(dep: CastDependency, *, module: str) -> None:
    """Every nested suppression is the exact reverse pair, kinded and justified."""
    seen: set[tuple[str, str, str]] = set()
    for suppression in dep.suppresses:
        if suppression.setup != dep.slot or suppression.consume != dep.requires:
            raise SuppressionScopeError(
                f"{module}: {dep.slot} requires {dep.requires} suppresses "
                f"{suppression.setup}->{suppression.consume}, but a suppression "
                f"may only be its parent's exact reverse pair "
                f"{dep.slot}->{dep.requires}"
            )
        if suppression.kind not in INFERRED_EDGE_KINDS:
            raise UnknownInferredKindError(
                f"{module}: suppression {suppression.setup}->"
                f"{suppression.consume} names inferred kind "
                f"{suppression.kind!r}, which is not one of "
                f"{sorted(INFERRED_EDGE_KINDS)}"
            )
        if not suppression.reason.strip():
            raise UnsourcedDependencyError(
                f"{module}: suppression {suppression.setup}->"
                f"{suppression.consume} carries no reason"
            )
        if suppression.latent_reason is not None and not (
            suppression.latent_reason.strip()
        ):
            raise MissingLatentReasonError(
                f"{module}: suppression {suppression.setup}->"
                f"{suppression.consume} declares a blank latent_reason; either "
                "say why the inference is absent or leave it None"
            )
        triple = (suppression.setup, suppression.consume, suppression.kind)
        if triple in seen:
            raise DuplicateDependencyError(
                f"{module}: suppression {suppression.setup}->"
                f"{suppression.consume} ({suppression.kind}) is declared twice"
            )
        seen.add(triple)


def _first_declared_cycle(
    deps: Sequence[CastDependency],
) -> tuple[str, ...] | None:
    """The first cycle in the declared ``requires -> slot`` graph, or ``None``."""
    successors: dict[str, list[str]] = {}
    for dep in deps:
        successors.setdefault(dep.requires, []).append(dep.slot)

    visiting: set[str] = set()
    settled: set[str] = set()
    path: list[str] = []

    def walk(node: str) -> tuple[str, ...] | None:
        visiting.add(node)
        path.append(node)
        for successor in successors.get(node, ()):
            if successor in visiting:
                return tuple(path[path.index(successor) :] + [successor])
            if successor not in settled:
                found = walk(successor)
                if found is not None:
                    return found
        path.pop()
        visiting.discard(node)
        settled.add(node)
        return None

    for start in successors:
        if start not in settled:
            cycle = walk(start)
            if cycle is not None:
                return cycle
    return None
