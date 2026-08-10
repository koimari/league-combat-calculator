"""Gate for the cast-dependency audit and its committed receipt.

Two jobs.  The first is the diff gate: ``docs/cast-dependency-audit.json``
is the committed record of what the declared-vs-inferred surface looks
like, and it is asserted equal — by set equality on every ledger — to what
the audit measures now.  The receipt moves with the slice that moves its
counts (R-36), so a ledger that changes without its receipt is red.

The second is the marker-reach evidence the audit itself demands.  The
audit derives the marker surface from the resolver's own apply-atom loop
and refuses to pass while any member lacks a negative test that withholds
or mutates it.  ``MARKER_NEGATIVE_TESTS`` below is where those tests are
declared, and each one drives ``detect_setup_consume_edges`` directly over
a synthetic kit built so that exactly one marker is load-bearing: with the
marker, an edge (or its citation); without it, a different answer.  A
synthetic kit rather than a cached champion, because "which champion
happens to author this today" is a roster fact that drifts, while "the
interpreter reads this key and the read matters" is the claim under test.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from scripts.cast_dependency_audit import (
    DECLARATION_ROUTES,
    RECEIPT_PATH,
    AuditDerivationError,
    _declaration_failures,
    _marker_ledger,
    apply_marker_keys,
    declared_negative_tests,
    run_audit,
)
from scripts.gate_receipt import SCHEMA_VERSION, validate_receipt
from src.calculator.ability_spec import DamagePart
from src.calculator.cast_dependency import CastDependency
from src.calculator.rotation_resolver import detect_setup_consume_edges

# Every marker the interpreter reads → the negative test that proves the
# read is load-bearing.  The audit reads this mapping out of this file and
# fails when the derived marker surface holds a key the mapping does not,
# which is how "a newly read key with no such test fails the audit" is
# enforced rather than remembered.
MARKER_NEGATIVE_TESTS = {
    "applies_dot_stack": "test_withholding_applies_dot_stack_drops_the_stack_edge",
    "cc_kind": "test_withholding_cc_kind_drops_the_cc_setup_fan_out",
    "cooldown": "test_zeroing_cooldown_disqualifies_the_setup_slot",
    "dot_duration": "test_withholding_dot_duration_drops_the_dot_consume_edge",
    "on_hit": "test_withholding_on_hit_changes_the_edge_citation",
    "parts": "test_withholding_parts_drops_the_cc_setup_fan_out",
    "stacking_dot": "test_withholding_stacking_dot_drops_the_stack_edge",
    "stat_buff": "test_withholding_stat_buff_drops_the_buff_edge",
    "target_debuff": "test_withholding_target_debuff_drops_the_shred_edge",
}

# The one champion whose declared option rotation the dot-consume fixture
# borrows: ``dot_consume`` is only ever declared by a module's OPTIONS
# rotation, so a fixture for it must run under a name that declares one.
_DOT_CONSUME_CHAMPION = "Cassiopeia"
_DOT_CONSUME_OPTION = {"E": ["target_poisoned"]}


# ─────────────────────────────────────────────────────────────────────
# Synthetic kits — one marker load-bearing at a time
# ─────────────────────────────────────────────────────────────────────


def _entry(**overrides):
    """One parsed ability entry: a castable damage row by default."""
    entry = {"cooldown": 8.0, "total_raw": 100.0, "parts": ()}
    entry.update(overrides)
    return entry


def _champion_data(attributes=None):
    """A synthetic cached champion carrying one wiki row per slot."""
    attributes = attributes or {}
    abilities = {}
    for slot in ("Q", "W"):
        abilities[slot] = [
            {
                "name": f"Synthetic {slot}",
                "effects": [
                    {
                        "description": "",
                        "leveling": [
                            {"attribute": attribute}
                            for attribute in attributes.get(slot, ())
                        ],
                    }
                ],
                "notes": "",
                "blurb": "",
            }
        ]
    return {"abilities": abilities}


def _edges(parsed, champion_data, *, champion="__synthetic__", option_keys=None):
    """The detector's answer for one synthetic kit."""
    return detect_setup_consume_edges(
        champion, parsed, champion_data, option_keys or {}
    )


def _pairs(edges):
    """The edge set as comparable tuples, citation excluded."""
    return sorted((edge.setup, edge.consume, edge.kind) for edge in edges)


def _withhold(parsed, slot, marker):
    """The same parse with one marker withheld from one slot."""
    mutated = {key: dict(value) for key, value in parsed.items()}
    if marker == "cc_kind":
        mutated[slot]["parts"] = tuple(
            dataclasses.replace(part, cc_kind=None)
            for part in mutated[slot].get("parts", ())
        )
    elif marker == "cooldown":
        mutated[slot]["cooldown"] = 0.0
    else:
        mutated[slot].pop(marker, None)
    return mutated


def _shred_kit():
    """Q shreds resistances, W is the burst it opens — a ``shred`` edge."""
    return {"Q": _entry(target_debuff={"armor": 20.0}), "W": _entry()}, _champion_data()


def _stack_kit(**setup_markers):
    """Q applies stacks, W consumes them — a ``stack_consume`` edge."""
    return (
        {"Q": _entry(**setup_markers), "W": _entry()},
        _champion_data({"W": ("Damage per stack",)}),
    )


def _cc_kit():
    """Q stuns, W is the damage it sets up — a ``cc_setup`` fan-out."""
    parsed = {
        "Q": _entry(
            parts=(DamagePart(damage_type="magic", amount=0.0, cc_kind="stun"),)
        ),
        "W": _entry(),
    }
    return parsed, _champion_data()


def _dot_kit():
    """Q applies the poison E's declared option consumes — ``dot_consume``."""
    parsed = {"Q": _entry(dot_duration=3.0), "E": _entry()}
    data = _champion_data()
    data["abilities"]["E"] = data["abilities"].pop("W")
    return parsed, data


# ─────────────────────────────────────────────────────────────────────
# The audit receipt
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def receipt():
    """The audit as measured now — one walk shared by every assertion."""
    return run_audit()


@pytest.fixture(scope="session")
def committed():
    """The committed receipt."""
    return json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))


class TestReceipt:
    def test_the_audit_passes(self, receipt) -> None:
        assert receipt["failures"] == []
        assert receipt["passed"] is True
        assert receipt["counts"]["failed"] == 0
        assert receipt["counts"]["passed"] == receipt["counts"]["total"]

    def test_the_receipt_carries_the_shared_envelope(self, receipt) -> None:
        validate_receipt(receipt)
        assert receipt["schema_version"] == SCHEMA_VERSION
        assert receipt["matrix"] == "cast_dependency_declarations"

    def test_the_committed_receipt_equals_what_the_audit_measures(
        self, receipt, committed
    ) -> None:
        """The diff gate, ledger by ledger, by set equality (R-36)."""
        assert set(committed["inferred_kind_coverage"]) == set(
            receipt["inferred_kind_coverage"]
        )
        for kind, producers in receipt["inferred_kind_coverage"].items():
            assert set(committed["inferred_kind_coverage"][kind]) == set(
                producers
            ), kind
        for ledger in (
            "declared_dependency_activation",
            "suppression_ledger",
            "conflict_ledger",
        ):
            assert _rows(committed[ledger]) == _rows(receipt[ledger]), ledger
        assert committed["authored_marker_reach"] == receipt["authored_marker_reach"]
        assert committed["acknowledged_gaps"] == receipt["acknowledged_gaps"]
        assert committed["option_matrix"] == receipt["option_matrix"]
        assert (
            committed["order_override_frontier"] == receipt["order_override_frontier"]
        )
        assert committed["counts"] == receipt["counts"]

    def test_the_walk_covers_every_cached_champion(self, receipt) -> None:
        matrix = receipt["option_matrix"]
        assert matrix["champions"] == 173
        assert matrix["states_walked"] > matrix["champions"]
        assert matrix["levels"] and matrix["builds"]


class TestInferredKindCoverage:
    def test_every_kind_but_the_acknowledged_gap_has_a_producer(self, receipt) -> None:
        empty = [
            kind
            for kind, producers in receipt["inferred_kind_coverage"].items()
            if not producers
        ]
        assert empty == ["enhanced_consume"]

    def test_the_gap_is_one_dated_reviewed_entry(self, receipt) -> None:
        """D-88 / H6: a dated one-line gap is auditable, a dead branch is not."""
        gaps = receipt["acknowledged_gaps"]
        assert len(gaps) == 1
        gap = gaps[0]
        assert gap["ledger"] == "inferred_kind_coverage"
        assert gap["member"] == "enhanced_consume"
        assert "D-88" in gap["decision"] and "H6" in gap["decision"]
        assert len(gap["dated"]) == len("YYYY-MM-DD")
        assert gap["reason"].strip()

    def test_deleting_the_gap_turns_the_audit_red(self) -> None:
        """The gate can reproduce its own red on demand (R-05).

        The acknowledged-gap list lives in the committed receipt rather
        than inside the tool (D-40), and this is the seam that proves the
        list is load-bearing: with no gaps, the unfilled kind fails.
        """
        ungapped = run_audit(acknowledged_gaps=())
        assert ungapped["passed"] is False
        assert [failure["item"] for failure in ungapped["failures"]] == [
            "inferred_kind_coverage:enhanced_consume"
        ]


class TestDeclarations:
    def test_every_declaration_is_active_somewhere(self, receipt) -> None:
        for row in receipt["declared_dependency_activation"]:
            assert row["active_states"] > 0, row

    def test_every_declaration_is_load_bearing_on_a_named_route(self, receipt) -> None:
        """Criterion 12, published rather than remembered.

        The routes are measured by deleting each declaration and asking
        what notices, and they live here — beside the activation counts
        and the source resolutions — so a reader of the committed receipt
        can tell which declaration carries weight and by what route
        without running anything.
        """
        for row in receipt["declared_dependency_activation"]:
            routes = row["load_bearing_routes"]
            assert routes, row
            assert set(routes) <= set(DECLARATION_ROUTES), row

    def test_a_declaration_on_no_route_fails_the_audit(self) -> None:
        """The gate reproduces its own red on demand (R-05).

        A declaration nothing would miss is exactly how a retired hand
        seed comes back: plausible prose in a field a validator accepts,
        with every other check still green.
        """
        dependency = CastDependency(
            slot="E",
            requires="Q",
            kind="cc_enabler",
            reason="synthetic",
            source="https://wiki.leagueoflegends.com/en-us/Syndra@4024662",
        )
        row = {
            "champion": "Syndra",
            "slot": "E",
            "requires": "Q",
            "active_states": 4,
            "load_bearing_routes": [],
            "source_resolution": {"resolved": True, "reviewed_revision_id": 4024662},
        }
        reasons = [
            failure["reason"] for failure in _declaration_failures(row, dependency)
        ]
        assert any("load-bearing on nothing" in reason for reason in reasons), reasons

    def test_every_source_resolves_against_the_committed_wiki_audit(
        self, receipt
    ) -> None:
        """Resolution is the gate; staleness is reported, not failed.

        A declaration citing an older revision than the audit's latest
        pull honestly names what its author read — the reading
        ``full_entry_audit`` already gives an overtaken module receipt.
        Every declaration happens to be current today, and that is pinned
        here so the day one goes stale is a visible receipt diff rather
        than a silent one.
        """
        for row in receipt["declared_dependency_activation"]:
            resolution = row["source_resolution"]
            assert resolution["resolved"] is True, row
            assert resolution["stale"] is False, row
            assert resolution["current"] is True, row
            assert resolution["revision_id"] == resolution["reviewed_revision_id"]

    def test_every_cc_enabler_names_a_marker_that_reaches_the_ledger(
        self, receipt
    ) -> None:
        enablers = [
            row
            for row in receipt["declared_dependency_activation"]
            if row["kind"] == "cc_enabler"
        ]
        assert enablers, "no cc_enabler declaration is audited"
        for row in enablers:
            resolution = row["cc_enabler_resolution"]
            assert resolution["marker_slot"] == row["slot"]
            assert resolution["cc_kinds"], row
            assert resolution["resolved"] is True
            assert resolution["reaches_event_ledger"] is True
            assert resolution["contract_error"] is None

    def test_every_suppression_is_matched_or_latent_with_a_reason(
        self, receipt
    ) -> None:
        for row in receipt["suppression_ledger"]:
            assert row["matched_states"] or row["latent_states"], row
            assert row["reason"].strip()
            if row["latent_states"]:
                assert row["latent_reason"], row

    def test_no_conflict_row_is_uncovered(self, receipt) -> None:
        assert [row for row in receipt["conflict_ledger"] if not row["covered"]] == []

    def test_every_surviving_override_carries_a_reason(self, receipt) -> None:
        frontier = receipt["order_override_frontier"]
        assert frontier["unclassified"] == []
        assert sum(frontier["reasons"].values()) == frontier["entries"]


class TestMarkerSurfaceIsDerived:
    def test_the_surface_is_read_out_of_the_resolver(self) -> None:
        assert set(apply_marker_keys()) == set(MARKER_NEGATIVE_TESTS)

    def test_a_new_read_grows_the_surface(self) -> None:
        """The derivation follows the resolver, not a list kept beside it."""
        source = _resolver_source().replace(
            'if info.get("on_hit"):',
            'if info.get("__probe_marker__"):\n            pass\n        if info.get("on_hit"):',
            1,
        )
        assert "__probe_marker__" in apply_marker_keys(source)

    def test_a_missing_loop_raises_instead_of_publishing_an_empty_surface(self) -> None:
        source = _resolver_source().replace("apply_atoms[s] = atoms", "pass")
        with pytest.raises(AuditDerivationError):
            apply_marker_keys(source)

    def test_every_marker_names_a_test_that_exists_and_nothing_else(self) -> None:
        """The mapping and the class of negative tests are the same set.

        Both directions matter: a marker naming a test nobody wrote is a
        claim, and a negative test the mapping does not name is evidence
        the audit cannot see.
        """
        defined = {
            name for name in vars(TestMarkerNegativeTests) if name.startswith("test_")
        }
        assert defined == set(MARKER_NEGATIVE_TESTS.values())

    def test_the_audit_reads_this_module_s_mapping(self) -> None:
        assert declared_negative_tests() == MARKER_NEGATIVE_TESTS

    def test_an_untested_marker_and_a_stale_test_both_fail_the_audit(self) -> None:
        """The rule itself, driven both ways (criterion 10).

        A key the interpreter newly reads with no negative test fails, and
        a negative test naming a key the interpreter no longer reads fails
        too — otherwise the mapping could outlive the read it describes.
        """
        observed = {
            "marker_authors": {"target_debuff": {"Garen"}, "__new__": {"Garen"}}
        }
        _, failures = _marker_ledger(
            ("target_debuff", "__new__"),
            observed,
            {"target_debuff": MARKER_NEGATIVE_TESTS["target_debuff"], "__gone__": "t"},
        )
        assert sorted(failure["item"] for failure in failures) == [
            "authored_marker_reach:__gone__",
            "authored_marker_reach:__new__",
        ]

    def test_a_suite_without_the_mapping_raises(self) -> None:
        with pytest.raises(AuditDerivationError):
            declared_negative_tests("MARKER_NEGATIVE_TESTS = dict()\n")


class TestMarkerNegativeTests:
    """One per derived marker: withhold it, and the interpreter answers differently."""

    def test_withholding_target_debuff_drops_the_shred_edge(self) -> None:
        parsed, data = _shred_kit()
        assert ("Q", "W", "shred") in _pairs(_edges(parsed, data))
        assert _pairs(_edges(_withhold(parsed, "Q", "target_debuff"), data)) == []

    def test_zeroing_cooldown_disqualifies_the_setup_slot(self) -> None:
        parsed, data = _shred_kit()
        assert ("Q", "W", "shred") in _pairs(_edges(parsed, data))
        assert _pairs(_edges(_withhold(parsed, "Q", "cooldown"), data)) == []

    def test_withholding_stat_buff_drops_the_buff_edge(self) -> None:
        parsed = {"Q": _entry(stat_buff={"ability_power": 40.0}), "W": _entry()}
        data = _champion_data()
        assert ("Q", "W", "buff") in _pairs(_edges(parsed, data))
        assert _pairs(_edges(_withhold(parsed, "Q", "stat_buff"), data)) == []

    def test_withholding_cc_kind_drops_the_cc_setup_fan_out(self) -> None:
        parsed, data = _cc_kit()
        assert ("Q", "W", "cc_setup") in _pairs(_edges(parsed, data))
        assert _pairs(_edges(_withhold(parsed, "Q", "cc_kind"), data)) == []

    def test_withholding_parts_drops_the_cc_setup_fan_out(self) -> None:
        parsed, data = _cc_kit()
        assert ("Q", "W", "cc_setup") in _pairs(_edges(parsed, data))
        assert _pairs(_edges(_withhold(parsed, "Q", "parts"), data)) == []

    def test_withholding_applies_dot_stack_drops_the_stack_edge(self) -> None:
        parsed, data = _stack_kit(applies_dot_stack=True)
        assert ("Q", "W", "stack_consume") in _pairs(_edges(parsed, data))
        assert _pairs(_edges(_withhold(parsed, "Q", "applies_dot_stack"), data)) == []

    def test_withholding_stacking_dot_drops_the_stack_edge(self) -> None:
        parsed, data = _stack_kit(stacking_dot=True)
        assert ("Q", "W", "stack_consume") in _pairs(_edges(parsed, data))
        assert _pairs(_edges(_withhold(parsed, "Q", "stacking_dot"), data)) == []

    def test_withholding_on_hit_changes_the_edge_citation(self) -> None:
        """``on_hit`` names the applier in the edge's citation.

        It is the one marker whose read reaches only the receipt: it is
        listed among the applier's atoms in the sentence the rotation
        receipt publishes, so withholding it changes what the model says
        about *why* the order is what it is, while leaving the order
        alone.  That is still an interpreter output, and pinning it is
        what would make a future read of ``on_hit`` that *does* move an
        edge visible as a change here.
        """
        parsed, data = _stack_kit(on_hit=True, applies_dot_stack=True)
        before = _edges(parsed, data)
        after = _edges(_withhold(parsed, "Q", "on_hit"), data)
        assert _pairs(before) == _pairs(after) == [("Q", "W", "stack_consume")]
        assert "on_hit" in before[0].cite
        assert "on_hit" not in after[0].cite
        assert before[0].cite != after[0].cite

    def test_withholding_dot_duration_drops_the_dot_consume_edge(self) -> None:
        parsed, data = _dot_kit()
        edges = _edges(
            parsed,
            data,
            champion=_DOT_CONSUME_CHAMPION,
            option_keys=_DOT_CONSUME_OPTION,
        )
        assert ("Q", "E", "dot_consume") in _pairs(edges)
        withheld = _edges(
            _withhold(parsed, "Q", "dot_duration"),
            data,
            champion=_DOT_CONSUME_CHAMPION,
            option_keys=_DOT_CONSUME_OPTION,
        )
        assert _pairs(withheld) == []


def _rows(ledger):
    """One ledger as a comparable set of canonical rows."""
    return sorted(json.dumps(row, sort_keys=True) for row in ledger)


def _resolver_source():
    """The resolver's source text, for the derivation tests."""
    from scripts.cast_dependency_audit import RESOLVER_SOURCE

    return RESOLVER_SOURCE.read_text(encoding="utf-8")
