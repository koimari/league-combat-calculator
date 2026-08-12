"""The behaviour frontier's gate — counters, exclusions, and the reds.

A frontier is only worth the exclusions it stands on.  Two properties are
therefore checked here rather than trusted: the committed receipt's exclusion
sets are equal to the ones the script declares (so an edit is a diff in a
committed artifact, D-40), and counter 1's default is the *strictest* class,
so a name-dispatch site in a brand-new module raises the counter instead of
escaping it.  The second is the negative the phase document asks for by name:
"no site remains in any of the thirteen baseline modules" would be
dischargeable by creating a fourteenth.
"""

import json
from pathlib import Path

from scripts import behavior_frontier
from src.calculator import interpreters
from src.calculator import item_behavior_catalog as catalog
from src.calculator import item_coverage

ROOT = Path(__file__).parents[1]
RECEIPT_PATH = ROOT / "docs" / "behavior-frontier.json"


def _receipt() -> dict:
    """The committed frontier artifact."""
    return json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))


def test_the_receipt_is_committed_and_reproduces_on_this_commit() -> None:
    """R-36: the receipt moves with the slice that moves a counter."""
    assert RECEIPT_PATH.exists()
    assert behavior_frontier.check(behavior_frontier.scan()) == ()


def test_the_exclusion_sets_are_committed_beside_the_counters() -> None:
    """D-40: exclusions that live only in the tool can be edited to zero."""
    receipt = _receipt()
    committed_c = set(receipt["exclusions"]["class_c_declarative_homes"]["modules"])
    committed_d = set(receipt["exclusions"]["class_d_non_behavioural"]["modules"])
    committed_b = set(receipt["exclusions"]["class_b_claim_prose"]["modules"])
    assert committed_c == set(behavior_frontier.CLASS_C_DECLARATIVE_HOMES)
    assert committed_d == set(behavior_frontier.CLASS_D_NON_BEHAVIOURAL)
    assert committed_b == set(behavior_frontier.CLASS_B_CLAIM_PROSE)
    assert not committed_c & committed_d
    assert not committed_c & committed_b
    assert not committed_d & committed_b


def test_every_excluded_module_carries_a_reason() -> None:
    """An exclusion with no stated cause is the prose this phase retires."""
    for block in (
        behavior_frontier.CLASS_C_DECLARATIVE_HOMES,
        behavior_frontier.CLASS_D_NON_BEHAVIOURAL,
        behavior_frontier.CLASS_B_CLAIM_PROSE,
    ):
        for module, reason in block.items():
            assert (ROOT / "src" / module).exists(), module
            assert len(reason.strip()) > 20, module


def test_counter_three_reads_the_catalog_rather_than_a_second_count() -> None:
    """One population, one number: the frontier and the catalog cannot drift."""
    report = behavior_frontier.scan()
    assert report.counter_3 == catalog.undeclared_entry_count()
    assert report.counter_4 == len(interpreters.uninterpreted_pairs())


def test_a_name_dispatch_site_in_a_new_module_raises_counter_one(
    tmp_path: Path,
) -> None:
    """The default is the strictest class, so a fourteenth module cannot hide."""
    fresh = tmp_path / "src"
    (fresh / "calculator").mkdir(parents=True)
    (fresh / "calculator" / "brand_new_engine.py").write_text(
        'ITEM = "Black Cleaver"\n', encoding="utf-8"
    )
    report = behavior_frontier.scan(fresh)
    assert report.counter_1 == 1
    assert report.by_module["calculator/brand_new_engine.py"] == {"counter_1": 1}


def test_a_site_in_a_declared_home_does_not_count(tmp_path: Path) -> None:
    """The other half: an exclusion has to actually exclude, or it is noise."""
    fresh = tmp_path / "src"
    (fresh / "calculator").mkdir(parents=True)
    (fresh / "calculator" / "item_effects.py").write_text(
        'ITEM = "Black Cleaver"\n', encoding="utf-8"
    )
    report = behavior_frontier.scan(fresh)
    assert report.counter_1 == 0
    assert report.class_c_sites == 1


def test_the_gate_reproduces_its_own_red() -> None:
    """R-05: a check nobody has seen fail is indistinguishable from no check."""
    receipt = _receipt()
    receipt["counters"]["counter_1"]["value"] += 1
    failures = behavior_frontier.check(behavior_frontier.scan(), receipt)
    assert any("counter_1" in failure for failure in failures)

    receipt = _receipt()
    receipt["exclusions"]["class_c_declarative_homes"]["modules"].pop(
        "calculator/trigger_stream.py"
    )
    failures = behavior_frontier.check(behavior_frontier.scan(), receipt)
    assert any("class_c" in failure for failure in failures)


def test_the_reviewed_nothing_set_is_bounded_and_every_member_is_sourced() -> None:
    """Counter 3 cannot be reached by reviewing the backlog into silence.

    Empty at the skeleton; filled at 3.8, when the flip renamed the reviewed
    stats-only claim into ``NO_RUNTIME_BEHAVIOR`` and made it the one reviewed
    registry that survives.  Three properties hold from here on: the committed
    member set equals the declared one, the size never passes the ceiling
    measured before the phase, and every member names the wiki revision its
    review read.
    """
    block = _receipt()["no_runtime_behavior"]
    assert block["members"], "the set is populated from 3.8 onwards"
    assert len(block["members"]) <= block["ratchet_ceiling"]
    assert sorted(block["sourced"]) == sorted(block["members"])
    assert sorted(block["members"]) == sorted(item_coverage.NO_RUNTIME_BEHAVIOR)


def test_the_reviewed_nothing_ratchet_reproduces_its_red(monkeypatch) -> None:
    """R-05: the ceiling and the set-equality clause each fail loud on demand.

    The ceiling is driven through the module constant and not through the
    receipt, deliberately: a ceiling a receipt could lower is a ratchet the
    thing it bounds gets to set.
    """
    report = behavior_frontier.scan()
    committed = _receipt()
    monkeypatch.setattr(behavior_frontier, "NO_RUNTIME_BEHAVIOR_CEILING", 0)
    over_ceiling = behavior_frontier.check(report, committed)
    assert any("ratchet ceiling" in failure for failure in over_ceiling)
    monkeypatch.undo()

    moved = behavior_frontier.check(
        report,
        committed
        | {
            "no_runtime_behavior": committed["no_runtime_behavior"] | {"members": ["a"]}
        },
    )
    assert any("committed member set differs" in failure for failure in moved)


def test_the_ten_h4_tags_ride_the_frontier() -> None:
    """Declared, reasoned, and carried where the decision can be measured."""
    block = _receipt()["h4_tags"]
    assert set(block["dead"]) == set(catalog.H4_DEAD_TAGS)
    assert set(block["self_referential"]) == set(catalog.H4_SELF_REFERENTIAL_TAGS)
    assert set(block["reasons"]) == set(block["dead"]) | set(block["self_referential"])
    assert set(block["families"]) == set(block["reasons"])


def test_the_priors_are_carried_beside_the_measurement() -> None:
    """R-07's discipline: a prior is never a gate, and its divergence has a cause."""
    priors = _receipt()["priors"]
    assert set(priors) >= {"counter_1", "counter_2", "counter_3", "class_c", "class_d"}
    for name, prior in priors.items():
        assert prior["cause"].strip(), name


def test_counters_five_to_seven_are_not_reported_here() -> None:
    """They are Phase 4's and live in docs/migration-frontier.json."""
    receipt = _receipt()
    assert set(receipt["counters"]) == {
        "counter_1",
        "counter_2",
        "counter_3",
        "counter_4",
    }


# ---------------------------------------------------------------------------
# The zero-policy frontier — the guard the ruled exception ships with (D-24)
# ---------------------------------------------------------------------------


def test_the_zero_policy_populations_are_committed_and_reproduce() -> None:
    """The three measured populations are in the receipt, not in the tool."""
    receipt = _receipt()["zero_policy_frontier"]
    measured = behavior_frontier.zero_policy_frontier()
    assert receipt["totals"] == measured.totals()
    assert receipt["produced_fallbacks_by_receiver"] == measured.produced_fallbacks
    assert receipt["hand_built_entries_by_module"] == measured.hand_built_entries
    assert receipt["issue"].strip()
    assert "slotlib" in receipt["declared_default"]
    assert "inputs.py" in receipt["input_vocabularies"]


def test_the_forbidden_population_is_empty_and_the_gate_says_so() -> None:
    """D-24's source assertion is a refusal, not a counter.

    A champion input read with a literal fallback fails ``--check`` on its
    first occurrence, whatever the receipt records — the ratchet applies to
    the shape on blocks the tree *produced*, never to the three inputs.
    """
    report = behavior_frontier.scan()
    assert behavior_frontier.zero_policy_frontier().forbidden_input_fallbacks == ()
    assert not behavior_frontier.check(report, behavior_frontier.build_receipt(report))


def test_a_planted_input_fallback_fails_the_gate_end_to_end(tmp_path) -> None:
    """The red is driven by real source under the real tree, not by a seam.

    Every other negative here decrements a committed number through
    ``check``'s ``committed`` argument, which exercises the comparison and
    not the measurement.  This one writes a module into
    ``src/calculator/champions/`` and runs ``main(["--check"])`` against the
    committed receipt, so the scan, the classification and the gate are all
    on the path.  The file is removed in ``finally`` and the check is asserted
    green again afterwards.
    """
    planted = behavior_frontier.CHAMPIONS_ROOT / "_frontier_negative_fixture.py"
    planted.write_text(
        "def parse(ctx):\n"
        '    """A stack count nothing wired, defaulted to a literal."""\n'
        "    return ctx.options.get('q_stacks', 3)\n",
        encoding="utf-8",
    )
    try:
        assert behavior_frontier.main(["--check"]) == 1
    finally:
        planted.unlink()
    assert behavior_frontier.main(["--check"]) == 0


def test_a_new_produced_fallback_fails_the_gate() -> None:
    """R-05: the ratcheted half has a red it can produce on demand.

    ``check``'s ``committed`` seam stands in for a receipt taken before the
    site was added, which is exactly the situation the ratchet exists for.
    """
    report = behavior_frontier.scan()
    committed = behavior_frontier.build_receipt(report)
    committed["zero_policy_frontier"]["totals"]["produced_fallbacks"] -= 1
    failures = behavior_frontier.check(report, committed)
    assert any("produced_fallbacks grew" in failure for failure in failures)


def test_the_ratchet_is_per_key_not_only_per_total() -> None:
    """One module shrinking may not pay for another module growing."""
    report = behavior_frontier.scan()
    committed = behavior_frontier.build_receipt(report)
    section = committed["zero_policy_frontier"]["hand_built_entries_by_module"]
    victim, donor = sorted(section)[:2]
    section[victim] -= 1
    section[donor] += 1
    failures = behavior_frontier.check(report, committed)
    assert any(victim in failure for failure in failures)
    assert not any("hand_built_entries grew" in failure for failure in failures)


def test_a_receipt_missing_the_section_fails_closed() -> None:
    """A deleted section is a failure, never a skipped check."""
    report = behavior_frontier.scan()
    committed = behavior_frontier.build_receipt(report)
    del committed["zero_policy_frontier"]
    failures = behavior_frontier.check(report, committed)
    assert any("no zero_policy_frontier section" in failure for failure in failures)

    committed = behavior_frontier.build_receipt(report)
    del committed["zero_policy_frontier"]["totals"]["hand_built_entries"]
    del committed["zero_policy_frontier"]["hand_built_entries_by_module"]
    failures = behavior_frontier.check(report, committed)
    assert any("no total for hand_built_entries" in failure for failure in failures)
    assert any("no hand_built_entries_by_module" in failure for failure in failures)


def test_a_new_hand_built_entry_fails_the_gate() -> None:
    """The second population is ratcheted by the same rule as the first."""
    report = behavior_frontier.scan()
    committed = behavior_frontier.build_receipt(report)
    committed["zero_policy_frontier"]["totals"]["hand_built_entries"] -= 1
    failures = behavior_frontier.check(report, committed)
    assert any("hand_built_entries grew" in failure for failure in failures)


def test_shrinking_a_population_is_not_a_failure() -> None:
    """The ratchet is non-growing, not equality: migrating one is progress."""
    report = behavior_frontier.scan()
    committed = behavior_frontier.build_receipt(report)
    committed["zero_policy_frontier"]["totals"]["produced_fallbacks"] += 5
    failures = behavior_frontier.check(report, committed)
    assert not any("produced_fallbacks" in failure for failure in failures)


def test_the_scan_finds_a_planted_fallback_and_a_planted_entry(tmp_path) -> None:
    """The measurement is a seam over a tree, so it can be driven directly."""
    (tmp_path / "fake_champion.py").write_text(
        "def parse(ctx):\n"
        "    stacks = ctx.options.get('q_stacks', 3)\n"
        "    rank = entry.get('rank', 0)\n"
        "    return {'name': 'Q', 'total_raw': float(stacks + rank)}\n",
        encoding="utf-8",
    )
    frontier = behavior_frontier.zero_policy_frontier(tmp_path)
    assert frontier.totals() == {
        "forbidden_input_fallbacks": 1,
        "produced_fallbacks": 1,
        "hand_built_entries": 1,
    }
    assert frontier.produced_fallbacks == {"entry": 1}
    assert "fake_champion.py:2" in frontier.forbidden_input_fallbacks[0]


def test_the_compiled_walk_derivation_lands_beside_the_hand_set() -> None:
    """D-98's first half for ``COMPILED_WALK_UNREPRESENTABLE_ITEMS``.

    The derivation is landed beside the legacy set and its difference is
    committed, because at 3.8 the two are not set-equal.  The gate is set
    equality against the receipt in both directions, so a declaration that
    closes part of the gap is a diff in a committed artifact rather than a
    number that quietly improved.
    """
    receipt = _receipt()["compiled_walk_delta"]
    measured = behavior_frontier.compiled_walk_delta()

    assert set(receipt["legacy"]) == set(measured["legacy"])
    assert set(receipt["legacy_only"]) == set(measured["legacy_only"])
    assert set(receipt["derived_only"]) == set(measured["derived_only"])
    assert set(receipt["derived"]) == set(measured["derived"])


def test_the_flip_is_blocked_exactly_while_the_two_sets_disagree() -> None:
    """A gap with no stated cause is the prose this campaign deletes.

    The blockers are derived from the difference they describe, so this is an
    equivalence rather than a count: ``flip_blocked_by`` is non-empty **iff**
    a difference stands, and every member of either direction is named in it.
    A hand-written blocker could be true of a set the tree had already left —
    the earlier version of this receipt was, which is why the count heuristic
    it was checked with is gone.
    """
    receipt = _receipt()["compiled_walk_delta"]
    blockers = receipt["flip_blocked_by"]
    differing = [*receipt["legacy_only"], *receipt["derived_only"]]

    assert bool(blockers) == bool(differing), (
        "the receipt says blocked while the sets agree, or clear while they "
        "differ — the one thing this block may never do"
    )
    joined = " ".join(blockers)
    for member in differing:
        assert member in joined, f"{member} differs and no blocker names it"
    for reason in blockers:
        assert reason.strip()


def test_the_committed_delta_gate_fails_when_the_section_is_deleted() -> None:
    """R-05: the new check reproduces its own red on demand."""
    report = behavior_frontier.scan()
    committed = _receipt()
    committed.pop("compiled_walk_delta")

    failures = behavior_frontier.check(report, committed)

    assert any("compiled_walk_delta" in failure for failure in failures)


def test_a_member_with_a_compiled_rule_fails_the_ratchet() -> None:
    """R-05's red for the fourth clause, through the check's own seam.

    A reviewed absence beside a compiled rule is two contradictory claims about
    one item, and it is also how the ratchet's ceiling stops meaning anything:
    thirty-four members held live rules when the set was renamed from
    ``_REVIEWED_STATS_ONLY``, so the ceiling bounded a population two and a
    half times larger than the one that can reach the rung it gates.
    """
    report = behavior_frontier.scan()
    fresh = behavior_frontier.build_receipt(report)
    committed = json.loads(json.dumps(fresh))
    fresh["no_runtime_behavior"]["declaring"] = ["Spirit Visage"]

    failures = behavior_frontier._no_runtime_behavior_failures(  # noqa: SLF001
        committed, fresh
    )

    assert any("compile a BehaviorRule" in failure for failure in failures)


def test_no_reviewed_nothing_member_compiles_a_rule() -> None:
    """The live set passes the clause the seam above reproduces red."""
    block = behavior_frontier.no_runtime_behavior_block()

    assert block["members"]
    assert block["declaring"] == []


def test_counter_four_carries_the_reason_for_every_gap_it_counts() -> None:
    """The number and its content, in the artifact a reader meets.

    Counter 4 was a bare integer: thirty-four unserved lanes with no statement
    anywhere of why any one was acceptable.  Every gap a declaration reaches
    is now either a dated row naming the route its number arrives by, or a
    compiled lane refused by that rule's own ``ReceiptOnly`` — and
    ``unreceipted`` is empty because ``validate_registrations`` refuses to
    import a tree holding a gap in neither population, which is asserted here
    by the second route rather than assumed from the first.
    """
    receipts = behavior_frontier.build_receipt(behavior_frontier.scan())["counters"][
        "counter_4"
    ]["receipts"]
    assert receipts["unreceipted"] == []
    assert receipts["per_rule_receipted"] == ["delta_amp/compiled_score_walk"]
    assert set(receipts["dated"]) == {
        f"{family.value}/{lane.value}"
        for family, lane in interpreters.UNSERVED_LANE_RECEIPTS
    }
    for pair, row in receipts["dated"].items():
        assert row["reason"].strip(), f"{pair} carries no reason"
        assert row["retires_at"].strip(), f"{pair} carries no retiring stage"


def test_a_receipt_missing_the_unserved_lane_section_fails_closed() -> None:
    """Deleting what a gate reads must fail it, never skip it."""
    receipt = _receipt()
    receipt["counters"]["counter_4"].pop("receipts")
    failures = behavior_frontier.check(behavior_frontier.scan(), receipt)
    assert any("no unserved-lane receipts" in failure for failure in failures)


def test_a_moved_gap_receipt_is_a_diff_in_the_committed_artifact() -> None:
    """D-40: the content is set-equality gated, exactly like the exclusions."""
    receipt = _receipt()
    receipt["counters"]["counter_4"]["receipts"]["dated"].pop(
        "on_hit_strike/receipt_walk"
    )
    failures = behavior_frontier.check(behavior_frontier.scan(), receipt)
    assert any("committed dated set differs" in failure for failure in failures)
