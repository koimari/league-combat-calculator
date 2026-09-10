"""The closed vocabularies a value reference is spelled in, and the refusal any of them raises."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

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
# is the plain one-to-eighteen ramp; ``linear_1_20`` is the same ramp over the
# top-lane level cap CLAUDE.md records, which is the span the item registry's
# own active formulas interpolate across.  There is no "whatever the caller
# meant" member on purpose.
LevelScale = Literal["registry_start", "linear_1_18", "linear_1_20"]


LEVEL_SCALES: frozenset[str] = frozenset(
    {"registry_start", "linear_1_18", "linear_1_20"}
)


# The top level each linear ramp interpolates to.  A ramp reaches its maximum
# key's value exactly at this level and is clamped there above it, so the two
# spans differ in one number rather than in two code paths.
_LINEAR_RAMP_CAP: Mapping[str, int] = {"linear_1_18": 18, "linear_1_20": 20}


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
