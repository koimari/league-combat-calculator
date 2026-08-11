"""Live references into the three number registries, and their receipts.

A declaration must be able to say *which number* a rule uses without holding
the number.  A float copied into a declaration is a stale literal the moment
the parser moves — the exact failure CLAUDE.md rule 5 exists to prevent, one
layer up — so every number a :class:`~.item_behavior.BehaviorRule` reads is a
reference resolved at call time against the registry that owns it.

Three registries own runtime numbers and this module can reach all three
(D-46): ``ITEM_EFFECTS`` and ``ALLY_ITEM_EFFECTS`` in ``item_effects``, and
``RUNE_EFFECTS`` in ``rune_effects`` — keystones are runtime damage
producers, so an items-only union would leave two amp producers outside the
no-literals rule.  This union is deliberately **not** Phase 1's
``coverage_evidence.EvidenceRegistry``, which carries a fourth member
(``ITEM_INPUT_OPTIONS``) holding scenario controls rather than sourced
numbers: an evidence member may name an option control's key and a value
reference may not.

Reads route through the registries' own fail-loud accessors
(``required_effect_value``, ``ally_item_effect_value``, ``rune_effect_value``)
rather than re-implementing them, so a missing key raises naming the owner
and the key instead of silently borrowing a default.  The modules are
imported, never the registry objects, because ``refresh_item_effects()``
rebuilds a registry in place and a name bound at import would be the thing
D-48's refresh proof cannot distinguish from a live reference.

:class:`SourceReceipt` and :func:`receipt_for` live here too, beside the
accessors they read: a receipt is a *citation of the registry entry a
declaration was read from*, so it belongs with the registry reads and not
with the rule union.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Union

from . import item_effects, rune_effects

# ── the registry union ────────────────────────────────────────────────────

ValueRegistry = Literal["ITEM_EFFECTS", "ALLY_ITEM_EFFECTS", "RUNE_EFFECTS"]

VALUE_REGISTRIES: frozenset[str] = frozenset(
    {"ITEM_EFFECTS", "ALLY_ITEM_EFFECTS", "RUNE_EFFECTS"}
)

# Why a raw number is allowed to sit inside a frozen declaration at all.
# Closed: a reason outside this set means the number is a *quantity*, and a
# quantity belongs in a registry behind a ValueRef.  ``origin`` is a
# coordinate the model measures from — the start of the fight — rather than a
# magnitude: no patch moves it, and spelling it ``count`` would say a
# window's start is a tally of something.
StructuralReason = Literal["count", "cap", "rank", "flag", "unit_scale", "origin"]

STRUCTURAL_REASONS: frozenset[str] = frozenset(
    {"count", "cap", "rank", "flag", "unit_scale", "origin"}
)

# How a two-key level ramp is interpolated.  ``registry_start`` delegates to
# the ally registry's own ``level_scaling_start`` breakpoint; ``linear_1_18``
# is the plain one-to-eighteen ramp.  There is no "whatever the caller meant"
# member on purpose.
LevelScale = Literal["registry_start", "linear_1_18"]

LEVEL_SCALES: frozenset[str] = frozenset({"registry_start", "linear_1_18"})

# The arithmetic a derived reference may perform over other references.
# ``SUB`` exists because an amplifier's registry number is sometimes a
# *multiplier* (Shadowflame's crit multiplier is 1.2) while the chain prices
# a *fraction*, and the conversion is a subtraction of the multiplier axis'
# origin.  Spelling it ADD against a negative constant would hide a
# conversion inside a sign.
DerivedOp = Literal["ADD", "SUB", "MUL", "MIN", "MAX", "RATIO"]

DERIVED_OPS: frozenset[str] = frozenset({"ADD", "SUB", "MUL", "MIN", "MAX", "RATIO"})


class ValueRefError(ValueError):
    """A reference is malformed — a registry, scale or op outside its union."""


class UnsourcedDeclarationError(ValueError):
    """No citation could be resolved for a declaration's owner.

    Raised by :func:`receipt_for`.  A declaration with no receipt is a number
    whose provenance is a memory, which is what every audit in this
    repository exists to make impossible.
    """


# ── receipts ──────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class SourceReceipt:
    """The revision a declaration's numbers were read from.

    ``revision_id`` is a MediaWiki revision id, or ``0`` — the explicit
    marker for a value read from the patch-stamped cached item source, which
    exposes no revision id.  Zero is spelled rather than omitted for the same
    reason the campaign spells ``STRUCTURAL_ZERO``: an absent id and an id
    that does not exist must not look alike.  ``revision_timestamp`` is the
    human-checkable stamp for that revision; when the id is ``0`` it names
    the cache instead (the precedent already in ``defensive_effects``).
    """

    url: str
    revision_id: int
    revision_timestamp: str

    def __post_init__(self) -> None:
        """Reject a receipt that cites nothing checkable."""
        if not self.url.startswith("http"):
            raise ValueRefError(f"SourceReceipt url must be a URL, got {self.url!r}")
        if isinstance(self.revision_id, bool) or not isinstance(self.revision_id, int):
            raise ValueRefError("SourceReceipt revision_id must be an int")
        if self.revision_id < 0:
            raise ValueRefError("SourceReceipt revision_id must not be negative")
        if not self.revision_timestamp.strip():
            raise ValueRefError("SourceReceipt revision_timestamp must not be empty")


def _registry(registry: ValueRegistry) -> Mapping[str, Mapping[str, object]]:
    """The live registry mapping for one member of the union."""
    if registry == "ITEM_EFFECTS":
        return item_effects.ITEM_EFFECTS
    if registry == "ALLY_ITEM_EFFECTS":
        return item_effects.ALLY_ITEM_EFFECTS
    if registry == "RUNE_EFFECTS":
        return rune_effects.RUNE_EFFECTS
    raise ValueRefError(
        f"{registry!r} is not one of {sorted(VALUE_REGISTRIES)} — a declaration "
        "may only reference a registry that owns runtime numbers (D-46)"
    )


def _entry_receipt(registry: ValueRegistry, owner: str) -> SourceReceipt | None:
    """The receipt an owner's own registry entry carries, if it carries one.

    A *complete* citation is all three of ``source_url``,
    ``source_revision_id`` and ``source_revision_timestamp``.  A partial one
    resolves to ``None`` rather than being completed from somewhere else:
    silently filling in the missing third of a citation is how a receipt
    starts describing a revision nobody read.
    """
    entry = _registry(registry).get(owner)
    if not isinstance(entry, Mapping):
        return None
    url = entry.get("source_url")
    revision = entry.get("source_revision_id")
    stamp = entry.get("source_revision_timestamp")
    if not isinstance(url, str) or not isinstance(revision, int):
        return None
    if not isinstance(stamp, str) or not stamp.strip():
        return None
    return SourceReceipt(url=url, revision_id=revision, revision_timestamp=stamp)


def receipt_for(
    registry: ValueRegistry,
    owner: str,
    *,
    declared: SourceReceipt | None = None,
) -> SourceReceipt:
    """Resolve one declaration's citation, or raise.

    Resolution order is ruled: the owning registry entry's own citation
    first, then the family's declared constant, then failure.  The declared
    constant arrives as ``declared`` rather than through a table here because
    families live in ``item_behavior`` — which imports this module — so a
    family-keyed fallback table in this file would invert the dependency.
    """
    entry = _entry_receipt(registry, owner)
    if entry is not None:
        return entry
    if declared is not None:
        return declared
    raise UnsourcedDeclarationError(
        f"{registry}[{owner!r}] carries no complete citation "
        "(source_url + source_revision_id + source_revision_timestamp) and the "
        "family declared no constant receipt — a rule may not be declared "
        "against an unsourced number"
    )


# ── references ────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Const:
    """A raw number that is legal in a declaration because it is structural.

    Counts, caps, ranks and flags describe the *shape* of a mechanic rather
    than its magnitude: three stacks is three stacks in every patch, and
    putting it in a registry would be a key nobody sources.  ``reason`` is
    what keeps that argument honest — a non-integral value is only legal
    under ``unit_scale`` (a per-cent or per-mille conversion), because every
    other non-integral number in this codebase is a quantity somebody
    patches.
    """

    value: float
    reason: StructuralReason

    def __post_init__(self) -> None:
        """Reject a magnitude wearing a structural constant's clothes."""
        if self.reason not in STRUCTURAL_REASONS:
            raise ValueRefError(
                f"Const reason {self.reason!r} is not one of "
                f"{sorted(STRUCTURAL_REASONS)}"
            )
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise ValueRefError("Const value must be a number")
        if not math.isfinite(self.value):
            raise ValueRefError("Const value must be finite")
        if self.reason == "flag" and self.value not in (0.0, 1.0):
            raise ValueRefError("a Const flag is 0.0 or 1.0")
        if not float(self.value).is_integer() and self.reason != "unit_scale":
            raise ValueRefError(
                f"Const({self.value!r}, {self.reason!r}) is non-integral; only "
                "unit_scale may be — every other non-integral number belongs "
                "in a registry behind a ValueRef"
            )

    def get(self, level: int | None = None) -> float:
        """The constant.  ``level`` is accepted so every reference reads alike."""
        del level
        return float(self.value)


@dataclass(frozen=True, slots=True)
class ValueRef:
    """One sourced number, read live from the registry that owns it."""

    registry: ValueRegistry
    owner: str
    key: str

    def __post_init__(self) -> None:
        """Reject a reference into a registry outside the union."""
        if self.registry not in VALUE_REGISTRIES:
            raise ValueRefError(
                f"{self.registry!r} is not one of {sorted(VALUE_REGISTRIES)}"
            )
        if not self.owner or not self.key:
            raise ValueRefError("a ValueRef names an owner and a key")

    def get(self, level: int | None = None) -> float:
        """Read the number now, raising with owner and key context if absent."""
        del level
        if self.registry == "ITEM_EFFECTS":
            value = item_effects.required_effect_value(self.owner, self.key)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueRefError(
                    f"ITEM_EFFECTS[{self.owner!r}][{self.key!r}] is not numeric"
                )
            return float(value)
        if self.registry == "ALLY_ITEM_EFFECTS":
            return item_effects.ally_item_effect_value(self.owner, self.key)
        return rune_effects.rune_effect_value(self.owner, self.key)


@dataclass(frozen=True, slots=True)
class LevelValueRef:
    """A two-key level ramp, resolved live and interpolated by a named scale."""

    registry: ValueRegistry
    owner: str
    min_key: str
    max_key: str
    scale: LevelScale

    def __post_init__(self) -> None:
        """Reject a scale outside the union, or one its registry cannot serve."""
        if self.registry not in VALUE_REGISTRIES:
            raise ValueRefError(
                f"{self.registry!r} is not one of {sorted(VALUE_REGISTRIES)}"
            )
        if self.scale not in LEVEL_SCALES:
            raise ValueRefError(
                f"level scale {self.scale!r} is not one of {sorted(LEVEL_SCALES)}"
            )
        if self.scale == "registry_start" and self.registry != "ALLY_ITEM_EFFECTS":
            raise ValueRefError(
                "the registry_start scale reads ALLY_ITEM_EFFECTS' own "
                "level_scaling_start breakpoint and is defined for no other "
                "registry"
            )
        if not self.owner or not self.min_key or not self.max_key:
            raise ValueRefError("a LevelValueRef names an owner and two keys")

    def get(self, level: int) -> float:
        """The ramp's value at *level*, read from the registry now."""
        if self.scale == "registry_start":
            return item_effects.ally_item_level_value(
                self.owner, self.min_key, self.max_key, level
            )
        low = ValueRef(self.registry, self.owner, self.min_key).get()
        high = ValueRef(self.registry, self.owner, self.max_key).get()
        clamped = max(1, min(18, int(level)))
        return low + (high - low) * (clamped - 1) / 17.0


@dataclass(frozen=True, slots=True)
class DerivedValueRef:
    """Arithmetic over other references, so a derivation is never a literal.

    ``RATIO`` and ``SUB`` are two-operand; the rest fold left over one or
    more operands.  A derived reference resolves its operands at call time,
    so a refresh moves the derived number too.
    """

    op: DerivedOp
    operands: tuple["AnyValueRef", ...]

    def __post_init__(self) -> None:
        """Reject an op outside the union or an arity the op cannot fold."""
        if self.op not in DERIVED_OPS:
            raise ValueRefError(f"derived op {self.op!r} is not one of {DERIVED_OPS}")
        if not self.operands:
            raise ValueRefError("a DerivedValueRef needs at least one operand")
        if self.op in ("RATIO", "SUB") and len(self.operands) != 2:
            raise ValueRefError(f"{self.op} takes exactly two operands")

    def get(self, level: int | None = None) -> float:
        """Fold the operands, resolving each against its registry now."""
        values = [_resolve(operand, level) for operand in self.operands]
        if self.op == "ADD":
            return math.fsum(values)
        if self.op == "SUB":
            minuend, subtrahend = values
            return minuend - subtrahend
        if self.op == "MIN":
            return min(values)
        if self.op == "MAX":
            return max(values)
        if self.op == "RATIO":
            numerator, denominator = values
            if denominator == 0.0:
                raise ValueRefError(
                    f"RATIO over {self.operands!r} divides by zero — a zero "
                    "denominator is a registry defect, not a result"
                )
            return numerator / denominator
        product = 1.0
        for value in values:
            product *= value
        return product


AnyValueRef = Union[Const, ValueRef, LevelValueRef, DerivedValueRef]

VALUE_REF_TYPES: tuple[type, ...] = (Const, ValueRef, LevelValueRef, DerivedValueRef)


def _resolve(reference: AnyValueRef, level: int | None) -> float:
    """Read one reference, supplying the level only to the ones that need it."""
    if isinstance(reference, LevelValueRef):
        if level is None:
            raise ValueRefError(
                f"{reference!r} is level-scaled and no level was supplied"
            )
        return reference.get(level)
    return reference.get(level)


def resolve(reference: AnyValueRef, level: int | None = None) -> float:
    """Read any reference in the union — the one entry point consumers use."""
    if not isinstance(reference, VALUE_REF_TYPES):
        raise ValueRefError(
            f"{reference!r} is not a value reference; a declaration holds "
            "references, never numbers"
        )
    return _resolve(reference, level)


__all__ = [
    "AnyValueRef",
    "Const",
    "DERIVED_OPS",
    "DerivedOp",
    "DerivedValueRef",
    "LEVEL_SCALES",
    "LevelScale",
    "LevelValueRef",
    "STRUCTURAL_REASONS",
    "SourceReceipt",
    "StructuralReason",
    "UnsourcedDeclarationError",
    "VALUE_REF_TYPES",
    "VALUE_REGISTRIES",
    "ValueRef",
    "ValueRefError",
    "ValueRegistry",
    "receipt_for",
    "resolve",
]
