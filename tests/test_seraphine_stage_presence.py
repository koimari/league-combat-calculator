"""Seraphine P (Stage Presence / Notes) and W (Surround Sound).

The roadmap slot session closes Seraphine's last two ``out_of_scope``
rows.

**P was mislabelled, not merely stale.** The packet called P
``no_damage``. Its third effect row carries a fully sourced on-hit
formula: while Notes are active Seraphine's next basic attack is
empowered to "fire all Notes at the target, with each one dealing
4 : 27.47 (based on level) (+ 4% AP) magic damage". The game binary
agrees term for term (``SeraphinePassive``: ``AutoDamage`` is a
``ByCharLevelInterpolationCalculationPart`` 4 -> 25 plus a
``StatByNamedDataValueCalculationPart`` on ``NoteAPRatio`` = 0.04), and
``TestNoteDamageIsBinaryCorroborated`` re-derives both terms from the
binary rather than trusting the module.

**The Note count is explicit state.** The engine does not simulate the
Note window (granted by ability casts, 6s duration, 4 per unit), so
``p_notes_fired`` defaults to 0. ``TestZeroNotesCostZero`` pins the same
phantom-proc contract Rammus' W and Rumble's P needed in this batch:
because consumers read ONLY ``parts``, a ``count=max(notes, 1)`` floor
would price one full Note at the default.

Unlike the Rumble/Rammus rails, the ceiling of 4 is a **sourced game
value** (``MaxNotes``), not a sanity rail — ``TestNoteCapIsSourced``
pins it against both the cached prose and the binary.

**Two sourced riders are deliberately withheld**, and both withholdings
are pinned so a later worker cannot quietly "finish" them:

* ally Notes (``AllyNoteDamagePercent`` 0.25) — they require allied
  champions in range at Seraphine's cast times, structurally outside the
  1v1 damage surface (the Rakan-E / Kai'Sa-R ally-coupling boundary);
* W's bonus movement speed, an additive PERCENT that the flat-scalar
  ``stat_buff`` channel would push past
  ``stats.apply_movement_speed_soft_caps`` (the Naafiri-W boundary).

**W stays scanner-priced.** Being shield-only, W cannot carry
``attach_self_shield`` (that payload rides damage-event rows), so it is
derived by the ally-support scanner — the Ekko-W / Rumble-W precedent.
The scanner authors both rows: the shield at scope
``self_and_all_teammates`` with ``target_self`` true, and the
shield-gated missing-health pulse heal.
"""

import copy
import json
from pathlib import Path

import pytest

from src.calculator.champions import (
    get_champion_module_contract,
    get_champion_options_meta,
    parse_champion_abilities,
)
from src.calculator.champions.seraphine import (
    ASSUMPTIONS,
    _MAX_NOTES,
)
from src.calculator.data_fetcher import get_champion
from src.calculator.stats import calculate_total_stats
from src.calculator.support_effects import derive_ally_effects
from tests import game_binary

_SERAPHINE = get_champion("Seraphine")
_WIKI = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))["Seraphine"]

# ``data/bin/characters/`` is a gitignored local game-file cache, so CI has
# no copy of it. The ci_evidence_parity tripwire requires every reference to
# be either force-tracked or absence-guarded; this is the guard idiom (the
# test_quinn_p_crit.py precedent). Locally the corroboration really runs.
_BIN_PATH = Path("data/bin/characters/seraphine.bin.json")
_BIN = json.loads(_BIN_PATH.read_text(encoding="utf-8")) if _BIN_PATH.exists() else None


def _passive_record() -> dict:
    """The binary ``SeraphinePassive`` spell record, or skip when absent."""
    if _BIN is None:
        pytest.skip("local Seraphine game-file evidence is unavailable")
    return next(
        value["mSpell"]
        for key, value in _BIN.items()
        if key.endswith("SeraphinePassiveAbility/SeraphinePassive")
        and isinstance(value, dict)
        and "mSpell" in value
    )


_P_EFFECT = _WIKI["abilities"]["P"][0]["effects"][2]
_HARMONY_EFFECT = _WIKI["abilities"]["P"][0]["effects"][1]

_TARGET = {
    "target_max_health": 2500.0,
    "target_current_health": 2500.0,
    "target_missing_health": 0.0,
}


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
    """Parse Seraphine at *level* with no items, mirroring the pipeline."""
    data = copy.deepcopy(_SERAPHINE)
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


def _notes(level: int, count: int, **kwargs):
    """The Stage Presence on-hit payload: per-Note damage and Notes fired.

    The empowered attack is a basic attack, so the row rides the on-hit
    channel with ``max_procs`` 1 — one empowered swing fires every Note it
    holds and the next has none.  A ``parts`` row on the ``passive`` slot
    could not reach a fight at all: ``passive`` is not an orderable cast
    (``pipeline.validate_cast_order_for_kit`` refuses it).  The sourced
    per-Note number and the Note count are unchanged; only where they live.
    """
    _, abilities = _parse(level, options={"p_notes": count}, **kwargs)
    on_hit = abilities["passive"].get("on_hit")
    if on_hit is None or not on_hit.get("max_procs"):
        return 0.0, 0
    return float(on_hit["damage_per_hit"]) / max(count, 1), count


# ---------------------------------------------------------------------------
# P — sourcing re-derived from the binary
# ---------------------------------------------------------------------------


class TestNoteDamageIsBinaryCorroborated:
    def test_cached_row_carries_exactly_two_terms(self):
        row = _leveling_row(_P_EFFECT, "Bonus Magic Damage")
        units = [modifier["units"][0] for modifier in row["modifiers"]]
        assert units == ["", "% AP"]

    def test_flat_term_is_a_per_level_array_not_a_rank_array(self):
        """Stage Presence is an innate: 20 entries, one per level."""
        row = _leveling_row(_P_EFFECT, "Bonus Magic Damage")
        values = row["modifiers"][0]["values"]
        assert len(values) == 20
        assert values[0] == pytest.approx(4.0)
        assert values[17] == pytest.approx(25.0)
        assert values[19] == pytest.approx(27.47)

    def test_binary_ladder_endpoints_match_the_wiki(self):
        """Binary interpolates 4 -> 25 over levels 1..18; wiki agrees."""
        parts = _passive_record()["mSpellCalculations"]["AutoDamage"]["mFormulaParts"]
        ladder = next(
            part for part in parts if "ByCharLevel" in str(part.get("__type", ""))
        )
        assert ladder["mStartValue"] == pytest.approx(4.0)
        assert ladder["mEndValue"] == pytest.approx(25.0)

    def test_binary_ap_ratio_matches_the_wiki(self):
        row = _leveling_row(_P_EFFECT, "Bonus Magic Damage")
        assert row["modifiers"][1]["values"][0] == pytest.approx(4.0)
        values = game_binary.data_value(_passive_record(), "NoteAPRatio")
        assert all(value == pytest.approx(0.04, abs=1e-6) for value in values)

    def test_binary_ap_ratio_is_wired_into_the_damage_formula(self):
        """The ratio must be REFERENCED, not merely present as a DataValue.

        The Rammus-P lesson: that record's ``BaseDamage`` DataValue exists
        but is absent from the formula, so trusting DataValues alone
        invents terms.
        """
        parts = _passive_record()["mSpellCalculations"]["AutoDamage"]["mFormulaParts"]
        referenced = {part.get("mDataValue") for part in parts}
        assert "NoteAPRatio" in referenced

    def test_formula_has_no_third_term(self):
        """Two parts only — no flat/health rider may be invented."""
        parts = _passive_record()["mSpellCalculations"]["AutoDamage"]["mFormulaParts"]
        assert len(parts) == 2


class TestNoteDamage:
    @pytest.mark.parametrize(
        ("level", "flat"),
        [(1, 4.0), (11, 16.35), (18, 25.0), (20, 27.47)],
    )
    def test_per_note_damage_is_the_sum_of_both_terms(self, level, flat):
        per_note, notes = _notes(level, 1, stats_override={"ability_power": 200.0})
        expected = flat + 0.04 * 200.0
        assert notes == 1
        assert per_note == pytest.approx(expected)

    def test_level_twenty_value_is_hand_derived(self):
        per_note, _ = _notes(20, 1, stats_override={"ability_power": 100.0})
        # 27.47 + 4.00 (4% of 100 AP)
        assert per_note == pytest.approx(31.47)

    def test_ap_term_is_actually_present(self):
        low, _ = _notes(18, 1, stats_override={"ability_power": 0.0})
        high, _ = _notes(18, 1, stats_override={"ability_power": 500.0})
        assert high - low == pytest.approx(0.04 * 500.0)

    @pytest.mark.parametrize("notes", [1, 2, 3, 4])
    def test_total_scales_linearly_in_the_note_count(self, notes):
        one_per_note, _ = _notes(18, 1)
        many_per_note, fired = _notes(18, notes)
        assert fired == notes
        assert many_per_note * fired == pytest.approx(one_per_note * notes)

    def test_note_damage_is_magic(self):
        _, abilities = _parse(18, options={"p_notes": 2})
        assert abilities["passive"]["damage_type"] == "magic"
        assert abilities["passive"]["on_hit"]["damage_type"] == "magic"

    def test_negative_note_counts_floor_at_zero(self):
        assert _notes(18, -3) == (0.0, 0)


class TestNoteCapIsSourced:
    """The ceiling of 4 is a game value, not a sanity rail."""

    def test_module_cap_matches_the_cached_prose(self):
        assert _MAX_NOTES == 4
        assert "stacks up to 4 times on each unit" in _HARMONY_EFFECT["description"]

    def test_module_cap_matches_the_binary(self):
        values = game_binary.data_value(_passive_record(), "MaxNotes")
        assert all(value == pytest.approx(4.0) for value in values)

    def test_note_count_is_clamped_to_the_cap(self):
        _, capped = _parse(18, options={"p_notes": 10_000})
        _, rail = _parse(18, options={"p_notes": _MAX_NOTES})
        assert capped["passive"]["on_hit"] == rail["passive"]["on_hit"]


class TestZeroNotesCostZero:
    """No Note must cost nothing - the Rammus-W phantom pin.

    The default is the sourced cap rather than 0, and that is a different
    claim from Rumble's ``overheat_autos``: every ability cast grants a
    Note, so four Notes are what the fight's OWN default rotation
    (Q/W/E/R) produces, not caster state the engine never simulates.
    ``max_procs`` still holds it to the single empowered swing.
    """

    def test_zero_notes_price_no_rider_at_all(self):
        _, abilities = _parse(18, options={"p_notes": 0})
        assert abilities["passive"]["total_raw"] == pytest.approx(0.0)
        assert abilities["passive"]["parts"] == ()
        assert not abilities["passive"]["on_hit"].get("max_procs")

    def test_zero_and_one_note_are_not_identical(self):
        assert _notes(18, 0) == (0.0, 0)
        per_note, fired = _notes(18, 1)
        assert per_note > 0.0 and fired == 1

    def test_option_is_registered_with_the_sourced_cap_as_its_default(self):
        meta = get_champion_options_meta("Seraphine")
        option = next(entry for entry in meta["options"] if entry["key"] == "p_notes")
        assert option["default"] == _MAX_NOTES
        assert option["min"] == 0
        assert option["max"] == _MAX_NOTES


# ---------------------------------------------------------------------------
# The deliberate withholdings
# ---------------------------------------------------------------------------


class TestAllyNotesAreWithheld:
    def test_cached_row_states_the_ally_reduction(self):
        assert "reduced by 75% for Notes from allies" in _P_EFFECT["description"]

    def test_binary_ally_percent_exists_but_is_not_priced(self):
        values = game_binary.data_value(_passive_record(), "AllyNoteDamagePercent")
        assert all(value == pytest.approx(0.25) for value in values)
        # Four self Notes at level 18 / 200 AP: 4 x (25 + 8). An ally Note
        # would add a fifth quarter-strength hit; the total must be exactly
        # the four self Notes.
        per_note, fired = _notes(18, 4, stats_override={"ability_power": 200.0})
        assert per_note * fired == pytest.approx(132.0)

    def test_withholding_is_documented(self):
        assumption = next(a for a in ASSUMPTIONS if "Stage Presence" in a)
        assert "Notes from allies" in assumption
        assert "1v1" in assumption


class TestEmpoweredAttackRidersAreWithheld:
    def test_cached_row_states_the_range_and_windup_riders(self):
        description = _P_EFFECT["description"]
        assert "uncancellable windup" in description
        assert "25 bonus attack range per Note" in description

    def test_no_stat_buff_is_emitted(self):
        _, abilities = _parse(18, options={"p_notes": 4})
        assert "stat_buff" not in abilities["passive"]

    def test_withholding_is_documented(self):
        assumption = next(a for a in ASSUMPTIONS if "Stage Presence" in a)
        assert "bonus attack range" in assumption


# ---------------------------------------------------------------------------
# W — the scanner-priced shield
# ---------------------------------------------------------------------------


def _ally_effects(
    level: int, stats: dict, *, rank: int = 5, options: dict | None = None
):
    return derive_ally_effects(
        get_champion("Seraphine"),
        level,
        dict(stats),
        [{"slot": "W", "time": 1.0}],
        {"W": rank},
        champion_options=options,
    )


class TestSurroundSound:
    def test_shield_is_the_two_sourced_terms(self):
        shield = next(
            effect
            for effect in _ally_effects(18, {"ability_power": 200.0, "health": 2000.0})
            if effect["kind"] == "shield"
        )
        # 140 (rank 5) + 40 (20% of 200 AP)
        assert shield["amount"] == pytest.approx(180.0)
        assert shield["duration"] == pytest.approx(2.5)

    def test_shield_covers_the_caster_and_the_team(self):
        shield = next(
            effect
            for effect in _ally_effects(18, {"ability_power": 0.0, "health": 2000.0})
            if effect["kind"] == "shield"
        )
        assert shield["target_self"] is True
        assert shield["target_scope"] == "self_and_all_teammates"

    @pytest.mark.parametrize(
        ("rank", "flat"), [(1, 60.0), (2, 80.0), (3, 100.0), (4, 120.0), (5, 140.0)]
    )
    def test_shield_flat_term_tracks_rank(self, rank, flat):
        shield = next(
            effect
            for effect in _ally_effects(
                18, {"ability_power": 0.0, "health": 2000.0}, rank=rank
            )
            if effect["kind"] == "shield"
        )
        assert shield["amount"] == pytest.approx(flat)

    def test_shield_does_not_scale_with_caster_health(self):
        """Unlike Rumble's W, Surround Sound has no max-health term."""
        low = next(
            effect
            for effect in _ally_effects(18, {"ability_power": 0.0, "health": 2000.0})
            if effect["kind"] == "shield"
        )
        high = next(
            effect
            for effect in _ally_effects(18, {"ability_power": 0.0, "health": 6000.0})
            if effect["kind"] == "shield"
        )
        assert high["amount"] == pytest.approx(low["amount"])

    def test_the_gated_pulse_heal_is_refused_not_published_at_zero(self):
        """The scanner withholds the pulse rather than pricing it.

        Its amount is a share of each RECIPIENT's live missing health, which
        the scanner cannot price per recipient, so it publishes no row at
        all - and w_already_shielded, which exists only to drop the
        caster's shield gate, must not resurrect a zero-amount one.
        tests/test_e8_support.py pins the same refusal on the roster
        path.
        """
        for options in (None, {"w_already_shielded": True}):
            effects = _ally_effects(
                18, {"ability_power": 0.0, "health": 2000.0}, options=options
            )
            assert {effect["kind"] for effect in effects} == {"shield"}

    def test_w_carries_no_damage_row(self):
        _, abilities = _parse(18, ranks={"Q": 5, "W": 5, "E": 5, "R": 3})
        assert abilities["W"]["total_raw"] == pytest.approx(0.0)
        assert abilities["W"]["parts"] == ()


class TestSurroundSoundMovementSpeedIsWithheld:
    def test_cached_row_states_both_movement_terms(self):
        description = _WIKI["abilities"]["W"][0]["effects"][0]["description"]
        assert "20% (+ 2% per 100 AP) decaying bonus movement speed" in description
        assert "8% (+ 0.8% per 100 AP) bonus movement speed" in description

    def test_no_move_speed_buff_is_emitted(self):
        _, abilities = _parse(18, ranks={"Q": 5, "W": 5, "E": 5, "R": 3})
        assert "stat_buff" not in abilities["W"]

    def test_withholding_names_the_soft_cap_channel(self):
        # Two assumptions mention Surround Sound (the older heal-pulse note
        # and this session's scanner note); select the scanner one.
        assumption = next(
            a
            for a in ASSUMPTIONS
            if "Surround Sound" in a and "ally-support scanner" in a
        )
        assert "move_speed" in assumption
        assert "soft_caps" in assumption
        assert "NOT modeled" in assumption


# ---------------------------------------------------------------------------
# Coverage contract
# ---------------------------------------------------------------------------


def test_module_coverage_has_no_out_of_scope_slots_left():
    """Read off the contract, not a module constant.

    Every slot is emitted and priced, so ``module_contract.default_coverage``
    already derives exactly this map; the contract refuses a module-level
    ``MODULE_COVERAGE`` that restates what SLOTS derive, so the assertion
    reads the registry's answer instead.
    """
    assert get_champion_module_contract("Seraphine").coverage == {
        "P": "modeled",
        "Q": "modeled",
        "W": "modeled",
        "E": "modeled",
        "R": "modeled",
    }
