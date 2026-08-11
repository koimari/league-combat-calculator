"""Tests for the slot-archetype engine (engine.py) and slotlib archetypes.

Two layers:
- Dispatch: unregistered champions route to the engine running
  GENERIC_SLOTS. (The Phase 3a byte-for-byte equivalence tests against
  the legacy generic parser retired with generic_parser.py itself —
  the generic path's behavior is locked by tests/test_generic_path.py
  and the golden snapshot.)
- Engine unit tests on synthetic slot maps / champion JSON: phase
  ordering, insertion order within a phase, zero-damage entry emission,
  and the shared factory params (source / cooldown_from / casts / ranks).
"""

import json

import pytest

from src.calculator.ability_spec import DamagePart
from src.calculator.champions import GENERIC_SLOTS
from src.calculator.champions import parse_abilities as dispatch_parse
from src.calculator.champions.engine import (
    BUFF,
    DAMAGE,
    PHASE_ORDER,
    build_parser,
)
from src.calculator.champions.slotlib import (
    STEROID_ZERO,
    ability_on_hit_entry,
    by_option,
    damage_entry,
    extract_value,
    find_named_leveling,
    on_hit_auto,
    pct_health_per_hit,
    proc_damage,
    simple_damage,
    stat_buff,
    sum_modifiers,
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
# Dispatcher fallback
# ---------------------------------------------------------------------------


class TestDedicatedDispatch:
    """Every cached champion routes to a dedicated packet module."""

    def test_dispatcher_fallback_uses_engine(
        self,
        champions_data: dict,
    ) -> None:
        """Garen's dedicated packet is used instead of the legacy fallback."""
        champ = next(c for c in champions_data.values() if c.get("name") == "Garen")
        stats = _default_stats()
        target = _default_target()
        dispatched = dispatch_parse(
            "Garen",
            champ,
            13,
            200.0,
            champion_stats=stats,
            target_stats=target,
        )
        assert dispatched["Q"]["total_raw"] > 0
        assert dispatched["R"]["cooldown"] == 100.0


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
        assert results["Q"]["parts"] == (DamagePart("true", 100.0),)

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
        assert results["Q"]["parts"] == (
            DamagePart("magic", 50.0),
            DamagePart("true", 50.0),
        )


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
        def resolve_per_proc(ctx, ability):
            from src.calculator.champions.slotlib import extract_named

            return extract_named(
                ability,
                "Bonus Magic Damage",
                ctx.level,
                ctx.stats,
                ctx.target,
            )

        defaults = {"per_proc": resolve_per_proc, "dmg_type": "magic"}
        defaults.update(params)
        parse = build_parser({"P": proc_damage(**defaults)}, "TestChamp")
        return parse(self._proc_champ(), 9, 0.0, champion_options=options)

    def test_per_proc_scales_with_level_and_count_multiplies(self) -> None:
        """Level 9 per-proc = 50; 3 procs -> 150 total under "passive"."""
        results = self._parse(options={"passive_procs": 3})
        assert results["passive"] == {
            "name": "Mark",
            "damage_type": "magic",
            "total_raw": 150.0,
            "parts": (DamagePart("magic", 50.0),),
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
        results = self._parse(per_proc=lambda _ctx, _ability: 0.0)
        assert results == {}

    def test_physical_type_carries_physical_part(self) -> None:
        results = self._parse(dmg_type="physical", options={"passive_procs": 2})
        assert results["passive"]["parts"] == (DamagePart("physical", 50.0),)

    def test_name_override_preserves_custom_proc_label(self) -> None:
        results = self._parse(name="Custom Proc")
        assert results["passive"]["name"] == "Custom Proc"


class TestSharedEntryAndModifierPrimitives:
    """Small shared units used by multiple champion-local parsers."""

    def test_ability_on_hit_entry_preserves_payload_and_optional_cooldown(
        self,
    ) -> None:
        payload = {"name": "Nested", "damage_per_hit": 42.0}
        without_cd = ability_on_hit_entry("Ability", 3, "magic", payload)
        with_cd = ability_on_hit_entry("Ability", 3, "magic", payload, 8.0)

        assert without_cd == {
            "name": "Ability",
            "rank": 3,
            "damage_type": "magic",
            "total_raw": 0.0,
            "parts": (),
            "on_hit": payload,
        }
        assert with_cd["cooldown"] == 8.0
        assert with_cd["on_hit"] is payload

    def test_named_leveling_and_modifier_override_share_one_walk(self) -> None:
        ability = _ability(
            leveling=[
                {
                    "attribute": "Odd Damage",
                    "modifiers": [
                        {"values": [10.0], "units": ["×"]},
                        {"values": [2.0], "units": ["special"]},
                    ],
                }
            ]
        )
        leveling = find_named_leveling(ability, "Odd Damage")

        assert leveling is not None
        assert (
            sum_modifiers(
                leveling,
                1,
                modifier_override=lambda unit, value: (
                    value if unit == "×" else value * 5 if unit == "special" else None
                ),
            )
            == 20.0
        )


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


class TestStatBuff:
    """BUFF-phase stat steroid entries (Vayne/Aatrox/Ambessa R pattern)."""

    def _steroid_champ(self, extra_leveling: list | None = None) -> dict:
        leveling = [
            _leveling("Bonus Attack Damage", [35, 50, 65]),
        ] + (extra_leveling or [])
        return _champion(
            R=[
                _ability(
                    name="Steroid R",
                    damage_type=None,
                    cooldowns=[100, 85, 70],
                    leveling=leveling,
                )
            ],
            Q=[
                _ability(
                    name="Q",
                    damage_type="PHYSICAL_DAMAGE",
                    cooldowns=[6, 5, 4, 3, 2],
                    leveling=[
                        {
                            "attribute": "Physical Damage",
                            "modifiers": [
                                {
                                    "values": [50, 75, 100, 125, 150],
                                    "units": ["% AD"] * 5,
                                },
                            ],
                        },
                    ],
                )
            ],
        )

    def test_flat_mode_entry_shape(self) -> None:
        """The entry is a zero-damage damage_entry plus the stat_buff.

        Its zero is ``STRUCTURAL_ZERO``: a steroid with no damage attribute
        deals none by declaration, which is a different fact from a formula
        that ran and produced nothing (D-24).
        """
        parse = build_parser(
            {"R": stat_buff("Bonus Attack Damage", "bonus_attack_damage")},
            "TestChamp",
        )
        results = parse(self._steroid_champ(), 16, 0.0)  # R rank 3
        assert results["R"] == {
            "name": "Steroid R",
            "rank": 3,
            "cooldown": 70.0,
            "damage_type": "physical",
            "total_raw": 0.0,
            "parts": (DamagePart("physical", 0.0),),
            "stat_buff": {"bonus_attack_damage": 65.0},
        }
        # The policy is metadata, not identity: equality above cannot see
        # it, so the declaration is asserted on its own.
        assert results["R"]["parts"][0].zero_policy is STEROID_ZERO

    def test_apply_to_mutates_stats_for_damage_slots(self) -> None:
        """apply_to feeds the buff into ctx.stats before DAMAGE slots."""
        parse = build_parser(
            {
                "Q": simple_damage(attr="Physical Damage", dmg_type="physical"),
                "R": stat_buff(
                    "Bonus Attack Damage",
                    "bonus_attack_damage",
                    apply_to=("attack_damage", "bonus_attack_damage"),
                ),
            },
            "TestChamp",
        )
        results = parse(
            self._steroid_champ(),
            16,
            0.0,
            champion_stats={"attack_damage": 100.0, "bonus_attack_damage": 0.0},
        )
        # Q rank 5 = 150% AD of (100 + 65) buffed AD.
        assert results["Q"]["total_raw"] == pytest.approx(1.5 * 165.0)

    def test_percent_of_mode(self) -> None:
        """Aatrox R: the leveling value is a % of another stat."""
        champ = self._steroid_champ()
        parse = build_parser(
            {
                "R": stat_buff(
                    "Bonus Attack Damage",
                    "bonus_attack_damage",
                    mode="percent_of",
                    percent_of="attack_damage",
                )
            },
            "TestChamp",
        )
        results = parse(champ, 6, 0.0, champion_stats={"attack_damage": 150.0})
        # R rank 1 = 35% of 150 AD.
        assert results["R"]["stat_buff"]["bonus_attack_damage"] == pytest.approx(52.5)

    def test_damage_attr_gives_active_damage(self) -> None:
        """Ambessa R: the buff entry also carries active cast damage."""
        champ = self._steroid_champ(
            extra_leveling=[_leveling("Physical Damage", [150, 250, 350])],
        )
        parse = build_parser(
            {
                "R": stat_buff(
                    "Bonus Attack Damage",
                    "bonus_attack_damage",
                    damage_attr="Physical Damage",
                )
            },
            "TestChamp",
        )
        results = parse(champ, 11, 0.0)  # R rank 2
        assert results["R"]["parts"] == (DamagePart("physical", 250.0),)
        assert results["R"]["total_raw"] == 250.0
        assert results["R"]["stat_buff"] == {"bonus_attack_damage": 50.0}

    def test_couples_publishes_value_for_dependent_slot(self) -> None:
        """Vayne pattern: R publishes a leveling value into ctx.stats."""
        champ = self._steroid_champ(
            extra_leveling=[
                _leveling("Tumble Cooldown Reduction", [30, 40, 50], ["%"] * 3),
            ],
        )

        def q_reads_stash(ctx):
            return {"name": "Q", "total_raw": ctx.stats.get("r_q_cdr", 0.0)}

        parse = build_parser(
            {
                "Q": q_reads_stash,
                "R": stat_buff(
                    "Bonus Attack Damage",
                    "bonus_attack_damage",
                    couples=("r_q_cdr", "Tumble Cooldown Reduction"),
                ),
            },
            "TestChamp",
        )
        results = parse(champ, 16, 0.0)  # R rank 3
        assert results["Q"]["total_raw"] == 50.0

    def test_rank_gate_skips_buff_and_stash(self) -> None:
        """Unranked R: no entry, no stats mutation, no stash."""
        champ = self._steroid_champ()

        seen: dict[str, float] = {}

        def q_reads_stats(ctx):
            seen["r_q_cdr"] = ctx.stats.get("r_q_cdr", 0.0)
            return {
                "name": "Q",
                "total_raw": ctx.stats.get("attack_damage", 0.0),
            }

        parse = build_parser(
            {
                "Q": q_reads_stats,
                "R": stat_buff(
                    "Bonus Attack Damage",
                    "bonus_attack_damage",
                    apply_to=("attack_damage",),
                    couples=("r_q_cdr", "Tumble Cooldown Reduction"),
                ),
            },
            "TestChamp",
        )
        results = parse(
            champ,
            16,
            0.0,
            ability_ranks={"R": 0},
            champion_stats={"attack_damage": 100.0},
        )
        assert "R" not in results
        assert results["Q"]["total_raw"] == 100.0
        assert seen["r_q_cdr"] == 0.0

    def test_unknown_mode_rejected_at_factory_time(self) -> None:
        with pytest.raises(ValueError, match="sideways"):
            stat_buff("Bonus Attack Damage", "bonus_attack_damage", mode="sideways")


class TestByOption:
    """Option-dispatched slot parsing (sweetspot / condemn_wall pattern)."""

    def _toggle_champ(self) -> dict:
        return _champion(
            E=[
                _ability(
                    name="Toggle E",
                    damage_type="PHYSICAL_DAMAGE",
                    cooldowns=[20, 18, 16, 14, 12],
                    leveling=[
                        _leveling("Physical Damage", [50, 85, 120, 155, 190]),
                        _leveling("Total Physical Damage", [125, 212, 300, 387, 475]),
                    ],
                )
            ],
        )

    def _toggle_parser(self):
        return by_option(
            "wall",
            {
                True: simple_damage(attr="Total Physical Damage", dmg_type="physical"),
                False: simple_damage(attr="Physical Damage", dmg_type="physical"),
            },
            default=True,
        )

    def test_option_selects_case(self) -> None:
        parse = build_parser({"E": self._toggle_parser()}, "TestChamp")
        on = parse(self._toggle_champ(), 18, 0.0, champion_options={"wall": True})
        off = parse(self._toggle_champ(), 18, 0.0, champion_options={"wall": False})
        assert on["E"]["total_raw"] == 475.0
        assert off["E"]["total_raw"] == 190.0

    def test_default_when_option_absent(self) -> None:
        parse = build_parser({"E": self._toggle_parser()}, "TestChamp")
        results = parse(self._toggle_champ(), 18, 0.0)
        assert results["E"]["total_raw"] == 475.0

    def test_truthy_values_normalize_for_bool_cases(self) -> None:
        """A truthy non-bool option value still hits the True case."""
        parse = build_parser({"E": self._toggle_parser()}, "TestChamp")
        results = parse(self._toggle_champ(), 18, 0.0, champion_options={"wall": 1})
        assert results["E"]["total_raw"] == 475.0

    def test_case_phases_must_agree(self) -> None:
        """Cases in different engine phases are a build-time error."""
        buffed = stat_buff("Bonus Attack Damage", "bonus_attack_damage")
        with pytest.raises(ValueError, match="phase"):
            by_option("x", {True: buffed, False: simple_damage()}, default=True)

    def test_composite_carries_case_phase(self) -> None:
        """The dispatcher parser inherits its cases' shared phase."""
        buffed = by_option(
            "x",
            {True: stat_buff("Bonus Attack Damage", "bonus_attack_damage")},
            default=True,
        )
        assert buffed.phase == BUFF


class TestPctHealthPerHit:
    """Shared %max-health on-hit math (Kog'Maw W / Vayne W / Aatrox P)."""

    def _on_hit_ability(
        self,
        ap_modifier: bool = False,
        floor: bool = False,
    ) -> dict:
        """W-shaped ability: %maxHP base, optional per-100-AP and floor."""
        modifiers = [
            {
                "values": [3, 3.75, 4.5, 5.25, 6],
                "units": ["% of target's maximum health"] * 5,
            },
        ]
        if ap_modifier:
            modifiers.append(
                {"values": [1.5] * 5, "units": ["% per 100 AP"] * 5},
            )
        leveling = [{"attribute": "Bonus Magic Damage", "modifiers": modifiers}]
        if floor:
            leveling.append(
                _leveling("Minimum Bonus Damage", [50, 65, 80, 95, 110]),
            )
        return {"name": "W", "effects": [{"leveling": leveling}]}

    def test_base_percent_of_target_max_health(self) -> None:
        """Rank 3: 4.5% of 2000 = 90 per hit."""
        damage = pct_health_per_hit(
            self._on_hit_ability(),
            "Bonus Magic Damage",
            3,
            _default_target(target_max_health=2000.0),
        )
        assert damage == pytest.approx(90.0)

    def test_ap_ratio_per_100_adds_percent(self) -> None:
        """Kog'Maw W: rank 3 + 80 AP at 1.5%/100AP = (4.5 + 1.2)% of 2000."""
        damage = pct_health_per_hit(
            self._on_hit_ability(ap_modifier=True),
            "Bonus Magic Damage",
            3,
            _default_target(target_max_health=2000.0),
            ap=80.0,
            ap_ratio_per_100=True,
        )
        assert damage == pytest.approx(114.0)

    def test_floor_attr_applies_minimum(self) -> None:
        """Vayne-W floor: 3% of 500 = 15 < 50 minimum -> 50."""
        damage = pct_health_per_hit(
            self._on_hit_ability(floor=True),
            "Bonus Magic Damage",
            1,
            _default_target(target_max_health=500.0),
            floor_attr="Minimum Bonus Damage",
        )
        assert damage == pytest.approx(50.0)

    def test_floor_not_hit_when_percent_higher(self) -> None:
        """Rank 5: 6% of 2000 = 120 > 110 minimum -> 120."""
        damage = pct_health_per_hit(
            self._on_hit_ability(floor=True),
            "Bonus Magic Damage",
            5,
            _default_target(target_max_health=2000.0),
            floor_attr="Minimum Bonus Damage",
        )
        assert damage == pytest.approx(120.0)

    def test_stacks_required_divides_per_proc(self) -> None:
        """Vayne-W stacks: one 120-damage proc across 3 hits = 40/hit."""
        damage = pct_health_per_hit(
            self._on_hit_ability(),
            "Bonus Magic Damage",
            5,
            _default_target(target_max_health=2000.0),
            stacks_required=3,
        )
        assert damage == pytest.approx(40.0)

    def test_missing_attribute_returns_none(self) -> None:
        """An absent attribute means "not this mechanic" — caller drops."""
        damage = pct_health_per_hit(
            self._on_hit_ability(),
            "No Such Attribute",
            3,
            _default_target(),
        )
        assert damage is None

    def test_no_target_gives_zero_damage(self) -> None:
        """Attribute present but no target stats -> 0.0 (entry still emitted)."""
        damage = pct_health_per_hit(
            self._on_hit_ability(),
            "Bonus Magic Damage",
            3,
            None,
        )
        assert damage == 0.0


# ---------------------------------------------------------------------------
# Entry-key validation
# ---------------------------------------------------------------------------


class TestEntryKeyValidation:
    """A slot parser emitting an unknown entry key fails loudly."""

    def test_unknown_key_raises_with_champion_slot_and_key(self) -> None:
        def bad_parser(_ctx):
            return {"name": "Oops", "parts": (), "r2_mn": 1.0}

        parse = build_parser({"Q": bad_parser}, "TestChamp")
        with pytest.raises(ValueError, match=r"TestChamp.*Q.*r2_mn"):
            parse(_champion(), 9, 0.0)

    def test_known_keys_pass(self) -> None:
        def good_parser(_ctx):
            return {
                "name": "Fine",
                "rank": 1,
                "cooldown": 5.0,
                "damage_type": "magic",
                "total_raw": 10.0,
                "parts": (DamagePart("magic", 10.0),),
            }

        parse = build_parser({"Q": good_parser}, "TestChamp")
        assert "Q" in parse(_champion(), 9, 0.0)

    def test_unknown_target_debuff_key_raises(self) -> None:
        """The rule-5 failure mode one level down: a typo'd shred key
        would silently reduce nothing."""

        def bad_parser(_ctx):
            return {
                "name": "Shred",
                "parts": (),
                "target_debuff": {"mr_reduction_flatt": 12.0},
            }

        parse = build_parser({"Q": bad_parser}, "TestChamp")
        with pytest.raises(ValueError, match=r"target_debuff.*mr_reduction_flatt"):
            parse(_champion(), 9, 0.0)

    def test_known_target_debuff_keys_pass(self) -> None:
        def good_parser(_ctx):
            return {
                "name": "Shred",
                "parts": (),
                "target_debuff": {
                    "armor_reduction_flat": 12.0,
                    "mr_reduction_flat": 12.0,
                    "stacks": 4,
                },
            }

        parse = build_parser({"Q": good_parser}, "TestChamp")
        assert "Q" in parse(_champion(), 9, 0.0)


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

    def test_synthetic_slot_key_maps_to_itself(self) -> None:
        """Every non-P slot key IS its results key — a synthetic "Q2"
        recast slot (Ambessa) needs no engine extension."""
        container = _ability(
            name="Q1",
            damage_type="PHYSICAL_DAMAGE",
            cooldowns=[9, 8, 7, 6, 5],
            leveling=[_leveling("Physical Damage", [50, 60, 70, 80, 90])],
        )
        recast = _ability(
            name="Q2",
            damage_type="PHYSICAL_DAMAGE",
            leveling=[_leveling("Physical Damage", [80, 95, 110, 125, 140])],
        )
        champ = _champion(Q=[container, recast])
        parse = build_parser(
            {
                "Q": simple_damage(attr="Physical Damage", dmg_type="physical"),
                "Q2": simple_damage(
                    attr="Physical Damage",
                    dmg_type="physical",
                    source=("Q", 1),
                    cooldown_from=("Q", 0),
                ),
            },
            "TestChamp",
        )
        results = parse(champ, 9, 0.0)  # Q rank 5
        assert results["Q2"]["name"] == "Q2"
        assert results["Q2"]["total_raw"] == 140.0
        # The recast shares its container's rank and cooldown.
        assert results["Q2"]["rank"] == results["Q"]["rank"] == 5
        assert results["Q2"]["cooldown"] == results["Q"]["cooldown"] == 5.0

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


# ---------------------------------------------------------------------------
# Cast-time stamping
# ---------------------------------------------------------------------------


class TestCastTimeStamping:
    """The engine stamps castable entries with the slot JSON's castTime,
    so timed fights can budget cast lockout without every slot parser
    (module or generic) plumbing it through by hand."""

    @staticmethod
    def _castable_slot(**extra):
        def slot_fn(_ctx):
            entry = damage_entry("Zap", 1, 5.0, 100.0, "magic")
            entry.update(extra)
            return entry

        slot_fn.phase = DAMAGE
        return slot_fn

    @staticmethod
    def _q_champion(cast_time) -> dict:
        ability = _ability(name="Zap")
        if cast_time is not None:
            ability["castTime"] = cast_time
        return _champion(Q=[ability])

    def test_castable_entry_gets_cast_time(self) -> None:
        parse = build_parser({"Q": self._castable_slot()}, "TestChamp")
        results = parse(self._q_champion("0.4"), 9, 0.0)
        assert results["Q"]["cast_time"] == pytest.approx(0.4)

    def test_instant_cast_omits_the_key(self) -> None:
        """castTime "none" (or absent) stamps nothing — entries stay lean
        and champions without cast-time data keep legacy behavior."""
        parse = build_parser({"Q": self._castable_slot()}, "TestChamp")
        assert "cast_time" not in parse(self._q_champion("none"), 9, 0.0)["Q"]
        assert "cast_time" not in parse(self._q_champion(None), 9, 0.0)["Q"]

    def test_module_supplied_cast_time_wins(self) -> None:
        parse = build_parser({"Q": self._castable_slot(cast_time=0.9)}, "TestChamp")
        results = parse(self._q_champion("0.4"), 9, 0.0)
        assert results["Q"]["cast_time"] == pytest.approx(0.9)

    def test_proc_entry_without_cooldown_not_stamped(self) -> None:
        """Non-castable entries (proc rows have no cooldown) are never
        stamped — they occupy no time on the cast timeline."""

        def proc_slot(_ctx):
            return {
                "name": "Proc",
                "damage_type": "magic",
                "total_raw": 10.0,
                "parts": (DamagePart("magic", 10.0),),
                "proc_count": 1,
            }

        proc_slot.phase = DAMAGE
        parse = build_parser({"P": proc_slot}, "TestChamp")
        ability = _ability(name="Innate")
        ability["castTime"] = "0.25"
        results = parse(_champion(P=[ability]), 9, 0.0)
        assert "cast_time" not in results["passive"]


# ---------------------------------------------------------------------------
# cc_kind event contract
# ---------------------------------------------------------------------------


class TestCcEventContract:
    """cc_kind is a trigger contract: the marked cast must reach the event
    ledger (else CC-triggered item passives silently never fire — the
    Imperial Mandate/Pantheon failure class), and the kind must belong to
    the known vocabulary (a typo must never author a no-op stun)."""

    @staticmethod
    def _cc_slot(**entry_overrides):
        def parse(ctx):
            entry = damage_entry("Stunner", 3, 8.0, 100.0, "physical")
            entry["parts"] = (DamagePart("physical", 100.0, cc_kind="stun"),)
            entry.update(entry_overrides)
            return entry

        parse.phase = DAMAGE
        return parse

    def test_cc_part_without_event_path_is_rejected(self) -> None:
        parse = build_parser({"Q": self._cc_slot()}, "TestChamp")
        with pytest.raises(ValueError, match="event ledger"):
            parse(_champion(Q=[_ability()]), 9, 0.0)

    def test_certified_single_hit_cc_part_is_accepted(self) -> None:
        parse = build_parser(
            {"Q": self._cc_slot(event_order_certified="single_hit")}, "TestChamp"
        )
        results = parse(_champion(Q=[_ability()]), 9, 0.0)
        assert results["Q"]["parts"][0].cc_kind == "stun"

    def test_authored_time_offset_cc_part_is_accepted(self) -> None:
        def parse_slot(ctx):
            entry = damage_entry("Delayed Stun", 3, 8.0, 100.0, "physical")
            entry["parts"] = (
                DamagePart("physical", 100.0, cc_kind="stun", time_offset=0.6),
            )
            return entry

        parse_slot.phase = DAMAGE
        parse = build_parser({"Q": parse_slot}, "TestChamp")
        results = parse(_champion(Q=[_ability()]), 9, 0.0)
        assert results["Q"]["parts"][0].cc_kind == "stun"

    def test_unknown_cc_kind_is_rejected(self) -> None:
        def parse_slot(ctx):
            entry = damage_entry("Typo Stun", 3, 8.0, 100.0, "physical")
            entry["parts"] = (DamagePart("physical", 100.0, cc_kind="stunn"),)
            entry["event_order_certified"] = "single_hit"
            return entry

        parse_slot.phase = DAMAGE
        parse = build_parser({"Q": parse_slot}, "TestChamp")
        with pytest.raises(ValueError, match="stunn"):
            parse(_champion(Q=[_ability()]), 9, 0.0)

    def test_reviewed_no_cc_result_needs_no_event_path(self) -> None:
        """cc_kind='none' is a reviewed no-CC statement, not a trigger."""

        def parse_slot(ctx):
            entry = damage_entry("Plain Nuke", 3, 8.0, 100.0, "physical")
            entry["parts"] = (DamagePart("physical", 100.0, cc_kind="none"),)
            return entry

        parse_slot.phase = DAMAGE
        parse = build_parser({"Q": parse_slot}, "TestChamp")
        results = parse(_champion(Q=[_ability()]), 9, 0.0)
        assert results["Q"]["parts"][0].cc_kind == "none"

    def test_damage_entry_cc_kind_certifies_single_hit(self) -> None:
        entry = damage_entry("X", 1, 5.0, 100.0, "magic", cc_kind="stun")
        assert entry["event_order_certified"] == "single_hit"
        assert entry["parts"][0].cc_kind == "stun"

    def test_damage_entry_rejects_mixed_cc(self) -> None:
        with pytest.raises(ValueError, match="mixed"):
            damage_entry("X", 1, 5.0, 100.0, "mixed", cc_kind="stun")
