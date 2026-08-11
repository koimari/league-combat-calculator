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


def test_the_reviewed_nothing_set_is_bounded_and_empty_at_the_skeleton() -> None:
    """Counter 3 cannot be reached by reviewing the backlog into silence."""
    block = _receipt()["no_runtime_behavior"]
    assert block["members"] == []
    assert block["ratchet_ceiling"] > 0
    failures = behavior_frontier.check(
        behavior_frontier.scan(),
        _receipt() | {"no_runtime_behavior": {"members": ["a"], "ratchet_ceiling": 0}},
    )
    assert any("ratchet ceiling" in failure for failure in failures)


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
    """The two measured populations are in the receipt, not in the tool."""
    receipt = _receipt()["zero_policy_frontier"]
    measured = behavior_frontier.zero_policy_frontier().totals()
    assert receipt["totals"] == measured
    assert receipt["issue"].strip()
    assert "slotlib" in receipt["declared_default"]


def test_a_new_literal_fallback_under_champions_fails_the_gate() -> None:
    """R-05: the guard has a red it can produce on demand.

    ``check``'s ``committed`` seam stands in for a receipt taken before the
    site was added, which is exactly the situation the ratchet exists for.
    """
    report = behavior_frontier.scan()
    committed = behavior_frontier.build_receipt(report)
    committed["zero_policy_frontier"]["totals"]["literal_fallbacks"] -= 1
    failures = behavior_frontier.check(report, committed)
    assert any("literal_fallbacks grew" in failure for failure in failures)


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
    committed["zero_policy_frontier"]["totals"]["literal_fallbacks"] += 5
    failures = behavior_frontier.check(report, committed)
    assert not any("literal_fallbacks" in failure for failure in failures)


def test_the_scan_finds_a_planted_fallback_and_a_planted_entry(tmp_path) -> None:
    """The measurement is a seam over a tree, so it can be driven directly."""
    (tmp_path / "fake_champion.py").write_text(
        "def parse(ctx):\n"
        "    stacks = ctx.options.get('q_stacks', 3)\n"
        "    return {'name': 'Q', 'total_raw': float(stacks)}\n",
        encoding="utf-8",
    )
    frontier = behavior_frontier.zero_policy_frontier(tmp_path)
    assert frontier.totals() == {"literal_fallbacks": 1, "hand_built_entries": 1}
    assert frontier.literal_fallbacks == {"options": 1}
