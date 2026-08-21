"""Rumble P (Junkyard Titan / Overheated) and W (Scrap Shield), plus the
``scaling.py`` unit-alias repair that closing W required.

The roadmap slot session closes Rumble's last two ``out_of_scope`` rows.

**P was mislabelled, not merely stale.** The packet called P
``no_damage``. Its third effect row carries a fully sourced on-hit
formula: Overheated "empowers his basic attacks to deal 5 : 44.12 (based
on level) (+ 25% AP) (+ 4% of the target's maximum health) bonus magic
damage on-hit". The game binary agrees term for term
(``RumbleHeatSystem``: ``TotalBaseDamage`` ByCharLevel 5 -> 40 with the
level-20 extrapolation, a 0.25 AP coefficient, and
``OverheatPercBonusDamage`` 0.04), and ``TestOverheatIsBinaryCorroborated``
re-derives all three from the binary rather than trusting the module.

**Two sourced rows in the same sentence are deliberately withheld**, and
both withholdings are pinned so a later worker cannot quietly "finish"
them:

* the 50% : 142.54% bonus attack speed, because the same sentence states
  its cost ("disabling his abilities as his Heat decays back down to 0
  over 4 seconds") and this engine has no ability-lockout channel —
  importing the upside alone would systematically overstate Rumble;
* the "Bonus Damage" row (65 : 163.32 by level), which is not a damage
  source at all. Read in context it is the CAP on the %max-health term,
  "capped at ... against monsters". ``TestBonusDamageRowIsAMonsterCap``
  pins that reading off the cached description, because the attribute
  name alone reads exactly like a damage row and is the obvious way to
  get this champion wrong.

**Overheat is not simulated, so the proc count is explicit state.** The
``overheat_autos`` option defaults to 0. ``TestZeroAutosCostZero`` pins
the same phantom-proc contract Rammus' W needed in this batch: because
consumers read ONLY ``parts``, a ``count=max(autos, 1)`` floor would
price one full empowered auto at the default.

**W required a genuine kernel repair.** Scrap Shield's third term is
"4% of maximum health". That spelling was missing from
``champions/scaling.py``'s ``_SIMPLE_UNITS`` (only "% maximum health" was
mapped), so ``resolve_scaling`` fell through to its unrecognized-unit
``0.0`` and SILENTLY dropped the term — the exact fail-open this codebase
bans. ``TestMaximumHealthAliasBlastRadius`` pins the alias, enumerates
every cached use of the spelling, and asserts each one resolves to a
non-zero contribution. Galio W is the worst case: its shield has no flat
term at all, so it was computing 0.0 outright.

Why nothing caught it: ``champion_coverage`` certifies units against
``is_supported_scaling_unit``, but only for rows it classifies as DAMAGE
units. Shield- and heal-strength rows are never unit-certified, so a
missing mapping on a utility row is invisible to that gate. Widening the
gate is out of scope for this batch (52 distinct cached units are
currently unsupported across non-damage rows); the enumeration below is
the narrow tripwire for this spelling.

**W stays scanner-priced.** Being shield-only, W cannot carry
``attach_self_shield`` (that payload rides damage-event rows), so it is
derived by the ally-support scanner at target scope "self" — the Ekko-W
precedent. Danger Zone's +50% is heat state and is not applied.
"""

import copy
import json
from pathlib import Path

import pytest

from src.calculator.champions import (
    get_champion_options_meta,
    parse_champion_abilities,
)
from src.calculator.champions.rumble import (
    ASSUMPTIONS,
    MODULE_COVERAGE,
    _MAX_OVERHEAT_AUTOS,
)
from src.calculator.champions.scaling import (
    _SIMPLE_UNITS,
    is_supported_scaling_unit,
    resolve_scaling,
)
from src.calculator.data_fetcher import get_champion
from src.calculator.stats import calculate_total_stats
from src.calculator.support_effects import derive_ally_effects

_RUMBLE = get_champion("Rumble")
_WIKI_ALL = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))
_WIKI = _WIKI_ALL["Rumble"]

# ``data/bin/characters/`` is a gitignored local game-file cache, so CI has
# no copy of it. The ci_evidence_parity tripwire requires every reference to
# be either force-tracked or absence-guarded; this is the guard idiom (the
# test_quinn_p_crit.py precedent). Locally the corroboration really runs.
_BIN_PATH = Path("data/bin/characters/rumble.bin.json")
_BIN = json.loads(_BIN_PATH.read_text(encoding="utf-8")) if _BIN_PATH.exists() else None


def _heat_record() -> dict:
    """The binary ``RumbleHeatSystem`` spell record, or skip when absent."""
    if _BIN is None:
        pytest.skip("local Rumble game-file evidence is unavailable")
    return next(
        value["mSpell"]
        for key, value in _BIN.items()
        if key.endswith("RumbleHeatSystem")
        and isinstance(value, dict)
        and "mSpell" in value
    )


_TARGET_MAX_HEALTH = 2500.0
_TARGET = {
    "target_max_health": _TARGET_MAX_HEALTH,
    "target_current_health": _TARGET_MAX_HEALTH,
    "target_missing_health": 0.0,
}

_P_EFFECT = _WIKI["abilities"]["P"][0]["effects"][2]
_ALIAS = "% of maximum health"


def _data_value(record: dict, name: str) -> list[float]:
    """One named ``DataValues`` row out of a binary spell record."""
    for entry in record.get("DataValues", []):
        if entry.get("name") == name:
            return list(entry.get("values") or [])
    raise AssertionError(f"binary record has no DataValues row {name!r}")


def _leveling_row(effect: dict, attribute: str) -> dict:
    for row in effect.get("leveling", []):
        if row["attribute"] == attribute:
            return row
    raise AssertionError(f"effect has no leveling row {attribute!r}")


def _parse(
    level: int,
    *,
    options: dict | None = None,
    ranks: dict | None = None,
    stats_override: dict | None = None,
):
    """Parse Rumble at *level* with no items, mirroring the pipeline."""
    data = copy.deepcopy(_RUMBLE)
    stats = calculate_total_stats(data, level, [])
    champion_stats = dict(stats)
    if stats_override:
        champion_stats.update(stats_override)
    abilities = parse_champion_abilities(
        data,
        level,
        champion_stats["ability_power"],
        ability_ranks=ranks,
        champion_stats=champion_stats,
        target_stats=dict(_TARGET),
        champion_options=options,
    )
    return champion_stats, abilities


# ---------------------------------------------------------------------------
# P — sourcing re-derived from the binary
# ---------------------------------------------------------------------------


class TestOverheatIsBinaryCorroborated:
    def test_cached_row_carries_all_three_terms(self):
        row = _leveling_row(_P_EFFECT, "Bonus Magic Damage")
        units = [modifier["units"][0] for modifier in row["modifiers"]]
        assert units == ["", "% AP", "% of the target's maximum health"]

    def test_flat_term_is_a_per_level_array_not_a_rank_array(self):
        """Junkyard Titan is an innate: 20 entries, one per level."""
        row = _leveling_row(_P_EFFECT, "Bonus Magic Damage")
        values = row["modifiers"][0]["values"]
        assert len(values) == 20
        assert values[0] == pytest.approx(5.0)
        assert values[17] == pytest.approx(40.0)
        assert values[19] == pytest.approx(44.12)

    def test_binary_ap_coefficient_matches_the_wiki(self):
        row = _leveling_row(_P_EFFECT, "Bonus Magic Damage")
        assert row["modifiers"][1]["values"][0] == pytest.approx(25.0)
        parts = _heat_record()["mSpellCalculations"]["TotalBaseDamage"]["mFormulaParts"]
        coefficients = [
            part.get("mCoefficient")
            for part in parts
            if part.get("mCoefficient") is not None
        ]
        assert pytest.approx(0.25, abs=1e-6) in coefficients

    def test_binary_percent_health_term_matches_the_wiki(self):
        row = _leveling_row(_P_EFFECT, "Bonus Magic Damage")
        assert row["modifiers"][2]["values"][0] == pytest.approx(4.0)
        values = _data_value(_heat_record(), "OverheatPercBonusDamage")
        assert all(value == pytest.approx(0.04, abs=1e-6) for value in values)

    def test_binary_base_ladder_matches_the_wiki_endpoints(self):
        """Wiki L18 == binary's last authored ByCharLevel point (40)."""
        parts = _heat_record()["mSpellCalculations"]["TotalBaseDamage"]["mFormulaParts"]
        ladders = [
            part for part in parts if "ByCharLevel" in str(part.get("__type", ""))
        ]
        assert ladders, "TotalBaseDamage has no per-level ladder part"
        flat = json.dumps(ladders)
        assert "5.0" in flat and "40.0" in flat


class TestOverheatDamage:
    @pytest.mark.parametrize(
        ("level", "flat"),
        [(1, 5.0), (11, 25.59), (18, 40.0), (20, 44.12)],
    )
    def test_per_auto_damage_is_the_sum_of_the_three_terms(self, level, flat):
        stats, abilities = _parse(
            level,
            options={"overheat_autos": 1},
            stats_override={"ability_power": 200.0},
        )
        expected = flat + 0.25 * 200.0 + 0.04 * _TARGET_MAX_HEALTH
        assert stats["ability_power"] == pytest.approx(200.0)
        assert abilities["passive"]["total_raw"] == pytest.approx(expected)

    def test_level_twenty_value_is_hand_derived(self):
        _, abilities = _parse(
            20, options={"overheat_autos": 1}, stats_override={"ability_power": 200.0}
        )
        # 44.12 + 50.00 (25% of 200 AP) + 100.00 (4% of 2500 max HP)
        assert abilities["passive"]["total_raw"] == pytest.approx(194.12)

    def test_target_max_health_term_is_actually_present(self):
        """The term the alias bug class silently drops; measured directly.

        It resolves through ``_parse_compound_unit`` (the cached spelling
        is "% of THE target's maximum health"), a different code path from
        the ``_SIMPLE_UNITS`` alias repaired for W — so both need pinning.
        """
        _, low = _parse(20, options={"overheat_autos": 1})
        data = copy.deepcopy(_RUMBLE)
        stats = calculate_total_stats(data, 20, [])
        doubled = parse_champion_abilities(
            data,
            20,
            stats["ability_power"],
            champion_stats=dict(stats),
            target_stats={
                "target_max_health": _TARGET_MAX_HEALTH * 2,
                "target_current_health": _TARGET_MAX_HEALTH * 2,
                "target_missing_health": 0.0,
            },
            champion_options={"overheat_autos": 1},
        )
        gain = doubled["passive"]["total_raw"] - low["passive"]["total_raw"]
        assert gain == pytest.approx(0.04 * _TARGET_MAX_HEALTH)

    @pytest.mark.parametrize("autos", [1, 2, 5, 12])
    def test_total_scales_linearly_in_the_auto_count(self, autos):
        _, one = _parse(20, options={"overheat_autos": 1})
        _, many = _parse(20, options={"overheat_autos": autos})
        assert many["passive"]["total_raw"] == pytest.approx(
            one["passive"]["total_raw"] * autos
        )
        assert [part.count for part in many["passive"]["parts"]] == [autos]

    def test_auto_count_is_clamped_to_the_rail(self):
        _, capped = _parse(20, options={"overheat_autos": 10_000})
        _, rail = _parse(20, options={"overheat_autos": _MAX_OVERHEAT_AUTOS})
        assert capped["passive"]["total_raw"] == pytest.approx(
            rail["passive"]["total_raw"]
        )

    def test_negative_auto_counts_floor_at_zero(self):
        _, abilities = _parse(20, options={"overheat_autos": -5})
        assert abilities["passive"]["total_raw"] == pytest.approx(0.0)


class TestZeroAutosCostZero:
    """No empowered auto must cost nothing — the Rammus-W phantom pin."""

    def test_default_option_prices_no_overheat_damage(self):
        _, abilities = _parse(20)
        assert abilities["passive"]["total_raw"] == pytest.approx(0.0)
        assert sum(
            part.amount * part.count for part in abilities["passive"]["parts"]
        ) == pytest.approx(0.0)

    def test_zero_and_one_auto_are_not_identical(self):
        _, none = _parse(20, options={"overheat_autos": 0})
        _, one = _parse(20, options={"overheat_autos": 1})
        assert none["passive"]["total_raw"] == pytest.approx(0.0)
        assert one["passive"]["total_raw"] > 0.0

    def test_option_is_registered_with_a_zero_default(self):
        meta = get_champion_options_meta("Rumble")
        option = next(
            entry for entry in meta["options"] if entry["key"] == "overheat_autos"
        )
        assert option["default"] == 0
        assert option["min"] == 0
        assert option["max"] == _MAX_OVERHEAT_AUTOS


# ---------------------------------------------------------------------------
# The two deliberate withholdings
# ---------------------------------------------------------------------------


class TestBonusDamageRowIsAMonsterCap:
    def test_cached_description_reads_it_as_a_cap(self):
        description = _P_EFFECT["description"]
        assert "capped at" in description
        assert "against monsters" in description

    def test_the_row_exists_and_is_not_added_to_the_total(self):
        row = _leveling_row(_P_EFFECT, "Bonus Damage")
        level_twenty_cap = row["modifiers"][0]["values"][19]
        assert level_twenty_cap == pytest.approx(163.32)
        _, abilities = _parse(
            20, options={"overheat_autos": 1}, stats_override={"ability_power": 200.0}
        )
        # 194.12 is the three sourced terms; the cap must not be a fourth.
        assert abilities["passive"]["total_raw"] == pytest.approx(194.12)
        assert abilities["passive"]["total_raw"] != pytest.approx(
            194.12 + level_twenty_cap
        )

    def test_withholding_is_documented(self):
        assumption = next(a for a in ASSUMPTIONS if "Junkyard Titan" in a)
        assert "monster-only cap" in assumption


class TestAttackSpeedSteroidIsWithheld:
    def test_cached_row_exists(self):
        row = _leveling_row(_P_EFFECT, "Per-Level Scaling")
        assert row["modifiers"][0]["values"][0] == pytest.approx(50.0)
        assert row["modifiers"][0]["values"][19] == pytest.approx(142.54)

    def test_no_attack_speed_buff_is_emitted(self):
        _, abilities = _parse(20, options={"overheat_autos": 3})
        assert "stat_buff" not in abilities["passive"]

    def test_withholding_names_the_lockout_it_is_bundled_with(self):
        assumption = next(a for a in ASSUMPTIONS if "Junkyard Titan" in a)
        assert "ability lockout" in assumption
        assert "142.54" in assumption


# ---------------------------------------------------------------------------
# W — the shield and the kernel repair it required
# ---------------------------------------------------------------------------


def _shield(champion: str, slot: str, level: int, stats: dict, rank: int = 5):
    effects = derive_ally_effects(
        get_champion(champion),
        level,
        dict(stats),
        [{"slot": slot, "time": 1.0}],
        {slot: rank},
    )
    return next(effect for effect in effects if effect["kind"] == "shield")


class TestScrapShield:
    def test_shield_is_the_three_sourced_terms(self):
        shield = _shield("Rumble", "W", 18, {"ability_power": 200.0, "health": 2000.0})
        # 145 (rank 5) + 60 (30% AP) + 80 (4% max HP)
        assert shield["amount"] == pytest.approx(285.0)
        assert shield["target_scope"] == "self"

    def test_max_health_term_tracks_the_caster_not_the_target(self):
        low = _shield("Rumble", "W", 18, {"ability_power": 0.0, "health": 2000.0})
        high = _shield("Rumble", "W", 18, {"ability_power": 0.0, "health": 4000.0})
        assert high["amount"] - low["amount"] == pytest.approx(80.0)

    def test_w_carries_no_damage_row(self):
        _, abilities = _parse(18, ranks={"Q": 5, "W": 5, "E": 5, "R": 3})
        assert abilities["W"]["total_raw"] == pytest.approx(0.0)

    def test_danger_zone_bonus_is_not_applied(self):
        """The base row is priced; +50% enhanced is unmodeled heat state."""
        shield = _shield("Rumble", "W", 18, {"ability_power": 200.0, "health": 2000.0})
        assert shield["amount"] != pytest.approx(285.0 * 1.5)
        assumption = next(a for a in ASSUMPTIONS if "Danger Zone Bonus" in a)
        assert "not " in assumption


class TestMaximumHealthAliasBlastRadius:
    """The repaired ``_SIMPLE_UNITS`` alias, pinned end to end."""

    def test_alias_is_mapped_to_self_maximum_health(self):
        assert _SIMPLE_UNITS[_ALIAS] == ("health", 100.0)
        assert is_supported_scaling_unit(_ALIAS)

    def test_alias_resolves_off_champion_health_not_target_health(self):
        resolved = resolve_scaling(
            _ALIAS,
            4.0,
            {"health": 2000.0},
            {"target_max_health": 9999.0},
        )
        assert resolved == pytest.approx(80.0)

    def test_unmapped_units_still_fail_to_zero(self):
        """Pins WHY this was silent: the fallback is a fail-open 0.0.

        Kept as a characterization, not an endorsement — it is the reason
        the enumeration below exists.
        """
        assert (
            resolve_scaling("% of Rumble's spare parts", 4.0, {"health": 2000.0}) == 0
        )

    def test_every_cached_use_of_the_alias_is_enumerated(self):
        """Fail-closed tripwire on the blast radius.

        A new champion adopting this spelling must be reviewed for
        self-vs-target semantics rather than silently inheriting the
        self-health mapping.
        """
        uses = set()
        for name, champion in _WIKI_ALL.items():
            for slot, entries in (champion.get("abilities") or {}).items():
                for ability in entries:
                    for effect in ability.get("effects") or []:
                        for row in effect.get("leveling") or []:
                            for modifier in row.get("modifiers") or []:
                                if _ALIAS in (modifier.get("units") or []):
                                    uses.add((name, slot, row["attribute"]))
        assert uses == {
            ("Galio", "W", "Magic Shield Strength"),
            ("Rumble", "W", "Shield Strength"),
            ("Rumble", "W", "Enhanced Shield Strength"),
            ("Soraka", "W", "Reduced Health Cost"),
        }

    def test_galio_shield_is_no_longer_zero(self):
        """The worst case: Galio W has no flat term, so it computed 0.0."""
        shield = _shield("Galio", "W", 18, {"ability_power": 0.0, "health": 2000.0})
        assert shield["amount"] == pytest.approx(270.0)  # 13.5% of 2000

    @pytest.mark.parametrize(
        ("champion", "slot", "attribute"),
        [
            ("Galio", "W", "Magic Shield Strength"),
            ("Rumble", "W", "Shield Strength"),
            ("Rumble", "W", "Enhanced Shield Strength"),
            ("Soraka", "W", "Reduced Health Cost"),
        ],
    )
    def test_each_cached_use_resolves_to_a_nonzero_contribution(
        self, champion, slot, attribute
    ):
        row = None
        for ability in _WIKI_ALL[champion]["abilities"][slot]:
            for effect in ability.get("effects") or []:
                for candidate in effect.get("leveling") or []:
                    if candidate["attribute"] == attribute:
                        row = candidate
        assert row is not None
        modifier = next(
            entry for entry in row["modifiers"] if _ALIAS in (entry.get("units") or [])
        )
        # Rank 1 for Soraka's descending cost row, max rank otherwise; both
        # must be non-zero for the alias to be doing any work at all.
        value = max(modifier["values"])
        assert resolve_scaling(_ALIAS, value, {"health": 2000.0}) > 0.0


# ---------------------------------------------------------------------------
# Coverage contract
# ---------------------------------------------------------------------------


def test_module_coverage_has_no_out_of_scope_slots_left():
    assert MODULE_COVERAGE == {
        "P": "modeled",
        "Q": "modeled",
        "W": "modeled",
        "E": "modeled",
        "R": "modeled",
    }
