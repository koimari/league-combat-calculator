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

import ast
import json
from pathlib import Path

from scripts import behavior_frontier
from src.calculator import interpreters
from src.calculator import item_behavior_catalog as catalog
from src.calculator import item_coverage
from src.calculator.interpreters.stat_derivation import declared_stat_derivations
from src.calculator.item_behavior import ThresholdRegenRule

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


def test_the_claim_evidence_containers_are_committed_beside_the_counter() -> None:
    """Amendment A's Class C arm is diff-gated exactly like the module sets.

    The umbrella's dated amendment (criterion 7) rules Phase 1's authored
    claim-evidence corpus and ``_REVIEW_ISSUE_REFS`` out of counter 2.  An
    exclusion that big has to be a diff in a committed artifact, per container
    and not merely per module, or the counter can be driven to its target by
    editing the tool.
    """
    block = _receipt()["exclusions"]["class_c_claim_evidence_containers"]
    declared = behavior_frontier.CLASS_C_CLAIM_EVIDENCE_CONTAINERS
    assert set(block["containers"]) == set(declared)
    for module, containers in declared.items():
        assert set(block["containers"][module]) == set(containers)
        # Only a Class B module may carry one: elsewhere it would excuse
        # counter 1, which is the escape hatch the receipt exists to close.
        assert module in behavior_frontier.CLASS_B_CLAIM_PROSE
        for name, reason in containers.items():
            assert len(reason.strip()) > 20, name
    assert "Amendment A" in block["amendment"]


def test_every_excluded_container_binds_something_in_its_module() -> None:
    """A stale exclusion excuses nothing and reads as though it did."""
    for (
        module,
        containers,
    ) in behavior_frontier.CLASS_C_CLAIM_EVIDENCE_CONTAINERS.items():
        source = (ROOT / "src" / module).read_text(encoding="utf-8")
        bound = set(behavior_frontier.top_level_bindings(ast.parse(source)).values())
        assert set(containers) <= bound, module


def test_counter_two_is_measured_net_of_the_committed_exclusions() -> None:
    """The netting is arithmetic over the receipt, not a number in prose.

    Gross minus the committed containers is the counter, and what survives is
    the population the amendment deliberately left counted.
    """
    report = behavior_frontier.scan()
    per_container = report.claim_evidence_by_container["calculator/item_coverage.py"]
    assert set(per_container) == set(
        behavior_frontier.CLASS_C_CLAIM_EVIDENCE_CONTAINERS[
            "calculator/item_coverage.py"
        ]
    )
    gross = report.counter_2 + report.class_c_claim_evidence_sites
    assert report.class_c_claim_evidence_sites == sum(per_container.values())
    assert report.counter_2 == gross - report.class_c_claim_evidence_sites
    # NO_RUNTIME_BEHAVIOR is the bound, so it stays counted: excluding it would
    # make the target compare a number with itself removed.
    assert report.by_module["calculator/item_coverage.py"]["counter_2"] == len(
        item_coverage.NO_RUNTIME_BEHAVIOR
    )


def test_the_surviving_counter_two_population_is_the_reviewed_set_itself() -> None:
    """The Class B description, checked against the tree instead of trusted.

    The receipt says item_coverage is Class B because one name-keyed container
    survived 3.8's collapse there.  That is a claim about which binding every
    remaining site sits in, and the tally beside it — a count — cannot see the
    difference between twenty-one reviewed members and twenty-one sites that
    regrew somewhere else in the module.  A class description no gate can
    contradict is the prose this counter is named for, living inside the
    instrument that measures it.
    """
    sites = [
        site
        for site in behavior_frontier.name_sites(
            behavior_frontier.SRC_ROOT, behavior_frontier.item_names()
        )
        if site.klass == "counter_2"
    ]
    assert {site.container for site in sites} == {"NO_RUNTIME_BEHAVIOR"}
    assert {site.name for site in sites} == set(item_coverage.NO_RUNTIME_BEHAVIOR)


def test_a_container_exclusion_outside_class_b_is_refused() -> None:
    """R-05: the arm's red, on the clause that keeps it off counter 1."""
    report = behavior_frontier.scan()
    committed = behavior_frontier.build_receipt(report)
    fresh = json.loads(json.dumps(committed))
    fresh["exclusions"]["class_c_claim_evidence_containers"]["containers"][
        "calculator/damage.py"
    ] = {"SOMETHING": "a reason"}
    committed["exclusions"]["class_c_claim_evidence_containers"]["containers"][
        "calculator/damage.py"
    ] = {"SOMETHING": "a reason"}

    failures = behavior_frontier._claim_evidence_failures(  # noqa: SLF001
        committed, fresh
    )

    assert any("is not a Class B module" in failure for failure in failures)


def test_a_moved_container_exclusion_fails_the_gate() -> None:
    """R-05: dropping one from the receipt is a diff, not a quiet improvement."""
    receipt = _receipt()
    receipt["exclusions"]["class_c_claim_evidence_containers"]["containers"][
        "calculator/item_coverage.py"
    ].pop("_SOURCE_REFS")
    failures = behavior_frontier.check(behavior_frontier.scan(), receipt)
    assert any("_SOURCE_REFS" in failure for failure in failures)

    receipt = _receipt()
    receipt["exclusions"].pop("class_c_claim_evidence_containers")
    failures = behavior_frontier.check(behavior_frontier.scan(), receipt)
    assert any("no claim-evidence exclusion section" in failure for failure in failures)


def test_a_site_outside_an_excluded_container_still_counts(tmp_path: Path) -> None:
    """The arm is per container, so the same module still feeds counter 2."""
    fresh = tmp_path / "src"
    (fresh / "calculator").mkdir(parents=True)
    (fresh / "calculator" / "item_coverage.py").write_text(
        '_SOURCE_REFS = {"Black Cleaver": ("url", 1)}\n'
        'SOMETHING_ELSE = {"Eclipse": "a claim nobody derived"}\n',
        encoding="utf-8",
    )
    report = behavior_frontier.scan(fresh)
    assert report.counter_2 == 1
    assert report.class_c_claim_evidence_sites == 1
    assert report.claim_evidence_by_container == {
        "calculator/item_coverage.py": {"_SOURCE_REFS": 1}
    }


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


def test_the_committed_refusal_set_is_what_the_fold_measures() -> None:
    """The compiled walk's refusals, gated by set equality (D-40).

    What the derivation-beside-legacy block became once the flip deleted the
    legacy.  The receipt records which owners the compiled score walk refuses
    and which family made it refuse, and both halves are compared to a fresh
    fold, so a declaration that changes which builds fall back is a diff in a
    committed artifact rather than a number that quietly improved.
    """
    receipt = _receipt()["compiled_walk_refusals"]
    measured = behavior_frontier.compiled_walk_refusals()

    assert set(receipt["refused"]) == set(measured["refused"])
    assert receipt["refused"] == measured["refused"]
    assert receipt["scope"] == "survival_ledger_transition"
    assert receipt["symbol"] == "interpreters.compilability_for"


def test_the_hand_set_is_gone_and_the_fold_is_what_the_gate_reads() -> None:
    """Criterion 13, over the source tree and through the gate itself.

    The retired symbol has zero occurrences in ``src/`` — not as a binding
    and not as a sentence about one, because a name that survives in prose is
    how a reader learns to look for something that is not there — and the
    build-level gate that used to read it now answers from the fold: an owner
    the fold refuses is refused by the gate, and an owner it does not is not.
    Both directions, so a gate wired to something else entirely could not
    pass this by refusing everything.
    """
    retired = "COMPILED_WALK_" + "UNREPRESENTABLE_ITEMS"
    holders = [
        path.relative_to(ROOT).as_posix()
        for path in sorted((ROOT / "src").rglob("*.py"))
        if retired in path.read_text(encoding="utf-8")
    ]
    assert holders == []

    refused = set(behavior_frontier.compiled_walk_refusals()["refused"])
    for name in sorted(behavior_frontier.item_names()):
        # The declared threshold regeneration is the one conditional answer,
        # and it is conditional on stats this call does not supply, so it is
        # asked separately below rather than folded into this equivalence.
        if name == "Warmog's Armor":
            continue
        receipt = interpreters.uncompilable_item_receipt([{"name": name}])
        assert (receipt is not None) == (name in refused), name
        if receipt is not None:
            assert receipt == f"item_mechanic={name}"


def test_the_conditional_holder_falls_back_only_while_its_ticks_are_live() -> None:
    """The gate's one conditional, read off the declaration and not a name.

    A threshold regeneration's ticks are authored in the event walk once the
    holder's bonus health passes the declared threshold, so an inactive
    holder is numerically identical in both walks and must not fall back.
    The threshold comes from the rule; nothing here names the item that
    happens to carry it, and the case dies honestly if the declaration does.
    """
    holders = [
        rule.owner
        for owner in sorted(catalog.rule_owners())
        for rule in catalog.behavior_rules(owner)
        if isinstance(rule.payload, ThresholdRegenRule)
    ]
    assert holders, "no declaration carries a threshold regeneration"
    build = [{"name": holders[0]}]
    threshold = declared_stat_derivations(holders[:1], ThresholdRegenRule)[0].value(
        "bonus_health_threshold"
    )

    assert interpreters.uncompilable_item_receipt(build) is not None
    assert (
        interpreters.uncompilable_item_receipt(
            build, loadout_stats={"bonus_health": threshold - 1.0}
        )
        is None
    )
    assert (
        interpreters.uncompilable_item_receipt(
            build, loadout_stats={"bonus_health": threshold}
        )
        is not None
    )
    assert (
        interpreters.uncompilable_item_receipt(build, threshold_ticks_compiled=True)
        is None
    )


def test_the_committed_refusal_gate_fails_when_the_section_is_deleted() -> None:
    """R-05: the check reproduces its own red on demand."""
    report = behavior_frontier.scan()
    committed = _receipt()
    committed.pop("compiled_walk_refusals")

    failures = behavior_frontier.check(report, committed)

    assert any("compiled_walk_refusals" in failure for failure in failures)


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

    ``per_rule_receipted`` is empty since H5's stage, and its emptiness is
    asserted rather than dropped: ``delta_amp``'s compiled lane was its only
    member, the flip made those rules ``Compilable``, and the lane moved into
    the dated table because a route still has to be named for it.  The
    per-rule form is not retired — it is the branch a future ``ReceiptOnly``
    would take, and ``tests/test_interpreters_registry.py`` drives it on a
    stub so an empty population here is not an untested one.
    """
    receipts = behavior_frontier.build_receipt(behavior_frontier.scan())["counters"][
        "counter_4"
    ]["receipts"]
    assert receipts["unreceipted"] == []
    assert receipts["per_rule_receipted"] == []
    assert "delta_amp/compiled_score_walk" in receipts["dated"]
    assert set(receipts["dated"]) == {
        f"{family.value}/{lane.value}"
        for family, lane in interpreters.UNSERVED_LANE_RECEIPTS
    }
    for pair, row in receipts["dated"].items():
        assert row["reason"].strip(), f"{pair} carries no reason"
        assert row["retires_at"].strip(), f"{pair} carries no retiring stage"


def test_every_gap_row_carries_its_route_into_the_committed_artifact() -> None:
    """The route is content, so it rides the receipt a reader meets.

    ``interpreters`` checks a route against its own registry at import; this
    is the other reader — the committed artifact — because a route that
    changed with no diff anywhere would be a claim about which engine
    produces a number, moved silently.
    """
    dated = _receipt()["counters"]["counter_4"]["receipts"]["dated"]
    for (family, lane), row in interpreters.UNSERVED_LANE_RECEIPTS.items():
        recorded = dated[f"{family.value}/{lane.value}"]
        assert recorded["via"] == [route.value for route in row.via]
        assert recorded["via"], f"{family.value}/{lane.value} records no route"


def test_a_moved_route_fails_the_gate() -> None:
    """R-05's red for the route clause, at the artifact rather than at import."""
    receipt = _receipt()
    receipt["counters"]["counter_4"]["receipts"]["dated"]["on_hit_strike/receipt_walk"][
        "via"
    ] = ["defense_resolver"]
    failures = behavior_frontier.check(behavior_frontier.scan(), receipt)
    assert any("routed through" in failure for failure in failures)


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


def test_counter_four_defers_in_writing_what_this_phase_cannot_close() -> None:
    """Amendment B: every deferred gap names its reason and its creditor.

    The umbrella's dated amendment (criterion 7) rules the receipt-walk gaps
    that only Phase 4's S3 can retire into committed deferral rows, and makes
    the Phase-3 exit target 0 net of them.  A deferral is a promise with a
    creditor, so each row carries the tree's own reason and the stage that
    owes it — never a stage this module invented.
    """
    block = _receipt()["counters"]["counter_4"]["deferrals"]
    assert set(block["rows"]) == set(behavior_frontier.COUNTER_4_DEFERRALS)
    open_gaps = {
        f"{family.value}/{lane.value}"
        for family, lane in interpreters.uninterpreted_pairs()
    }
    for key, row in block["rows"].items():
        assert key in open_gaps, key
        assert row["reason"].strip(), key
        assert row["recorded_stage"] == row["retires_at"], key
        assert "Phase 4 S3" in row["recorded_stage"], key
    # Every deferral is on the receipt walk; the pair engine defers nothing,
    # which is why criterion 4's pair-engine half is discharged outright.
    assert set(block["by_lane"]) == {"receipt_walk"}


def test_counter_four_targets_are_measured_net_of_the_deferrals() -> None:
    """The netting is arithmetic on the entry, not a smaller bare number."""
    targets = _receipt()["targets"]["targets"]
    for lane in behavior_frontier.COUNTER_4_TARGET_LANES:
        entry = targets[f"counter_4/{lane}"]
        assert entry["measured"] == entry["gross"] - entry["deferred"]
        assert entry["met"], lane
    assert targets["counter_4/receipt_walk"]["deferred"] == len(
        behavior_frontier.COUNTER_4_DEFERRALS
    )
    assert targets["counter_4/pair_engine"]["gross"] == 0


def test_a_deferral_that_outlives_its_gap_fails_the_gate() -> None:
    """R-05: the red for the clause that stops a stale row excusing a counter."""
    report = behavior_frontier.scan()
    committed = behavior_frontier.build_receipt(report)
    fresh = json.loads(json.dumps(committed))
    stale = "no_such_family/receipt_walk"
    fresh["counters"]["counter_4"]["deferrals"]["rows"][stale] = {
        "recorded_stage": "Phase 4 S3 — one kernel, five views",
        "reason": "invented",
        "retires_at": "Phase 4 S3 — one kernel, five views",
    }
    committed["counters"]["counter_4"]["deferrals"]["rows"][stale] = fresh["counters"][
        "counter_4"
    ]["deferrals"]["rows"][stale]

    failures = behavior_frontier._deferral_failures(committed, fresh)  # noqa: SLF001

    assert any("is not an open gap" in failure for failure in failures)


def test_a_deferral_dated_against_the_tree_fails_the_gate() -> None:
    """A stage the tree's own receipt does not say is not a creditor."""
    report = behavior_frontier.scan()
    committed = behavior_frontier.build_receipt(report)
    fresh = json.loads(json.dumps(committed))
    row = fresh["counters"]["counter_4"]["deferrals"]["rows"][
        "on_hit_strike/receipt_walk"
    ]
    row["recorded_stage"] = "some stage nobody scheduled"

    failures = behavior_frontier._deferral_failures(committed, fresh)  # noqa: SLF001

    assert any("the tree's receipt says" in failure for failure in failures)


def test_a_moved_or_missing_deferral_set_fails_the_gate() -> None:
    """D-40: the rows are diff-gated exactly like the exclusions are."""
    receipt = _receipt()
    receipt["counters"]["counter_4"]["deferrals"]["rows"].pop("delta_amp/receipt_walk")
    failures = behavior_frontier.check(behavior_frontier.scan(), receipt)
    assert any("committed deferral set differs" in failure for failure in failures)

    receipt = _receipt()
    receipt["counters"]["counter_4"].pop("deferrals")
    failures = behavior_frontier.check(behavior_frontier.scan(), receipt)
    assert any("no deferral rows" in failure for failure in failures)


def test_every_counter_carries_its_target_and_the_gap_left_to_it() -> None:
    """The gate compares a counter to its target, not only to the receipt.

    Criterion 1's second clause and criterion 4 were dischargeable-looking on
    a green ``--check`` because nothing in it read a target at all.  The block
    records the bound each target resolves to, derived rather than typed.
    """
    targets = _receipt()["targets"]["targets"]
    assert set(targets) == {
        "counter_1",
        "counter_2",
        "counter_3",
        "counter_4/pair_engine",
        "counter_4/receipt_walk",
    }
    assert targets["counter_2"]["bound"] == len(item_coverage.NO_RUNTIME_BEHAVIOR)
    for key, entry in targets.items():
        assert entry["criterion"], key
        assert entry["met"] == (entry["measured"] <= entry["bound"]), key
        assert entry["gap"] == max(entry["measured"] - entry["bound"], 0), key


def test_an_outstanding_target_names_what_the_tree_says_retires_it() -> None:
    """``owed_to`` is read from the tree's own receipts, never written here.

    Empty is a legal answer and an honest one — it says no receipt in the tree
    schedules the remainder, which is a fact worth committing rather than a
    blank filled in with a guess.
    """
    targets = _receipt()["targets"]["targets"]
    assert targets["counter_4/receipt_walk"]["owed_to"] == "; ".join(
        sorted(
            {
                row.retires_at
                for (family, lane), row in interpreters.UNSERVED_LANE_RECEIPTS.items()
                if lane.value == "receipt_walk"
                and (family, lane) not in interpreters.INTERPRETERS
            }
        )
    )


def test_a_counter_drifting_away_from_its_target_fails_the_gate() -> None:
    """R-05's red for the target ratchet: the gap may shrink and never grow."""
    report = behavior_frontier.scan()
    committed = behavior_frontier.build_receipt(report)
    committed["targets"]["targets"]["counter_2"]["measured"] -= 1
    failures = behavior_frontier.check(report, committed)
    assert any("counter_2 moved away from its target" in f for f in failures)


def test_a_met_target_recorded_outstanding_fails_the_gate() -> None:
    """A target the tree has reached may not stay recorded as owed."""
    report = behavior_frontier.scan()
    committed = behavior_frontier.build_receipt(report)
    committed["targets"]["targets"]["counter_1"]["met"] = False
    failures = behavior_frontier.check(report, committed)
    assert any("counter_1 is met=True in the tree" in f for f in failures)


def test_a_moved_bound_is_a_deliberate_diff_in_the_artifact() -> None:
    """Reviewing an item into NO_RUNTIME_BEHAVIOR moves counter 2's target."""
    report = behavior_frontier.scan()
    committed = behavior_frontier.build_receipt(report)
    committed["targets"]["targets"]["counter_2"]["bound"] += 1
    failures = behavior_frontier.check(report, committed)
    assert any("counter_2's bound moved" in f for f in failures)


def test_a_receipt_missing_the_targets_section_fails_closed() -> None:
    """Deleting what the target gate reads must fail it, never skip it."""
    report = behavior_frontier.scan()
    committed = behavior_frontier.build_receipt(report)
    del committed["targets"]
    failures = behavior_frontier.check(report, committed)
    assert any("no targets section" in f for f in failures)

    committed = behavior_frontier.build_receipt(report)
    del committed["targets"]["targets"]["counter_3"]
    failures = behavior_frontier.check(report, committed)
    assert any("counter_3 is not in the committed receipt" in f for f in failures)


def test_every_deferral_to_a_shipped_stage_is_declared_overdue() -> None:
    """Amendment B's exit sentence, as a state a reader can read.

    "Phase 4's exit re-asserts them retired" was unmet for a whole phase with
    nothing in the tree saying so.  Now every row whose stage has shipped
    carries ``overdue`` and a blocker naming an artifact a reader can open.
    """
    rows = _receipt()["counters"]["counter_4"]["deferrals"]["rows"]
    overdue = {key: row for key, row in rows.items() if row["overdue"]}
    assert overdue, "no row is overdue, so this clause is asserting nothing"
    for key, row in overdue.items():
        assert row["recorded_stage"] in behavior_frontier.completed_stages(), key
        assert row["blocked_on"].startswith("docs/receipts/"), key
        assert row["overdue_because"], key


def test_a_row_whose_stage_shipped_without_saying_so_fails_the_gate() -> None:
    """R-05: the red for the third way a deferral goes wrong.

    The gate already refuses a row whose gap is gone and a row the tree dates
    elsewhere.  This is the one it could not see: the due date passes and the
    row says nothing.
    """
    report = behavior_frontier.scan()
    committed = behavior_frontier.build_receipt(report)
    fresh = json.loads(json.dumps(committed))
    key = "delta_amp/receipt_walk"
    for block in (committed, fresh):
        row = block["counters"]["counter_4"]["deferrals"]["rows"][key]
        row["overdue"] = False
        row["blocked_on"] = ""

    failures = behavior_frontier._deferral_failures(committed, fresh)  # noqa: SLF001

    assert any("is not declared overdue with a blocker" in f for f in failures)


def test_an_overdue_claim_on_a_live_stage_fails_the_gate() -> None:
    """The other direction: overdue is a fact about a stage, not a mood."""
    report = behavior_frontier.scan()
    committed = behavior_frontier.build_receipt(report)
    fresh = json.loads(json.dumps(committed))
    key = "periodic/receipt_walk"
    for block in (committed, fresh):
        row = block["counters"]["counter_4"]["deferrals"]["rows"][key]
        row["recorded_stage"] = "a stage that has not shipped"
        row["retires_at"] = "a stage that has not shipped"

    failures = behavior_frontier._deferral_failures(committed, fresh)  # noqa: SLF001

    assert any("is not a completed stage" in f for f in failures)


def test_a_deferral_to_a_stage_nothing_declares_fails_the_gate() -> None:
    """The clause that makes the overdue rule come due on its own.

    ``COMPLETED_STAGES`` used to be a literal inside this module and was the
    sole trigger of the overdue rule, so a stage could ship and every row
    deferred to it stay silent until somebody remembered to edit the tool —
    the failure shape the campaign is named after, one level up.  A deferral
    may now only name a stage the committed record declares, and shippedness
    is read from the tree from then on.
    """
    report = behavior_frontier.scan()
    committed = behavior_frontier.build_receipt(report)
    fresh = json.loads(json.dumps(committed))
    key = "spellblade/receipt_walk"
    for block in (committed, fresh):
        row = block["counters"]["counter_4"]["deferrals"]["rows"][key]
        row["recorded_stage"] = "Phase 9 S1 — a stage no record declares"
        row["retires_at"] = "Phase 9 S1 — a stage no record declares"

    failures = behavior_frontier._deferral_failures(committed, fresh)  # noqa: SLF001

    assert any("campaign-stages.json declares" in f for f in failures)


def test_stage_completion_is_read_from_the_tree_not_from_a_declaration() -> None:
    """Both conjuncts, and neither of them a field somebody sets.

    A stage is shipped when the campaign range carries its slice tag *and* its
    declared successor's — the second conjunct is what stops a stage counting
    as shipped on its own opening commit.
    """
    declared = behavior_frontier.declared_stages()
    shipped = behavior_frontier.completed_stages()
    assert set(shipped) <= set(declared)
    assert "Phase 4 S3 — one kernel, five views" in shipped

    tags = behavior_frontier._tag_first_seen()  # noqa: SLF001
    for stage, row in declared.items():
        assert "shipped" not in row, f"{stage} declares shippedness rather than a tag"
        if stage in shipped:
            assert row["slice_tag"] in tags and row["followed_by"] in tags
            assert tags[row["slice_tag"]] in shipped[stage]


def test_every_declared_stage_carries_a_blocker_a_reader_can_open() -> None:
    """A stage record is only useful if its blocker names an artifact."""
    for stage, row in behavior_frontier.declared_stages().items():
        assert row["blocked_on"].startswith("docs/receipts/"), stage
        assert row["slice_tag"] and row["followed_by"], stage
