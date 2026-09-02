"""Sylas P (Petricite Burst) and R (Hijack) — a conversion and a kernel gap.

The roadmap slot session closes Sylas' last two ``out_of_scope`` rows, and
they close differently. P becomes ``modeled``; R stays open. Both verdicts
are pinned here because both were nearly gotten wrong in opposite
directions.

**P is a CONVERSION, not a bonus row, and that distinction is the whole
test module.** The batch's working template — Rumble's Overheated on-hit,
Seraphine's Notes — adds a sourced magic row on top of the ordinary swing.
Applying that template to Petricite Burst would have inflated Sylas, and
three independent reads say so:

* the ratio is **130% AD**. No bonus row can exceed a whole auto and still
  be called the attack's own damage;
* the cached note "Spellblade damage does not get converted to magic
  damage" only parses if the attack's own damage *is* converted;
* the wiki states the 130% AD (+ 30% AP) is the empowered attack's total,
  magic instead of physical, with on-hit effects and life steal still
  applying to the primary target.

``TestConversionNotBonusRow`` measures the harm rather than asserting it:
at level 18 with 200 AP against 100 armor / 0 magic resistance, the correct
conversion prices one empowered swing at 205.60, while the additive reading
would have priced 261.60 — an overstatement of exactly 56.00, which is
precisely the ordinary physical swing that should have been *replaced*.
That number is the phantom auto the wrong model invents.

The channel already existed: ``auto_attack_conversion`` (the Galio Colossal
Smash precedent). The module supplies only the non-AD remainder,
``0.30 x total AD + 0.30 x AP``, and the engine's own swing path keeps the
AD term and its crits. ``TestBonusRawIsTheNonADRemainder`` re-derives both
coefficients from the game binary, because every ``leveling`` array on
Sylas' cached P entry is EMPTY — the ratios live only in description prose,
so the constants would otherwise be unfalsifiable.

**Four sourced riders are withheld, and each withholding is pinned** so a
later worker cannot quietly "fix" the module by adding one:
the secondary-target whirl (40% AD + 20% AP), the nonstandard
(175% + 30%) critical strike, the 115% monster multiplier plus the
secondary-target minion execute, and the 125% bonus attack speed.
``TestWithheldRiders`` asserts the constants exist AND that no emitted row
carries them. The crit case is the interesting one: this kernel genuinely
cannot express it, and ``TestNonstandardCritCannotBeExpressed`` measures
why — ``DamagePart.crit_effectiveness`` scales the crit PROBABILITY
(``crit_probability = min(1.0, eff * state.crit_chance)``) and the
multiplier applied is the global ``state.crit_multiplier``, so no value of
``crit_effectiveness`` yields a 175% multiplier.

**R stays ``out_of_scope``, and this is the Olaf-R rule in its strongest
form.** Hijack is not a slot whose damage is zero — it is a slot whose
damage is *another champion's ultimate*. Calling it ``no_damage`` would be
flatly false. ``TestHijackIsAKernelGapNotAnEvidenceGap`` pins both halves:
the binary ``SylasR`` record carries exactly one calculation,
``PerTargetCooldown``, with no damage formula, and the sourced AP-conversion
rule that would make a cross-champion import correct (0.6% AP per 1% total
AD, 0.4% AP per 1% bonus AD) has no channel that rewrites a foreign
ability's scaling terms.
"""

import copy
import json
from pathlib import Path

import pytest

from src.calculator.ability_spec import DamagePart
from src.calculator.champions import (
    get_champion_option_rotation,
    parse_champion_abilities,
)
from src.calculator.champions.sylas import (
    _MAX_UNSHACKLED_STACKS,
    _PRIMARY_AP_RATIO,
    _PRIMARY_TOTAL_AD_RATIO,
    _SECONDARY_AP_RATIO,
    _SECONDARY_TOTAL_AD_RATIO,
    ASSUMPTIONS,
    MODULE_COVERAGE,
    OPTIONS,
)
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.data_fetcher import get_champion
from src.calculator.stats import calculate_total_stats
from tests import game_binary

_SYLAS = get_champion("Sylas")
_WIKI = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))["Sylas"]

# ``data/bin/characters/`` is a gitignored local game-file cache, so CI has
# no copy of it. The ci_evidence_parity tripwire requires every reference to
# be either force-tracked or absence-guarded; this is the guard idiom (the
# test_quinn_p_crit.py precedent). Locally the corroboration really runs.
_BIN_PATH = Path("data/bin/characters/sylas.bin.json")
_BIN = json.loads(_BIN_PATH.read_text(encoding="utf-8")) if _BIN_PATH.exists() else None


def _spell_record(suffix: str) -> dict:
    """One binary ``mSpell`` record by object-path suffix, or skip."""
    if _BIN is None:
        pytest.skip("local Sylas game-file evidence is unavailable")
    return next(
        value["mSpell"]
        for key, value in _BIN.items()
        if key.endswith(suffix) and isinstance(value, dict) and "mSpell" in value
    )


_P_ENTRY = _WIKI["abilities"]["P"][0]
_R_ENTRY = _WIKI["abilities"]["R"][0]

_TARGET = {
    "target_max_health": 3000.0,
    "target_current_health": 3000.0,
    "target_missing_health": 0.0,
}

# Level 18, no items: the stat growth formula puts Sylas at exactly 112 AD,
# which keeps every hand-derived figure below a clean arithmetic check.
_LEVEL = 18
_AD = 112.0
_AP = 200.0


def _parse(
    *,
    procs: int | None = None,
    level: int = _LEVEL,
    ability_power: float = _AP,
    ranks: dict | None = None,
):
    """Parse Sylas at *level* with no items, mirroring the pipeline."""
    data = copy.deepcopy(_SYLAS)
    champion_stats = dict(calculate_total_stats(data, level, []))
    champion_stats["ability_power"] = ability_power
    options: dict = {} if procs is None else {"passive_procs": procs}
    abilities = parse_champion_abilities(
        data,
        level,
        ability_power,
        ability_ranks=ranks or {"Q": 5, "W": 5, "E": 5, "R": 3},
        champion_stats=champion_stats,
        target_stats=dict(_TARGET),
        champion_options=options,
    )
    return champion_stats, abilities


def _conversion(**kwargs) -> dict:
    """The ``auto_attack_conversion`` payload off the parsed P slot."""
    _, abilities = _parse(**kwargs)
    return abilities["passive"]["auto_attack_conversion"]


def _fight(
    *,
    procs: int,
    duration: float = 1.0,
    armor: float = 100.0,
    magic_resistance: float = 0.0,
):
    """Autos-only deterministic fight — isolates the swing accounting."""
    champion_stats, abilities = _parse(
        procs=procs,
        ranks={"Q": 0, "W": 0, "E": 0, "R": 0},
    )
    return calculate_fight_damage(
        champion_stats,
        abilities,
        [],
        FightConfig(
            target_health=3000.0,
            target_armor=armor,
            target_magic_resistance=magic_resistance,
            fight_duration_seconds=duration,
            auto_attack_uptime=1.0,
            auto_attacks_only=True,
            deterministic=True,
        ),
    )


def _converted_damage(result: dict) -> float:
    breakdown = result["breakdown"].get("on_hit_ability_passive")
    return float(breakdown["total_damage"]) if breakdown else 0.0


# ---------------------------------------------------------------------------
# The central claim: conversion, not a bonus row
# ---------------------------------------------------------------------------


class TestConversionNotBonusRow:
    def test_level_18_stat_anchor(self):
        """Every hand-derived figure below rests on this AD."""
        champion_stats, _ = _parse(procs=0)
        assert champion_stats["attack_damage"] == pytest.approx(_AD)

    def test_p_rides_the_conversion_channel_and_books_no_ability_damage(self):
        """The slot keeps the batch's full row shape but contributes zero.

        Petricite Burst decorates the packet's own well-formed zero row
        rather than replacing it, so the module still satisfies the
        batch-wide slot contract (``tests/test_cp10_batch_08.py`` requires
        every parsed slot to carry ``parts`` and ``damage_type``). The
        ledger contribution must nevertheless be exactly nothing: every
        point of this passive's damage arrives through the converted basic
        attack, so a non-empty ``parts`` here would be counted twice.
        """
        _, abilities = _parse(procs=1)
        passive = abilities["passive"]

        assert "auto_attack_conversion" in passive
        assert passive["parts"] == ()
        assert passive["total_raw"] == pytest.approx(0.0)
        assert passive["damage_type"] == "magic"

    def test_full_row_shape_matches_the_batch_slot_contract(self):
        _, abilities = _parse(procs=1)
        for slot in ("passive", "Q", "W", "E", "R"):
            assert "parts" in abilities[slot]
            assert "damage_type" in abilities[slot]

    def test_decorating_the_packet_row_did_not_add_ledger_damage(self):
        """Spending stacks must never move the ability ledger."""
        for procs in (0, 1, 3):
            _, abilities = _parse(procs=procs)
            assert abilities["passive"]["total_raw"] == pytest.approx(0.0)
            assert abilities["passive"]["parts"] == ()

    def test_one_empowered_swing_replaces_rather_than_adds(self):
        """205.60 magic, and the physical swing is GONE — not 56 + 205.6."""
        result = _fight(procs=1)
        assert _converted_damage(result) == pytest.approx(205.60, abs=0.01)
        assert result["breakdown"]["auto_attacks"]["total_damage"] == pytest.approx(0.0)
        assert result["total_damage"] == pytest.approx(205.60, abs=0.01)

    def test_the_baseline_swing_it_replaces(self):
        """Without a proc the same fight is one ordinary armor-mitigated auto."""
        result = _fight(procs=0)
        assert result["breakdown"]["auto_attacks"]["total_damage"] == pytest.approx(
            _AD * 100.0 / 200.0
        )
        assert result["total_damage"] == pytest.approx(56.0)
        assert _converted_damage(result) == pytest.approx(0.0)

    def test_additive_reading_would_have_invented_one_whole_auto(self):
        """The measured harm of the rejected model: exactly the phantom swing.

        Had P been priced as the batch's usual additive magic row, the fight
        would have kept the ordinary physical swing (56.00 against 100 armor)
        AND added the full 130% AD + 30% AP as magic (205.60 against 0 magic
        resistance) for 261.60. The conversion prices 205.60. The 56.00 gap
        is not a rounding difference — it is a whole extra basic attack per
        empowered swing.
        """
        conversion_total = _converted_damage(_fight(procs=1))
        ordinary_swing = _fight(procs=0)["total_damage"]
        naive_additive_total = ordinary_swing + (
            _PRIMARY_TOTAL_AD_RATIO * _AD + _PRIMARY_AP_RATIO * _AP
        )

        assert naive_additive_total == pytest.approx(261.60, abs=0.01)
        assert conversion_total == pytest.approx(205.60, abs=0.01)
        assert naive_additive_total - conversion_total == pytest.approx(56.0, abs=0.01)
        assert naive_additive_total - conversion_total == pytest.approx(
            ordinary_swing, abs=0.01
        )

    def test_converted_swing_is_mitigated_as_magic_not_physical(self):
        """The other half of the harm: the swing changes resistance channel.

        Same fight, resistances swapped. If the converted instance were still
        mitigated as physical, swapping 100 armor for 100 magic resistance
        would not move it.
        """
        unresisted = _converted_damage(
            _fight(procs=1, armor=100.0, magic_resistance=0.0)
        )
        resisted = _converted_damage(_fight(procs=1, armor=0.0, magic_resistance=100.0))

        assert unresisted == pytest.approx(205.60, abs=0.01)
        assert resisted == pytest.approx(205.60 / 2.0, abs=0.01)

    def test_conversion_does_not_replace_later_ordinary_swings(self):
        """One stack spent converts ONE swing; the rest stay physical."""
        result = _fight(procs=1, duration=3.0)
        assert _converted_damage(result) == pytest.approx(205.60, abs=0.01)
        # Two further ordinary autos at 56.00 each.
        assert result["breakdown"]["auto_attacks"]["total_damage"] == pytest.approx(
            112.0, abs=0.01
        )

    def test_conversion_is_bounded_by_the_number_of_swings(self):
        """Three stacks in a one-auto fight cannot convert three swings."""
        one_auto = _converted_damage(_fight(procs=3, duration=1.0))
        assert one_auto == pytest.approx(205.60, abs=0.01)

    def test_converted_damage_scales_with_stacks_spent(self):
        """Over a three-auto fight, each extra stack converts one more swing."""
        totals = [
            _converted_damage(_fight(procs=n, duration=3.0)) for n in (0, 1, 2, 3)
        ]
        assert totals == pytest.approx([0.0, 205.60, 411.20, 616.80], abs=0.02)


# ---------------------------------------------------------------------------
# bonus_raw arithmetic and its binary provenance
# ---------------------------------------------------------------------------


class TestBonusRawIsTheNonADRemainder:
    def test_bonus_raw_excludes_the_ad_the_engine_already_owns(self):
        conversion = _conversion(procs=1)
        modified_total = _PRIMARY_TOTAL_AD_RATIO * _AD + _PRIMARY_AP_RATIO * _AP
        assert modified_total == pytest.approx(205.60)
        assert conversion["bonus_raw"] == pytest.approx(modified_total - _AD)
        assert conversion["bonus_raw"] == pytest.approx(93.60)

    def test_bonus_raw_is_less_than_a_whole_auto(self):
        """The structural signature of a conversion contract.

        A bonus-on-hit row would have carried the FULL 205.60. That
        ``bonus_raw`` is smaller than the champion's own AD is what proves
        the engine is expected to supply the swing.
        """
        assert _conversion(procs=1)["bonus_raw"] < _AD

    def test_bonus_raw_is_the_sum_of_the_two_non_ad_terms(self):
        """0.30 x total AD (the remainder above 1.0) + 0.30 x AP."""
        conversion = _conversion(procs=1)
        assert conversion["bonus_raw"] == pytest.approx(0.30 * _AD + 0.30 * _AP)

    def test_ap_sensitivity_is_exactly_the_primary_ap_ratio(self):
        low = _conversion(procs=1, ability_power=0.0)["bonus_raw"]
        high = _conversion(procs=1, ability_power=100.0)["bonus_raw"]
        assert high - low == pytest.approx(_PRIMARY_AP_RATIO * 100.0)
        assert low == pytest.approx(0.30 * _AD)

    def test_ad_sensitivity_is_the_ratio_minus_the_engine_owned_swing(self):
        """Level 11 vs 18 moves AD; bonus_raw moves at 0.30 per point."""
        stats_11, _ = _parse(procs=1, level=11)
        stats_18, _ = _parse(procs=1, level=18)
        low = _conversion(procs=1, level=11)["bonus_raw"]
        high = _conversion(procs=1, level=18)["bonus_raw"]
        ad_delta = stats_18["attack_damage"] - stats_11["attack_damage"]

        assert ad_delta > 0
        assert high - low == pytest.approx(
            (_PRIMARY_TOTAL_AD_RATIO - 1.0) * ad_delta, abs=1e-6
        )

    def test_damage_type_is_magic(self):
        assert _conversion(procs=1)["damage_type"] == "magic"

    def test_bonus_raw_never_goes_negative(self):
        """The floor is unreachable at a 1.30 ratio, and it stays pinned.

        A future patch that dropped the primary ratio below 1.0 would make
        the empowered attack weaker than the swing it replaces; the module
        clamps rather than emitting a negative bonus that would silently
        refund damage.
        """
        assert _PRIMARY_TOTAL_AD_RATIO > 1.0
        assert _conversion(procs=1, ability_power=0.0)["bonus_raw"] >= 0.0


class TestBinaryCorroborationOfTheRatios:
    """The cached ``leveling`` arrays are empty, so the binary is the source."""

    def test_cached_leveling_arrays_are_all_empty(self):
        """Why the ratios are module constants at all."""
        assert _P_ENTRY["effects"]
        for effect in _P_ENTRY["effects"]:
            assert effect["leveling"] == []

    def test_prose_carries_the_primary_ratios(self):
        text = " ".join(effect["description"] for effect in _P_ENTRY["effects"])
        assert "130% AD" in text
        assert "30% AP" in text

    def test_primary_damage_has_exactly_two_formula_parts(self):
        """No third term may be invented (the Rammus BaseDamage lesson)."""
        record = _spell_record("SylasPassive")
        parts = record["mSpellCalculations"]["PassiveDamage"]["mFormulaParts"]
        assert len(parts) == 2

    def test_primary_ad_coefficient_is_total_ad(self):
        record = _spell_record("SylasPassive")
        parts = record["mSpellCalculations"]["PassiveDamage"]["mFormulaParts"]
        ad_part = parts[0]
        assert ad_part["__type"] == "StatByCoefficientCalculationPart"
        assert ad_part["mStat"] == 2  # attack damage
        # No mStatFormula override => TOTAL attack damage, not bonus AD
        # (the Senna / Miss Fortune / Naafiri precedent).
        assert "mStatFormula" not in ad_part
        assert ad_part["mCoefficient"] == pytest.approx(
            _PRIMARY_TOTAL_AD_RATIO, abs=1e-6
        )

    def test_primary_ap_coefficient(self):
        record = _spell_record("SylasPassive")
        parts = record["mSpellCalculations"]["PassiveDamage"]["mFormulaParts"]
        ap_part = parts[1]
        assert ap_part["__type"] == "StatByCoefficientCalculationPart"
        assert "mStat" not in ap_part  # stat 0 = ability power
        assert ap_part["mCoefficient"] == pytest.approx(_PRIMARY_AP_RATIO, abs=1e-6)

    def test_module_reads_total_ad_the_same_way_the_binary_does(self):
        """Bonus AD would have understated it; the ratio is on TOTAL AD.

        At level 18 with no items, bonus AD is 0 while total AD is 112 — so
        a bonus-AD reading would collapse the whole AD term to zero.
        """
        champion_stats, _ = _parse(procs=1)
        assert champion_stats.get("bonus_attack_damage", 0.0) == pytest.approx(0.0)
        assert _conversion(procs=1)["bonus_raw"] > 0.30 * _AP


# ---------------------------------------------------------------------------
# Stack accounting
# ---------------------------------------------------------------------------


class TestUnshackledStackAccounting:
    def test_default_is_zero_attacks(self):
        """Fail-closed: an unset option must not add damage."""
        assert _conversion()["count"] == 0

    def test_default_fight_is_identical_to_no_conversion(self):
        """The zero-golden-diff pin for this batch."""
        default_total = _fight(procs=0)["total_damage"]
        _, abilities = _parse(ranks={"Q": 0, "W": 0, "E": 0, "R": 0})
        champion_stats, _ = _parse(ranks={"Q": 0, "W": 0, "E": 0, "R": 0})
        unset = calculate_fight_damage(
            champion_stats,
            abilities,
            [],
            FightConfig(
                target_health=3000.0,
                target_armor=100.0,
                target_magic_resistance=0.0,
                fight_duration_seconds=1.0,
                auto_attack_uptime=1.0,
                auto_attacks_only=True,
                deterministic=True,
            ),
        )
        assert unset["total_damage"] == pytest.approx(default_total)

    def test_stack_cap_is_the_sourced_three(self):
        assert _MAX_UNSHACKLED_STACKS == 3
        assert "stacking up to 3 times" in _P_ENTRY["effects"][0]["description"]

    def test_binary_passive_charges_corroborates_the_cap(self):
        record = _spell_record("SylasPassive")
        charges = game_binary.data_value(record, "PassiveCharges")
        # Rank-indexed; every real rank holds 3.
        assert charges[1:] == [3.0] * len(charges[1:])

    def test_requests_above_the_cap_are_clamped(self):
        assert _conversion(procs=9)["count"] == _MAX_UNSHACKLED_STACKS

    def test_negative_requests_floor_at_zero(self):
        assert _conversion(procs=-4)["count"] == 0

    def test_option_metadata_matches_the_sourced_bounds(self):
        option = next(opt for opt in OPTIONS if opt["key"] == "passive_procs")
        assert option["type"] == "int"
        assert option["default"] == 0
        assert option["min"] == 0
        assert option["max"] == _MAX_UNSHACKLED_STACKS

    def test_option_is_classified_as_caster_state(self):
        """Stacks come from Sylas' own casts over a window the engine does
        not simulate, so the count is self_state — not a consume edge (which
        would have to name one setup slot, and every ability cast feeds it).
        """
        rotation = get_champion_option_rotation("Sylas")
        assert rotation["passive_procs"] == {"role": "self_state", "slot": "P"}


# ---------------------------------------------------------------------------
# Withheld riders — each pinned so it cannot be quietly "fixed" in
# ---------------------------------------------------------------------------


class TestWithheldRiders:
    def test_secondary_whirl_ratios_are_sourced_but_unmodeled(self):
        """40% AD + 20% AP needs nearby enemies the 1v1 surface lacks."""
        assert _SECONDARY_TOTAL_AD_RATIO == 0.40
        assert _SECONDARY_AP_RATIO == 0.20
        text = " ".join(effect["description"] for effect in _P_ENTRY["effects"])
        assert "40% AD" in text
        assert "20% AP" in text

        conversion = _conversion(procs=1)
        primary_only = _PRIMARY_TOTAL_AD_RATIO * _AD + _PRIMARY_AP_RATIO * _AP
        assert conversion["bonus_raw"] == pytest.approx(primary_only - _AD)

    def test_binary_secondary_coefficients_match_the_withheld_constants(self):
        record = _spell_record("SylasPassive")
        parts = record["mSpellCalculations"]["PassiveAoEDamage"]["mFormulaParts"]
        assert len(parts) == 2
        assert parts[0]["mStat"] == 2
        assert parts[0]["mCoefficient"] == pytest.approx(
            _SECONDARY_TOTAL_AD_RATIO, abs=1e-6
        )
        assert parts[1]["mCoefficient"] == pytest.approx(_SECONDARY_AP_RATIO, abs=1e-6)

    def test_monster_multiplier_is_sourced_and_not_applied(self):
        record = _spell_record("SylasPassive")
        assert game_binary.data_value(record, "MonsterDamageMulti")[0] == pytest.approx(
            1.15
        )
        text = " ".join(effect["description"] for effect in _P_ENTRY["effects"])
        assert "115% damage to monsters" in text
        # No monster class exists to bind it to; the emitted figure is the
        # plain champion one.
        assert _conversion(procs=1)["bonus_raw"] == pytest.approx(93.60)

    def test_secondary_minion_execute_is_sourced_and_not_applied(self):
        record = _spell_record("SylasPassive")
        assert game_binary.data_value(record, "CheatingThreshold")[0] == pytest.approx(
            25.0
        )
        text = " ".join(effect["description"] for effect in _P_ENTRY["effects"])
        assert "executes minions that are secondary targets" in text

    def test_bonus_attack_speed_is_sourced_and_emits_no_stat_buff(self):
        record = _spell_record("SylasPassive")
        assert game_binary.data_value(record, "PassiveAttackSpeed")[0] == pytest.approx(
            1.25
        )
        assert "125% bonus attack speed" in _P_ENTRY["effects"][1]["description"]

        _, abilities = _parse(procs=3)
        for entry in abilities.values():
            assert "stat_buff" not in entry

    def test_stack_duration_is_sourced_and_not_a_modeled_window(self):
        """The 4s refreshing window is why the count is user-set, not derived."""
        record = _spell_record("SylasPassive")
        assert game_binary.data_value(record, "PassiveDuration")[0] == pytest.approx(
            4.0
        )
        assert "for 4 seconds" in _P_ENTRY["effects"][0]["description"]

    def test_every_withholding_is_named_in_the_detail_string(self):
        _, abilities = _parse(procs=1)
        detail = abilities["passive"]["detail"]
        assert "REPLACE" in detail
        for fragment in ("40% AD", "175%", "monster", "125% bonus attack speed"):
            assert fragment in detail


class TestNonstandardCritCannotBeExpressed:
    """The wiki records a (175% + 30%) crit; this kernel has no such dial."""

    def test_the_nonstandard_crit_is_sourced(self):
        text = " ".join(effect["description"] for effect in _P_ENTRY["effects"])
        assert "(175% + 30%) damage" in text
        assert "incorrectly critically strikes" in _P_ENTRY["notes"]

    def test_crit_effectiveness_scales_probability_not_the_multiplier(self):
        """Measured off the dataclass contract, not quoted from a docstring.

        ``crit_effectiveness`` is documented as "the part crits at this
        effectiveness" and the evaluator turns it into
        ``crit_probability = min(1.0, eff * state.crit_chance)``. There is no
        field on a DamagePart that overrides the crit MULTIPLIER, so a 175%
        crit is not expressible.
        """
        part = DamagePart("magic", 100.0)
        assert part.crit_effectiveness == 0.0
        fields = set(DamagePart.__dataclass_fields__)
        assert "crit_effectiveness" in fields
        assert "crit_multiplier" not in fields
        assert not any("multiplier" in name for name in fields)

    def test_conversion_payload_declares_no_crit_override(self):
        """Fail-closed: the divergence is documented, not approximated."""
        conversion = _conversion(procs=1)
        assert set(conversion) == {"name", "count", "bonus_raw", "damage_type"}

    def test_readings_coincide_at_zero_crit_chance(self):
        """An ordinary Sylas build has no crit, so nothing is lost today.

        The fight above carries no crit chance, which is why the module's
        205.60 is exactly right rather than merely close — the divergence
        only opens on a crit build, and it is recorded in ASSUMPTIONS.
        """
        result = _fight(procs=1)
        assert _converted_damage(result) == pytest.approx(
            _PRIMARY_TOTAL_AD_RATIO * _AD + _PRIMARY_AP_RATIO * _AP, abs=0.01
        )


# ---------------------------------------------------------------------------
# R — a kernel gap, not an evidence gap
# ---------------------------------------------------------------------------


class TestHijackIsAKernelGapNotAnEvidenceGap:
    def test_r_stays_out_of_scope(self):
        assert MODULE_COVERAGE["R"] == "out_of_scope"

    def test_r_is_not_labelled_no_damage(self):
        """The Olaf-R rule. Hijack's damage is another champion's ultimate,
        so ``no_damage`` would be a false claim rather than a conservative
        one."""
        assert MODULE_COVERAGE["R"] != "no_damage"

    def test_binary_r_record_has_no_damage_formula(self):
        record = _spell_record("SylasRAbility/SylasR")
        assert sorted(record["mSpellCalculations"]) == ["PerTargetCooldown"]

    def test_recast_is_where_the_damage_lives(self):
        descriptions = [effect["description"] for effect in _R_ENTRY["effects"]]
        assert any(
            "casts his hijacked ultimate ability at no cost" in text
            for text in descriptions
        )

    def test_the_ap_conversion_rule_is_sourced_but_has_no_channel(self):
        descriptions = " ".join(effect["description"] for effect in _R_ENTRY["effects"])
        assert "0.6% AP per 1% total AD" in descriptions
        assert "0.4% AP per 1% bonus AD" in descriptions

    def test_no_cross_champion_import_surface_exists(self):
        """Unknown attacker names fail closed, so no foreign R can be
        instantiated at a rank of Sylas' choosing."""
        with pytest.raises((KeyError, ValueError)):
            parse_champion_abilities(
                {"name": "NotAChampion", "abilities": {}},
                _LEVEL,
                0.0,
            )

    def test_r_emits_a_zero_damage_row_rather_than_an_invented_one(self):
        _, abilities = _parse(procs=0)
        assert abilities["R"]["total_raw"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Receipts
# ---------------------------------------------------------------------------


class TestModuleCoverageAndReceipts:
    def test_coverage_is_explicit_for_every_slot(self):
        assert MODULE_COVERAGE == {
            "P": "modeled",
            "Q": "modeled",
            "W": "modeled",
            "E": "modeled",
            "R": "out_of_scope",
        }

    def test_p_receipt_records_the_conversion_verdict(self):
        text = " ".join(ASSUMPTIONS)
        assert "CONVERSION" in text
        assert "not as bonus on-hit damage" in text
        assert "REPLACES one" in text

    def test_p_receipt_records_every_withholding(self):
        text = " ".join(ASSUMPTIONS)
        for fragment in (
            "secondary-target whirl",
            "175% + 30%",
            "115% monster multiplier",
            "125% bonus attack speed",
        ):
            assert fragment in text

    def test_r_receipt_records_the_named_kernel_gap(self):
        text = " ".join(ASSUMPTIONS)
        assert "out_of_scope, NOT no_damage" in text
        assert "cross-champion ultimate-import kernel" in text
        assert "PerTargetCooldown" in text
