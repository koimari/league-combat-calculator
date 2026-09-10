"""Which panel rows a published total counts, and in what order."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

#: The receipt's three event panels, in the order a total that unions them
#: reads them.  The order is *declared* rather than incidental, and it is
#: also what attributes a shared id: the first panel to publish an id owns
#: it, so ``events`` before ``support_events`` means a support packet that
#: delivered damage is counted as damage.
SUM_PANELS: tuple[str, ...] = ("events", "healing_events", "support_events")


class DuplicateSumMember(ValueError):
    """One panel published one event id twice, so its own rows repeat.

    Named rather than generic because the failure it describes has no
    symptom: a total that counted one event twice is a plausible number.
    This is the unambiguous half — a *panel* repeating an id is a defect
    whatever the id means.  The cross-panel half is not a defect and is not
    refused; see :attr:`SumPlan.shared`.
    """


@dataclass(frozen=True, slots=True)
class SumPlan:
    """The event ids one published total sums, in the order it sums them.

    The receipt publishes three event panels and a reader that wants every
    event of a fight unions them.  Nothing said what that union should do
    with an id on two panels — D-65's own note is that three sources are
    unioned with only a comment preventing a double count — and the answer
    turns out to matter: a Redemption Intervention is published once on
    ``events`` as the damage it dealt and once on ``support_events`` as the
    support packet that dealt it, same id, same amount.  Summing the panels
    counts that 219.2 twice, and the wrong total is a perfectly ordinary
    number, which is this campaign's whole subject.

    A plan is that union made a value.  :attr:`members` is every published
    ``(panel, event_id)`` pair in declared order; :attr:`ids` is what a
    total sums — each event **once**, attributed to the first panel in
    :data:`SUM_PANELS` that published it.  So the double count is not
    tested for, it is unrepresentable: a caller folding over ``ids`` cannot
    reach the same event twice, which is the move ``Quantity.__add__``
    makes for propagation one layer up.

    **Ordering is declared, not incidental.**  Members arrive in
    :data:`SUM_PANELS` order and, within a panel, in walk order — the order
    the rows were published in.  That is a declaration rather than a
    detail because float addition is not associative: a total folded over a
    re-spelled ordering is a different number, and a plan whose order was
    "whatever the mapping iterated" would make it a different number for
    reasons no reader could see.

    **What is refused and what is recorded.**  One panel publishing one id
    twice is a defect with no benign reading, and it raises.  Two panels
    publishing one id is a support packet that delivered damage — refusing
    it would refuse to serve Redemption at all — so it is *recorded*, in
    :attr:`shared`, where a reader can see the events that would have been
    double-counted instead of inferring their absence.
    """

    members: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        """Refuse a panel that published one id twice."""
        # A ``dict`` rather than a ``set``: this type is reachable from the
        # receipt view, and criterion 3's purity walk follows an attribute
        # call into every class defining that name -- so ``seen.add(...)``
        # would enrol the damage engine's own ``add`` in a view's call
        # graph.  Membership in a dict answers the same question and
        # resolves to nothing.
        seen: dict[tuple[str, str], bool] = {}
        for member in self.members:
            if member in seen:
                raise DuplicateSumMember(
                    f"panel {member[0]!r} publishes event id {member[1]!r} twice; "
                    "its own rows would count that event twice"
                )
            seen[member] = True

    @property
    def ids(self) -> tuple[str, ...]:
        """What a total sums: every event once, in the plan's declared order.

        The deduplication is the plan's whole job, so it is a derivation and
        not a caller's discipline.  First panel wins, which is why
        :data:`SUM_PANELS` is an order rather than a set.
        """
        ordered: list[str] = []
        seen: dict[str, bool] = {}
        for _panel, event_id in self.members:
            if event_id not in seen:
                seen[event_id] = True
                ordered.append(event_id)
        return tuple(ordered)

    @property
    def shared(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        """The ids more than one panel published, with the panels, in order.

        Empty for almost every fight.  Non-empty is not an error: it is the
        list of events a naive union would have counted twice, named so a
        reader can see them rather than trust that they do not exist.
        """
        panels_by_id: dict[str, list[str]] = {}
        for panel, event_id in self.members:
            if event_id in panels_by_id:
                panels_by_id[event_id].append(panel)
            else:
                panels_by_id[event_id] = [panel]
        return tuple(
            (event_id, tuple(panels))
            for event_id, panels in panels_by_id.items()
            if len(panels) > 1
        )

    def of(self, panel: str) -> tuple[str, ...]:
        """Every id one panel published, in the plan's declared order."""
        return tuple(
            event_id for member_panel, event_id in self.members if member_panel == panel
        )


def sum_plan(panels: Mapping[str, Sequence[Mapping[str, Any]]]) -> SumPlan:
    """The plan over the receipt's published rows, keyed by panel name.

    A row with no ``event_id`` contributes no member, because a union over ids
    cannot double-count an unidentified row.  A panel outside :data:`SUM_PANELS`
    raises: a fourth stream silently outside the plan is the gap this closes.
    """
    unknown = sorted(panel for panel in panels if panel not in SUM_PANELS)
    if unknown:
        raise KeyError(
            f"{unknown} is not a declared sum panel; the declared panels are "
            f"{list(SUM_PANELS)}"
        )
    members: list[tuple[str, str]] = []
    for panel in SUM_PANELS:
        for row in panels.get(panel, ()):
            event_id = row.get("event_id")
            if event_id is not None:
                members.append((panel, str(event_id)))
    return SumPlan(members=tuple(members))
