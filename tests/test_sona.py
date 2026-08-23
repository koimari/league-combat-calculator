"""Sona's reviewed crowd control (``MODULE_CC``).

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

import json
from pathlib import Path

import pytest

from src.calculator.ability_atoms import _ability_atoms
from src.calculator.champions import get_champion_module_contract
from src.calculator.data_fetcher import get_champion
from tests import rider_probe
from src.calculator.champions import sona
from tests import cc_review

RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}

_WIKI = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))["Sona"]


@pytest.fixture(name="abilities")
def _abilities() -> dict:
    return sona.parse_abilities(get_champion("Sona"), 18, 0.0, dict(RANKS))


class TestReviewedCrowdControl:
    """Sona's reviewed crowd control, and what declaring it clears."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Sona")
        assert sona.MODULE_CC == {"Q": "none", "R": "stun"}
        # Power Chord's Tempo slow rides the passive's empowered attack,
        # not Q, so Q's own text carries no control at all.
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert "stuns them for 1.5 seconds" in cc_review.slot_text(data, "R")

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Sona") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Sona")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


class TestPowerChordRider:
    """Sona P prices the chord three basic abilities empower (slice 6)."""

    def test_one_chord_reaches_the_total(self):
        """Level 18, no items: 240.0 raw magic on one empowered attack.

        Cached P "Per-Level Scaling" 20 : 270 (based on level) + 20% AP —
        the unmodified chord; the probe target halves magic damage.
        """
        result = rider_probe.fight("Sona")
        row = result["breakdown"][rider_probe.RIDER_ROW]

        assert row["name"] == "Power Chord (on-hit)"
        assert row["count"] == 1
        assert row["total_damage"] == pytest.approx(120.0, abs=0.05)
        assert row["total_damage"] < result["total_damage"]

    def test_no_chord_prices_nothing(self):
        result = rider_probe.fight("Sona", champion_options={"p_power_chords": 0})
        assert rider_probe.RIDER_ROW not in result["breakdown"]

    def test_the_map_reports_what_each_slot_prices(self):
        assert get_champion_module_contract("Sona").coverage == {
            "P": "modeled",
            "Q": "modeled",
            "W": "modeled",
            "E": "no_damage",
            "R": "modeled",
        }


class TestSongOfCelerityIsASourcedZeroDamageRow:
    """E: movement only, so ``no_damage`` rather than an open receipt.

    The prior receipt claimed "the movement-speed axis, which ``slotlib``'s
    ``stat_buff`` dispatch has no key for".  That claim is false today —
    ``move_speed_percent`` is a live term in the shared ``resolve_move_speed``
    fold — so E closes the way Teemo W and Udyr E closed, on the same wiring.
    """

    def test_e_emits_a_visible_zero_row(self, abilities):
        row = abilities["E"]

        assert row["name"] == "Song of Celerity"
        assert row["total_raw"] == 0.0
        assert row["parts"] == ()
        assert row["detail"]

    def test_e_has_no_damage_instance_anywhere_in_the_cache(self):
        """The verdict is re-derived, not trusted from the module's prose."""
        for entry in _WIKI["abilities"]["E"]:
            assert entry["damageType"] is None
            assert entry["affects"] == "Self, Allies"
            for effect in entry["effects"]:
                for row in effect["leveling"]:
                    assert "Movement Speed" in row["attribute"]

    def test_e_atom_catalog_is_movement_and_timing_only(self):
        ids = [
            atom["atom_id"]
            for atom in _ability_atoms("Sona", get_champion("Sona"))["E"]
        ]

        assert not [atom_id for atom_id in ids if atom_id.startswith("damage")]
        assert any("movement" in atom_id.replace(" ", "") for atom_id in ids)

    def test_e_publishes_only_sonas_own_half_as_a_move_speed_stat_buff(self, abilities):
        """20% + 2% per 100 AP, on the shared movement-speed channel.

        The ranked Melody Bonus (10/12/14/16/18%) is the ALLY half and is
        withheld: it needs tagged allied champions, which the 1v1 surface
        has no room for.  A published rank-5 grant would read 18% higher.
        """
        assert abilities["E"]["stat_buff"] == {"move_speed_percent": 20.0}

    def test_the_ap_scaling_is_read_from_the_sentence_not_a_literal(self):
        buffed = sona.parse_abilities(get_champion("Sona"), 18, 200.0, dict(RANKS))

        assert buffed["E"]["stat_buff"]["move_speed_percent"] == pytest.approx(24.0)

    def test_a_sentence_that_stops_stating_the_grant_raises(self):
        """Fail-closed: no module literal stands behind these numbers."""
        with pytest.raises(ValueError, match="the self grant cannot be sourced"):
            sona._celerity_grant({"effects": [{"description": "bonus movement speed"}]})

    @staticmethod
    def _fight_move_speed(seconds: float) -> float:
        from src.calculator.pipeline import FightParams, run_fight

        return run_fight(
            get_champion("Sona"),
            18,
            [],
            FightParams(
                target_health=2000.0,
                target_armor=100.0,
                target_magic_resistance=50.0,
                fight_duration_seconds=seconds,
                ability_ranks=dict(RANKS),
                deterministic=True,
            ),
        )["champion_stats"]["move_speed"]

    def test_the_fight_folds_the_grant_through_the_shared_move_speed_call(self):
        from src.calculator.stats import calculate_total_stats, resolve_move_speed

        build = calculate_total_stats(get_champion("Sona"), 18, [])
        buffed = self._fight_move_speed(10.0)

        assert buffed == pytest.approx(
            resolve_move_speed(
                build["move_speed_flat"],
                build["move_speed_percent"] + 20.0 * (3.0 / 10.0),
            )
        )
        assert buffed > build["move_speed"]

    def test_the_grant_is_weighted_by_the_casts_window(self):
        """A 3s cast must not read the same in a 5s fight and a 30s one."""
        assert self._fight_move_speed(3.0) == pytest.approx(390.0)
        assert self._fight_move_speed(5.0) == pytest.approx(364.0)
        assert self._fight_move_speed(30.0) == pytest.approx(331.5)

    def test_the_priced_window_is_the_damaged_one_and_the_atom_is_the_wrong_one(self):
        """Why the sentence is read — and why reading the atom would lie.

        ``timing.active_duration`` on this slot is 7.0: the UNDISTURBED
        duration.  A modelled fight is a state in which she takes damage, so
        the sourced 3s damaged window is the one this surface can price;
        using the atom would over-credit the buff by 7/3.  This is the Teemo-W
        trap with the sign flipped, so it is pinned the same way.
        """
        active = _WIKI["abilities"]["E"][0]["effects"][0]["description"]
        assert "bonus movement speed for 7 seconds" in active
        assert "3 seconds have elapsed" in active
        assert sona._celerity_grant(_WIKI["abilities"]["E"][0]) == (20.0, 2.0, 3.0)

        atoms = [
            atom
            for atom in _ability_atoms("Sona", get_champion("Sona"))["E"]
            if atom["atom_id"] == "timing.active_duration"
        ]
        assert [atom["values"] for atom in atoms] == [[7.0]]
        assert atoms[0]["source"] == "Sona.E[0].effects[0].description"
