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

**A named delivery is resolved here and never merely recorded.**  Three shapes
count as named -- the row's own ruled act already performed, every owner
carrying a cross-participant half the walk stages, or a dated umbrella
amendment naming the delivery -- and the third is the one that could have been
a sentence.  Amendment P (2026-08-16) names ``damage_routing``'s: the program
rider system and the kernel state paths already in the tree, one per declared
payload family.  Naming a standing mechanism is an amendment's act and never a
lane's, so what this file does with the name is look it up: every mechanism the
ruling names is resolved against the kernel's own declarations on every run,
and a declaration the ruling does not cover -- or a named mechanism that leaves
the kernel -- re-stops the row and says which.  That is the ruling's own
conditional stop, *the kernel is never extended inside a retirement slice*,
made checkable rather than readable.

**A row served through the lane it declares carries its ground while it is
still open.**  Umbrella Amendment Q (2026-08-16) rules that a family whose
walk-side need is satisfied *through its declared serving lane* does not need
-- and must not declare -- a receipt-walk interpreter lane, because one
producer is what the one-engine thesis demands.  The condition is derived here
rather than named: a row whose declared route is not the pair engine and whose
ruled act is already performed publishes the ruling's evidence, in both
directions the ruling requires.  Forwards, what the family's own resolver
interpreter writes is joined to every read of those fields off a resolved
defences value, found by walking the source of every module outside the
resolver, and a declaration nothing consumes fails.  Backwards, the family's
interpreter is removed from the registry the coverage ladder reads and every
declaring owner is asked the public question again: the answer has to be
``withheld`` naming the missing pair rather than a modelled status, because a
producer whose absence is not a named refusal is the silent zero this campaign
is about.  Both run on every check, so the ground a closed row stands on is
re-measured rather than remembered, and the lane re-enters if a mechanic of the
family ever authors walk-priced rows the resolver does not feed.

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
import ast
import dataclasses
import functools
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

# pylint: disable=wrong-import-position,wrong-import-order
import golden_snapshot

from calculator import (
    interpreters,
    item_coverage,
    shield_ledger,
    trigger_stream,
)
from calculator.defensive_effects import option_reader
from calculator.item_behavior import (
    DefenseOption,
    DefenseSubject,
    Subject,
)
from calculator.item_behavior_catalog import behavior_rules, rule_owners
from calculator.program import events
from calculator.survival import actions as survival_actions

RECEIPTS_DIR = REPO_ROOT / "docs" / "receipts"
SCHEDULE_PATH = RECEIPTS_DIR / "receipt-walk-retirement-schedule.json"
FRONTIER_PATH = REPO_ROOT / "docs" / "behavior-frontier.json"
COUPLED_BASELINE_PATH = REPO_ROOT / "scripts" / "golden_coupled_baseline.json"
INTERPRETERS_DIR = REPO_ROOT / "src" / "calculator" / "interpreters"
CALCULATOR_DIR = REPO_ROOT / "src" / "calculator"

#: The lane whose deferrals this file sizes.  The compiled-score-walk gaps are
#: a different lane with a different blocker (H5) and are deliberately not here.
LANE = "receipt_walk"

#: The ruling that spells the retiring act per lane rather than per walk, and
#: so gives a row whose declared route is not the pair engine a settled act.
#: It was owed and is answered; the id stays here because every row's act
#: cites it, and a citation nobody can resolve is the thing this file avoids.
RULING = "what_retires_a_receipt_walk_deferral_whose_route_is_not_the_pair_engine"

#: The lane whose interpreter Amendment F named, and the only lane that closes
#: the eleven pair-engine-fed rows.
PAIR_ENGINE = "pair_engine"

#: Umbrella Amendment O's two rulings, cited by every row the triage below
#: classifies and by the closure that ruling performs.
RECLASSIFICATION_RULING = "umbrella Amendment O, Ruling 1"
TRIAGE_RULING = "umbrella Amendment O, Ruling 2"

#: The ruling that names the walk-side delivery of the one row Ruling 2's stop
#: clause fired on, and the family it names it for.  The family is scoped
#: because the ruling is: it answers one row, and a mapping that silently
#: reached a second family would be this file widening an amendment.
NAMED_DELIVERY_RULING = "umbrella Amendment P"
NAMED_DELIVERY_FAMILY = "damage_routing"

#: What umbrella Amendment P (2026-08-16) NAMES, per declared payload family:
#: the standing kernel mechanism that carries that declaration's walk-side
#: numbers.  The amendment names them; this file **resolves** each name against
#: the tree on every run (:func:`_mechanism_stands`), so a named mechanism that
#: leaves the kernel, or a fourth mechanic of the family whose payload family
#: the amendment does not name, turns the delivery term unnamed again and
#: re-stops the row.  That is the ruling's own conditional stop -- *the kernel
#: is never extended inside a retirement slice* -- made checkable rather than
#: readable.
AMENDMENT_P_DELIVERY: dict[str, tuple[str, ...]] = {
    "DamageDeferralRule": (
        "program.events.Defer",
        "survival.actions.SurvivalAction.deferred",
        "survival.actions.SurvivalAction.deferred_batch_slot",
    ),
    "ExecuteRule": (
        "program.events.Execute",
        "survival.actions.SurvivalAction.execute_threshold_ratio",
        "survival.actions.SurvivalAction.execute_source",
    ),
    "ShieldBypassRule": ("shield_ledger.ShieldPools.venom_factor",),
}

#: The families Amendment O, Ruling 1 closes off the receipt walk.  A ruling
#: names a family; every FIELD of the closed row below is derived, and
#: :func:`_reclassification_failures` refuses a name the tree does not agree
#: with -- a family still declaring the lane, or one an interpreter serves,
#: is not a family this ruling closed.  ``crit_profile`` is here because
#: Ruling 1 names it and the tree agrees: ``_FAMILY_LANES`` declares no
#: receipt-walk lane for it, no interpreter serves one, and the frontier does
#: not defer the row.  Measuring is one act and closing is another, so a
#: name arrives here in the commit that drops the lane and never before it.
RECLASSIFIED: tuple[str, ...] = ("crit_profile",)

#: The ruling that corrects a lane DECLARATION rather than closing a debt:
#: umbrella Amendment Q (2026-08-16).  A family whose walk-side need is
#: satisfied through its declared serving lane does not need -- and must not
#: declare -- a receipt-walk interpreter lane, because one producer is what the
#: one-engine thesis demands.  It is a different act from Amendment O, Ruling
#: 1's reclassification and carries a different ground: not "the family authors
#: nothing for the walk to consume" but "what the walk consumes, it consumes
#: from the lane the family declares".
LANE_CORRECTION_RULING = "umbrella Amendment Q"

#: The families Amendment Q closes off the receipt walk by lane-declaration
#: correction.  A ruling names them; every FIELD of the closed row below is
#: derived, and :func:`_lane_correction_failures` refuses a name the tree does
#: not agree with -- a family still declaring the lane, one an interpreter
#: serves there, one whose declared serving lane has no interpreter after all,
#: or one the frontier still defers.  Measuring is one act and closing is
#: another, so a name arrives here in the commit that drops the lane and never
#: before it.
LANE_CORRECTED: tuple[str, ...] = (
    "combat_state",
    "opening_defense",
    "threshold_defense",
)

#: Amendment F's own figure for the size of the receipt-walk debt, quoted from
#: the amendment rather than derived from the tree: every row it names has since
#: left, so nothing here can re-count them.  The mismatch narration below quotes
#: the amendment about its fourteen and derives every other count in the
#: sentence FROM it, so the sentence cannot say "Three" over a list of four.
AMENDMENT_F_ROWS = 14

#: The count words that narration spells.  Prose spells a small number as a
#: word, and a word typed beside a derived list is the same defect one field
#: along: the list moves and the word does not.  Sized to the debt so a count
#: outside it fails by name rather than rendering a digit into prose.
_COUNT_WORDS: tuple[str, ...] = (
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
)


#: The subject the resolver is run against to derive what each declaration
#: writes.  It is a probe and not a population: the FIELD NAMES a declaration
#: writes are what the consumption check joins on, and a subject that armed no
#: option would make a gated defence look like a declaration that writes
#: nothing at all.  Every declared option is armed, read off the enum rather
#: than listed, so a third option arms itself on the commit that declares it.
PROBE_LEVEL_STATS: Mapping[str, float] = {
    "health": 2500.0,
    "max_health": 2500.0,
    "armor": 100.0,
    "magic_resistance": 100.0,
    "attack_damage": 100.0,
    "bonus_attack_damage": 60.0,
    "ability_power": 0.0,
    "bonus_health": 1000.0,
    "bonus_armor": 60.0,
    "bonus_magic_resistance": 60.0,
    "mana": 1000.0,
}

#: The name a resolved ``StartingDefenses`` is bound to everywhere it is
#: consumed.  The consumption scan below is an AST predicate over reads *off
#: that value* rather than a search for a field name in a file, which is what
#: keeps a same-named attribute of some other record out of the answer.
RESOLVED_STATE_BINDING = "defenses"

#: Where the resolver builds its answer, excluded from the consumption scan.
#: A field read inside the producer is not the walk consuming it, and the
#: exclusion is stated rather than left to chance -- it removes nothing today,
#: which is the point: the day a resolver module started reading its own
#: output back, the check would otherwise count that as consumption.
RESOLVER_SOURCES: tuple[str, ...] = ("interpreters", "defensive_effects.py")

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


def spelled(count: int) -> str:
    """``count`` as the word the mismatch narration spells it with."""
    if not 0 <= count < len(_COUNT_WORDS):
        raise ScheduleError(
            f"the mismatch narration cannot spell {count}: the count words are "
            f"sized to Amendment F's {AMENDMENT_F_ROWS} rows, so a count "
            "outside them means the debt this receipt narrates is not the one "
            "the amendment named"
        )
    return _COUNT_WORDS[count]


def mismatch_narration(lane_corrected_ever: Sequence[str]) -> str:
    """Amendment F's route mismatch, every count spelled off its own list.

    Takes the families rather than reading them, so the one property the
    sentence has to have -- that its count words and its names describe the
    same set -- is reachable by a test with a set of its own instead of only
    on whatever the tree happens to hold.
    """
    corrected = len(lane_corrected_ever)
    return (
        "Amendment F describes all "
        + spelled(AMENDMENT_F_ROWS)
        + " rows as the families whose "
        "numbers participant_timeline._pair_run_fight produces today. "
        + spelled(AMENDMENT_F_ROWS - corrected).capitalize()
        + " declare that route in their own via field. "
        + spelled(corrected).capitalize()
        + " -- "
        + ", ".join(lane_corrected_ever)
        + " -- declare the defence resolver instead, and their rows say in "
        "their own words that a walk-lane interpreter there would be a "
        "second producer of one number, which is what D-60 and umbrella "
        "criterion 8 forbid. So Amendment F's act, spelled with the receipt "
        "walk, named for those "
        + spelled(corrected)
        + " the act the campaign's own criterion "
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
        "stops owing the walk an answer, and reading "
        + spelled(AMENDMENT_F_ROWS)
        + " as "
        + spelled(AMENDMENT_F_ROWS - corrected)
        + "."
    )


def deferral_rows() -> dict[str, Mapping[str, Any]]:
    """The committed ``(family, receipt_walk)`` deferral rows, by family.

    The row and its unserved-lane receipt are two halves of one record in the
    frontier -- the row carries the overdue flag and the blocker, the receipt
    carries ``via``, the declared route the number arrives by -- so they are
    joined here rather than one being read without the other.

    **An empty result is the DISCHARGED state, not a failed read**, and the
    two are told apart structurally rather than by a flag.  Refusing an empty
    set would be an instrument that stops working on the commit the debt
    reaches zero.  What such a refusal is worth is catching a read that found
    no rows *because it read the wrong thing*, so that is what it
    checks: the frontier's deferral block has to be present and
    well-formed, and an empty ``rows`` inside a present block is the tree
    saying the debt is paid.
    """
    counter = json.loads(FRONTIER_PATH.read_text(encoding="utf-8"))["counters"][
        "counter_4"
    ]
    deferrals = counter.get("deferrals")
    if not isinstance(deferrals, Mapping) or "rows" not in deferrals:
        raise ScheduleError(
            "the frontier records no receipt-walk deferral BLOCK; a schedule "
            "built off a counter that publishes no deferrals is reading the "
            "wrong artifact rather than reading a paid debt"
        )
    rows = deferrals["rows"]
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


def population_size(node: object) -> int:
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

    Read from the registry, the one place a family's served lanes are written.
    """
    return {
        lane.value
        for declared, lane in interpreters.INTERPRETERS
        if declared.value == family
    }


def priced_rows(result: Mapping[str, Any]) -> frozenset[str]:
    """The breakdown rows a fight's own ``total_damage`` holds.

    Exact rather than heuristic: summing ``total_damage`` over these rows
    reproduces the fight's own, which :mod:`tests.test_receipt_walk_schedule`
    asserts.  An ``informational`` row publishes a difference a priced row
    already holds; a row with no ``total_damage`` is not damage.
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
    runs = (
        [resolved.fight_params]
        if not resolved.enemies
        else list(resolved.target_fight_params)
    )
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
        golden_snapshot._run_fight(  # noqa: SLF001 - the gate's own fight runner  # pylint: disable=protected-access
            champions[champion],
            PROBE_LEVEL,
            [by_name[name] for name in items],
            auto_attack_uptime=1.0,
            one_rotation=False,
        )
    )


def authored_rows(owners: Sequence[str], covering: Sequence[str]) -> tuple[str, ...]:
    """Which priced pair-engine rows *owners*' declarations author.

    Ablation, over two domains, and the union of what both find.

    The first is the **covering population** umbrella Amendment O, Ruling 1
    names: every committed coupled scenario putting one of this family's
    owners on a participant, run pair fight by pair fight with the family's
    items on and off.  A row present with them and absent without them is a
    row this family authors.

    The second is one probe per owner, on a ranged and a melee champion, which
    makes a zero a claim about the FAMILY rather than about the scenarios that
    happen to hold it.  Two of ``crit_profile``'s three owners are equipped by
    no covering scenario, so without the probes a row they authored would be
    invisible to the check meant to reopen the closed row.
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
        for full, ablated in zip(with_them, without, strict=False):
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


def _kernel_mechanisms() -> dict[str, frozenset[str]]:
    """Every mechanism a named delivery may land in, read from the kernel.

    Two shapes, because Amendment P names two: a rider family the kernel's
    own :data:`~..program.events.RIDER_KINDS` declares, and a field of a
    kernel state record.  Both are read off the declaring object rather than
    listed here, so a mechanism that leaves the kernel stops resolving on the
    commit that removes it instead of on the day somebody re-reads a receipt.
    """
    return {
        "program.events": frozenset(kind.__name__ for kind in events.RIDER_KINDS),
        "survival.actions.SurvivalAction": frozenset(
            survival_actions.SurvivalAction._fields  # pylint: disable=protected-access
        ),
        "shield_ledger.ShieldPools": frozenset(
            field.name for field in dataclasses.fields(shield_ledger.ShieldPools)
        ),
    }


def _mechanism_stands(path: str) -> bool:
    """Whether one mechanism umbrella Amendment P names is in the tree today."""
    holder, _, leaf = path.rpartition(".")
    return leaf in _kernel_mechanisms().get(holder, frozenset())


def _declared_payloads(
    family: str, owners: Sequence[str]
) -> tuple[tuple[str, str], ...]:
    """Each declaration of *family* as ``(mechanic_id, payload family)``.

    The payload family is what Amendment P's mapping is keyed on: the ruling
    names a kernel mechanism per SHAPE of declaration -- a deferral, an
    execute, a shield bypass -- rather than per mechanic id, so a second owner
    declaring an existing shape is delivered by the ruling and a new shape is
    not.
    """
    return tuple(
        sorted(
            (rule.mechanic_id, type(rule.payload).__name__)
            for owner in owners
            for rule in behavior_rules(owner)
            if rule.family.value == family
        )
    )


def _amendment_named_delivery(
    family: str, owners: Sequence[str]
) -> tuple[dict[str, tuple[str, ...]], tuple[str, ...]]:
    """Amendment P's delivery for each declaration, and what it does not cover.

    Returns the resolved mechanisms keyed by mechanic id, and the declarations
    the ruling leaves unanswered -- a shape it does not name, or one whose
    named mechanism is absent from the kernel.  A non-empty second half
    is the ruling's own conditional stop firing: *if any owner's effect has no
    existing rider or state path the kernel can express, the implementing lane
    STOPS blocked naming exactly which*.  It is returned rather than raised
    because naming which is the whole of what the stop buys.
    """
    if family != NAMED_DELIVERY_FAMILY:
        return {}, ()
    resolved: dict[str, tuple[str, ...]] = {}
    unanswered: list[str] = []
    for mechanic, payload in _declared_payloads(family, owners):
        mechanisms = AMENDMENT_P_DELIVERY.get(payload, ())
        missing = [path for path in mechanisms if not _mechanism_stands(path)]
        if not mechanisms:
            unanswered.append(
                f"{mechanic} ({payload}): umbrella Amendment P names no kernel "
                "mechanism for this declaration's payload family"
            )
        elif missing:
            unanswered.append(
                f"{mechanic} ({payload}): the mechanism the ruling names no "
                "longer stands in the kernel -- " + ", ".join(missing)
            )
        else:
            resolved[f"{mechanic} ({payload})"] = mechanisms
    return resolved, tuple(unanswered)


def _named_delivery_resolution(
    declarations: Mapping[str, Mapping[str, Sequence[str]]],
) -> dict[str, Any]:
    """Amendment P's mapping, resolved whether or not the row is still open.

    The resolution outlives the row it was written for, deliberately.  A named
    delivery checked only while its row stood would be a ruling that held
    exactly as long as nobody depended on it: what the walk stages for this
    family IS those mechanisms, so a fourth mechanic whose payload shape the
    amendment does
    not name, or a named mechanism that leaves the kernel, has to go red here
    as well as in the interpreter's own branch table.  ``covers_every_declaration``
    is the totality half and ``unanswered`` names which, because the ruling's
    conditional stop is *STOPS blocked, naming exactly which*.
    """
    owners = sorted(declarations.get(NAMED_DELIVERY_FAMILY, {}))
    resolved, unanswered = _amendment_named_delivery(NAMED_DELIVERY_FAMILY, owners)
    return {
        "family": NAMED_DELIVERY_FAMILY,
        "ruled_by": NAMED_DELIVERY_RULING,
        "owners": owners,
        "mechanisms_by_declaration": {
            declaration: list(mechanisms)
            for declaration, mechanisms in sorted(resolved.items())
        },
        "covers_every_declaration": bool(resolved) and not unanswered,
        "unanswered": list(unanswered),
        "why_it_outlives_the_row": (
            "The row retired on 2026-08-16 and this stayed. The mechanisms the "
            "amendment names are what the walk stages for this family now, not "
            "what it would have staged, so a shape the ruling does not name or "
            "a mechanism that leaves the kernel is a live break rather than a "
            "stale note -- and a check that switched itself off the moment its "
            "row left would be a delivery term recorded rather than resolved."
        ),
    }


def _delivery_term(
    family: str, owners: Sequence[str], act: Mapping[str, Any]
) -> dict[str, Any]:
    """Whether a class-(c) row's walk-side delivery term is named, and where.

    Amendment O, Ruling 2 requires one before such a row may retire, and
    forbids a LANE from inventing one.  Three shapes count as named and every
    one of them is resolved against the tree.  The row's own ruled retiring
    act may already be performed -- ``INTERPRETERS`` holding the key for the
    lane the row declares is Amendment K's delivery, standing in the tree
    today.  Or every declaring owner may carry a cross-participant half the
    walk already stages, which is the SPLIT shape: the shred's roster number
    reaches the walk as the ``damage_modifier`` packet its own coupled half
    emits.  Or a dated umbrella amendment may NAME the delivery, which is what
    Amendment P does for ``damage_routing`` -- the program rider system and
    the kernel state paths already in the tree, one per declared payload
    family.  The third shape is an amendment's act and never a lane's, and it
    is machine-resolved rather than recorded: every mechanism the ruling names
    is looked up in the kernel on every run, so a declaration the ruling does
    not cover, or a mechanism that leaves the kernel, re-stops the row and
    names which.  None of the three present is a row that STOPS the next
    retirement round, named here rather than papered over.
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
    resolved, unanswered = _amendment_named_delivery(family, owners)
    if resolved and not unanswered:
        return {
            "named": True,
            "ruled_by": NAMED_DELIVERY_RULING,
            "where": (
                "umbrella Amendment P (2026-08-16) names this family's "
                "walk-side delivery as the program rider system and the kernel "
                "state paths ALREADY IN THE TREE, one per declared payload "
                "family, and every mechanism it names stands in the kernel "
                "today: "
                + "; ".join(
                    f"{mechanic}: {', '.join(paths)}"
                    for mechanic, paths in sorted(resolved.items())
                )
                + ". The retirement act is then the ruled act (Amendments "
                "L/M/N) with rider and state compilation as the interpreter's "
                "output, and equivalence fixtures per owner."
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
            + (
                " Umbrella Amendment P names this family's delivery and the "
                "ruling's own conditional stop has fired on: "
                + "; ".join(unanswered)
                + ". The kernel is never extended inside a retirement slice, "
                "so the lane stops blocked naming exactly which rather than "
                "growing one."
                if unanswered
                else ""
            )
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
    rows = authored_rows(entry["owners"], entry["covering_coupled_scenarios"])
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
            "authored_pair_rows": list(authored_rows(owners, covering)),
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


def _family_member(family: str) -> interpreters.RuleFamily:
    """The enum member a family name names, or a stop."""
    member = next(
        (
            candidate
            for candidate in interpreters.RuleFamily
            if candidate.value == family
        ),
        None,
    )
    if member is None:
        raise ScheduleError(f"{family!r} is not a rule family")
    return member


def _probe_subject(owners: Sequence[str]) -> DefenseSubject:
    """The subject the resolver is run against to see what a declaration writes.

    Every declared :class:`DefenseOption` is armed for every owner, read off
    the enum rather than listed.  A gated defence pays nothing without its
    input by design, so an unarmed probe would report the two stasis
    declarations writing no field at all -- and "writes nothing" is exactly the
    answer the consumption check below must not get for the wrong reason.
    """
    options = {
        owner: {option.value: 1.0 for option in DefenseOption} for owner in owners
    }
    return DefenseSubject(
        level=PROBE_LEVEL,
        stats=PROBE_LEVEL_STATS,
        options=options,
        option_value=option_reader(options),
    )


def resolved_fields(family: str, owners: Sequence[str]) -> dict[str, tuple[str, ...]]:
    """What each declaration of *family* writes into the resolver's state.

    Derived by running the family's own registered resolver interpreter over
    its declarations, never read from a table: the join the consumption check
    makes is between what the resolver WRITES and what the walk READS, and a
    hand-written left side would be a claim about the interpreter rather than
    the interpreter's own answer.
    """
    subject = _probe_subject(owners)
    written: dict[str, tuple[str, ...]] = {}
    for owner in owners:
        for rule in behavior_rules(owner):
            if rule.family.value != family:
                continue
            outcome = interpreters.resolve_defense(rule, subject)
            written[rule.mechanic_id] = tuple(
                sorted({field.name for field in outcome.fields})
            )
    return written


def _binds_resolved_state(node: ast.expr) -> bool:
    """Whether *node* is the resolved defences value, however it was reached."""
    if isinstance(node, ast.Name):
        return node.id == RESOLVED_STATE_BINDING or node.id.endswith(
            "_" + RESOLVED_STATE_BINDING
        )
    if isinstance(node, ast.Attribute):
        return node.attr == RESOLVED_STATE_BINDING
    return False


def _reads_in(module: str, tree: ast.AST) -> list[tuple[str, str]]:
    """Every ``(field, site)`` one module reads off the resolved defences.

    Two shapes, because the tree uses two: a plain attribute read, and the
    ``getattr(defenses, "field", default)`` form the walk uses where a
    participant may carry no resolved state at all.  The site is the enclosing
    definition, so what the receipt publishes is a function a reader can open
    rather than a file to search.
    """
    found: list[tuple[str, str]] = []

    def visit(node: ast.AST, enclosing: str) -> None:
        for child in ast.iter_child_nodes(node):
            site = enclosing
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                site = f"{enclosing}.{child.name}" if enclosing else child.name
            if isinstance(child, ast.Attribute) and _binds_resolved_state(child.value):
                found.append((child.attr, f"{module}.{site}" if site else module))
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Name)
                and child.func.id == "getattr"
                and len(child.args) >= 2
                and _binds_resolved_state(child.args[0])
                and isinstance(child.args[1], ast.Constant)
                and isinstance(child.args[1].value, str)
            ):
                found.append(
                    (child.args[1].value, f"{module}.{site}" if site else module)
                )
            visit(child, site)

    visit(tree, "")
    return found


@functools.lru_cache(maxsize=1)
def _resolved_state_reads() -> Mapping[str, tuple[str, ...]]:
    """Every consumer of the resolver's resolved state, by field, from source.

    This is the source assertion umbrella Amendment Q's forward direction
    requires, and it is a scan of the tree rather than a list in a receipt:
    the day a walk-side site stops reading a field, the field's consumer set
    shrinks here on that commit.  The resolver's own modules are excluded --
    a producer reading its own output back is not the walk consuming it.
    """
    reads: dict[str, set[str]] = {}
    for path in sorted(CALCULATOR_DIR.rglob("*.py")):
        relative = path.relative_to(CALCULATOR_DIR).as_posix()
        if any(relative.startswith(source) for source in RESOLVER_SOURCES):
            continue
        module = relative[: -len(".py")].replace("/", ".")
        for field, site in _reads_in(
            module, ast.parse(path.read_text(encoding="utf-8"))
        ):
            reads.setdefault(field, set()).add(site)
    return {field: tuple(sorted(sites)) for field, sites in reads.items()}


def _capability_impl(mechanic: str) -> str | None:
    """The walk-side implementation this mechanic's own capability names."""
    capability = trigger_stream.CAPABILITIES.get(mechanic)
    if capability is None or capability.engine is not trigger_stream.Engine.WALK:
        return None
    return capability.impl


def walk_side_consumption(family: str, owners: Sequence[str]) -> dict[str, Any]:
    """Amendment Q's forward direction: what the walk consumes, and from where.

    Per DECLARATION and never per family, because a family passes this on one
    mechanic while another of its mechanics reaches the walk from somewhere
    else entirely -- which is the case the correction may not be made on.  For
    each declaration: the fields its resolver interpreter writes, the sites
    that read them off the resolved state, the fields no engine reads at all
    (published rather than hidden -- a resolved number nothing consumes is a
    fact about the model, not a failure of this check), and, where the
    declaration's own ``MechanicCapability`` names a walk-side impl, whether
    that named module is among the consuming ones.  ``consumed_nowhere`` is
    the failing set: a declaration none of whose fields any site reads is the
    walk NOT being fed through the resolver, and the correction does not hold
    for its family.
    """
    reads = _resolved_state_reads()
    written = resolved_fields(family, owners)
    per_declaration: dict[str, Any] = {}
    consumed_nowhere: list[str] = []
    unbound_impls: list[str] = []
    for mechanic, fields in sorted(written.items()):
        sites = sorted({site for field in fields for site in reads.get(field, ())})
        unread = [field for field in fields if not reads.get(field)]
        named = _capability_impl(mechanic)
        modules = {site.rsplit(".", 1)[0] for site in sites}
        entry: dict[str, Any] = {
            "resolved_fields": list(fields),
            "consumed_at": sites,
            "fields_no_engine_reads": unread,
        }
        if named is not None:
            entry["capability_named_walk_impl"] = named
            entry["named_impl_is_a_consumer"] = named.rsplit(".", 1)[0] in modules
            if not entry["named_impl_is_a_consumer"]:
                unbound_impls.append(f"{mechanic} -> {named}")
        per_declaration[mechanic] = entry
        if not sites:
            consumed_nowhere.append(mechanic)
    return {
        "rule": (
            "Umbrella Amendment Q's forward direction, source-asserted. The "
            "fields are what this family's own resolver interpreter writes, "
            "run over its declarations; the sites are every read of one of "
            "those fields off a resolved defences value, found by walking the "
            "source of every module outside the resolver. A declaration "
            "nothing consumes means the walk is not fed through the lane this "
            "family declares, and the correction does not hold for it."
        ),
        "by_declaration": per_declaration,
        "declarations_consumed_nowhere": consumed_nowhere,
        "capability_named_impls_that_are_not_consumers": sorted(unbound_impls),
        "holds": not consumed_nowhere and not unbound_impls,
    }


def withheld_without_the_serving_interpreter(
    family: str, lanes: Sequence[str], owners: Sequence[str]
) -> dict[str, Any]:
    """Amendment Q's backward direction: the producer's absence fails closed.

    Run, not reasoned about.  The family's interpreter is removed from the
    registry the coverage ladder reads and every declaring owner is asked the
    public question again: an owner that still answers a modelled status is an
    owner whose numbers survive the loss of the producer this correction says
    is their only one, which is the silent zero the campaign is about.  The
    answer has to be ``withheld`` AND has to name the missing ``(family,
    lane)`` pair, because a refusal that does not say what is missing is a
    number withheld for a reason nobody can act on.
    """
    member = _family_member(family)
    removed = {interpreters.EngineLane(lane) for lane in lanes}
    needed = frozenset(removed)
    public = sorted(
        question
        for question, lane_set in (
            ("attacker", item_coverage.ATTACKER_LANES),
            ("scoring", item_coverage.SCORING_LANES),
            ("target", item_coverage.TARGET_LANES),
        )
        if needed & lane_set
    )
    standing = item_coverage.INTERPRETERS
    answers: dict[str, Any] = {}
    item_coverage.INTERPRETERS = {
        key: value
        for key, value in standing.items()
        if not (key[0] is member and key[1] in removed)
    }
    try:
        for owner in sorted(owners):
            coverage = item_coverage.item_model_coverage(owner, needed)
            answers[owner] = {
                "status": coverage.status,
                "names_the_missing_pair": all(
                    f"{family}/{lane}" in coverage.reason for lane in lanes
                ),
            }
    finally:
        item_coverage.INTERPRETERS = standing
    unheld = sorted(
        owner
        for owner, answer in answers.items()
        if answer["status"] != "withheld" or not answer["names_the_missing_pair"]
    )
    return {
        "rule": (
            "Umbrella Amendment Q's backward direction, run on every check. "
            "The family's interpreter is removed from the registry the "
            "coverage ladder reads and every declaring owner is asked again: "
            "the answer must be withheld and must name the missing (family, "
            "lane) pair, never a modelled status and never a silent zero."
        ),
        "lanes_removed": list(lanes),
        "public_questions_that_need_those_lanes": public,
        "by_owner": answers,
        "owners_that_do_not_fail_closed": unheld,
        "holds": bool(answers) and bool(public) and not unheld,
    }


def _lane_correction_evidence(
    family: str,
    owners: Sequence[str],
    act: Mapping[str, Any],
    triage: Mapping[str, Any],
) -> dict[str, Any]:
    """Both directions of umbrella Amendment Q's check, and its reopening clause.

    Published for every row whose walk-side need is served through the lane it
    declares, whether or not the correction has been performed for it: the
    evidence is what the ruling rests on, so it is measured while the row is
    still open and re-measured after it closes, and a row that stopped
    satisfying it would go red rather than quietly keep a dropped lane.
    """
    forwards = walk_side_consumption(family, owners)
    backwards = withheld_without_the_serving_interpreter(
        family, act["retiring_lane"], owners
    )
    return {
        "ruled_by": LANE_CORRECTION_RULING,
        "walk_side_consumption": forwards,
        "fails_closed_without_the_serving_interpreter": backwards,
        "authored_pair_rows": list(triage["authored_pair_rows"]),
        "reopens_if": (
            "a mechanic of this family ever authors walk-priced rows not fed "
            "by the resolver -- measured on every run as the priced pair rows "
            "the family authors over its covering population and a probe per "
            "owner, and as the per-declaration consumption above -- in which "
            "case the receipt-walk lane re-enters _FAMILY_LANES and the "
            "deferral row reopens."
        ),
        "holds": forwards["holds"]
        and backwards["holds"]
        and not triage["authored_pair_rows"],
    }


def corrected_rows() -> dict[str, Any]:
    """The rows Amendment Q closed, with the checks that reopen them.

    A closed row leaves ``families`` above -- the frontier stops deferring it,
    so the schedule stops sizing it -- and the evidence the closure rests on
    would leave with it.  This is that record, and every field of it is
    re-derived on every run: the owners from the catalog, the resolved fields
    from the family's own interpreter, the consuming sites from the source of
    every module outside the resolver, and the withheld answer from the
    coverage ladder with the interpreter removed.
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
    for family in sorted(LANE_CORRECTED):
        owners = sorted(declarations.get(family, {}))
        covering = [
            name for name in covering_by_family.get(family, ()) if name in baseline
        ]
        served = sorted(registered_lanes(family) - {LANE})
        act = {"retiring_lane": served}
        triage = {"authored_pair_rows": list(authored_rows(owners, covering))}
        closed[family] = {
            "closed_row": f"{family}/{LANE}",
            "owners": owners,
            "declared_rules": sorted(
                mechanic
                for ids in declarations.get(family, {}).values()
                for mechanic in ids
            ),
            "covering_coupled_scenarios": covering,
            "serving_lanes_an_interpreter_answers_for": served,
            "closed_as": "not_a_needed_lane",
            "why": (
                "This family's walk-side need is satisfied THROUGH the lane it "
                "declares: an interpreter serves that lane, the walk consumes "
                "the state that interpreter builds, and a receipt-walk "
                "interpreter beside it would be a second producer of one "
                "number. One producer is what the one-engine thesis demands, "
                "so the receipt-walk lane was a declaration this family never "
                "owed and the deferral row under it was counting the absence "
                "of a defect rather than a debt."
            ),
            "evidence": _lane_correction_evidence(family, owners, act, triage),
            "ruled_by": LANE_CORRECTION_RULING,
        }
    return closed


def _lane_correction_failures() -> list[str]:
    """The tree has to agree that a corrected row is closed, and stay agreeing.

    Five ways it could stop: the family could go on declaring the receipt-walk
    lane, an interpreter could be registered for it there -- which would make
    this a retirement wearing a correction's name -- the serving lane the
    correction rests on could lose its interpreter, the frontier could still
    defer the row, or either direction of the ruling's own check could stop
    holding.
    """
    failures: list[str] = []
    rows = deferral_rows()
    for family, entry in corrected_rows().items():
        member = _family_member(family)
        if interpreters.EngineLane.RECEIPT_WALK in interpreters.lanes_for(member):
            failures.append(
                f"{family!r} is recorded as closed off the receipt walk by "
                "lane-declaration correction and still declares that lane; a "
                "correction the lane table does not carry is a receipt saying "
                "what the tree denies"
            )
        if LANE in registered_lanes(family):
            failures.append(
                f"{family!r} is recorded as closed by lane-declaration "
                "correction and an interpreter serves its receipt-walk lane; "
                "that is a retirement, which is a different act"
            )
        if not entry["serving_lanes_an_interpreter_answers_for"]:
            failures.append(
                f"{family!r} is recorded as served through the lane it "
                "declares and no interpreter serves any lane of it; the ground "
                "the correction stands on is gone"
            )
        if family in rows:
            failures.append(
                f"{family!r} is recorded as closed and the frontier still "
                "defers its receipt-walk row"
            )
        evidence = entry["evidence"]
        forwards = evidence["walk_side_consumption"]
        if forwards["declarations_consumed_nowhere"]:
            failures.append(
                f"{family!r}: nothing outside the resolver consumes what "
                + ", ".join(forwards["declarations_consumed_nowhere"])
                + " writes, so this family's walk-side need is not served "
                "through the lane it declares and the receipt-walk lane "
                "re-enters"
            )
        if forwards["capability_named_impls_that_are_not_consumers"]:
            failures.append(
                f"{family!r}: a declaration names a walk-side impl that reads "
                "none of the fields its own resolver writes -- "
                + ", ".join(forwards["capability_named_impls_that_are_not_consumers"])
            )
        backwards = evidence["fails_closed_without_the_serving_interpreter"]
        if not backwards["holds"]:
            failures.append(
                f"{family!r}: with its serving interpreter removed, "
                + (
                    ", ".join(backwards["owners_that_do_not_fail_closed"])
                    + " do not answer withheld naming the missing pair"
                    if backwards["owners_that_do_not_fail_closed"]
                    else "no declaring owner is asked a public question that "
                    "needs the lane"
                )
                + "; a producer whose absence is not a named refusal is the "
                "silent zero this correction says cannot happen"
            )
        if entry["evidence"]["authored_pair_rows"]:
            failures.append(
                f"{family!r} is recorded as closed by lane-declaration "
                "correction and now authors "
                + ", ".join(entry["evidence"]["authored_pair_rows"])
                + "; a walk-priced row not fed by the resolver reopens the row"
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
    derived from the registry, which is what makes it a fact that can be false.
    A field saying ``settled`` on both branches of this function would
    discriminate nothing.  That the acts are settled is said once, in this
    file's own words; per row, what is worth publishing is which of them still
    need performing.
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
        # Umbrella Amendment Q's condition, derived rather than named: the
        # row's declared serving lane is not the receipt walk and an
        # interpreter already answers for it.  A row that satisfies it carries
        # the ruling's evidence while it is still open, because the evidence
        # is what the correction rests on and it may not first be measured by
        # the commit that performs it.
        act = slices[family]["retiring_act"]
        served = tuple(route) != (PAIR_ENGINE,) and act["already_performed"]
        slices[family]["served_through_its_declared_lane"] = served
        if served:
            slices[family]["lane_correction_evidence"] = _lane_correction_evidence(
                family, slices[family]["owners"], act, slices[family]["triage"]
            )
    lane_corrected = sorted(
        family
        for family, entry in slices.items()
        if tuple(entry["route_today"]) != (PAIR_ENGINE,)
    )
    # The mismatch narration below names the families whose row declared the
    # defence resolver rather than the pair engine.  ``lane_corrected`` reads
    # the rows still standing, which is what the live field wants and what the
    # sentence must not depend on: once those rows close the list empties and
    # the sentence renders "Three --  -- declare the defence resolver instead",
    # a justification whose subject a retirement round took away.  The closed
    # rows are LANE_CORRECTED, the one declaration of which families Amendment Q
    # closed -- the same names ``corrected_rows()`` iterates to build its
    # evidence block, and gated in both directions by
    # ``_lane_correction_failures``, so reading the declaration is reading the
    # closed rows and not a second list.  The narration reads both and stays
    # true of a debt that has been paid.  Its COUNT WORDS come off this same
    # list through :func:`spelled`, and its complement off Amendment F's own
    # figure, because a word typed beside a derived list is the same defect one
    # field along: a fourth family here would otherwise render "Three -- a, b,
    # c, d --".
    lane_corrected_ever = sorted(set(lane_corrected) | set(LANE_CORRECTED))
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
    served_through_their_lane = sorted(
        family
        for family, entry in slices.items()
        if entry["served_through_its_declared_lane"]
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
            mismatch_narration(lane_corrected_ever)
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
        "named_delivery_rule": (
            "Umbrella Amendment P (2026-08-16): the walk-side delivery of "
            "damage_routing -- the one row Ruling 2's stop clause fired on -- "
            "is the program rider system and the kernel state paths ALREADY IN "
            "THE TREE, named per declared payload family. Death's Dance's "
            "deferred-damage routing is a Defer rider on the holder's incoming "
            "damage events, The Collector's threshold execute an Execute rider "
            "on outgoing damage, and Serpent's Fang's shield reduction the "
            "kernel's barrier-state adjustment path. Naming a standing "
            "mechanism is an amendment's act and never a lane's (Amendment K's "
            "precedent), so what this file does with the name is RESOLVE it: "
            "each mechanism is looked up in the kernel's own declarations on "
            "every run, and a declaration the ruling does not name -- or a "
            "named mechanism that leaves the kernel -- turns the term unnamed "
            "again, re-stops the row and says which, because the ruling's own "
            "conditional stop is that the kernel is never extended inside a "
            "retirement slice."
        ),
        "named_delivery_resolution": _named_delivery_resolution(declarations),
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
        "lane_correction_rule": (
            "Umbrella Amendment Q (2026-08-16): a family whose walk-side need "
            "is satisfied THROUGH its declared serving lane does not need -- "
            "and must not declare -- a RECEIPT_WALK interpreter lane, because "
            "one producer is what the one-engine thesis demands. RECEIPT_WALK "
            "leaves _FAMILY_LANES for exactly the three measured families the "
            "defence resolver feeds, in Amendment O, Ruling 1's shape and on a "
            "different ground, and their rows close as lane-declaration "
            "CORRECTIONS rather than as retirements. The ground is checked in "
            "BOTH directions on every run -- the walk consumes what the "
            "resolver built, source-asserted per declaration; and removing the "
            "serving interpreter flips every declaring owner to withheld with "
            "the missing pair named, never to a silent zero -- and the lane "
            "re-enters if a mechanic of the family ever authors walk-priced "
            "rows the resolver does not feed. This is not the D-40 move: the "
            "declaration is corrected on a measured ground recorded in the "
            "umbrella with its check, rather than edited to move a counter."
        ),
        "rows_served_through_their_declared_lane": served_through_their_lane,
        "closed_by_authority_reclassification": reclassified_rows(),
        "closed_by_lane_declaration_correction": corrected_rows(),
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
    failures.extend(
        f"{key}: committed value differs from derived"
        for key in (
            "scheduled_slices",
            "slices_whose_retiring_lane_amendment_k_corrects",
            "slices_whose_ruled_act_is_already_performed",
            "named_delivery_rule",
            "named_delivery_resolution",
            "triage_by_class",
            "triage_rows_stopping_the_next_retirement_round",
            "closed_by_authority_reclassification",
            "lane_correction_rule",
            "rows_served_through_their_declared_lane",
            "closed_by_lane_declaration_correction",
        )
        if committed.get(key) != fresh[key]
    )
    resolution = fresh["named_delivery_resolution"]
    if not resolution["covers_every_declaration"]:
        failures.append(
            "named delivery: umbrella Amendment P's mapping no longer covers "
            f"every declaration of {resolution['family']} -- "
            + "; ".join(resolution["unanswered"])
        )
    for family, entry in fresh["families"].items():
        evidence = entry.get("lane_correction_evidence")
        if evidence is not None and not evidence["holds"]:
            failures.append(
                f"family {family!r}: its walk-side need is served through the "
                "lane it declares and umbrella Amendment Q's check no longer "
                "holds for it, so the ground under a lane-declaration "
                "correction is gone"
            )
    failures.extend(_reclassification_failures())
    failures.extend(_lane_correction_failures())
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
