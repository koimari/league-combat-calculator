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

**The heat axis prices the rest of the same sentence.**
``overheat_windows`` declares how many times the mech reaches the cached
Heat ceiling, and that one number buys BOTH remaining rows together: the
50% : 142.54% bonus attack speed and the self-silence stated beside it
("disabling his abilities as his Heat decays back down to 0 over 4
seconds"). ``TestHeatAxisReadsTheCache`` pins every constant to cached
prose — the 150 ceiling, the 20 per cast, the 4-second window — and
``TestOverheatWindowPricesBothHalves`` pins the pairing, because the
upside arriving without its cost is the exact way to overstate this
champion.

**One sourced row is still deliberately withheld:** the "Bonus Damage"
row (65 : 163.32 by level), which is not a damage source at all. Read in
context it is the CAP on the %max-health term, "capped at ... against
monsters". ``TestBonusDamageRowIsAMonsterCap`` pins that reading off the
cached description, because the attribute name alone reads exactly like a
damage row and is the obvious way to get this champion wrong.

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
``_SIMPLE_UNITS``, but only for rows it classifies as DAMAGE
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
import math
from pathlib import Path

import pytest

from src.calculator.champions import (
    get_champion_module_contract,
    get_champion_options_meta,
    parse_champion_abilities,
)
from src.calculator.champions.rumble import (
    _MAX_OVERHEAT_AUTOS,
    _MAX_OVERHEAT_WINDOWS,
    ASSUMPTIONS,
    _heat_mechanics,
)
from src.calculator.champions.scaling import (
    _SIMPLE_UNITS,
    resolve_scaling,
)
from src.calculator.data_fetcher import get_champion
from src.calculator.stats import calculate_total_stats
from src.calculator.support_effects import derive_ally_effects
from tests import game_binary

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

_P_ABILITY = _WIKI["abilities"]["P"][0]
_P_EFFECT = _P_ABILITY["effects"][2]
_ALIAS = "% of maximum health"


class _AbilityCtx:
    """The one thing ``_heat_mechanics`` asks of a ``SlotCtx``.

    Reading the heat constants needs no stats, target or options, so the
    reader is exercised against the cache directly — which is what lets a
    doctored cache prove the fail-closed branches.
    """

    def __init__(self, data: dict):
        self._abilities = data["abilities"]

    def ability(self, slot: str):
        entries = self._abilities.get(slot)
        return entries[0] if entries else None


def _heat_ctx(data: dict | None = None) -> _AbilityCtx:
    return _AbilityCtx(_RUMBLE if data is None else data)


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


def _rider(level: int, autos: int, **kwargs):
    """The Overheated on-hit payload, and what the declared swings cost.

    Batch K priced P as a ``parts`` row on the ``passive`` slot. That row
    can never reach a fight: ``passive`` is not an orderable cast
    (``pipeline.validate_cast_order_for_kit`` refuses it), so the merged
    module carries the same fail-closed count on the on-hit channel the
    game actually uses, bounded by ``max_procs``. The per-swing number and
    the count are unchanged; only where they live moved.
    """
    # One window is declared throughout: empowered swings with nowhere to
    # land are a refused contradiction, so the damage half is only ever
    # asked about inside a window (``TestImpossibleHeatStatesAreRefused``).
    _, abilities = _parse(
        level,
        options={"overheat_autos": autos, "overheat_windows": 1},
        **kwargs,
    )
    entry = abilities["passive"]
    on_hit = entry.get("on_hit")
    if on_hit is None:
        return 0.0, 0
    return float(on_hit["damage_per_hit"]), int(on_hit["max_procs"])


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
        values = game_binary.data_value(_heat_record(), "OverheatPercBonusDamage")
        assert all(value == pytest.approx(0.04, abs=1e-6) for value in values)

    def test_binary_base_ladder_matches_the_wiki_endpoints(self):
        """Wiki L18 == binary's last authored ByCharLevel point (40)."""
        parts = _heat_record()["mSpellCalculations"]["TotalBaseDamage"]["mFormulaParts"]
        ladders = [
            part for part in parts if "ByCharLevel" in str(part.get("__type", ""))
        ]
        assert ladders, "TotalBaseDamage has no per-level ladder part"
        flat = json.dumps(ladders)
        assert "5.0" in flat
        assert "40.0" in flat


class TestOverheatDamage:
    @pytest.mark.parametrize(
        ("level", "flat"),
        [(1, 5.0), (11, 25.59), (18, 40.0), (20, 44.12)],
    )
    def test_per_auto_damage_is_the_sum_of_the_three_terms(self, level, flat):
        per_swing, procs = _rider(level, 1, stats_override={"ability_power": 200.0})
        expected = flat + 0.25 * 200.0 + 0.04 * _TARGET_MAX_HEALTH
        assert procs == 1
        assert per_swing == pytest.approx(expected)

    def test_level_twenty_value_is_hand_derived(self):
        per_swing, _ = _rider(20, 1, stats_override={"ability_power": 200.0})
        # 44.12 + 50.00 (25% of 200 AP) + 100.00 (4% of 2500 max HP)
        assert per_swing == pytest.approx(194.12)

    def test_target_max_health_term_is_actually_present(self):
        """The term the alias bug class silently drops; measured directly.

        It resolves through ``_parse_compound_unit`` (the cached spelling
        is "% of THE target's maximum health"), a different code path from
        the ``_SIMPLE_UNITS`` alias repaired for W — so both need pinning.
        """
        low_per_swing, _ = _rider(20, 1)
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
            champion_options={"overheat_autos": 1, "overheat_windows": 1},
        )
        gain = doubled["passive"]["on_hit"]["damage_per_hit"] - low_per_swing
        assert gain == pytest.approx(0.04 * _TARGET_MAX_HEALTH)

    @pytest.mark.parametrize("autos", [1, 2, 5, 12])
    def test_total_scales_linearly_in_the_auto_count(self, autos):
        one_per_swing, _ = _rider(20, 1)
        many_per_swing, procs = _rider(20, autos)
        assert procs == autos
        assert many_per_swing * procs == pytest.approx(one_per_swing * autos)

    def test_auto_count_is_clamped_to_the_rail(self):
        capped = _rider(20, 10_000)
        rail = _rider(20, _MAX_OVERHEAT_AUTOS)
        assert capped == rail
        assert capped[1] == _MAX_OVERHEAT_AUTOS

    def test_negative_auto_counts_floor_at_zero(self):
        assert _rider(20, -5) == (0.0, 0)


class TestZeroAutosCostZero:
    """No empowered auto must cost nothing — the Rammus-W phantom pin."""

    def test_default_option_prices_no_overheat_damage(self):
        _, abilities = _parse(20)
        assert abilities["passive"]["total_raw"] == pytest.approx(0.0)
        assert sum(
            part.amount * part.count for part in abilities["passive"]["parts"]
        ) == pytest.approx(0.0)

    def test_zero_and_one_auto_are_not_identical(self):
        assert _rider(20, 0) == (0.0, 0)
        per_swing, procs = _rider(20, 1)
        assert per_swing > 0.0
        assert procs == 1

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
        per_swing, _ = _rider(20, 1, stats_override={"ability_power": 200.0})
        # 194.12 is the three sourced terms; the cap must not be a fourth.
        assert per_swing == pytest.approx(194.12)
        assert per_swing != pytest.approx(194.12 + level_twenty_cap)

    def test_withholding_is_documented(self):
        assumption = next(a for a in ASSUMPTIONS if "Junkyard Titan" in a)
        assert "monster-only cap" in assumption


class TestHeatAxisReadsTheCache:
    """CF17: every number the axis prices comes out of cached prose.

    The three constants a heat model needs are stated in sentences, not in
    leveling rows, so they are the easiest thing in this module to freeze
    as literals.  These pin them to the cache instead.
    """

    def test_the_cached_prose_states_all_three(self):
        innate = _P_ABILITY["effects"][0]["description"]
        assert "becomes Overheated while at 150 Heat" in innate
        assert "at or above 50 Heat" in innate  # Danger Zone, still unpriced
        assert "decays back down to 0 over 4 seconds" in _P_EFFECT["description"]
        for slot in ("Q", "W", "E"):
            ability = _RUMBLE["abilities"][slot][0]
            assert "generates 20 Heat" in ability["effects"][0]["description"]

    def test_the_module_reads_them_rather_than_declaring_them(self):
        ceiling, per_cast, window = _heat_mechanics(_heat_ctx())
        assert (ceiling, per_cast, window) == (150.0, 20.0, 4.0)

    def test_the_casts_per_window_are_derived_not_stated(self):
        """8 casts is arithmetic on two cached numbers, never a constant."""
        ceiling, per_cast, _ = _heat_mechanics(_heat_ctx())
        assert math.ceil(ceiling / per_cast) == 8
        _, abilities = _parse(20, options={"overheat_windows": 1})
        assert "= 8 casts each" in abilities["passive"]["detail"]

    def test_a_cache_that_stops_stating_the_ceiling_raises(self):
        """Rule 5's fail-closed shape: no literal wins when prose moves."""
        broken = copy.deepcopy(_RUMBLE)
        broken["abilities"]["P"][0]["effects"][0]["description"] = "Innate: heat."
        with pytest.raises(ValueError, match="Overheat ceiling"):
            _heat_mechanics(_heat_ctx(broken))

    def test_a_cache_whose_slots_disagree_on_heat_per_cast_raises(self):
        broken = copy.deepcopy(_RUMBLE)
        effect = broken["abilities"]["W"][0]["effects"][0]
        effect["description"] = effect["description"].replace(
            "generates 20 Heat", "generates 30 Heat"
        )
        with pytest.raises(ValueError, match="disagree on Heat per cast"):
            _heat_mechanics(_heat_ctx(broken))


class TestOverheatWindowPricesBothHalves:
    """The AS bonus and the self-silence are one purchase, never one alone.

    CF17's blocker was never the lockout mechanism — it was that Overheat
    has no sourced start INSTANT.  The axis answers the question the model
    can actually source (how much of the fight is spent Overheated) and
    declines the one it cannot (where the span sits), so the upside can
    never arrive without its cost.
    """

    def test_cached_row_exists(self):
        row = _leveling_row(_P_EFFECT, "Per-Level Scaling")
        assert row["modifiers"][0]["values"][0] == pytest.approx(50.0)
        assert row["modifiers"][0]["values"][19] == pytest.approx(142.54)

    def test_zero_windows_emit_neither_half(self):
        """A payload present at magnitude zero still reads as priced."""
        _, abilities = _parse(20)
        passive = abilities["passive"]
        assert "stat_buff" not in passive
        assert "self_cast_lockout_seconds" not in passive
        assert "on_hit" not in passive

    def test_one_window_emits_both_halves_together(self):
        _, abilities = _parse(20, options={"overheat_windows": 1})
        passive = abilities["passive"]
        # Level 20 is the last entry of the cached per-level array.
        assert passive["stat_buff"] == {"bonus_attack_speed": pytest.approx(142.54)}
        assert passive["self_cast_lockout_seconds"] == pytest.approx(4.0)

    def test_the_lockout_scales_with_the_declared_window_count(self):
        for windows in (1, 2, 3):
            _, abilities = _parse(20, options={"overheat_windows": windows})
            assert abilities["passive"]["self_cast_lockout_seconds"] == pytest.approx(
                4.0 * windows
            )

    def test_the_declared_count_is_railed(self):
        _, abilities = _parse(20, options={"overheat_windows": 99})
        assert abilities["passive"]["self_cast_lockout_seconds"] == pytest.approx(
            4.0 * _MAX_OVERHEAT_WINDOWS
        )
        _, floored = _parse(20, options={"overheat_windows": -3})
        assert "self_cast_lockout_seconds" not in floored["passive"]

    def test_the_option_is_registered_with_a_zero_default(self):
        meta = get_champion_options_meta("Rumble")
        row = next(o for o in meta["options"] if o["key"] == "overheat_windows")
        assert row["default"] == 0
        assert row["min"] == 0
        assert row["max"] == _MAX_OVERHEAT_WINDOWS

    def test_a_shortened_attack_speed_row_raises_instead_of_pricing_the_max(self):
        """``extract_value`` falls through to the LAST value past its axis.

        A truncated per-level row would otherwise price level 20's 142.54%
        at every level, silently — the documented Weapon Master trap.
        """
        broken = copy.deepcopy(_RUMBLE)
        row = _leveling_row(
            broken["abilities"]["P"][0]["effects"][2], "Per-Level Scaling"
        )
        row["modifiers"][0]["values"] = row["modifiers"][0]["values"][:5]
        with pytest.raises(ValueError, match="does not carry the Overheated bonus"):
            parse_champion_abilities(
                broken,
                20,
                0.0,
                champion_stats=dict(calculate_total_stats(broken, 20, [])),
                target_stats=dict(_TARGET),
                champion_options={"overheat_windows": 1},
            )

    def test_the_declared_windows_must_fit_the_declared_fight(self):
        """Saturation is the failure a clamp hides.

        Clamped, windows 3, 4 and 5 all returned one 10-second fight's
        answer: ``buff_window_share`` capped the attack speed at 1.0 while
        ``self_cast_lockout_seconds`` kept growing past a horizon that had
        already hit zero, so three distinct declarations priced alike.
        """
        for windows in (3, 4, 5):
            with pytest.raises(ValueError, match="does not fit in the declared"):
                _parse(
                    20,
                    options={
                        "overheat_windows": windows,
                        "fight_duration_seconds": 10.0,
                    },
                )

    def test_the_refusal_names_the_numbers_and_the_fitting_count(self):
        with pytest.raises(ValueError) as excinfo:
            _parse(
                20,
                options={"overheat_windows": 3, "fight_duration_seconds": 10.0},
            )
        message = str(excinfo.value)
        assert "3 x 4s = 12s" in message
        assert "10s fight" in message
        assert "declare at most 2 window(s)" in message

    def test_the_windows_that_do_fit_are_untouched(self):
        for windows in (1, 2):
            _, abilities = _parse(
                20,
                options={
                    "overheat_windows": windows,
                    "fight_duration_seconds": 10.0,
                },
            )
            assert abilities["passive"]["self_cast_lockout_seconds"] == pytest.approx(
                4.0 * windows
            )

    def test_a_clockless_parse_has_no_horizon_to_contradict(self):
        """One-rotation mode and direct parses carry no fight duration."""
        _, abilities = _parse(20, options={"overheat_windows": 5})
        assert abilities["passive"]["self_cast_lockout_seconds"] == pytest.approx(20.0)

    def test_empowered_autos_derive_the_window_that_holds_them(self):
        """A swing is evidence of the window it landed in.

        Priced alone, ``overheat_autos`` bought empowered damage during
        zero declared windows — upside with nothing paying for it. The
        window is derived rather than refused because the shared option
        sweeps (``cast_dependency_audit.option_states``) arm one option at
        a time and can never satisfy a cross-option rule.
        """
        _, abilities = _parse(20, options={"overheat_autos": 3})
        passive = abilities["passive"]
        assert passive["on_hit"]["max_procs"] == 3
        assert passive["self_cast_lockout_seconds"] == pytest.approx(4.0)
        assert passive["stat_buff"] == {"bonus_attack_speed": pytest.approx(142.54)}
        assert "derived from the declared swings" in passive["detail"]

    def test_a_declared_window_is_not_overridden_by_the_derivation(self):
        _, abilities = _parse(20, options={"overheat_autos": 3, "overheat_windows": 2})
        passive = abilities["passive"]
        assert passive["self_cast_lockout_seconds"] == pytest.approx(8.0)
        assert "2 Overheat window(s) of 4s declared" in passive["detail"]

    def test_an_autos_only_fight_drops_the_window_and_the_swings(self):
        """No cast, no Heat — and no empowered swing without the window."""
        _, abilities = _parse(
            20,
            options={
                "overheat_autos": 3,
                "overheat_windows": 2,
                "auto_attacks_only": True,
            },
        )
        passive = abilities["passive"]
        assert "on_hit" not in passive
        assert "stat_buff" not in passive
        assert "self_cast_lockout_seconds" not in passive
        assert "builds no Heat and never Overheats" in passive["detail"]

    def test_autos_inside_a_declared_window_are_priced(self):
        _, abilities = _parse(20, options={"overheat_autos": 3, "overheat_windows": 1})
        assert abilities["passive"]["on_hit"]["max_procs"] == 3

    def test_the_assumption_states_the_axis_and_its_refusal(self):
        assumption = next(a for a in ASSUMPTIONS if "heat axis" in a)
        assert "142.54" in assumption
        assert "overheat_windows" in assumption
        # The one thing the model still declines to claim.
        assert "not which casts it eats" in assumption


# ---------------------------------------------------------------------------
# W — the shield and the kernel repair it required
# ---------------------------------------------------------------------------


def _shield(champion: str, slot: str, level: int, stats: dict, rank: int = 5):
    effects = derive_ally_effects(
        get_champion(champion),
        level,
        dict(stats),
        [{"slot": slot, "time": 1.0}],
        ability_ranks={slot: rank},
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
    """Read off the contract, not a module constant.

    Every slot is emitted and priced, so ``module_contract.default_coverage``
    already derives exactly this map; the contract refuses a module-level
    ``MODULE_COVERAGE`` that restates what SLOTS derive, so the assertion
    reads the registry's answer instead.
    """
    assert get_champion_module_contract("Rumble").coverage == {
        "P": "modeled",
        "Q": "modeled",
        "W": "modeled",
        "E": "modeled",
        "R": "modeled",
    }
