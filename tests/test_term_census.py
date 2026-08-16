"""The term census — umbrella Amendment N, Ruling 2, and its reds.

Two families have now been stopped by the same shape: a term the pair engine
applies to a packet and the from-declaration pricing stage does not, each found
by the lane that tripped over it.  Ruling 2 rules that a third shall not be
found the same way, and `scripts/term_census.py` is the instrument.  This file
is its gate and its negatives.

The negatives matter more here than usual.  A census that enumerates the sites
somebody already knew about, and cannot be made to report one they did not, is
indistinguishable from the hand list Ruling 2 forbids — so every claim the
instrument makes is driven through its own seam and shown to fail on demand:
an injected re-pricing site with no restatement, an injected one that restates,
an authoring site that must stay out, and a fourth static holder amp the walk's
composition would not deliver.
"""

from __future__ import annotations

import sys
from dataclasses import fields
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import term_census  # noqa: E402  (path is set above)

from src.calculator.interpreters.delta_amp import StaticHolderAmps  # noqa: E402

#: The four sites the umbrella's Amendment N enumerated by hand, as the shape
#: each of them is.  Named here as the *question* the instrument is asked, not
#: as its answer: what the tests below assert is that the derived census finds
#: exactly these and classifies each the way the amendment described it, so a
#: fifth site is a failure and a missing fourth is a failure too.
AMENDMENT_N_SITES = {
    "_apply_liandry_reprice": "packet_reprice",
    "_apply_temporary_lethality_windows": "packet_reprice",
    "_reattribute_empowered_swings": "packet_removal",
    "_resolve_starting_shield_outcome": "packet_reprice",
}


def _in_place(sites):
    """The in-place half of a census, keyed by function."""
    return {site.function: site for site in sites if site.shape == "in_place_reprice"}


class TestTheCensusIsTheAmendmentsOwnScanDerived:
    """What the amendment found by hand, the instrument finds from source."""

    def test_the_in_place_sites_are_exactly_the_four(self):
        """No fifth, and no missing fourth.

        The amendment's own scan over `damage.py` found four functions that
        write rows or events they did not author: the two the ruling names,
        `_reattribute_empowered_swings`, which moves damage between two
        authored rows, and `_resolve_starting_shield_outcome`, the third
        re-pricing site its prose does not name.  This is that scan, derived.
        """
        sites = _in_place(term_census.census())
        assert set(sites) == set(AMENDMENT_N_SITES)

    def test_each_site_is_classified_the_way_the_amendment_described_it(self):
        """Three re-price packets; one only moves rows and drops packets.

        The distinction is the census's whole content: a site that re-prices a
        packet owes a term, and a site that re-attributes between rows with the
        fight total untouched owes nothing, which is exactly what the amendment
        said `_reattribute_empowered_swings` does.
        """
        sites = _in_place(term_census.census())
        assert {
            name: site.disposition for name, site in sites.items()
        } == AMENDMENT_N_SITES

    def test_every_enumerated_site_is_covered(self):
        """Ruling 2's gate: no further family retires while one is not.

        Asserted as the state of the tree rather than as a count, because the
        number of sites is not what the ruling binds — the emptiness of the
        uncovered set is.
        """
        sites = term_census.census()
        assert term_census.uncovered(sites) == ()
        assert term_census.main(["--check"]) == 0

    def test_the_re_pricing_sites_are_covered_by_keeping_a_declaration_in_step(self):
        """And they are covered by *that*, not by something else being green."""
        sites = _in_place(term_census.census())
        for name, disposition in AMENDMENT_N_SITES.items():
            if disposition == "packet_reprice":
                assert sites[name].restates
                assert sites[name].coverage() == "term:AuthoredDeclaration.kept_in_step"
            else:
                assert not sites[name].restates
                assert sites[name].coverage().startswith("no_packet_is_re_priced")


class TestTheAmpFoldIsEnumeratedToo:
    """The shape a census keyed only on in-place writes would have missed."""

    def test_the_amp_fields_are_read_from_the_declaration_that_produces_them(self):
        """Derived from `StaticHolderAmps`, so a fourth amp arrives named."""
        declared = {
            f"{field.name}_amp"
            for field in fields(StaticHolderAmps)
            if isinstance(field.default, float)
        }
        assert set(term_census.static_holder_amp_fields()) == declared

    def test_every_declared_amp_is_one_the_walk_folds(self):
        """The join `DeclaredPacket.holder_amp` covers these sites *by*.

        An amp declared and never folded into `factor_for` would be a term
        that exists and does not reach the packet — Amendment M, Ruling 1's
        deletion, wearing a green gate.
        """
        assert term_census.unfolded_amps() == ()

    def test_the_fold_reaches_the_engine_sites_that_apply_it(self):
        """The three the catalog names, present and covered by the one term.

        `_mitigate` applies the magic amp, `_add_item_proc_damage` the ability
        amp and `_mitigate_basic_attack_swing` the basic one — which is the
        reading `StaticHolderAmps.factor_for` states in its own docstring, and
        none of the three writes a packet in place.
        """
        folds = {
            site.function: site
            for site in term_census.census()
            if site.shape == "holder_amp_fold"
        }
        assert {
            "_mitigate",
            "_add_item_proc_damage",
            "_mitigate_basic_attack_swing",
        } <= set(folds)
        for site in folds.values():
            assert site.coverage() == "term:DeclaredPacket.holder_amp"


class TestTheCensusCanBeMadeToFail:
    """R-05, four ways: the reds this gate ships with."""

    def test_an_injected_re_pricing_site_with_no_restatement_is_uncovered(self):
        """The finding Ruling 2 exists to produce, on demand.

        A function that reads a packet's damage, computes a new one from it and
        writes it back is a re-pricing site whatever it is called; with no
        declaration kept in step, the census reports it.
        """
        injected = (
            "def _some_new_window(state):\n"
            "    for row in state.breakdown.values():\n"
            "        for event in row['damage_events']:\n"
            "            damage = event['damage']\n"
            "            event['damage'] = damage * 1.5\n"
        )
        sites = _in_place(term_census.census(injected))
        assert set(sites) == {"_some_new_window"}
        assert sites["_some_new_window"].coverage() == "UNCOVERED"
        assert [site.function for site in term_census.uncovered(sites.values())] == [
            "_some_new_window"
        ]

    def test_the_same_site_covered_reports_the_term_that_covers_it(self):
        """The seam is not a switch that only ever says no.

        The same injected body, with the one restatement home called from it,
        is reported as covered by the term rather than reported at all — which
        is what makes the red above a finding instead of the instrument's
        default answer.
        """
        injected = (
            "def _some_new_window(state):\n"
            "    for row in state.breakdown.values():\n"
            "        for event in row['damage_events']:\n"
            "            damage = event['damage']\n"
            "            event['damage'] = damage * 1.5\n"
            "            _restate_declaration(event, scale=1.5)\n"
        )
        sites = _in_place(term_census.census(injected))
        assert (
            sites["_some_new_window"].coverage()
            == "term:AuthoredDeclaration.kept_in_step"
        )

    def test_an_authoring_site_is_not_a_finding(self):
        """The predicate's other half, driven the same way.

        A function that gives a row a value computed from somewhere else is
        authoring it, not re-pricing anything, and a census that reported those
        would report most of the engine and therefore nothing.
        """
        injected = (
            "def _authors_a_row(state):\n"
            "    total = _mitigate(100.0, 'magic', state.resists, 1.0)\n"
            "    row = state.breakdown.get('key')\n"
            "    row['total_damage'] = total\n"
            "    row['damage_events'] = [{'time': 0.0, 'damage': total}]\n"
        )
        assert _in_place(term_census.census(injected)) == {}

    def test_a_packet_removal_is_not_a_re_pricing(self):
        """Dropping packets is not changing what one is worth.

        A slice of the list it replaces removes packets — they leave with
        their declarations, which is the correct thing to happen to a packet
        that no longer exists — and the census says so instead of demanding a
        term nobody could write.
        """
        injected = (
            "def _drops_packets(state):\n"
            "    row = state.breakdown.get('auto_attacks')\n"
            "    events = row['damage_events']\n"
            "    row['damage_events'] = events[:2]\n"
        )
        sites = _in_place(term_census.census(injected))
        assert sites["_drops_packets"].disposition == "packet_removal"
        assert sites["_drops_packets"].coverage() == (
            "no_packet_is_re_priced:packet_removal"
        )

    def test_an_amp_the_walk_would_not_deliver_fails_the_join(self, monkeypatch):
        """The fourth red: a static holder amp `factor_for` does not fold.

        Driven through the declaration rather than through the scan, because
        that is where the failure would really come from — a fourth amp added
        to `StaticHolderAmps` and not to the composition that delivers it.
        """
        monkeypatch.setattr(
            term_census,
            "amps_the_walk_folds",
            lambda: ("magic_amp", "ability_amp"),
        )
        assert term_census.unfolded_amps() == ("basic_amp",)
        assert term_census.main(["--check"]) == 1


def test_the_report_names_every_site_and_its_coverage():
    """`--json` publishes the census, so a reader is not left with a count."""
    report = term_census.report(term_census.census())
    assert report["jurisdiction"] == term_census.PAIR_ENGINE
    assert report["uncovered"] == []
    assert {row["function"] for row in report["sites"]} >= set(AMENDMENT_N_SITES)
    assert all(row["coverage"] != "UNCOVERED" for row in report["sites"])


def test_the_cli_exits_zero_without_check_even_with_a_finding(monkeypatch):
    """`--check` is what makes it a gate; the bare run is a report.

    Stated because the two are easy to confuse and the difference decides
    whether a red is seen: a lane that ran the report and read exit 0 would
    have been told about the finding in words it might not read.
    """
    monkeypatch.setattr(term_census, "unfolded_amps", lambda: ("basic_amp",))
    assert term_census.main([]) == 0
    assert term_census.main(["--check"]) == 1


@pytest.mark.parametrize("home", term_census.RESTATEMENT_HOME)
def test_every_declared_restatement_home_exists_in_the_engine(home):
    """A coverage predicate keyed on a name nothing defines is always red."""
    source = (REPO_ROOT / term_census.PAIR_ENGINE).read_text(encoding="utf-8")
    assert f"def {home}(" in source
