"""The property sweep: rules every fight obeys, over every champion and random legal builds.

No property needs a reference number, so the sweep reaches the champion x
item combinations no hand-written test pins: a longer fight never deals less,
more armour or magic resistance never deals more, a stat item never lowers
damage, a traced fight's packets sum to its total, a fight that clips at its
end lands nothing after it, and a legal build never raises.  A violation not on
``ACKNOWLEDGED`` with its reason fails the gate, and
``tests/test_property_sweep.py`` holds a sample of it and every acknowledgement
to a fresh run.

    python scripts/property_sweep.py                 # every champion, exit 1 on a violation
    python scripts/property_sweep.py --shard 0/4     # one CI shard
    python scripts/property_sweep.py --champions Sion Vi --builds 3
"""

from __future__ import annotations

import argparse
import random
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, NamedTuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.calculator.application_errors import ApplicationError
from src.calculator.calculate import calculate_payload
from src.calculator.champions import registered_champion_names
from src.calculator.loadout_rules import (
    conflicts_with_groups,
    occupied_groups,
    role_quest_legal_items,
)
from src.calculator.optimizer_candidates import (
    get_eligible_boots,
    get_eligible_legendaries,
)

#: One timed fight at full auto uptime that clips at its end, so every
#: property below reads the fight window alone.
BASE_REQUEST: Mapping[str, Any] = {
    "level": 18,
    "fight_mode": "timed",
    "fight_duration": 8.0,
    "include_auto_attacks": True,
    "auto_attack_uptime": 1.0,
    "target_armor": 100.0,
    "target_mr": 60.0,
    "count_damage_after_fight_end": False,
}
DURATIONS = tuple(float(seconds) for seconds in range(2, 15))
RESISTANCES = (0.0, 40.0, 80.0, 120.0, 200.0, 300.0)
#: Pure-stat components, named as ``data/items.json`` spells them.
STAT_ITEMS = ("Long Sword", "Amplifying Tome")
LEGENDARIES_PER_BUILD = 3
DEFAULT_BUILDS = 1
SEED = "property-sweep"
#: Relative slack for one total against another: float order, not damage.
TOLERANCE = 1e-9
#: Half a unit of the one decimal ``program/precision.py`` publishes a
#: fight's total at, which its unrounded packets may differ from.
TOTAL_ROUNDING = 0.05 + 1e-9

#: ``(property, champion, scenario)`` -> why the violation is the game's rule.
ACKNOWLEDGED: Mapping[tuple[str, str, str], str] = {}


class Violation(NamedTuple):
    """One property one scenario broke, with the numbers that broke it."""

    prop: str
    champion: str
    scenario: str
    detail: str

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.prop, self.champion, self.scenario)


class Scenario(NamedTuple):
    """A champion and the build it fights in."""

    champion: str
    label: str
    boots: str
    items: tuple[str, ...]


def random_builds(champion: str, count: int) -> list[tuple[str, tuple[str, ...]]]:
    """*count* legal builds for *champion*: tier-two boots and three
    legendaries no exclusivity group forbids, seeded by the champion."""
    draws = random.Random(f"{SEED}:{champion}")
    boots = sorted(item["name"] for item in get_eligible_boots(2))
    # No role is requested, so no support quest stage is legal.
    legendaries = sorted(
        item["name"]
        for item in role_quest_legal_items(get_eligible_legendaries(), "", False)
    )
    builds: list[tuple[str, tuple[str, ...]]] = []
    for _ in range(count):
        build: list[str] = []
        for name in draws.sample(legendaries, len(legendaries)):
            if len(build) == LEGENDARIES_PER_BUILD:
                break
            if not conflicts_with_groups(name, occupied_groups(build)):
                build.append(name)
        builds.append((draws.choice(boots), tuple(build)))
    return builds


def scenarios_for(champion: str, builds: int) -> list[Scenario]:
    """The champion bare, then each of its random builds."""
    return [
        Scenario(champion, "no items", "", ()),
        *(
            Scenario(champion, "build " + " + ".join((boots, *items)), boots, items)
            for boots, items in random_builds(champion, builds)
        ),
    ]


def _fight(
    scenario: Scenario,
    *,
    trace: bool = False,
    items: Sequence[str] | None = None,
    **over: Any,
) -> Mapping[str, Any]:
    request = {
        **BASE_REQUEST,
        "champion": scenario.champion,
        "boots": scenario.boots,
        "items": list(scenario.items if items is None else items),
        **over,
    }
    return calculate_payload(request, deterministic=True, trace=trace)


def _worse(before: float, after: float) -> float:
    """How far *after* falls below *before*, past float slack."""
    return before - after - TOLERANCE * max(1.0, abs(before))


def _monotone(
    scenario: Scenario,
    prop: str,
    field: str,
    values: Sequence[float],
    *,
    rising: bool,
) -> Iterable[Violation]:
    """A total that must not fall (``rising``) or rise as *field* grows."""
    totals = [_fight(scenario, **{field: value})["total_damage"] for value in values]
    for (low, before), (high, after) in zip(
        zip(values, totals), list(zip(values, totals))[1:]
    ):
        broke = _worse(before, after) > 0 if rising else _worse(after, before) > 0
        if broke:
            yield Violation(
                prop,
                scenario.champion,
                scenario.label,
                f"{field} {low:g} -> {high:g}: total {before:.4f} -> {after:.4f}",
            )


def duration_monotone(scenario: Scenario) -> Iterable[Violation]:
    """A longer fight never deals less damage."""
    return _monotone(
        scenario, "duration_monotone", "fight_duration", DURATIONS, rising=True
    )


def armor_monotone(scenario: Scenario) -> Iterable[Violation]:
    """More target armour never deals more damage."""
    return _monotone(
        scenario, "armor_monotone", "target_armor", RESISTANCES, rising=False
    )


def mr_monotone(scenario: Scenario) -> Iterable[Violation]:
    """More target magic resistance never deals more damage."""
    return _monotone(scenario, "mr_monotone", "target_mr", RESISTANCES, rising=False)


def stat_item_monotone(scenario: Scenario) -> Iterable[Violation]:
    """A pure-stat component never lowers damage."""
    before = _fight(scenario)["total_damage"]
    for item in STAT_ITEMS:
        after = _fight(scenario, items=(*scenario.items, item))["total_damage"]
        if _worse(before, after) > 0:
            yield Violation(
                "stat_item_monotone",
                scenario.champion,
                scenario.label,
                f"+{item}: total {before:.4f} -> {after:.4f}",
            )


def trace_is_the_fight(scenario: Scenario) -> Iterable[Violation]:
    """A traced fight's packets sum to its total and none lands past its end."""
    payload = _fight(scenario, trace=True)
    lines = payload["trace"]["lines"]
    total = float(payload["total_damage"])
    traced = sum(float(line["mitigated"]) for line in lines)
    if abs(traced - total) > TOTAL_ROUNDING:
        yield Violation(
            "trace_sums_to_total",
            scenario.champion,
            scenario.label,
            f"packets {traced:.6f} vs total {total:.6f}",
        )
    end = float(BASE_REQUEST["fight_duration"])
    late = [line for line in lines if float(line["time"]) > end + 1e-9]
    if late:
        yield Violation(
            "clipped_fight_lands_nothing_after_its_end",
            scenario.champion,
            scenario.label,
            f"{len(late)} packet(s), first {late[0]['source']} at {late[0]['time']:.4f}",
        )


PROPERTIES: tuple[Callable[[Scenario], Iterable[Violation]], ...] = (
    duration_monotone,
    armor_monotone,
    mr_monotone,
    stat_item_monotone,
    trace_is_the_fight,
)


def sweep_champion(champion: str, builds: int = DEFAULT_BUILDS) -> list[Violation]:
    """Every property over every scenario of one champion."""
    violations: list[Violation] = []
    for scenario in scenarios_for(champion, builds):
        for prop in PROPERTIES:
            try:
                violations.extend(prop(scenario))
            except ApplicationError:
                raise
            except Exception as exc:  # pylint: disable=broad-exception-caught
                violations.append(
                    Violation(
                        "a_legal_fight_never_raises",
                        champion,
                        scenario.label,
                        f"{prop.__name__}: {type(exc).__name__}: {exc}",
                    )
                )
    return violations


def _sweep_one(args: tuple[str, int]) -> list[Violation]:
    return sweep_champion(*args)


def sweep(
    champions: Sequence[str], builds: int = DEFAULT_BUILDS, workers: int | None = None
) -> list[Violation]:
    """Every champion's violations, one champion per worker."""
    with ProcessPoolExecutor(max_workers=workers) as pool:
        found = pool.map(_sweep_one, [(champion, builds) for champion in champions])
        return [violation for per_champion in found for violation in per_champion]


def _shard(champions: Sequence[str], spec: str | None) -> list[str]:
    if not spec:
        return list(champions)
    index, count = (int(part) for part in spec.split("/"))
    return [
        name for position, name in enumerate(champions) if position % count == index
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--champions", nargs="*", help="sweep these champions only")
    parser.add_argument("--builds", type=int, default=DEFAULT_BUILDS)
    parser.add_argument("--shard", help="K/N: sweep every Nth champion from K")
    parser.add_argument("--workers", type=int, default=None)
    args = parser.parse_args(argv)
    champions = _shard(args.champions or registered_champion_names(), args.shard)
    violations = sweep(champions, args.builds, args.workers)
    unexplained = [v for v in violations if v.key not in ACKNOWLEDGED]
    for violation in violations:
        mark = "acknowledged" if violation.key in ACKNOWLEDGED else "VIOLATION"
        print(
            f"{mark}: {violation.prop} | {violation.champion} | "
            f"{violation.scenario} | {violation.detail}"
        )
    print(
        f"{len(champions)} champion(s), {len(violations)} violation(s), "
        f"{len(unexplained)} unexplained"
    )
    return 1 if unexplained else 0


if __name__ == "__main__":
    sys.exit(main())
