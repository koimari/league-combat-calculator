"""Mel P (Searing Brilliance) and the W (Rebuttal) ``no_damage`` receipt.

The roadmap slot session closes Mel's last two ``out_of_scope`` rows,
and they close for DIFFERENT reasons — this file pins both.

**P was mislabelled, not unmodellable.**  The packet asset's stock
reason ("no enemy-damage formula for this slot") was wrong: the slot
carries three mechanics and the third is ordinary, priceable damage.
Mel's ability casts each generate 3 stacks of Searing Brilliance for 5
seconds (max 9), and her next basic attack consumes them all to fire one
blazing projectile per stack for ``8 : 30 (based on level) (+ 4% AP)``
magic damage each.  That is the cast-armed empower window Taric's
Bravado introduced, so P is priced through ``_empower_window_procs``
rather than ``empowers_next_auto`` (which multiplies flatly by cast
count).  Mechanic 2, the Overwhelm stored-damage detonation, stays a
DOCUMENTED kill boundary — asserted here to stamp no execute ratio.

**W owns no damage at all.**  ``no_damage`` is a receipt, not a gap:
three independent cached sources agree that Rebuttal has no damage term
of its own, and this file recomputes all three rather than trusting the
label.

Four layers are pinned:

1. The ladder, recomputed from the game file's own interpolation
   endpoints (``8.0 -> 30.0`` over levels 1-18, ``+0.04`` AP) against the
   cached wiki row, at the level endpoints and across every cached index.
2. The five hardcoded game-file constants, read back out of
   ``data/bin/characters/mel.bin.json`` — the rule declaration is only
   worth its comment if a patch that moves the binary fails the suite.
3. The module's fail-closed behavior when either cached row drifts or
   goes missing (no silent stale projectile, no ``.get(key, literal)``).
4. The end-to-end fight, where the never-overstates invariant is
   visible: every proc requires an arming cast, so the default
   3-projectile packet can only ever be at or below the live swing.
"""

import copy
import json
from pathlib import Path

import pytest

from src.calculator.champions import (
    get_champion_option_rotation,
    get_champion_options_meta,
    parse_champion_abilities,
)
from src.calculator.champions.mel import (
    _P_MAX_MISSILES,
    _P_MISSILE_AP_RATIO,
    _P_MISSILE_LEVEL_1,
    _P_MISSILE_LEVEL_18,
    _P_MISSILES_PER_CAST,
    _P_PER_MISSILE_TOLERANCE,
    _P_TOTAL_TOLERANCE,
    _P_WINDOW_DURATION,
    ASSUMPTIONS,
    MODULE_COVERAGE,
    _searing_brilliance_per_missile,
)
from src.calculator.damage import (
    FightConfig,
    _empower_window_procs,
    calculate_fight_damage,
)
from src.calculator.stats import calculate_total_stats

_DATA = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))
_MEL = _DATA["Mel"]
_MEL_P = _MEL["abilities"]["P"][0]
_BIN = json.loads(Path("data/bin/characters/mel.bin.json").read_text(encoding="utf-8"))
_ATOMS = json.loads(Path("data/atoms/mel.atoms.json").read_text(encoding="utf-8"))
_FULL_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}

# The game file's ByCharLevel interpolation, written out as arithmetic the
# test owns independently of the module: 8 at level 1, 30 at level 18, and
# a straight line of 22/17 per level between (and beyond — the cached wiki
# row extrapolates the same line up to the level-20 cap).
_LADDER_SPAN_LEVELS = 17.0


def _ladder(level: int) -> float:
    """One projectile's flat damage at ``level`` from the interpolation."""
    return _P_MISSILE_LEVEL_1 + (_P_MISSILE_LEVEL_18 - _P_MISSILE_LEVEL_1) * (
        (level - 1) / _LADDER_SPAN_LEVELS
    )


def _bin_object(script_name: str) -> dict:
    """The mSpell payload of a named bin SpellObject."""
    for value in _BIN.values():
        if isinstance(value, dict) and value.get("mScriptName") == script_name:
            return value["mSpell"]
    raise AssertionError(f"{script_name} is absent from mel.bin.json")


def _bin_data_value(spell: dict, name: str) -> list[float]:
    for entry in spell.get("DataValues", []):
        if entry.get("name") == name:
            return list(entry["values"])
    raise AssertionError(f"DataValue {name!r} is absent")


def _cached_row(occurrence: int) -> list[float]:
    """One of P's two cached "Per-Level Scaling" modifier value arrays."""
    rows = [
        leveling
        for effect in _MEL_P.get("effects", [])
        for leveling in effect.get("leveling", [])
        if leveling.get("attribute") == "Per-Level Scaling"
    ]
    return [float(value) for value in rows[occurrence]["modifiers"][0]["values"]]


def _parse(level: int, *, ability_power: float = 0.0, options: dict | None = None):
    """parse_champion_abilities for Mel at a level, with real stats."""
    stats = calculate_total_stats(_MEL, level, [])
    if ability_power:
        stats["ability_power"] = ability_power
    return parse_champion_abilities(
        _MEL,
        level,
        stats["ability_power"],
        ability_ranks=_FULL_RANKS,
        champion_options=options or {},
        champion_stats=stats,
        target_stats={"target_max_health": 2000.0, "target_current_health": 2000.0},
    )


def _engine_fight(level: int, duration: float, *, magic_resistance: float = 0.0):
    """A fight straight off ``calculate_fight_damage``.

    Zero resists so the breakdown row's numbers ARE the raw packet, and
    the API's breakdown whitelist does not hide the proc ledger.
    """
    stats = calculate_total_stats(_MEL, level, [])
    abilities = parse_champion_abilities(
        _MEL,
        level,
        stats["ability_power"],
        ability_ranks=_FULL_RANKS,
        champion_stats=stats,
        target_stats={
            "target_max_health": 10000.0,
            "target_current_health": 10000.0,
        },
    )
    return calculate_fight_damage(
        stats,
        abilities,
        [],
        FightConfig(
            target_health=10000.0,
            target_armor=0.0,
            target_magic_resistance=magic_resistance,
            fight_duration_seconds=duration,
            auto_attack_uptime=1.0,
            one_rotation=False,
            deterministic=True,
        ),
    )


# ---------------------------------------------------------------------------
# 1. The projectile ladder, recomputed against both cached sources
# ---------------------------------------------------------------------------


class TestProjectileLadder:
    @pytest.mark.parametrize(
        ("level", "per_missile"),
        [
            # 8 + 22 x (level - 1) / 17, rounded to the cache's 2 decimals:
            (1, 8.00),  # 8 + 0
            (6, 14.47),  # 8 + 22 x  5/17 == 14.470588
            (11, 20.94),  # 8 + 22 x 10/17 == 20.941176
            (18, 30.00),  # 8 + 22 x 17/17 == 30 exactly (the endpoint)
            (20, 32.59),  # 8 + 22 x 19/17 == 32.588235 (past the endpoint)
        ],
    )
    def test_cached_row_reproduces_the_game_file_interpolation(
        self, level: int, per_missile: float
    ) -> None:
        """The cached wiki row IS the binary's ladder, to cache rounding."""
        assert _cached_row(0)[level - 1] == pytest.approx(per_missile)
        assert _ladder(level) == pytest.approx(per_missile, abs=0.01)

    def test_every_cached_index_tracks_the_ladder(self) -> None:
        """Not just the endpoints — the whole 40-entry cached row.

        The module's tolerance is +/-0.01; the worst real deviation is
        0.0047 (level 11), so the gate has ~2x headroom over cache
        rounding and would still catch a one-decimal balance change.
        """
        row = _cached_row(0)
        worst = max(abs(value - _ladder(index + 1)) for index, value in enumerate(row))
        assert worst == pytest.approx(0.004706, abs=1e-6)
        assert worst < _P_PER_MISSILE_TOLERANCE

    def test_the_second_cached_row_is_exactly_nine_projectiles(self) -> None:
        """The 9-stack cap, corroborated by the wiki independently of the bin.

        Occurrence 1 is the all-stacks total ("72 : 270"); 72 == 9 x 8 and
        270 == 9 x 30.  Worst amplified rounding across the row is 0.04,
        inside the module's 0.06 tolerance.
        """
        per_missile = _cached_row(0)
        total = _cached_row(1)
        assert total[0] == pytest.approx(_P_MAX_MISSILES * per_missile[0])
        assert total[17] == pytest.approx(_P_MAX_MISSILES * per_missile[17])
        worst = max(
            abs(total[index] - _P_MAX_MISSILES * value)
            for index, value in enumerate(per_missile)
        )
        assert worst == pytest.approx(0.04, abs=1e-9)
        assert worst < _P_TOTAL_TOLERANCE


# ---------------------------------------------------------------------------
# 2. The hardcoded game-file rule declaration, read back out of the binary
# ---------------------------------------------------------------------------


class TestGameFileConstants:
    """Each of the five hardcoded constants against mel.bin.json.

    The module names these as a HARDCODED rule declaration to verify on
    patch updates; without this class that comment is unenforced.
    """

    def test_missiles_per_cast_and_cap(self) -> None:
        spell = _bin_object("MelPassive")
        assert set(_bin_data_value(spell, "PassiveBonusMissiles")) == {
            float(_P_MISSILES_PER_CAST)
        }
        assert set(_bin_data_value(spell, "MaxPassiveBonusMissiles")) == {
            float(_P_MAX_MISSILES)
        }

    def test_empower_window_duration(self) -> None:
        spell = _bin_object("MelPassive")
        assert set(_bin_data_value(spell, "BonusAttackDuration")) == {
            _P_WINDOW_DURATION
        }

    def test_missile_damage_interpolation_and_ap_coefficient(self) -> None:
        spell = _bin_object("MelPassive")
        parts = spell["mSpellCalculations"]["PassiveBonusMissileDamage"][
            "mFormulaParts"
        ]
        by_level = next(
            part
            for part in parts
            if part["__type"] == "ByCharLevelInterpolationCalculationPart"
        )
        coefficient = next(
            part
            for part in parts
            if part["__type"] == "StatByCoefficientCalculationPart"
        )
        assert by_level["mStartValue"] == pytest.approx(_P_MISSILE_LEVEL_1)
        assert by_level["mEndValue"] == pytest.approx(_P_MISSILE_LEVEL_18)
        # Stored as a float32 (0.03999999910593033), so compare as a ratio.
        assert coefficient["mCoefficient"] == pytest.approx(
            _P_MISSILE_AP_RATIO, abs=1e-6
        )

    def test_the_prose_stack_rule_matches_the_binary(self) -> None:
        """The cached description carries the same 3 / 9 / 5s the bin does."""
        prose = " ".join(
            effect.get("description", "") for effect in _MEL_P.get("effects", [])
        )
        assert f"generate {_P_MISSILES_PER_CAST} stacks of Searing Brilliance" in prose
        assert f"stacking up to {_P_MAX_MISSILES} times" in prose
        assert "for 5 seconds" in prose


# ---------------------------------------------------------------------------
# 3. The parsed P entry
# ---------------------------------------------------------------------------


class TestSearingBrillianceEntry:
    def test_coverage_closes_p_as_modeled_and_w_as_no_damage(self) -> None:
        assert MODULE_COVERAGE == {
            "P": "modeled",
            "Q": "modeled",
            "W": "no_damage",
            "E": "modeled",
            "R": "modeled",
        }

    @pytest.mark.parametrize(
        ("level", "expected"),
        [
            # 3 projectiles (one cast's stacks) x the ladder value:
            (1, 24.00),  # 3 x  8.00
            (6, 43.41),  # 3 x 14.47
            (11, 62.82),  # 3 x 20.94
            (18, 90.00),  # 3 x 30.00
            (20, 97.77),  # 3 x 32.59
        ],
    )
    def test_per_swing_damage_at_the_level_endpoints(
        self, level: int, expected: float
    ) -> None:
        """A no-item Mel holds no AP, so the +4% AP term is exactly 0 here."""
        on_hit = _parse(level)["passive"]["on_hit"]
        assert on_hit["damage_per_hit"] == pytest.approx(expected)
        assert on_hit["damage_type"] == "magic"

    def test_ability_power_scales_every_projectile(self) -> None:
        """3 x (30 + 0.04 x 250) == 3 x 40 == 120 at level 18."""
        on_hit = _parse(18, ability_power=250.0)["passive"]["on_hit"]
        assert on_hit["damage_per_hit"] == pytest.approx(120.0)

    def test_the_projectile_option_scales_the_swing_and_clamps_at_the_cap(
        self,
    ) -> None:
        """The sourced maximum 9 is the ceiling; 0 prices nothing."""
        base = _parse(18)["passive"]["on_hit"]["damage_per_hit"]
        full = _parse(18, options={"p_searing_brilliance_missiles": 9})
        assert full["passive"]["on_hit"]["damage_per_hit"] == pytest.approx(270.0)
        assert full["passive"]["on_hit"]["damage_per_hit"] == pytest.approx(base * 3)
        none = _parse(18, options={"p_searing_brilliance_missiles": 0})
        assert none["passive"]["on_hit"]["damage_per_hit"] == pytest.approx(0.0)
        over = _parse(18, options={"p_searing_brilliance_missiles": 99})
        assert over["passive"]["on_hit"]["damage_per_hit"] == pytest.approx(270.0)

    def test_the_empower_window_shape_is_the_sourced_one(self) -> None:
        """Every ability cast arms it; one basic attack spends it.

        ``charges_per_arm``/``max_charges`` are 1 because the kit grants
        ONE empowered attack — the stacks are the projectile count inside
        that swing, not extra swings.  ``refresh_on_consume`` is absent:
        no cached source says consuming the buff restarts its 5 seconds.
        """
        window = _parse(18)["passive"]["on_hit"]["empower_window"]
        assert tuple(window["armed_by"]) == ("Q", "W", "E", "R")
        assert window["duration"] == pytest.approx(_P_WINDOW_DURATION)
        assert window["charges_per_arm"] == 1
        assert window["max_charges"] == 1
        assert tuple(window["consumed_by"]) == ("auto",)
        assert "refresh_on_consume" not in window

    def test_the_certified_constants_ride_the_entry(self) -> None:
        constants = _parse(18)["passive"]["certified_constants"]
        assert constants == {
            "missiles_per_cast": _P_MISSILES_PER_CAST,
            "max_missiles": _P_MAX_MISSILES,
            "window_duration": _P_WINDOW_DURATION,
            "missile_ap_ratio": _P_MISSILE_AP_RATIO,
            "missile_level_1": _P_MISSILE_LEVEL_1,
            "missile_level_18": _P_MISSILE_LEVEL_18,
        }

    def test_the_projectile_option_is_classified_for_the_rotation(self) -> None:
        """Declared ``self_state``, not a duplicate ``stack_consume`` edge.

        The arming relation is already structural (``empower_window``
        walks the accepted cast timeline), and a ``consume`` role would
        have to name ONE ``setup_slot`` — which cannot express "any of
        the four ability slots arms it".
        """
        keys = {opt["key"] for opt in get_champion_options_meta("Mel")["options"]}
        assert "p_searing_brilliance_missiles" in keys
        declaration = get_champion_option_rotation("Mel")[
            "p_searing_brilliance_missiles"
        ]
        assert declaration == {"role": "self_state", "slot": "P"}


# ---------------------------------------------------------------------------
# 4. The Overwhelm kill boundary stays documented, never priced
# ---------------------------------------------------------------------------


class TestOverwhelmBoundary:
    def test_p_stamps_no_execute_ratio(self) -> None:
        """Mel's threshold is a POST-MITIGATION DAMAGE quantity.

        The engine's execute seam (``execute_threshold_ratio``, Zeri's
        Living Battery) takes a fraction of the target's MAXIMUM health.
        A champion module parses before mitigation exists, so the only
        ratio it could stamp is the unmitigated one — strictly larger
        than the real threshold, i.e. invented kills.
        """
        passive = _parse(18)["passive"]
        assert "execute_threshold_ratio" not in passive
        assert "execute_source" not in passive
        assert "stored_damage" not in passive

    def test_the_boundary_is_named_in_the_assumptions_and_the_detail(self) -> None:
        boundary = [line for line in ASSUMPTIONS if "Overwhelm" in line]
        assert any("documented, not priced" in line for line in boundary)
        assert "Overwhelm (P mechanic 2)" in _parse(18)["passive"]["detail"]

    def test_the_w_cooldown_cache_lag_receipt_survives(self) -> None:
        """The pre-existing 16.16.1 wiki-lag flag is untouched by this work."""
        assert any(line.startswith("KNOWN CACHE LAG") for line in ASSUMPTIONS)


# ---------------------------------------------------------------------------
# 5. Fail-closed: drifted or missing sources raise, never silently stale
# ---------------------------------------------------------------------------


class _Ctx:
    """The minimal SlotCtx surface ``_searing_brilliance_per_missile`` reads."""

    def __init__(self, level: int, ability_power: float = 0.0) -> None:
        self.level = level
        self.stats = {"ability_power": ability_power}


class TestFailClosed:
    def test_a_drifted_per_projectile_row_raises(self) -> None:
        """A balance change the game file did not corroborate must raise."""
        ability = copy.deepcopy(_MEL_P)
        row = next(
            leveling
            for effect in ability["effects"]
            for leveling in effect.get("leveling", [])
            if leveling.get("attribute") == "Per-Level Scaling"
        )
        row["modifiers"][0]["values"][17] = 34.0  # was 30 at level 18
        with pytest.raises(ValueError, match="projectile damage drifted"):
            _searing_brilliance_per_missile(_Ctx(18), ability)

    def test_a_drifted_stack_cap_row_raises(self) -> None:
        """If the total row stops being 9x the projectile, the cap moved."""
        ability = copy.deepcopy(_MEL_P)
        rows = [
            leveling
            for effect in ability["effects"]
            for leveling in effect.get("leveling", [])
            if leveling.get("attribute") == "Per-Level Scaling"
        ]
        rows[1]["modifiers"][0]["values"][17] = 240.0  # 8 projectiles, not 9
        with pytest.raises(ValueError, match="stack cap drifted"):
            _searing_brilliance_per_missile(_Ctx(18), ability)

    def test_a_missing_row_raises_instead_of_pricing_zero(self) -> None:
        """No ``.get(key, stale_literal)`` fallback: absence is loud."""
        ability = copy.deepcopy(_MEL_P)
        for effect in ability["effects"]:
            effect["leveling"] = []
        with pytest.raises(ValueError, match="missing its cached"):
            _searing_brilliance_per_missile(_Ctx(18), ability)


# ---------------------------------------------------------------------------
# 6. The fight, and the never-overstates invariant
# ---------------------------------------------------------------------------


class TestFightPricing:
    def test_a_proc_requires_an_arming_cast(self) -> None:
        """THE understatement guarantee.

        Every proc is preceded by at least one arming cast, so at the
        instant a charge is spent the live game holds at least the
        3 stacks that cast generated.  The default packet is therefore at
        or below the live swing for every timeline — never above it.
        """
        window = {
            "armed_by": ("Q", "W", "E", "R"),
            "duration": _P_WINDOW_DURATION,
            "charges_per_arm": 1,
            "max_charges": 1,
            "consumed_by": ("auto",),
        }
        # Four casts inside one window still spend ONE charge: the live
        # game would fire 9 projectiles on that swing, this prices 3.
        procs = _empower_window_procs(
            window,
            arm_times=[0.0, 0.35, 0.35, 0.6],
            consumer_times=[(time, "auto") for time in (1.0, 2.0, 3.0)],
        )
        assert procs == [1.0]
        # And a swing with no arming cast behind it prices nothing.
        assert (
            _empower_window_procs(window, arm_times=[], consumer_times=[(1.0, "auto")])
            == []
        )

    def test_the_fight_books_one_packet_per_consumed_charge(self) -> None:
        """Level 18, 5s, zero MR: one charge spent, 3 x 30 == 90 raw."""
        result = _engine_fight(18, 5.0)
        row = result["breakdown"]["on_hit_ability_passive"]
        assert row["count"] == 1
        assert row["unit"] == "procs"
        assert row["damage_type"] == "magic"
        assert row["damage_per_hit"] == pytest.approx(90.0)
        assert row["total_damage"] == pytest.approx(90.0)

    def test_the_packet_is_mitigated_by_magic_resistance(self) -> None:
        """40 MR: 90 x 100/140 == 64.2857 (the golden harness's target)."""
        row = _engine_fight(18, 5.0, magic_resistance=40.0)["breakdown"][
            "on_hit_ability_passive"
        ]
        assert row["total_damage"] == pytest.approx(90.0 * 100.0 / 140.0)

    def test_a_burst_with_no_autos_books_nothing(self) -> None:
        """No basic attack means no stack consumption — a real zero."""
        stats = calculate_total_stats(_MEL, 18, [])
        abilities = parse_champion_abilities(
            _MEL,
            18,
            stats["ability_power"],
            ability_ranks=_FULL_RANKS,
            champion_stats=stats,
            target_stats={
                "target_max_health": 10000.0,
                "target_current_health": 10000.0,
            },
        )
        result = calculate_fight_damage(
            stats,
            abilities,
            [],
            FightConfig(
                target_health=10000.0,
                target_armor=0.0,
                target_magic_resistance=0.0,
                fight_duration_seconds=5.0,
                auto_attack_uptime=0.0,
                one_rotation=True,
                deterministic=True,
            ),
        )
        assert "on_hit_ability_passive" not in result["breakdown"]


# ---------------------------------------------------------------------------
# 7. W (Rebuttal): the no_damage receipt, recomputed from all three sources
# ---------------------------------------------------------------------------


class TestRebuttalNoDamage:
    def test_the_w_row_prices_exactly_zero_and_still_exists(self) -> None:
        """``no_damage`` is a receipt row, not a dropped slot."""
        entry = _parse(18)["W"]
        assert entry["total_raw"] == pytest.approx(0.0)
        assert entry["parts"] == ()
        assert entry["rank"] == 5
        assert "no enemy projectile source is modeled" in entry["detail"]

    def test_the_binary_gives_w_no_damage_node(self) -> None:
        """MelW owns a PERCENT and a SHIELD — nothing to multiply.

        ``BaseDamagePercent`` is rank-indexed from 0, so ranks 1-5 are
        0.40/0.45/0.50/0.55/0.60 == the wiki's 40-60%; the physical twin
        is that times ``PhysDamageMod``-complement 0.7 (0.4 x 0.7 == the
        cached 28%).  A percentage is not a damage amount.
        """
        spell = _bin_object("MelW")
        assert set(spell["mSpellCalculations"]) == {"DamagePercent", "ShieldAmount"}
        ranks = _bin_data_value(spell, "BaseDamagePercent")[1:6]
        assert ranks == pytest.approx([0.40, 0.45, 0.50, 0.55, 0.60], abs=1e-6)
        physical = _bin_data_value(spell, "PhysDamageMod")[0]
        assert ranks[0] * (1.0 - physical) == pytest.approx(0.28, abs=1e-6)

    def test_no_damage_atom_is_emitted_for_w(self) -> None:
        """The atom corpus agrees: MelW carries only utility atoms."""
        by_behavior: dict[str, list[str]] = {}
        for atom in _ATOMS:
            by_behavior.setdefault(atom["behavior"], []).append(atom["atom_id"])
        assert sorted(by_behavior["MelW"]) == [
            "crowd-control-mobility.cc-immunity",
            "heal-shield.shield",
            "interaction.projectile-destruction",
        ]
        assert not any(atom.startswith("damage.") for atom in by_behavior["MelW"])
        # Contrast: every damaging slot does carry a damage instance.
        for behavior in ("MelQ", "MelE", "MelR"):
            assert "damage.damage-instance" in by_behavior[behavior]

    def test_the_receipt_is_named_in_the_assumptions(self) -> None:
        line = next(line for line in ASSUMPTIONS if line.startswith("W (Rebuttal)"))
        assert "prices no damage" in line
        assert "structurally absent" in line
