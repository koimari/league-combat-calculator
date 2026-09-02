"""Rammus P (Spiked Shell) and E (Frenzying Taunt), plus the W thorns
phantom-proc repair the same closure surfaced.

The roadmap slot session closes Rammus' last two ``out_of_scope`` rows.
They close for opposite reasons, and the difference is the whole point of
pinning them together.

**P was a real, unpriced steroid — a behavior change, not a stale label.**
Spiked Shell is easy to mistake for the thorns reflect; it is not. Thorns
is W (``Defensive Ball Curl``, already modeled). P is a pure stat
conversion: "Rammus gains bonus attack damage equal to the sum of 15%
total armor and 15% total magic resistance". The cached P entry has an
EMPTY ``leveling`` array, so the two ratios live only in prose — which is
exactly the shape that invites a silent literal. ``TestSpikedShellIsBinary
Corroborated`` re-derives both ratios from the game binary
(``RammusP`` ``ArmorRatio`` / ``MagicResistRatio``) instead of trusting the
module's constants, and pins the *negative* half of the sourcing decision
too: the record carries a ``BaseDamage`` DataValue of 10.0 that its own
``TotalDamage`` calculation never references, so the modeled formula must
have exactly two terms and no flat one.

**The double-application trap.** ``_spiked_shell`` both mutates
``ctx.stats`` (so later slots in the same parse read the buffed AD) and
emits a ``stat_buff`` (so the fight engine applies it to the auto stream).
Those are two different dictionaries only because
``build_stats_context`` copies; if that ever stops being a copy the buff
lands twice and every Rammus auto silently gains a second +15%/+15%.
``TestBuffAppliesExactlyOnce`` measures the fight's own
``champion_stats`` rather than re-reading the parse, so it fails closed on
that regression.

**E is the opposite: a sourced damage row that must NOT be priced.**
The cached E carries "Monster Magic Damage" (80-160 + 70% AP), but the
sourced description restricts it by target class — "Monsters are
additionally dealt magic damage upon being affected." This engine's
``target_class`` is a two-value label (``champion``/``minion``) with no
monster value at all, so the row can never bind on the surface the
calculator exposes. It is documented in ASSUMPTIONS, never added. The
taunt itself is sourced and already emitted as a control event, which is
why E is ``no_damage`` rather than ``out_of_scope``.

**The W phantom-proc pin.** A ``_defensive_ball_curl`` that forces
``count=max(autos, 1)`` prices one full thorns proc at the default
``w_thorns_autos=0``, because ``damage_entry``'s consumers read ONLY
``parts`` — ``autos=0`` and ``autos=1`` score identically. Zero enemy autos
must cost zero; ``TestThornsCountsZeroAsZero`` pins that, since the same
"floor the count at 1" reflex is what the Rumble P row in this batch had
to avoid as well.
"""

import copy
import json
from pathlib import Path

import pytest

from src.calculator.champions import parse_champion_abilities
from src.calculator.champions.rammus import (
    _SPIKED_SHELL_ARMOR_RATIO,
    _SPIKED_SHELL_MAGIC_RESISTANCE_RATIO,
    ASSUMPTIONS,
    MODULE_COVERAGE,
)
from src.calculator.data_fetcher import get_champion
from src.calculator.item_effects import TARGET_CLASSES
from src.calculator.pipeline import FightParams, run_fight
from src.calculator.stats import calculate_total_stats
from tests import game_binary

_RAMMUS = get_champion("Rammus")
_WIKI = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))["Rammus"]

# ``data/bin/characters/`` is a gitignored local game-file cache, so CI has
# no copy of it. The ci_evidence_parity tripwire requires every reference to
# be either force-tracked or absence-guarded; this is the guard idiom (the
# test_quinn_p_crit.py precedent). Locally the corroboration really runs.
_BIN_PATH = Path("data/bin/characters/rammus.bin.json")
_BIN = json.loads(_BIN_PATH.read_text(encoding="utf-8")) if _BIN_PATH.exists() else None


def _bin_p() -> dict:
    """The binary ``RammusP`` spell record, or skip when absent."""
    if _BIN is None:
        pytest.skip("local Rammus game-file evidence is unavailable")
    return _BIN["Characters/Rammus/Spells/RammusPAbility/RammusP"]["mSpell"]


_TARGET = {
    "target_max_health": 2000.0,
    "target_current_health": 2000.0,
    "target_missing_health": 0.0,
}


def _parse(level: int, *, options: dict | None = None, ranks: dict | None = None):
    """Parse Rammus at *level* with no items, mirroring the pipeline."""
    data = copy.deepcopy(_RAMMUS)
    stats = calculate_total_stats(data, level, [])
    abilities = parse_champion_abilities(
        data,
        level,
        stats["ability_power"],
        ability_ranks=ranks,
        champion_stats=dict(stats),
        target_stats=dict(_TARGET),
        champion_options=options,
    )
    return stats, abilities


def _fight(level: int, *, options: dict | None = None, auto_uptime: float = 1.0):
    """One deterministic auto-only fight against a zero-resistance dummy."""
    params = FightParams(
        target_health=2000.0,
        target_bonus_health=0.0,
        target_armor=0.0,
        target_magic_resistance=0.0,
        fight_duration_seconds=5.0,
        auto_attack_uptime=auto_uptime,
        one_rotation=False,
        include_actives=False,
        cast_order=None,
        auto_attacks_only=True,
        ability_ranks=None,
        champion_options=options,
        deterministic=True,
    )
    return run_fight(copy.deepcopy(_RAMMUS), level, [], params)


# ---------------------------------------------------------------------------
# P — the sourcing, re-derived rather than trusted
# ---------------------------------------------------------------------------


class TestSpikedShellIsBinaryCorroborated:
    def test_wiki_prose_states_both_ratios(self):
        """The cache's only P source is prose; pin the exact sentence."""
        effects = _WIKI["abilities"]["P"][0]["effects"]
        assert len(effects) == 1
        description = effects[0]["description"]
        assert "15% total armor" in description
        assert "15% total magic resistance" in description
        assert "bonus attack damage" in description

    def test_the_p_leveling_array_is_empty(self):
        """Why the constants are hardcoded: there is no row to read."""
        assert _WIKI["abilities"]["P"][0]["effects"][0].get("leveling", []) == []

    @pytest.mark.parametrize(
        ("data_value", "constant"),
        [
            ("ArmorRatio", _SPIKED_SHELL_ARMOR_RATIO),
            ("MagicResistRatio", _SPIKED_SHELL_MAGIC_RESISTANCE_RATIO),
        ],
    )
    def test_binary_ratios_match_the_module_constants(self, data_value, constant):
        values = game_binary.data_value(_bin_p(), data_value)
        assert values, f"{data_value} row is empty"
        assert all(value == pytest.approx(constant, abs=1e-6) for value in values)

    def test_binary_formula_has_exactly_the_two_stat_terms(self):
        """The negative half of the decision: no third term exists.

        ``BaseDamage`` (10.0) is present in ``DataValues`` but absent from
        ``TotalDamage``'s formula parts, so a flat term would be invented,
        not sourced. If a future patch wires it in, this fails.
        """
        parts = _bin_p()["mSpellCalculations"]["TotalDamage"]["mFormulaParts"]
        assert [part["mDataValue"] for part in parts] == [
            "ArmorRatio",
            "MagicResistRatio",
        ]
        assert all(
            part["__type"] == "StatByNamedDataValueCalculationPart" for part in parts
        )
        assert game_binary.data_value(_bin_p(), "BaseDamage")  # exists...
        assert "BaseDamage" not in {part["mDataValue"] for part in parts}  # ...unused


class TestSpikedShellBuff:
    @pytest.mark.parametrize("level", [1, 6, 11, 18, 20])
    def test_buff_is_fifteen_percent_of_each_total_resistance(self, level):
        stats, abilities = _parse(level)
        expected = 0.15 * stats["armor"] + 0.15 * stats["magic_resistance"]
        assert abilities["passive"]["stat_buff"] == {
            "bonus_attack_damage": pytest.approx(expected)
        }

    def test_level_eighteen_value_is_hand_derived(self):
        """A literal anchor so a stat-growth drift is visible here too."""
        stats, abilities = _parse(18)
        assert stats["armor"] == pytest.approx(112.0)
        assert stats["magic_resistance"] == pytest.approx(67.0)
        assert abilities["passive"]["stat_buff"][
            "bonus_attack_damage"
        ] == pytest.approx(26.85)

    def test_the_grant_is_bonus_ad_not_a_damage_row(self):
        _, abilities = _parse(18)
        assert abilities["passive"]["total_raw"] == pytest.approx(0.0)
        assert "deals no damage of its own" in abilities["passive"]["detail"]

    def test_buff_scales_with_purchased_resistances(self):
        """A prose-sourced ratio must still read TOTAL, not base, armor."""
        data = copy.deepcopy(_RAMMUS)
        stats = calculate_total_stats(data, 18, [])
        inflated = dict(stats)
        inflated["armor"] = stats["armor"] + 100.0
        inflated["magic_resistance"] = stats["magic_resistance"] + 100.0
        abilities = parse_champion_abilities(
            data,
            18,
            stats["ability_power"],
            champion_stats=inflated,
            target_stats=dict(_TARGET),
        )
        gain = abilities["passive"]["stat_buff"]["bonus_attack_damage"] - 26.85
        assert gain == pytest.approx(30.0)  # 15% of 100 armor + 15% of 100 MR


class TestBuffAppliesExactlyOnce:
    """The parse-time ``ctx.stats`` mutation must not reach the fight twice.

    ``_spiked_shell`` writes the buff into ``ctx.stats`` AND emits it as a
    ``stat_buff``. That is only safe because the parse context holds a
    COPY of the champion stats. Measured off the fight's own resolved
    ``champion_stats``, so a lost copy shows up as a doubled value.
    """

    def test_fight_attack_damage_gains_the_buff_once(self):
        stats, abilities = _parse(18)
        buff = abilities["passive"]["stat_buff"]["bonus_attack_damage"]
        result = _fight(18)
        assert result["champion_stats"]["attack_damage"] == pytest.approx(
            stats["attack_damage"] + buff
        )
        assert result["champion_stats"]["bonus_attack_damage"] == pytest.approx(buff)

    def test_auto_damage_prices_the_buffed_ad(self):
        """Every auto must land at the buffed AD, not the base one."""
        result = _fight(18)
        buffed_ad = result["champion_stats"]["attack_damage"]
        assert buffed_ad == pytest.approx(138.85)
        # Zero resistances: raw == mitigated, so the total must be an exact
        # whole multiple of one buffed auto.
        autos = result["auto_attack_damage"] / buffed_ad
        assert autos == pytest.approx(round(autos))
        assert autos >= 1


# ---------------------------------------------------------------------------
# E — a sourced row that must stay unpriced
# ---------------------------------------------------------------------------


class TestFrenzyingTauntIsNoDamageAgainstChampions:
    def test_the_cached_damage_row_is_monster_restricted(self):
        """The row exists; the description is what withholds it."""
        effect = _WIKI["abilities"]["E"][0]["effects"][0]
        attributes = {row["attribute"] for row in effect["leveling"]}
        assert "Monster Magic Damage" in attributes
        assert "Monsters are additionally dealt magic damage" in effect["description"]

    def test_engine_has_no_monster_target_class(self):
        """Why the row can never bind on the exposed surface."""
        assert "monster" not in TARGET_CLASSES
        assert set(TARGET_CLASSES) == {"champion", "minion"}

    @pytest.mark.parametrize("level", [6, 11, 18])
    def test_e_prices_zero_damage(self, level):
        _, abilities = _parse(level, ranks={"Q": 5, "W": 5, "E": 5, "R": 3})
        assert abilities["E"]["total_raw"] == pytest.approx(0.0)

    def test_e_still_emits_the_sourced_taunt(self):
        """``no_damage`` must not mean ``no effect``."""
        _, abilities = _parse(18, ranks={"Q": 5, "W": 5, "E": 5, "R": 3})
        events = abilities["E"]["control_events"]
        assert [event.kind for event in events] == ["taunt"]
        assert events[0].duration == pytest.approx(2.0)  # rank 5 of 1.2-2.0s
        atom = abilities["E"]["control_source_atoms"][0]
        assert atom["values"] == [1.2, 1.4, 1.6, 1.8, 2.0]

    def test_monster_row_is_documented_not_silently_dropped(self):
        assumption = next(a for a in ASSUMPTIONS if "Frenzying Taunt" in a)
        assert "Monster Magic Damage" in assumption
        assert "no monster value" in assumption or "has no monster" in assumption


# ---------------------------------------------------------------------------
# W — the phantom-proc repair
# ---------------------------------------------------------------------------


class TestThornsCountsZeroAsZero:
    def test_default_option_prices_no_thorns(self):
        """The regression: ``count=max(autos, 1)`` charged one free proc."""
        _, abilities = _parse(18, ranks={"Q": 5, "W": 5, "E": 5, "R": 3})
        assert abilities["W"]["total_raw"] == pytest.approx(0.0)
        assert sum(
            part.amount * part.count for part in abilities["W"]["parts"]
        ) == pytest.approx(0.0)

    def test_zero_and_one_auto_are_no_longer_identical(self):
        ranks = {"Q": 5, "W": 5, "E": 5, "R": 3}
        _, none = _parse(18, ranks=ranks, options={"w_thorns_autos": 0})
        _, one = _parse(18, ranks=ranks, options={"w_thorns_autos": 1})
        assert none["W"]["total_raw"] == pytest.approx(0.0)
        assert one["W"]["total_raw"] > 0.0

    @pytest.mark.parametrize("autos", [1, 2, 5])
    def test_thorns_scale_linearly_in_the_auto_count(self, autos):
        ranks = {"Q": 5, "W": 5, "E": 5, "R": 3}
        _, one = _parse(18, ranks=ranks, options={"w_thorns_autos": 1})
        _, many = _parse(18, ranks=ranks, options={"w_thorns_autos": autos})
        assert many["W"]["total_raw"] == pytest.approx(one["W"]["total_raw"] * autos)


# ---------------------------------------------------------------------------
# Coverage contract
# ---------------------------------------------------------------------------


def test_module_coverage_has_no_out_of_scope_slots_left():
    assert MODULE_COVERAGE == {
        "P": "modeled",
        "Q": "modeled",
        "W": "modeled",
        "E": "no_damage",
        "R": "modeled",
    }
