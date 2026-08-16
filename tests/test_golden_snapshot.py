"""The golden instrument: fingerprint, classified diffs, and the coupled baseline.

Every check here is about the *instrument*, never about a champion's numbers:
what `compare` ignores, what `fingerprint` counts, which producers the coupled
scenario set reaches, and whether each new gate can be made to fail on demand
(runbook R-05).
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import golden_snapshot as gs  # noqa: E402  (path is set above)

from src.calculator import pipeline  # noqa: E402
from src.calculator.interpreters.delta_amp import resolve_part_amp  # noqa: E402
from src.calculator.interpreters.threshold_defense import (  # noqa: E402
    ThresholdExpiryWithheld,
)
from src.calculator.item_behavior import (  # noqa: E402
    Basis,
    DefenseField,
    EmpoweredHitRule,
    PartAmpRule,
    PeriodicRule,
    ThresholdDefenseRule,
)
from src.calculator.item_behavior_catalog import (  # noqa: E402
    behavior_rules,
    rule_owners,
)
from src.calculator.item_effects import (  # noqa: E402
    required_effect_value,
    resolve_damage_effects,
)
from src.calculator.item_support_effects import producer_item  # noqa: E402

COUPLED_BASELINE = REPO_ROOT / "scripts" / "golden_coupled_baseline.json"
COUPLED_EXACT = REPO_ROOT / "scripts" / "golden_coupled_exact.json"
PAIR_BASELINE = REPO_ROOT / "scripts" / "golden_baseline.json"


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _holder(entry):
    """The captured roster row of the scenario's own champion."""
    return next(
        row for row in entry["combat"]["breakdown"] if row["participant_id"] == "main"
    )


@pytest.fixture(scope="module")
def coupled():
    """One coupled capture, shared by every check that reads its numbers."""
    return gs.capture_coupled(
        gs.COUPLED_SCENARIOS, producers=gs.cross_participant_producers()
    )


# ---------------------------------------------------------------------------
# Provenance exclusion (R-14) and the fingerprint domain
# ---------------------------------------------------------------------------


class TestProvenanceExclusion:
    def test_src_tree_sha_is_excluded(self):
        """A comment-only edit moves it, so comparing it waives the gate."""
        assert "src_tree_sha" in gs.COMPARE_EXCLUDED_PROVENANCE

    @pytest.mark.parametrize("path", [PAIR_BASELINE, COUPLED_BASELINE])
    def test_no_numeric_section_is_excluded(self, path):
        sections = set(gs.numeric_sections(_load(path)))
        assert sections
        assert not sections & gs.COMPARE_EXCLUDED_PROVENANCE

    @pytest.mark.parametrize("path", [PAIR_BASELINE, COUPLED_BASELINE])
    def test_every_excluded_key_is_actually_captured(self, path):
        """The exclusion set names keys the snapshot carries, not aspirations."""
        metadata = _load(path)["metadata"]
        assert gs.COMPARE_EXCLUDED_PROVENANCE <= set(metadata)

    def test_dropping_git_head_from_the_exclusion_set_turns_compare_red(self):
        """R-05: the gate's own red, reproducible on demand.

        `compare` pops exactly `COMPARE_EXCLUDED_PROVENANCE`; with `git_head`
        out of that set, two captures of one unchanged tree differ on every
        commit.  The seam is the constant.
        """
        baseline = _load(COUPLED_BASELINE)
        current = json.loads(json.dumps(baseline))
        current["metadata"]["git_head"] = "0" * 40
        for excluded in (gs.COMPARE_EXCLUDED_PROVENANCE, frozenset({"src_tree_sha"})):
            left = json.loads(json.dumps(baseline))
            right = json.loads(json.dumps(current))
            for snapshot in (left, right):
                for key in excluded:
                    snapshot["metadata"].pop(key, None)
            diffs = gs.leaf_report(left, right)
            assert bool(diffs) is ("git_head" not in excluded)


class TestFingerprint:
    @pytest.mark.parametrize("path", [PAIR_BASELINE, COUPLED_BASELINE])
    def test_metadata_carries_the_counts_the_fingerprint_prints(self, path):
        """One function produces the receipt figure and the snapshot's copy."""
        snapshot = _load(path)
        printed = gs.fingerprint(snapshot)
        assert snapshot["metadata"]["fingerprint"] == {
            field: printed[field] for field in gs.FINGERPRINT_COUNT_FIELDS
        }

    @pytest.mark.parametrize("path", [PAIR_BASELINE, COUPLED_BASELINE])
    def test_excluded_key_set_is_exactly_the_compare_exclusion(self, path):
        assert set(gs.fingerprint(_load(path))["excluded_metadata"].split(",")) == set(
            gs.COMPARE_EXCLUDED_PROVENANCE
        )

    def test_metadata_is_not_counted(self):
        """Its two wall-clock stamps move on every capture; counting them lies."""
        snapshot = {"a": {"x": 1.0}, "metadata": {"noise": [1, 2, 3, 4, 5]}}
        assert gs.fingerprint(snapshot)["leaves"] == 1
        assert gs.numeric_sections(snapshot) == {"a": {"x": 1.0}}

    def test_counts_separate_numeric_leaves_from_text(self):
        snapshot = {"s": {"n": 1.5, "i": 2, "t": "x", "b": True, "z": None}}
        counts = gs.fingerprint_counts(snapshot)
        assert counts["leaves"] == 5
        assert counts["numeric_leaves"] == 2
        # One entry per top-level key of each section — the scenario/champion
        # count, not the leaf count.
        assert counts["entries"] == 5
        assert gs.fingerprint_counts({"s": {"a": {}}, "t": {}})["entries"] == 1


# ---------------------------------------------------------------------------
# Classified diffs (R-15)
# ---------------------------------------------------------------------------


class TestLeafReport:
    @pytest.mark.parametrize(
        "old, new, transition",
        [
            ({"a": 10.0}, {"a": 10.5}, "value"),
            ({"a": 0.0}, {"a": 3.0}, "zero_to_value"),
            ({"a": 3.0}, {"a": 0.0}, "value_to_zero"),
            ({"a": 3.0}, {"a": {"error": "ValueError: x"}}, "value_to_error"),
            ({"a": {"error": "ValueError: x"}}, {"a": 3.0}, "error_to_value"),
            ({}, {"a": 3.0}, "absent_to_value"),
            ({"a": 3.0}, {}, "value_to_absent"),
            ({"a": "left"}, {"a": "right"}, "text_change"),
        ],
    )
    def test_every_transition_is_classified(self, old, new, transition):
        (diff,) = gs.leaf_report({"s": old}, {"s": new})
        assert diff.transition == transition
        assert diff.section == "s"

    def test_percent_is_infinite_from_zero(self):
        (diff,) = gs.leaf_report({"s": {"a": 0.0}}, {"s": {"a": 3.0}})
        assert diff.percent == float("inf")
        assert diff.abs_delta == pytest.approx(3.0)

    def test_a_small_percentage_move_on_a_plain_leaf_owes_nobody(self):
        (diff,) = gs.leaf_report({"s": {"armor": 100.0}}, {"s": {"armor": 100.5}})
        assert not gs.qualifies_for_investigation(diff)

    def test_a_large_percentage_move_qualifies(self):
        (diff,) = gs.leaf_report({"s": {"armor": 100.0}}, {"s": {"armor": 120.0}})
        assert gs.qualifies_for_investigation(diff)

    def test_a_flat_damage_move_qualifies_below_ten_percent(self):
        """The systematic single-digit-percent move R-15's third clause catches."""
        (diff,) = gs.leaf_report(
            {"s": {"total_damage": 1000.0}}, {"s": {"total_damage": 1002.0}}
        )
        assert abs(diff.percent) < gs.INVESTIGATION_PERCENT
        assert gs.qualifies_for_investigation(diff)

    def test_the_same_move_on_a_non_damage_leaf_does_not(self):
        (diff,) = gs.leaf_report({"s": {"armor": 1000.0}}, {"s": {"armor": 1002.0}})
        assert not gs.qualifies_for_investigation(diff)

    def test_every_non_value_transition_qualifies(self):
        (diff,) = gs.leaf_report({"s": {"a": "left"}}, {"s": {"a": "right"}})
        assert gs.qualifies_for_investigation(diff)

    def test_report_is_sorted_by_section_then_magnitude(self):
        old = {"s": {"a": 100.0, "b": 100.0}, "t": {"c": 100.0}}
        new = {"s": {"a": 101.0, "b": 150.0}, "t": {"c": 200.0}}
        paths = [diff.path for diff in gs.leaf_report(old, new)]
        assert paths == ["/s/b", "/s/a", "/t/c"]

    def test_report_file_carries_every_diff_and_the_ratio_clause(self, tmp_path):
        old = {"s": {"a": 100.0}, "metadata": {}}
        new = {"s": {"a": 150.0}, "metadata": {}}
        report = gs._write_report(
            tmp_path / "r.json", gs.leaf_report(old, new), gs.PAIR_SNAPSHOT_KIND
        )
        assert report["differing_leaves"] == 1
        assert report["qualifying_leaves"] == 1
        assert report["largest_abs_delta_per_section"]["s"] == "/s/a"
        assert json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))["diffs"]


# ---------------------------------------------------------------------------
# Identity-keyed list matching: a removal is a membership transition, never a
# run of value changes against the record the shift slid into its place.
# ---------------------------------------------------------------------------


def _events(*rows):
    """A snapshot fragment holding one identity-bearing event list."""
    return {
        "s": {
            "events": [
                {"event_id": f"main:enemy:Aatrox:{ordinal}", **fields}
                for ordinal, fields in rows
            ]
        }
    }


def _without_identity(document):
    """The same fragment with every ``event_id`` stripped."""
    return {
        "s": {
            "events": [
                {k: v for k, v in row.items() if k != gs.IDENTITY_FIELD}
                for row in document["s"]["events"]
            ]
        }
    }


_THREE_ROWS = _events(
    (31, {"damage": 10.0, "source": "W"}),
    (33, {"damage": 20.0, "source": "expose_weakness_Bloodsong"}),
    (35, {"damage": 30.0, "source": "E"}),
)
_MIDDLE_REMOVED = _events(
    (31, {"damage": 10.0, "source": "W"}),
    (35, {"damage": 30.0, "source": "E"}),
)


class TestIdentityKeyedListMatching:
    """R-15's membership transitions, keyed on the event's own identity.

    A slice that removes a row from an event list shifts every later ordinal.
    Paired by position, that manufactures value diffs between two *different*
    events — the defect that produced two dissenting oracle verdicts about a
    comparison with no referent.  Paired by ``event_id`` — the attacker's id
    and that attacker's ordinal, which no list position can change — the same
    removal is one ``value_to_absent`` membership transition and the surviving
    rows compare against themselves.
    """

    def test_a_removed_member_is_one_membership_transition(self):
        (diff,) = gs.leaf_report(_THREE_ROWS, _MIDDLE_REMOVED)
        assert diff.transition == "value_to_absent"
        assert diff.path == "/s/events[1]"
        assert diff.identity == "main:enemy:Aatrox:33"

    def test_the_removal_reports_no_value_change_on_the_survivor(self):
        """The whole point: nothing is said about the row that moved up."""
        paths = [diff.path for diff in gs.leaf_report(_THREE_ROWS, _MIDDLE_REMOVED)]
        assert "/s/events[2]/damage" not in paths
        assert "/s/events[2]/source" not in paths

    def test_the_same_removal_without_identities_manufactures_value_changes(self):
        """R-05's permanent negative: the defect, reproducible on demand.

        Identical fixture, ``event_id`` stripped, so the only difference is
        whether the members can be paired by identity.  Positional pairing
        reports the surviving row as *changes* to the removed row — two
        different events compared as one — which is the red this check exists
        to keep out of the report.
        """
        diffs = gs.leaf_report(
            _without_identity(_THREE_ROWS), _without_identity(_MIDDLE_REMOVED)
        )
        by_path = {diff.path: (diff.old, diff.new, diff.transition) for diff in diffs}
        assert by_path["/s/events[1]/damage"] == (20.0, 30.0, "value")
        assert by_path["/s/events[1]/source"] == (
            "expose_weakness_Bloodsong",
            "E",
            "text_change",
        )
        assert by_path["/s/events[2]"][2] == "value_to_absent"
        assert len(diffs) > 1

    def test_an_added_member_is_absent_to_value_at_its_own_ordinal(self):
        (diff,) = gs.leaf_report(_MIDDLE_REMOVED, _THREE_ROWS)
        assert diff.transition == "absent_to_value"
        assert diff.path == "/s/events[1]"
        assert diff.identity == "main:enemy:Aatrox:33"

    def test_a_reordered_list_reports_nothing(self):
        """Identity outranks position: the same events in another order are the same."""
        shuffled = {"s": {"events": list(reversed(_THREE_ROWS["s"]["events"]))}}
        assert gs.leaf_report(_THREE_ROWS, shuffled) == ()

    def test_a_matched_member_keeps_the_baselines_address(self):
        """A moved field is reported where the *baseline* holds it.

        Committed allowlists, oracle receipts and escalation ledgers all
        address leaves by the baseline's ordinal, so identity decides *what*
        is compared and the baseline still decides where the leaf is spelled.
        """
        moved = _events(
            (31, {"damage": 10.0, "source": "W"}),
            (35, {"damage": 99.0, "source": "E"}),
        )
        diffs = gs.leaf_report(_THREE_ROWS, moved)
        by_path = {diff.path: diff for diff in diffs}
        assert by_path["/s/events[2]/damage"].old == 30.0
        assert by_path["/s/events[2]/damage"].new == 99.0
        assert by_path["/s/events[2]/damage"].identity == "main:enemy:Aatrox:35"

    def test_every_leaf_under_an_identified_record_carries_that_identity(self):
        moved = _events(
            (31, {"damage": 10.0, "source": "W"}),
            (33, {"damage": 20.0, "source": "expose_weakness_Bloodsong"}),
            (35, {"damage": 31.0, "source": "E"}),
        )
        (diff,) = gs.leaf_report(_THREE_ROWS, moved)
        assert diff.identity == "main:enemy:Aatrox:35"

    def test_a_duplicate_identity_falls_back_to_position(self):
        """Fail closed: an ambiguous index is refused, never half-applied."""
        duplicated = {
            "s": {
                "events": [
                    {"event_id": "main:enemy:Aatrox:31", "damage": 10.0},
                    {"event_id": "main:enemy:Aatrox:31", "damage": 20.0},
                ]
            }
        }
        other = {
            "s": {
                "events": [
                    {"event_id": "main:enemy:Aatrox:31", "damage": 10.0},
                    {"event_id": "main:enemy:Aatrox:31", "damage": 25.0},
                ]
            }
        }
        (diff,) = gs.leaf_report(duplicated, other)
        assert diff.path == "/s/events[1]/damage"
        assert diff.identity is None

    def test_a_list_of_unidentified_members_still_pairs_by_position(self):
        """The fallback is the old behaviour, unchanged for every other list."""
        old = {"s": {"rows": [{"a": 1.0}, {"a": 2.0}]}}
        new = {"s": {"rows": [{"a": 1.0}, {"a": 3.0}]}}
        (diff,) = gs.leaf_report(old, new)
        assert diff.path == "/s/rows[1]/a"

    def test_a_membership_transition_qualifies_for_investigation(self):
        """R-15 already carries both members of the closed transition set."""
        (diff,) = gs.leaf_report(_THREE_ROWS, _MIDDLE_REMOVED)
        assert gs.qualifies_for_investigation(diff)

    def test_the_report_file_carries_the_identity(self, tmp_path):
        report = gs._write_report(
            tmp_path / "r.json",
            gs.leaf_report(_THREE_ROWS, _MIDDLE_REMOVED),
            gs.PAIR_SNAPSHOT_KIND,
        )
        assert report["diffs"][0]["identity"] == "main:enemy:Aatrox:33"


# ---------------------------------------------------------------------------
# The two lists identity pairing did not reach: a cast row, which spells its
# identity as an origin beside that origin's ordinal, and a bare-string list,
# whose members have no fields to be identified by at all.
# ---------------------------------------------------------------------------


def _casts(*rows):
    """A snapshot fragment holding one ``cast_timeline``-shaped list."""
    return {
        "s": {
            "cast_timeline": [
                {"slot": slot, "ordinal": ordinal, "resource_cost": cost}
                for slot, ordinal, cost in rows
            ]
        }
    }


#: Syndra's pre-C6 cast timeline in miniature: Q, W, E, each the first cast
#: of its slot, with the mana each spends.
_CASTS_BEFORE = _casts(("Q", 1, 40.0), ("W", 1, 100.0), ("E", 1, 90.0))

#: The same timeline after a second Dark Sphere charge is inserted at
#: position 1.  Every later row keeps its own identity and changes nothing.
_CASTS_AFTER = _casts(("Q", 1, 40.0), ("Q", 2, 0.0), ("W", 1, 100.0), ("E", 1, 90.0))


class TestOriginOrdinalIdentity:
    """A cast row's identity is its slot and that slot's ordinal.

    C6 inserted one row into Syndra's ``cast_timeline`` and positional
    pairing re-addressed every later row, which is how three oracle briefs
    came to ask about ``cast_timeline[1]/resource_cost: 100.0 -> 0.0`` —
    Force of Will's rank-5 mana cost against the second Dark Sphere charge's,
    two different casts at one address.  That is the defect
    ``identity_pairing_does_not_reach_a_bare_scalar_list`` names, reproduced
    here as a fixture so the remedy has a red it can produce on demand.
    """

    def test_the_inserted_cast_is_one_membership_transition(self):
        (diff,) = gs.leaf_report(_CASTS_BEFORE, _CASTS_AFTER)
        assert diff.transition == "absent_to_value"
        assert diff.identity == "Q#2"

    def test_no_later_cast_is_reported_as_a_value_change(self):
        """The whole point: W's mana cost is never compared against Q2's."""
        paths = [diff.path for diff in gs.leaf_report(_CASTS_BEFORE, _CASTS_AFTER)]
        assert "/s/cast_timeline[1]/resource_cost" not in paths

    def test_stripping_the_ordinal_reproduces_the_substitution(self):
        """R-05's permanent negative, on the identity this commit adds.

        Identical fixture with ``ordinal`` dropped, so the only difference is
        whether the rows can be paired by identity.  Positional pairing then
        hands exactly the brief the three C6 receipts answered.
        """

        def stripped(document):
            return {
                "s": {
                    "cast_timeline": [
                        {k: v for k, v in row.items() if k != gs.ORDINAL_FIELD}
                        for row in document["s"]["cast_timeline"]
                    ]
                }
            }

        diffs = {
            diff.path: (diff.old, diff.new)
            for diff in gs.leaf_report(stripped(_CASTS_BEFORE), stripped(_CASTS_AFTER))
        }
        assert diffs["/s/cast_timeline[1]/resource_cost"] == (100.0, 0.0)

    def test_a_repeated_origin_ordinal_falls_back_to_position(self):
        """Fail closed, exactly as a duplicate ``event_id`` does."""
        duplicated = _casts(("Q", 1, 40.0), ("Q", 1, 50.0))
        other = _casts(("Q", 1, 40.0), ("Q", 1, 55.0))
        (diff,) = gs.leaf_report(duplicated, other)
        assert diff.path == "/s/cast_timeline[1]/resource_cost"
        assert diff.identity is None

    def test_a_moved_cast_keeps_the_baselines_address(self):
        moved = _casts(("Q", 1, 40.0), ("W", 1, 100.0), ("E", 1, 95.0))
        (diff,) = gs.leaf_report(_CASTS_BEFORE, moved)
        assert diff.path == "/s/cast_timeline[2]/resource_cost"
        assert diff.identity == "E#1"


class TestBareStringListIdentity:
    """A bare string is its own address, and only where a member left or came.

    Phase 5's seed retirement replaced the rotation record's hand-written
    ``setup`` / ``consume`` / ``sources`` lists with derived ones of a
    different length, and positional pairing turned seventeen surviving or
    added members into value questions.  Pairing such a list by its own
    strings is guarded on the lengths differing, which is what makes this a
    correction rather than a relaxation: an equal-length list cannot have
    gained or lost a member, so a substitution there is still one
    ``text_change`` owed to an investigator.
    """

    def test_a_grown_list_reports_only_what_arrived(self):
        diffs = gs.leaf_report(
            {"s": {"setup": ["Q"]}}, {"s": {"setup": ["E", "Q", "R"]}}
        )
        assert {(d.transition, d.identity) for d in diffs} == {
            ("absent_to_value", "E"),
            ("absent_to_value", "R"),
        }

    def test_a_shrunk_list_reports_only_what_left(self):
        (diff,) = gs.leaf_report(
            {"s": {"cast_order": ["Q", "Q2", "W"]}},
            {"s": {"cast_order": ["Q", "W"]}},
        )
        assert diff.transition == "value_to_absent"
        assert diff.identity == "Q2"

    def test_an_equal_length_substitution_is_still_one_text_change(self):
        """The guard, asserted: nothing about a same-length list moves.

        Without it a reworded justification string would split into a removal
        plus an addition, and a membership transition can be adjudicated by
        citation where a ``text_change`` never can — a relaxation this commit
        must not buy.
        """
        (diff,) = gs.leaf_report(
            {"s": {"sources": ["a", "b"]}}, {"s": {"sources": ["a", "c"]}}
        )
        assert diff.path == "/s/sources[1]"
        assert diff.transition == "text_change"
        assert (diff.old, diff.new) == ("b", "c")

    def test_a_repeated_string_falls_back_to_position(self):
        """``cast_order`` holds repeats, and a repeat is not an identity."""
        diffs = gs.leaf_report(
            {"s": {"cast_order": ["Q", "W", "Q"]}},
            {"s": {"cast_order": ["Q", "W"]}},
        )
        assert [d.path for d in diffs] == ["/s/cast_order[2]"]
        assert diffs[0].identity is None

    def test_a_numeric_list_keeps_its_value_diffs(self):
        """Numbers are excluded on purpose: R-15 grades them by magnitude."""
        (diff,) = gs.leaf_report(
            {"s": {"ticks": [10.0, 20.0]}}, {"s": {"ticks": [10.0, 20.0, 30.0]}}
        )
        assert diff.path == "/s/ticks[2]"
        assert diff.transition == "absent_to_value"

    def test_a_numeric_move_is_never_re_spelled_as_a_membership_change(self):
        """A grown numeric list still grades its moved member by magnitude."""
        diffs = {
            diff.path: diff.transition
            for diff in gs.leaf_report(
                {"s": {"ticks": [10.0, 20.0]}}, {"s": {"ticks": [10.0, 25.0, 30.0]}}
            )
        }
        assert diffs["/s/ticks[1]"] == "value"
        assert diffs["/s/ticks[2]"] == "absent_to_value"

    def test_a_membership_transition_on_a_string_still_owes_an_investigator(self):
        """Widening the pairing widens no threshold: R-15 still qualifies it."""
        diffs = gs.leaf_report(
            {"s": {"setup": ["Q"]}}, {"s": {"setup": ["E", "Q", "R"]}}
        )
        assert all(gs.qualifies_for_investigation(diff) for diff in diffs)


# ---------------------------------------------------------------------------
# The coupled baseline (R-11, R-12)
# ---------------------------------------------------------------------------


class TestCoupledCoverage:
    def test_the_scenario_set_covers_every_producer(self):
        assert (
            gs._uncovered_producers(
                gs.COUPLED_SCENARIOS, gs.cross_participant_producers()
            )
            == ()
        )

    def test_a_seventh_producer_without_a_scenario_fails_the_capture(self):
        """R-12's whole point: the producer set is read, so coverage cannot rot."""
        producers = gs.cross_participant_producers() | {
            "Unequipped Relic — Seventh Wonder"
        }
        with pytest.raises(ValueError, match="Unequipped Relic"):
            gs.capture_coupled(gs.COUPLED_SCENARIOS, producers=producers)

    def test_every_producer_moves_a_leaf_when_its_packet_is_suppressed(
        self, coupled, monkeypatch
    ):
        """Coverage means the baseline can *see* the producer, not merely hold it."""
        from src.calculator import participant_timeline

        original = participant_timeline.derive_item_support_effects
        for producer in gs.cross_participant_producers():

            def muted(*args, _producer=producer, **kwargs):
                return [
                    packet
                    for packet in original(*args, **kwargs)
                    if packet.get("source") != _producer
                ]

            monkeypatch.setattr(
                participant_timeline, "derive_item_support_effects", muted
            )
            without = gs.capture_coupled(
                gs.COUPLED_SCENARIOS, producers=gs.cross_participant_producers()
            )
            monkeypatch.setattr(
                participant_timeline, "derive_item_support_effects", original
            )
            assert gs.leaf_report(coupled, without), (
                f"suppressing {producer!r} changes no leaf of the coupled "
                "baseline — the scenario set does not reach it"
            )

    def test_every_producer_item_is_equipped_by_some_scenario(self):
        equipped = frozenset().union(*(s.equipped() for s in gs.COUPLED_SCENARIOS))
        for producer in gs.cross_participant_producers():
            assert producer_item(producer) in equipped

    def test_score_scenarios_cover_both_damage_ledger_shapes(self, monkeypatch):
        """Both ledger shapes are covered by scenarios, never by assumption."""
        shapes = {}
        original = pipeline.calculate_fight_damage

        def recording(*args, **kwargs):
            if kwargs.get("score_only"):
                shapes.setdefault(recording.name, set()).add(
                    bool(kwargs.get("tuple_ledger"))
                )
            return original(*args, **kwargs)

        monkeypatch.setattr(pipeline, "calculate_fight_damage", recording)
        for scenario in gs.COUPLED_SCENARIOS:
            if not scenario.score_mode:
                continue
            recording.name = scenario.name
            gs.coupled_entry(scenario)
        assert {True, False} <= {
            shape for shapes_ in shapes.values() for shape in shapes_
        }
        assert shapes["score_event_scan_holder"] == {False}
        assert shapes["score_plain_tuple"] == {True}

    def test_one_catalyst_roster_is_present(self):
        equipped = {name for s in gs.COUPLED_SCENARIOS for name in s.equipped()}
        assert "Catalyst of Aeons" in equipped


class TestDeferralFamilyCoverage:
    """R-12's second reading: no receipt-walk deferral family is unseen.

    The umbrella's Amendment L, Ruling 2 makes a covering scenario the first
    act of a family's retirement, because against a family the baseline holds
    no roster for, the retirement slice's ``Expected qualifying occurrences``
    line reads zero, no investigator is ever owed, and the re-pricing ships
    unseen — the campaign's founding failure shape wearing the campaign's own
    gate as a disguise.
    """

    def test_the_scenario_set_covers_every_deferral_family(self):
        assert (
            gs._uncovered_families(gs.COUPLED_SCENARIOS, gs.receipt_walk_families())
            == ()
        )

    def test_the_family_mapping_is_read_rather_than_typed(self):
        """The schedule receipt is the join, and the catalog is its source.

        A hand list in the harness, or a schedule receipt that stopped
        matching the declarations, both fail here — which is what makes a
        fifteenth family arrive on the commit that declares it.
        """
        declared = {}
        for owner in rule_owners():
            for rule in behavior_rules(owner):
                declared.setdefault(rule.family.value, set()).add(owner)
        families = gs.receipt_walk_families()
        assert families
        for family, items in families.items():
            assert set(items) == declared[family]

    def test_a_family_no_scenario_equips_fails_the_capture(self):
        """The permanent negative (R-05), driven through the ``families`` seam."""
        families = dict(gs.receipt_walk_families())
        families["fifteenth_family"] = frozenset({"Unequipped Relic — Seventh Wonder"})
        with pytest.raises(ValueError, match="fifteenth_family"):
            gs.capture_coupled(
                gs.COUPLED_SCENARIOS,
                producers=gs.cross_participant_producers(),
                families=families,
            )

    def test_the_carry_roster_prices_the_families_it_covers(self, coupled):
        """Covering means the snapshot can *see* the family, not merely hold it."""
        entry = coupled["coupled_scenarios"]["crit_onhit_carry_roster"]
        fight = entry["fights"]["1:Malphite"]
        rows = fight["breakdown"]
        # charged_strike, on_hit_strike and secondary_target each price a
        # named row of their own.
        for row in (
            "on_hit_Kraken Slayer",
            "on_hit_Blade of the Ruined King",
            "secondary_Runaan's Hurricane",
        ):
            assert rows[row]["total_damage"] > 0
        # crit_profile is priced into the attack rows rather than into one of
        # its own, so the facts that say it landed are the holder's crit
        # damage bonus and the crits it is applied to.
        stats = fight["champion_stats"]
        assert stats["critical_strike_damage_percent"] > 0
        assert stats["critical_strike_chance"] > 0
        # threshold_defense: the Lifeline shield the holder absorbed itself,
        # told apart from the ally's shield by its own published field.
        holder = _holder(entry)
        assert holder["shield_absorbed"] > holder["support_shield_received"]

    def test_the_bruiser_roster_prices_the_families_it_covers(self, coupled):
        entry = coupled["coupled_scenarios"]["immolate_active_bruiser_roster"]
        rows = entry["fights"]["0:Aatrox"]["breakdown"]
        for row in ("immolate_Sunfire Aegis", "active_Stridebreaker"):
            assert rows[row]["total_damage"] > 0
        # damage_routing routes damage the holder took into later ticks, and
        # every one of them carries the event it was deferred from.
        deferred = [
            event
            for event in entry["combat"]["events"]
            if event.get("target") == "main" and event.get("deferred_from")
        ]
        assert deferred
        # opening_defense writes durability rather than damage, so what the
        # snapshot publishes for it is the holder's coverage row.
        coverage = {
            row["name"]: row
            for row in _holder(entry)["utility_outcomes"]["item_coverage"]
        }
        assert "critical_mitigation" in coverage["Randuin's Omen"]["dimensions"]


class TestHolderAmpCoverage:
    """R-12's third reading: no static holder amp goes unarmed.

    The umbrella's Amendment M, Ruling 2 makes arming them a covering
    scenario's job.  The pair engine applies the holder's own amplifiers to
    an item active and to an ability-triggered item proc; a family re-priced
    out of those rows while no scenario arms an amp would drop the term from
    every total that holds it, and a scenario set in which every amp reads
    ``1.0`` proves only the case that cannot fail.
    """

    def test_the_scenario_set_arms_every_static_holder_amp(self):
        assert (
            gs._unarmed_amp_kinds(gs.COUPLED_SCENARIOS, gs.holder_amp_declarations())
            == ()
        )

    def test_every_declared_amp_owner_produces_its_amp_in_the_engine(self):
        """The mapping is read from the declarations, and the engine agrees.

        Each half is checked against the code that *applies* the amp rather
        than against a second copy of the join: a per-part amp must resolve
        for the attack class its own declaration types, and a magic amp must
        reach ``resolve_damage_effects``.  A hand list in the harness, or a
        declaration that stopped producing an amp, fails here.
        """
        amps = gs.holder_amp_declarations()
        assert amps
        for kind, owners in amps.items():
            assert owners
            for owner in owners:
                rules = [
                    rule
                    for rule in behavior_rules(owner)
                    if isinstance(rule.payload, PartAmpRule)
                    and rule.mechanic_id.endswith(kind)
                ]
                if not rules:
                    assert resolve_damage_effects([{"name": owner}]).magic_amp > 1.0
                    continue
                for rule in rules:
                    for attack_class in rule.payload.typing.attack_classes:
                        resolved = resolve_part_amp(
                            [owner],
                            attack_class,
                            level=18,
                            fight_duration_seconds=8.0,
                            target_bonus_health=0.0,
                            holder_is_melee=False,
                        )
                        assert resolved is not None
                        assert resolved.owner == owner

    def test_an_amp_no_scenario_arms_fails_the_capture(self):
        """The permanent negative (R-05), driven through the ``amps`` seam."""
        amps = dict(gs.holder_amp_declarations())
        amps["fourth_part_amp"] = frozenset({"Unarmed Relic — Eighth Wonder"})
        with pytest.raises(ValueError, match="fourth_part_amp"):
            gs.capture_coupled(
                gs.COUPLED_SCENARIOS,
                producers=gs.cross_participant_producers(),
                amps=amps,
            )

    def test_the_mage_roster_arms_the_two_amps_ruling_1_seeds(self, coupled):
        """Arming means the snapshot *prices* the amp, not merely holds it."""
        entry = coupled["coupled_scenarios"]["amp_armed_mage_roster"]
        rows = entry["fights"]["0:Aatrox"]["breakdown"]
        # The ability amp is armed: it has a row of its own, which an
        # unarmed Actualizer — an active nobody triggered — would not write.
        assert rows["ability_amp_Actualizer"]["total_damage"] > 0
        # Ruling 1's two seed cases, both on an Abyssal Mask holder: an item
        # active, and an ability-triggered item proc.
        for row in ("active_Hextech Rocketbelt", "proc_Stormsurge"):
            assert rows[row]["total_damage"] > 0

    def test_the_magic_amp_is_priced_into_both_seed_rows(self):
        """The magic amp is a mitigation term, so its arming is a ratio.

        It writes no row of its own, so "armed" is measured by dropping the
        item that declares it and re-running the same roster: both seed rows
        fall by exactly the declared amp.  That is the term Amendment M's
        Ruling 1 says the walk's from-declaration price does not yet carry,
        and this is the baseline being able to see it.
        """
        armed = next(
            scenario
            for scenario in gs.COUPLED_SCENARIOS
            if scenario.name == "amp_armed_mage_roster"
        )
        request = json.loads(json.dumps(dict(armed.request)))
        request["items"] = [name for name in request["items"] if name != "Abyssal Mask"]
        unamped = gs.coupled_entry(gs.CoupledScenario("unamped", request))
        with_amp = gs.coupled_entry(armed)["fights"]["0:Aatrox"]["breakdown"]
        without = unamped["fights"]["0:Aatrox"]["breakdown"]
        declared = 1.0 + required_effect_value("Abyssal Mask", "magic_amp")
        for row in ("active_Hextech Rocketbelt", "proc_Stormsurge"):
            ratio = with_amp[row]["total_damage"] / without[row]["total_damage"]
            assert ratio == pytest.approx(declared, rel=1e-3)

    def test_the_carry_roster_arms_the_basic_amp(self, coupled):
        entry = coupled["coupled_scenarios"]["hexoptics_basic_amp_carry"]
        rows = entry["fights"]["0:Aatrox"]["breakdown"]
        assert rows["basic_amp_Hexoptics C44"]["total_damage"] > 0
        # The amp prices basic-damage parts, so the roster has to be making
        # basic attacks for the row above to be a measurement.
        assert rows["auto_attacks"]["total_damage"] > 0


class TestRepricingWindowCoverage:
    """R-12's fourth reading: no re-pricing window goes unarmed.

    The umbrella's Amendment N, Ruling 3 makes arming them a covering
    scenario's job.  The pair engine re-prices packets it already authored
    once the complete ledger exists — a lethality window rescales later
    physical packets, a lifeline's max-health raise reprices later burn ticks
    — while the walk's from-declaration price knows only the one effective
    resistance a fight publishes.  A scenario set that arms neither window
    can watch a family retire without ever seeing the term leave.
    """

    def test_the_scenario_set_arms_every_repricing_window(self):
        assert (
            gs._unarmed_repricing_windows(
                gs.COUPLED_SCENARIOS, gs.repricing_window_declarations()
            )
            == ()
        )

    def test_the_window_mapping_is_two_joins_and_both_are_declared(self):
        """The mapping is read from the declarations, and each side is real.

        The lethality window is one holder declaration; the max-health window
        is an attacker declaration joined to a *defender's*, and a mapping
        keyed only on the holder's items would report the second covered by
        an empty set.  Each side is checked against the declaration that
        produces it, so a hand list here — or a declaration that stopped
        carrying its payload — fails.
        """
        windows = gs.repricing_window_declarations()
        assert set(windows) == {gs.LETHALITY_WINDOW, gs.MAX_HEALTH_WINDOW}
        assert len(windows[gs.LETHALITY_WINDOW]) == 1
        assert len(windows[gs.MAX_HEALTH_WINDOW]) == 2
        for sides in windows.values():
            for side in sides:
                assert side
        (holders,) = windows[gs.LETHALITY_WINDOW]
        for owner in holders:
            payloads = [
                rule.payload
                for rule in behavior_rules(owner)
                if isinstance(rule.payload, EmpoweredHitRule)
                and rule.payload.temporary_lethality is not None
            ]
            assert payloads
        scaled, raisers = windows[gs.MAX_HEALTH_WINDOW]
        for owner in scaled:
            bases = {
                term.basis
                for rule in behavior_rules(owner)
                if isinstance(rule.payload, PeriodicRule)
                for term in rule.payload.formula.terms
            }
            assert Basis.TARGET_MAX_HEALTH in bases
        for owner in raisers:
            written = {
                field
                for rule in behavior_rules(owner)
                if isinstance(rule.payload, ThresholdDefenseRule)
                for field in rule.payload.writes
            }
            assert DefenseField.THRESHOLD_HEALTH_BONUS in written

    def test_a_window_no_scenario_arms_fails_the_capture(self):
        """The permanent negative (R-05), driven through the ``windows`` seam."""
        windows = dict(gs.repricing_window_declarations())
        windows["third_repricing_window"] = (
            frozenset({"Unarmed Relic — Ninth Wonder"}),
        )
        with pytest.raises(ValueError, match="third_repricing_window"):
            gs.capture_coupled(
                gs.COUPLED_SCENARIOS,
                producers=gs.cross_participant_producers(),
                windows=windows,
            )

    def test_a_window_only_one_side_of_which_is_equipped_fails_the_capture(self):
        """The two-ended join's own negative.

        A one-sided reading would call the lethality window covered by the
        assassin roster and stop there.  Give that same window a second side
        no scenario equips and the capture must go red, which is what proves
        the guard intersects its sides rather than unioning them.
        """
        windows = dict(gs.repricing_window_declarations())
        windows[gs.LETHALITY_WINDOW] = (
            *windows[gs.LETHALITY_WINDOW],
            frozenset({"Unarmed Relic — Ninth Wonder"}),
        )
        with pytest.raises(ValueError, match=gs.LETHALITY_WINDOW):
            gs.capture_coupled(
                gs.COUPLED_SCENARIOS,
                producers=gs.cross_participant_producers(),
                windows=windows,
            )

    def test_the_assassin_roster_fires_the_lethality_window(self, coupled):
        """Armed means *fired*: the engine publishes what the window reached."""
        entry = coupled["coupled_scenarios"]["lethality_window_assassin_roster"]
        rows = entry["fights"]["0:Aatrox"]["breakdown"]
        window = rows["on_hit_once_Voltaic Cyclosword_ability"]["temporary_lethality"]
        assert window["applied_event_count"] > 0
        # The declared figures, read through the declaration's own value
        # references — the holder is melee, which is the side of the declared
        # split this roster earns.
        declared = next(
            rule.payload.temporary_lethality
            for rule in behavior_rules("Voltaic Cyclosword")
            if isinstance(rule.payload, EmpoweredHitRule)
            and rule.payload.temporary_lethality is not None
        )
        assert window["amount"] == required_effect_value(
            "Voltaic Cyclosword", declared.melee.key
        )
        assert window["duration"] == required_effect_value(
            "Voltaic Cyclosword", declared.duration.key
        )

    def test_the_lethality_window_reprices_the_packets_inside_it(self):
        """The window is a resistance term, so its arming is a ratio.

        Every basic attack inside the window meets the target at the
        published effective armour *less* the declared lethality, and every
        one after it meets the published figure.  The step between the two is
        therefore the ratio of the two armour multipliers — the term
        ``survival.pricing.price_declared_packet`` does not carry, and this
        is the baseline being able to see it.
        """
        armed = next(
            scenario
            for scenario in gs.COUPLED_SCENARIOS
            if scenario.name == "lethality_window_assassin_roster"
        )
        fight = gs.coupled_entry(armed)["fights"]["0:Aatrox"]
        window = fight["breakdown"]["on_hit_once_Voltaic Cyclosword_ability"][
            "temporary_lethality"
        ]
        autos = [
            event
            for event in fight["damage_events"]
            if event["source"] == "auto_attacks"
        ]
        inside = [e["damage"] for e in autos if e["time"] <= window["duration"]]
        outside = [e["damage"] for e in autos if e["time"] > window["duration"]]
        assert inside and outside
        published = float(fight["effective_armor"])
        windowed = published - float(window["amount"])
        # Flat penetration cannot drive armour below zero, so the subtraction
        # above is the engine's own arithmetic only while it stays positive.
        assert windowed > 0
        expected = (100.0 + published) / (100.0 + windowed)
        assert inside[0] / outside[0] == pytest.approx(expected, rel=1e-2)

    def test_the_mage_roster_fires_the_max_health_reprice(self, coupled):
        """The defender's lifeline arms mid-fight and the burn is repriced.

        Both sides of the join have to show up for this to be a measurement:
        the defender's declaration triggers, and the attacker's burn ticks
        step up afterwards by the ratio the raised maximum implies.
        """
        entry = coupled["coupled_scenarios"]["liandry_reprice_mage_roster"]
        fight = entry["fights"]["0:Malphite"]
        assert fight["threshold_health_triggered"] is True
        gained = float(fight["threshold_health_bonus_gained"])
        assert gained > 0
        ticks = [
            event["damage"]
            for event in fight["damage_events"]
            if event["source"] == "burn_Liandry's Torment"
        ]
        assert ticks
        assert max(ticks) > min(ticks)
        raised = float(fight["target_effective_max_health"])
        expected = raised / (raised - gained)
        assert max(ticks) / min(ticks) == pytest.approx(expected, rel=1e-2)

    def test_the_mage_roster_departs_from_the_shared_duration(self):
        """The departure is the mechanic, not a tuned number.

        A fight that reaches the lifeline's own expiry is withheld rather
        than priced, so the roster set's shared eight seconds captures
        nothing at all on this pair.  The scenario states the shorter fight;
        this pins that the longer one really is unpriceable, so nobody
        "simplifies" it back to the shared duration.
        """
        armed = next(
            scenario
            for scenario in gs.COUPLED_SCENARIOS
            if scenario.name == "liandry_reprice_mage_roster"
        )
        assert armed.request["fight_duration"] < 8
        shared = json.loads(json.dumps(dict(armed.request)))
        shared["fight_duration"] = 8
        with pytest.raises(ThresholdExpiryWithheld):
            gs.coupled_entry(gs.CoupledScenario("shared_duration", shared))


def _q2_row_was_absent_before_c6(scenario):
    """Did an oracle receipt read this scenario's ``Q2`` row as absent (R-19)?

    The pre-fix end of C6's transition, taken from the independent receipt
    that adjudicated it rather than from a value restated here.  Exactly one
    receipt covers the row, and it must both name the scenario and report the
    old value as absent, so a receipt rewritten into agreement with the fix
    stops discharging this pin instead of silently satisfying it.
    """
    receipts = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((REPO_ROOT / "docs" / "receipts").glob("oracle-C6-*.json"))
    ]
    covering = [
        receipt
        for receipt in receipts
        if receipt.get("scenario") == scenario
        and receipt.get("leaf_path") == "fights/manual_target/breakdown/Q2"
    ]
    return len(covering) == 1 and covering[0]["old_value"] == "<absent>"


class TestSyndraPinScenarios:
    """The cast-order pin C6 is measured against (Phase 0, slice 0A.2)."""

    def test_both_orders_are_captured_at_every_splinter_count(self):
        names = {scenario.name for scenario in gs.COUPLED_SCENARIOS}
        for splinters in gs.SYNDRA_PIN_SPLINTERS:
            assert f"syndra_custom_order_{splinters}" in names
            assert f"syndra_derived_order_{splinters}" in names

    def test_the_two_orders_share_one_parameter_set(self):
        by_name = {scenario.name: scenario for scenario in gs.COUPLED_SCENARIOS}
        custom = dict(by_name["syndra_custom_order_120"].request)
        derived = dict(by_name["syndra_derived_order_120"].request)
        assert custom.pop("cast_order") == gs.SYNDRA_CUSTOM_ORDER
        assert "cast_order" not in derived
        custom["allies"] = [
            {k: v for k, v in ally.items() if k != "cast_order"}
            for ally in custom["allies"]
        ]
        assert custom == derived

    def test_the_parameter_set_is_level_18_600_ap_and_10_ability_haste(self):
        """The haste is what puts Q's recast at 5.0 s and W's at 7.273 s."""
        from src.calculator.data_fetcher import get_champion, get_item_by_name
        from src.calculator.stats import calculate_total_stats

        request = gs._syndra_pin_request(120, cast_order=None)
        stats = calculate_total_stats(
            get_champion("Syndra"),
            request["level"],
            [get_item_by_name(name) for name in request["items"]],
            item_options=request["item_options"],
        )
        assert request["level"] == 18
        assert stats["ability_power"] == pytest.approx(600.0)
        assert stats["ability_haste"] == pytest.approx(10.0)

    def test_the_custom_order_timeline_differs_from_the_derived_one(self, coupled):
        """A pin both the fix and a fall-through satisfy is not a pin."""
        entries = coupled["coupled_scenarios"]
        for splinters in gs.SYNDRA_PIN_SPLINTERS:
            custom = entries[f"syndra_custom_order_{splinters}"]["fights"][
                "manual_target"
            ]["cast_timeline"]
            derived = entries[f"syndra_derived_order_{splinters}"]["fights"][
                "manual_target"
            ]["cast_timeline"]
            assert [(c["time"], c["slot"]) for c in custom] != [
                (c["time"], c["slot"]) for c in derived
            ]

    def test_the_splinter_axis_is_load_bearing(self, coupled):
        """Q's second charge arrives at 40 stacks; 39 is the negative control."""
        entries = coupled["coupled_scenarios"]

        def slots(name):
            timeline = entries[name]["fights"]["manual_target"]["cast_timeline"]
            return [cast["slot"] for cast in timeline]

        assert "Q2" not in slots("syndra_derived_order_39")
        assert "Q2" in slots("syndra_derived_order_60")
        assert "Q2" in slots("syndra_derived_order_120")

    def test_a_custom_order_keeps_the_recast_slot(self, coupled):
        """The defect C6 corrected: the request used to delete this row.

        This test replaces the pre-C6 ``..._drops_the_recast_slot_today``,
        which pinned the defect and had to invert with the fix.  Both ends
        of the transition are still asserted after the phase-boundary
        re-capture, and neither end is a number typed here.  The corrected
        end is the live capture, which the re-captured baseline now
        reproduces.  The defective end is
        ``docs/receipts/expected-golden-diff-C6.json`` and its oracle
        receipts, which record the ``Q2`` breakdown row as ``<absent>``
        before the fix for 60 and 120 splinters and declare nothing at all
        for 39 — the committed evidence that the row is one C6 added rather
        than one the baseline always held.  Until the boundary the committed
        baseline was the defective end; reading that end from the allowlist
        instead is what keeps the pin from becoming a test that passes
        against itself.
        """
        committed = _load(COUPLED_BASELINE)["coupled_scenarios"]
        entries = coupled["coupled_scenarios"]
        declared = set(
            json.loads(
                (
                    REPO_ROOT / "docs" / "receipts" / "expected-golden-diff-C6.json"
                ).read_text(encoding="utf-8")
            )["expected_diff_paths"]["coupled_golden"]
        )

        def slots(source, name):
            fight = source[name]["fights"]["manual_target"]
            return [cast["slot"] for cast in fight["cast_timeline"]]

        def breakdown_path(name):
            return f"/coupled_scenarios/{name}/fights/manual_target/breakdown/Q2"

        for splinters in (60, 120):
            name = f"syndra_custom_order_{splinters}"
            assert slots(entries, name).count("Q2") == 1
            assert slots(committed, name) == slots(entries, name)
            assert breakdown_path(name) in declared
            assert _q2_row_was_absent_before_c6(name)
        assert "Q2" not in slots(entries, "syndra_custom_order_39")
        assert "Q2" not in slots(committed, "syndra_custom_order_39")
        assert breakdown_path("syndra_custom_order_39") not in declared


def declared_exact_moves():
    """Per-attacker totals a landed semantic slice declared it would move.

    R-17: a correction lands against the *committed* baselines plus a
    committed allowlist of expected diff paths, and the baselines are
    re-captured once per phase boundary.  This file is one of those
    baselines, so its equality gate reads the same allowlists — a declaration
    that lives in ``docs/receipts/`` and is reverted with its slice, never an
    edit to this test.

    Each entry names both values, so an allowlisted total may be exactly the
    one the baseline still holds or exactly the one the slice declared, and
    nothing else.  That keeps the entry harmless after the phase-boundary
    re-capture instead of turning a stale allowlist into a permanent hole.
    """
    declared: dict[str, dict[str, dict[str, str]]] = {}
    for receipt in sorted(
        (REPO_ROOT / "docs" / "receipts").glob("expected-*-diff-*.json")
    ):
        body = json.loads(receipt.read_text(encoding="utf-8"))
        moves = body.get("expected_diff_paths", {}).get("coupled_exact", {})
        for scenario, keys in moves.items():
            declared.setdefault(scenario, {}).update(keys)
    return declared


def declared_exact_new_scenarios():
    """Scenarios a landed slice declared this baseline does not hold yet.

    The same mechanism as :func:`declared_exact_moves` and for the same
    reason, over the one shape a per-key allowlist cannot express: a scenario
    the committed capture predates entirely has no old total to name, so it
    is declared by name.  Adding a covering scenario is its own act and the
    capture is the integration agent's next commit (R-17, R-32, and the
    umbrella's Amendment L, Ruling 2), so between the two this baseline
    legitimately holds fewer scenarios than the harness runs.

    The declaration is bounded on both sides: a name here must be one the
    scenario set actually holds, so a typo is a red rather than a waiver, and
    it never excuses a scenario going *missing* — only the equality below is
    relaxed, and only in the direction the ruling permits.
    """
    declared: set[str] = set()
    for receipt in sorted(
        (REPO_ROOT / "docs" / "receipts").glob("expected-*-diff-*.json")
    ):
        body = json.loads(receipt.read_text(encoding="utf-8"))
        names = body.get("expected_diff_paths", {}).get(
            "coupled_exact_new_scenarios", ()
        )
        declared.update(names)
    return declared


class TestExactBaseline:
    """R-13: golden equality is two decimals, so bit-exactness needs its own file."""

    def test_the_exact_capture_reproduces_the_committed_totals(self):
        captured = gs.capture_coupled(
            gs.coupled_scenarios_for(exact=True),
            producers=gs.cross_participant_producers(),
            exact=True,
        )["coupled_scenarios"]
        committed = _load(COUPLED_EXACT)["coupled_scenarios"]
        declared = declared_exact_moves()
        assert set(committed) <= set(captured)
        assert set(captured) - set(committed) <= declared_exact_new_scenarios()
        for scenario, totals in committed.items():
            allowed = declared.get(scenario, {})
            assert set(captured[scenario]) == set(totals)
            for key, value in totals.items():
                if key in allowed:
                    declared_pair = (allowed[key]["old"], allowed[key]["new"])
                    assert value in declared_pair
                    assert captured[scenario][key] in declared_pair
                else:
                    assert captured[scenario][key] == value

    def test_a_declared_exact_move_names_a_key_the_baseline_holds(self):
        """An allowlist entry for a total that does not exist is a typo, not a waiver."""
        committed = _load(COUPLED_EXACT)["coupled_scenarios"]
        for scenario, keys in declared_exact_moves().items():
            assert scenario in committed
            assert set(keys) <= set(committed[scenario])

    def test_a_declared_new_scenario_names_one_the_harness_runs(self):
        """The other half of the same guard, for the other declaration shape."""
        names = {scenario.name for scenario in gs.coupled_scenarios_for(exact=True)}
        assert declared_exact_new_scenarios() <= names

    def test_exact_values_are_repr_floats_not_rounded(self):
        captured = gs.capture_coupled(
            gs.coupled_scenarios_for(exact=True),
            producers=gs.cross_participant_producers(),
            exact=True,
        )
        values = [
            value
            for entry in captured["coupled_scenarios"].values()
            for value in entry.values()
        ]
        assert values
        assert all(isinstance(value, str) for value in values)
        assert all(float(value) == float(value) for value in values)

    def test_the_exact_file_is_not_the_compared_baseline(self):
        """It is excluded from the 2-dp compare and gated by the test above."""
        assert _load(COUPLED_EXACT)["metadata"]["exact"] is True
        assert _load(COUPLED_BASELINE)["metadata"]["exact"] is False


class TestFingerprintsReceipt:
    """The receipt is the sole home of every golden shape count (criterion 2)."""

    RECEIPT = REPO_ROOT / "docs" / "receipts" / "campaign-fingerprints.json"

    @pytest.mark.parametrize(
        "block, path",
        [
            ("golden", PAIR_BASELINE),
            ("coupled_golden", COUPLED_BASELINE),
            ("coupled_golden_exact", COUPLED_EXACT),
        ],
    )
    def test_the_receipt_reproduces_the_committed_fingerprint(self, block, path):
        recorded = _load(self.RECEIPT)[block]
        printed = gs.fingerprint(_load(path))
        assert {field: printed[field] for field in recorded} == recorded

    def test_every_recorded_block_carries_a_provenance_class(self):
        receipt = _load(self.RECEIPT)
        for block, provenance in receipt["provenance"].items():
            assert block in receipt
            assert provenance in {"VERIFIED", "CARRIED", "PRIOR"}

    def test_the_ratio_denominator_comes_from_the_receipt(self):
        """R-15's 1% clause reads a field, never a figure from a document."""
        receipt = _load(self.RECEIPT)
        assert gs.receipt_numeric_leaves(gs.PAIR_SNAPSHOT_KIND) == (
            receipt["golden"]["numeric_leaves"]
        )
        assert gs.receipt_numeric_leaves(gs.COUPLED_SNAPSHOT_KIND) == (
            receipt["coupled_golden"]["numeric_leaves"]
        )
