"""The roster one composition pass walks, frozen, and how a later pass differs.

``program/`` answers "what happened, and to whom".  The "to whom" is this
module: a :class:`Program` names the participants of one pass beside the
actors those ids stand for, index-aligned and validated as such, so the five
views that take ``(Program, WalkResult)`` read a champion at a level holding
items rather than a string.

:class:`ParamPatch` is the only way a later pass differs from its
predecessor.  Anything else would make "the program is rebuilt per pass" a
claim about intent rather than a property: two passes that could differ by an
undeclared mutation are two programs nobody can diff.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..delivery_facts import CombatantFacts


@dataclass(frozen=True, slots=True)
class ParamPatch:
    """The per-pass parameter overrides a cross-pass dependency feeds pass 2."""

    overrides: Mapping[str, Any]
    reason: str


@dataclass(frozen=True, slots=True)
class Program:
    """One composition pass's roster, frozen.

    ``pass_index`` is a field rather than context because a cross-pass
    dependency rebuilds the program: two passes are two programs, and a
    reader that could not tell them apart would attribute pass 1's numbers to
    pass 2 and discard the patch that caused it.

    ``actors`` is the roster those participant ids stand for, index-aligned
    with ``participants``.  Two id lists that could disagree would be the
    kept-in-step-by-hand arrangement one layer down, so there is one list and
    the other is derived from it at construction.
    """

    participants: tuple[str, ...]
    pass_index: int = 0
    patch: ParamPatch | None = None
    actors: tuple[CombatantFacts, ...] = ()
    focus: str = ""

    def __post_init__(self) -> None:
        """A roster that disagrees with its own id list is not one."""
        if self.actors and len(self.actors) != len(self.participants):
            raise ValueError(
                "program actors and participants must be index-aligned: "
                f"{len(self.actors)} actors against {len(self.participants)} ids"
            )
        for index, actor in enumerate(self.actors):
            if actor.participant_id != self.participants[index]:
                raise ValueError(
                    "program actor "
                    f"{actor.participant_id!r} sits at slot {index}, which the "
                    f"participant list calls {self.participants[index]!r}"
                )

    def roster_size(self) -> int:
        """How many participants the program's roster indices are bounded by."""
        return len(self.participants)


def roster_program(
    actors: Sequence[CombatantFacts],
    *,
    pass_index: int = 0,
    patch: ParamPatch | None = None,
    focus: str = "",
) -> Program:
    """The program one composition pass walks, named by its roster.

    The composition authors its transitions as engine packets and compiles
    them straight to ``SurvivalAction`` through ``WalkCompiler``, so no
    logical event list exists for those passes: the views read the roster and
    the walk result, pinned by a test.
    """
    return Program(
        participants=tuple(str(actor.participant_id) for actor in actors),
        pass_index=pass_index,
        patch=patch,
        actors=tuple(actors),
        focus=focus,
    )


__all__ = [
    "ParamPatch",
    "Program",
    "roster_program",
]
