"""The books one composition pass writes through, and the subjects its steps read."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, MutableMapping
from typing import Any, NamedTuple

from ..fight_params import FightParams
from ..program.build import Program
from ..program.walk import WalkResult
from ..roster_composition import Combatant

#: Every input that priced one cached pair packet, restores included.
PairCacheKey = tuple[str, str, tuple[float | str, ...], tuple[tuple[float, float], ...]]

#: The engine targeting-row kinds that landed on a secondary target, read by
#: the allocation receipt and the utility census.
SECONDARY_TARGETING_KINDS = frozenset(
    {
        "active_secondary",
        "chain_lightning",
        "chain_lightning_copied_on_hit",
        "cleave_secondary",
        "hydra_cleave",
        "runaan_bolt",
        "runaan_bolt_copied_on_hit",
    }
)


class TimelineScene(NamedTuple):
    """The roster and the three event books a scheduler authors into.

    The books are held by reference, so a scheduler appends to the same lists
    the composition goes on to read.
    """

    all_actors: list[Combatant]
    incoming: MutableMapping[str, list[dict[str, Any]]]
    outgoing: MutableMapping[str, list[dict[str, Any]]]
    support_effects: MutableMapping[str, list[dict[str, Any]]]


class Roster(NamedTuple):
    """The composed actors, in the order every ledger fold replays them."""

    main: Combatant
    ally_actors: list[Combatant]
    enemy_actors: list[Combatant]
    enemy_attackers: list[Combatant]
    all_actors: list[Combatant]


class Ledgers(NamedTuple):
    """The books one pass writes, held by reference by every step.

    ``main_cast_timeline`` is the main champion's own cast schedule, taken
    from its first outgoing pair fight, and drives grey-health consume
    timing (Rengar W, Mordekaiser W).
    """

    outgoing: defaultdict[str, list[dict[str, Any]]]
    incoming: defaultdict[str, list[dict[str, Any]]]
    healing: defaultdict[str, list[dict[str, Any]]]
    support_effects: defaultdict[str, list[dict[str, Any]]]
    item_denial_receipts: list[dict[str, Any]]
    breakdown: defaultdict[str, dict[str, Any]]
    coverage_reports: list[dict[str, Any]]
    main_cast_timeline: list[dict[str, Any]]

    @classmethod
    def empty(cls) -> Ledgers:
        """One pass's books, before any pair fight is folded in."""
        return cls(
            defaultdict(list),
            defaultdict(list),
            defaultdict(list),
            defaultdict(list),
            [],
            defaultdict(
                lambda: {
                    "participant_id": "",
                    "team": "",
                    "champion": "",
                    "total_damage": 0.0,
                    "sources": {},
                }
            ),
            [],
            [],
        )

    def scene(self, all_actors: list[Combatant]) -> TimelineScene:
        """The three books a scheduler authors into, with their roster."""
        return TimelineScene(
            all_actors, self.incoming, self.outgoing, self.support_effects
        )


class GreySubject(NamedTuple):
    """The main champion one grey-health pool is banked and repaid for.

    Grey health reads five facts off the request and one off the roster, and
    nothing else, which is what keeps its module clear of the composition's
    own record.
    """

    name: str
    champion_data: Mapping[str, Any]
    level: int
    stats: Mapping[str, float]
    params: FightParams
    enemy_count: int


class Walked(NamedTuple):
    """What the survival walk hands the published receipt."""

    program: Program
    result: WalkResult
    survival: dict[str, Any]
    public_breakdown: list[dict[str, Any]]
    support_by_attacker: Mapping[str, float]
