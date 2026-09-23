"""What the 96-field ``SurvivalAction`` costs: the numbers ``benchmarks.md`` holds.

Every input is a real action read from a named golden scenario's walk, so a
row prices values the engine produced rather than a hand-typed tuple.  Three
tables: construction per ``ActionKind`` group, the fast damage constructor
against the keyword call it replaces, and the walk itself per scenario.

Usage:
    python scripts/bench_survival_action.py                          # tables
    python scripts/bench_survival_action.py --compare benchmarks.md  # non-zero on a regression
"""

from __future__ import annotations

import argparse
import inspect
import statistics
import subprocess
import sys
import time
import timeit
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, NamedTuple
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.golden_snapshot import COUPLED_SCENARIOS
from src.calculator.calculate import calculate_payload
from src.calculator.program import walk as walk_module
from src.calculator.survival.action_families import WideAction
from src.calculator.survival.actions import compiled_damage_action
from src.calculator.survival.typed_action import ActionKind, SurvivalAction

REPEATS = 15
NUMBER = 20_000
WALK_REPEATS = 50

#: The split's target groups; every kind maps to one, so a new kind raises here.
GROUPS = {
    "damage": ("PLAIN_DAMAGE", "DAMAGE", "EXECUTE", "DEFER", "REDIRECT"),
    "heal": ("HEAL", "OVERHEAL_SHIELD", "ICHOR_CONVERT"),
    "shield": ("SHIELD", "TEMP_HEALTH"),
    "buff": ("STAT_BUFF", "DAMAGE_MODIFIER", "ON_HIT_MAGIC"),
    "state": (
        "REVIVE",
        "STASIS",
        "INVULNERABLE",
        "UNTARGETABLE",
        "SPELL_SHIELD",
        "CROWD_CONTROL",
        "CROWD_CONTROL_RESIST",
    ),
    "utility": ("UTILITY",),
}
GROUP_OF = {
    ActionKind[kind]: group for group, kinds in GROUPS.items() for kind in kinds
}

#: ``(group, golden scenario its representative is read from)``.  No golden
#: scenario walks a utility action, so that group has no row.
CONSTRUCTION_INPUTS = (
    ("damage", "crit_onhit_carry_roster"),
    ("heal", "cleaver_bloodsong_roster"),
    ("shield", "lethality_window_assassin_roster"),
    ("buff", "cleaver_bloodsong_roster"),
    ("state", "control_event_roster"),
)

#: Damage and ichor heals, damage-modifier buffs and heals, the most shields.
WALK_SCENARIOS = (
    "crit_onhit_carry_roster",
    "cleaver_bloodsong_roster",
    "lethality_window_assassin_roster",
)

CONSTRUCTORS = ("row_copy", "keywords", "narrow")

TABLES = {
    "construction": (
        "group",
        "scenario",
        "set fields",
        "all-kw µs",
        "set-kw µs",
        "narrow µs",
    ),
    "constructor": ("constructor", "fields", "µs"),
    "walk": ("scenario", "actions", "walk median µs", "p10-p90 µs", "request ms"),
}
#: Which column of which table ``--compare`` reads, by row name.
MEDIAN_COLUMN = {
    **{group: ("construction", 3) for group, _ in CONSTRUCTION_INPUTS},
    **dict.fromkeys(CONSTRUCTORS, ("constructor", 2)),
    **dict.fromkeys(WALK_SCENARIOS, ("walk", 2)),
}

_GOLDEN = {scenario.name: scenario.request for scenario in COUPLED_SCENARIOS}
_DEFAULT = WideAction()
_REAL_WALK = walk_module.run_survival_walk


def walked(scenario: str) -> tuple[list[SurvivalAction], float, float]:
    """One request's walked actions, its walk seconds and its request seconds."""
    actions: list[SurvivalAction] = []
    walk_seconds: list[float] = []

    def timed(walk_actions: list[SurvivalAction], ctx: Any) -> None:
        started = time.perf_counter()
        _REAL_WALK(walk_actions, ctx)
        walk_seconds.append(time.perf_counter() - started)
        actions.extend(walk_actions)

    with patch.object(walk_module, "run_survival_walk", timed):
        started = time.perf_counter()
        calculate_payload(_GOLDEN[scenario], deterministic=True)
        request_seconds = time.perf_counter() - started
    if not walk_seconds:
        raise RuntimeError(f"{scenario} ran no survival walk")
    return actions, sum(walk_seconds), request_seconds


def set_fields(action: SurvivalAction) -> dict[str, Any]:
    """The fields this action holds away from the class default."""
    return {
        name: value
        for name, value, default in zip(action._fields, action, _DEFAULT, strict=True)
        if value is not default and value != default
    }


def representative(actions: Sequence[SurvivalAction], group: str) -> SurvivalAction:
    """The group's first action at its median set-field count."""
    members = [action for action in actions if GROUP_OF[action.kind] == group]
    if not members:
        raise RuntimeError(f"no {group} action in the pinned walk")
    width = statistics.median_low(len(set_fields(action)) for action in members)
    return next(action for action in members if len(set_fields(action)) == width)


def narrow_type(fields: Mapping[str, Any]) -> type:
    """A NamedTuple over only these fields."""
    return NamedTuple("NarrowAction", [(name, Any) for name in fields])


def per_call_us(
    call: Callable[..., object],
    args: Sequence[object],
    kwargs: Mapping[str, object],
    *,
    repeats: int,
    number: int,
) -> float:
    """Median over ``repeats`` of ``number`` calls, in µs per call."""
    readings = timeit.repeat(
        "call(*args, **kwargs)",
        globals={"call": call, "args": tuple(args), "kwargs": dict(kwargs)},
        repeat=repeats,
        number=number,
    )
    return round(statistics.median(readings) / number * 1e6, 3)


def construction_row(
    group: str, scenario: str, action: SurvivalAction, *, repeats: int, number: int
) -> dict[str, Any]:
    """One group's action built wide by every keyword, wide by its set ones, and narrow."""
    held = set_fields(action)
    timing = {"repeats": repeats, "number": number}
    return {
        "group": group,
        "scenario": scenario,
        "set fields": len(held),
        "all-kw µs": per_call_us(WideAction, (), action._asdict(), **timing),
        "set-kw µs": per_call_us(WideAction, (), held, **timing),
        "narrow µs": per_call_us(narrow_type(held), (), held, **timing),
    }


def constructor_rows(
    action: SurvivalAction, *, repeats: int, number: int
) -> list[dict[str, Any]]:
    """The fast damage constructor against the keyword call it states it equals."""
    parameters = inspect.signature(compiled_damage_action).parameters.values()
    positional = [
        getattr(action, p.name) for p in parameters if p.kind is p.POSITIONAL_OR_KEYWORD
    ]
    keywords = {
        p.name: getattr(action, p.name) for p in parameters if p.kind is p.KEYWORD_ONLY
    }
    every = {p.name: getattr(action, p.name) for p in parameters}
    if compiled_damage_action(*positional, **keywords) != WideAction(**every):
        raise RuntimeError("compiled_damage_action no longer builds the keyword tuple")
    timing = {"repeats": repeats, "number": number}
    readings = (
        (compiled_damage_action, positional, keywords),
        (WideAction, (), every),
        (narrow_type(every), (), every),
    )
    return [
        {
            "constructor": name,
            "fields": len(every),
            "µs": per_call_us(call, args, kwargs, **timing),
        }
        for name, (call, args, kwargs) in zip(CONSTRUCTORS, readings, strict=True)
    ]


def walk_row(scenario: str, *, repeats: int) -> dict[str, Any]:
    """Median and p10-p90 spread of one scenario's walk, warm, over ``repeats`` requests."""
    walked(scenario)
    runs = [walked(scenario) for _ in range(repeats)]
    walk_us = [seconds * 1e6 for _, seconds, _ in runs]
    deciles = statistics.quantiles(walk_us, n=10, method="inclusive")
    return {
        "scenario": scenario,
        "actions": len(runs[0][0]),
        "walk median µs": round(statistics.median(walk_us)),
        "p10-p90 µs": round(deciles[8] - deciles[0]),
        "request ms": round(
            statistics.median(request * 1e3 for *_, request in runs), 2
        ),
    }


def bench(
    walk_scenarios: Sequence[str], *, repeats: int, number: int, walk_repeats: int
) -> dict[str, Any]:
    """Every table, plus the width census over the pinned walks."""
    sources = {
        scenario: walked(scenario)[0]
        for scenario in dict.fromkeys(s for _, s in CONSTRUCTION_INPUTS)
    }
    held = [set_fields(a) for actions in sources.values() for a in actions]
    damage = representative(sources[CONSTRUCTION_INPUTS[0][1]], "damage")
    return {
        "construction": [
            construction_row(
                group,
                scenario,
                representative(sources[scenario], group),
                repeats=repeats,
                number=number,
            )
            for group, scenario in CONSTRUCTION_INPUTS
        ],
        "constructor": constructor_rows(damage, repeats=repeats, number=number),
        "walk": [
            walk_row(scenario, repeats=walk_repeats) for scenario in walk_scenarios
        ],
        "census": {
            "actions": len(held),
            "median set fields": statistics.median(map(len, held)),
            "never set": len(set(WideAction._fields).difference(*held)),
        },
    }


def markdown(report: Mapping[str, Any]) -> str:
    """The committed tables' own shape, so a run pastes into ``benchmarks.md``."""
    head = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    census = report["census"]
    lines = [
        f"CPython {sys.version.split()[0]} at {head or 'unknown'}; "
        f"{len(WideAction._fields)} fields, {census['actions']} walked actions, "
        f"median {census['median set fields']} set, {census['never set']} never set",
    ]
    for table, columns in TABLES.items():
        lines += ["", "| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
        lines += [
            "| " + " | ".join(str(row[c]) for c in columns) + " |"
            for row in report[table]
        ]
    return "\n".join(lines)


def committed_medians(text: str) -> dict[str, float]:
    """``{row name: median}`` from every table row this bench owns."""
    rows = {}
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        table, column = MEDIAN_COLUMN.get(cells[0], (None, 0))
        if table and len(cells) == len(TABLES[table]):
            rows[cells[0]] = float(cells[column])
    return rows


def regressions(measured: str, committed: str, tolerance: float = 1.25) -> list[str]:
    """Rows whose median exceeds the committed one by more than 25%."""
    now, then = committed_medians(measured), committed_medians(committed)
    return [
        f"{name}: {then[name]} -> {value}"
        for name, value in now.items()
        if name in then and value > then[name] * tolerance
    ]


def main(argv: Sequence[str] | None = None) -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scenario", choices=WALK_SCENARIOS, default=None)
    parser.add_argument("--repeats", type=int, default=REPEATS)
    parser.add_argument("--number", type=int, default=NUMBER)
    parser.add_argument("--walk-repeats", type=int, default=WALK_REPEATS)
    parser.add_argument(
        "--compare", default=None, help="fail if a median regressed vs benchmarks.md"
    )
    args = parser.parse_args(argv)

    selected = tuple(name for name in WALK_SCENARIOS if args.scenario in (None, name))
    table = markdown(
        bench(
            selected,
            repeats=args.repeats,
            number=args.number,
            walk_repeats=args.walk_repeats,
        )
    )
    print(table)
    if args.compare:
        slower = regressions(table, Path(args.compare).read_text(encoding="utf-8"))
        for failure in slower:
            print(f"REGRESSION: {failure}", file=sys.stderr)
        if slower:
            sys.exit(1)


if __name__ == "__main__":
    main()
