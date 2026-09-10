"""The coverage words a champion module declares, and the contract they read into."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any, NamedTuple

from ..cast_dependency import CastDependency
from ..stat_conversion import BonusHealthConversion

REQUIRED_CHAMPION_SLOTS = ("P", "Q", "W", "E", "R")


VALID_COVERAGE = frozenset({"modeled", "no_damage", "out_of_scope"})


REVIEW_STATUS = "reviewed_module"


#: Engine channels that price a slot whose own parsed row does not.  A
#: passive with no cast still reaches the fight: a revive resolves through
#: ``defensive_effects.resolve_starting_defenses``, a shield rides another
#: slot's damage event as a ``self_shield_events`` payload, and lifesteal
#: or a cast heal is authored by the champion's ``healing.py`` rule.  A
#: module claiming ``modeled`` for such a slot names the channel here so
#: the claim resolves to a receipt instead of to prose.
COVERAGE_CHANNELS = frozenset(
    {
        "starting_revive_defense",
        "self_shield_events",
        "self_healing_rule",
        # A passive priced as its own breakdown row by another slot's
        # ``post_hit_proc`` (Kai'Sa's Plasma rides W in one-rotation, R in
        # timed): the row is published under the passive's name.
        "post_hit_proc",
    }
)


# Facts with one home outside the module: the review status is this
# contract's, and the packet spec rides the parser ``build_packet_module``
# returns.  A module restating either is a second home that can disagree
# with the first, so the restatement is refused rather than surveyed.
_RESTATED_FACTS = ("REVIEW_STATUS", "PACKET_SPEC")


def default_coverage(slots: Mapping[str, Any]) -> dict[str, str]:
    """The five-slot coverage ``SLOTS`` implies: an emitted slot is
    ``modeled``, an unemitted one ``out_of_scope``.  Any other reading is
    the module's own, stated through ``MODULE_COVERAGE``.
    """
    return {
        slot: ("modeled" if slot in slots else "out_of_scope")
        for slot in REQUIRED_CHAMPION_SLOTS
    }


class ChampionModuleContractError(ValueError):
    """A registered champion module does not publish a valid contract."""


def coverage(*, no_damage: str = "", out_of_scope: str = "") -> dict[str, str]:
    """A module's own five-slot reading, named by exception.

    ``modeled`` is what a registered module claims for a slot unless it says
    otherwise, so a declaration states only the slots it reads differently:
    ``coverage(no_damage="PW")`` is a kit whose passive and W price nothing
    the enemy takes, and everything else modelled.
    """
    named = no_damage + out_of_scope
    unknown = sorted(set(named) - set(REQUIRED_CHAMPION_SLOTS))
    if unknown:
        raise ChampionModuleContractError(
            f"coverage() named {unknown}, which are not champion slots"
        )
    if len(set(named)) != len(named):
        raise ChampionModuleContractError(
            "coverage() named one slot twice: "
            f"no_damage={no_damage!r} out_of_scope={out_of_scope!r}"
        )
    stated = dict.fromkeys(no_damage, "no_damage")
    stated.update(dict.fromkeys(out_of_scope, "out_of_scope"))
    return {slot: stated.get(slot, "modeled") for slot in REQUIRED_CHAMPION_SLOTS}


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
    coverage_channels: dict[str, tuple[str, ...]] = field(default_factory=dict)
    review_status: str = REVIEW_STATUS
    packet_spec: dict[str, Any] | None = None
    packet_sha256: str | None = None
    cast_dependencies: tuple[CastDependency, ...] = ()
    cc_kinds: dict[str, str] = field(default_factory=dict)
    ultimate_recasts: bool = False
    stat_conversion: BonusHealthConversion | None = None


class DeclarationSites(NamedTuple):
    """The three places a champion module may declare a contract fact on: the
    module itself, the ``parse_abilities`` it publishes, and its slot map.
    """

    module: ModuleType
    parser: Callable[..., Any]
    slots: dict[str, Any]
