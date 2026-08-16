"""Counter 4's outstanding receipt-walk deferrals, sized as slices.

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

So this file is one declared population per still-deferred family, every field
derived:

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
its route, and every row has a settled one.  What each row still publishes for
itself is whether that act has been **performed**: ``INTERPRETERS`` holds the
ruled key for the three the resolver feeds and not for the rest, which is the
one thing about an act that can be false and so the one worth a field.

``delta_amp`` was the fourteenth row and is the first to leave.  Its structured
route declared the pair engine while its prose named a second one, which
Amendment K answered without correcting -- the declaration is the route (D-40),
so the correction was a behaviour claim owing its own slice.  That slice landed
on 2026-08-15 under Amendment M, Ruling 1, which ordered this family first and
ruled its act to be the walk-side delivery of the holder's static, pair-local
amplifiers; the receipt walk now reads the family's declaration through
``interpreters.delta_amp.WALK_INTERPRETER``, the frontier stopped deferring the
row, and the row left this file with it.  The mismatch it carried is kept as
an answered record rather than deleted, because a mismatch that is only
deleted is one no reader can check was ever real.

**Every open row also carries its triage class**, which umbrella Amendment O,
Ruling 2 (2026-08-16) makes a one-time act in front of any further retirement
round.  The fifth family attempted, ``crit_profile``, stopped on a property
nobody had measured for the others: it authors no pair-engine row at all, so
Amendment L, Ruling 1's shape -- both halves of which name a pair row the
family authors -- had nothing to stamp.  Ruling 2 says that shape is measured
once, for every remaining row, rather than rediscovered one halt at a time.
So each row publishes which priced pair rows its declarations actually author,
measured by ablation over the covering population and over a per-owner probe,
and the class that follows: ``a`` authors its own rows and retires by the
ruled act; ``b`` authors none and folds pair-locally into the holder's own
rows, which Ruling 1 closes by authority reclassification; ``c`` authors none
and reaches participants through rows it does not author, which owes a named
walk-side delivery term and stops the next retirement round if it has none.

**What this file is not.**  It is not a retirement, and no row here retires
anything -- every row still standing is ``overdue`` and gated, exactly as
Amendment F leaves it.  It does not re-date a row, re-scope the debt, or read
the debt as smaller: one row out is one slice landed, never one debt
re-counted.  The triage adds no exception to that: measuring a row is not
paying it, and a class is a fact about the shape of the work rather than a
smaller amount of it.
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
from calculator import interpreters  # noqa: E402
from calculator import trigger_stream  # noqa: E402
from calculator.item_behavior import Subject  # noqa: E402
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

#: Umbrella Amendment O's two rulings, cited by every row the triage below
#: classifies and by the closure that ruling performs.
RECLASSIFICATION_RULING = "umbrella Amendment O, Ruling 1"
TRIAGE_RULING = "umbrella Amendment O, Ruling 2"

#: The families Amendment O, Ruling 1 closes off the receipt walk.  A ruling
#: names a family; every FIELD of the closed row below is derived, and
#: :func:`_reclassification_failures` refuses a name the tree does not agree
#: with -- a family still declaring the lane, or one an interpreter serves,
#: is not a family this ruling closed.  Empty while the triage that identifies
#: the class-(b) rows lands: measuring is one act and closing is another, and
#: a name added here before the lane table drops the lane would be this file
#: claiming a closure the tree denies.
RECLASSIFIED: tuple[str, ...] = ()

#: Two probe champions, one ranged and one melee, because several declarations
#: split on range (``MeleeRangedSplit``) and a family measured on one of them
#: is measured on half its own rules.  They are a fixture and not a
#: population: the population is the covering scenario set, enumerated per
#: family above, and these probes only widen the *domain* the zero is claimed
#: over so that an owner no covering scenario equips is still measured.
PROBE_CHAMPIONS: tuple[str, str] = ("Caitlyn", "Darius")

#: The probe fight: level 18, autos at full uptime and not one rotation, so
#: on-hit, charge, spellblade and periodic paths all run.  A row a family
#: authors only in a longer fight would otherwise read as a row it authors
#: nowhere.
PROBE_LEVEL = 18


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


def registered_lanes(family: str) -> set[str]:
    """The lanes ``INTERPRETERS`` already holds an interpreter of *family* in.

    Read from the registry rather than from a list here: whether a family's
    ruled retiring act has been performed is a fact about the tree, and the
    one place it is written is the registration table itself.
    """
    return {
        lane.value
        for declared, lane in interpreters.INTERPRETERS
        if declared.value == family
    }


def priced_rows(result: Mapping[str, Any]) -> frozenset[str]:
    """The breakdown rows a fight's own ``total_damage`` holds.

    This is the predicate umbrella Amendment O, Ruling 1 turns on, and it is
    exact rather than a heuristic: summing ``total_damage`` over the rows this
    returns reproduces the fight's ``total_damage`` to the last bit, which
    :mod:`tests.test_receipt_walk_schedule` asserts rather than assumes.  Two
    kinds of row are outside it and both are outside it for the ruling's own
    stated reason.  A row carrying ``informational`` publishes a *difference*
    a priced row already holds and is summed into no total -- Sundered Sky's
    forced crit and The Collector's execute are both that shape.  A row with
    no ``total_damage`` at all is not damage: the heal rows carry
    ``total_amount`` and a ``unit``.  A family whose only rows are those two
    kinds authors nothing a roster total holds, which is what "authors no pair
    row" means.
    """
    return frozenset(
        key
        for key, entry in (result.get("breakdown") or {}).items()
        if isinstance(entry, Mapping)
        and not entry.get("informational")
        and entry.get("total_damage") is not None
    )


def _stripped(request: Mapping[str, Any], owners: frozenset[str]) -> dict[str, Any]:
    """*request* with every one of *owners* off every participant.

    The ablation removes the ITEM, so it removes the mechanic and the item's
    stat line together.  That makes the instrument conservative in the one
    direction that matters: a row that survives the removal is not this
    family's, and a family measured to author no row is one whose whole item
    removal authors none -- strictly stronger than its mechanic authoring
    none, and never weaker.
    """
    out = json.loads(json.dumps(dict(request)))
    for loadout in (out, *out.get("allies", ()), *out.get("enemies", ())):
        if "items" in loadout:
            loadout["items"] = [name for name in loadout["items"] if name not in owners]
        if loadout.get("boots") in owners:
            loadout.pop("boots")
        options = loadout.get("item_options")
        if isinstance(options, Mapping):
            loadout["item_options"] = {
                name: value for name, value in options.items() if name not in owners
            }
    return out


def _scenario_rows(request: Mapping[str, Any]) -> tuple[frozenset[str], ...]:
    """The priced rows of every pair fight one coupled scenario request runs.

    The same entry ``golden_snapshot.coupled_entry`` takes, run for its pair
    fights alone: this measures what the PAIR ENGINE authors, which is the
    engine the reclassification is about.
    """
    parsed = golden_snapshot.parse_scenario_request(dict(request), deterministic=True)
    resolved = golden_snapshot.resolve_scenario(parsed)
    if not resolved.enemies:
        runs = [resolved.fight_params]
    else:
        runs = list(resolved.target_fight_params)
    return tuple(
        priced_rows(
            golden_snapshot.run_fight(
                resolved.champion_data, parsed.level, list(resolved.items), params
            )
        )
        for params in runs
    )


def _probe_rows(champion: str, items: Sequence[str]) -> frozenset[str]:
    """The priced rows one probe champion authors holding *items*."""
    champions = golden_snapshot.fetch_champion_data()
    by_name = {
        data["name"]: data for data in golden_snapshot.fetch_item_data().values()
    }
    return priced_rows(
        golden_snapshot._run_fight(  # pylint: disable=protected-access
            champions[champion],
            PROBE_LEVEL,
            [by_name[name] for name in items],
            auto_attack_uptime=1.0,
            one_rotation=False,
        )
    )


def authored_rows(
    family: str, owners: Sequence[str], covering: Sequence[str]
) -> tuple[str, ...]:
    """Which priced pair-engine rows *family*'s declarations author.

    Ablation, over two domains, and the union of what both find.

    The first is the **covering population** umbrella Amendment O, Ruling 1
    names: every committed coupled scenario putting one of this family's
    owners on a participant, run pair fight by pair fight with the family's
    items on and off.  A row present with them and absent without them is a
    row this family authors.

    The second is one probe per owner, on a ranged and a melee champion, and
    it is what makes the zero a claim about the FAMILY rather than about the
    scenarios that happen to hold it.  Two of ``crit_profile``'s three owners
    are equipped by no covering scenario; without the probes, a mechanic of
    theirs that authored a row would be invisible to the check that is
    supposed to reopen the closed row when one does.
    """
    held = frozenset(owners)
    found: set[str] = set()
    by_name = {
        scenario.name: scenario for scenario in golden_snapshot.COUPLED_SCENARIOS
    }
    for name in covering:
        scenario = by_name[name]
        with_them = _scenario_rows(scenario.request)
        without = _scenario_rows(_stripped(scenario.request, held))
        for full, ablated in zip(with_them, without):
            found |= full - ablated
    for champion in PROBE_CHAMPIONS:
        bare = _probe_rows(champion, ())
        for owner in owners:
            found |= _probe_rows(champion, (owner,)) - bare
    return tuple(sorted(found))


def _subjects(family: str, owners: Sequence[str]) -> tuple[str, ...]:
    """Each declaration's declared ``Subject``, or ``undeclared`` for none.

    The umbrella's semantic-authority rule decides authority by what a rule's
    inputs and effects reach, and the catalog already declares that per
    payload.  ``Subject.HOLDER`` is a pair-local fold into the holder's own
    rows; ``Subject.TARGET`` lands on a shared defender every roster
    participant meets; a payload declaring no subject at all writes
    ``DefenseField``s the defence resolver owns, and the subject's live state
    under combined fire is a roster input by that rule's own words.  So this
    is read rather than judged.
    """
    return tuple(
        sorted(
            (
                rule.payload.subject.value
                if isinstance(getattr(rule.payload, "subject", None), Subject)
                else "undeclared"
            )
            for owner in owners
            for rule in behavior_rules(owner)
            if rule.family.value == family
        )
    )


def _cross_participant_halves(owners: Sequence[str]) -> dict[str, list[str]]:
    """Each owner's declared halves that modify ANOTHER participant's damage.

    Read through ``trigger_stream.cross_participant_packet_source``, which is
    D-07's semantic with one home (Amendment C, extended by Amendment M,
    Ruling 3), so "this family's roster numbers already have a named walk-side
    delivery" is answered by the same function the producer set is filtered
    with rather than by a second reading of it.
    """
    halves: dict[str, list[str]] = {}
    for owner in owners:
        named = []
        for rule in behavior_rules(owner):
            capability = trigger_stream.CAPABILITIES.get(rule.mechanic_id)
            if capability is None:
                continue
            source = trigger_stream.cross_participant_packet_source(capability)
            if source is not None:
                named.append(f"{rule.mechanic_id} -> {source}")
        halves[owner] = sorted(named)
    return halves


def _delivery_term(
    family: str, owners: Sequence[str], act: Mapping[str, Any]
) -> dict[str, Any]:
    """Whether a class-(c) row's walk-side delivery term is named, and where.

    Amendment O, Ruling 2 requires one before such a row may retire, and
    forbids a lane from inventing one.  Two shapes count as named and both are
    read from the tree.  The row's own ruled retiring act may already be
    performed -- ``INTERPRETERS`` holding the key for the lane the row
    declares is Amendment K's delivery, standing in the tree today.  Or every
    declaring owner may carry a cross-participant half the walk already
    stages, which is the SPLIT shape: the shred's roster number reaches the
    walk as the ``damage_modifier`` packet its own coupled half emits.
    Neither present is a row that STOPS the next retirement round, named here
    rather than papered over.
    """
    if act["already_performed"]:
        return {
            "named": True,
            "where": (
                "interpreters.INTERPRETERS holds the ("
                + family
                + ", "
                + ", ".join(act["retiring_lane"])
                + ") key, which is the delivery umbrella Amendment K rules for "
                "this row and it stands in the tree today"
            ),
        }
    halves = _cross_participant_halves(owners)
    if halves and all(halves.values()):
        return {
            "named": True,
            "where": (
                "every declaring owner carries a cross-participant half the "
                "walk already stages, so this family's roster numbers reach it "
                "as that half's own packet: "
                + "; ".join(
                    f"{owner}: {', '.join(named)}"
                    for owner, named in sorted(halves.items())
                )
            ),
        }
    return {
        "named": False,
        "why": (
            "no interpreter is registered in the lane this row declares, and "
            + ", ".join(sorted(owner for owner, named in halves.items() if not named))
            + " declare no cross-participant half the walk stages -- so this "
            "family's roster-relevant numbers have no walk-side delivery term "
            "anywhere in the tree or in an amendment. Amendment O, Ruling 2 "
            "stops the next retirement round here rather than letting a lane "
            "invent one."
        ),
    }


def _triage(family: str, entry: Mapping[str, Any]) -> dict[str, Any]:
    """One row's Amendment O, Ruling 2 class, measured rather than asserted.

    Three classes, and the measurement decides which.  A family that authors
    priced pair rows is class ``a`` and retires by the ruled act.  A family
    that authors none divides on where its numbers go instead: every
    declaration naming the HOLDER as its subject is the pair-local fold
    Ruling 1 reclassifies (class ``b``); anything else reaches a participant
    through rows it does not author (class ``c``) and owes a named walk-side
    delivery term before it may retire.
    """
    rows = authored_rows(family, entry["owners"], entry["covering_coupled_scenarios"])
    subjects = _subjects(family, entry["owners"])
    holder_scoped = bool(subjects) and set(subjects) == {Subject.HOLDER.value}
    if rows:
        return {
            "authored_pair_rows": list(rows),
            "declared_subjects": list(subjects),
            "class": "a",
            "class_means": (
                "authors-own-rows: this family's declarations author "
                f"{len(rows)} priced pair-engine row(s), so Amendment L, "
                "Ruling 1's shape has something to stamp and the row retires "
                "by the ruled act (Amendments L/M/N)."
            ),
            "ruled_by": TRIAGE_RULING,
        }
    if holder_scoped:
        return {
            "authored_pair_rows": [],
            "declared_subjects": list(subjects),
            "class": "b",
            "class_means": (
                "pair-local fold into holder-own rows: this family authors no "
                "priced pair-engine row anywhere in the covering population or "
                "in a per-owner probe, and every declaration names the holder "
                "as its subject, so the fold lands in the holder's own "
                "champion rows. All-pair-local inputs => PAIR_ONLY, so the "
                "pair engine is this family's authoritative home and the row "
                "closes as not_a_gap by Amendment O, Ruling 1's "
                "reclassification rather than by a retirement."
            ),
            "ruled_by": RECLASSIFICATION_RULING,
        }
    return {
        "authored_pair_rows": [],
        "declared_subjects": list(subjects),
        "class": "c",
        "class_means": (
            "roster-relevant fold: this family authors no priced pair-engine "
            "row, and its declarations do not all name the holder as their "
            "subject -- a target-subject rule lands on a shared defender every "
            "roster participant meets, and a payload declaring no subject "
            "writes the defence fields whose inputs are the subject's live "
            "state under combined fire. Its numbers therefore reach "
            "participants through rows it does not author, so it may not be "
            "reclassified, and it owes a NAMED walk-side delivery term in "
            "Amendment M's shape before it retires."
        ),
        "walk_side_delivery_term": _delivery_term(
            family, entry["owners"], entry["retiring_act"]
        ),
        "ruled_by": TRIAGE_RULING,
    }


def reclassified_rows() -> dict[str, Any]:
    """The rows Amendment O, Ruling 1 closed, with the check that reopens them.

    A closed row leaves ``families`` above -- the frontier stops deferring it,
    so the schedule stops sizing it -- and everything a reader would want to
    check about the closure would leave with it.  This is that record, and
    every field of it is re-derived on every run: the owners from the catalog,
    the covering scenarios from the scenario set, and the authored-row
    measurement from the pair engine itself.  **That measurement is the
    machine check the ruling requires.**  The day a mechanic of a closed
    family authors a priced pair row, this block stops matching the committed
    one, the gate goes red, and the row is reopened by the tree rather than by
    somebody remembering to look.
    """
    declarations = owners_by_family()
    covering_by_family = golden_snapshot.covering_scenarios(
        golden_snapshot.COUPLED_SCENARIOS,
        {family: set(owners) for family, owners in declarations.items()},
    )
    baseline = json.loads(COUPLED_BASELINE_PATH.read_text(encoding="utf-8"))[
        "coupled_scenarios"
    ]
    closed: dict[str, Any] = {}
    for family in sorted(RECLASSIFIED):
        owners = sorted(declarations.get(family, {}))
        covering = [
            name for name in covering_by_family.get(family, ()) if name in baseline
        ]
        closed[family] = {
            "closed_row": f"{family}/{LANE}",
            "owners": owners,
            "declared_rules": sorted(
                mechanic
                for ids in declarations.get(family, {}).values()
                for mechanic in ids
            ),
            "covering_coupled_scenarios": covering,
            "authored_pair_rows": list(authored_rows(family, owners, covering)),
            "declared_subjects": list(_subjects(family, owners)),
            "ruled_by": RECLASSIFICATION_RULING,
            "closed_as": "not_a_gap",
            "why": (
                "Every declaration of this family names the holder as its "
                "subject and none of them authors a priced pair-engine row, in "
                "the covering population or in a per-owner probe on a ranged "
                "and a melee champion. All-pair-local inputs => PAIR_ONLY "
                "under the umbrella's own semantic-authority rule, so the pair "
                "engine is this family's authoritative home, no second engine "
                "prices it, no double-count exists, and the (family, "
                "RECEIPT_WALK) deferral row was a schedule category error "
                "rather than a debt."
            ),
            "reopens_if": (
                "any mechanic of this family ever authors a priced pair-engine "
                "row, or any declaration of it stops naming the holder as its "
                "subject. Both are re-measured here on every run and diff-gated "
                "against the committed block, so the reopening is the tree's "
                "act and not a reader's."
            ),
        }
    return closed


def _reclassification_failures() -> list[str]:
    """The tree has to agree that a reclassified row is closed.

    A ruling names a family and this file records the name; what it may not
    do is let the name outlive the closure.  Three ways it could: the family
    could go on declaring the receipt-walk lane, an interpreter could be
    registered for it after all -- which would make this a retirement wearing
    a reclassification's name -- or the frontier could still defer the row.
    """
    failures: list[str] = []
    rows = deferral_rows()
    for family in RECLASSIFIED:
        member = next(
            (
                candidate
                for candidate in interpreters.RuleFamily
                if candidate.value == family
            ),
            None,
        )
        if member is None:
            failures.append(f"{family!r} is reclassified and is not a rule family")
            continue
        if interpreters.EngineLane.RECEIPT_WALK in interpreters.lanes_for(member):
            failures.append(
                f"{family!r} is recorded as closed off the receipt walk and "
                "still declares that lane; a reclassification the lane table "
                "does not carry is a receipt saying what the tree denies"
            )
        if LANE in registered_lanes(family):
            failures.append(
                f"{family!r} is recorded as closed by reclassification and an "
                "interpreter serves its receipt-walk lane; that is a "
                "retirement, which is a different act with a different receipt"
            )
        if family in rows:
            failures.append(
                f"{family!r} is recorded as closed and the frontier still "
                "defers its receipt-walk row"
            )
    return failures


def _retiring_act(family: str, route: Sequence[str]) -> dict[str, Any]:
    """What retires this row, read off its own declared route.

    Amendment F names one act for all fourteen and spells it with one lane,
    which is true of the eleven the pair engine feeds and names, for the rest,
    the second producer D-60 forbids.  Amendment K rules the act per lane
    instead: a per-family interpreter in the lane the row itself declares.
    The act is derived from ``via`` rather than assumed, so a row that
    re-declares its route re-derives its act on the same commit.

    ``already_performed`` is the half of the act a reader cannot see from the
    prose: Amendment K observes that ``INTERPRETERS`` already holds the ruled
    key for the three rows the defence resolver feeds, so their act is done
    and what stands is the receipt-walk lane the table still declares.  It is
    derived from the registry, which is what makes it a fact that can be false
    -- the field it replaces said ``settled`` on both branches of this
    function and so could no longer discriminate anything, while the ruling it
    reported had already made every act settled.  That the acts are settled is
    said once, in this file's own words; per row, what is worth publishing is
    which of them still need performing.
    """
    lanes = [LANE] if tuple(route) == (PAIR_ENGINE,) else list(route)
    performed = bool(lanes) and set(lanes) <= registered_lanes(family)
    if tuple(route) == (PAIR_ENGINE,):
        return {
            "act": (
                "A receipt-walk interpreter for this family: the walk prices it "
                "itself instead of consuming the pair engine's timed rows that "
                "participant_timeline._pair_run_fight produces. This is "
                "Amendment F's named act and it describes this row as written."
            ),
            "retiring_lane": lanes,
            "already_performed": performed,
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
        "retiring_lane": lanes,
        "already_performed": performed,
        "ruled_by": RULING,
    }


def schedule() -> dict[str, Any]:
    """The whole artifact, derived."""
    rows = deferral_rows()
    declarations = owners_by_family()
    baseline = json.loads(COUPLED_BASELINE_PATH.read_text(encoding="utf-8"))[
        "coupled_scenarios"
    ]
    # One home for "which scenarios cover this family" (R-12): the capture
    # guard that refuses a blind baseline and this file's population read the
    # same predicate, so a covering scenario and a scheduled population can
    # never disagree about what covering means.  The committed baseline is
    # the extra filter here and only here -- a population is enumerated from
    # a snapshot that exists, and a scenario the baseline has not captured
    # yet has no rows to bound anything with.
    covering_by_family = golden_snapshot.covering_scenarios(
        golden_snapshot.COUPLED_SCENARIOS,
        {family: set(owners) for family, owners in declarations.items()},
    )
    slices: dict[str, Any] = {}
    for family, row in sorted(rows.items()):
        owned = declarations.get(family, {})
        covering = [
            name for name in covering_by_family.get(family, ()) if name in baseline
        ]
        sizes = {name: population_size(baseline[name]) for name in covering}
        total = sum(sizes.values())
        route = list(row["via"])
        slices[family] = {
            "interpreter_module": (INTERPRETERS_DIR / f"{family}.py")
            .relative_to(REPO_ROOT)
            .as_posix(),
            "deferral_row": f"{family}/{LANE}",
            "route_today": route,
            "retiring_act": _retiring_act(family, route),
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
        slices[family]["triage"] = _triage(family, slices[family])
    lane_corrected = sorted(
        family
        for family, entry in slices.items()
        if tuple(entry["route_today"]) != (PAIR_ENGINE,)
    )
    performed = sorted(
        family
        for family, entry in slices.items()
        if entry["retiring_act"]["already_performed"]
    )
    blind = [
        family
        for family, entry in slices.items()
        if entry["coupled_baseline_is_blind_to_this_family"]
    ]
    by_class: dict[str, list[str]] = {}
    for family, entry in sorted(slices.items()):
        by_class.setdefault(entry["triage"]["class"], []).append(family)
    stopped = sorted(
        family
        for family, entry in slices.items()
        if entry["triage"]["class"] == "c"
        and not entry["triage"]["walk_side_delivery_term"]["named"]
    )
    return {
        "artifact": "receipt_walk_retirement_schedule",
        "rule": (
            "Umbrella criterion 7's outstanding receipt-walk deferrals, sized "
            "as the slices Amendment F says they are. One row per "
            "family: its declarations and their owners, the committed coupled "
            "scenarios that put one of those owners on a participant, the size "
            "of each such scenario's committed snapshot, and the "
            "Expected qualifying occurrences line R-20's second half requires a "
            "slice to declare BEFORE its first src/ edit."
        ),
        "gate": "tests/test_receipt_walk_schedule.py",
        "what_this_is_not": (
            "It is not a retirement and no row here retires anything: every "
            "row still standing is overdue and gated, exactly as Amendment F "
            "leaves it. It does not re-date a row, re-scope the debt or read "
            "it as smaller -- one row out is one slice landed, never one debt "
            "re-counted -- and it registers no interpreter, because an "
            "interpreter registered to move a counter without changing what "
            "the walk prices is a counter driven to zero by editing what it "
            "counts. Its row set is read from the frontier's own deferrals, "
            "so a row leaves here only once the tree has stopped deferring "
            "it: delta_amp left on 2026-08-15, when Amendment M, Ruling 1's "
            "act landed and the receipt walk began reading that family's "
            "declaration through its own interpreter."
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
            "ANSWERED 2026-08-15, and kept because a mismatch that is only "
            "deleted is one no reader can check was ever real. "
            "delta_amp/receipt_walk declared via = ['pair_engine'], so it was "
            "counted here as taking Amendment F's act as written, while its "
            "own reason named two routes -- 'a holder-side amp reaches it "
            "already priced inside the pair engine's damage rows, and a "
            "cross-participant one as the damage_modifier packet "
            "item_support_effects emits, which survival/transitions stages as "
            "an ActionKind.DAMAGE_MODIFIER' -- and said neither of them was "
            "the rule. The structured route and the prose beside it therefore "
            "described different things, and only the structured one was "
            "gated. Amendment K answered it in the same sentence as the "
            "three: the declaration is the route (D-40), so the row's act was "
            "the receipt-walk one, and correcting the reason would be a "
            "behaviour claim owing its own slice rather than a schedule's "
            "edit. That slice has landed. Amendment M, Ruling 1 ordered this "
            "family first of the fourteen and ruled its act to be the "
            "walk-side delivery of the holder's static, pair-local "
            "amplifiers; interpreters.delta_amp.WALK_INTERPRETER performs it, "
            "the receipt walk now reads the amp declaration through its own "
            "lane, and the row retired -- so the mismatched reason is gone "
            "with the row it belonged to, and the compiled-score-walk row "
            "that shared it now names that walk alone (R-36). No family row "
            "above records this mismatch any more, which is the only correct "
            "state once the row it described has retired."
        ),
        "triage_rule": (
            "Umbrella Amendment O, Ruling 2 (2026-08-16): before any further "
            "retirement round, EVERY remaining open deferral row is measured "
            "for the property that stopped crit_profile -- which priced "
            "pair-engine rows the family's declarations actually author -- and "
            "classified here. (a) authors-own-rows: retires by the ruled act "
            "(Amendments L/M/N). (b) pair-local fold into holder-own rows: "
            "closes by Ruling 1's authority reclassification, each with its "
            "machine check. (c) roster-relevant fold: requires a NAMED "
            "walk-side delivery term in Amendment M's shape, and a class-(c) "
            "row lacking one STOPS the next retirement round rather than "
            "having a term invented for it. The measurement is derived from "
            "the pair engine by ablation, never asserted, and is diff-gated "
            "with the rest of this file."
        ),
        "triage_by_class": by_class,
        "triage_rows_stopping_the_next_retirement_round": stopped,
        "what_the_triage_does_not_do": (
            "It retires nothing and it budgets nothing. A class-(a) row is a "
            "behaviour-changing slice nobody has budgeted, exactly as before; "
            "a class-(c) row with a named delivery term is startable and not "
            "started; and a class-(c) row without one is stopped by name, "
            "which is the whole of what Ruling 2 buys -- the eleventh lane to "
            "pick a family up inherits a measurement instead of rediscovering "
            "the shape that stopped the fifth."
        ),
        "closed_by_authority_reclassification": reclassified_rows(),
        "scheduled_slices": len(slices),
        "slices_whose_retiring_act_is_amendment_f_as_written": len(slices)
        - len(lane_corrected),
        "slices_whose_retiring_lane_amendment_k_corrects": list(lane_corrected),
        "slices_whose_ruled_act_is_already_performed": list(performed),
        "what_already_performed_does_not_mean": (
            "Not that the row retires. INTERPRETERS holding the ruled key is "
            "the act being done; the deferral stands because the family still "
            "declares a receipt-walk lane the table has no interpreter for, "
            "and D-40 forbids editing that table from inside the counter it "
            "moves. So this list is the count of acts performed, never a "
            "count of debts paid -- rows in, slices out, one for one. It "
            "is published per row because it is the one thing about an act "
            "that can be false, and it replaces a flag that said settled on "
            "every row and so could not tell a reader anything."
        ),
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
        "slices_whose_ruled_act_is_already_performed",
        "triage_by_class",
        "triage_rows_stopping_the_next_retirement_round",
        "closed_by_authority_reclassification",
    ):
        if committed.get(key) != fresh[key]:
            failures.append(f"{key}: committed value differs from derived")
    failures.extend(_reclassification_failures())
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
