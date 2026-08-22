"""Tristana's two remaining slots: Q closes MODELED, P closes ``no_damage``.

Roadmap session 5 batch L.  The pair is the point of the file: two slots
that both emitted bare zero rows before, adjudicated differently.

- Q (Rapid Fire) is a Q-slot attack-speed steroid with a sourced
  magnitude AND a sourced window, which is exactly the shape the engine's
  windowed-attack-speed kernel exists for.  It becomes ``modeled``: a
  ``stat_buff`` plus a bare ``auto_attack_override.active_duration``.
- P (Draw a Bead) is bonus attack RANGE.  Range is inert in this model,
  so nothing about the slot would change damage if it were modeled —
  that is ``no_damage`` under the Olaf-R / Sivir-R rule, not a receipted
  ``out_of_scope`` opening (contrast Teemo P and Udyr P in this same
  batch, which DO carry unmodeled attack-speed steroids).

The tests re-derive the evidence from ``data/champions.json``, the typed
atom catalog and ``data/gamefiles/characters/tristana.bin.json`` rather
than trusting the module's prose, and pin the live fight arithmetic the
window produces.
"""

import json
import math
from pathlib import Path

import pytest

from src import app as app_module
from src.calculator.ability_atoms import _ability_atoms
from src.calculator.champions import tristana
from src.calculator.champions.slotlib import STEROID_ZERO
from src.calculator.data_fetcher import get_champion

RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}

_WIKI = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))["Tristana"]
# ``data/gamefiles/`` is a gitignored local cdtb cache, so CI has no copy.
# The PRIMARY receipt for every number in this file is the git-tracked
# ``data/champions.json`` (both of Q's numbers are typed atoms) and is
# asserted unconditionally; the binary is a SECOND, corroborating source,
# and the tests that read it skip when the cache is absent (the
# ``test_gnar_mega_gamefile.py`` ternary idiom).
_BIN_PATH = Path("data/gamefiles/characters/tristana.bin.json")
_BIN = json.loads(_BIN_PATH.read_text(encoding="utf-8")) if _BIN_PATH.exists() else None


def _bin_record(object_name: str) -> dict:
    if _BIN is None:
        pytest.skip(f"{_BIN_PATH} absent (gitignored local game-file cache)")
    for value in _BIN.values():
        if isinstance(value, dict) and value.get("ObjectName") == object_name:
            return value
    raise AssertionError(f"{object_name} missing from the cached binary")


def _data_values(object_name: str) -> dict[str, list]:
    return {
        row["name"]: row["values"]
        for row in _bin_record(object_name)["mSpell"]["DataValues"]
    }


@pytest.fixture(name="abilities")
def _abilities() -> dict:
    data = get_champion("Tristana")
    return tristana.parse_abilities(data, 18, 0.0, dict(RANKS))


def _fight(q_rank: int = 5, duration: float = 10.0) -> dict:
    """One no-item level-18 fight, autos included (the window's surface)."""
    payload = {
        "champion": "Tristana",
        "level": 18,
        "items": [],
        "role": "bottom",
        "ability_ranks": dict(RANKS, Q=q_rank),
        "fight_mode": "time_based",
        "fight_duration": duration,
        "include_auto_attacks": True,
        "target_health": 10_000.0,
        "target_armor": 0,
        "target_mr": 0,
    }
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


class TestRapidFireIsAModeledWindowedSteroid:
    """Q: the sourced magnitude and the sourced window both reach the engine."""

    def test_q_publishes_the_stat_buff_and_the_window(self, abilities):
        row = abilities["Q"]

        assert row["name"] == "Rapid Fire"
        assert row["total_raw"] == 0.0
        assert row["stat_buff"] == {"bonus_attack_speed": 120.0}
        assert row["auto_attack_override"] == {"active_duration": 7.0}

    def test_the_zero_is_declared_rather_than_merely_absent(self, abilities):
        """The steroid row is built by ``damage_entry``, so its zero has a
        disposition (D-24).  A bare ``parts == ()`` would say only that no
        damage was published; ``STEROID_ZERO`` says the zero is the ANSWER
        — a steroid slot with no damage attribute — which is the stronger
        statement and the one the zero-policy frontier counts.
        """
        parts = abilities["Q"]["parts"]

        assert [(part.damage_type, part.amount) for part in parts] == [
            ("physical", 0.0)
        ]
        assert [part.zero_policy for part in parts] == [STEROID_ZERO]

    def test_the_override_carries_the_window_and_nothing_else(self, abilities):
        """A bare window moves the auto COUNT, never the per-swing formula.

        ``ad_ratio`` defaults to 1.0 and the per-swing
        ``swing_window_ratio`` that consumes it is read only inside
        ``damage.py``'s ``override_crit_as_bonus`` branch (Ashe's
        flurry).  Publishing either key here would silently re-price
        every auto attack.
        """
        override = abilities["Q"]["auto_attack_override"]

        assert set(override) == {"active_duration"}
        for forbidden in ("ad_ratio", "crit_as_bonus", "replace_raw", "damage_ratio"):
            assert forbidden not in override

    def test_both_numbers_ride_typed_atoms(self):
        atoms = {
            atom["atom_id"]: atom
            for atom in _ability_atoms("Tristana", get_champion("Tristana"))["Q"]
        }

        assert atoms["ability.bonus _attack _speed"]["values"] == [
            60.0,
            75.0,
            90.0,
            105.0,
            120.0,
        ]
        assert atoms["timing.active_duration"]["values"] == [7.0]
        assert atoms["timing.active_duration"]["units"] == ["s"]

    def test_the_binary_agrees_with_the_wiki_on_both(self):
        values = _data_values("TristanaQ")

        # Riot spell DataValues are rank-0-indexed: index 0 is the
        # rank-0 placeholder, so ranks 1-5 are indices 1..5.
        assert values["AttackSpeedMod"][0] == pytest.approx(0.45, abs=1e-6)
        assert [round(v * 100) for v in values["AttackSpeedMod"][1:6]] == [
            60,
            75,
            90,
            105,
            120,
        ]
        assert set(values["BuffDuration"]) == {7.0}

    def test_q_scales_by_rank(self):
        data = get_champion("Tristana")
        for rank, expected in enumerate([60.0, 75.0, 90.0, 105.0, 120.0], start=1):
            parsed = tristana.parse_abilities(data, 18, 0.0, dict(RANKS, Q=rank))
            assert parsed["Q"]["stat_buff"]["bonus_attack_speed"] == expected

    def test_unlearned_q_publishes_no_buff(self):
        data = get_champion("Tristana")
        parsed = tristana.parse_abilities(data, 18, 0.0, dict(RANKS, Q=0))

        assert "Q" not in parsed

    def test_a_stripped_leveling_row_fails_closed(self):
        """No literal fallback: a degraded cache must raise, not zero out."""
        data = json.loads(json.dumps(get_champion("Tristana")))
        for effect in data["abilities"]["Q"][0]["effects"]:
            effect["leveling"] = []

        with pytest.raises((KeyError, ValueError)):
            tristana.parse_abilities(data, 18, 0.0, dict(RANKS))


class TestTheWindowSplitsTheLiveAutoCount:
    """The engine surface: pre-window / in-window / post-window autos."""

    def test_the_fight_applies_the_buffed_attack_speed(self):
        buffed = _fight(q_rank=5)["champion_stats"]["attack_speed"]
        base = _fight(q_rank=0)["champion_stats"]["attack_speed"]
        ratio = _fight(q_rank=0)["champion_stats"]["attack_speed_ratio"]

        assert buffed == pytest.approx(base + ratio * 1.20)

    def test_the_auto_count_matches_the_windowed_arithmetic(self):
        """floor(in-window) + floor(post-window), not one blended floor."""
        base_fight = _fight(q_rank=0)
        base_as = base_fight["champion_stats"]["attack_speed"]
        ratio = base_fight["champion_stats"]["attack_speed_ratio"]
        buffed_as = base_as + ratio * 1.20
        uptime = 0.8  # the engine's default auto-attack uptime
        window, duration = 7.0, 10.0

        expected = math.floor(buffed_as * window * uptime) + math.floor(
            base_as * (duration - window) * uptime
        )

        assert _fight(q_rank=5)["breakdown"]["auto_attacks"]["count"] == expected
        # And the base fight is the plain single-rate floor.
        assert base_fight["breakdown"]["auto_attacks"]["count"] == math.floor(
            base_as * duration * uptime
        )

    def test_the_window_raises_the_count_without_changing_per_hit_damage(self):
        buffed = _fight(q_rank=5)["breakdown"]["auto_attacks"]
        base = _fight(q_rank=0)["breakdown"]["auto_attacks"]

        assert buffed["count"] > base["count"]
        assert buffed["damage_per_hit"] == pytest.approx(base["damage_per_hit"])


class TestDrawABeadIsASourcedZeroDamageRow:
    """P: bonus attack range only, so ``no_damage``."""

    def test_p_emits_a_visible_zero_row_with_the_sourced_range(self, abilities):
        row = abilities["passive"]

        assert row["name"] == "Draw a Bead"
        assert row["total_raw"] == 0.0
        assert row["parts"] == ()
        # Level 18 reads index 17 of the 20-entry per-level row.
        assert "150" in row["detail"]
        assert "167.65" in row["detail"]

    def test_p_publishes_nothing_to_the_engine(self, abilities):
        row = abilities["passive"]

        assert "stat_buff" not in row
        assert "auto_attack_override" not in row
        assert "on_hit" not in row

    def test_p_has_no_damage_instance_and_only_a_range_atom(self):
        for entry in _WIKI["abilities"]["P"]:
            assert entry["damageType"] is None
            assert entry["affects"] == "Self"

        atoms = _ability_atoms("Tristana", get_champion("Tristana"))["P"]
        assert [atom["atom_id"] for atom in atoms] == ["ability.per-_level _scaling"]
        assert atoms[0]["values"][0] == 0.0
        assert atoms[0]["values"][-1] == pytest.approx(167.65)

    def test_range_cannot_reach_damage_because_is_melee_is_a_static_stat(self):
        """Why range is ``no_damage`` and an attack-speed steroid is not.

        ``damage.py`` reads the melee/ranged split from
        ``champion_stats["is_melee"]`` — a static champion stat, never
        derived from attack range.  The engine's ONLY mention of attack
        range at all is a documentary receipt field inside Senna's
        every-20-souls threshold ledger (``stat_application:
        parse_time_seeded``), which prices nothing.  A patch that wires
        range into a damage formula trips this test.
        """
        source = Path("src/calculator/damage.py").read_text(encoding="utf-8")

        assert 'is_melee = champion_stats["is_melee"]' in source
        occurrences = [
            line.strip() for line in source.splitlines() if "attack_range" in line
        ]
        assert occurrences == [
            '"bonus_attack_range": 20.0 * (threshold_value // 20),'
        ], occurrences


class TestModuleCoverageRecordsTheSplitVerdict:
    def test_coverage_map(self):
        assert tristana.MODULE_COVERAGE == {
            "P": "no_damage",
            "Q": "modeled",
            "W": "modeled",
            "E": "modeled",
            "R": "modeled",
        }

    def test_no_priced_ability_row_moved(self, abilities):
        assert abilities["W"]["total_raw"] == pytest.approx(210.0)
        assert abilities["E"]["total_raw"] == pytest.approx(320.0)
        assert abilities["R"]["total_raw"] == pytest.approx(325.0)
        assert abilities["Q"]["total_raw"] == 0.0
        assert abilities["passive"]["total_raw"] == 0.0
