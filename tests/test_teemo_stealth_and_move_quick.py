"""Teemo's two remaining slots: W closes ``no_damage``, P stays receipted open.

Roadmap session 5 batch L.  The pair is the whole point of this file: two
slots that both carry zero damage rows today, adjudicated DIFFERENTLY
under the Olaf-R / Sivir-R rule.

- W (Move Quick) is sourced-NON-damaging: movement only, nothing about it
  would change damage if it were modeled.  That closes as ``no_damage``.
- P (Guerrilla Warfare) carries Element of Surprise, a real 20/40/60/80%
  bonus-attack-speed steroid that WOULD change damage.  It stays
  ``out_of_scope`` with a receipt naming the two structural blockers.

The tests re-derive the evidence from ``data/champions.json`` and
``data/gamefiles/characters/teemo.bin.json`` rather than trusting the
module's prose, so a patch that adds a damage row to W, or that starts
emitting a leveling row for Element of Surprise, fails here instead of
silently leaving a stale verdict in place.
"""

import json
from pathlib import Path

import pytest

from src.calculator.ability_atoms import _ability_atoms
from src.calculator.champions import teemo
from src.calculator.data_fetcher import get_champion

RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}

_WIKI = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))["Teemo"]
# ``data/gamefiles/`` is a gitignored local cdtb cache, so CI has no copy.
# The PRIMARY receipt for every number in this file is the git-tracked
# ``data/champions.json`` and is asserted unconditionally; the binary is a
# SECOND, corroborating source, and the tests that read it skip when the
# cache is absent (the ``test_gnar_mega_gamefile.py`` ternary idiom).
_BIN_PATH = Path("data/gamefiles/characters/teemo.bin.json")
_BIN = json.loads(_BIN_PATH.read_text(encoding="utf-8")) if _BIN_PATH.exists() else None


def _teemo_passive_record() -> dict:
    """The binary record whose ``ObjectName`` is ``TeemoPassive``."""
    if _BIN is None:
        pytest.skip(f"{_BIN_PATH} absent (gitignored local game-file cache)")
    for value in _BIN.values():
        if isinstance(value, dict) and value.get("ObjectName") == "TeemoPassive":
            return value
    raise AssertionError("TeemoPassive record missing from the cached binary")


@pytest.fixture(name="abilities")
def _abilities() -> dict:
    data = get_champion("Teemo")
    return teemo.parse_abilities(data, 18, 0.0, dict(RANKS))


class TestMoveQuickIsASourcedZeroDamageRow:
    """W: movement only, so ``no_damage`` rather than an open receipt."""

    def test_w_emits_a_visible_zero_row(self, abilities):
        row = abilities["W"]

        assert row["name"] == "Move Quick"
        assert row["total_raw"] == 0.0
        assert row["parts"] == ()
        assert row["detail"]

    def test_w_detail_carries_the_cached_movement_numbers(self, abilities):
        """Rank 5: 28% passive, doubled to 56%. Read, never restated."""
        detail = abilities["W"]["detail"]

        assert "28%" in detail
        assert "56%" in detail
        assert "3s" in detail

    def test_w_has_no_damage_instance_anywhere_in_the_cache(self):
        for entry in _WIKI["abilities"]["W"]:
            assert entry["damageType"] is None
            assert entry["affects"] == "Self"
            for effect in entry["effects"]:
                for row in effect["leveling"]:
                    assert "Movement Speed" in row["attribute"]

    def test_w_atom_catalog_is_movement_and_timing_only(self):
        atoms = _ability_atoms("Teemo", get_champion("Teemo"))["W"]
        ids = [atom["atom_id"] for atom in atoms]

        assert not [atom_id for atom_id in ids if atom_id.startswith("damage")]
        assert any("movement" in atom_id.replace(" ", "") for atom_id in ids)

    def test_w_publishes_the_active_grant_as_a_move_speed_stat_buff(self, abilities):
        """The cast's own row, on the shared movement-speed channel.

        The percent-movement boundary closed when ``calculate_total_stats``
        started publishing the two components its fold reads, so the grant
        is a term in that one fold rather than a decomposition somebody
        would have to invent.  The PASSIVE branch is still withheld: its
        5s-undamaged condition is a state a fight never enters.
        """
        assert abilities["W"]["stat_buff"] == {"move_speed_percent": 56.0}

    @staticmethod
    def _fight_move_speed(seconds: float) -> float:
        from src.calculator.pipeline import FightParams, run_fight

        return run_fight(
            get_champion("Teemo"),
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
        """Abilities, items and runes all land in one term list."""
        from src.calculator.stats import calculate_total_stats, resolve_move_speed

        build = calculate_total_stats(get_champion("Teemo"), 18, [])
        # The active lasts _W_ACTIVE_SECONDS, so a 10s fight earns 3/10.
        share = teemo._W_ACTIVE_SECONDS / 10.0
        buffed = self._fight_move_speed(10.0)

        assert buffed == pytest.approx(
            resolve_move_speed(
                build["move_speed_flat"],
                build["move_speed_percent"] + 56.0 * share,
            )
        )
        assert buffed > build["move_speed"]

    def test_the_grant_is_weighted_by_the_casts_window(self):
        """A 3s cast must not read the same in a 5s fight and a 30s one.

        The whole SC12 family shares this contract; W is its proof, so an
        unweighted W would be the pattern's one counter-example.
        """
        assert self._fight_move_speed(5.0) == pytest.approx(435.704)
        assert self._fight_move_speed(10.0) == pytest.approx(385.44)
        assert self._fight_move_speed(30.0) == pytest.approx(348.48)

    def test_the_window_is_prose_and_the_slots_one_atom_is_the_wrong_one(self):
        """Why the constant exists — and why reading the atom would lie.

        ``timing.active_duration`` on this slot is 5.0: the PASSIVE's
        "after 5 seconds without taking damage" idle condition, not the
        cast's 3s window. Using it would over-credit the buff by 5/3.
        """
        assert teemo._W_ACTIVE_SECONDS == 3.0
        active = _WIKI["abilities"]["W"][0]["effects"][1]["description"]
        assert "doubles the bonus movement speed for 3 seconds" in active

        atoms = [
            atom
            for atom in _ability_atoms("Teemo", get_champion("Teemo"))["W"]
            if atom["atom_id"] == "timing.active_duration"
        ]
        assert [atom["values"] for atom in atoms] == [[5.0]]
        assert atoms[0]["source"] == "Teemo.W[0].effects[0].description"
        assert (
            "without taking" in _WIKI["abilities"]["W"][0]["effects"][0]["description"]
        )


class TestGuerrillaWarfareStaysReceiptedOpen:
    """P: a real attack-speed steroid, so ``out_of_scope``, not ``no_damage``."""

    def test_p_emits_a_visible_zero_row_naming_the_steroid(self, abilities):
        row = abilities["passive"]

        assert row["name"] == "Guerrilla Warfare"
        assert row["total_raw"] == 0.0
        assert row["parts"] == ()
        for magnitude in ("20%", "40%", "60%", "80%"):
            assert magnitude in row["detail"]

    def test_p_publishes_no_attack_speed_buff(self, abilities):
        """The withholding is the assertion: nothing reaches the engine."""
        row = abilities["passive"]

        assert "stat_buff" not in row
        assert "auto_attack_override" not in row
        assert "on_hit" not in row

    def test_the_ladder_is_dual_sourced_not_prose_only(self):
        """Wiki prose AND the binary agree on 20/40/60/80 by level.

        An earlier draft of this receipt claimed the magnitude was
        prose-only.  It is not: the blocker is the engine channel, not
        the sourcing, and this test pins the correction.
        """
        prose = " ".join(
            effect["description"]
            for entry in _WIKI["abilities"]["P"]
            for effect in entry["effects"]
        )
        assert "20% / 40% / 60% / 80%" in prose

        calc = _teemo_passive_record()["mSpell"]["mSpellCalculations"][
            "BonusAttackSpeed"
        ]
        part = calc["mFormulaParts"][0]
        assert part["__type"] == "ByCharLevelBreakpointsCalculationPart"
        assert part["mLevel1Value"] == pytest.approx(0.20, abs=1e-6)
        assert [bp["mLevel"] for bp in part["mBreakpoints"]] == [5, 10, 15]
        for breakpoint in part["mBreakpoints"]:
            assert breakpoint["mAdditionalBonusAtThisLevel"] == pytest.approx(
                0.20, abs=1e-6
            )

    def test_the_window_and_stealth_delay_are_sourced_too(self):
        values = {
            row["name"]: row["values"]
            for row in _teemo_passive_record()["mSpell"]["DataValues"]
        }

        assert set(values["AttackSpeedDuration"]) == {5.0}
        assert set(values["StealthCooldownDuration"]) == {1.5}

    def test_the_cache_carries_no_leveling_row_for_the_steroid(self):
        """Why no ability atom exists even though the value is known."""
        for entry in _WIKI["abilities"]["P"]:
            assert entry["damageType"] is None
            for effect in entry["effects"]:
                assert effect["leveling"] == []

        atoms = _ability_atoms("Teemo", get_champion("Teemo"))["P"]
        assert [atom["atom_id"] for atom in atoms] == ["timing.active_duration"]
        assert atoms[0]["values"] == [1.5]

    def test_the_windowed_attack_speed_kernel_is_q_slot_only(self):
        """The structural blocker, asserted against the engine source.

        ``damage.py`` resolves an ``auto_attack_override.active_duration``
        window's START by walking ``cast_order`` and breaking on ``"Q"``.
        A P-slot steroid has no window to ride, so it could only be
        published unwindowed for the entire fight.
        """
        source = Path("src/calculator/damage.py").read_text(encoding="utf-8")
        anchor = source.index('if "bonus_attack_speed" in stat_buff:')
        kernel = source[anchor : anchor + 2000]

        assert "auto_attack_override" in kernel
        assert "for slot in state.cast_order:" in kernel
        assert 'if slot == "Q":' in kernel
        # No other slot letter opens that window.
        assert 'if slot == "P":' not in kernel


class TestModuleCoverageRecordsTheSplitVerdict:
    def test_coverage_map(self):
        assert teemo.MODULE_COVERAGE == {
            "P": "out_of_scope",
            "Q": "modeled",
            "W": "no_damage",
            "E": "modeled",
            "R": "modeled",
        }

    def test_closing_w_did_not_move_any_priced_row(self, abilities):
        """Both adjudicated slots are zero, so the damage totals stand."""
        assert abilities["Q"]["total_raw"] == pytest.approx(260.0)
        assert abilities["E"]["total_raw"] == pytest.approx(185.0)
        assert abilities["R"]["total_raw"] == pytest.approx(450.0)
        assert abilities["W"]["total_raw"] == 0.0
        assert abilities["passive"]["total_raw"] == 0.0
