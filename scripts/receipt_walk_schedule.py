"""Counter 4's fourteen receipt-walk deferrals, sized as slices.

Umbrella criterion 7 is partially discharged, and Amendment F says why in
terms: the fourteen ``(family, RECEIPT_WALK)`` rows defer to a stage that
shipped without retiring them, the act that actually retires one is a
per-family receipt-walk interpreter, and *"retiring it is fourteen slices, one
per family, each carrying its own ``Expected qualifying occurrences`` line"*.
Fourteen slices nobody had sized is what "unbudgeted" means.  Sizing them is
the one part of that work a lane may do before any of it starts, and R-20's
second half is explicit that it is done **before** a slice's first ``src/``
edit: where an occurrence count is not knowable in advance, the slice declares
the *population* instead, enumerated from committed artifacts -- the baseline
files, the scenario set, the registries.

So this file is fourteen declared populations, every field derived:

* the family's declarations and their owners, read from the behaviour catalog;
* which committed coupled scenarios put one of those owners on a participant,
  read from the scenario set;
* the size of each such scenario's committed roster snapshot, which is the
  conservative bound a retiring slice's occurrences live inside -- pricing a
  family in the walk instead of consuming another engine's rows can move any
  aggregate downstream of it in that scenario, so the scenario subtree is the
  honest population and a narrower one would be a guess;
* and the retiring act, derived from the row's **own declared route** rather
  than assumed uniform.

That last one is where the measurement disagreed with the prose, and the
disagreement is now ruled rather than merely recorded.  Amendment F describes
all fourteen as *"the families whose numbers ``participant_timeline._pair_run_fight``
produces today"*.  Eleven of them declare that route.  Three route through the
defence resolver and their rows say in their own words that a walk-lane
interpreter there *"would be a second producer of one number"* -- which is what
D-60 forbids, so Amendment F's act, spelled with the receipt walk, named for
those three the act criterion 8 rules out.  **Amendment K (2026-08-15)
corrects the spelling rather than the act:** the retiring act is a per-family
interpreter in the family's *own declared serving lane*, whichever lane the
row's ``via`` names, discharging criterion 8's own property -- the family's
numbers reach the walk through exactly one interpreter instead of arriving
already priced by the pair engine.  So this file derives each row's act from
its route, and every row has a settled one.  ``delta_amp``, which declares the
pair engine in its structured route while its prose names a second one, is
answered by the same sentence: the declaration is the route (D-40), so its act
is the receipt-walk one, and the prose mismatch is recorded beside it as a
behaviour claim owing its own slice rather than a schedule's edit.

**What this file is not.**  It is not a retirement, and no row here retires
anything -- the deferrals stand, ``overdue`` and gated, exactly as
Amendment F leaves them.  It does not re-date a row, re-scope the debt, or
read the debt as smaller: fourteen rows in, fourteen slices out.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

# pylint: disable=wrong-import-position,wrong-import-order
import golden_snapshot  # noqa: E402
from calculator.item_behavior_catalog import behavior_rules, rule_owners  # noqa: E402

RECEIPTS_DIR = REPO_ROOT / "docs" / "receipts"
SCHEDULE_PATH = RECEIPTS_DIR / "receipt-walk-retirement-schedule.json"
FRONTIER_PATH = REPO_ROOT / "docs" / "behavior-frontier.json"
COUPLED_BASELINE_PATH = REPO_ROOT / "scripts" / "golden_coupled_baseline.json"
INTERPRETERS_DIR = REPO_ROOT / "src" / "calculator" / "interpreters"

#: The lane whose deferrals this file sizes.  The compiled-score-walk gaps are
#: a different lane with a different blocker (H5) and are deliberately not here.
LANE = "receipt_walk"

#: The ruling that spells the retiring act per lane rather than per walk, and
#: so gives a row whose declared route is not the pair engine a settled act.
#: It was owed and is answered; the id stays here because every row's act
#: cites it, and a citation nobody can resolve is the thing this file avoids.
RULING = "what_retires_a_receipt_walk_deferral_whose_route_is_not_the_pair_engine"

#: The lane whose interpreter Amendment F named, and the only lane the eleven
#: pair-engine-fed rows are retired by.
PAIR_ENGINE = "pair_engine"


class ScheduleError(RuntimeError):
    """The schedule does not say what the tree says."""


def _frontier() -> Mapping[str, Any]:
    return json.loads(FRONTIER_PATH.read_text(encoding="utf-8"))


def deferral_rows() -> dict[str, Mapping[str, Any]]:
    """The committed ``(family, receipt_walk)`` deferral rows, by family.

    The row and its unserved-lane receipt are two halves of one record in the
    frontier -- the row carries the overdue flag and the blocker, the receipt
    carries ``via``, the declared route the number arrives by -- so they are
    joined here rather than one being read without the other.
    """
    counter = _frontier()["counters"]["counter_4"]
    rows = counter["deferrals"]["rows"]
    dated = counter["receipts"]["dated"]
    out: dict[str, Mapping[str, Any]] = {}
    for key, row in rows.items():
        family, _, lane = key.partition("/")
        if lane != LANE:
            continue
        receipt = dated.get(key)
        if receipt is None:
            raise ScheduleError(
                f"deferral row {key!r} has no unserved-lane receipt, so its "
                "declared route cannot be read; the schedule refuses to guess "
                "which engine a family's number arrives by"
            )
        out[family] = {**row, "via": list(receipt["via"])}
    if not out:
        raise ScheduleError(
            "the frontier records no receipt-walk deferral rows; a schedule "
            "for a debt the tree no longer carries would be a plan for nothing"
        )
    return out


def owners_by_family() -> dict[str, dict[str, list[str]]]:
    """Every declared rule, grouped by family and then by owner."""
    grouped: dict[str, dict[str, list[str]]] = {}
    for owner in sorted(rule_owners()):
        for rule in behavior_rules(owner):
            grouped.setdefault(rule.family.value, {}).setdefault(owner, []).append(
                rule.mechanic_id
            )
    return grouped


def population_size(node: Any) -> int:
    """How many numbers a committed snapshot subtree holds.

    The bound, not the prediction.  A slice that moves a family's pricing into
    the walk may move any aggregate downstream of it, so the population is the
    whole scenario and anything outside it is an unexpected occurrence that
    stops the slice -- which is what R-20's second half asks a population to do.
    """
    if isinstance(node, Mapping):
        return sum(population_size(value) for value in node.values())
    if isinstance(node, (list, tuple)):
        return sum(population_size(value) for value in node)
    if isinstance(node, bool):
        return 0
    return 1 if isinstance(node, (int, float)) else 0


def _retiring_act(route: Sequence[str]) -> dict[str, Any]:
    """What retires this row, read off its own declared route.

    Amendment F names one act for all fourteen and spells it with one lane,
    which is true of the eleven the pair engine feeds and names, for the rest,
    the second producer D-60 forbids.  Amendment K rules the act per lane
    instead: a per-family interpreter in the lane the row itself declares.
    The act is derived from ``via`` rather than assumed, so a row that
    re-declares its route re-derives its act on the same commit.
    """
    if tuple(route) == (PAIR_ENGINE,):
        return {
            "act": (
                "A receipt-walk interpreter for this family: the walk prices it "
                "itself instead of consuming the pair engine's timed rows that "
                "participant_timeline._pair_run_fight produces. This is "
                "Amendment F's named act and it describes this row as written."
            ),
            "retiring_lane": [LANE],
            "settled": True,
            "ruled_by": RULING,
        }
    return {
        "act": (
            "A per-family interpreter in this family's own declared serving "
            "lane -- " + ", ".join(route) + " -- so that the family's numbers "
            "reach the walk through exactly one interpreter instead of "
            "arriving already priced by the pair engine. That is umbrella "
            "criterion 8's property, which is why the act serves D-60 rather "
            "than colliding with it: the lane's interpreter is not a second "
            "producer of one number, it is the one producer, and the walk "
            "consumes what it built. Amendment K rules this act for every row, "
            "correcting the lane Amendment F spelled it with and neither "
            "narrowing nor widening the debt."
        ),
        "retiring_lane": list(route),
        "settled": True,
        "ruled_by": RULING,
    }


def schedule() -> dict[str, Any]:
    """The whole artifact, derived."""
    rows = deferral_rows()
    declarations = owners_by_family()
    baseline = json.loads(COUPLED_BASELINE_PATH.read_text(encoding="utf-8"))[
        "coupled_scenarios"
    ]
    equipped = {
        scenario.name: scenario.equipped()
        for scenario in golden_snapshot.COUPLED_SCENARIOS
    }
    slices: dict[str, Any] = {}
    for family, row in sorted(rows.items()):
        owned = declarations.get(family, {})
        covering = sorted(
            name
            for name, items in equipped.items()
            if items & set(owned) and name in baseline
        )
        sizes = {name: population_size(baseline[name]) for name in covering}
        total = sum(sizes.values())
        route = list(row["via"])
        slices[family] = {
            "interpreter_module": (INTERPRETERS_DIR / f"{family}.py")
            .relative_to(REPO_ROOT)
            .as_posix(),
            "deferral_row": f"{family}/{LANE}",
            "route_today": route,
            "retiring_act": _retiring_act(route),
            "declared_rules": sorted(
                mechanic for ids in owned.values() for mechanic in ids
            ),
            "owners": sorted(owned),
            "covering_coupled_scenarios": covering,
            "population_by_scenario": sizes,
            "population_total": total,
            "coupled_baseline_is_blind_to_this_family": not covering,
            "expected_qualifying_occurrences": (
                f"Expected qualifying occurrences: bounded by the enumerated "
                f"population of {total} committed roster values across "
                f"{len(covering)} coupled scenario(s) -- "
                + ", ".join(f"{name} {size}" for name, size in sorted(sizes.items()))
                if covering
                else (
                    "Expected qualifying occurrences: 0 on the coupled baseline, "
                    "which holds no scenario putting one of this family's owners "
                    "on a participant. That is a declared emptiness and not a "
                    "clean bill: the retiring slice has no roster-path signal at "
                    "all, so it owes a covering scenario or a non-golden numeric "
                    "gate of its own before it may claim anything (D-93, R-11)."
                )
            ),
        }
    lane_corrected = sorted(
        family
        for family, entry in slices.items()
        if tuple(entry["route_today"]) != (PAIR_ENGINE,)
    )
    blind = [
        family
        for family, entry in slices.items()
        if entry["coupled_baseline_is_blind_to_this_family"]
    ]
    return {
        "artifact": "receipt_walk_retirement_schedule",
        "rule": (
            "Umbrella criterion 7's fourteen receipt-walk deferrals, sized as "
            "the fourteen slices Amendment F says they are. One row per "
            "family: its declarations and their owners, the committed coupled "
            "scenarios that put one of those owners on a participant, the size "
            "of each such scenario's committed snapshot, and the "
            "Expected qualifying occurrences line R-20's second half requires a "
            "slice to declare BEFORE its first src/ edit."
        ),
        "gate": "tests/test_receipt_walk_schedule.py",
        "what_this_is_not": (
            "It is not a retirement and no row here retires anything: the "
            "deferrals stand, overdue and gated, exactly as Amendment F leaves "
            "them. It does not re-date a row, re-scope the debt or read it as "
            "smaller -- fourteen rows in, fourteen slices out -- and it "
            "registers no interpreter, because an interpreter registered to "
            "move a counter without changing what the walk prices is a counter "
            "driven to zero by editing what it counts."
        ),
        "why_a_lane_may_write_this": (
            "R-20's second half makes enumerating a qualifying population a "
            "pre-edit act, performed from committed artifacts. Every field here "
            "is read from the committed frontier, the behaviour catalog, the "
            "committed coupled scenario set or the committed coupled baseline. "
            "Nothing here decides what a slice should do; it says how big each "
            "one is, which is what 'unbudgeted' was the absence of."
        ),
        "where_the_measurement_disagreed_with_the_prose_and_what_ruled_it": (
            "Amendment F describes all fourteen rows as the families whose "
            "numbers participant_timeline._pair_run_fight produces today. "
            "Eleven declare that route in their own via field. Three -- "
            + ", ".join(lane_corrected)
            + " -- declare the defence resolver instead, and their rows say in "
            "their own words that a walk-lane interpreter there would be a "
            "second producer of one number, which is what D-60 and umbrella "
            "criterion 8 forbid. So Amendment F's act, spelled with the receipt "
            "walk, named for those three the act the campaign's own criterion "
            "rules out. That was measured here and routed to an owed ruling, "
            "which answered it on 2026-08-15: umbrella Amendment K rules the "
            "retiring act per LANE rather than per walk -- a per-family "
            "interpreter in the family's own declared serving lane, whichever "
            "lane the row's via names -- discharging criterion 8's own property "
            "that the family's numbers reach the walk through exactly one "
            "interpreter instead of arriving already priced by the pair engine. "
            "Every row therefore has a settled act, derived from its own route "
            "rather than assumed uniform, and the three moves a lane may still "
            "not make are unchanged in force: registering an interpreter that "
            "changes nothing the walk prices, editing the lane table so a family "
            "stops owing the walk an answer, and reading fourteen as eleven."
        ),
        "a_second_and_smaller_mismatch": (
            "delta_amp/receipt_walk declares via = ['pair_engine'], so it is "
            "counted above as taking Amendment F's act as written, while its "
            "own reason names two routes -- 'a holder-side amp reaches it "
            "already priced inside the pair engine's damage rows, and a "
            "cross-participant one as the damage_modifier packet "
            "item_support_effects emits, which survival/transitions stages as "
            "an ActionKind.DAMAGE_MODIFIER' -- and says neither of them is the "
            "rule. The structured route and the prose beside it therefore "
            "describe different things, and only the structured one is gated. "
            "Amendment K answers it in the same sentence as the three: the "
            "declaration is the route (D-40), so this row's act is the "
            "receipt-walk one, and correcting via would be a behaviour claim "
            "owing its own slice rather than a schedule's edit. It stays "
            "recorded here because a prose sentence that disagrees with a gated "
            "declaration is a thing a reader should be able to find."
        ),
        "scheduled_slices": len(slices),
        "slices_whose_retiring_act_is_amendment_f_as_written": len(slices)
        - len(lane_corrected),
        "slices_whose_retiring_lane_amendment_k_corrects": list(lane_corrected),
        "families_with_no_covering_coupled_scenario": sorted(blind),
        "families": slices,
    }


def check(committed: Mapping[str, Any] | None = None) -> list[str]:
    """Every way the committed schedule can stop being true of the tree.

    ``committed`` is R-05's seam, so the gate has a red it can reproduce on
    demand rather than one demonstrated once during development.
    """
    if committed is None:
        if not SCHEDULE_PATH.exists():
            return [f"{SCHEDULE_PATH.name} is not committed; run --write"]
        committed = json.loads(SCHEDULE_PATH.read_text(encoding="utf-8"))
    fresh = schedule()
    failures: list[str] = []
    if set(committed.get("families", {})) != set(fresh["families"]):
        failures.append(
            "the schedule covers a different set of families than the "
            "frontier's receipt-walk deferral rows; a scheduled slice that "
            "outlives its deferral, or a deferral with no scheduled slice, is "
            "the debt going unread under a file that says it is sized"
        )
    for family, entry in fresh["families"].items():
        if committed.get("families", {}).get(family) != entry:
            failures.append(f"family {family!r}: committed row differs from derived")
    for key in (
        "scheduled_slices",
        "slices_whose_retiring_lane_amendment_k_corrects",
    ):
        if committed.get(key) != fresh[key]:
            failures.append(f"{key}: committed value differs from derived")
    return failures


def main(argv: Sequence[str] | None = None) -> int:
    """``--write`` regenerates the receipt; ``--check`` gates it."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="regenerate the receipt")
    parser.add_argument("--check", action="store_true", help="fail on any drift")
    args = parser.parse_args(argv)
    if args.write:
        SCHEDULE_PATH.write_text(
            json.dumps(schedule(), indent=1, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"wrote {SCHEDULE_PATH.relative_to(REPO_ROOT).as_posix()}")
        return 0
    failures = check()
    for failure in failures:
        print(failure)
    return 1 if failures else 0


if __name__ == "__main__":  # pragma: no cover - CLI
    sys.exit(main())
