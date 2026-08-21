"""A declared defence, read through its own declaration.

The four defence families share no arithmetic — a spell shield is not a
resistance ramp is not a resurrection — but they share exactly one thing:
*how a defence is allowed to reach the registry*.  This module is that,
and only that.

:class:`DefenseSlot` is the accessor the family interpreters hold instead of
an item name.  Every read refuses rather than defaults: a key the
declaration does not carry is a stop, a level ramp asked for as a flat value
is a stop, and a field the mechanic never declared it writes cannot be
written.  That is what makes the declaration load-bearing rather than
descriptive — deleting a value reference takes the number out of the fight
with a named error, instead of leaving a resolver reading the registry
directly and nobody noticing the declaration went stale.

Nothing here is memoized, for the same reason nothing in the catalog is:
``refresh_item_effects()`` has to move the answer, and a defence projection
cached across a patch-day refresh is the stale literal one layer up.
"""

from __future__ import annotations

from .. import item_effects
from ..item_behavior import (
    BehaviorRule,
    BuildContext,
    DEFENSE_PAYLOAD_TYPES,
    DefenseExclusivity,
    DefenseField,
    DefenseMechanic,
    EngineLane,
    KernelField,
)
from ..item_behavior_catalog import behavior_rules
from ..value_ref import LateLevelValueRef, LevelValueRef, ValueRef

# What a defence compiles to for inspection at build time: how many sourced
# numbers its declaration carries.  A defence's *value* is not a build-time
# number — it depends on the subject's own resolved stats and on the
# scenario's input options — so the shape is what this lane can prove, and
# claiming otherwise would be a number the mechanic cannot have yet.
DEFENSE_VALUE_COUNT_FIELD = "defense_values"


class DefenseInterpretationError(ValueError):
    """A defence was asked something its declaration does not answer."""


def payload(rule: BehaviorRule):
    """*rule*'s defence payload, or a stop."""
    if not isinstance(rule.payload, DEFENSE_PAYLOAD_TYPES):
        raise DefenseInterpretationError(f"{rule.mechanic_id} is not a defence rule")
    return rule.payload


class DefenseSlot:
    """One holder's declared defence, with the numbers it may read.

    The resolver holds one of these instead of an item name.  ``owner`` is
    still available — a published label and a state source name the item —
    but it is a *value read off the declaration*, never a literal a branch
    was chosen by.
    """

    __slots__ = ("rule",)

    def __init__(self, rule: BehaviorRule) -> None:
        """Bind the slot to one compiled rule."""
        payload(rule)
        self.rule = rule

    @property
    def owner(self) -> str:
        """The item whose registry entry carries this defence."""
        return self.rule.owner

    @property
    def mechanic(self) -> DefenseMechanic:
        """Which defence this slot is."""
        return payload(self.rule).mechanic

    def value(self, key: str) -> float:
        """One declared number, read live from the registry that owns it."""
        for reference in payload(self.rule).values:
            if isinstance(reference, ValueRef) and reference.key == key:
                return reference.get()
        raise DefenseInterpretationError(
            f"{self.rule.mechanic_id} declares no {key!r} value; a defence "
            "reads the numbers its declaration names and no others"
        )

    def ramp(self, key: str, level: int) -> float:
        """One declared one-to-eighteen ramp, read at *level*.

        *key* is the ramp's low key, which is how the declaration names it: a
        ramp is one number with two ends, not two numbers.
        """
        for reference in payload(self.rule).values:
            if isinstance(reference, LevelValueRef) and reference.min_key == key:
                return reference.get(level)
        raise DefenseInterpretationError(
            f"{self.rule.mechanic_id} declares no {key!r} level ramp"
        )

    def late_ramp(self, key: str, level: int) -> float:
        """One declared late ramp — flat until the level the entry names."""
        for reference in payload(self.rule).values:
            if isinstance(reference, LateLevelValueRef) and reference.min_key == key:
                return reference.get(level)
        raise DefenseInterpretationError(
            f"{self.rule.mechanic_id} declares no {key!r} late level ramp"
        )

    def threshold(self) -> float:
        """The health fraction that arms this defence, or a stop."""
        return self._policy_reference("threshold")

    def duration(self) -> float:
        """How long this defence lasts once armed, or a stop."""
        return self._policy_reference("duration")

    def _policy_reference(self, name: str) -> float:
        """One of the payload's own declared references, read now."""
        reference = getattr(payload(self.rule), name, None)
        if reference is None:
            raise DefenseInterpretationError(
                f"{self.rule.mechanic_id} declares no {name}; it is a defence "
                "of a different shape than the one asking"
            )
        return reference.get()

    def grant(
        self, field: DefenseField, value: float | int | bool | str
    ) -> KernelField:
        """One resolved field, refused unless the declaration writes it.

        This is the half that makes ``writes`` load-bearing: an interpreter
        that grew a field its mechanic never declared would be a defence
        doing something no reader of the declaration could see.
        """
        if field not in payload(self.rule).writes:
            raise DefenseInterpretationError(
                f"{self.rule.mechanic_id} does not declare that it writes "
                f"{field.value}; a defence writes the state its declaration "
                "names and no other"
            )
        return KernelField(
            name=field.value,
            value=value,
            lane=EngineLane.DEFENSE_RESOLVER,
            rule_id=self.rule.mechanic_id,
        )


def declared_defenses(names: frozenset[str]) -> dict[DefenseMechanic, BehaviorRule]:
    """Every defence a build declares, one rule per mechanic.

    Two things are decided here and nowhere else.  Exclusivity: a build may
    legally hold two Lifelines, two Annuls or both stasis items, and exactly
    one of each group is read.  Which one: the owner whose entry comes first
    in the number registry.  Walking the registry rather than the build is
    what makes that tie-break statable at all, because a build is a set and a
    set has no first.
    """
    selected: dict[DefenseMechanic, BehaviorRule] = {}
    claimed: set[DefenseExclusivity] = set()
    for owner in item_effects.ITEM_EFFECTS:
        if owner not in names:
            continue
        for rule in behavior_rules(owner):
            if not isinstance(rule.payload, DEFENSE_PAYLOAD_TYPES):
                continue
            exclusivity = rule.payload.exclusivity
            if exclusivity is not DefenseExclusivity.NONE:
                if exclusivity in claimed:
                    continue
                claimed.add(exclusivity)
            selected.setdefault(rule.payload.mechanic, rule)
    return selected


def compiled_shape(
    rule: BehaviorRule, ctx: BuildContext, lane: EngineLane
) -> tuple[KernelField, ...]:
    """The shape a defence compiles to, and the proof its numbers resolve.

    Registered for every defence family on the resolver lane — a defence's
    *value* depends on the subject's own resolved stats, so the shape is all
    this lane can honestly compile and all six families compile it the same
    way.  Resolving every reference here is what makes a defence's build-time
    failures — a missing registry key, a ramp whose ends were not parsed —
    surface when the build is made rather than on whichever fight first needed
    the number.
    """
    references = payload(rule).values
    for reference in references:
        if isinstance(reference, (LevelValueRef, LateLevelValueRef)):
            reference.get(ctx.level)
        else:
            reference.get()
    return (
        KernelField(
            name=DEFENSE_VALUE_COUNT_FIELD,
            value=len(references),
            lane=lane,
            rule_id=rule.mechanic_id,
        ),
    )


__all__ = [
    "DEFENSE_VALUE_COUNT_FIELD",
    "DefenseInterpretationError",
    "DefenseSlot",
    "compiled_shape",
    "declared_defenses",
    "payload",
]
