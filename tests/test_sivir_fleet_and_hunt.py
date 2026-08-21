"""Sivir P (Fleet of Foot) and R (On the Hunt) — two slots, two verdicts.

The roadmap slot session closes Sivir's last two ``out_of_scope`` rows,
and they close **differently**. That asymmetry is the point of pinning
them in one module: "no damage row" and "nothing left to model" are not
the same claim, and the batch keeps mixing them up.

**P closes as ``no_damage``.** Fleet of Foot's single cached effect is a
self movement-speed grant — "basic attacks on-attack and ability hits
against enemy champions grant her 55 : 75 (based on level) bonus movement
speed decaying over 1.5 seconds" — with no enemy-damage clause anywhere
in the entry. The binary agrees rather than merely failing to disagree:
``SivirPassive``'s ``mSpellCalculations`` contains exactly one entry,
``FlatMS``, and no damage formula at all.
``TestFleetOfFootHasNoDamageAnywhere`` re-derives the movement ladder
from the binary's ``ByCharLevelBreakpoints`` part (55 at level 1, +5 at
each of 6/11/16/18 = 75) so the "it is only movement speed" claim is
measured, not asserted. This is the Vayne-P / Kalista-P / Pyke-P shape:
sourced, non-damaging, therefore ``no_damage``.

**The movement grant is deliberately not a ``stat_buff``**, and the
reason is arithmetic rather than editorial.
``_apply_stat_buff_ultimates`` adds the buff straight onto
``champion_stats["move_speed"]``, which has ALREADY been through
``stats.apply_movement_speed_soft_caps``. Above 415 raw movement speed
the real grant is worth 0.8x what the channel would credit (0.5x above
490), and the one live consumer of that stat is ``item_effects``'
``adaptive_force_per_total_move_speed`` (Swiftmarch) — so an
over-credited movement number turns into DAMAGE.
``TestMovementSpeedIsNotStatBuffed`` measures the 0.8x/0.5x gap off the
real soft-cap function so the argument cannot rot into folklore.

**R stays ``out_of_scope``, and that is not laziness.** The Olaf-R rule:
a real, sourced, unmodeled mechanic is ``out_of_scope``, never
``no_damage``. The binary confirms there is no damage to miss
(``SivirR``'s ``mSpellCalculations`` is empty), but both sourced combat
effects hit a *named* kernel gap, and each gap is pinned by measuring
the kernel rather than by quoting the docstring:

* the rank-scaled bonus movement speed is an additive PERCENT, and
  ``calculate_total_stats`` exposes only the final soft-capped
  ``move_speed`` scalar — ``TestOnTheHuntKernelGaps`` asserts no
  ``move_speed_flat`` / ``move_speed_percent`` pair exists to compose
  against, so a decomposition would have to be invented;
* ``on_attack_cooldown_refund`` is a field of
  ``item_effects.CooldownProcEffect`` (the item-proc scheduler's
  surface), so there is no ability-cooldown-refund channel a champion
  module could author into.

**One SOURCE CONFLICT is recorded, not used.** ``SivirR`` carries
``HuntAttackSpeed`` (5%/6%/7% at ranks 1-3) that the cached wiki text
never mentions. ``TestHuntAttackSpeedIsAnUnusedSourceConflict`` pins
both halves — the binary row exists, the wiki text is silent, and no
attack-speed buff is emitted — so a later worker who finds the binary
row cannot quietly "fix" the module with an uncorroborated steroid.
"""

import copy
import json
from pathlib import Path

import pytest

from src.calculator.champions import parse_champion_abilities
from src.calculator.champions.sivir import ASSUMPTIONS, MODULE_COVERAGE
from src.calculator.data_fetcher import get_champion
from src.calculator.item_effects import (
    CooldownProcEffect,
    required_effect_value,
    swiftmarch_adaptive_force,
)
from src.calculator.stats import apply_movement_speed_soft_caps, calculate_total_stats

_SIVIR = get_champion("Sivir")
_WIKI = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))["Sivir"]

# ``data/bin/characters/`` is a gitignored local game-file cache, so CI has
# no copy of it. The ci_evidence_parity tripwire requires every reference to
# be either force-tracked or absence-guarded; this is the guard idiom (the
# test_quinn_p_crit.py precedent). Locally the corroboration really runs.
_BIN_PATH = Path("data/bin/characters/sivir.bin.json")
_BIN = json.loads(_BIN_PATH.read_text(encoding="utf-8")) if _BIN_PATH.exists() else None


def _spell_record(suffix: str) -> dict:
    """One binary ``mSpell`` record by object-path suffix, or skip."""
    if _BIN is None:
        pytest.skip("local Sivir game-file evidence is unavailable")
    return next(
        value["mSpell"]
        for key, value in _BIN.items()
        if key.endswith(suffix) and isinstance(value, dict) and "mSpell" in value
    )


def _data_value(record: dict, name: str) -> list[float]:
    """One named ``DataValues`` row out of a binary spell record."""
    for entry in record.get("DataValues", []):
        if entry.get("name") == name:
            return list(entry.get("values") or [])
    raise AssertionError(f"binary record has no DataValues row {name!r}")


_P_EFFECT = _WIKI["abilities"]["P"][0]["effects"][0]
_R_ENTRY = _WIKI["abilities"]["R"][0]

_TARGET = {
    "armor": 100.0,
    "magic_resist": 50.0,
    "magic_resistance": 50.0,
    "target_max_health": 2500.0,
    "target_current_health": 2500.0,
    "target_missing_health": 0.0,
}


def _parse(level: int = 18, *, ranks: dict | None = None, stats_override=None):
    """Parse Sivir at *level* with no items, mirroring the pipeline."""
    data = copy.deepcopy(_SIVIR)
    champion_stats = dict(calculate_total_stats(data, level, []))
    if stats_override:
        champion_stats.update(stats_override)
    abilities = parse_champion_abilities(
        data,
        level,
        champion_stats["ability_power"],
        ability_ranks=ranks or {"Q": 5, "W": 5, "E": 5, "R": 3},
        champion_stats=champion_stats,
        target_stats=dict(_TARGET),
    )
    return champion_stats, abilities


# ---------------------------------------------------------------------------
# P — sourced, non-damaging, therefore no_damage
# ---------------------------------------------------------------------------


class TestFleetOfFootHasNoDamageAnywhere:
    def test_cached_entry_has_exactly_one_effect(self):
        assert len(_WIKI["abilities"]["P"][0]["effects"]) == 1

    def test_cached_description_never_says_damage(self):
        assert "damage" not in _P_EFFECT["description"].lower()

    def test_cached_description_is_a_movement_speed_grant(self):
        assert "bonus movement speed" in _P_EFFECT["description"]

    def test_cached_entry_declares_no_damage_type(self):
        assert _WIKI["abilities"]["P"][0]["damageType"] is None

    def test_no_leveling_row_is_a_damage_row(self):
        attributes = [row["attribute"] for row in _P_EFFECT["leveling"]]
        assert attributes == ["Per-Level Scaling"]

    def test_cached_movement_ladder_is_the_wiki_prose(self):
        values = _P_EFFECT["leveling"][0]["modifiers"][0]["values"]
        assert values == [55, 60, 65, 70, 75]

    def test_binary_passive_has_no_damage_calculation(self):
        record = _spell_record("SivirPassiveAbility/SivirPassive")
        assert list(record["mSpellCalculations"]) == ["FlatMS"]

    def test_binary_movement_ladder_reproduces_the_wiki(self):
        record = _spell_record("SivirPassiveAbility/SivirPassive")
        parts = record["mSpellCalculations"]["FlatMS"]["mFormulaParts"]
        assert len(parts) == 1
        assert parts[0]["__type"] == "ByCharLevelBreakpointsCalculationPart"
        speed = parts[0]["mLevel1Value"]
        assert speed == pytest.approx(55.0)
        # +5 at each of levels 6/11/16/18 walks 55 -> 75 by level 18,
        # which is exactly the cached [55, 60, 65, 70, 75] ladder.
        for breakpoint in parts[0]["mBreakpoints"]:
            if breakpoint["mLevel"] <= 18:
                speed += breakpoint["mAdditionalBonusAtThisLevel"]
        assert speed == pytest.approx(75.0)

    def test_binary_decay_window_matches_the_wiki_prose(self):
        record = _spell_record("SivirPassiveAbility/SivirPassive")
        assert _data_value(record, "HasteDuration")[1] == pytest.approx(1.5)
        assert "1.5 seconds" in _P_EFFECT["description"]

    def test_parser_emits_a_zero_damage_passive_row(self):
        _, abilities = _parse()
        assert abilities["passive"]["total_raw"] == pytest.approx(0.0)
        assert abilities["passive"]["parts"] == ()

    def test_passive_row_is_named_from_the_cache(self):
        _, abilities = _parse()
        assert abilities["passive"]["name"] == "Fleet of Foot"

    @pytest.mark.parametrize("level", [1, 6, 11, 16, 18, 20])
    def test_passive_prices_nothing_at_any_level(self, level):
        _, abilities = _parse(level)
        assert abilities["passive"]["total_raw"] == pytest.approx(0.0)

    def test_coverage_says_no_damage_not_out_of_scope(self):
        assert MODULE_COVERAGE["P"] == "no_damage"

    def test_classification_is_documented_with_the_binary_receipt(self):
        assumption = next(a for a in ASSUMPTIONS if "Fleet of Foot) has no" in a)
        assert "no_damage, not out_of_scope" in assumption
        assert "SivirPassive" in assumption


class TestMovementSpeedIsNotStatBuffed:
    """The channel would over-credit the grant, and movement becomes damage."""

    def test_passive_row_emits_no_stat_buff(self):
        _, abilities = _parse()
        assert "stat_buff" not in abilities["passive"]

    def test_no_slot_emits_a_move_speed_stat_buff(self):
        _, abilities = _parse()
        for entry in abilities.values():
            assert "move_speed" not in entry.get("stat_buff", {})

    def test_soft_cap_discounts_the_level_18_grant(self):
        # Sivir's level-18 grant is +75 raw. From a 400 raw base the
        # result crosses into the 0.8x band, so the DISPLAYED gain is 63,
        # not 75 — the stat_buff channel adds onto the already-capped
        # scalar and would credit the full 75.
        base = apply_movement_speed_soft_caps(400.0)
        buffed = apply_movement_speed_soft_caps(400.0 + 75.0)
        assert base == pytest.approx(400.0)
        assert buffed == pytest.approx(463.0)
        assert buffed - base == pytest.approx(63.0)
        assert buffed - base < 75.0

    def test_grant_is_worth_exactly_four_fifths_inside_the_415_band(self):
        base = apply_movement_speed_soft_caps(420.0)
        buffed = apply_movement_speed_soft_caps(470.0)
        assert buffed - base == pytest.approx(0.8 * 50.0)

    def test_grant_is_worth_exactly_half_above_490(self):
        base = apply_movement_speed_soft_caps(500.0)
        buffed = apply_movement_speed_soft_caps(575.0)
        assert buffed - base == pytest.approx(0.5 * 75.0)

    def test_the_over_credit_would_become_adaptive_force(self):
        # Naming the consumer is the whole reason the buff is withheld:
        # Swiftmarch converts TOTAL movement speed into adaptive force, so
        # the 12-point over-credit above is invented damage, not cosmetics.
        items = [{"name": "Swiftmarch"}]
        honest = swiftmarch_adaptive_force(items, total_move_speed=463.0)
        over_credited = swiftmarch_adaptive_force(items, total_move_speed=475.0)
        assert over_credited > honest
        assert over_credited - honest == pytest.approx(
            12.0
            * required_effect_value("Swiftmarch", "adaptive_force_per_total_move_speed")
        )

    def test_withholding_names_the_soft_cap_and_the_consumer(self):
        assumption = next(a for a in ASSUMPTIONS if "Fleet of Foot) has no" in a)
        assert "apply_movement_speed_soft_caps" in assumption
        assert "adaptive_force_per_total_move_speed" in assumption
        assert "NOT modeled as a stat_buff" in assumption


# ---------------------------------------------------------------------------
# R — real, sourced, unmodeled: out_of_scope, NOT no_damage
# ---------------------------------------------------------------------------


class TestOnTheHuntCarriesNoDamage:
    def test_binary_ultimate_has_no_damage_calculation(self):
        # The key is absent entirely, not merely empty: SivirR carries no
        # GameCalculation at all.
        record = _spell_record("SivirRAbility/SivirR")
        assert "mSpellCalculations" not in record

    def test_the_absence_is_meaningful_because_siblings_have_the_key(self):
        # Guards against reading a schema quirk as evidence: Sivir's
        # damaging and healing slots all carry mSpellCalculations.
        for suffix, expected in (
            ("SivirQAbility/SivirQ", "TotalDamage"),
            ("SivirWAbility/SivirW", "TotalMaxDamage"),
            ("SivirEAbility/SivirE", "TotalHeal"),
        ):
            record = _spell_record(suffix)
            assert expected in record["mSpellCalculations"]

    def test_cached_entry_declares_no_damage_type(self):
        assert _R_ENTRY["damageType"] is None

    def test_no_cached_effect_carries_a_damage_row(self):
        for effect in _R_ENTRY["effects"]:
            for row in effect.get("leveling", []):
                assert "damage" not in row["attribute"].lower()

    def test_parser_emits_a_zero_damage_ultimate_row(self):
        _, abilities = _parse()
        assert abilities["R"]["total_raw"] == pytest.approx(0.0)
        assert abilities["R"]["parts"] == ()


class TestOnTheHuntStaysOutOfScope:
    def test_coverage_is_out_of_scope_not_no_damage(self):
        assert MODULE_COVERAGE["R"] == "out_of_scope"

    def test_olaf_rule_is_stated_explicitly(self):
        assumption = next(a for a in ASSUMPTIONS if "On the Hunt) stays" in a)
        assert "out_of_scope, NOT no_damage" in assumption
        assert "Olaf-R rule" in assumption

    def test_both_sourced_effects_are_named_in_the_receipt(self):
        assumption = next(a for a in ASSUMPTIONS if "On the Hunt) stays" in a)
        assert "20/25/30%" in assumption
        assert "0.5 seconds" in assumption

    def test_binary_movement_ladder_matches_the_wiki_ranks(self):
        record = _spell_record("SivirRAbility/SivirR")
        # DataValues arrays are rank-indexed with an unused slot 0.
        assert _data_value(record, "MaxMS")[1:4] == pytest.approx([0.20, 0.25, 0.30])

    def test_binary_cooldown_refund_matches_the_wiki(self):
        record = _spell_record("SivirRAbility/SivirR")
        assert _data_value(record, "AttackCooldownRefund")[1] == pytest.approx(0.5)
        assert "0.5 seconds" in " ".join(
            effect["description"] for effect in _R_ENTRY["effects"]
        )


class TestOnTheHuntKernelGaps:
    """Both blockers are measured against the kernel, not quoted."""

    def test_no_move_speed_decomposition_exists_to_compose_against(self):
        stats = calculate_total_stats(copy.deepcopy(_SIVIR), 18, [])
        assert "move_speed" in stats
        assert "move_speed_flat" not in stats
        assert "move_speed_percent" not in stats

    def test_cooldown_refund_channel_is_item_proc_only(self):
        import dataclasses

        fields = {f.name for f in dataclasses.fields(CooldownProcEffect)}
        assert "on_attack_cooldown_refund" in fields

    def test_no_ability_slot_emits_a_cooldown_refund_key(self):
        _, abilities = _parse()
        for entry in abilities.values():
            assert "on_attack_cooldown_refund" not in entry

    def test_receipt_names_both_kernel_gaps(self):
        assumption = next(a for a in ASSUMPTIONS if "On the Hunt) stays" in a)
        assert "move_speed_flat" in assumption
        assert "CooldownProcEffect" in assumption


class TestHuntAttackSpeedIsAnUnusedSourceConflict:
    def test_binary_carries_the_attack_speed_row(self):
        record = _spell_record("SivirRAbility/SivirR")
        assert _data_value(record, "HuntAttackSpeed")[1:4] == pytest.approx(
            [0.05, 0.06, 0.07]
        )

    def test_cached_wiki_text_never_mentions_attack_speed(self):
        text = " ".join(effect["description"] for effect in _R_ENTRY["effects"]).lower()
        assert "attack speed" not in text

    def test_no_attack_speed_buff_is_emitted(self):
        _, abilities = _parse()
        for entry in abilities.values():
            buff = entry.get("stat_buff", {})
            assert "attack_speed" not in buff
            assert "bonus_attack_speed" not in buff

    def test_conflict_is_recorded_rather_than_used(self):
        assumption = next(a for a in ASSUMPTIONS if "On the Hunt) stays" in a)
        assert "SOURCE CONFLICT" in assumption
        assert "HuntAttackSpeed" in assumption
        assert "fail-closed" in assumption


# ---------------------------------------------------------------------------
# The modeled slots must not have moved
# ---------------------------------------------------------------------------


class TestModeledSlotsAreUnchanged:
    def test_q_still_prices_the_two_way_pass(self):
        _, abilities = _parse()
        parts = abilities["Q"]["parts"]
        assert len(parts) == 1
        assert parts[0].count == 2

    def test_e_is_a_shield_row_not_a_damage_row(self):
        _, abilities = _parse()
        assert abilities["E"]["total_raw"] == pytest.approx(0.0)
        assert abilities["E"]["self_state_events"][0]["kind"] == "spell_shield"

    def test_w_still_prices_damage(self):
        _, abilities = _parse()
        assert abilities["W"]["total_raw"] > 0.0


# ---------------------------------------------------------------------------
# Coverage contract
# ---------------------------------------------------------------------------


def test_module_coverage_is_the_explicit_two_verdict_dict():
    assert MODULE_COVERAGE == {
        "P": "no_damage",
        "Q": "modeled",
        "W": "modeled",
        "E": "modeled",
        "R": "out_of_scope",
    }
