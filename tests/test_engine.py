"""Tests for the slot-archetype engine (engine.py) and slotlib archetypes.

Two layers:
- Equivalence: the engine running GENERIC_SLOTS must produce output
  identical to the legacy generic parser for every champion in the data.
  This is the Phase 3 step-1 contract and survives golden-baseline churn.
- Engine unit tests on synthetic slot maps / champion JSON: phase
  ordering, insertion order within a phase, zero-damage entry emission,
  and the shared factory params (source / cooldown_from / casts / ranks).
"""

import json

import pytest

from src.calculator.champions import GENERIC_SLOTS
from src.calculator.champions import parse_abilities as dispatch_parse
from src.calculator.champions.engine import (
    BUFF,
    PHASE_ORDER,
    build_parser,
)
from src.calculator.champions.generic_parser import (
    parse_abilities as legacy_generic_parse,
)
from src.calculator.champions.slotlib import (
    extract_value,
    multi_cast,
    on_hit_auto,
    proc_damage,
    simple_damage,
    toggle_dot,
    utility,
)

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def champions_data() -> dict:
    """Load all champion data from JSON."""
    with open("data/champions.json") as f:
        return json.load(f)


def _default_stats(**overrides: float) -> dict[str, float]:
    """Create a default champion stats dict for testing."""
    stats = {
        "attack_damage": 150.0,
        "bonus_attack_damage": 50.0,
        "base_attack_damage": 100.0,
        "ability_power": 200.0,
        "health": 2500.0,
        "bonus_health": 500.0,
        "armor": 80.0,
        "magic_resistance": 60.0,
        "max_mana": 1000.0,
        "bonus_mana": 400.0,
    }
    stats.update(overrides)
    return stats


def _default_target(**overrides: float) -> dict[str, float]:
    """Create a default target stats dict."""
    stats = {
        "target_max_health": 2500.0,
        "target_current_health": 2500.0,
        "target_missing_health": 0.0,
    }
    stats.update(overrides)
    return stats


def _engine_parse(champ: dict, *args, **kwargs) -> dict:
    """Run a champion through the engine with the generic slot map."""
    parse = build_parser(GENERIC_SLOTS, champ.get("name", ""))
    return parse(champ, *args, **kwargs)


def _leveling(attribute: str, values: list, units: list | None = None) -> dict:
    """Build one effects[].leveling[] entry with a single modifier."""
    return {
        "attribute": attribute,
        "modifiers": [
            {"values": values, "units": units or [""] * len(values)},
        ],
    }


def _ability(
    name: str = "Test Ability",
    damage_type: str | None = "MAGIC_DAMAGE",
    cooldowns: list | None = None,
    leveling: list | None = None,
    targeting: str | None = None,
    description: str = "",
) -> dict:
    """Build a minimal ability JSON dict."""
    ability: dict = {
        "name": name,
        "effects": [{"description": description, "leveling": leveling or []}],
    }
    if damage_type is not None:
        ability["damageType"] = damage_type
    if cooldowns is not None:
        ability["cooldown"] = {
            "modifiers": [
                {"values": cooldowns, "units": [""] * len(cooldowns)},
            ],
        }
    if targeting is not None:
        ability["targeting"] = targeting
    return ability


def _champion(name: str = "TestChamp", **slots: list) -> dict:
    """Build a minimal champion data dict from slot -> ability list."""
    return {"name": name, "abilities": slots}


# ---------------------------------------------------------------------------
# Equivalence with the legacy generic parser (the step-1 contract)
# ---------------------------------------------------------------------------


class TestGenericEquivalence:
    """Engine + GENERIC_SLOTS must match generic_parser exactly."""

    @pytest.mark.parametrize("level", [4, 13, 18])
    def test_all_champions_match_legacy(
        self,
        champions_data: dict,
        level: int,
    ) -> None:
        """Every champion, identical output at low/mid/max level."""
        stats = _default_stats()
        target = _default_target()
        for cid, champ in champions_data.items():
            legacy = legacy_generic_parse(
                champ,
                level,
                200.0,
                champion_stats=stats,
                target_stats=target,
            )
            engine = _engine_parse(
                champ,
                level,
                200.0,
                champion_stats=stats,
                target_stats=target,
            )
            assert engine == legacy, f"Mismatch for {champ.get('name', cid)}"

    def test_all_champions_match_without_stats(
        self,
        champions_data: dict,
    ) -> None:
        """Identical output when champion/target stats are omitted."""
        for cid, champ in champions_data.items():
            legacy = legacy_generic_parse(champ, 13, 150.0)
            engine = _engine_parse(champ, 13, 150.0)
            assert engine == legacy, f"Mismatch for {champ.get('name', cid)}"

    def test_all_champions_match_with_rank_overrides(
        self,
        champions_data: dict,
    ) -> None:
        """Identical output under explicit ability_ranks."""
        stats = _default_stats()
        target = _default_target()
        ranks = {"Q": 1, "W": 2, "E": 3, "R": 1}
        for cid, champ in champions_data.items():
            legacy = legacy_generic_parse(
                champ,
                18,
                200.0,
                ability_ranks=ranks,
                champion_stats=stats,
                target_stats=target,
            )
            engine = _engine_parse(
                champ,
                18,
                200.0,
                ability_ranks=ranks,
                champion_stats=stats,
                target_stats=target,
            )
            assert engine == legacy, f"Mismatch for {champ.get('name', cid)}"

    def test_dispatcher_fallback_uses_engine(
        self,
        champions_data: dict,
    ) -> None:
        """Unregistered champions dispatched normally match the legacy path."""
        champ = next(c for c in champions_data.values() if c.get("name") == "Garen")
        stats = _default_stats()
        target = _default_target()
        legacy = legacy_generic_parse(
            champ,
            13,
            200.0,
            champion_stats=stats,
            target_stats=target,
        )
        dispatched = dispatch_parse(
            "Garen",
            champ,
            13,
            200.0,
            champion_stats=stats,
            target_stats=target,
        )
        assert dispatched == legacy


# ---------------------------------------------------------------------------
# Phase ordering
# ---------------------------------------------------------------------------


class TestPhaseOrdering:
    """Cross-phase order is engine-guaranteed; within a phase, insertion."""

    def test_buff_mutates_stats_before_damage_slot(self) -> None:
        """A BUFF slot listed AFTER a damage slot still runs first."""

        def q_reads_ad(ctx):
            return {"name": "Q", "total_raw": ctx.stats["attack_damage"]}

        def r_buffs_ad(ctx):
            ctx.stats["attack_damage"] += 100.0
            return {"name": "R Steroid", "total_raw": 0.0}

        r_buffs_ad.phase = BUFF

        # Q listed first in the map — phase order must still win.
        parse = build_parser({"Q": q_reads_ad, "R": r_buffs_ad}, "TestChamp")
        results = parse(
            _champion(),
            9,
            0.0,
            champion_stats={"attack_damage": 50.0},
        )
        assert results["Q"]["total_raw"] == 150.0

    def test_insertion_order_within_phase(self) -> None:
        """Within a phase, ctx.results exposes earlier slots' entries."""

        def q_base(ctx):
            return {"name": "Q", "total_raw": 40.0}

        def w_depends_on_q(ctx):
            # Illaoi pattern: W defined in terms of Q's computed damage.
            return {"name": "W", "total_raw": ctx.results["Q"]["total_raw"] * 2}

        parse = build_parser(
            {"Q": q_base, "W": w_depends_on_q},
            "TestChamp",
        )
        results = parse(_champion(), 9, 0.0)
        assert results["W"]["total_raw"] == 80.0

    def test_unknown_phase_rejected_at_build_time(self) -> None:
        """A typo'd .phase on a custom parser fails fast, at build time."""

        def bad(ctx):
            return None

        bad.phase = "sideways"
        with pytest.raises(ValueError, match="sideways"):
            build_parser({"Q": bad}, "TestChamp")

    def test_phase_order_constant(self) -> None:
        """The approved phase order: BUFF -> DEBUFF -> DAMAGE -> ONHIT -> AMP."""
        assert PHASE_ORDER == ("buff", "debuff", "damage", "onhit", "amp")


# ---------------------------------------------------------------------------
# Zero-damage entry emission (the stat_buff trap)
# ---------------------------------------------------------------------------


class TestZeroDamageEmission:
    """Entries a parser returns are emitted even at zero damage."""

    def test_engine_emits_zero_damage_entry(self) -> None:
        """The engine never drops an entry, even at zero damage."""

        def r_stat_buff(ctx):
            return {"name": "Stat Buff", "total_raw": 0.0}

        r_stat_buff.phase = BUFF
        parse = build_parser({"R": r_stat_buff}, "TestChamp")
        results = parse(_champion(), 9, 0.0)
        assert results["R"] == {"name": "Stat Buff", "total_raw": 0.0}

    def test_explicit_attr_emits_zero_damage(self) -> None:
        """simple_damage with an explicit attr never drops the slot."""
        champ = _champion(
            Q=[
                _ability(
                    name="Zero Q",
                    cooldowns=[8, 8, 8, 8, 8],
                    leveling=[_leveling("Special Damage", [0, 0, 0, 0, 0])],
                )
            ],
        )
        parse = build_parser(
            {"Q": simple_damage(attr="Special Damage")},
            "TestChamp",
        )
        results = parse(champ, 9, 0.0)
        assert results["Q"]["total_raw"] == 0.0
        assert results["Q"]["name"] == "Zero Q"


# ---------------------------------------------------------------------------
# simple_damage factory params
# ---------------------------------------------------------------------------


class TestSimpleDamageParams:
    """source / cooldown_from / casts / ranks / dmg_type handling."""

    def _two_entry_q_champ(self) -> dict:
        """Q slot with a cooldown-bearing container at 0, damage at 1."""
        container = _ability(
            name="Q Container",
            cooldowns=[12, 11, 10, 9, 8],
            leveling=[],
        )
        subspell = _ability(
            name="Q Subspell",
            leveling=[_leveling("Magic Damage", [50, 90, 130, 170, 210])],
        )
        return _champion(Q=[container, subspell])

    def test_source_reads_other_entry(self) -> None:
        """source=(slot, index) reads a non-default JSON entry."""
        champ = self._two_entry_q_champ()
        parse = build_parser(
            {"Q": simple_damage(source=("Q", 1))},
            "TestChamp",
        )
        results = parse(champ, 9, 0.0)  # Q rank 5 at level 9
        assert results["Q"]["name"] == "Q Subspell"
        assert results["Q"]["total_raw"] == 210.0

    def test_cooldown_from_other_entry(self) -> None:
        """Damage from the subspell, cooldown from its container."""
        champ = self._two_entry_q_champ()
        parse = build_parser(
            {"Q": simple_damage(source=("Q", 1), cooldown_from=("Q", 0))},
            "TestChamp",
        )
        results = parse(champ, 9, 0.0)
        assert results["Q"]["cooldown"] == 8.0

    def test_casts_int_multiplies_damage(self) -> None:
        """An int casts param multiplies the slot's total damage."""
        champ = _champion(
            Q=[
                _ability(
                    name="Triple Q",
                    cooldowns=[10, 10, 10, 10, 10],
                    leveling=[_leveling("Magic Damage", [60, 70, 80, 90, 100])],
                )
            ],
        )
        parse = build_parser({"Q": simple_damage(casts=3)}, "TestChamp")
        results = parse(champ, 9, 0.0)
        assert results["Q"]["total_raw"] == 300.0

    def test_casts_as_attribute_name(self) -> None:
        """Xerath-R pattern: the cast count is itself leveling data."""
        champ = _champion(
            R=[
                _ability(
                    name="Recast R",
                    cooldowns=[120, 110, 100],
                    leveling=[
                        _leveling("Magic Damage", [200, 250, 300]),
                        _leveling("Number of Recasts", [3, 4, 5]),
                    ],
                )
            ],
        )
        parse = build_parser(
            {"R": simple_damage(casts="Number of Recasts")},
            "TestChamp",
        )
        results = parse(champ, 11, 0.0)  # R rank 2 at level 11
        assert results["R"]["total_raw"] == 250.0 * 4

    def test_casts_attribute_missing_falls_back_to_one(self) -> None:
        """A missing casts attribute means one cast, not zero damage."""
        champ = _champion(
            Q=[
                _ability(
                    name="Q",
                    cooldowns=[10, 10, 10, 10, 10],
                    leveling=[_leveling("Magic Damage", [60, 70, 80, 90, 100])],
                )
            ],
        )
        parse = build_parser(
            {"Q": simple_damage(casts="No Such Attribute")},
            "TestChamp",
        )
        results = parse(champ, 9, 0.0)
        assert results["Q"]["total_raw"] == 100.0

    def test_cooldown_recharge_reads_recharge_rate(self) -> None:
        """Charge abilities: rechargeRate is the sustained-use limiter."""
        ability = _ability(
            name="Charge Q",
            cooldowns=[3, 3, 3, 3, 3],  # inter-cast timer, NOT the limiter
            leveling=[_leveling("Magic Damage", [70, 95, 120, 145, 170])],
        )
        ability["rechargeRate"] = [16, 15, 14, 13, 12]
        champ = _champion(Q=[ability])
        parse = build_parser(
            {"Q": simple_damage(cooldown="recharge")},
            "TestChamp",
        )
        results = parse(champ, 9, 0.0)  # Q rank 5
        assert results["Q"]["cooldown"] == 12.0

    def test_cooldown_recharge_falls_back_to_cooldown(self) -> None:
        """Without rechargeRate data, recharge mode uses the cooldown."""
        champ = _champion(
            Q=[
                _ability(
                    name="Q",
                    cooldowns=[10, 9, 8, 7, 6],
                    leveling=[_leveling("Magic Damage", [70, 95, 120, 145, 170])],
                )
            ],
        )
        parse = build_parser(
            {"Q": simple_damage(cooldown="recharge")},
            "TestChamp",
        )
        results = parse(champ, 9, 0.0)
        assert results["Q"]["cooldown"] == 6.0

    def test_unknown_cooldown_mode_rejected_at_factory_time(self) -> None:
        with pytest.raises(ValueError, match="sideways"):
            simple_damage(cooldown="sideways")

    def test_ranks_level_pins_rank_to_champion_level(self) -> None:
        """Aphelios pattern: per-level values with rank pinned to level."""
        per_level = [float(10 * (i + 1)) for i in range(18)]
        champ = _champion(
            Q=[
                _ability(
                    name="Level-scaled Q",
                    leveling=[_leveling("Physical Damage", per_level)],
                    damage_type="PHYSICAL_DAMAGE",
                )
            ],
        )
        parse = build_parser(
            {"Q": simple_damage(ranks="level")},
            "TestChamp",
        )
        results = parse(champ, 7, 0.0)
        assert results["Q"]["total_raw"] == 70.0  # values[level - 1]
        assert results["Q"]["rank"] == 7

    def test_explicit_dmg_type_overrides_classifier(self) -> None:
        """An explicit dmg_type wins over the JSON classifier."""
        champ = _champion(
            Q=[
                _ability(
                    name="Q",
                    cooldowns=[10, 10, 10, 10, 10],
                    leveling=[_leveling("Magic Damage", [60, 70, 80, 90, 100])],
                )
            ],
        )
        parse = build_parser(
            {"Q": simple_damage(dmg_type="true")},
            "TestChamp",
        )
        results = parse(champ, 9, 0.0)
        assert results["Q"]["damage_type"] == "true"
        assert results["Q"]["true_damage"] == 100.0
        assert "magic_damage" not in results["Q"]

    def test_mixed_type_splits_magic_and_true(self) -> None:
        """Mixed damage splits evenly between magic and true (Ahri Q)."""
        champ = _champion(
            Q=[
                _ability(
                    name="Mixed Q",
                    damage_type="MIXED_DAMAGE",
                    cooldowns=[10, 10, 10, 10, 10],
                    leveling=[_leveling("Mixed Damage", [60, 70, 80, 90, 100])],
                )
            ],
        )
        parse = build_parser({"Q": simple_damage()}, "TestChamp")
        results = parse(champ, 9, 0.0)
        assert results["Q"]["magic_damage"] == 50.0
        assert results["Q"]["true_damage"] == 50.0


# ---------------------------------------------------------------------------
# toggle_dot archetype
# ---------------------------------------------------------------------------


class TestToggleDot:
    """Phase-structured toggle/channel DoT summed into a damage entry."""

    def _dot_champ(self) -> dict:
        """R with initial and empowered per-tick attrs (Anivia shape)."""
        return _champion(
            R=[
                _ability(
                    name="Storm",
                    cooldowns=[6, 6, 6],
                    leveling=[
                        _leveling("Magic Damage per Tick", [30, 45, 60]),
                        _leveling("Empowered Damage per Tick", [90, 135, 180]),
                    ],
                )
            ],
        )

    def _parse_storm(self, options: dict | None = None, **params) -> dict:
        defaults = {
            "phases": [
                ("Magic Damage per Tick", 3),
                ("Empowered Damage per Tick", None),
            ],
            "duration_option": ("r_duration", 5.0),
            "min_duration": 1.5,
            "cooldown": 999.0,
            "dmg_type": "magic",
        }
        defaults.update(params)
        parse = build_parser({"R": toggle_dot(**defaults)}, "TestChamp")
        # Level 16 -> R rank 3.
        return parse(self._dot_champ(), 16, 0.0, champion_options=options)

    def test_phases_split_ticks_in_order(self) -> None:
        """5s at 0.5s/tick = 3 initial + 7 empowered ticks."""
        results = self._parse_storm()
        assert results["R"]["total_raw"] == pytest.approx(3 * 60 + 7 * 180)
        assert results["R"]["magic_damage"] == results["R"]["total_raw"]

    def test_duration_option_overrides_default(self) -> None:
        """10s = 3 initial + 17 empowered ticks."""
        results = self._parse_storm(options={"r_duration": 10.0})
        assert results["R"]["total_raw"] == pytest.approx(3 * 60 + 17 * 180)

    def test_min_duration_clamp(self) -> None:
        """Durations below the floor are clamped (3 initial ticks only)."""
        results = self._parse_storm(options={"r_duration": 0.5})
        assert results["R"]["total_raw"] == pytest.approx(3 * 60)

    def test_cooldown_is_pinned_by_caller(self) -> None:
        """The cooldown param is used verbatim (999 = cast-once)."""
        results = self._parse_storm()
        assert results["R"]["cooldown"] == 999.0

    def test_single_phase_consumes_all_ticks(self) -> None:
        """A single uncapped phase gets every tick."""
        results = self._parse_storm(
            phases=[("Magic Damage per Tick", None)],
            cooldown=0.0,
        )
        assert results["R"]["total_raw"] == pytest.approx(10 * 60)
        assert results["R"]["cooldown"] == 0.0

    def test_rank_gate(self) -> None:
        """Unranked slot emits nothing."""
        parse = build_parser(
            {
                "R": toggle_dot(
                    phases=[("Magic Damage per Tick", None)],
                    duration_option=("r_duration", 5.0),
                )
            },
            "TestChamp",
        )
        results = parse(self._dot_champ(), 16, 0.0, ability_ranks={"R": 0})
        assert "R" not in results


# ---------------------------------------------------------------------------
# multi_cast archetype
# ---------------------------------------------------------------------------


class TestMultiCast:
    """N recasts per activation, reported per-cast (Ahri R pattern)."""

    def _dash_champ(self) -> dict:
        return _champion(
            R=[
                _ability(
                    name="Dash R",
                    cooldowns=[130, 105, 80],
                    leveling=[_leveling("Magic Damage", [60, 90, 120])],
                )
            ],
        )

    def test_emits_per_cast_shape_without_cooldown(self) -> None:
        """total_casts stays an int; no cooldown key in the entry."""
        parse = build_parser(
            {"R": multi_cast(casts=3, dmg_type="magic")},
            "TestChamp",
        )
        results = parse(self._dash_champ(), 16, 0.0)  # R rank 3
        assert results["R"] == {
            "name": "Dash R",
            "rank": 3,
            "damage_per_cast": 120.0,
            "total_casts": 3,
            "total_raw": 360.0,
            "damage_type": "magic",
        }

    def test_explicit_attr_mode(self) -> None:
        parse = build_parser(
            {"R": multi_cast(casts=2, attr="Magic Damage", dmg_type="magic")},
            "TestChamp",
        )
        results = parse(self._dash_champ(), 6, 0.0)  # R rank 1
        assert results["R"]["damage_per_cast"] == 60.0
        assert results["R"]["total_raw"] == 120.0

    def test_rank_gate(self) -> None:
        parse = build_parser(
            {"R": multi_cast(casts=3, dmg_type="magic")},
            "TestChamp",
        )
        results = parse(self._dash_champ(), 16, 0.0, ability_ranks={"R": 0})
        assert "R" not in results


# ---------------------------------------------------------------------------
# proc_damage archetype
# ---------------------------------------------------------------------------


class TestProcDamage:
    """Count-configurable passive procs (Akali/Ambessa/Akshan pattern)."""

    def _proc_champ(self) -> dict:
        per_level = [float(10 + 5 * i) for i in range(18)]
        return _champion(
            P=[
                _ability(
                    name="Mark",
                    leveling=[_leveling("Bonus Magic Damage", per_level)],
                )
            ],
        )

    def _parse(self, options: dict | None = None, **params) -> dict:
        defaults = {"attr": "Bonus Magic Damage", "dmg_type": "magic"}
        defaults.update(params)
        parse = build_parser({"P": proc_damage(**defaults)}, "TestChamp")
        return parse(self._proc_champ(), 9, 0.0, champion_options=options)

    def test_per_proc_scales_with_level_and_count_multiplies(self) -> None:
        """Level 9 per-proc = 50; 3 procs -> 150 total under "passive"."""
        results = self._parse(options={"passive_procs": 3})
        assert results["passive"] == {
            "name": "Mark",
            "damage_type": "magic",
            "magic_damage": 50.0,
            "total_raw": 150.0,
            "proc_count": 3,
        }

    def test_default_count_when_option_absent(self) -> None:
        results = self._parse(default_count=4)
        assert results["passive"]["proc_count"] == 4
        assert results["passive"]["total_raw"] == 200.0

    def test_zero_procs_emits_nothing(self) -> None:
        results = self._parse(options={"passive_procs": 0})
        assert results == {}

    def test_zero_damage_emits_nothing(self) -> None:
        results = self._parse(attr="No Such Attribute")
        assert results == {}

    def test_physical_type_uses_physical_key(self) -> None:
        results = self._parse(dmg_type="physical", options={"passive_procs": 2})
        assert results["passive"]["physical_damage"] == 50.0
        assert "magic_damage" not in results["passive"]


# ---------------------------------------------------------------------------
# utility archetype and extract_value
# ---------------------------------------------------------------------------


class TestUtility:
    """Zero-damage display placeholder for ranked utility abilities."""

    def _shield_champ(self) -> dict:
        return _champion(
            E=[
                _ability(
                    name="Shield",
                    damage_type=None,
                    cooldowns=[14, 13, 12, 11, 10],
                    leveling=[_leveling("Shield Strength", [60, 90, 120, 150, 180])],
                )
            ],
        )

    def test_emits_zero_damage_entry_with_real_cooldown(self) -> None:
        parse = build_parser({"E": utility(dmg_type="magic")}, "TestChamp")
        results = parse(self._shield_champ(), 9, 0.0, ability_ranks={"E": 5})
        assert results["E"] == {
            "name": "Shield",
            "rank": 5,
            "cooldown": 10.0,
            "damage_type": "magic",
            "magic_damage": 0.0,
            "total_raw": 0.0,
        }

    def test_rank_gate(self) -> None:
        parse = build_parser({"E": utility()}, "TestChamp")
        results = parse(self._shield_champ(), 9, 0.0, ability_ranks={"E": 0})
        assert "E" not in results


class TestExtractValue:
    """Raw leveling value extraction (no scaling resolution)."""

    def _ability_with_two_modifiers(self) -> dict:
        return {
            "name": "Buff",
            "effects": [
                {
                    "leveling": [
                        {
                            "attribute": "Bonus Attack Speed",
                            "modifiers": [
                                {"values": [20, 30, 40, 50, 60], "units": ["%"] * 5},
                                {"values": [5, 5, 5, 5, 5], "units": ["%"] * 5},
                            ],
                        },
                    ],
                },
            ],
        }

    def test_reads_first_modifier_at_rank(self) -> None:
        ability = self._ability_with_two_modifiers()
        assert extract_value(ability, "Bonus Attack Speed", 3) == 40.0

    def test_modifier_index_selects_modifier(self) -> None:
        ability = self._ability_with_two_modifiers()
        assert extract_value(ability, "Bonus Attack Speed", 3, modifier_index=1) == 5.0

    def test_missing_attribute_returns_zero(self) -> None:
        ability = self._ability_with_two_modifiers()
        assert extract_value(ability, "No Such Attribute", 3) == 0.0


# ---------------------------------------------------------------------------
# P-slot handling
# ---------------------------------------------------------------------------


class TestPassiveSlot:
    """P slot maps to the "passive" results key; on_hit_auto detection."""

    def test_p_slot_keys_result_as_passive(self) -> None:
        """The P slot's entry lands under the "passive" results key."""
        champ = _champion(
            P=[
                _ability(
                    name="Test Passive",
                    description="Basic attacks deal bonus magic damage on-hit.",
                    leveling=[
                        _leveling("Magic Damage", [float(5 + i) for i in range(18)])
                    ],
                )
            ],
        )
        parse = build_parser({"P": on_hit_auto()}, "TestChamp")
        results = parse(champ, 10, 0.0)
        assert "passive" in results
        assert results["passive"]["on_hit"]["damage_per_hit"] == 14.0

    def test_on_hit_auto_requires_keywords(self) -> None:
        """A passive without on-hit keywords emits nothing."""
        champ = _champion(
            P=[
                _ability(
                    name="Not On-Hit",
                    description="Deals damage in an area around the champion.",
                    leveling=[_leveling("Magic Damage", [10.0] * 18)],
                )
            ],
        )
        parse = build_parser({"P": on_hit_auto()}, "TestChamp")
        assert parse(champ, 10, 0.0) == {}

    def test_on_hit_auto_requires_damage_type(self) -> None:
        """A passive without a damageType field emits nothing."""
        champ = _champion(
            P=[
                _ability(
                    name="Utility Passive",
                    damage_type=None,
                    description="Basic attacks slow the target on-hit.",
                    leveling=[_leveling("Slow", [20.0] * 18, units=["%"] * 18)],
                )
            ],
        )
        parse = build_parser({"P": on_hit_auto()}, "TestChamp")
        assert parse(champ, 10, 0.0) == {}
